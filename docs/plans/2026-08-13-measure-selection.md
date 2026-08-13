# Plan — Measure selection for curried recursion

**Date:** 2026-08-13
**Status:** Implemented; verified
**Depends on:** [Type-directed `fix` and `ref`](2026-08-13-fix-ref-typing.md),
[Bootstrap corpus](2026-08-13-bootstrap-corpus.md)
**Closes:** the deliberate boundary recorded in the fix/ref plan — "curried
recursion whose decreasing argument is not the first cannot state its measure" —
and unblocks tranche 2's `list/foldRight` and `list/foldLeft`.

## Objective

§2.5 requires every `fix` to carry a measure, and §3.1.3 checks that measure
against `fn D () I64` where `D` is the annotation's **first** domain. A curried
recursion whose decreasing argument is not the first — `foldRight : (a → b → b)
→ b → List a → b` — therefore has no way to state `(ref #List.size)`, and every
such definition is capped at the `structural` tier.

Settle how a measure names its argument, and carry the decision through the
spec, the prototype, the grammar, and the corpus.

**Visible surface:** the change alters one line of the canonical S-expression
emission surface (`(fix T k measure body)`). There is no UI, rendered page, or
TUI pane, so this plan carries no mockup bundle.

## Decision

**Add a position field to the `fix` node.** The node becomes

```text
[10, T, k, measure, body]
```

where `k` counts arrows along `T`'s curried spine from 0 and selects the
decreasing argument. `T` must expose at least `k + 1` arrows; the measure is
checked against `fn D_k () I64`. `k = 0` is today's rule exactly.

Canonical surface: `(fix <type> <position> <measure> <body>)`.

`k` is placed **before** `measure`, not after it. §8.1 emits a definition as a
pre-order traversal, so the field that determines the measure's goal type must
precede the measure for §8.2's type-directed pruning to have anything to prune
with. A trailing `k` would force the mask to emit the measure against an unknown
goal and validate afterwards.

### Why this and not the alternatives

**Rejected: measure over the whole argument list (`fn D₀ () (fn D₁ () (… I64)))`).**
Attractive because it needs no node change and is strictly more expressive —
a multi-argument measure covers recursions that descend on two arguments at once.
It breaks on spine ambiguity with real consequences: `T = fn A () (fn B () C)`
and "a one-argument function returning a function" are the same node, so the rule
must fix the measure's arity from `T`'s *full* arrow spine. A recursion at
`List I64 → (I64 → I64)` that descends on the list and returns a closure would
then need a two-argument measure and a recursive call saturated to two arguments,
which the natural body never produces — the rule makes a case that works today
unprovable. It also loses the property that `(ref #List.size)` is usable as a
measure *directly*, which is the corpus's R4 primitive and the reason measures
are content-addressed at all.

**Rejected: keep the node and require the decreasing argument first.** This is
not merely an ergonomic tax; the naive form is not even expressible, because the
argument order is part of the definition's public type and reordering it produces
a different definition. The workable form is *internal*: hoist loop-invariant
arguments outside the `fix`, permute the rest so the decreasing one is first, and
eta-wrap to restore the public type. That costs nothing in mask or identity, and
it is genuinely tempting — but:

- It defeats the corpus's stated correctness criterion. With three or more
  remaining arguments the internal permutation is a free choice, so the same
  Unison source transpiles to different bytes depending on which permutation the
  transpiler picks. §4.1's identity is intensional, so those are different
  definitions carrying separate evidence. "A transpiler is correct exactly when
  it reproduces these bytes" stops being checkable.
- It hides the termination story (P2). With `k`, "this recursion descends on
  argument 2, and here is its measure" is one integer read at the node. Under
  permutation it must be reconstructed by inverting an eta-wrapper.
- It degrades §8.3's narrowing loop (P4). A wrong `k` is a one-token error the
  checker localizes to `fix.measure`; a wrong permutation is a whole-term error.
- The tax is permanent and lands on the transpiler, the generating agent, and
  every reader, to avoid a cost that is one uint field in one tag.

**Rejected: a separate `measure` object kind or a side table.** Termination is a
property of the recursion, not of the namespace; §4.3's object kinds are closed
for the same reason §2's tags are, and pulling `k` out of the term would make two
`fix` nodes with different decreasing arguments hash identically.

### Deliberately not adopted: multi-argument measures

`k` selects one argument, and the measure sees only that argument. A recursion
that genuinely needs `size xs + size ys` — `merge` on two sorted lists, where
neither argument decreases alone — must take `div` in v0.1. This is recorded as a
pinned negative test rather than left implicit.

The widening path costs no second node change: a multi-argument rule would keep
`k` as the field it already is (the index of the last argument the measure reads)
and only widen the expected measure type from `D_k → I64` to
`D₀ → … → D_k → I64`. That is a rule change requiring a version bump for stored
definitions, not another mask change.

