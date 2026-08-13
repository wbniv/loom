# Plan — Nominal match validation

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Builtin ability reference prelude](2026-08-13-builtin-ability-prelude.md)

## Objective

Close the validation gap deliberately left by registry-only checking: infer the
nominal data type of a `match` scrutinee, instantiate its constructor field
types, verify constructor indices and binder counts, and require exactly one arm
for every constructor.

This is the first type-directed checker, not a claim of a complete Loom
typechecker.

## Rules

- Type equality at this layer is structural equality of canonical type IR.
- Data type arguments instantiate declaration `tyvar` occurrences; local
  declaration `self` becomes the referenced nominal data type with instantiated
  arguments.
- Constructor applications synthesize their nominal result type after their
  explicit argument count is registry-validated.
- Variables synthesize types from a de Bruijn type environment.
- Literals, lambdas, applications, lets, and holes synthesize enough type
  information to locate nested matches.
- A match scrutinee must synthesize a nominal `data` type. The checker rejects an
  unknown or non-data scrutinee rather than guessing.
- Each constructor index must occur exactly once, be in range, and declare the
  exact constructor field count as its binder count.
- Constructor fields enter an arm environment in signature order, with the last
  field at term index 0, matching `SPEC.md` §2.3.1.
- Every arm body must synthesize the same result type.

## Deliberate boundary

This layer does not yet type abilities/handlers, `fix`, refinements, or arbitrary
applications requiring polymorphic instantiation. It traverses only expressions
whose type can be determined by the rules above and raises a path-aware
`TypeDirectionError` otherwise. No unsupported node is silently accepted.

## Work

- [x] Add normative nominal match rules to `SPEC.md`.
- [x] Expose immutable declaration constructor field types from the registry.
- [x] Implement type-parameter and recursive-`self` substitution.
- [x] Implement path-aware synthesis and checking for the supported core.
- [x] Validate match bounds, duplicate/missing arms, binder counts, field
  environments, and common result types.
- [x] Test parameterized recursive data and nested matches.
- [x] Preserve all parser, scope, reference, prelude, and GBNF results.

## Verification

```sh
task prototype:test
cd prototype && python3 -m py_compile *.py
cd ..
LOOM_GBNF_VALIDATOR=/path/to/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
```

## Completion criteria

- Match validity is derived from the verified declaration behind the scrutinee
  type, never from arm claims alone.
- Constructor field types and binder order are instantiated correctly.
- Missing, duplicate, out-of-range, and wrong-binder-count arms fail clearly.
- Existing golden identities remain unchanged and every verification step PASSes.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

```text
Ran 50 tests in 0.036s

OK
GBNF PASS: 11 valid cases accepted; 11 invalid cases rejected
TODO.md: clean
```

Python compilation and `git diff --check` also exited successfully.
