# Plan — Builtin ability reference prelude

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Declaration objects and reference validation](2026-08-13-declaration-objects-reference-validation.md)

## Objective

Replace the eight placeholder builtin ability names in `SPEC.md` with canonical
ability declarations, stable operation indices, precise boundary semantics, and
pinned SHA-256 identities usable by the registry and generation mask.

## Design

The v0.1 core has no `Result`, path, socket, process, or foreign-value data types.
The prelude therefore avoids pretending those abstractions already exist:

- obvious scalar operations use base types directly;
- fallible OS/network/process/FFI operations exchange opaque `Bytes` envelopes;
- envelope formats are runtime ABI contracts and are not interpreted by the
  core calculus;
- `div` has no performable operations and serves only as the effect-row marker
  for recursion whose termination is not proved.

Operation order is semantic because terms use numeric indices. Names are
reference metadata and are pinned alongside declarations in `prototype/prelude.py`.

## Work

- [x] Specify all eight declarations and operation indices in `SPEC.md`.
- [x] Define edge behavior for negative clock/rand scalar inputs.
- [x] Implement immutable canonical prelude declarations and derived hashes.
- [x] Ensure structurally identical abilities remain nominally distinct by
  embedding domain-separated 32-byte keys in declaration identity.
- [x] Pin literal hash hex values in tests so accidental ABI changes fail loudly.
- [x] Provide a preloaded declaration registry and name/hash lookup helpers.
- [x] Validate representative builtin `perform`, `handle`, effect-row, and
  capability uses through the existing reference checker.
- [x] Remove the completed builtin-signature TODO and record the milestone.

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

- Every builtin name resolves to one pinned 32-byte hash.
- Every operation index, parameter list, and result type is normative.
- The pinned declarations pass canonical declaration validation.
- Registry-backed definitions can use every builtin without fixture hashes.
- All tests pass and the §4.4 definition identity remains unchanged.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

```text
Ran 41 tests in 0.033s

OK
GBNF PASS: 11 valid cases accepted; 11 invalid cases rejected
TODO.md: clean
```

Python compilation and `git diff --check` also exited successfully.
