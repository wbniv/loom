# Plan — Bootstrap corpus tranche 2: the recursive slice

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Bootstrap corpus for prior starvation](2026-08-13-bootstrap-corpus.md)
(R4 termination policy, R7 manifest/dependency conventions),
[Type-directed `fix` and `ref`](2026-08-13-fix-ref-typing.md),
[Measure selection for curried recursion](2026-08-13-measure-selection.md),
[Extern object encoding](2026-08-13-extern-object-encoding.md), `SPEC.md` §2.5
(totality, the measure and position field), §3.1.5 (`fix`/`ref` typing), §5.1.3
(extern definitions)

## Objective

Finish tranche 2 of the bootstrap corpus. `list/foldRight` was built as the
exemplar by the fix/ref-typing and measure-selection plans; this plan
transpiles the six remaining recursive list definitions — `list/append`,
`list/reverse`, `list/map`, `list/foldLeft`, `list/concat`, `list/flatMap` —
to tier `checked`, verifies the `list/size` assumed-base wiring the exemplar
established is complete rather than duplicating it, and records the
integration result (full-suite count, grammar cases, pinned identities).

No visible surface (fixtures and normative text only), so this plan carries no
mockups.

## Rules

### The six fixtures, in dependency order

Every `fix` below measures `(ref #List.size)` (the assumed-base extern R4
pinned) and takes no `div` — no recursion in this tranche descends on two
arguments at once. All six join `list/foldRight` in `corpus_registry.MANIFEST`
in the order listed, which is also their dependency order (`SPEC.md` §5.2, R7):
`list/concat` and `list/flatMap` `ref` `list/append`, so `list/append` precedes
them.

| Definition | Type (at `I64`) | Own `fix`? | Measure position | Depends on |
|---|---|---|---|---|
| `list/append` | `List I64 -> List I64 -> List I64` | yes | 0 (first list) | — |
| `list/reverse` | `List I64 -> List I64` | yes | 1 (accumulator form) | — |
| `list/map` | `(I64 -> I64) -> List I64 -> List I64` | yes | 1 (list is 2nd arg) | — |
| `list/foldLeft` | `(I64 -> I64 -> I64) -> I64 -> List I64 -> I64` | yes | 2 (list is 3rd arg) | — |
| `list/concat` | `List I64 -> List I64 -> List I64` | **no** | — | `list/append` (`ref`) |
| `list/flatMap` | `(I64 -> List I64) -> List I64 -> List I64` | yes | 1 (list is 2nd arg) | `list/append` (`ref`, in the Cons arm) |

`list/append` reuses the exact shape `test_corpus.
ExpressivenessLimitTest.test_a_recursive_definition_reaches_the_checked_tier`
already pinned as a *test* of the recursive-`fix` capability — this plan is
what turns that shape into the corpus's actual fixture.

`list/reverse` is written as an efficient accumulator-passing recursion rather
than the naive `append`-based one, to keep it independent of `list/append`:
its `fix` has type `List I64 -> List I64 -> List I64` (accumulator first, then
the list being consumed), decreasing on the *second* argument (position 1),
and the top-level definition applies that `fix` to `Nil` — `(app (fix …)
(con #List 0 ()))` — so the stored definition's own type is the plain
single-argument `List I64 -> List I64` a caller expects. This is the same
"helper with a seeded accumulator, applied once" pattern `SPEC.md` §2.5's
measure-per-position rule was built to make statable at all: the measure
still reads only the second (list) argument, never the accumulator.

