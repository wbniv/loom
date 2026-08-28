# Feedback-legibility arm — does a readable narrowing note change what the model writes?

**TODO entry:** the `## Watch` row *"Feedback-legibility standalone effect"*, promoted
on the model-scale arm's §6 row 3 handback.
**Predecessor:** [2026‑08‑27‑model-scale-arm](2026-08-27-model-scale-arm.md) §6 row 3 —
*"Stop the scale track … hand back the feedback-legibility lever (2026‑08‑26 §2.4)"*
([report](../results/2026-08-27-model-scale-arm-report.md)).
**Origin:** [2026‑08‑26‑hole-elicitation](2026-08-26-hole-elicitation.md) §2.4, which
filed the defect and §6 row 1, which named it *the cheaper lever*.
**Baseline record:** [2026‑08‑26 decomposition report](../results/2026-08-26-decomposition-report.md),
`prototype/runs/decomp-redraft/records.jsonl`.

The narrowing-note repr fix (`8ed72cd`, `[narrowing-legibility]`) landed on
2026‑08‑26 and has never been measured. It is landed, tested and free to keep; the
question is not whether to keep it but **whether feedback legibility is a lever worth
building on** — whether making the checker's complaint readable changes what the model
writes next. That decides whether the campaign's next investment goes into the feedback
surface or somewhere else.

---

## 1. The ordering confound, settled

Everything in this plan turns on one question: are the banked `decomp-redraft` records
genuinely pre-fix, and genuinely comparable? Both halves check out, and they check out
for different reasons, so they are recorded separately.

### 1.1 Ordering: clean, by two independent witnesses

| Event | Timestamp | Evidence |
|---|---|---|
| `decomp-whole` records written | 2026‑08‑26 05:43 | file mtime |
| `decomp-redraft` records written | 2026‑08‑26 09:07 | file mtime |
| Decomposition run reported | 2026‑08‑26 12:51 | commit `d38950c` |
| **Repr fix lands** | **2026‑08‑26 13:55** | commit `8ed72cd` |

The second witness is stronger than the clock, because it does not depend on trusting
a filesystem timestamp:

```
$ git diff --stat d38950c 8ed72cd^ -- prototype/typecheck.py
(empty — identical)
$ git diff --stat 8ed72cd HEAD -- prototype/typecheck.py
(empty — identical)
$ git log --oneline d38950c..HEAD -- prototype/typecheck.py
8ed72cd Render narrowing notes as canonical type surfaces, never Python repr
```

`typecheck.py` at the baseline commit is byte-identical to `8ed72cd^`, and `typecheck.py`
at HEAD is byte-identical to `8ed72cd`. The banked run therefore ran **exactly** the
pre-fix renderer, and HEAD is **exactly** the post-fix one, with a single commit between
them and nothing else. The banked records confirm it directly — every leaked
`error_message` still carries its raw bytes object:

```
definition.term.body: type mismatch: expected [1, b'.\xe91\xa3ta2\x88,\xdb\xc63…
```

### 1.2 Isolation: also clean — the `redraft` path saw nothing else change

Three commits touched `experiment/runner.py` after the baseline (`1b8086b` the
well-scoped fill gate, `f603922` the hole-required block, `cd0f717` `hole_at_error`),
and two touched `experiment/prompts.py` (`4f7b450`, `cd0f717`). None of them is reachable
from `redraft`:

- Every runner hunk lands in `_fill_the_holes` (`prototype/experiment/runner.py:853`)
  or `_run_holes_protocol` (`:977`). `_run_whole_protocol` (`:817`), which serves both
  `whole` and `redraft`, is untouched.
- `build_prompt`'s only new parameter is `hole_block`
  (`prototype/experiment/prompts.py:1508`), and its own docstring at `:1540` says it is
  read *"only when `generation_protocol == "holes"`"*.
- `fill_gate` defaults to `"accepted"`, so existing configs are byte-identical.

So the answer to the brief's question is: **yes, the banked decomposition records are
cleanly pre-fix, and cleanly isolated too.**

### 1.3 And they are still not admissible as the control arm

Two reasons, and the first is the campaign's own standard.

**The concurrency rule.** 2026‑08‑25 §4.5: *"The test is against the concurrent `whole`
arm, so a harness change cannot masquerade as an effect."* 2026‑08‑26 §2.4 invoked exactly
that rule to reject *"re-running only `holes` against the banked controls"*, even though
it would have saved $3. A banked control here would be the same move with the same
defect, and this plan does not get to use a standard against someone else's design and
then waive it for its own.

