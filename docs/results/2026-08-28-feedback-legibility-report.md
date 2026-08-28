# Feedback-legibility arm — results

**Plan:** [2026‑08‑27‑feedback‑legibility‑arm](../plans/2026-08-27-feedback-legibility-arm.md) §2 (pre‑registered)
**Model:** Qwen2.5‑Coder‑7B‑Instruct GGUF Q4_K_M · **Hardware:** g2‑standard‑4 L4 24 GB (Spot, both attempts) ·
**Condition:** `gbnf+typemask` · held‑out regime · `address_book: full` · `leave_one_out` ·
`generation_protocol: redraft` · 8 tasks × seeds 1–8 = **64 cells/arm, 128 cells total** · purse 4,608 tok/cell
**Arms:** `legib-legible` (`narrowing_note_render: surface`, HEAD / `8ed72cd`) vs
`legib-repr` (`narrowing_note_render: repr`, the pre‑fix feedback surface, reconstructed through the §2.1 seam).
**Selection:** [`experiment.legibility_compare`](../../prototype/experiment/legibility_compare.py) — **exit code 5, §6 row 4**.
Raw records: `prototype/runs/legib-{legible,repr}/records.jsonl`. Run id `20260828T112559Z`.

**One variable moved.** The two shipped configs are byte-copies of
`decomp-redraft.config.json` differing in `output_dir` and `narrowing_note_render`
only — checked as a *difference from the source* by deliverable 3's check 3, not by a
field-by-field re-listing. Both arms ran back-to-back on one instance from one runlist,
against one `llama.cpp` build and one model load, which is the property §1.3 paid for.

## Pre-launch gates

