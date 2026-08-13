# Plan — Effect documentation and fixture consistency

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Effect purity soundness](2026-08-13-effect-purity-soundness.md)

## Objective

Implement the recommendations from the effect-purity change review: make the
contextual-typing boundary normative, align verification and handler-row plan
language, turn the larger clock-handler sample into an executable fixture, and
describe the prototype's actual repository status.

## Work

- [x] Specify where expected types flow and how effectful lambdas obtain rows.
- [x] Correct the effect plan's continuation-row completion criterion.
- [x] Label the purity counterexample as schematic and record the fresh GBNF
  result.
- [x] Promote the documented clock handler to a canonical example fixture.
- [x] Validate that fixture through round-trip and effect-directed tests.
- [x] Update the prototype example catalog and root repository status.
- [x] Run and record all verification steps.

## Verification

```sh
task prototype:test
cd prototype && python3 -m py_compile *.py
cd ..
LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
```

## Completion criteria

- The documented larger example has one authoritative canonical fixture.
- Both surface round-trip and effect-directed validation cover that fixture.
- The specification makes synthesis-only effectful lambdas deliberately
  invalid and names the contexts that propagate expected types.
- Plan verification claims and handler-row language match observed behavior.
- Repository status distinguishes the working prototype from unimplemented
  runtime, store, solver, and evidence layers.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

```text
Ran 65 tests in 0.052s

OK
GBNF PASS: 12 valid cases accepted; 11 invalid cases rejected
TODO.md: clean
```

Python compilation and `git diff --check` also exited successfully.
