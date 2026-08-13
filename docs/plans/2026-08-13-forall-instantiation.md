# Plan — First-order `forall` instantiation

**Date:** 2026-08-13
**Status:** Implemented; PASS
**Depends on:** [Type-directed `fix` and `ref`](2026-08-13-fix-ref-typing.md)
(the `ref` typing rule this needs), [Bootstrap corpus](2026-08-13-bootstrap-corpus.md)
(`corpus/maybe/mapPoly`)
**Closes:** SPEC.md §3.1.3's stated future rule — instantiation was written
down as intended behavior but never implemented, so a quantified `ref` could
be written, hashed, and stored, but never called except through a monomorphic
wrapper.

## Objective

Give the match layer a rule for eliminating `forall`: when a term is
**checked** against a concrete expected type and synthesizes `forall^p T`, do
not fail the plain structural comparison outright — instantiate `T` by
first-order matching against the expected type first. This is the only
change; no node is added, and synthesis position is untouched.

## Rule

Stated normatively in `SPEC.md` §3.1.3; restated here as the implementation
contract.

1. **Trigger.** In `MatchChecker.check`, the existing fallback (`actual =
   synth(...); if actual != expected: fail`) gets one more branch: if
   `actual != expected` **and** `actual[0] == 6` (a `forall`), attempt
   instantiation before failing. In practice the only term that synthesizes a
   `forall` type is a `ref` whose resolved type is quantified — no other
   `synth` case produces a `forall`-tagged type — so this covers exactly
   §3.1.3's "quantified reference" without a `ref`-specific branch.
2. **Peel the prefix.** Strip the leading `forall^p` off `actual` to get `p`
   (the count) and `T` (the body), mirroring `scope.forall_prefix` but over an
   already-resolved type value rather than a definition under validation.
3. **Match.** Walk `T` and the expected type `E` structurally in lockstep.
   Where `T` has `tyvar i` with `i < p`, bind it to the corresponding subtree
   of `E`. Every other node tag must agree between `T` and `E`, recursing into
   substructure (`data` arguments, `fn` domain/codomain, `refine` base).
   Failure anywhere — an unbound `tyvar`, the same `tyvar` bound to two
   different subtrees, or a structural tag disagreement — is a path-aware
   `TypeDirectionError`, not a silent skip.
4. **Rows are out of scope.** A `fn` type's row is compared via the existing
   `_closed_row` helper on both sides — instantiation substitutes types, not
   rows, so a row variable anywhere in `T` or `E` fails explicitly with the
   layer's existing "row-polymorphic effect checking is not implemented"
   message rather than being matched away.
5. **Result equals `E` by construction.** Once every `tyvar` is bound,
   substituting the bindings back into `T` and comparing to `E` is asserted
   (defense in depth — matching already guarantees this position-by-position,
   this is not a second source of truth).
6. **Polymorphic caller.** `E` may itself contain `tyvar` nodes — the
   *caller's own* `forall`-bound variables, still in scope at the checking
   site. This layer never substitutes a definition's own type variables
   (§2.3.1: they stay opaque atoms under structural equality), so those nodes
   are never inspected as *pattern* binding sites (only `T`'s own `i < p`
   nodes are); they simply appear as ordinary, opaque subtrees on the `E`
   side and bind like any other concrete type. No special case is needed —
   this falls out of the matcher treating `E` purely as data.
7. **Synthesis position stays uninstantiated.** `synth` is unchanged: a
   quantified reference used as, say, an application's function still
   synthesizes `forall^p T` verbatim. A polymorphic definition is therefore
   still called only through a monomorphic wrapper or a typed `let` at each
   use site — the rule adds an elimination for checking position only.
8. **Nested `forall` past the prefix cannot occur for a legitimately checked
   resolver result.** `scope.forall_prefix` already refuses a definition type
   whose remainder (after stripping the leading `forall`s) contains another
   `forall` — v0.1 is rank-1 only. Any `reference_type` resolver that returns
   the *stored* type of an actual checked definition therefore never presents
   a `T` containing a nested `forall`. The matcher still guards this
   defensively (a malformed resolver is possible in principle) with an
   explicit refusal rather than mishandling it silently — this is not an
   open case the spec leaves unsettled, it is foreclosed by scope validation
   upstream.

