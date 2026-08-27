# Hole-elicitation pilot (Stage 0) — results

**Plan:** [2026‑08‑26‑hole‑elicitation](../plans/2026-08-26-hole-elicitation.md) §4.2 (pre‑registered)
**Model:** Qwen2.5‑Coder‑7B‑Instruct GGUF Q4_K_M · **Hardware:** g2‑standard‑4 L4 24 GB (on‑demand — see provenance) ·
**Condition:** `gbnf+typemask` · curated store · `address_book: full` · `generation_protocol: holes` ·
`fill_gate: well‑scoped` · 4 blocks × 16 cells (8 tasks × seeds 1–2) · purse 4,608 tok/cell
**Selection:** [`experiment.pilot_select`](../../prototype/experiment/pilot_select.py) (E1/E2 verdict);
rubric by execution via [`experiment.decomp_hand_score`](../../prototype/experiment/decomp_hand_score.py).
Raw records: `prototype/runs/pilot-{b0,b1,b2,b3}/records.jsonl`.

**Provenance.** Three instances. Spot attempts one and two were preempted 29 and
3 minutes after creation (evening us‑central1‑a — effectively stocked out, the
2026‑08‑23 pattern), before any arm work; the pre‑committed fallback then ran the
whole pilot **on‑demand, non‑preemptible**: four arms sequential, ≈55 min each,
all four `SUCCEEDED`, per‑arm fetch on the first try, instance self‑removed and
the root + bucket destroyed and 404‑verified. The pilot ran with the
feedback‑legibility fix (`8ed72cd`) already landed — every narrowing note the
model saw was a canonical type surface, so the elicitation pressure below was
applied on top of legible feedback, not instead of it.

## Gate E1 — fill-reaching draw rate per block

```
block                         draws  qualify  draw_rate  wilson_lo   cells  cell_rate    E1
§3-block (B0, reference)        190        3     1.58%      0.63%   3/16      18.75%  fail
exemplar (B1)                   204        6     2.94%      1.53%   4/16      25.00%  fail
hole-required (B2)              174       10     5.75%      3.47%   8/16      50.00%  fail
checker-holed (B3, diagnostic)    180        3     1.67%      0.67%   3/16      18.75%  fail
```

Bar: one‑sided 95 % Wilson lower bound ≥ 10 %, stated on the bound, not the
point estimate. **No block clears.** The strongest pressure — B2's explicit
hole‑demand feedback — multiplied the reference rate 3.6× and still sits at a
third of the bar; the worked exemplars (B1) less than doubled it. Fill draws
actually taken per arm: 3 / 6 / 10 / 12.

## Gate E2 — assembly liveness, pooled

**NOT CLEAR.** Across all four blocks, 31 fill draws were taken and **not one
spliced into a four‑layer‑accepted assembly.** This is the outcome the plan's
own §1.2 predicted: a hole does not make the surrounding committed structure
any righter, and fills cannot repair a draft that was wrong around the hole.

## Verdict, per §6's pre-committed table — row 1

**Hole‑directed decomposition is not elicitable at this model scale under
prompt or feedback pressure.** That is a finding about the model and the
surface, not about decomposition in the abstract. **Stage 1 is not launched;
≈ $4.55 is not spent** — which was the pilot's entire purpose. Row 1's two
pre‑named next steps: (1) the model‑scale arm (2026‑08‑25 §6 row 3) moves onto
the table as an honest question; (2) the feedback‑legibility lever — already
landed before this run, so its standalone effect on the standard protocol is
now the cheaper open question, measurable in any future arm at zero extra cost.

E2's zero is reported alongside but row 1 governs: with E1 failed everywhere,
the 31 fills are too few to constitute a test of assembly, and no conclusion
beyond §1.2's standing prediction is drawn from them.

## Hand rubric (row 8: every candidate, by execution)

Unique mechanical‑floor surfaces across the pilot, scored differentially
against verified gold on the reference interpreter:

| arm | task | surface | verdict |
|---|---|---|---|
| b0 (+b2, b3 dup.) | `list/sum` | `λxs. List.size xs` | **FAIL** (length ≠ sum) |
| b1 | `list/reverseThen` | new recursive surface | **FAIL** (mismatch on 2 of 3 inputs) |
| **b1** | `list/mapLength` | `λf. λxs. List.size xs` | **PASS** — the extensional shortcut again (map preserves length), *not* a composition |

Hand‑scored semantic cells: b0 0, **b1 2** (seeds 1 and 2, same shortcut
surface), b2 0, b3 0. No new composition. One secondary worth recording: the
exemplar arm had the most accepted skeletons (19 vs 12/9/12) and by far the
most floor candidates — the worked examples helped *general* acceptance more
than they helped holes.

## Cost

| item | est. (§5) | actual |
|---|---|---|
| Spot attempts 1–2 (preempted at 29 min / 3 min) | — | ≈ $0.15 |
| On‑demand pilot (boot + 4 arms, ≈4.2 h @ $0.85/h) | — | ≈ $3.57 |
| Storage + egress | < $0.02 | < $0.02 |
| **Total** | **≈ $1.30 spot** | **≈ $3.74** (on‑demand fallback) |

Stage 1's ≈ $4.55 unspent. Net campaign effect of the pilot design: the
question "can elicitation fix the starvation?" was answered **no** for $3.74
instead of being discovered inside a $5.90 confirmatory run.