## Mask-cost accounting (§8.2)

| Axis | Cost |
|---|---|
| New term tags | **0.** §2's "every tag added is mask complexity paid forever" is untouched — tag 10 keeps its meaning. |
| New type tags | 0. |
| New token classes | **0.** `uint` is already emitted in five term positions (`var` index, `con`/`perform` operation index, match arm constructor index and binder count, handler operation index). The mask's uint state is reused verbatim. |
| Node arity | One row of §2.1's table goes from 4 fields to 5. The mask's per-tag field count is a table lookup either way. |
| Grammar | One production gains one `uint` terminal: `"(fix " type " " uint " " term " " term ")"`. |
| Type-directed pruning | **Improves.** With `k` decoded before the measure, the pruner knows the measure's exact goal type `fn D_k () I64` at the moment it starts emitting the measure. Under the trailing-field or whole-spine alternatives it does not. |
| Identity churn | **Zero today.** No `fix` node is stored anywhere: the §4.4 golden is `id` at `I64`, the five `examples/` fixtures contain no `fix`, and every corpus fixture on disk is tranche 1 (non-recursive). Every occurrence is in test source. The same change after tranche 2 lands would re-hash every recursive definition in the store; the window is open now and closes with the first stored recursion. |

## Rules

Normative in `SPEC.md` §2.1, §2.3.1, §2.5, §3.1.3; restated here as the
implementation contract.

1. **Shape.** `[10, T, k, measure, body]`; `k` a canonical nonnegative integer.
   `k` binds nothing, so §2.3.1's depths are unchanged.
2. **Spine.** `T` must be `fn D₀ r₀ (fn D₁ r₁ (… fn D_k r_k C))` — at least
   `k + 1` arrows, each a `fn` node. A shorter spine is refused with the position
   and the spine length in the message, not silently clamped.
3. **Measure.** Checked at the current environment, without the recursive binder,
   against `fn D_k () I64`. `I64` because v0.1 has no natural base type; empty row
   because an effectful measure is meaningless to the oracle. Both unchanged from
   the fix/ref plan.
4. **Walked rows are untouched.** `r₀ … r_{k-1}` may be non-empty: reaching
   argument `k` may perform effects, which changes nothing about how many times
   the recursion runs. Only the measure's own row must be empty.
5. **Body.** Unchanged: checked against `T` with the recursive value at term
   index 0, under the unchanged ambient allowance.
6. **`terminates` obligation (§2.5, oracle, not this layer).** The measure is
   nonnegative on every argument it is applied to, and at every occurrence of the
   recursive value inside `body` applied to at least `k + 1` arguments, the
   measure of that occurrence's argument `k` is strictly less than the measure of
   the enclosing invocation's argument `k`. An occurrence applied to fewer than
   `k + 1` arguments leaves nothing to compare, so the obligation is unprovable
   there and the definition must take `div`.
7. **Layering.** `scope.py` validates that `k` is a nonnegative integer — the
   same shape check it already applies to a match arm's binder count — and
   `matches.py` validates it against `T`'s spine, exactly as `matches.py`
   validates a binder count against the constructor's field count. Neither layer
   guesses.

## Corpus follow-through

`DeclarationRegistry.reference_type` already resolves an extern hash to the type
a `ref` to it has, so wiring the corpus's resolver is three lines, not thirty:
`corpus_registry.reference_type()` returns that bound method, and the tier test
passes it to `matches.validate_source`. With the resolver and `k` both in place,
`list/foldRight` at `I64` reaches tier `checked` with `(ref #List.size)` stated
directly as its measure at `k = 2`.

## Work

- [x] `SPEC.md` §2.1 node shape, §2.3.1 binder bullet, §2.5 totality (selection
      plus the restated `terminates` obligation), §3.1.3 typing rule.
- [x] Confirm §8.2 carries no node-arity table — it does not; no edit needed.
- [x] `transcode.py`: parse and render the position field.
- [x] `loom.gbnf`: one `uint` in the `fix` production.
- [x] `scope.py`: arity 5, position shape check, shifted field indices.
- [x] `references.py`: shifted field indices.
- [x] `matches.py`: `_check_fix` walks the spine to `D_k`.
- [x] `corpus_registry.py`: `reference_type()` and the `list/foldRight` manifest
      entry; `corpus/list_fold_right_i64.loom.sexpr`.
- [x] Tests: `test_fix_ref.py` (updated pins plus position cases),
      `test_scope.py`, `test_matches.py`, `test_roundtrip.py` tag coverage,
      `test_refinements.py` fixture, `validate_gbnf.py`, `test_corpus.py`
      (resolver wiring; the lifted limit replaced by the multi-argument-measure
      limit it exposes).
