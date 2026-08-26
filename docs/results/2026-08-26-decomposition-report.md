# Hole-directed decomposition — results

**Plan:** [2026‑08‑25‑hole‑decomposition](../plans/2026-08-25-hole-decomposition.md) §4 (pre‑registered)
**Model:** Qwen2.5‑Coder‑7B‑Instruct GGUF Q4_K_M · **Hardware:** g2‑standard‑4 L4 24 GB ·
**Backend:** llama‑cpp in‑process · **Condition:** `gbnf+typemask` · curated store ·
`address_book: full` · purse 4,608 tok/cell, 768/draw, 8 tasks × 8 seeds = 64 cells/arm
**Analysis:** [`experiment.decomposition_analysis`](../../prototype/experiment/decomposition_analysis.py)
(cell primary, Fisher, stratified permutation) and
[`experiment.decomp_hand_score`](../../prototype/experiment/decomp_hand_score.py)
(rubric verdicts **by execution** on the reference interpreter, differential
against the verified gold terms). Raw records: `prototype/runs/decomp-{whole,redraft,holes}/records.jsonl`.

**Provenance.** Two spot instances: the first was preempted 8 minutes after
creation (2026‑08‑26 07:31 UTC, before model load — nothing lost); the second
ran all three arms sequentially to `SUCCEEDED` (markers 11:43, 15:07, ≈18:35
UTC), ≈10.7 h un‑preempted, and the driver's per‑arm fetch (commit `ac7094e`)
brought every arm home on the first try. Teardown verified: root destroyed
(4 resources), bucket 404, zero instances. No test was computed until all
three arms were banked.

## The two headlines

**1. The primary is null — and by the plan's own pre‑committed reading it is
"starved, not refuted" (§6 row 4).** Composed‑definition cells: `holes` 2/64
vs `whole` 3/64 (one‑sided Fisher p = 0.82; task‑stratified permutation
agrees, p = 0.82 — no clustering caveat). But the protocol almost never got to
run: skeleton funnel acceptance was **5.5 %** (41 of 747), far below the 20 %
the licensing table conditions on, and — the deeper starvation — **the model
wrote a hole in only 12 of 747 skeletons (1.6 %)**. Nine of those twelve died
at typecheck, one at references; the two accepted were both *bare* holes,
which §3's rule correctly ends unfilled (a bare hole's sub‑task is the
original task). **Not one fill draw ever happened, in the entire arm.** The
experiment measured the protocol's elicitation, not its mechanism; per §6
row 4 this is reported as **inconclusive about decomposition**, and the
pre‑committed next step is a re‑run with the fill gate relaxed from
`accepted` to `parses` — plus, beyond row 4's letter, something the row did
not anticipate: relaxing the gate cannot help if the model does not write
holes, so the re‑run design must also address hole *elicitation*.

**2. The project's first genuine held‑out semantic successes — two of them,
verified by execution.** Every prior candidate in project history died under
the hand rubric. This run's nine mechanical‑floor candidates (4 unique
surfaces) were scored by running each against the task's verified gold term
on a concrete input battery under the reference interpreter:

| arm | task | surface (refs resolved) | verdict |
|---|---|---|---|
| whole (+redraft, holes dup.) | `list/sum` | `λxs. List.size xs` | **FAIL** — length ≠ sum (mismatch on [1,2,3], [5,−2]) |
| whole (+redraft dup.) | `list/reverseThen` | recursive, head‑preserving | **FAIL** — wrong on ([1,2],[3]); **FuelExhausted** on ([7,8,9],[]) — non‑terminating despite passing the measure's shape check |
| **redraft** | `list/mapLength` | `λf. λxs. List.size xs` | **PASS** — extensionally correct: map preserves length, so the count never needed the map |
| **holes** | `list/mapLength` | `λf. λxs. List.size (list/map f xs)` | **PASS** — correct **and the first genuine two‑definition composition along the recorded route in project history** |

