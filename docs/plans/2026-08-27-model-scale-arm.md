# Model-scale arm — does elicitation appear at 14B?

Discharges `[model-scale-arm]`, opened by
[2026‑08‑26 hole-elicitation](2026-08-26-hole-elicitation.md) §6 row 1 and
anticipated by 2026‑08‑25 §6 row 3. Reads against the
[Stage 0 pilot report](../results/2026-08-27-hole-elicitation-pilot-report.md).

**The question.** The pilot established that Qwen2.5‑Coder‑7B‑Instruct will not
write holes at a usable rate under any of three pressures. §6 row 1 called that a
finding about *the model and the surface*, not about decomposition. This arm tests
the model half of that disjunction: **does hole-elicitation appear when only the
parameter count changes?**

---

## 1. Why 14B, and why not 32B

The obvious reading of "model-scale arm" is Qwen2.5‑Coder‑**32B**, the top of the
family. That is not the recommendation, for one hard reason and one good one.

**Hard: 32B is not purchasable in this project today.** Measured, not assumed:

```
NVIDIA_A100_GPUS          us-central1   0.0
NVIDIA_A100_80GB_GPUS     us-central1   0.0
PREEMPTIBLE_NVIDIA_A100_GPUS            0.0
NVIDIA_L4_GPUS            us-central1   1.0
```

32B at Q4_K_M is 19.85 GB of weights. With a 32k KV cache and compute buffers it
does not fit an L4's 24 GB, so it needs an A100‑class card, and the quota for every
A100 SKU here is zero. A quota increase is a days-long request against a
trial-credit project, with no guarantee of grant.

**Good: 14B is the right *first* step regardless of quota.** It is the only step
that changes exactly one variable. Same family, same instruction format, same
Q4_K_M quantization, same tokenizer — so the GBNF grammar and the per-token type
mask carry over untouched. And it is the measurement that tells us what a 32B run is
worth: a flat 14B result makes ≈ $27 of A100 time a poor bet, while any movement
gives a slope to size the next step with. Sequencing 14B first is the decision-
theoretically correct order even in a world with unlimited A100 quota.

**The 32B arm is not abandoned** — it is gated on this arm's result plus a quota
grant, and §6 says exactly what result would license it.

### It fits the card, with numbers

| | 7B (banked) | 14B (this arm) |
|---|---|---|
| Layers / KV heads | 28 / 4 | 48 / 8 |
| Q4_K_M weights | 4.68 GB | 8.99 GB |
| KV cache @ 32k ctx, f16 | ≈ 1.6 GB | ≈ 6.4 GB |
| Weights + KV + buffers | ≈ 8 GB | **≈ 17 GB** |
| L4 capacity | 24 GB | 24 GB |

Comfortable, but not so comfortable that it goes unchecked — deliverable 1 confirms
it on the instance before any arm work.

---

## 2. Design

Two blocks, not four. The pilot's four blocks spanned a fill-reaching draw rate of
1.58 % (B0) to 5.75 % (B2); this arm carries **both ends and drops the middle**:

| Block | Role here |
|---|---|
| `§3-block` (B0) | reference — the protocol with no elicitation pressure |
| `hole-required` (B2) | the strongest pressure measured at 7B, and the one whose demand note demonstrably fired (42 notes, 2.7× reference holes-per-candidate) |

`exemplar` (B1) is dropped because its measured effect at 7B was on *skeleton
acceptance*, not on holes — it added 3 fill draws over the reference while adding 7
accepted skeletons. `checker-holed` (B3) is dropped because it is barred from
selection by pre-commitment and answers a different question (what the checker can
place, not what the model will).

Everything else is held byte-identical to the pilot: 8 tasks × seeds 1–2 = 16 cells
per block, `gbnf+typemask`, held-out regime, `leave_one_out`, purse 4,608 tok/cell,
`fill_gate: well-scoped`, `address_book: full`, `generation_protocol: holes`,
pruners pinned to `goal-type, de-bruijn, ref-hash`. **32 cells total.**

