# Plan — Effect purity soundness

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Effect-directed typing](2026-08-13-effect-directed-typing.md)

## Objective

Close a confirmed soundness hole in the effect-directed layer: an unannotated
lambda synthesizes a function type with an **empty** effect row while its body
is checked against the **current** ambient allowance. Inside a handler, such a
closure can perform the handled ability, escape through the return clause typed
as pure, and be applied outside any handler — defeating §2.4's central claim
that a type mentioning no ability cannot exercise it.

Accepted counterexample before this fix:

```loom
(def (fn (cap clock) () (fn Unit () I64))
  (lam (cap clock)
    (handle clock
      (lam Unit (perform clock 0 ()))
      ((0 (app (var 0) (lit i64 7))) (1 (app (var 0) (lit unit))))
      (var 0))))
```

Also resolve a three-way disagreement about operation-less abilities: the
effect-typing plan says `div` "cannot be handled", but the checker accepts
`(handle div term () ret)` — the exhaustiveness check is vacuous for zero
operations — and `SPEC.md` says nothing either way.

No visible surface (checker internals and normative spec text), so this plan
carries no mockups.

## Rules

- **Synthesized lambdas are pure.** A lambda synthesized without an expected
  function type has its body checked with the **empty** ambient allowance, and
  its synthesized type carries the empty row. Latent effects are expressible
  only by checking against an annotated `fn domain row codomain`, exactly as
  §3.1.2 already types checked lambdas. This is deliberately conservative: even
  a beta-redex whose surrounding ambient would make the perform safe is
  rejected until it carries a row annotation.
- **Operation-less abilities cannot be handled.** `handle` over an ability that
  declares no operations (`div`) is a type error. Divergence is an effect
  marker discharged by no v0.1 handler; per §2.5 it stays visible in every
  caller's row all the way up.
- **Arm mismatch reporting keys on the error path, not the message prefix.**
  `_check_match` rewraps a checking failure as "arm result type differs" only
  when the failure occurred at the arm body's own path; a mismatch nested
  deeper inside the arm keeps its original path and message.
- **Registry cleanup.** `operation_signature` deep-copies the full ability
  object and then deep-copies the two extracted fields again; resolve the
  object without the first copy.

## Work

- [x] State lambda-synthesis purity and the operation-less `handle` rejection
  normatively in `SPEC.md` §3.1.2.
- [x] Synthesize unannotated lambda bodies under the empty ambient row.
- [x] Reject `handle` over an ability with no operations.
- [x] Key arm-mismatch rewrapping on the arm body path.
- [x] Drop the redundant deep copy in `operation_signature`.
- [x] Regression tests: the escape counterexample, the `div` handler, nested
  arm mismatch attribution, and synthesized-lambda purity.
- [x] Preserve all existing identities, tests, and validation layers.

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

- The escape counterexample above is rejected at the `perform` site.
- `(handle div term () ret)` is rejected with an explicit error.
- A mismatch nested inside a match arm is not mislabeled as an arm-result
  mismatch.
- All prior tests pass unchanged and the golden definition hash is unchanged.

## Recorded verification

Run on 2026-08-13.

**Result: PASS** (GBNF step not run — see note)

1. `task prototype:test`

    ```text
    Ran 64 tests in 0.040s

    OK
    ```

    PASS.

2. `cd prototype && python3 -m py_compile *.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `LOOM_GBNF_VALIDATOR=... task grammar:test`

    ```text
    GBNF validator not found. Pass its path as the first argument or set
    LOOM_GBNF_VALIDATOR for `task grammar:test`.
    ```

    NOT RUN — no `test-gbnf-validator` binary is installed on this machine and
    the repository does not vendor llama.cpp. `loom.gbnf` is untouched by this
    change; the previously recorded grammar PASS stands.

4. `task todo:lint`

    ```text
    TODO.md: clean
    ```

    PASS.

5. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.
