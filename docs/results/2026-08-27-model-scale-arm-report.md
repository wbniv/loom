# Model-scale arm (14B) — results

**Plan:** [2026‑08‑27‑model‑scale‑arm](../plans/2026-08-27-model-scale-arm.md) §2.1 (pre‑registered)
**Model:** Qwen2.5‑Coder‑14B‑Instruct GGUF Q4_K_M · **Hardware:** g2‑standard‑4 L4 24 GB (on‑demand — see provenance) ·
**Condition:** `gbnf+typemask` · curated store · `address_book: full` · `generation_protocol: holes` ·
`fill_gate: well‑scoped` · 2 blocks × 16 cells (8 tasks × seeds 1–2) · purse 4,608 tok/cell
**Selection:** [`experiment.scale_compare`](../../prototype/experiment/scale_compare.py) (E1/E2/S1 verdict, exit 3).
Reads against the banked 7B pilot: [Stage 0 pilot report](2026-08-27-hole-elicitation-pilot-report.md).
Raw records: `prototype/runs/scale14-{b0,b2}/records.jsonl`.

**One variable moved.** Same family, same instruction format, same Q4_K_M
quantization, same tokenizer, byte-identical configs but `output_dir`. Parameter
count is the only difference from the banked 7B blocks.

## Pre-launch gates

**Compatibility gate (deliverable 1): PASS.** The type mask is built over the
vocabulary, so a different tokenizer would silently invalidate every comparison
in §2.1. Three independent reads agree on `n_vocab 152064` — the banked 7B
telemetry, a live 7B load, and a live 14B load. Both 14B block reports carry
`Vocabulary: 152064 tokens` in their masking sections, so the mask ran over the
same vocabulary on both sides of the comparison. §1's memory arithmetic held on a
real load: 14B ran the full 32k context on the L4's 24 GB with no `n_ctx`
reduction, so §7's second contingency never fired.

**CPU stub gate (deliverable 3): PASS, 12/12**, re-run unchanged as a regression
check; its output is pasted in the plan. §1's stated gap stands as written — check
1d validates the seven shipped configs and does not know about `scale14_b0` /
`scale14_b2`, which are covered by `test_scale_arm.py` instead.

## Provenance

Two instance inserts, both recovered from the Compute operations log and Cloud
audit logs (times PDT, ‑07:00):

| time | event |
|---|---|
| 23:15:19, 2026‑08‑26 | insert #1 — `provisioningModel: SPOT`, `preemptible: true`, `instanceTerminationAction: DELETE`; DONE 23:16:12 |
| 23:16:14 | `compute.instances.preempted` — ≈ 2 s after the instance became ready, **before any arm work started** |
| 23:24:19 | insert #2 — `provisioningModel: STANDARD`, `preemptible: false`: §4's pre-committed on-demand fallback; ready 23:24:31 |
| 04:04:16, 2026‑08‑27 | `compute.instances.guestTerminate`; stopped 04:04:59 — the runner shut itself down on completion |

Only two inserts exist: after the single preemption the driver went straight to
on-demand rather than retrying Spot. Both arms ran sequentially on that one
instance and both per-arm status markers in the artifacts bucket read `SUCCEEDED`.

**Reproducibility note.** The serial console could not be read after the fact —
`get-serial-port-output` returns "not ready" on a stopped instance — so the trail
above comes from the operations and audit logs rather than from boot output. Read
the console live, or capture it to the bucket, if a future run needs boot-time
evidence.

## The verdict, executed

`python3 -m experiment.scale_compare`, run from `prototype/`, verbatim (the
`python3 experiment/scale_compare.py` form fails on a relative import; `-m` is the
working invocation). It exits 3.