- [x] Rows in `docs/plans/README.md` and `prototype/README.md`.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
```

Note: `task` resolves the Taskfile relative to the repository root, which from a
nested `.claude/worktrees/…` checkout is the worktree. The recorded `todo:lint`
run below invokes the same linter by absolute path against this worktree's
`TODO.md`; from the main checkout the `task` form is equivalent.

## Completion criteria

- A curried recursion states its decreasing argument, and `foldRight` at `I64`
  typechecks with `(ref #List.size)` as its measure.
- A position past the annotation's spine, and a measure over the wrong domain,
  both fail with path-aware errors.
- The §4.4 golden identity is unchanged (it contains no `fix`).
- The grammar accepts the new surface and still rejects the old one.
- The multi-argument-measure limit the decision does *not* lift is pinned by a
  test rather than left as prose.

## Recorded verification

Run on 2026-08-13. **Result: PASS.**

### 1. `task prototype:test`

```text
test_fix_measure_position_binds_nothing_and_must_be_a_nonnegative_integer (test_scope.ScopeTest...) ... ok
test_a_measure_over_the_third_argument_typechecks (test_fix_ref.MeasureSelectionTest...) ... ok
test_a_measure_over_two_arguments_is_not_expressible (test_fix_ref.MeasureSelectionTest...) ... ok
test_a_position_past_the_curried_spine_is_refused (test_fix_ref.MeasureSelectionTest...) ... ok
test_rows_walked_past_by_the_selector_are_untouched (test_fix_ref.MeasureSelectionTest...) ... ok
test_the_measure_domain_follows_the_position (test_fix_ref.MeasureSelectionTest...) ... ok
test_the_same_recursion_cannot_state_its_measure_at_position_zero (test_fix_ref.MeasureSelectionTest...) ... ok
test_a_stored_reference_measures_a_non_initial_argument (test_fix_ref.ReferenceTypingTest...) ... ok
test_every_fixture_reaches_its_declared_validation_tier (test_corpus.CorpusFixtureTest...) ... ok
test_a_measure_cannot_read_more_than_one_argument (test_corpus.ExpressivenessLimitTest...) ... ok
test_a_recursive_definition_reaches_the_checked_tier (test_corpus.ExpressivenessLimitTest...) ... ok

----------------------------------------------------------------------
Ran 213 tests in 0.101s

OK
```

PASS. 213 of 213, no failures or errors; selected lines shown. Nine of those are
new — one scope case, six measure-selection cases, one stored-measure case, and
one corpus case replacing the limit this change lifts. The 204-test baseline was
confirmed by running the same eleven modules from `git archive HEAD prototype`:

```text
Ran 204 tests in 0.079s

OK
```

The **before** state is preserved as a test rather than described:
`test_the_same_recursion_cannot_state_its_measure_at_position_zero` is exactly
the old rule applied to `foldRight` — the measure checked against the *first*
domain — and it still fails, with
`definition.term.measure.…: lambda parameter annotation differs from expected domain`.
`test_a_measure_over_the_third_argument_typechecks` is the same definition with
`k = 2`, and it passes.

### 2. `python3 -m py_compile prototype/*.py`

```text
py_compile exit=0
```

PASS (no output; exit 0).

### 3. `LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test`

```text
GBNF PASS: 13 valid cases accepted; 13 invalid cases rejected
```

PASS. The valid set gained the `k = 0` and `k = 1` surfaces; the invalid set
gained the pre-position `fix` surface and a negative position, so the grammar is
pinned in both directions across the shape change.

### 4. `task todo:lint` — run as `python3 ~/python-tui-lib/scripts/todo-lint.py TODO.md` (see the note above)

```text
TODO.md: clean
exit=0
```

PASS.

### 5. `git diff --check`

```text
exit=0
```

PASS (no output; exit 0).

### 6. §4.4 golden identity unchanged

```text
$ python3 transcode.py examples/01_id.loom.sexpr
ir     = [0, [2, [0, 2], [], [0, 2]], [3, [0, 2], [0, 0]]]
bytes  = 83008402820002808200028303820002820000  (19 bytes)
hash   = #76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605
```

PASS — byte-for-byte the §4.4 worked example. The golden contains no `fix`, so
the node-shape change cannot reach it.

### 7. `list/foldRight` at the `checked` tier

The new fixture `prototype/corpus/list_fold_right_i64.loom.sexpr` is 288 bytes,
identity `#2509a18eb5e81726042a2cef5cd5444955a71c9dce18221ff8a49d0f93c82893`,
pinned in `corpus_registry.MANIFEST` and enforced in both directions by
`test_every_fixture_reaches_its_declared_validation_tier`. Its measure is
`(ref 0x4bd80df0…)` — the assumed-base `List.size` extern — stated directly at
`k = 2`, with no eta-reordering and no wrapper definition.
