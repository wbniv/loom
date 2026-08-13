# Plan — Declaration objects and reference validation

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Stateful scope validation](2026-08-13-stateful-scope-validation.md)

## Objective

Give data and ability hashes canonical referents, then validate every nominal
data/ability use that can be checked without full typing: object existence,
kind, index bounds, argument arity, and handler clause arity.

## Canonical schema

- Object kind `4`: data declaration `[4, parameter-count, constructors]`, where
  each constructor is an array of field types.
- Object kind `5`: ability declaration `[5, operations]`, where each operation
  is `[parameter-types, result-type]`.
- Constructor and operation names remain metadata. Their array positions are
  the canonical indices used by terms.
- Declaration types use the ordinary type IR plus declaration-local tag `7`,
  `self`: `[7, [type-arguments]]`. It is legal only inside the data declaration
  being hashed and avoids an impossible hash cycle for recursive data.
- Data declaration type variables are scoped by `parameter-count`; ability
  declarations are monomorphic in v0.1 because ability references and
  capability types carry no type arguments.
- Empty constructor and operation lists are legal at the encoding layer.
  Inhabitance and usefulness are later static-semantic concerns.

## Work

- [x] Amend `SPEC.md` with object kinds, schemas, identity, and local `self`.
- [x] Implement declaration validation, canonical CBOR encoding, and hashing.
- [x] Implement an in-memory content-addressed declaration registry that checks
  supplied keys against declaration hashes.
- [x] Validate nominal types and effect rows resolve to the expected kind.
- [x] Validate `con`, `perform`, and `handle` indices and arities.
- [x] Reuse ability operation parameter counts for handler scope validation.
- [x] Add positive, negative, recursive-data, hash-integrity, and wrong-kind
  tests.
- [x] Preserve parser/identity and GBNF results.

## Deliberate boundary

This layer does not prove argument or result types, match constructor indices or
binder counts, match exhaustiveness, duplicate match arms, handler
exhaustiveness, or effect-row correctness. A `match` node carries no data hash,
so even its local constructor bounds require inference of the scrutinee type;
those checks belong to the typechecker. This layer also does not invent the builtin prelude signatures;
that existing TODO remains open and becomes implementable using the ability
object schema defined here.

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

- Recursive data declarations hash without self-referential bytes.
- Registry keys are verified from canonical declaration bytes.
- Every local nominal reference fails closed on missing or wrong-kind objects.
- Constructor/operation indices and explicit argument arities are checked.
- Handler scope obtains arity from the same verified ability declaration.
- All verification steps record PASS without changing the §4.4 golden hash.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

```text
Ran 34 tests in 0.028s

OK
GBNF PASS: 11 valid cases accepted; 11 invalid cases rejected
TODO.md: clean
```

Python compilation and `git diff --check` also exited successfully.
