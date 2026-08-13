# Plan — Effect-directed typing

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Nominal match validation](2026-08-13-nominal-match-validation.md)

## Objective

Extend the bidirectional prototype checker through Loom's ability boundary:
type operation arguments/results from verified declarations, enforce function
effect rows, require capability values for `perform`, and type handlers that
discharge one ability.

## Rules

- Checking a lambda against `fn domain row codomain` checks its annotation
  against `domain`, binds the parameter, and checks its body against `codomain`
  with `row` as the exact ambient effect allowance.
- A closed definition begins with no ambient effects. Effects become available
  only inside a lambda checked against an annotated function row or inside the
  handled computation of a `handle` node.
- `perform a i args` resolves operation `i`, checks each argument against its
  declared parameter type, and synthesizes the declared result type.
- `perform` additionally requires `a` in the ambient effect row and some
  in-scope value of type `cap a`.
- Checking `handle a term ops ret` against result type `R` checks `term` with
  `a` added to the ambient row and obtains its result type `T`.
- The return clause binds the handled result at index 0 and checks against `R`.
- Each operation clause binds its parameters in signature order and a
  continuation at index 0. The continuation type is
  `fn operation-result ambient-row R`; the clause body checks against `R`.
- A handler must contain each operation exactly once. The empty `div` ability
  cannot be handled with operation clauses and remains an effect marker.
- Closed effect rows only are type-directed in this milestone; a row variable
  produces an explicit unsupported error.

## Work

- [x] Add normative effect/handler typing rules to `SPEC.md`.
- [x] Expose immutable operation parameter/result types from the declaration
  registry.
- [x] Thread ambient effects through bidirectional checking and synthesis.
- [x] Check lambda rows, perform arguments/results, capability presence, and
  handler clauses/continuations/exhaustiveness.
- [x] Cover effects nested in lets, matches, and handlers.
- [x] Preserve all existing identities and validation layers.

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

- Unauthorized, undeclared, or capability-less operations are rejected.
- Operation signatures are read from verified canonical declarations.
- Handlers type their return and every operation clause consistently.
- The continuation receives the unchanged outer ambient row; the handler
  removes only the additional allowance it introduces for the handled term.
- All verification steps PASS and the golden definition hash is unchanged.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

```text
Ran 60 tests in 0.038s

OK
GBNF PASS: 11 valid cases accepted; 11 invalid cases rejected
TODO.md: clean
```

Python compilation and `git diff --check` also exited successfully.
