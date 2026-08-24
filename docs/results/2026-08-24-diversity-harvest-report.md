# Diversity-seeking harvest — results

**Plan:** [2026‑08‑23‑diversity‑harvest](../plans/2026-08-23-diversity-harvest.md)
**Model:** Qwen2.5‑Coder‑7B‑Instruct GGUF Q4_K_M · **Hardware:** g2‑standard‑4 L4 24 GB ·
**Backend:** llama‑cpp · **Condition:** `gbnf+typemask` · `n_ctx` 32,768 · temperature 0.8
**Zone:** europe‑west4‑c (on‑demand; every other zone was STOCKOUT all morning)

| run | id | started (UTC) | elapsed |
|---|---|---|---:|
| `diverse-followup` | `div-diverse-followup-20260824T101056Z` | 2026‑08‑24T11:23:43Z | 2,610 s |
| `sizematch-followup` | `div-sizematch-followup-20260824T123150Z` | 2026‑08‑24T13:16:17Z | 2,440 s |
| `diverse-heldout12` | — | — | **still queued** (see below) |

> **Status: PARTIAL.** Runs 1 and 2 are complete and are scored below. Run 3
> (`diverse-heldout12`, 96 held-out attempts) has not landed — the launch
> wrapper is still cycling zones for L4 capacity. **The held-out verdicts and
> P1–P3 are left open**, and plan verification step 7 is not closed, until it
> does. The `full_corpus` contrast — the comparison this plan moved its power
> to — is complete and is not waiting on anything.

Both completed arms drew **identical budgets** — 78 full-corpus attempts / 198 draws /
39,936 tokens, and 24 held-out attempts / 54 draws / 12,288 tokens each — so the
comparison is exact rather than approximately matched.

---

## The headline: a clean null

**The diversity harvest changed nothing measurable, in either direction.** Every
pairwise comparison is non-significant, and the one directional signal is one
draw against three.

| metric | `diverse` (15 defs) | `sizematch` (15 defs) | Fisher p |
|---|---:|---:|---:|
| full_corpus accepted | 59/198 | 56/198 | **0.82** |
| full_corpus acc/1k tok | 1.477 | 1.402 | — |
| full_corpus distinct accepted | 12 | 11 | — |
| full_corpus repeat rate | 0.797 | 0.804 | — |
| full_corpus vacuous share of accepted | **0.017** (1 of 59) | **0.054** (3 of 56) | — |
| held_out accepted | **0/54** | **3/54** | **0.24** |
| held_out semantic (hand-scored) | 0 | **0** (1 candidate, scored below) | — |

Against the recorded baselines, also non-significant:

| comparison | Fisher p |
|---|---:|
| `diverse` 59/198 vs curated 55/196 | 0.74 |
| `diverse` 59/198 vs generated‑41 turn 1, 72/206 | 0.29 |
| `diverse` 59/198 vs generated‑41 turn 2, 69/206 | 0.45 |

---

## The 0‑vs‑3 held-out gap is not recycling, and not vacuity

`sizematch` accepted 3 held-out draws where `diverse` accepted 0. The obvious
mechanism — the arm that kept the junk got *fake* held-out signal by re-emitting
a store object that happens to typecheck against a held-out task, the
type-collision recycling documented for the powered arms — was checked by
identity lookup against the arm's own store. **It does not hold.**

| task | seed·draw | in the store? | G1/G2 |
|---|---|---|---|
| `heldout/maybe/mapOrElse` | 3·0 | **novel** — not a store object | non-vacuous |
| `heldout/list/headOrElse` | 3·0 | **novel** — not a store object | non-vacuous |
| `heldout/list/sum` | 3·0 | **novel** — not a store object | non-vacuous |

All three are newly generated terms, none is byte-identical to anything in
`.loom-store-sizematch`, and all three pass G1 and G2 — so neither recycling nor
the vacuity gate explains the gap. Note also that all three landed on **seed 3,
draw 0**, one per task: a single seed accounts for the entire difference between
the arms.

That closes off the tidy story in which pruning removes a fake signal. The
honest reading of 0/54 vs 3/54 (p = 0.24), with the difference concentrated in
one seed, is **sampling noise** — and it is recorded here because the
alternative explanation was specifically looked for and specifically not found.