```
### Model-scale arm — 14B against the banked 7B

block                       draws  qualify  draw_rate  wilson_lo    cells  cell_rate    E1
§3-block (B0, reference)      202        0     0.00%      0.00%     0/16      0.00%  fail
hole-required (B2)            198        3     1.52%      0.61%     3/16     18.75%  fail

Gate E1 bar: one-sided 95% Wilson lower bound >= 10%. Stated on the bound, not the point estimate (§2.1).

### Gate E2 — assembly liveness, pooled across both blocks

  4 fill draws, 0 spliced into a four-layer-accepted assembly.
  Gate E2: NOT CLEAR

### S1 — scale comparison, B2@14B vs banked B2@7B

  14B: 3/198 = 1.52%   7B: 10/174 = 5.75%
  one-sided Fisher exact, alpha = 0.05: p = 0.9947   not significant
  Reported only. §2.1 measured S1's power at a doubled rate as 0.54,
  so no §6 row is keyed to this p-value.

### Verdict

  No block clears E1 and B2 sits at 1.52%, below the 11.5% descriptive threshold (§6 row 3).
  Scale is not the lever at any size reachable from here. Stop the scale
  track; hand back the feedback-legibility lever (2026-08-26 §2.4).
```

## Gate E1 — fill-reaching draw rate per block

**No block clears**, on the same bar as the pilot: one-sided 95 % Wilson lower
bound ≥ 10 %, stated on the bound. The reference block produced **zero**
fill-reaching draws in 202; the strongest measured pressure produced **three** in
198, a bound of 0.61 %, one sixteenth of the bar.

**Why B2's cell rate (18.75 %) is so much larger than its draw rate (1.52 %), and
why it is not a second result.** The two numbers count different things. Three
qualifying draws landed in three *distinct* cells, so the cell rate is
3/16 = 18.75 % — the largest value three qualifying draws can produce, since no
cell got a second one. A cell rate that high on three draws says only that the
three were spread rather than clustered; it carries no evidence that any cell
sustained hole-directed behaviour. §2.1 states E1 on the draw-level bound for
exactly this reason, and the pair is read that way here. Against the banked 7B,
the cell rate moved the same direction as the draw rate: B2@7B was 8/16 = 50 %,
B2@14B is 3/16 = 18.75 %.

## Gate E2 — assembly liveness, pooled