**What §1.2 does not cover.** §1.2 pins the *source*. It cannot pin the instance, the
`llama.cpp` build, the driver, or GPU-level nondeterminism, and no cheap check can. The
banked-versus-new difference would carry all of that inside the effect estimate.

**Design chosen:** two arms, run concurrently on one instance from one runlist, differing
in exactly one config field. The banked figure is kept, but demoted to a **calibration
anchor** (§2.4 C1) — a pre-registered check that the `repr` arm lands where the banked
arm landed. That is what banked data is good for. It is not a control.

---

## 2. Design

### 2.1 Two arms, one config field, one instance

| Arm | `narrowing_note_render` | Role |
|---|---|---|
| `legib-repr` | `"repr"` | control — the pre-fix feedback surface, reconstructed |
| `legib-legible` | `"surface"` | treatment — HEAD, `8ed72cd`'s rendering |

Everything else is a byte-copy of `decomp-redraft.config.json`: `generation_protocol:
redraft`, 8 tasks × seeds 1–8 = **64 cells/arm**, `gbnf+typemask`, held-out regime,
`leave_one_out`, purse 4,608 tok/cell, 768 tok/draw, `address_book: full`, pruners pinned
to `goal-type, de-bruijn, ref-hash`. **128 cells total.**

**The seam, and why a seam rather than a revert.** `_render` / `_render_row`
(`prototype/typecheck.py:45`, `:61`) read a `contextvars.ContextVar` defaulting to
`"surface"`; under `"repr"` they are unconditional `repr()`, which is what the nine
`_fail` sites did before `8ed72cd`. The runner sets it once per cell from the config.

The alternative — `git checkout 8ed72cd^ -- prototype/typecheck.py` in a second checkout
— is genuinely clean on the diff (§1.1 proves it drags nothing along) and was the first
design considered. It is rejected because **it cannot run concurrently.** Two checkouts
means two instances or two sequential deploys, which throws away the one property §1.3
just paid for. A config field also gets validated by the stub gate the way every other
arm difference is, and is diffable by the config checker; a checkout is not.

**The seam is verified against the banked bytes, not against intent.** `8ed72cd`'s own
replay harness (`prototype/test_experiment.py`) already reconstructs note text over
`decomp-{whole,redraft,holes}/records.jsonl`. Deliverable 2 extends it: with the var set
to `"repr"`, every one of the **2,159 banked rejected draws** — `8ed72cd`'s and
2026‑08‑26 §2.2's `--section blame` convention, 734 `whole` + 719 `redraft` + 706 `holes`
skeletons — must reproduce its recorded `error_message` **byte-for-byte**. Anything less and the control arm is not the pre-fix
condition, it is an approximation of it, and the arm does not launch.

**No `whole` arm.** `whole` never receives a note — `_narrows`
(`prototype/experiment/runner.py:646`) gates narrowing on `generation_protocol in
(PROTOCOL_REDRAFT, PROTOCOL_HOLES)` — so the fix is inert there by construction. That is
proven by a stub check (deliverable 3), not bought with 4 GPU‑hours. **No `holes` arm**
either: 2026‑08‑26 §2.4's whole objection to folding this lever in was that it moves
`redraft` and `holes` together and confounds both, and the scale arm has since closed the
`holes` track.

### 2.2 Gates, fixed before launch

The primary is **not** draw-level funnel acceptance. That needs saying plainly, because
the TODO Watch row names funnel acceptance as the comparison and an earlier draft of this
plan made it the primary. The power script (deliverable 5) says it would be a coin flip,
so it is demoted to descriptive and a denser endpoint carries the decision — the same
correction the model-scale arm made to S1, for the same reason.