## What the five arms look like together

The one pattern that survives inspection is **monotone in how much generated
context the arm carries** — not in how good it is:

| arm | generated defs | surface chars | vacuous share of store | acc/1k tok |
|---|---:|---:|---:|---:|
| `curated` | 0 | 0 | — | 1.377 |
| `sizematch` | 15 | 1,998 | 0.667 | 1.402 |
| `diverse` | 15 | 4,015 | **0.000** | 1.477 |
| `generated` turn 2 | 41 | 7,916 | 0.610 | 1.728 |
| `generated` turn 1 | 41 | 7,916 | 0.610 | 1.803 |

Read down the vacuity column and then down the acc/1k column: they do not track.
Read down the count or the character column instead, and they do. **The corpus
loop's recall gain looks like a function of context mass, not context quality.**
Removing 63 % of the harvest cost most of the gain even though everything removed
was, by the plan's own gates, uninformative — and a structurally selected 15
bought only +0.075 acc/1k over a neutral 15 (p = 0.82).

That is a claim the data *suggests* and does not establish: the 15‑vs‑41
comparisons are themselves non-significant (p = 0.29, 0.45). What can be said
without qualification is the negative: selection did not help.

---

## Pre-registered predictions, scored

Scored by `experiment/diversity_report.py`, which was committed before any arm
launched.

**P1 — held-out acc/1k in [0.08, 0.25] (conf 0.7).** **OPEN — awaiting run 3.**
P1 was written against the 96‑attempt arm and will be scored on it. The 3‑seed
held-out cell that did run gives 0.000 on 54 draws, below the interval; that is
data, not the verdict.

**P2 — zero held-out semantic successes under the rubric (conf 0.85).**
**OPEN — awaiting run 3**, though nothing so far contradicts it. The `diverse`
arm produced zero accepted held-out draws in the 3‑seed cell, so nothing reached
the mechanical floor. The `sizematch` arm produced one candidate; it is
hand-scored **0** below. Composition remains at zero across every run this
project has recorded.

**P3 — `diverse` beats `sizematch` on held-out acc/1k (conf 0.6).** **OPEN for
the powered comparison; failing on the evidence so far.** In the 3‑seed cell it
is 0.000 vs 0.244 — 0/54 vs 3/54, the reverse of the prediction, p = 0.24, with
the whole difference sitting in one seed and no recycling or vacuity mechanism
behind it (above). Run 3 gives `diverse` a 96‑attempt held-out measurement
against the recorded 4/96 and 7/96 baselines; `sizematch`'s 96‑attempt
counterpart is the reserve arm and has not been run, so even after run 3 the
direct `diverse`‑vs‑`sizematch` held-out contrast will rest on the 3‑seed cells.

**P4 — `diverse` full_corpus ≥ 1.377 and within ±15 % of 1.803/1.728 (conf 0.6).**
**HELD MECHANICALLY, CONTRADICTED SUBSTANTIVELY — and the criterion was badly
designed.** 1.477 ≥ 1.377, and |1.477 − 1.728|/1.728 = 14.5 %, inside the
threshold by half a point; against the other baseline it is 18.1 %, outside.
The prediction passed because it was written as a disjunction over two baselines
and the nearer one happened to sit just inside an arbitrary band. Its *purpose*
was to test "content, not mass", and on that question the answer is the
opposite of what P4 asserts. Recorded as a pass because that is what the
pre-registered rule says, and flagged as a bad rule because that is what the
evidence says.

**P5 — repeat rate below the 0.836–0.847 band (conf 0.5).** **HELD, BUT NOT
ATTRIBUTABLE.** `diverse` 0.797 — but `sizematch` is 0.804, also below the band.
Both 15‑definition arms repeat less than both 41‑definition arms, so this is a
corpus-size effect that the control caught. Without `sizematch` this would have
been reported as a diversity win. It is not one.

**P6 — `diverse` emits a lower vacuous share than `sizematch` (conf 0.55).**
**HELD.** 0.017 vs 0.054 at full_corpus — the only result attributable to
selection rather than size. It is also **1 vacuous draw against 3**, which is
not a number to build on. Direction is right; magnitude is unmeasured.

