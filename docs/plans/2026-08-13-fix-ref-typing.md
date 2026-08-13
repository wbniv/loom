# Plan — Type-directed `fix` and `ref`

**Date:** 2026-08-13
**Status:** Implemented; verified with one recorded cross-file failure (see
Verification step 1)
**Depends on:** [Nominal match validation](2026-08-13-nominal-match-validation.md),
[Effect-directed typing](2026-08-13-effect-directed-typing.md)
**Closes:** [Bootstrap corpus](2026-08-13-bootstrap-corpus.md) finding 3 — `fix`
(tag 10) and `ref` (tag 1) pass scope and reference validation but had no
match-layer typing rule, capping every recursive corpus definition at the
`structural` tier.

## Objective

Give the type-directed layer a rule for the last two nodes tranche 2 needs, so
that recursive definitions (`List.size`, `List.append`, `List.map`, `foldr`) can
be *typed* rather than merely parsed and scope-checked. This is still not a
complete typechecker, and it deliberately discharges no termination evidence.

## Rules

Stated normatively in `SPEC.md` §3.1.5; restated here as the implementation
contract.

### `fix T measure body` (tag 10)

1. **Annotation.** Checked against expected type `E`, `T` must equal `E` under
   the layer's structural type equality. In synthesis position `fix`
   synthesizes `T` (deep-copied).
2. **`T` must be a `fn D row C`.** §2.5's measure maps the recursive *argument*
   to a number, so a recursive value with no argument has nothing to measure.
   A non-`fn` `T` is refused explicitly — `fix at a non-function type is not
   implemented in the nominal match layer` — rather than guessing a rule. The
   row must be closed, consistent with §3.1.2's row-polymorphism limit.
3. **Measure.** Checked at the *current* environment — without the recursive
   binder, per §2.3.1 — against `fn D () I64`.
   - **`I64`, not a refined natural.** v0.1 has no natural base type (§2.2);
     structural type equality would otherwise force every measure to spell one
     exact refinement node. Non-negativity is part of the oracle's obligation,
     not of this rule.
   - **Empty row.** A measure that is itself effectful is meaningless to a
     termination oracle.
   - **Rejected: deferring measure typing entirely** with an unsupported error.
     That would leave the measure the one unchecked subterm of an otherwise
     typed node, and the corpus's `(ref #List.size)` measure — the whole point
     of R4 — would never be validated against the function it measures.
4. **Body.** Checked against `T` with the recursive value at term index 0, under
   the **unchanged** ambient allowance. Forming a recursive function value is
   itself pure; because `T` is a `fn` type, a `lam` body immediately re-anchors
   the allowance to `row` via §3.1.2's checked-lambda rule. There is no separate
   `fix` effect rule.
5. **`terminates` is not discharged here.** This layer establishes that the term
   has type `T`. Whether the measure strictly decreases is oracle evidence
   (§2.5, §6.2), and §3.2.1 already states that no v0.1 `terminates` obligation
   can reach A3 by any route.

### `ref h` (tag 1)

6. **Injected resolver, never a guess.** The prototype has no store of typed
   definitions, and `DeclarationRegistry` holds data/ability declarations, not
   definitions. `MatchChecker` therefore takes an optional
   `reference_type: ReferenceTypeResolver | None = None` constructor argument —
   the same shape `scope.py` uses for its ability-arity resolver — and
   `validate_source` passes it through. **No def-object store is invented.**
7. **Resolution.** With a resolver, `ref h` synthesizes the resolved type,
   deep-copied so the caller's mapping cannot be mutated through the checker.
   Checking compares that type structurally, via the existing synth fallthrough
   — `ref` needs no branch in `check`.
8. **Refusal.** With no resolver, or a hash the resolver does not resolve
   (`KeyError`/`LookupError`/`DeclarationError`/a non-type result), the layer
   raises a path-aware `TypeDirectionError` — exactly as §2.3.1 requires a
   checker to report an unresolved ability operation instead of guessing an
   arity.
9. **Effects.** A `ref` whose type carries a non-empty row interacts with the
   ambient row exactly as any other `fn`-typed value: the row is checked at the
   application site by the existing rule. No special casing.

## Deliberate boundary

- ~~**Curried recursion whose decreasing argument is not the first cannot state
  its measure.** Rule 3 fixes the measure's domain to `T`'s domain, so
  `foldRight : (a → b → b) → b → List a → b` cannot use `(ref #List.size)`.
  That is a §2.5 gap — the spec gives no way to name a non-initial argument as
  the decreasing one — not a checker limitation, and it is recorded in §3.1.5
  rather than papered over. `list/size`, `list/append`, `list/reverse`, and
  `list/map` are unaffected.~~ Closed 2026‑08‑13 by the
  [measure-selection plan](2026-08-13-measure-selection.md): the `fix` node
  gained a position field, so rule 3 now reads "against `fn D_k () I64`".
