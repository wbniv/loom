# Corpus-size sweep — results

**Plan:** [2026‑08‑24‑corpus‑size‑sweep](../plans/2026-08-24-corpus-size-sweep.md)
**Model:** Qwen2.5‑Coder‑7B‑Instruct GGUF Q4_K_M · **Hardware:** g2‑standard‑4 L4 24 GB ·
**Backend:** llama‑cpp · **Condition:** `gbnf+typemask` · `n_ctx` 32,768 · temperature 0.8

**Provenance.** Runlist `sweep-runlist-20260824T162810Z`, four sequential arms
on one instance on the diversity root's own isolated Terraform state
(`infrastructure/gcp/experiment-diversity`), `us-central1-c`, 2026‑08‑24:

| arm | generated defs | status marker (UTC) |
|---|---:|---|
| `sweep-size08` | 8 | 17:36 |
| `sweep-size15` | 15 | 18:17 |
| `sweep-size25` | 25 | 19:01 |
| `sweep-size41` | 41 | 19:53 |

All four `SUCCEEDED`; the runlist self-deleted the instance at the end
(`runlist complete: 4/4 arms succeeded`, `finish: exit code 0, status
SUCCEEDED`). Results were copied into `prototype/runs/sweep-size{08,15,25,41}/`
(gitignored, as every prior run in this project) and the root — instance,
artifacts bucket, IAM — was **fully destroyed** afterward, per §3's teardown
rule. Record counts on disk: 255 / 251 / 254 / 272, matching the dispatch's
expectation exactly (each = full_corpus draws + held_out draws, e.g. sweep41
215 + 57 = 272). The **0‑def anchor** is the previously recorded
`followup-curated` run (2026‑08‑14, not re-run — reused per §2.2), whose
`full_corpus` 55/196 = 1.377 acc/1k tok and `held_out` 1/47 = 0.081 acc/1k tok
match the plan's citation exactly.