**Seam verification against banked bytes (deliverable 2): PASS.** Under `"repr"`, all
**2,159/2,159** banked rejected draws — 734 `whole` + 719 `redraft` + 706 `holes` —
reproduce their recorded `error_message` **byte-for-byte**, with 0 mismatches and 0
classification changes; under `"surface"`, 0 leaked repr artefacts (0.00 %) and
`funnel_outcome` unchanged on every draw, in both directions. That is C3 re-asserted,
so a difference between the arms cannot be a re-classification artefact. Output is
pasted in the plan's deliverable 2 (`### Deliverable 2 replay: narrowing_note_render
seam vs banked bytes`), and the same assertion runs as
`NarrowingNoteRenderingTest.test_repr_mode_reproduces_the_banked_pre_fix_bytes_exactly`
in `prototype/test_experiment.py`. This was the gate on the whole arm: the control arm is
the pre-fix condition exactly, not an approximation of it.

**CPU stub gate (deliverable 3): ALL CHECKS PASS,** four checks, output pasted in the
plan. Check 1 re-ran `hole_elicitation_stub_check.py` unchanged as a regression and it
still passes. Check 2 is **C2**: `_narrows` is `False` for `whole` under every condition
but `gbnf+rejection`, and a scripted `whole` cell produces byte-identical prompts under
both renderings — so the fix is inert on `whole` by construction and §2.3's argument for
not buying a `whole` arm holds. Check 3 pins both configs by difference from
`decomp-redraft.config.json`. Check 4 drives one cell of each *shipped* config through a
stub: the note fed into the next draw's prompt leaks the repr artefact only under
`legib-repr`, never under `legib-legible`, while both classify the same rejected draft
identically (C3 at the config level).

Nothing launched until both gates' output was in the plan file, per §3.

## Provenance

Two instance inserts, both **Spot**, recovered from the Compute operations log
(`gcloud compute operations list`, times PDT, ‑07:00; converted to UTC below):

| time (UTC) | event |
|---|---|
| 06:42:00 | driver launch, run id `20260828T064048Z` — bucket + IAM apply |
| 06:44:29 → 08:36:17 | GGUF upload to the artifacts bucket (no instance running) |
| 08:36:42 | insert #1 — Spot; DONE 08:36:49, runner boots |
| **09:01:30** | **`compute.instances.preempted`** — ≈ 25 min into the first attempt, before either arm finished |
| 09:01:44 → 11:24:22 | driver **blind-polls a dead instance** for 2.4 h (process defect, below) |
| 11:24:22 | teardown of attempt 1 |
| 11:26:57 | insert #2 — Spot again, run id `20260828T112559Z`; DONE 11:27:05 |
| 11:27:32 | runner starting, NVIDIA driver ready on the first attempt |
| 11:59:50 | `arm legib-legible: running the matrix` |
| 15:27:09 | `arm legib-legible: SUCCEEDED`; `arm legib-repr` starts 15:27:11 |
| 18:51:02 | `arm legib-repr: SUCCEEDED` — `runlist complete: 2/2 arms succeeded` |
| 18:51:10 | instance self-delete (`delete` operation, DONE 18:52:08) |

**Both attempts ran Spot; the pre-committed on-demand fallback never fired.** After the
preemption the driver relaunched on Spot and the second attempt carried both arms to
completion with no further preemption. **64/64 cells in both arms** — §4's pre-committed
degradation to 40 cells/arm was never triggered, so §2.2's `n = 64` power row is the one
in force (L1 MDE RR 1.20, 39.97 % → 47.96 %, power 0.81; 0.93 against RR = 1.25).

Both per-arm status markers read `SUCCEEDED`, and the driver fetched each arm's results
individually at 18:51:15 and 18:51:30 — the model-scale arm's "driver never fetched the
results" defect did not recur.

## The verdict, executed

`python -m experiment.legibility_compare`, run from `prototype/`, verbatim. **It exits
5 — §6 row 4.**

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

## L1 — the primary gate, significant in the reverse direction

The pre-registered one-sided test in the *legible > repr* direction is **null**
(p = 0.9786). The reverse-direction test on the same 64 cell pairs, same statistic, same
9,999 permutations, same seed 0, is **significant: p = 0.0215**. `legibility_compare`
exits 5 on that, which is §6's fourth row.

**What row 4 licenses**, in §6's own words and no further:

- **ESCALATE to the plan owner** before any further spend on the note surface. Done, on
  2026‑08‑28.
- **Do not revert `8ed72cd`** on this evidence. It is a correctness fix independent of
  this arm — the offline half of it (37/41/42 % repr leak → 0 %, 0 reclassifications on
  2,159 draws) stands on its own, and deliverable 2 re-confirmed it in both directions
  on this arm's seam.
- **The note-surface design question re-opens with the opposite sign** and needs the plan
  owner's read before any spend.

**What row 4 does not license.** §6 calls the outcome *"genuinely surprising and not a
rounding error: an unreadable note would be making the model more local, presumably by
making it conservative about touching the noted region"* — and files it as an
escalation, not a finding. That "presumably" is the plan's, and it is a hypothesis for
the plan owner to rule on, not a mechanism this arm established. Nothing here licenses
a claim that unreadable feedback is *better*, and L1 measures note-*following*, not
note-*usefulness* (§7's third bullet states that limit; it was stated before launch, not
after). L2 is null in the same direction and carries no weight either way: §2.2 measured
its power against a 1.25× effect at 0.23, so its null means "no effect ≥ 1.75×", not "no
effect", and **no §6 row is keyed to it**.

**No deviation from §2.5.** No number was computed until both arms were banked. The
seed, the permutation count, the direction and α are the ones fixed in §2.2 and in
`legibility_compare.py`'s constants; the reverse-direction p-value is a pre-registered
exit code, not a test found after the fact.

## C1 — PASS, and exactly

Both anchors land inside the banked arm's 95 % Wilson intervals, but the interesting
part is that they do not merely land inside them — **they are identical**. The `repr`
arm reproduced the banked `decomp-redraft` run **draw for draw**: L1 263/658, L2 53/772,
the same numerators over the same denominators, 6 days and two instances apart.

That is what §1.2's isolation argument predicted. §1.2 pinned the *source* — nothing on
the `redraft` path changed between the baseline commit and HEAD — and said plainly that
it could not pin the instance, the `llama.cpp` build, the driver, or GPU-level
nondeterminism. The exact reproduction closes that gap empirically: sampling at these
seeds is deterministic through the whole stack, **the harness had zero drift**, and the
two arms in this run therefore differ by the render seam and nothing else. §6's C1 row —
"no result in this report may be cited against the 2026‑08‑26 decomposition numbers" —
does not fire; the banked figures and this arm's are on the same footing.

It also means the counterfactual is settled rather than assumed: had the plan taken the
rejected design (banked `decomp-redraft` as the control, §2.3), the control arm would
have produced these same numbers. That does **not** retroactively justify the cheap
design — the concurrency rule exists because the equality had to be *demonstrated*, and
demonstrating it is exactly what the second arm bought.

## Protocol telemetry

Reported, not leaned on. Both arms, one cell key (`gbnf+typemask|held_out`), from
`prototype/runs/legib-{legible,repr}/summary.json`:

| | `legib-legible` (surface) | `legib-repr` (repr) |
|---|---|---|
| Cells | 64/64 | 64/64 |
| Draws | 795 | 772 |
| Redraws | 731 | 708 |
| Accepted draws | 51 (6.42 %) | 53 (6.87 %) |
| Funnel — parse / references / scope / typecheck | 19 / 63 / 5 / 657 | 18 / 72 / 3 / 626 |
| Mean draws per attempt | 12.42 | 12.06 |
| Mean draw latency | 15.54 s | 15.75 s |
| Mean tokens to first success | 1,192.2 | 1,191.7 |
| Distinct accepted identities | 17 | 21 |
| Repeated-definition rate | 66.67 % | 60.38 % |
| Mechanical-floor "semantic" successes | 4 | 3 |
| Completion tokens | 259,540 | 259,655 |
| Draw latency, summed | 12,350.9 s | 12,157.8 s |

**Masking cost is small and arm-symmetric.** Mask time is **3.93 %** of draw latency in
the legible arm (485.1 s of 12,350.9 s) and **4.01 %** in the repr arm (487.7 s of
12,157.8 s) — ≈ 3.9–4.0 %, so the render seam did not move what the mask costs, as it
should not. Vocabulary reads 152,064 tokens on both arms, the same figure the
model-scale arm's compatibility gate pinned, so the mask ran over the same vocabulary on
both sides of the comparison. Mask fallbacks: 13 legible, 9 repr.

**Not scored here.** The R3 hand rubric is outstanding for 5 legible and 4 repr draws.
The arm's question is L1/L2 and hand-scoring 9 draws is not on its critical path; it is
left outstanding by rule, not by omission — and the mechanical floor overstates, as the
pilot's hand rubric established.

**Throughput — §4's estimate was right to within 1.5 %.** §4 modelled 21.3 tok/s from
the banked `decomp-redraft` arm's own measured rate:

| arm | completion tokens | summed draw latency | measured |
|---|---|---|---|
| `legib-legible` | 259,540 | 12,350.9 s | **21.0 tok/s** |
| `legib-repr` | 259,655 | 12,157.8 s | **21.4 tok/s** |

Both are far above §4's 15 tok/s floor, so **§6's last row never fired** and no re-size
was triggered. The arms drew 519,195 completion tokens against §4's modelled 589,824 —
the purse is a ceiling, not a target, and cells that accept early spend less of it.

Overhead on the second attempt: 7.40 h of instance life minus 6.84 h of summed arm
elapsed (12,416.8 s + 12,221.2 s) = **0.56 h** for boot, model load, build-cache restore
and the inter-arm gap, against §4's 0.3 h estimate. Same direction as the model-scale
arm's 0.52 h against 0.4 h — the fixed overhead line is the mildly optimistic one in
both plans, and 0.5–0.6 h is the number to carry into the next.

## Cost, against §4's table

Both attempts billed at the Spot rate; the on-demand fallback and its pre-committed
40‑cell degradation were never invoked.

| line | interval (UTC) | duration | rate | cost |
|---|---|---|---|---|
| Attempt 1, Spot — preempted | 08:36:42 → 09:01:44 | 0.42 h | $0.25/h | ≈ $0.10 |
| Attempt 2, Spot — both arms, self-deleted | 11:26:57 → 18:51:10 | 7.40 h | $0.25/h | ≈ $1.85 |
| Storage + egress | | | | < $0.03 |
| **Total** | | **≈ 7.8 Spot‑hours** | | **≈ $1.98** |

| against §4 | figure |
|---|---|
| §4 all-Spot scenario, no preemption | $2.00 |
| §4 all on-demand, 64 cells/arm | ≈ $6.79 (over the ceiling — why the degradation was pre-committed) |
| **Budget ceiling for this arm** | **$4.55** |
| **Actual** | **≈ $1.98 — 44 % of the ceiling, and just under the all-Spot scenario** |

The run came in at essentially §4's best case: Spot held for the whole of the second
attempt, the preemption cost 25 min of compute rather than a fallback to a 3.4× unit
price, and the throughput estimate — the line §4 said was the closest the campaign has
ever had at plan time — was right.

**Deviation from the orchestrator's working figures.** The handback into this report
carried "≈ 2.3 h billed" for attempt 1 and ≈ 9.7 Spot‑hours / ≈ $2.4 overall. The
operations log does not support that: insert #1 at 08:36:42Z and
`compute.instances.preempted` at 09:01:30Z bound attempt 1 at **0.42 h**, and the
2.3 h figure is the *driver's blind poll after the instance was already gone*, not
billed compute. The corrected total is ≈ 7.8 Spot‑hours ≈ $1.98. Both figures are under
the ceiling; the corrected one is recorded here because a cost line that double-counts a
polling gap as compute would overstate every future estimate built on it.

## Process defect — the driver blind-polled a dead instance for 2.4 h

The instance was preempted at 09:01:30Z. The driver kept polling the status object until
11:24:22Z — **2.38 h** — before the attempt was torn down and relaunched. No compute was
billed for that window, so the cost was wall-clock, not money: the second attempt could
have started around 09:05Z instead of 11:27Z. This is the item
`[driver-preemption-detect]` was queued for, and the fix has since landed — the driver
now watches for the preemption system event rather than waiting out its poll budget
against a status object that will never appear.

## Teardown

The instance self-deleted on completion at 18:51:10Z (`delete` operation DONE 18:52:08Z),
and the teardown apply that follows it removed the runner from state. Verified after the
fact on project `project-19b81040-83b3-4483-a0d`:

```
$ gcloud compute instances list --project project-19b81040-83b3-4483-a0d
Listed 0 items.

