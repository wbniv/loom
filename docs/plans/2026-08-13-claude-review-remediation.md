# Plan — Claude review remediation and tranche integration

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Source:** [Recent Claude work review](../reviews/2026-08-13-claude-recent-work-review.md)

## Objective

Close the foreign-boundary soundness issue, reconcile extern monomorphism with
forall instantiation, replace test-local definition resolution, enforce corpus
provenance, record integrated verification, and give the expanded type checker
an accurate module/error name.

## Work

- [x] Validate extern capabilities per curried arrow in application order.
- [x] Reject nested and too-late capabilities with adversarial tests.
- [x] Retain monomorphic externs under an explicit ABI contract.
- [x] Add immutable scope-validated definition-type snapshots and use them for
  corpus definition references.
- [x] Normalize and test Unison repository/license attribution.
- [x] Rename the expanded checker to `typecheck.py` and `TypingError`, retaining
  a compatibility shim without shadowing Python's `typing` module.
- [x] Run and record integrated tranche verification.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
```

## Completion criteria

- No extern arrow can exercise an ability before receiving its direct cap.
- Extern polymorphism has a current, non-contradictory normative rationale.
- Corpus definition refs resolve from validated immutable type snapshots.
- Every externally derived fixture identifies its repository and license.
- Integrated tests, grammar cases, identities, compilation, and lint pass.

## Recorded integration verification

Run on 2026-08-13 against the combined post-merge tree.

**Result: PASS**

```text
Ran 237 tests in 0.207s

OK
GBNF PASS: 15 valid cases accepted; 16 invalid cases rejected
TODO.md: clean
```

The prototype tests include the §4.4 golden identity, every pinned corpus and
extern identity, manifest consistency, validation tiers, and the new
foreign-boundary adversarial cases. Python compilation and `git diff --check`
also exited successfully.