- Mutual recursion remains out of scope: `fix` binds one value (corpus plan
  R‑list, "local mutual recursion is dropped").
- Row-polymorphic `fix` annotations are refused with the existing closed-row
  error.

## Work

- [x] Add `SPEC.md` §3.1.5 stating both rules and the non-discharge of
      `terminates`.
- [x] Thread a `reference_type` resolver through `MatchChecker` and
      `matches.validate_source`.
- [x] Implement `_check_fix` (shared by check and synth) and
      `_resolve_reference`.
- [x] Test recursive binder types, measure shape, annotation rows, effects
      under `fix`, and resolver positives/negatives in `prototype/test_fix_ref.py`.
- [x] Wire `test_fix_ref` into `task prototype:test`; add README rows.
- [x] Re-declare the corpus tier assertion that this layer intentionally
      invalidates (owned elsewhere — see Verification step 1). Done at merge, and
      re-declared again by the measure-selection plan once the corpus gained a
      `ref` resolver.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

## Completion criteria

- A structurally recursive definition typechecks with the recursive value at
  index 0 and constructor binders in §2.3.1 order.
- Wrong annotations, wrong body types, wrong measure shapes, and
  ambient-row violations under `fix` all fail with path-aware errors.
- `ref` resolves through the injected resolver and refuses explicitly without
  one.
- No `terminates` obligation is discharged by the typing layer.

## Recorded verification

Run on 2026-08-13.

### 1. `task prototype:test`

```text
test_fix_annotation_must_equal_the_expected_type ... ok
test_fix_at_a_non_function_type_is_refused ... ok
test_fix_body_cannot_exceed_the_annotation_row ... ok
test_fix_body_checks_under_the_annotation_row ... ok
test_fix_body_is_checked_against_the_annotation ... ok
test_fix_synthesizes_its_annotation_in_application_position ... ok
test_measure_is_checked_without_the_recursive_binder ... ok
test_measure_must_map_the_recursive_argument_to_i64 ... ok
test_recursive_call_arguments_use_the_constructor_binder_types ... ok
test_recursive_fix_binds_the_recursive_value_at_index_zero ... ok
test_terminates_is_not_discharged_by_this_layer ... ok
test_absent_resolver_is_refused_rather_than_guessed ... ok
test_effectful_reference_obeys_the_ambient_row ... ok
test_reference_checks_against_its_resolved_type ... ok
test_reference_serves_as_a_fix_measure ... ok
test_reference_synthesizes_its_resolved_type_in_application_position ... ok
test_reference_type_mismatch_is_reported ... ok
test_resolved_types_are_isolated_copies ... ok
test_resolver_returning_a_non_type_is_refused ... ok
test_unresolved_hash_is_refused ... ok

======================================================================
FAIL: test_recursion_and_stored_references_stop_at_the_structural_tier
(test_corpus.ExpressivenessLimitTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File ".../prototype/test_corpus.py", line 189, in
        test_recursion_and_stored_references_stop_at_the_structural_tier
    self.assertIn("term tag 10", str(caught.exception))
AssertionError: 'term tag 10' not found in 'definition.term.measure: reference
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa is unresolved:
the match layer has no reference-type resolver'

----------------------------------------------------------------------
Ran 175 tests in 0.084s

FAILED (failures=1)
```

**FAIL — and it is the failure the corpus plan designed.** Bootstrap-corpus R6:
"A layer growing a rule for `fix` therefore turns a green test red, forcing the
tier to be re‑declared rather than letting a stale deferral outlive its cause."
All 20 new tests pass and the other 154 are unchanged; the single failure is the
stale *assertion string*, not a stale tier. `fix` is now typed, so the fixture's
deferral cause has moved to the unresolved `(ref #List.size)` measure — tranche 2
remains correctly `structural` until the corpus supplies a reference-type
resolver. `test_corpus.py` and `corpus_registry.py` are owned concurrently and
were deliberately left untouched; the one-line follow-up is to assert the new
refusal (`has no reference-type resolver`) and restate the deferral reason.

### 2. `python3 -m py_compile prototype/*.py`

```text
py_compile OK
```

**PASS**

### 3. `task todo:lint`

```text
TODO.md: clean
```

**PASS**

### 4. `git diff --check`

```text
diff --check clean
```

**PASS**