### 2.1 Gates, fixed before launch

- **E1 (unchanged from the pilot):** fill-reaching draw rate, one-sided 95 % Wilson
  lower bound **≥ 10 %**, per block. Stated on the bound, not the point estimate.
- **E2 (unchanged):** at least one fill draw splices into a four-layer-accepted
  assembly, pooled across both blocks.
- **S1 (new, the scale test):** B2@14B vs B2@7B fill-reaching draw rate, one-sided
  two-proportion test at α = 0.05, direction pre-declared as *scale helps*. The 7B
  side is the banked `pilot-b2` record (10/174), read as fixed, not re-run.

**S1 is a screen, not a confirmatory test, and the plan says so before it runs.**
At n ≈ 174 draws per side and a 5.75 % baseline, S1 has adequate power only against
a roughly doubled rate; a true effect of +2–3 points will not reach α = 0.05 here.
Deliverable 4 computes the exact powered MDE with the existing
`corpus_size_sweep_power.py` helper and pastes it into this file **before launch**,
so the arm's blind spot is on the record rather than discovered in the report.

### 2.2 No peeking

Blocks, gates, bar, α, direction, cell count, purse and the 7B comparison record are
all fixed above. Any change is filed here, before the first draw, with the defect
stated.

---

## 3. Deliverables

1. **The 14B GGUF, fetched and verified** — `qwen2.5-coder-14b-instruct-q4_k_m.gguf`,
   size exactly 8,988,110,272 bytes, plus a **`vocab_size == 152064` check against
   the banked 7B telemetry**. This is the compatibility gate: the type mask is built
   over the vocabulary, so a different tokenizer would silently invalidate every
   comparison in §2.1. Also confirms the §1 memory arithmetic on a real load.
   *(T1 — mechanical, but the vocab assertion is the whole point of it.)*
2. **`scale14_b0.config.json`, `scale14_b2.config.json`, `scale14-runlist.json`** —
   byte-copies of `pilot_b0` / `pilot_b2` with only `output_dir` changed. The model
   identity and backend seam are rewritten on the instance, as always. *(T1.)*
3. **CPU stub gate** — re-run `hole_elicitation_stub_check.py` unchanged and paste
   the output here. The protocol is untouched by this arm, so this is a regression
   check, not a new gate; it is still the thing that stands between us and GPU spend.
   *(T1.)*
4. **Powered MDE for S1** — via `corpus_size_sweep_power.py`, pasted into §2.1
   before launch. *(T2.)*
5. **`experiment/scale_compare.py`** — reads `runs/scale14-b0`, `runs/scale14-b2` and
   the banked `runs/pilot-b0`, `runs/pilot-b2`, prints E1 per block, E2 pooled, and
   the S1 two-proportion result, and exits on a code per §6's row. The verdict is
   executed, not judged — same discipline as `pilot_select.py`. Its on-screen output
   is the arm's only visible surface; the mockup is §5. *(T2.)*
6. **The run** — §4. *(T5, driven inline.)*
7. **Report** — `docs/results/2026-08-2X-model-scale-arm-report.md`: gate verdicts,
   the §4.6 telemetry carried over from the pilot, the §6 row that fired, cost and
   teardown evidence. *(T3.)*

Deliverables 1–5 are CPU-only and gate the GPU spend. **Nothing launches until 3's
output is in this file.**

---

## 4. Cost

`g2-standard-4` (L4 24 GB), us‑central1, **Spot first with the pre-committed
on-demand fallback** — the exact shape the pilot used, and the reason the pilot
survived two preemptions without a decision being needed mid-run.

Throughput is the estimate most likely to be wrong: 14B Q4_K_M is 1.92× the 7B's
weight bytes, and decode here is memory-bandwidth-bound, so the pilot's measured
16.7 tok/s is modelled as **≈ 8.5 tok/s**. Model load is also slower.

