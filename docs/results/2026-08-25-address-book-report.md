# Address-book run — results

**Plan:** [2026‑08‑24‑next‑lever](../plans/2026-08-24-next-lever.md) §4 (pre‑registered), as amended by
[Amendment A1](../plans/2026-08-24-next-lever.md#amendment-a1--addr-typed-leaves-the-holm-family-2026-08-25-pre-data) (pre‑data, 2026‑08‑25)
**Model:** Qwen2.5‑Coder‑7B‑Instruct GGUF Q4_K_M · **Hardware:** g2‑standard‑4 L4 24 GB ·
**Backend:** llama‑cpp in‑process · **Condition:** `gbnf+typemask` · `n_ctx` 32,768 ·
curated‑only store (26 definitions / 47 objects) · budgets per §4.3: 8 draws × 768 tokens, no fragments
**Analysis:** [`experiment.address_book_analysis`](../../prototype/experiment/address_book_analysis.py), which
reuses the audit's route machinery so every arm number shares a code path with the
12/4,135 baseline. Raw records: `prototype/runs/addr-{none,full,typed}/records.jsonl`.

**Provenance.** Two spot instances. The first ran `addr-none` to success
(marker 18:31 UTC, 2026‑08‑25) and was **preempted by GCP at 19:02 UTC**
(`compute.instances.preempted` in the operations log), 31 minutes into
`addr-full`; the per‑arm incremental upload preserved the finished arm. A
committed two‑arm resume runlist re‑ran `addr-full` and `addr-typed` on a
second spot instance (markers 02:39 and ~03:51 UTC, 2026‑08‑26; final runlist
status `SUCCEEDED`). Every §4.2/§4.3 config field was byte‑identical across
both instances; no test was computed and no arm metric was examined until all
three arms were banked. Teardown verified: instance self‑removal plus a full
`terraform destroy` of the diversity root (4 resources), bucket 404‑confirmed,
zero instances left.

## Harness health

Every cell in every arm ran **exactly 8 draws at the full 768‑token cap** (the
§4.3 fix, commit `048a6c9`). Truncated‑draw fractions: `addr-none` 7.5 %,
`addr-full` 3.8 %, `addr-typed` 5.9 % — all under §4.3's 10 % censoring
threshold, so the run is **not censored** and the primary is reported
unflagged. Prompt tokens per arm: 11,952 / 18,810 / 12,597–14,490 mean 14,169,
against §4.2's ≈ 12.0k / 18.1k / 14.3k estimates.

## Primary — H1, per Amendment A1

**Route‑reference rate** (share of draws whose `(ref 0x…)` set contains every
element of the task's `composes` route), `addr-full` vs `addr-none`, one‑sided
Fisher exact, α = 0.05, no Holm:

| variant | addr-none | addr-full | p (one‑sided) |
|---|---|---|---|
| §4.5 letter — externs included | 1/320 (0.31 %) | 10/320 (3.13 %) | **0.00553** |
| baseline‑consistent — definitions only | 1/320 (0.31 %) | 12/320 (3.75 %) | **0.00156** |

**The primary is significant on both variants.** (§4.5's parenthetical
"definitions and externs alike" conflicts with how the quoted 0.290 % baseline
was computed — definitions only, per the audit — so both are reported; the
concurrent control makes the choice non‑corrupting, and they agree.) Supplying
addresses raised the full‑route reference rate roughly **tenfold** over the
concurrent control, from one draw in 320 to 10–12. H1 is confirmed at the
first adequately‑powered attempt: **the model refs what it is shown and cannot
ref what it is not** — and when shown, it does.

The lone `addr-none` full‑route draw is `concatLength`, the single task whose
route was already addressable from the bare prompt (§1.2), exactly as the
diagnostic predicted.

## Exploratory — `addr-typed` (flagged per Amendment A1)

`addr-typed` is **route‑incomplete for 5 of 8 tasks** — its pre‑registered
§4.2 filter omits at least one route element for `concatLength`, `mapLength`,
`mapOrElse`, `headOrElse`, and `stampedBytes`; only `reverseThen`, `sum`, and
`selectNonNegative` carry complete routes (Amendment A1's table). Every
comparison below is two‑sided and licenses nothing on a loss.

| comparison | rates | p (two‑sided) |
|---|---|---|
| typed vs none — externs incl. | 21/320 vs 1/320 | 8.1e‑06 |
| typed vs full — externs incl. | 21/320 vs 10/320 | 0.064 |
| typed vs none — defs only | 25/320 vs 1/320 | 5.1e‑07 |
| typed vs full — defs only | 25/320 vs 12/320 | 0.041 |

**`addr-typed` beat `addr-full` in point estimate on both variants despite its
handicap** — with its hits concentrated almost entirely in its route‑complete
tasks (`reverseThen` 18/40, vs 6/40 under `addr-full`). Because the handicap
biases only *against* `addr-typed`, this is conservative evidence for §6's
fifth row: **retrieval, not presence, is what the context is short of.** A
35‑row wall of hex is itself a retrieval problem for a 7B; a 7–13‑row filtered
book is not. Per the pre‑committed reading, this promotes the spine‑aware mask
(§2.4) from follow‑up to lever — it is the same filter applied at decode time.

## Secondaries (§4.6 as amended)

- **Hand‑scored semantic success (R3 rubric): 0/320 in every arm.** One draw
  met the mechanical floor (`addr-full`, `heldout/list/sum`, seed 2 draw 4,
  `checked+type-exact`) and failed the rubric: the term is
  `lam xs. (List.size xs)` — the *length*, not the sum, passing the floor by
  type collision (`List I64 → I64`), the same recycling failure mode the
  powered held‑out report documented. Clopper–Pearson 95 % intervals:
  `addr-none` and `addr-typed` [0, 1.15 %], `addr-full` [0.01, 1.73 %] before
  hand‑scoring, [0, 1.15 %] after. The ≥ 5‑success threshold (A1) is not
  approached; per §4.7's fixed reading this is reported as a count, not a
  significance claim.
- **Any‑required‑reference rate** (≥ 1 route definition): 26 → 67 → 82 of 320
  (8.1 % / 20.9 % / 25.6 %) — baseline was 2.9 %.
- **Illegal‑`ref` rate** (a `(ref …)` at a data‑declaration hash): 7 / 3 / 17
  draws (2.2 % / 0.9 % / 5.3 %) against the 1.0 % baseline. The `addr-full`
  fall is consistent with the model guessing less when shown legal addresses;
  `addr-typed`'s rise is unexplained and recorded as an open observation —
  the typed book lists only `ref`‑legal objects, so these hashes still enter
  only through example bodies.
- **Funnel:** typecheck remains the dominant rejection everywhere
  (252 / 267 / 265 of 320); parse rejections track the truncation fractions.
- **acc/1k tok** (continuity only — **not comparable across arms**, the block
  changes the denominator by design): 0.061 / 0.031 / 0.072.

## Verdict, per §6's pre‑committed table

**Row 2: primary significant, semantic successes < 6.** The model can now
*reach* the right definitions but cannot *assemble* them. Addressing is
solved as a mechanism — the store's addresses belong in every future held‑out
prompt — and **composition is the residual**. The licensed next lever is
**hole‑directed decomposition** (plan §2.2), with the **spine‑aware mask**
(§2.4) as its companion, the latter independently promoted by the exploratory
`addr-typed` result above. The §7 consequences for archived results are
already applied — both 2026‑08‑24 reports carry correction addenda.

A null‑adjacent caution, fixed in advance (§4.7): at these n the semantic
secondary's zero is evidence against a ≥ 2 % per‑draw semantic rate under
addressing, not against smaller ones.

## Cost

| item | est. (§5) | actual |
|---|---|---|
| Spot compute, instance 1 (boot + `addr-none` + 31 min lost to preemption) | — | ≈ $0.55 |
| Spot compute, instance 2 (boot + `addr-full` + `addr-typed`) | — | ≈ $0.75 |
| Storage + egress | < $0.02 | < $0.02 |
| **Total** | **≈ $1.29 spot** | **≈ $1.31** |

The preemption cost ≈ 31 minutes of GPU re‑work and zero data, courtesy of
per‑arm incremental uploads. The driver's runlist‑mode fetch gap discovered
during the rescue is filed as `[runlist-partial-fetch]` in `TODO.md`.