Hand‑scored semantic successes per arm: **whole 0, redraft 1, holes 1** (each
1/64 cells, Clopper–Pearson 95 % [0.04 %, 8.4 %]). The ≥ 5 threshold (§4.6) is
nowhere near cleared — these are existence proofs, not rates, and the report
makes no significance claim. Two caveats stated plainly: the `holes`‑arm
composition came from a **hole‑free skeleton draft**, so it cannot be
attributed to the fill mechanism (which never ran); and the `redraft` success
computes the right answer without composing — the route‑reference secondary,
not the rubric, is what separates the two.

## Cell table (64 cells/arm)

| metric | whole | redraft | holes |
|---|---:|---:|---:|
| composed cells (primary unit) | 3 | 3 | 2 |
| funnel‑accepted cell | 14 | 18 | 13 |
| type‑exact cell | 26 | 31 | 27 |
| full‑route cell | 16 | 12 | 11 |
| hand‑scored semantic | 0 | **1** | **1** |
| charged draws | 762 | 772 | 747 |
| accepted draws | 28 | **53** | 41 |
| truncated draws (%) | 2.8 % | 2.3 % | 4.6 % |
| completion tokens | 260,726 | 259,655 | 261,264 |

Truncation is under the 10 % censoring rule everywhere; every cell ran under
the §4.3.2 purse with full‑cap draws only (the address‑book run's fix,
verified by the runner's guard tests).

## Tests, as pre‑registered

- **Primary** (`holes` > `whole`, one‑sided, α = 0.05): 2/64 vs 3/64,
  **p = 0.82.** Null. Direction negative.
- **Attribution gate** (`holes` > `redraft`): 2/64 vs 3/64, p = 0.82 — moot
  with a null primary, reported for completeness.
- **Stratified permutation sensitivity:** agrees with the Fisher on both
  comparisons (p ≈ 0.82); no unresolved clustering caveat.
- **`redraft` vs `whole`** (context, one‑sided): 3/64 vs 3/64, p = 0.66 on the
  primary — but narrowing nearly **doubled draw‑level funnel acceptance**
  (53 vs 28 accepted draws) and produced a hand‑scored success where `whole`
  produced none. Suggestive, not significant, and recorded as the §6 row‑5
  diagnostic input for any future protocol choice.

## Holes‑arm protocol telemetry (the starvation, quantified)

```
skeleton draws 747, accepted 41 (5.5%)
accepted skeletons: hole-free 39, bare-hole 2 (round ends unfilled by §3's rule), non-bare with holes 0
accepted non-bare skeletons with >=1 fillable hole: 0
hole-bearing skeletons rejected by the funnel: 10 (typecheck 9, references 1)
fills attempted 0, spliced 0, rolled back 0
holes-per-skeleton histogram: {0: 735, 1: 12}
```

The chain that starved the mechanism: the model writes holes rarely (1.6 % of
skeletons) → hole‑bearing drafts typecheck poorly (10 of 12 rejected) → the
accepted remainder were bare holes the protocol rightly refuses to fill. The
fill/splice/rollback machinery — stub‑verified end to end before launch — was
never reached by real model output.

## Verdict, per §6's pre‑committed table

**Row 4: primary null, accepted‑draft rate < 20 % — the protocol was starved,
not refuted.** Inconclusive about decomposition as a lever; no conclusion
about composition is licensed in either direction. The pre‑committed follow‑up
is a re‑run with the fill gate relaxed from `accepted` to `parses`; the
elicitation finding above means that re‑run's design must also change how
holes are invited (the §3 block as written licenses holes but does not induce
them — 98.4 % of skeletons ignored it). The first‑successes headline stands
independently of the null, per the ≥ 5‑successes row's own instruction to
re‑examine recycling before claiming anything: both PASS verdicts are by
differential execution against verified gold, the strongest evidence this
project has applied to a candidate.

## Cost

| item | est. (§5) | actual |
|---|---|---|
| Spot attempt 1 (preempted at 8 min) | — | ≈ $0.05 |
| Spot attempt 2 (boot + 3 arms, ≈10.7 h) | — | ≈ $2.68 |
| Storage + egress | < $0.02 | < $0.02 |
| **Total** | **≈ $3.07 spot** | **≈ $2.75** |