## Deliberate boundary

- Refinement predicates (`refine T φ`, tag 3) match structurally on `T` but
  require the predicate term `φ` to already be identical on both sides —
  `φ` contains term variables, not declaration-type nodes, and this layer has
  no term-level substitution machinery to reconcile a predicate that differs.
  Not exercised by the bootstrap corpus (arithmetic-free by construction).
- Row polymorphism remains unimplemented, as stated above and in §3.1.2
  already.
- Only checking position instantiates. This matches §3.1.3's stated rule
  exactly; a synthesis-position elimination would be a different, unstated
  feature.

## Work

- [x] Update `SPEC.md` §3.1.3: replace "Instantiation is not available in
      v0.1" with the implemented rule, the checking-position-only boundary,
      and the polymorphic-caller case.
- [x] Implement `_instantiate`, `_match_type`, `_substitute_type` in
      `prototype/matches.py`, and the one-branch hook in `check`'s fallback.
      Additive only — `_check_fix` and the fix rules are untouched (owned by
      a concurrent change).
- [x] Add `prototype/test_instantiation.py`: monomorphic instantiation via a
      typed `let`, the `corpus/maybe/mapPoly`-at-`I64` proof definition
      (resolver keyed by the fixture's pinned identity, validated through
      scope, references, and the match layer), a polymorphic caller
      instantiating at its own type variable, inconsistent-binding
      rejection, unbound-`tyvar` rejection, structural-mismatch rejection,
      and row-variable refusal.
- [x] Wire `test_instantiation` into `task prototype:test`.
- [x] Add rows to `docs/plans/README.md` and `prototype/README.md`; update
      the corpus paragraph in `prototype/README.md` that described mapPoly's
      instantiation gap as open.
- [x] Check `test_corpus.ExpressivenessLimitTest` for a pinned
      "writable but not instantiable" residue to re-pin — none found; the
      only related pinned test
      (`test_recursion_and_stored_references_stop_at_the_structural_tier`)
      fails on a missing resolver entirely, not on instantiation, and is
      unaffected by this change.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

## Completion criteria

- `corpus/maybe/mapPoly` called at `I64` through a typed `let` type-checks
  end to end (scope, references, match layer).
- A polymorphic caller can instantiate a quantified reference at its own
  type variable.
- Inconsistent bindings, unbound type variables, structural mismatches, and
  row variables in a quantified type all fail with path-aware errors, not
  silently.
- Synthesis position is unaffected: a quantified reference in application
  position still synthesizes its quantified type verbatim (existing
  `test_fix_ref.py` coverage, unmodified, still passes).
- No existing test's behavior changes except where this rule closes a gap
  that used to be a plain "type mismatch".

## Recorded verification

Run on 2026-08-13.

### 1. `task prototype:test`

The new `test_instantiation.InstantiationTest` cases, from the full `-v` run
(the other 214 pre-existing tests are unchanged and pass; full listing omitted
for length):

```text
test_inconsistent_binding_is_rejected (test_instantiation.InstantiationTest.test_inconsistent_binding_is_rejected) ... ok
test_mappoly_instantiated_at_i64_is_a_proof_definition (test_instantiation.InstantiationTest.test_mappoly_instantiated_at_i64_is_a_proof_definition) ... ok
test_monomorphic_instantiation_via_typed_let (test_instantiation.InstantiationTest.test_monomorphic_instantiation_via_typed_let) ... ok
test_polymorphic_caller_instantiates_with_its_own_type_variable (test_instantiation.InstantiationTest.test_polymorphic_caller_instantiates_with_its_own_type_variable) ... ok
test_row_variable_in_a_quantified_type_is_refused_explicitly (test_instantiation.InstantiationTest.test_row_variable_in_a_quantified_type_is_refused_explicitly) ... ok
test_structural_mismatch_is_rejected (test_instantiation.InstantiationTest.test_structural_mismatch_is_rejected) ... ok
test_unbound_type_variable_is_rejected (test_instantiation.InstantiationTest.test_unbound_type_variable_is_rejected) ... ok

----------------------------------------------------------------------
Ran 221 tests in 0.109s

OK
```

**PASS** — all 221 tests (214 pre-existing + 7 new) pass; no pre-existing test
changed behavior.

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
(no output)
```

**PASS**