**NOT CLEAR.** Four fill draws across both blocks, **none spliced into a
four-layer-accepted assembly**; all four are recorded as `fill-rejected` in the B2
block report, and B0 took no fill draws at all. This repeats the pilot's zero on a
smaller population (4 fills here, 31 across the pilot's four blocks) and adds
nothing beyond the plan's §1.2 standing prediction. §6's fourth row — E2 clearing
while E1 fails — did not fire.

## S1 — scale comparison, and what the direction does and does not license

B2@14B is 3/198 = 1.52 %; the banked B2@7B is 10/174 = 5.75 %. One-sided Fisher
exact in the pre-declared *scale helps* direction gives p = 0.9947. **This is
reported, not decided on** (§2.1), and no §6 row is keyed to it.

The plan's §6 anticipated a flat result. What arrived is below baseline, and that
distinction needs stating precisely, because the report must not be readable as a
claim about inverse scaling:

- **What it licenses.** Exactly what a flat result would have licensed, and no
  more: §6 row 3's trigger is descriptive — B2@14B below 11.5 % — and 1.52 % is
  below it by the same logic that 5.75 % or 0.00 % would have been. The scale
  track stops.
- **What it does not license.** It is **not** evidence that scale *hurts*
  hole-elicitation. The p-value near 1 is an artefact of testing a one-sided
  hypothesis against a point estimate that moved the other way; it is not a test
  of the reverse hypothesis, and no reverse test was pre-registered. §2.1 measured
  S1's power at 0.54 against a *doubled* rate; nothing was measured about its
  power against a decrease, and no such measurement exists. At 3/198 against
  10/174, both arms sit near the floor, and sampling variation at these counts is
  large relative to the gap. Anyone extending this line should treat 7B and 14B as
  **both null on holes**, not as two points on a downward slope.

One reading is consistent with the telemetry below without being established by
it, and is recorded as a hypothesis rather than a finding: 14B's accepted-skeleton
rate is three to four times the 7B's, so a larger share of its draws ended in
complete, accepted, hole-free definitions — a model that finishes the definition
has fewer occasions to leave a hole. Nothing in this arm was designed to test
that, and it is not offered as one.

## Protocol telemetry (plan §4.6), carried over from the pilot

Reported, not leaned on — these are the numbers that say whether the protocol
actually ran. §4.6's own rule is that an accepted-skeleton rate below 20 % means a
null primary indicates a **starved** protocol rather than a refuted one.

| | B0@7B | B0@14B | B2@7B | B2@14B |
|---|---|---|---|---|
| Rounds | 190 | 202 | 174 | 198 |
| Accepted skeletons | 12 (**0.063**) | 40 (**0.198**) | 9 (**0.052**) | 43 (**0.217**) |
| Hole-required notes (§2.2 B2) | — | — | 42 | 44 |
| Holes per accepted skeleton | 0.083 | 0.05 | 0.0 | 0.07 |
| Holes per candidate | 0.026 | 0.01 | 0.069 | 0.056 |
| Bare-hole drafts (§3, unfilled by rule) | 1 | 2 | 0 | 3 |
| Fill draws (spliced) | 3 (0) | 0 (0) | 10 (0) | 4 (0) |
| Completion tokens, skeletons / fills | 65,140 / 882 | 63,753 / 0 | 62,579 / 3,088 | 61,636 / 2,188 |

Two things this table settles.

**The starvation escape hatch is closed at 14B.** At 7B, both blocks sat at
5–6 % accepted skeletons, far under §4.6's 20 % line, so "the protocol was
starved" remained an available reading of the pilot's null. At 14B both blocks
clear it — 19.8 % and 21.7 %, roughly a 3.1× and 4.2× improvement — while the hole
rate went to zero and 1.52 % respectively. **Scale plainly improved the model on
the ordinary protocol and did nothing for holes.** That is a stronger null than
the pilot's, not a weaker one.

**The B2 pressure fired, as it did at 7B.** 44 hole-required notes were added at
14B against 42 at 7B, so the difference between the blocks is not that the demand
note went missing. The reference block's response to it is the whole gap: B0@14B
recorded 0.01 holes per candidate and took no fill draws at all.

All four unfillable holes in B2@14B carry the same v1 boundary as the pilot's — a
hole under a `match` binder needs the scrutinee's synthesized type, which is
`[mask-spine-refs]`'s machinery, not this plan's.

**Not scored here.** The R3 mechanical-floor "semantic" count rose sharply too (1
cell per block at 7B; 8 cells per block at 14B). It is deliberately not used
above: the pilot's hand rubric found that two of three unique mechanical-floor
surfaces were extensional shortcuts that **FAIL** against verified gold, so the
floor overstates. Both 14B block reports carry `R3's hand-scored rubric … is
outstanding for 42 draws`, and this arm did not run it — the arm's question is
E1/E2, and hand-scoring 84 draws is not on its critical path. It is left
outstanding by rule, not by omission.

## Verdict, per §6's pre-committed table — row 3

**E1 fails at both blocks and B2@14B (1.52 %) is below the 11.5 % descriptive
threshold. Scale is not the lever at any size reachable from here.** Hole-directed
decomposition did not appear when the only variable moved was parameter count, and
it did not appear even though the same model got substantially better at the
ordinary protocol on the same run. **Stop the scale track.**

**Consequence for the 32B arm, stated explicitly: it is not licensed, and it does
not become licensed by an A100 quota grant.** §1 gated 32B on *this arm's result
plus* a quota grant; §6 row 2 is the only row that would have licensed it, and it
required E1 to fail *with* B2@14B ≥ 11.5 % and B0 < B2 — a measured 7B→14B slope
to size the extrapolation with. There is no such slope: B2 moved down, not up, and
§6 row 3 governs. The ≈ $27 A100 run is therefore not bought, and the A100 quota
request goes back to being a background errand rather than a priority. §6 row 3's
instruction is explicit — do not buy a 32B run on the strength of two nulls; three
now.

**Handing the track back.** Per §6 row 3 and the pilot report's row 1, the
feedback-legibility lever (2026‑08‑26 §2.4) is the live question. It is already
landed and measurable at zero extra GPU cost in any future arm.

## Cost, against §4's table

| item | §4 estimate | actual |
|---|---|---|
| Spot attempt (preempted at ≈ 2 s) | $0.25/h | negligible (≈ 1 min) |
| On-demand run, 23:24:31 → 04:04:59 = 4.68 h @ $0.85/h | ≈ $4.42 all-on-demand | **≈ $3.97** |
| **Total against the $4.50 ceiling** | **$1.30 all-Spot / ≈ $4.42 all on-demand** | **≈ $3.97 — under the ceiling** |

Under budget, and under §4's own all-on-demand scenario — but for the right reason
stated plainly: **the run came in shorter than the modelled 5.2 h, not because the
rate was better.** It paid the full on-demand rate for all but a minute of its
life.

**Throughput — §4 called this the estimate most likely to be wrong, and it was
right.** §4 modelled ≈ 8.5 tok/s from the pilot's measured 16.7 tok/s and the
1.92× weight-byte ratio:

| block | completion tokens | elapsed | measured |
|---|---|---|---|
| B0 | 63,753 | 7,471.4 s | **8.53 tok/s** |
| B2 | 63,824 | 7,489.3 s | **8.52 tok/s** |

Within 0.4 % of the model on both blocks. §4's "stop after B0 if measured tok/s is
below 6" rule never came close to firing, and §6's fifth row did not fire.
Overhead — boot, model load and build-cache restore — was 4.68 h wall minus 4.16 h
of summed arm elapsed = **0.52 h**, against §4's 0.4 h estimate; the
memory-bandwidth model transferred cleanly and the fixed overhead was the mildly
optimistic line.

## Teardown

Torn down through the driver's own default scope: `terraform apply -var
launch_runner=false` in `infrastructure/gcp/experiment-diversity`, the root that
owns this runner.

```
Apply complete! Resources: 0 added, 0 changed, 1 destroyed.
```

Verified after the apply:

- `gcloud compute instances list` → `Listed 0 items`
- `gcloud compute disks list` → empty, so the 150 GB boot disk went with the
  instance rather than being orphaned.

The artifacts bucket `gs://loom-diversity-artifacts-19b81040/` is **deliberately
left standing**: the bucket and its IAM bindings survive an instance-scope
teardown, and its objects expire on a 7‑day lifecycle rule. Both arms' results
were fetched to `prototype/runs/scale14-b0` and `prototype/runs/scale14-b2` before
teardown, and both per-arm status markers in that bucket read `SUCCEEDED`.

## Process defect — the driver never fetched the results

Recorded plainly because it nearly cost the run. Both arms completed and uploaded,
and both per-arm status markers read `SUCCEEDED` — but **nothing landed in
`prototype/runs/`**. The results sat in GCS uncollected and were pulled by hand
this session, roughly 7 h after the run finished. Had anyone assumed the bucket's
7‑day lifecycle rule was the only clock, that would still have been true here; the
cost was 7 h of a dead instance's results being invisible, not data loss.

**No cause is offered, because the evidence to establish one does not exist.** The
driver process is long gone, and there is no local driver log for this run —
`prototype/runs/logs/` holds only the *pilot's* `startup-script.log`. The serial
console is likewise unreadable on a stopped instance (see provenance). What is
missing is the driver's own log for this run; without it, any mechanism would be a
guess. The pilot, by contrast, recorded per-arm fetch on the first try, so this is
a change in behaviour between two runs of the same driver and is worth a real
diagnosis before the next GPU spend — starting with keeping the driver log.