| Line | Quantity | Rate | Hours |
|---|---|---|---|
| 32 cells × 4,608 tok purse | 147,456 tok | 8.5 tok/s | 4.8 h |
| Boot, model load, build-cache restore | | | 0.4 h |
| **Total** | | | **≈ 5.2 h** |

| Scenario | Unit price | Cost |
|---|---|---|
| All-Spot, no preemption | $0.25/h | **$1.30** |
| All on-demand (the pilot's actual outcome) | $0.85/h | **≈ $4.42** |
| **Budget ceiling for this arm** | | **$4.50** |

If the first arm's measured tok/s comes in below 6, the run is stopped after B0 and
re-sized rather than allowed to run long — a rule fixed here so it is not a judgment
call at 03:00.

---

## 5. Mockup — `scale_compare.py` output

The arm's only visible surface is one CLI table. Target shape:

```
### Model-scale arm — 14B against the banked 7B

block                    draws  qualify  draw_rate  wilson_lo   cells  cell_rate    E1
§3-block (B0)              ---      ---      --.--%     --.--%   --/16     --.--%  ----
hole-required (B2)         ---      ---      --.--%     --.--%   --/16     --.--%  ----

E1 bar: one-sided 95% Wilson lower bound >= 10%.

### Gate E2 — assembly liveness, pooled
  <n> fill draws, <m> spliced into a four-layer-accepted assembly.
  Gate E2: <CLEAR|NOT CLEAR>

### S1 — scale test, B2@14B vs B2@7B (banked, 10/174 = 5.75%)
  14B: <q>/<n> = <r>%   7B: 10/174 = 5.75%
  one-sided two-proportion, alpha=0.05: p = <p>   <significant|not significant>
  powered MDE at this n (deliverable 4): <mde>%

### Verdict
  <the §6 row, named>
```

---

## 6. What each outcome licenses

| Outcome | What it licenses next |
|---|---|
| **E1 clears at 14B** | Elicitation is a scale phenomenon and 7B was simply below threshold. The lever is alive: re-open Stage 1's design against 14B, and make the A100 quota request a priority rather than a background errand. |
| **E1 fails, S1 significant** | Scale moves elicitation but not far enough at 14B. This is the row that licenses **32B**: the measured 7B→14B slope sizes the extrapolation, and the ≈ $27 A100 run becomes a bet with a number behind it rather than a hope. Request quota and re-plan. |
| **E1 fails, S1 not significant** | Scale is not the lever at any size reachable from here. **Stop the scale track** — do not buy a 32B run on the strength of two nulls. Hand back the feedback-legibility lever (2026‑08‑26 §2.4), which is already landed and measurable at zero extra GPU cost in any future arm. |
| **E2 clears while E1 fails** | Rare and informative: fills are reaching assembly at a low rate. Report it as the first live fill evidence in the campaign and re-read §1.2's blame analysis against a non-empty population. |
| **Measured throughput < 6 tok/s** | Stop after B0 and re-size per §4. Not a finding, a budget rule. |

---

## 7. What would change this plan

- **The vocab check fails** (deliverable 1). The type mask is not portable to this
  model and the whole comparison is invalid. Stop; the arm needs a different design,
  not a workaround.
- **14B does not fit 24 GB in practice** despite §1's arithmetic. Drop `n_ctx` only
  as a last resort and file it — context length is not a free variable, it changes
  what the model can see of the address book.
- **A100 quota is granted before this arm runs.** Do not skip 14B. The sequencing
  argument in §1 is independent of availability, and the 7B→14B slope is what makes
  a 32B result interpretable rather than a lone data point.
- **Someone lands a pruner or touches `prompts.py`.** Every config in this arm and
  the banked pilot must be re-verified as pinned before the comparison in §2.1 means
  anything. *(Inherited from 2026‑08‑25 §9, still live.)*