---

## Hand-scoring — the rubric applied

One draw across both arms met the mechanical floor (funnel `accepted` **and**
exact declared-type match). Procedure per the plan: spec first, then the term.

### `sizematch-followup` · `heldout/list/sum` · seed 3, draw 0

**Spec:** "The result of adding every element of a list together, starting from
zero." Type `List I64 -> I64`; intended composition `corpus/list/foldLeft` with
`I64.add`.

**Term:**

```
(def (fn (data 0x2ee9…(I64)) () I64)
     (lam (data 0x2ee9…(I64))
          (app (ref 0x4bd80df0fc10754098795f5fe2bd676a20f933192622f10455b7f55dff5ad5ae)
               (var 0))))
```

**Resolving the reference:** `0x4bd80df0…` is the extern **`List.size`**, of type
`(fn (data 0x2ee9…(I64)) () I64)`. The term is therefore `λxs. List.size xs` —
it returns the list's **length**.

**Score: 0.** Rubric rule 3 — it reaches the declared type by discarding
structure the spec requires it to preserve, using only the list's length and
never an element's value. (It coincides with the sum only where every element is
1.) It is a type-correct, checker-accepted, semantically wrong answer, and it is
the third such false positive the mechanical floor has produced.

**The G2 gate does not catch this one.** `λxs. List.size xs` uses its parameter
and performs a real application, so it is non-vacuous by the harvest's own
criteria. The mechanical vacuity metric caught turn 2's `let c = b in b`; it
does not catch "right type, wrong function". That bounds what the proxy is worth:
it detects *empty* terms, not *incorrect* ones, and the rubric stays human for
exactly this reason.

---

## Outstanding

**`diverse-heldout12` is in flight**, after an hour of STOCKOUT across
europe‑west4‑a/b/c and us‑central1‑a/b/c. It carries P1, P2 and the 96‑attempt
held-out comparison against the recorded 4/96 and 7/96 baselines. This document
is updated and step 7 closed when it lands.

**Its 96‑attempt `sizematch` counterpart is the reserve arm and is not
scheduled.** So the direct held-out contrast between the two 15‑definition arms
will remain a 54‑draw comparison whatever run 3 says. That is a real limit on
what this plan can conclude about held-out acceptance — and it is why the plan
moved its power to `full_corpus` before launching, where the comparison *is*
complete.

**Cost so far:** 2 on-demand g2‑standard‑4 runs, ≈ 1.4 h of GPU ≈ $1.20, plus a
third in flight; failed launch attempts created no instances and cost nothing.

---

## Verdict — interim, on the `full_corpus` contrast

**Final for `full_corpus`; the held-out half waits on run 3.** What follows does
not depend on run 3: the powered comparison is complete, both arms drew
identical budgets, and no held-out number can change it.

**A diversity-seeking harvest does not measurably move recall.**

Composition is so far unchanged — zero held-out semantic successes, as
everywhere else, and the single mechanical-floor candidate hand-scored 0 — but
that half of the verdict is provisional until run 3. The corpus loop's
recall gain does not survive pruning the harvest to its informative 15 — and
since a *neutral* 15 performs the same (p = 0.82), what the loop is buying looks
like context mass rather than context quality. The store's 61 % vacuity, which
motivated this whole increment, turns out not to be costing the loop anything
measurable; removing it did not help.

The one thing selection bought is a lower vacuous-output rate (1 of 59 vs 3 of
56). That is real, cheap and small.

The lever the corpus-loop plan proposed — "change *what* gets harvested" — is
tested and negative on recall, and pending on composition.

**The structural argument does not wait on run 3, though.** The candidate pool
contains 22 non-vacuous definitions in total and **zero of them solve a held-out
task**. No selection policy over that pool can teach a composition the pool does
not contain, so a fourth turn differing only in the selection rule is not worth
its GPU hour whatever run 3 reports. If run 3 comes back at 0/96 it confirms the
plateau; if it comes back with a mechanical-floor candidate, the rubric decides
it and the precedent — three false positives so far, including this document's
`List.size`‑for‑`sum` — says expect another 0. Either way the next lever has to
change what the model can *learn from*, not which subset of its own past output
it is shown.
