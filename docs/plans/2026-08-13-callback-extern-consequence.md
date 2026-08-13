# Plan — Callback-extern consequence, stated normatively

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Claude review remediation and tranche integration](2026-08-13-claude-review-remediation.md)

## Objective

[The remediation meta-review](../reviews/2026-08-13-remediation-meta-review.md)
found one piece of residue: §5.1.3's per-arrow capability-honesty rule makes an
extern that invokes an effectful callback unwritable without a direct `cap`
parameter of its own — correct blast-radius behavior, since the callback's
abilities occur during the extern's own call — but that consequence existed
only as emergent behavior of `_check_extern_capability_order`, never stated in
the spec. This plan adds the sentence and pins the accepted/rejected test pair
the finding calls for. It documents existing behavior; `declarations.py` is
unchanged.

## Rules

- The new §5.1.3 text extends the existing capability-honesty paragraph rather
  than restructuring the section, and stays in that paragraph's register.
- The rejected shape is exactly the finding's example, `fn (fn (cap a) ()
  Unit) {a} Unit`: the extern's own row names the callback's ability, but the
  only `cap` in sight is buried in the callback's domain, not taken directly.
- The accepted shape is the same callback and the same row, with a direct
  `cap` of the same ability taken earlier in the curried spine — the extern
  now holds the authority it exercises.
- Tests use a pinned prelude ability hash (`clock`, per `prelude.HASHES`), same
  idiom as the existing `FFI`/`NET` class attributes in
  `ExternCapabilityHonestyTest`.

## Work

- [x] Extend §5.1.3's capability-honesty paragraph with the callback
  consequence.
- [x] Add `test_a_callback_only_extern_is_unwritable` (rejected).
- [x] Add `test_a_callback_extern_with_its_own_direct_cap_is_accepted`
  (accepted).
- [x] Confirm no change to `_check_extern_capability_order` or any other
  checker/validator behavior.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

## Completion criteria

- §5.1.3 states the callback consequence in one to three sentences, in place,
  without restructuring the section.
- The rejected callback-only shape and the accepted callback-plus-direct-cap
  shape are both pinned as tests and both pass against the unmodified checker.
- No checker or validator source changed.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

### 1. `task prototype:test`

```text
----------------------------------------------------------------------
Ran 239 tests in 0.167s

OK
```

(237 tests before this change, per the meta-review's integration record; +2
for the new pair, all passing.)

### 2. `python3 -m py_compile prototype/*.py`

```text
PY_COMPILE_OK
```

### 3. `task todo:lint`

```text
TODO.md: clean
```

### 4. `git diff --check`

Exited 0, no output — no trailing whitespace or conflict markers introduced.
