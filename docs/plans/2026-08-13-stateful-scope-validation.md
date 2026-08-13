# Plan — Stateful scope validation

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Canonical parser hardening](2026-08-12-canonical-parser-hardening.md)

## Objective

Define Loom's previously implicit binder conventions and implement the first
stateful validity layer: rejection of out-of-scope term and type de Bruijn
indices. Keep this layer separate from syntax transcoding, because handler
operation arity comes from referenced ability definitions rather than the local
term node.

## Semantic decisions

- A definition begins with term depth 0 and type depth 0.
- `lam` adds one term binder in its body.
- `let` checks its bound term at the current depth and adds one binder only in
  its body.
- A `match` arm adds its encoded `binder-count` binders in constructor-field
  order, with the last field at index 0.
- A refinement predicate adds its refined value as term index 0.
- A hole constraint adds the prospective hole value as term index 0.
- `forall` adds one type binder throughout its body.
- A row variable is checked against the surrounding type-binder depth.
- `fix` adds the recursive value as term index 0 in its body; its declared type
  and termination measure are checked outside that binder. Recursive functions
  therefore normally use a `lam` body, where argument index 0 and self index 1.
- A handler return clause adds the handled computation's result as term index 0.
- A handler operation clause obtains the operation parameter count from the
  referenced ability definition. It binds the continuation at index 0 and the
  operation parameters below it, with the last parameter nearest the
  continuation.
- Types may contain refinement predicates that refer to the surrounding term
  context. Ordinary function codomains do not implicitly bind their domain
  value; dependent arrows are not introduced by this amendment.

## Implementation

- [x] Add the binder conventions to `SPEC.md` as normative scope rules.
- [x] Add `prototype/scope.py` with structured path-aware errors.
- [x] Validate term indices, type indices, refinement predicates, rows, match
  arms, handlers, recursion, and hole constraints.
- [x] Represent ability lookup as an injected resolver returning operation
  parameter counts; reject missing abilities or operation indices explicitly.
- [x] Add `validate_source` as a parse-plus-scope convenience function without
  changing `transcode_source`'s store-independent syntax/identity behavior.
- [x] Test every binder-producing construct, boundary index, nested shadowing,
  unresolved ability, and invalid operation index.
- [x] Update the prototype README and TODO record.

## Verification

```sh
cd prototype
python3 -m unittest test_roundtrip test_scope -v
python3 -m py_compile *.py
cd ..
LOOM_GBNF_VALIDATOR=/path/to/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
```

## Completion criteria

- Every binder-producing node has one normative depth rule.
- Every term/type index is checked at its precise occurrence.
- Handler scope checking cannot guess operation arity.
- Scope failures identify the AST path, index, and available depth.
- Existing canonical bytes and hashes remain unchanged.
- Parser, scope, and production GBNF suites all pass.

## Recorded verification

Run on 2026-08-13:

**Result: PASS**

```text
Ran 23 tests in 0.020s

OK
```

The production GBNF harness also remained green with 11 valid cases accepted
and 11 invalid cases rejected. `task todo:lint`, Python compilation, and
`git diff --check` passed.
