# Diversity-seeking harvest — results

**Plan:** [2026‑08‑23‑diversity‑harvest](../plans/2026-08-23-diversity-harvest.md)
**Model:** Qwen2.5‑Coder‑7B‑Instruct GGUF Q4_K_M · **Hardware:** g2‑standard‑4 L4 24 GB ·
**Backend:** llama‑cpp · **Condition:** `gbnf+typemask` · `n_ctx` 32,768 · temperature 0.8
**Zone:** europe‑west4‑c (on‑demand; every other zone was STOCKOUT all morning)

| run | id | started (UTC) | elapsed |
|---|---|---|---:|
| `diverse-followup` | `div-diverse-followup-20260824T101056Z` | 2026‑08‑24T11:23:43Z | 2,610 s |
| `sizematch-followup` | `div-sizematch-followup-20260824T123150Z` | 2026‑08‑24T13:16:17Z | 2,440 s |
| `diverse-heldout12` | `div-diverse-heldout12-20260824T133150Z` | 2026‑08‑24T13:57Z | ~2,600 s |

**Status: complete.** All three runs landed; every pre-registered prediction is
scored. Instances self-deleted and the artifacts bucket was removed — see
[Teardown](#teardown).

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

## The 96‑attempt held-out arm

`diverse-heldout12`: **5/96 accepted, 4 distinct, 0.102 acc/1k tok, 210 draws,
and zero draws reaching the mechanical floor** — so nothing to hand-score.

| arm | generated defs | accepted/96 | acc/1k tok | distinct | mechanical-floor candidates |
|---|---:|---:|---:|---:|---:|
| `curated` (recorded) | 0 | 4 | 0.081 | 2 | 0 |
| **`diverse`** | 15 | **5** | **0.102** | 4 | **0** |
| `generated` (recorded) | 41 | 7 | 0.142 | 5 | 1 → hand-scored **0** in turn 2 |

Every comparison is non-significant: `diverse` vs curated **p = 1.00**,
`diverse` vs generated‑41 **p = 0.77**, and the two recorded arms against each
other **p = 0.54**.

**The ordering is the same one the `full_corpus` regime produced, arrived at
independently.** Held-out acc/1k tok rises monotonically with the number of
generated definitions — 0 → 0.081, 15 → 0.102, 41 → 0.142 — and not with their
quality: the 15 definitions here are 0 % vacuous and land *below* 41 definitions
that are 61 % vacuous. Two regimes, two independent measurements, same answer.

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

**P1 — held-out acc/1k in [0.08, 0.25] (conf 0.7).** **HELD.** 0.102, inside the
interval, and statistically indistinguishable from both recorded baselines
(p = 1.00 vs curated, p = 0.77 vs generated‑41). This was the prediction that
said *nothing will change*, and it was the one I was most confident in. It was
right.

**P2 — zero held-out semantic successes under the rubric (conf 0.85).** **HELD.**
Zero of the `diverse` arm's 210 held-out draws reached the mechanical floor, so
there was nothing to hand-score. Composition remains at zero across every run
this project has recorded, now including a 96‑attempt arm built from a corpus
selected specifically to be informative.

**P3 — `diverse` beats `sizematch` on held-out acc/1k (conf 0.6).** **FAILED.**
The only direct comparison is the 3‑seed cell — 0.000 vs 0.244, 0/54 vs 3/54,
the reverse of the prediction (p = 0.24), with the whole difference in one seed
and neither recycling nor vacuity behind it. **The powered version of this
comparison does not exist**: `sizematch`'s 96‑attempt counterpart was the
reserve arm and was never scheduled, so the direct held-out contrast between the
two 15‑definition arms rests on 54 draws and cannot be strengthened from the
data collected. That is a real gap in this plan's design, not a rounding error:
P3 was named as "the only prediction that tests whether *selection* rather than
size or noise is doing anything", and it is the one the run budget under-served.
What can be said is that `diverse` did not beat the control anywhere, in either
regime, at any sample size measured.

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

**The 96‑attempt `sizematch` arm was never run**, so the direct held-out
contrast between the two 15‑definition arms rests on 54 draws. See P3 — this is
the plan's one design gap, and it under-served precisely the prediction that
tested the mechanism.

**Cost:** 3 on-demand g2‑standard‑4 runs, ≈ 2.1 h of GPU ≈ **$1.80**. Failed
launch attempts created no instances and cost nothing.

## Teardown

- **Instances:** none. `gcloud compute instances list` → `Listed 0 items.` The
  runner self-deleted at the end of its startup script, as designed.
- **Artifacts bucket:** `gs://loom-diversity-artifacts-19b81040` (4.77 GB — the
  GGUF plus results) **removed**. The run outputs were copied into the main
  checkout's `prototype/runs/` first: `prototype/runs/` is gitignored, so the
  records are *not* in git, and this branch's worktree is disposable. Deleting
  the bucket without that copy would have left the only surviving copy inside a
  directory designed to be thrown away.
- **Terraform state: NOT cleaned — needs an operator.** The state at prefix
  `experiment-diversity` still holds entries for the deleted bucket, its two
  IAM members, and a project IAM member conditioned on an instance name that no
  longer exists. `task infra:destroy-diversity` does the cleanup and is safe by
  construction (the root shares no resource with any other run), but it tears
  down IAM bindings and no *user* has approved that — it was requested only by
  an orchestrating agent, so it was correctly refused. **Ongoing cost is $0**;
  the residue is stale state entries, not live resources.

---

## Verdict

**A diversity-seeking harvest moves neither composition nor recall.**

Composition is unchanged: **zero** held-out semantic successes across 210
held-out draws in the 96‑attempt arm, zero in the 3‑seed cells, and the one
mechanical-floor candidate anywhere in these runs hand-scored **0** (it computes
list length, not sum). That is now true of every run this project has recorded,
including one whose entire generated corpus was selected to be non-vacuous,
structurally distinct, and novel against the curated corpus.

Recall did not move either, and the reason looks like the opposite of this
plan's hypothesis. The corpus loop's gain does not survive pruning the harvest
to its informative 15, and a *neutral* 15 performs the same (p = 0.82 at
`full_corpus`). **In both regimes independently, acceptance tracks the number of
generated definitions and not their quality** — `full_corpus` 1.377 / 1.40–1.48
/ 1.73–1.80 and `held_out` 0.081 / 0.102 / 0.142 across 0, 15 and 41
definitions. The store's 61 % vacuity, which motivated this whole increment,
costs the loop nothing measurable; removing it did not help.

The one thing selection bought is a lower vacuous-output rate (1 of 59 vs 3 of
56). That is real, cheap and small.

The lever the corpus-loop plan proposed — "change *what* gets harvested" — is
**tested and negative on both counts.**

**And the structural argument says not to try a fourth variation.** The
candidate pool contains 22 non-vacuous definitions in total and **zero of them
solve a held-out task**. No selection policy over that pool can teach a
composition the pool does not contain. Three turns of this loop
(harvest-everything ×2, selective harvest ×1) have moved held-out semantic
success not at all, from zero, and the mechanical floor has now produced four
false positives — `let c = b in b` for `reverseThen`, and `List.size` for `sum`
here. The next lever has to change what the model can *learn from*, not which
subset of its own past output it is shown.

### What this does not license

"Corpus mass drives acceptance" is the pattern in these numbers, and it is
suggestive rather than established: every pairwise comparison behind it is
non-significant (p = 0.29–1.00), the two points at 15 definitions differ in
bytes as well as count, and n = 3 corpus sizes is a line drawn through three
clusters. It earns a follow-up that varies corpus size deliberately — the same
generations at 15/25/41 definitions — not a claim. What *is* established, at the
strength of a clean null over identical budgets, is the negative: selecting for
structural informativeness bought nothing measurable.