All five configs are byte-identical except `store_export`/`output_dir`
(§2.4); all four fresh arms drew from the same 78‑attempt, 3‑seed,
`full_corpus`+`held_out` matrix (102 cells each, confirmed in the
pre-registration's stub dry-run). No data contradicts the pre-registration:
task sets, seeds, and cell counts match across all five points, so the §2.7
test runs as specified with no substitution.

---

## 1. The four arms plus the anchor

| arm | generated defs | `full_corpus` accepted/draws | acc/1k tok | distinct | `held_out` accepted/draws | acc/1k tok | distinct |
|---|---:|---:|---:|---:|---:|---:|---:|
| `followup-curated` (anchor) | 0 | 55/196 | 1.377 | 9 | 1/47 | 0.081 | 1 |
| `sweep-size08` | 8 | 57/205 | 1.427 | 11 | 4/50 | 0.326 | 3 |
| `sweep-size15` | 15 | 61/201 | 1.527 | 11 | 1/50 | 0.081 | 1 |
| `sweep-size25` | 25 | 65/204 | 1.628 | 12 | 2/50 | 0.163 | 2 |
| `sweep-size41` | 41 | 76/215 | 1.903 | 15 | 5/57 | 0.407 | 4 |

**`full_corpus` acc/1k tok is monotone across all five points** —
1.377 / 1.427 / 1.527 / 1.628 / 1.903 — the cleanest version of the pattern
this sweep was built to test for. `held_out` acc/1k tok is not monotone
(0.081 → 0.326 → **0.081** → 0.163 → 0.407): sweep15 falls straight back to
the anchor's rate before climbing again at 25 and 41. At 1–5 accepted draws
per arm this is exactly the sampling noise §2.8 warned a small held-out cell
would carry, not a reversal of anything.

**One nuance the acc/1k tok column hides.** All five `full_corpus` cells
share the same fixed token budget (39,936 tokens; §2's shared-budget rule),
so acc/1k tok is proportional to the raw accepted count — but *not* to the
raw acceptance *rate*, because draws-to-exhaust-budget also grows with size
(196 → 205 → 201 → 204 → 215 draws). Per-draw accept probability (accepted /
draws, the quantity §2.7's Bernoulli trial actually is) dips slightly from
the anchor to `sweep08` — 0.2806 → **0.2780** — before climbing:

| defs | accepted | draws | per-draw rate |
|---:|---:|---:|---:|
| 0 | 55 | 196 | 0.2806 |
| 8 | 57 | 205 | 0.2780 |
| 15 | 61 | 201 | 0.3035 |
| 25 | 65 | 204 | 0.3186 |
| 41 | 76 | 215 | 0.3535 |

That dip is the reason the trend test below, run on this per-draw series
rather than on the smoother acc/1k tok curve, comes back weaker than the
acc/1k tok column alone would suggest.

---

## 2. The §2.7 trend test, run for real

Pre-registered method: pool every `full_corpus` draw across all five points
(1,021 draws total) as a Bernoulli outcome, fit
`logit(P(accepted)) = β0 + β1·log1p(defs)` by MLE, and test `H0: β1 = 0` via
the likelihood-ratio statistic against the intercept-only null (χ², 1 df,
two-sided, α = 0.05), Wald p-value on β1 reported alongside as the
pre-registered cross-check. Implementation:
[`prototype/experiment/corpus_size_sweep_analysis.py`](../../prototype/experiment/corpus_size_sweep_analysis.py),
which imports `_lr_test` from `corpus_size_sweep_power.py` rather than
reimplementing it, exactly as §2.7 specified.

```
$ python3 -m experiment.corpus_size_sweep_analysis
full_corpus draws pooled for the trend test:
  defs=  0  accepted=  55/196   rate=0.2806
  defs=  8  accepted=  57/205   rate=0.2780
  defs= 15  accepted=  61/201   rate=0.3035
  defs= 25  accepted=  65/204   rate=0.3186
  defs= 41  accepted=  76/215   rate=0.3535
  total draws pooled: 1021

LR test (H0: beta1=0, log1p(defs), alpha=0.05):
  p = 0.1280  -> not significant at alpha=0.05

Wald cross-check on beta1:
  beta1 = 0.0812  se = 0.0538  z = 1.5089  p = 0.1313  -> not significant at alpha=0.05
```

**Result: p = 0.128 (LR), p = 0.131 (Wald cross-check) — not significant at
α = 0.05.** The two agree closely, as expected for n this large. β1 is
positive (0.081), consistent in *direction* with the visibly monotone
acc/1k tok curve, but the trial-level signal does not clear the
pre-registered threshold.

**Pre-registered interpretation (§2.7–2.8), applied as written.** The plan
fixed, before any GPU run, that this test would run at ≈38% power under its
planning-assumption effect size (curated 0.2806 → generated‑41 0.3495,
log1p‑linearly interpolated) at the ~198‑draw/arm budget this sweep could
afford — well under the conventional 80% threshold — and it fixed the
reading in advance: *"A non-significant trend test at this budget is not
evidence against the mass hypothesis — it is close to a coin flip either way
under the planning assumption. … The report will state the result as 'trend
detected' / 'no trend detected — underpowered, not refuted' rather than
treating a null result as a refutation."* Applying that rule to p = 0.128:
**no trend detected — underpowered, not refuted.**

**Sample size a decisive answer would need (§2.8's required extrapolation,
now run against the *observed* rates rather than the planning assumption).**
Re-running the same LR-test power simulation with the five observed rates
above in place of the log1p‑linear interpolation, sweeping `n_per_arm`:

```
observed full_corpus per-draw rates: {0: 0.2806, 8: 0.278, 15: 0.3035, 25: 0.3186, 41: 0.3535}

actual n/arm this sweep produced: ~204 (196-215)
  n_per_arm=  204  power=0.326
  n_per_arm=  400  power=0.551
  n_per_arm=  800  power=0.837
  n_per_arm= 1200  power=0.959
  n_per_arm= 1600  power=0.990
  n_per_arm= 2000  power=0.998
```

At the actual budget this sweep ran (~204 draws/arm), power against the
*observed* effect size is **0.326** — close to, and consistent with, the
38% pre-registered estimate (the small discrepancy is the anchor→8-def dip
noted above, which shrinks the effective effect size a little below the
two-endpoint planning interpolation). Power crosses 80% at **≈800
draws/arm — roughly 4× this sweep's budget** — which is the number a
decisive answer would need. This is a sample-size projection, not a new
significance test: it reuses the same LR-test power machinery
(`trend_test_power`), does not touch α, and answers the question the
pre-registration (§2.8) committed to answering if the primary test came back
null. It is exploratory in the sense that it substitutes observed rates for
the planning assumption — it is not a new hypothesis test, and it changes no
conclusion above.

---

## 3. Hand-scoring — one held-out mechanical-floor candidate

Across all 11 `held_out`-regime accepted draws in the four fresh arms, ten
already carry an automatic semantic verdict (`semantic_rule:
checked+type-exact`, `semantic_success: false`, `"type mismatch"`) — they
fail a mechanical check, not an ambiguous one, so they need no hand-scoring.
Exactly **one** draw met the mechanical floor and reached
`rubric_pending: true`:

### `sweep-size41` · `heldout/list/reverseThen` · seed 2, draw 0

**Spec:** "The first list in reverse order, with the second list following
it." Type `List I64 -> List I64 -> List I64`; intended composition
`corpus/list/reverse` then `corpus/list/append`.

**Term** (identity `631d16b8e72b89c18916a091c177f83bb279711493bfbab909d4dea07a872514`):

```
(def (fn (data 0x2ee9…(I64)) () (fn (data 0x2ee9…(I64)) () (data 0x2ee9…(I64))))
     (lam (data 0x2ee9…(I64))
          (lam (data 0x2ee9…(I64))
               (let (data 0x2ee9…(I64)) (var 0) (var 1)))))
```

De-sugared: `λa. λb. let c = b in b` — it binds `c` to its second argument
and returns `c`, i.e. it **returns its second argument unchanged and
discards the first entirely**. No reversal happens; no append happens.

**Score: 0 — FAIL.** This is not a fresh judgement call: it is the identical
identity hash already on record. `harvest_select.py`'s own docstring names
`generated/corpus/list/append/631d16b8e72b` as "a two-argument function that
ignores its first argument — the exact skeleton the model then reproduced
for `heldout/list/reverseThen`," and the corpus-loop plan's 12-seed turn
already hand-scored this exact term `λa. λb. let c = b in b` **0** on this
exact task (`docs/plans/2026-08-14-corpus-loop.md`, "Turn 2 and the 12-seed
sample"). It has now recurred a third time, this time inside `sweep41`'s
41-definition store (drawn from the same 55-item pool `size-match` prefixes,
which apparently still contains this object at n = 41). The mechanical floor
(checked-tier + exact type match) cannot distinguish it from a correct
solution — type-correct, checker-accepted, semantically vacuous — exactly
the failure mode the R3 rubric exists to catch, and it caught it again.

**No other held-out candidate arose in any arm at any size.** Held-out
composition is unmoved by this sweep: 0 hand-scored successes across all
four fresh arms, same as the anchor and every other run this project has
recorded.

---

## Verdict

**"Acceptance tracks context mass" is still open — the pre-registration
licenses neither "established" nor "refuted."**

The descriptive pattern is now the cleanest it has ever looked in this
project: `full_corpus` acc/1k tok is monotone across all five points on one
pool, one deterministic ordering, one axis — 1.377 / 1.427 / 1.527 / 1.628 /
1.903 — with the mass-vs-quality confound from the diversity-harvest report
removed by construction (`chosen(n) ⊆ chosen(m)` for `n < m`, verified by
direct set inclusion, §2.1). But the pre-registered test built to tell a
real trend from run-to-run noise at this exact budget — the LR test on
pooled per-draw Bernoulli outcomes — comes back **p = 0.128, not
significant at α = 0.05**, and that test was known before any GPU ran to
have only ≈38% power against the project's own planning-assumption effect
size. A null result at 38% power is not evidence against the mass
hypothesis; per §2.7's own pre-committed reading, it is close to a coin flip
either way. **The correct statement, and the only one this pre-registration
licenses, is "no trend detected — underpowered, not refuted."**

What moved in this sweep's favor: β1 is positive (0.081, both LR and Wald
agree), the acc/1k tok curve is monotone rather than merely directional, and
the per-draw rate is also monotone across the four fresh arms (0.2780 →
0.3035 → 0.3186 → 0.3535) — it only dips once, between the anchor and the
smallest fresh arm. None of that clears α = 0.05 at this n, and none of it
should be read as more than what it is: a pattern consistent with the mass
hypothesis, in a design built specifically to isolate it from the
selection confound, that this budget cannot yet confirm.

Composition did not move. One held-out draw reached the mechanical floor in
254 held-out draws across four arms, and hand-scoring it against the R3
rubric returned the same FAIL this exact term has already returned twice
before on this exact task. Held-out semantic success remains at **zero**
across every run this project has recorded.

**What a decisive answer requires:** ≈800 draws/arm (≈4× this sweep's
budget) against the observed effect size, per the extrapolation in §2. That
is a concrete, falsifiable follow-up, not a design change — same pool, same
ordering, same test, more seeds.

## Addendum (2026‑08‑25)

This report's **held-out** results (the zero-successes headline, the
hand-scored `reverseThen` candidate in §3, and the reachability implicit in
"0 of 22 non-vacuous defs solve any held-out task") are undermined by two
defects documented in [next-lever plan §1](../plans/2026-08-24-next-lever.md):
the `held_out` prompt withholds the 64‑hex addresses a solution needs to
`(ref …)` — 7 of this project's 8 held-out tasks are unsolvable from that
prompt as built, regardless of store size or selection rule (§1.2) — and every
held-out cell here was terminated by a truncated final draw, leaving a median
of one usable draw per cell against gold answers that cost more tokens than
that (§1.3). The **`full_corpus`** halves of this report — the acc/1k tok
sweep in §1–§2, the monotone trend, the LR test and its verdict — are
**unaffected**: `full_corpus` censorship is flat across store sizes (§1.3) and
its conclusions stand as written above.
