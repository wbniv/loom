# Plan — Evidence confidence bounds

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** SPEC.md §6 (evidence), §3.4 (crisp by design), §13 open problem 6

## Objective

Close the numeric half of §13 open problem 6: A1 `property` evidence currently
flattens a statistical claim to a bare run count, so `A1(10⁶)` from a narrow
generator outranks `A1(10³)` from an adversarial one purely by arithmetic on
`n`. Extend the A1 payload to carry an explicit **failure-probability bound at
a stated confidence, relative to a stated generator**, specified as a
deterministic CBOR shape like every other store object (§4.2, §5), and restate
§6.3 monotone assurance over the resulting partial order.

The accept/refuse decision stays two-valued (§3.4): only the *inputs* a policy
thresholds against become numeric. The namespace policy object format itself
remains an open TODO and is deliberately **not** specified here — this change
only makes the fields a future policy can threshold against exist and be
checkable.

No visible surface (normative spec text only), so this plan carries no mockups.

## Rules

- **The payload is an exact-rational CBOR array, not a float.** Payload bytes
  feed the memo-ledger key `(def-hash, obligation-id, payload-hash)` (§6.4), so
  the encoding must be one-value-one-byte-sequence. Probabilities are encoded
  as canonical rationals `[numerator, denominator]` (denominator ≥ 1, `gcd = 1`,
  `0 ≤ num ≤ den`), never as floats, and never as a bare run count.
- **The bound is recomputable, not asserted.** The payload records the
  estimator family as a method tag, so a checker recomputes the bound from
  `(method, runs, failures, confidence)` and rejects any payload whose recorded
  bound is *below* the recomputed one. Recording a bound that is too large (or
  a confidence that is too small) is always sound and always permitted; that is
  what lets a limited-precision implementation stay conservative.
- **Clopper–Pearson is the only v0.1 method.** The exact binomial upper bound
  is distribution-free, needs no solver, and is never anti-conservative at
  small `n`. Alternatives considered and rejected: the normal/Wald
  approximation and the Wilson interval (both understate the bound at small `n`
  or near `p = 0`, exactly the regime the evidence lattice lives in), and
  Bayesian credible intervals (prior-dependent, so two honest implementations
  disagree on the same draws — fatal for a content-addressed ledger). Unknown
  method tags are rejected outright rather than accepted at a degraded level.
- **Supporting evidence has zero failures.** Obligations are crisp
  propositions (§3.4), so a failing draw is a refutation, not a weaker
  positive. `failures` stays in the payload so refutations encode, but an
  evidence object supporting an obligation has `failures = 0` and its bound
  therefore uses the `k = 0` specialization `p ≤ 1 − (1 − c)^(1/n)`.
- **A1 strength is a partial order, and incomparable means refused.** One A1
  payload is at least as strong as another only when the generator hashes are
  equal, the bound is no larger, and the confidence is no smaller. Different
  generators are incomparable — never silently ordered by run count — and
  §6.3's rebind refusal fires on incomparability exactly as it does on a
  decrease. The cross-level order `A0 ⊏ A1 ⊏ A2 ⊑ A3` stays total; only the
  interior of A1 is partial.
- **Run count survives as observation, not as rank.** `runs` and `seed` remain
  in the payload for reproducibility and for recomputing the bound; they no
  longer order A1 by themselves.
- **§5.3 gets one sentence, not a policy grammar.** The binding record's
  `policy-ref` note gains a pointer saying an A1 threshold is a
  `(bound, confidence, generator)` triple rather than a run count, with the
  policy object format still open (§13).

## Work

- [x] Specify the A1 `property` payload as a CBOR array with canonical field
  order in `SPEC.md` §6.1, including the rational encoding, the method-tag
  registry, and the checker's recomputation duty.
- [x] Restate the assurance order in §6.1 over the new payload (total across
  levels, partial within A1).
- [x] Restate §6.3 monotone assurance in terms of that partial order, including
  the generator-change case.
- [x] Update §3.4's third "where uncertainty lives" bullet — it currently cites
  the run-count flattening as a known defect.
- [x] Add the minimal §5.3 sentence about numeric A1 thresholds.
- [x] Keep §12's worked example consistent: policy threshold and the
  `ensures.isMiddleOf` obligation line now carry a bound and confidence.
- [x] Narrow §13 open problem 6 to what remains open.
- [x] Add this plan's row to `docs/plans/README.md`.

## Verification

```sh
task prototype:test
task todo:lint
git diff --check
```

## Completion criteria

- §6.1 states the A1 payload as a deterministic CBOR array with a stated field
  order and an exact-rational probability encoding.
- The bound, its confidence, and the generator it is relative to are all
  explicit payload fields, and the bound is recomputable by a checker.
- §6.3 defines strictly-stronger for two A1 payloads, and says what happens
  when two payloads are incomparable.
- §3.4's crisp accept/refuse boundary is unchanged and says so explicitly.
- §12's numbers are arithmetically consistent with the stated method
  (10⁴ zero-failure draws at 99 % ⇒ bound 4.61 × 10⁻⁴).
- §13 open problem 6 describes only the still-open residue.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

1. `task prototype:test`

    ```text
    Ran 65 tests in 0.037s

    OK
    ```

    PASS.

2. `task todo:lint`

    ```text
    TODO.md: clean
    ```

    PASS.

3. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.