`list/foldLeft` is `list/foldRight`'s accumulator case: the curried spine and
measure position are identical to `list/foldRight` (position 2), but the
recursive call's *second* argument changes each step (`rec f (f z x) xs'`)
instead of staying fixed, and the combining application nests the opposite
way (`f` applied to the accumulator and the head, before recursing, rather
than the head and the recursive result after). Getting the de Bruijn indices
right for that (`rec=5, f=4, z=3, l=2, x=1, xs=0` inside the Cons arm,
mirroring the comment already on `test_fix_ref.MeasureSelectionTest`) was
mechanical once `list/foldRight`'s own indices were understood, and the
checker is the judge either way — `typecheck.py` was not touched to make
either fixture pass.

### The dependency chain: `list/concat` and `list/flatMap`

These are the first manifest entries whose `ref` resolves to another manifest
definition rather than only to an extern in the assumed base — exercising
`corpus_registry.reference_type()`'s `definition_types.DefinitionTypeRegistry`
path for the first time with a real dependency, not just as a defensive
fallback.

`list/concat` has **no `fix` of its own**: `\xs ys. append xs ys`, a direct
`ref` into `list/append` applied to both arguments. It reaches `checked`
through ordinary application typing (`MatchChecker.synth`'s `tag == 4` case
resolving the `ref`'s type), never touching `_check_fix` at all — there is no
measure for it to state because there is no new recursion to measure.

`list/flatMap` **does** have its own `fix` (decreasing on the list argument,
position 1, same as `list/map`), but its Cons arm delegates the per-element
concatenation to `(ref #list/append)` rather than re-deriving structural list
concatenation inline: `Nil -> Nil; Cons x xs' -> append (f x) (flatMap f
xs')`. This is the tranche's clearest instance of "compose an earlier
tranche-2 definition by `ref`" — the recursion is genuinely new, but one of
its steps is not.

### `list/size` wiring: verified, not duplicated

The task brief called out `list/size` as "assumed-base wiring... may already
be complete; verify rather than duplicate." It is. `corpus_registry._EXTERNS`
already pins `List.size : List I64 -> I64` as an uninterpreted §5.1.3 extern
(`corpus_registry.EXTERN_HASHES["List.size"]`), `corpus_registry.registry()`
already registers it, and `corpus_registry.reference_type()` already resolves
`ref`s to it through the same `DeclarationRegistry.reference_type` path a
`checked`-tier `fix` measure needs — all of which `list/foldRight` already
exercised. Nothing new was added for `list/size` itself; the six new fixtures
below simply use the existing wiring, the same way `list/foldRight` did.

### The monomorphic boundary, hit and recorded

`list/concat` was first drafted as the standard cross-language meaning of
"concat" — flatten a `List (List I64)` — before that draft was abandoned. A
`fix` recursing over `List (List I64)` needs a measure of type
`List (List I64) -> I64`, but the pinned `List.size` extern's type is fixed at
`List I64 -> I64` (monomorphic, per `SPEC.md` §5.1.3's extern shape rules — no
second, differently-typed `List.size` exists, and an extern's type may not be
polymorphic at all: `test_externs.ExternShapeTest.
test_polymorphic_externs_are_rejected` pins that refusal). Composing a
flattening `concat` from the already-built `list/foldRight`/`list/map` has the
same problem one level earlier: both are monomorphic at `I64` throughout (the
combining function, accumulator, and result are all fixed at `I64`), so
neither can be `ref`'d at a `List I64`-accumulator or `List (List I64)`-element
instantiation without a generic (`forall`-quantified) version — which
`SPEC.md` §3.1.3's instantiation rule and §2.5's measure selection have each
landed independently, but never together inside one recursive `fix`, and nail-
ing that combination down is not this tranche's job. `list/concat` was
redesigned to the binary two-list form instead (`List I64 -> List I64 ->
List I64`, delegating to `list/append`), which sidesteps the boundary rather
than crossing it. Recorded as residue 5 in the bootstrap-corpus plan, not
solved here, and no `typecheck.py`, `declarations.py`, `scope.py`,
`transcode.py`, or `loom.gbnf` change was made or attempted while finding it.

## Work

- [x] Build `list/append` (own `fix`, position 0, no `ref` dependency) and pin
  its identity.
- [x] Build `list/reverse` (own `fix`, accumulator form, position 1, no `ref`
  dependency) and pin its identity.
- [x] Build `list/map` (own `fix`, position 1, no `ref` dependency) and pin its
  identity.
- [x] Build `list/foldLeft` (own `fix`, position 2, no `ref` dependency) and
  pin its identity.
- [x] Build `list/concat` (no `fix`; `ref`s `list/append`) and pin its
  identity.
- [x] Build `list/flatMap` (own `fix`, position 1; `ref`s `list/append` in its
  Cons arm) and pin its identity.
- [x] Verify `list/size`'s assumed-base wiring is already complete; add
  nothing new for it.
- [x] Add the six manifest entries to `corpus_registry.MANIFEST` in dependency
  order, after `list/foldRight`.
- [x] Confirm `test_corpus.py`'s existing classes cover the six new entries
  automatically via `MANIFEST` iteration (tier enforcement, canonicity,
  purity, few-shot pairs, dependency-order, provenance) — no new test class
  needed.
- [x] Add two of the new fixtures (`list/append`, `list/flatMap`) to
  `validate_gbnf.py`'s `EXTRA_VALID`, since the corpus directory is not
  globbed there the way `examples/` is, and these are the first surfaces to
  exercise a `ref` nested inside a `fix` body rather than only as a measure.
- [x] Update `prototype/README.md`'s corpus narrative paragraph.
- [x] Add this plan's row to `docs/plans/README.md`.
- [x] Re-declare tranche 2 as built in `docs/plans/2026-08-13-bootstrap-corpus.md`
  (strike-through style) and record the monomorphic-boundary finding as a new
  residue item there.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
LOOM_GBNF_VALIDATOR=/path/to/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
```

## Completion criteria

- Six new fixtures exist in `prototype/corpus/`, each canonical, identity-pinned,
  and reaching tier `checked` — verified by `test_corpus.py`'s existing
  manifest-iterating test classes with no test-class changes needed.
- `list/concat` and `list/flatMap` each `ref` `list/append`, and
  `test_corpus.CorpusFixtureTest.test_manifest_declares_dependencies_before_use`
  passes with the manifest in the stated dependency order.
- `list/size`'s wiring is confirmed complete rather than re-specified.
- The monomorphic boundary found while designing `list/concat` is recorded as
  residue in the bootstrap-corpus plan, not silently worked around.
- `typecheck.py`, `declarations.py`, `scope.py`, `transcode.py`, and
  `loom.gbnf` are all untouched.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

1. `task prototype:test`

    ```text
    ----------------------------------------------------------------------
    Ran 237 tests in 0.286s

    OK
    ```

    PASS (237 of 237 tests OK — 221 pre-existing plus 16 `test_corpus` tests,
    seven of which iterate `corpus_registry.MANIFEST` and therefore covered the
    six new entries automatically with no test-class changes; confirmed by
    running `test_corpus` alone, also 16/16 `ok`).

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test`

    ```text
    GBNF PASS: 17 valid cases accepted; 16 invalid cases rejected
    ```

    PASS (15 valid cases before this plan; 17 after — the two `list/append`
    and `list/flatMap` surfaces added to `validate_gbnf.py`'s `EXTRA_VALID`).

4. `task todo:lint`

    ```text
    TODO.md: clean
    exit=0
    ```

    PASS.

5. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.

### Pinned identities added

| Name path | Fixture | Tier | Identity (SHA-256) |
|---|---|---|---|
| `corpus/list/append` | `list_append_i64.loom.sexpr` | `checked` | `32f5d833f0b7c42ea8252e7ec8810657e9e9d132d395d30a7259e683bc31f791` |
| `corpus/list/reverse` | `list_reverse_i64.loom.sexpr` | `checked` | `9d677953e4471fb4b1c80accfd4f2cb48d59b08073a9e431f74bd1f0020e249b` |
| `corpus/list/map` | `list_map_i64.loom.sexpr` | `checked` | `617903dc2f185adc90f658f482357c9961001882d693cab0c4701ae518e21ade` |
| `corpus/list/foldLeft` | `list_fold_left_i64.loom.sexpr` | `checked` | `7c880749df1f488a834cc9b2352d0d064dba904e2c7cfd83af762cee2d3b665f` |
| `corpus/list/concat` | `list_concat_i64.loom.sexpr` | `checked` | `9bdf05836448d24d7c66f987cbf6de55e7a7bfa303c4636db9b259958c9d93a1` |
| `corpus/list/flatMap` | `list_flat_map_i64.loom.sexpr` | `checked` | `72fe5503bbf99fd187a83b5fd5cca4f6df2c5747fcd0d934457e7c96f6f4e6ed` |

The bootstrap corpus now carries 13 fixtures total (6 from tranche 1's built
subset, plus `list/foldRight`, plus these six), all at tier `checked`.