$ gcloud compute disks list --project project-19b81040-83b3-4483-a0d
Listed 0 items.
```

Zero instances and zero disks — the boot disk went with the instance rather than being
orphaned.

The artifacts bucket `gs://loom-diversity-artifacts-19b81040/` is **deliberately left
standing**, as in the model-scale arm: it survives an instance-scope teardown and its
objects expire on a lifecycle rule (`age: 7 days`, plus `daysSinceNoncurrentTime: 1`).
It currently holds **16,981,108,475 B ≈ 15.8 GiB**, almost all of it the four cached
GGUFs (1.5B, 3B, 7B, 14B) — which is why attempt 2 re-uploaded nothing and reached
`apply 2/2` in 51 s against attempt 1's 1.9 h. Both arms' results were fetched to
`prototype/runs/legib-legible` and `prototype/runs/legib-repr` before teardown, and both
per-arm status markers read `SUCCEEDED`.

## Where this leaves the campaign

§6 row 4 is an escalation, not a decision. What is settled by this run:

- **`8ed72cd` stands.** It is landed, tested, free to keep, and this arm's evidence does
  not touch its correctness.
- **The harness is drift-free at these seeds** (C1, exact), which is a reusable result:
  the next arm can anchor against banked runs without re-buying a control for
  calibration alone — though not without one for *comparison*, which is a different job
  (§1.3).
- **The note-surface investment decision is open, with the sign reversed** from what the
  plan expected, and belongs to the plan owner before any further GPU spend.