- **L1 (primary gate) — repair locality.** Over narrowed draws that follow a rejected
  draft, the fraction whose next draft's failure path lies **at or below the path the
  note named** (common prefix ≥ the noted path's length), or which are accepted outright.
  Banked `repr` rate: **263/658 = 39.97 %**. Degenerate case, fixed here so it cannot
  be decided after the fact: an empty noted path (13 of the 658 banked pairs, 2.0 %)
  has length 0, so every successor counts as local. It is a small, arm-symmetric
  inflation of the base rate, both arms compute it identically, and the predicate
  lives in one definition shared by `legibility_power.py` and
  `legibility_compare.py` (deliverable 6) so the two cannot drift.
  Test: paired sign-flip randomization over
  the 64 cell pairs `(task, seed)`, statistic = pooled rate difference
  (legible − repr), one-sided (**legible > repr**), α = 0.05, 9,999 permutations,
  seed 0.

  This is the endpoint the intervention directly targets. A note reading `expected [1,
  b'.\xe91\xa3…']` names a node in an encoding the model has never seen in the surface,
  so it has nothing to localize on and rewrites elsewhere; a note reading `expected (fn
  (data 0x2ee9… (I64)) () Bool)` names one it can act on. L1 asks whether the model can
  *act on the note at all*, which is what §2.4 alleged was broken. It is the analogue of
  the elicitation pilot's E1, and it carries E1's limitation too: **L1 clearing does not
  license "legibility improves generation".** It licenses "the feedback surface is now
  readable, so a lever built on feedback has something to stand on." §6 says so in the row.

- **L2 (descriptive) — draw-level funnel acceptance.** `funnel_outcome == "accepted"`
  over all charged draws, the quantity the Watch row names. Banked `repr` rate:
  **53/772 = 6.87 %.** Same paired test, reported with its p-value and its measured
  power. **No §6 row is keyed to L2 alone.**

  L2 is deliberately unconditional — over *every* charged draw, not only narrowed ones.
  Restricting to narrowed draws is denser and was considered, but "narrowed" is
  post-treatment: an arm that accepts more has fewer narrowed draws left, and the ones
  left are the harder ones. Conditioning on it would bias the primary against the
  treatment. The narrowed-only figure is reported as a secondary with that caveat
  attached.

**Powered MDE, measured before launch.** Deliverable 5
(`experiment/legibility_power.py`, paired sign-flip, α = 0.05, 1,500 simulations ×
999 permutations, seed 0, cell rates beta-binomial-fitted to the 64 banked cells, cell
sizes resampled per arm):

```
### Feedback-legibility arm — pre-registered power

  Paired sign-flip randomization test, one-sided (legible > repr), alpha = 0.05,
  target power = 80%, 1500 simulations x 999 permutations, seed 0.
  Cell sizes resampled per arm; cell rates beta-binomial, fitted to the banked cells.
  `iid MDE` is the same MDE computed as if draws were independent and unpaired —
  the gap to the MDE column is what clustering costs net of what pairing buys.

### L1 (primary gate) — repair locality

  banked control (`decomp-redraft`): 263/658 = 39.97% over 64 cells, 10.28 draws/cell (range 5-24).
  Beta-binomial MLE: a = 2.9925, b = 4.9959 (mean 37.46%, concentration 7.99).

  cells/arm  MDE (RR)  MDE rate  power@MDE   power@RR=1.25   iid MDE
         40      1.26   50.36%       0.82            0.80      1.24
         48      1.24   49.56%       0.82            0.85      1.22
         64      1.20   47.96%       0.81            0.93      1.18

### L2 (descriptive) — draw-level funnel acceptance

  banked control (`decomp-redraft`): 53/772 = 6.87% over 64 cells, 12.06 draws/cell (range 7-31).
  Beta-binomial MLE: a = 0.4748, b = 9.2064 (mean 4.90%, concentration 9.68).

  cells/arm  MDE (RR)  MDE rate  power@MDE   power@RR=1.25   iid MDE
         40      2.05   14.07%       0.82            0.16      1.70
         48      1.95   13.39%       0.82            0.19      1.65
         64      1.75   12.01%       0.81            0.23      1.55
```

**Read honestly, in both directions.**

- **L1 at 64 cells/arm detects RR ≥ 1.20** — 39.97 % → 47.96 %, +8 points — at 80 %
  power, and has **0.93 power against a 1.25× effect**. That is a real gate.
- **L2 at 64 cells/arm needs RR ≥ 1.75** — 6.87 % → 12.0 % — and has **0.23 power
  against 1.25×.** Detecting the sort of effect a rendering change plausibly produces on
  a 6.87 % base rate would take roughly 50× this arm's budget: hundreds of GPU‑hours and
  a three-figure spend, against a project scale of $1.30–$4.55. **That is not
  affordable and this plan does not pretend otherwise.** L2's null will mean "no effect
  ≥ 1.75× ", not "no effect", and §6's rows say so.
- **Pairing does not repay what clustering costs.** For L1 the paired MDE (1.20) is
  slightly *worse* than the naive iid one (1.18): the intra-cluster correlation is 0.120
  on ~10 draws/cell (design effect 2.11) and pairing buys back all but a sliver. It is
  still the right test — the iid number is unavailable to an honest analysis, not an
  alternative to it — but the pairing is bought for validity, not for power, and that is
  worth knowing before anyone proposes it as a way to buy power elsewhere.

**There is no prior on the effect size, and none is claimed.** The banked run has
leaked notes and unleaked notes, and it is tempting to read across them — leaked-note
draws accept at 4.46 % against 10.46 % for unleaked ones within the `typecheck` stratum,
one-sided Fisher p = 0.0049, which looks like a large effect. **It is not this
experiment's contrast and it is mostly task composition.** Unleaked pre-fix notes are
notes that mention no type at all, not notes that render a type well; the treatment's
condition never occurred. Stratifying by task collapses the contrast to a Mantel–Haenszel
odds ratio of 1.60 and an arm-wide counterfactual of 53 → 57.5 accepted draws, **RR ≈
1.08** — the exposed group is loaded with `nat/selectNonNegative` (60 draws against 8,
0 % acceptance arm-wide) and the unexposed with `maybe/mapOrElse` (114 against 52,
19.3 %). The 1.25 probe column above is therefore a *reference point chosen before the
run*, not an expectation.

### 2.3 Designs rejected here

- **A pinned single-file revert of `typecheck.py` in a second checkout.** §2.1: clean on
  the diff, but it cannot run concurrently, which is the property §1.3 exists to buy.
- **Banked `decomp-redraft` as the control, one new arm only.** Saves ≈ $1.00 and half
  the wall clock. Rejected on 2026‑08‑25 §4.5, the same standard 2026‑08‑26 §2.4 used to
  reject the analogous saving. Survives only as §4's pre-committed degradation? **No —
  it does not survive at all.** The degradation on cost is fewer cells, never fewer arms.
- **A `whole` arm as a placebo.** `whole` is inert by construction
  (`runner.py:656`); an A‑A check there would cost 4 GPU‑hours to re-derive what a
  stub check proves for free. Deliverable 3 proves it instead.
- **Funnel acceptance as the primary.** §2.2: 0.23 power against a 1.25× effect. Keying
  the decision to it would buy a coin flip and call it a result.
- **Answering this offline, at $0.** `8ed72cd` already did the offline half — 37/41/42 %
  → 0 %, 0 reclassifications on 2,159 draws. The remaining question is what the *model*
  does with the better note, and no replay can answer that; the model has to be
  re-sampled against the changed prompt.

### 2.4 Calibration and invariance checks

- **C1 — drift anchor.** The `repr` arm's L1 and L2 rates must fall inside the banked
  arm's 95 % Wilson intervals (L1 `263/658`, L2 `53/772`). C1 is **reported, never
  decisive**: the primary is a within-run comparison and stays valid whatever C1 says.
  A C1 failure means the banked numbers cannot be cited alongside this arm's, and it is
  a harness-drift finding in its own right — §1.2 says nothing changed in the `redraft`
  path, so a failure would mean the change is in the instance, the build or the sampler,
  and that is worth knowing before the next arm is planned.
- **C2 — protocol invariance.** Stub check: `_narrows` (`runner.py:646`) is false for
  `generation_protocol == "whole"` under every condition but `gbnf+rejection`, so no
  `whole` prompt can differ between the two renderings. CPU only.
- **C3 — classification invariance.** `8ed72cd` established that the renderer does not
  move `funnel_outcome` on any of 2,159 banked draws. Re-asserted by the seam replay
  (deliverable 2) in both directions, so a difference between the arms cannot be a
  re-classification artefact.

### 2.5 No peeking, no test-shopping

No number is computed until both arms are banked. L1 is the primary; L2 and the
narrowed-only secondary are reported whatever they say. The permutation seed, the
permutation count, the direction and α are fixed in this section and in
`legibility_compare.py`'s constants. Any deviation is filed in the report under this
section, named as a deviation, before the verdict.

---

## 3. Deliverables

1. **The `narrowing_note_render` seam** — a `contextvars.ContextVar` in
   `prototype/typecheck.py` read by `_render` / `_render_row`, plus the `Config` field
   (validated against `{"surface", "repr"}`, defaulting to `"surface"`) and the runner
   set-site. Existing configs stay behaviourally byte-identical. *(T3 — small, but it
   reaches into the typechecker's error path and the runner's cell setup.)*
2. **Seam verification against banked bytes** — extend `8ed72cd`'s replay in
   `prototype/test_experiment.py`: under `"repr"`, all 2,159 banked rejected draws
   reproduce their recorded `error_message` byte-for-byte; under `"surface"`, 0 % leak
   and `funnel_outcome` unchanged on every one. **This is the gate on the whole arm** —
   if the control arm is not the pre-fix condition exactly, there is nothing to compare.
   *(T2.)*
    **Output.** `NarrowingNoteRenderingTest.test_repr_mode_reproduces_the_banked_pre_fix_bytes_exactly`
    (`prototype/test_experiment.py`) asserts this as a unit test; the same replay, run inline below
    over all 2,159 banked rejected draws across the three decomposition arms:

    ```
    === Deliverable 2 replay: narrowing_note_render seam vs banked bytes ===

    --- repr mode: byte-identity check of error_message against the banked bytes ---
    whole    : 734/734 byte-identical, 0 mismatches, 0 classification changes
    redraft  : 719/719 byte-identical, 0 mismatches, 0 classification changes
    holes    : 706/706 byte-identical, 0 mismatches, 0 classification changes
    TOTAL    : 2159/2159 byte-identical, 0 mismatches

    --- surface mode: repr-leak check (0% target) + classification invariance ---
    whole    : 734 rejected, 0 leaked (0.00%), 0 classification changes
    redraft  : 719 rejected, 0 leaked (0.00%), 0 classification changes
    holes    : 706 rejected, 0 leaked (0.00%), 0 classification changes
    TOTAL    : 2159 rejected, 0 leaked (0.00%)

    VERDICT: byte-identity YES; surface leak 0.00%; classification changes 0 in both directions
    ```

    And the test-suite run of the same assertion:

    ```
    $ python3 -m unittest test_experiment.NarrowingNoteRenderingTest.test_repr_mode_reproduces_the_banked_pre_fix_bytes_exactly -v
    test_repr_mode_reproduces_the_banked_pre_fix_bytes_exactly (test_experiment.NarrowingNoteRenderingTest.test_repr_mode_reproduces_the_banked_pre_fix_bytes_exactly)
    Deliverable 2: the seam is verified against the banked bytes, not ... ok

    ----------------------------------------------------------------------
    Ran 1 test in 5.444s

    OK
    ```

    **Verdict: gate clears.** Byte-identity holds on all 2,159/2,159 banked rejected draws under
    `"repr"`; `"surface"` reproduces 0 % leak with `funnel_outcome` unchanged on every draw, in
    both directions. The control arm is the pre-fix condition exactly — the arm may launch on this
    gate.
3. **CPU stub gate** — re-run `hole_elicitation_stub_check.py` unchanged (regression),
   and add the arm's own checks: C2 (`whole` is inert), the two configs differing from
   `decomp-redraft.config.json` by `output_dir` and `narrowing_note_render` only, and a
   scripted stub driving one cell of each arm. Output pasted into this file before
   launch. *(T2.)*

    **Output.** `experiment/legibility_stub_check.py`
    (`python3 -m experiment.legibility_stub_check`, from `prototype/`):

    ```
    ### Check 1 — hole_elicitation_stub_check.py, re-run unchanged (regression)

      exit code: 0
      ### Deliverable 6 verdict: ALL CHECKS PASS — the GPU gate is open

      result: PASS

    ### Check 2 — C2: protocol invariance (`whole` is inert to the render seam)

      _narrows(protocol='whole'    condition='gbnf'          ) = False (expected False)  ok
      _narrows(protocol='whole'    condition='gbnf+typemask' ) = False (expected False)  ok
      _narrows(protocol='whole'    condition='gbnf+rejection') = True  (expected True )  ok
      _narrows(protocol='redraft'  condition='gbnf'          ) = True  (expected True )  ok
      _narrows(protocol='redraft'  condition='gbnf+typemask' ) = True  (expected True )  ok
      _narrows(protocol='holes'    condition='gbnf'          ) = True  (expected True )  ok
      render=surface draws=2  funnel_outcomes=['typecheck', 'typecheck']
      render=repr    draws=2  funnel_outcomes=['typecheck', 'typecheck']
      whole-protocol prompts, surface vs repr: byte-identical

      result: PASS

    ### Check 3 — the two arm configs vs decomp-redraft.config.json (§3 deliverable 4)

      decomp-redraft.config.json carries no narrowing_note_render key: True
      legib_legible.config.json    only-two-fields-differ=True  output_dir='runs/legib-legible'  narrowing_note_render='surface'  validates=True  ok
      legib_repr.config.json       only-two-fields-differ=True  output_dir='runs/legib-repr'  narrowing_note_render='repr'  validates=True  ok

      result: PASS

    ### Check 4 — a scripted stub drives one cell of each shipped arm config

      note: driven at condition `gbnf` (the mask needs a real vocabulary) with the
            draw cap overridden to 2 and the backend replaced with a stub; every
            other field — including `narrowing_note_render` — is the arm's own
            shipped config, loaded from disk rather than reconstructed.

      legib-legible  narrowing_note_render=surface draws=2 outcomes=['typecheck', 'typecheck'] round-1-prompt-leaks-repr=False (expected False)  ok
      legib-repr     narrowing_note_render=repr    draws=2 outcomes=['typecheck', 'typecheck'] round-1-prompt-leaks-repr=True (expected True)  ok
      classification invariance (C3), across arms: match — {'legib-legible': ['typecheck', 'typecheck'], 'legib-repr': ['typecheck', 'typecheck']}

      result: PASS

    ### Deliverable 3 verdict: ALL CHECKS PASS — the GPU gate is open
    ```

    **Verdict: gate clears.** The regression check re-ran `hole_elicitation_stub_check.py`
    unchanged and it still passes, so nothing this arm's seam touched broke that gate. C2
    holds both by construction (`_narrows` is `False` for `whole` under every condition but
    `gbnf+rejection`, unconditionally `True` for `redraft`/`holes`) and empirically (a
    scripted `whole` cell produces byte-identical prompts under both renders). The two
    shipped configs differ from `decomp-redraft.config.json` by exactly `output_dir` and
    `narrowing_note_render`, and both validate. A scripted stub driving one cell of each
    shipped config classifies the same rejected draft identically (C3, at the config level)
    while the note fed into the next draw's prompt leaks the repr artefact only under
    `legib-repr`, never under `legib-legible` — each arm's own file behaves exactly as its
    row in §2.1's table says. The gate is open.
4. **`legib_legible.config.json`, `legib_repr.config.json`,
   `legibility-runlist.json`** — byte-copies of `decomp-redraft.config.json` with only
   `output_dir` and `narrowing_note_render` changed. Model identity and backend seam are
   rewritten on the instance, as always. Pinned by *difference* from their source in
   `test_legibility_arm.py`, not by a field-by-field re-listing that would pass even if
   the source drifted underneath — the gap the model-scale arm's deliverable 3 named.
   *(T1.)*
5. **Powered MDE** — `experiment/legibility_power.py`, pasted into §2.2 before launch.
   `scale14_power.py`'s method is reused (one-sided, simulated, fixed seed); its numbers
   and its two-sample shape are not. **Done** — and its result demoted this plan's
   original primary to descriptive. *(T2.)*
6. **`experiment/legibility_compare.py`** — reads `runs/legib-legible`,
   `runs/legib-repr` and the banked `runs/decomp-redraft`, prints L1, L2, the
   narrowed-only secondary and C1, and exits on a code per §6's row. The verdict is
   executed, not judged — same discipline as `pilot_select.py` and `scale_compare.py`,
   and it imports L1's predicate from a single definition shared with the power script so
   the endpoint cannot drift between the two. Its on-screen output is the arm's only
   visible surface; the mockup is §5. *(T2.)*
7. **The run** — §4. *(T5, driven inline.)*
8. **Report** — `docs/results/2026-08-2X-feedback-legibility-report.md`: gate verdicts,
   telemetry, the §6 row that fired, cost and teardown evidence. *(T3.)*

Deliverables 1–6 are CPU-only and gate the GPU spend. **Nothing launches until 2's and
3's output is in this file.**

---

## 4. Cost

`g2-standard-4` (L4 24 GB), us‑central1, in runlist mode — both arms on one instance,
self-deleting at the end. **Spot first with the pre-committed on-demand fallback**, the
shape the pilot and the model-scale arm both used.

Throughput is measured, not modelled: the banked `decomp-redraft` arm emitted
259,655 completion tokens in 3.39 h of draw latency, **21.3 tok/s**. The arm is the same
protocol, the same model and the same purse, so this is the closest estimate the campaign
has ever had at plan time.

| Line | Quantity | Rate | Hours |
|---|---|---|---|
| 2 arms × 64 cells × 4,608 tok purse | 589,824 tok | 21.3 tok/s | 7.7 h |
| Boot, model load, build-cache restore | | | 0.3 h |
| **Total** | | | **≈ 8.0 h** |

| Scenario | Unit price | Cost |
|---|---|---|
| All-Spot, no preemption | $0.25/h | **$2.00** |
| All on-demand, 64 cells/arm | $0.85/h | ≈ $6.79 |
| **All on-demand, degraded to 40 cells/arm (5.1 h)** | $0.85/h | **≈ $4.34** |
| Storage + egress | | < $0.03 |
| **Budget ceiling for this arm** | | **$4.55** |

**The on-demand figure at 64 cells is over the ceiling, so the reduction is
pre-committed rather than decided at 03:00:** if the run must go on-demand, drop to
**5 seeds / 40 cells per arm** and report §2.2's `n = 40` power row as the one in force
— L1's MDE becomes RR 1.26 with 0.80 power at 1.25×, which is still a gate. Nothing
else changes, and **the reduction is never fewer arms** (§2.3). If measured throughput
comes in below 15 tok/s, stop after the first arm and re-size.

Preemption is not hypothetical — the decomposition run lost one instance 8 minutes in
and the model-scale arm ran entirely on-demand after a preemption. Per-arm incremental
upload and a committed resume runlist are reused unchanged. **Teardown is part of the
run:** the instance self-deletes, and the report carries the root-destroyed / bucket-404 /
zero-instances evidence.

---

## 5. Mockup — `legibility_compare.py` output

The arm's only visible surface is one CLI report. Target shape:

```
### Feedback-legibility arm — legible vs repr, redraft protocol

arm                        draws   cells   L1 rate   L2 rate
legib-legible (surface)      ---   --/64    --.--%    --.--%
legib-repr    (repr)         ---   --/64    --.--%    --.--%

### L1 — repair locality (PRIMARY GATE)

  legible <k>/<n> = --.--%   repr <k>/<n> = --.--%   diff +-.-- pts (RR -.--)
  paired sign-flip over 64 cell pairs, one-sided (legible > repr),
  alpha = 0.05, 9999 permutations, seed 0:  p = -.----   <significant|null>
  powered MDE at this n (deliverable 5): RR 1.20  (39.97% -> 47.96%)

### L2 — draw-level funnel acceptance (DESCRIPTIVE)

  legible <k>/<n> = --.--%   repr <k>/<n> = --.--%   diff +-.-- pts (RR -.--)
  same test:  p = -.----   <significant|null>
  Reported only. §2.2 measured L2's power against a 1.25x effect as 0.23,
  so no §6 row is keyed to this p-value. A null here means "no effect
  >= 1.75x", not "no effect".
  secondary, narrowed draws only (post-treatment selection — see §2.2):
    legible <k>/<n> = --.--%   repr <k>/<n> = --.--%

### C1 — drift anchor against the banked pre-fix run (decomp-redraft)

  L1  banked 263/658 = 39.97%  95% Wilson [--.--%, --.--%]   repr arm --.--%  <in|OUT>
  L2  banked  53/772 =  6.87%  95% Wilson [--.--%, --.--%]   repr arm --.--%  <in|OUT>
  Reported, never decisive (§2.4). OUT means the banked numbers cannot be
  cited alongside this arm's — not that the primary is invalid.

### Verdict

  <the §6 row, named>
```

Exit codes, keyed to §6's rows: `0` L1 clears; `2` L1 null and L2 ≥ 1.5× descriptively;
`3` L1 null and L2 < 1.5×; `5` L1 significant in the **reverse** direction; `4` a
required run directory is missing.

---

## 6. What each outcome licenses

| Outcome | What it licenses next |
|---|---|
| **L1 clears** (repair locality, legible > repr, p < 0.05) | The model **can act on a readable note and could not act on a repr**. Feedback legibility is a live lever and the surface is worth investing in: promote the note surface to a first-class design object — name the expected type *and* the offending sub-term, quote the sub-term's own surface, and re-open prefix-primed repair (2026‑08‑26 §2.5) against a note the model can parse. **This licenses work on the feedback surface, not a claim that acceptance improved** — L2 could not have seen that either way (§2.2). |
| **L1 null, L2 point estimate ≥ 1.5×** | The mechanism gate says the model does not act more locally, but the outcome moved further than L1's null would predict. That is incoherent enough to be worth a second look rather than a decision: **ESCALATE to the plan owner** with both numbers, and re-plan a purpose-built acceptance arm with a power budget, or drop the lever. Do not read the L2 point estimate as a result — its 95 % interval will be wide by construction. |
| **L1 null, L2 point estimate < 1.5×** | Legibility is **not** a lever at 7B on this protocol: the model was not reading the note in either rendering, so making it readable changed nothing measurable. Stop the feedback-surface track. Keep `8ed72cd` — it is landed, free and correct — as a **standing improvement carried by every future arm**, not as a lever to build on. The next lever must target something other than the feedback channel. |
| **L1 significant in the reverse direction** (repr > legible) | Genuinely surprising and not a rounding error: an unreadable note would be making the model *more* local, presumably by making it conservative about touching the noted region. **ESCALATE.** Do not revert `8ed72cd` on this evidence — it is a correctness fix independent of this arm — but the note-surface design question re-opens with the opposite sign and needs the plan owner's read before any spend. |
| **C1 fails** (the `repr` arm misses the banked interval) | Harness drift between 2026‑08‑26 and the run, in the instance, the build or the sampler, since §1.2 rules out the source. Reported alongside whichever row fired; the primary stands (within-run), but **no result in this report may be cited against the 2026‑08‑26 decomposition numbers**, and the drift is filed as its own item before the next arm is planned. |
| **Measured throughput < 15 tok/s** | Stop after the first arm and re-size per §4. Not a finding, a budget rule. |

---

## 7. What would change this plan

- **Deliverable 2 failing** — if the seam cannot reproduce the banked `error_message`
  bytes exactly, the control arm is an approximation of the pre-fix condition rather than
  the condition itself. The arm does not launch; the seam is fixed or the design goes
  back to the rejected two-checkout revert with its concurrency cost priced in.
- **C2 failing** — if `whole` turns out to be reachable by the renderer after all, the
  §2.3 argument for dropping the `whole` arm collapses and the arm's cost re-opens.
- **A cheaper endpoint than L1 with a defensible reading.** L1 measures note-*following*,
  not note-*usefulness*, and that limit is stated rather than hidden. If someone can
  define an endpoint that separates the two at comparable density, it should displace L1
  before launch, not after.
- **Anything that makes 200+ cells/arm affordable** — a spot price change, a faster
  backend, a smaller purse that still reaches the funnel. L2 becomes a real primary at
  roughly 50× this budget, and only then.

---

## Deliverable 7 verdict record (2026-08-28, appended by the orchestrator)

Both arms ran on one Spot g2-standard-4 (run id `20260828T112559Z`), 64/64 cells each,
no degradation triggered. `python -m experiment.legibility_compare` **exit code 5 — §6
row 4 fired**. Raw output verbatim:

```
### Feedback-legibility arm — legible vs repr, redraft protocol

arm                         draws    cells   L1 rate   L2 rate
legib-legible (surface)       795  64/64      37.77%     6.42%
legib-repr    (repr)          772  64/64      39.97%     6.87%

### L1 -- repair locality (PRIMARY GATE)

  legible 258/683 = 37.77%   repr 263/658 = 39.97%   diff -2.20 pts (RR 0.95)
  paired sign-flip over 64 cell pairs, one-sided (legible > repr),
  alpha = 0.05, 9999 permutations, seed 0:  p = 0.9786   null
  powered MDE at this n (deliverable 5): RR 1.20  (39.97% -> 47.96%)

### L2 -- draw-level funnel acceptance (DESCRIPTIVE)

  legible 51/795 = 6.42%   repr 53/772 = 6.87%   diff -0.45 pts (RR 0.93)
  same test:  p = 0.8498   null
  Reported only. §2.2 measured L2's power against a 1.25x effect as 0.23,
  so no §6 row is keyed to this p-value. A null here means "no effect
  >= 1.75x", not "no effect".
  secondary, narrowed draws only (post-treatment selection -- see §2.2):
    legible 47/683 = 6.88%   repr 49/658 = 7.45%

### C1 -- drift anchor against the banked pre-fix run (decomp-redraft)

  L1  banked 263/658 = 39.97%  95% Wilson [36.30%, 43.76%]   repr arm 39.97%  in
  L2  banked 53/772 = 6.87%  95% Wilson [5.29%, 8.87%]   repr arm 6.87%  in
  Reported, never decisive (§2.4). OUT means the banked numbers cannot be
  cited alongside this arm's -- not that the primary is invalid.

### Verdict

  L1 is significant in the REVERSE direction: repr 39.97% > legible 37.77%, p = 0.0215 (§6 row 4).
  Genuinely surprising, not a rounding error. ESCALATE to the plan
  owner before any further spend. Do not revert the repr fix on this
  evidence -- it is a correctness fix independent of this arm.
```

**C1: PASS**, and exactly — the `repr` arm reproduced the banked decomp-redraft run to the
draw (L1 263/658, L2 53/772 identical), the deterministic replay §1.2 predicted.

**Throughput budget rule: holds.** legible 259,540 tok / 12,350.9 s = 21.0 tok/s;
repr 259,655 tok / 12,157.8 s = 21.4 tok/s — both above the 15 tok/s floor (and at the
§4 21.3 tok/s estimate), so no re-size was triggered.

**Escalated to the plan owner per §6 row 4** before any further spend on the
note-surface design. The repr fix (`8ed72cd`) stands.
