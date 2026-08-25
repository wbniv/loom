# Plan — The next capability lever: the store has never been addressable

**Date:** 2026-08-24
**Status:** Design complete, pre-registered, **no GPU run launched**. §1's diagnostic
is run and its raw output is pasted below; §4's arms and tests are fixed before any
run. Awaiting dispatch of deliverables 1–4, then the single runlist instance in §5.
**TODO entry:** `[next-lever]`
**Parent:** [the diversity-harvest report](../results/2026-08-24-diversity-harvest-report.md),
["What this does not license"](../results/2026-08-24-diversity-harvest-report.md#what-this-does-not-license),
and [the corpus-size sweep report](../results/2026-08-24-corpus-size-sweep-report.md)
verdict: *"Held-out semantic success remains at zero across every run this project
has recorded."*

**Visible surface:** none. Prompt construction, config files and experiment
scripts only; per house rule, no mockup bundle.

---

## 1. The item's premise is false, and the measurement was censored

The dispatching item reads: *"both 2026‑08‑24 experiments concluded the ceiling is
the pool's content — no selection rule or feedback volume buys composition the pool
lacks (0 of 22 non-vacuous defs solve any held-out task)."*

Three findings below, each reproducible from the repository as it stands, say the
premise is wrong in a specific and fixable way. **The pool contains the
compositions. The prompt has never contained their addresses. And every held-out
cell has been terminated by a truncated draw.**

### 1.1 The pool already contains the compositions — five of them, written by hand today

The item's framing ("0 of 22 *generated* defs solve a held-out task") measures the
wrong pool. The held-out tasks were never designed to be solved by a generated
definition; `Task.composes` in
[`prototype/experiment/prompts.py`](../../prototype/experiment/prompts.py) records
the intended route, and every route is **two curated definitions applied in order**.
Written out by hand against the curated store and pushed through the harness's own
`run_funnel` + `score_semantic`:

```
heldout/list/reverseThen         chars= 613  ~447 completion tokens  funnel=accepted  mechfloor=True
heldout/maybe/mapOrElse          chars= 445  ~325 completion tokens  funnel=accepted  mechfloor=True
heldout/list/concatLength        chars= 537  ~392 completion tokens  funnel=accepted  mechfloor=True
heldout/list/mapLength           chars= 409  ~299 completion tokens  funnel=accepted  mechfloor=True
heldout/list/sum                 chars= 367  ~268 completion tokens  funnel=accepted  mechfloor=True
```

Five of eight held-out tasks, solved in one sitting, from curated definitions only,
with no generated definition involved. *"No selection policy over that pool can
teach a composition the pool does not contain"* is true and irrelevant — the
composition is not missing.

Token counts are `len(surface) / 1.37`, where 1.37 ch/token is the **measured**
median completion tokenization across the 4,135 held-out draws on record
(`len(record["raw"]) / record["tokens_completion"]`), not the 1.51 prompt-side
figure `prompts.CHARS_PER_TOKEN` carries.

### 1.2 The prompt withholds the addresses — 2 of 26, and 7 of 8 tasks are unsolvable

A definition's canonical surface is `(def TYPE TERM)`. **It does not contain its own
content hash.** The example block in `build_prompt` renders `spec` then `surface`,
and nothing else. So a definition's 64‑hex identity reaches the model *only* when
some other shown definition happens to `(ref …)` it in its body — which happens for
exactly three of the twenty-six curated definitions (`list/concat` and `list/flatMap`
reference `list/append`; `clock/nowPair` references `clock/now`).

Per-task, against the curated `held_out` prompt, checking every element of the
task's own recorded route:

```
heldout/list/concatLength        OK       list/append=present  List.size=present
heldout/list/mapLength           BLOCKED  list/map=ABSENT  List.size=present
heldout/list/reverseThen         BLOCKED  list/reverse=ABSENT  list/append=present
heldout/maybe/mapOrElse          BLOCKED  maybe/map=ABSENT  maybe/getOrElse=ABSENT
heldout/list/headOrElse          BLOCKED  list/uncons=ABSENT  maybe/getOrElse=ABSENT
heldout/list/sum                 BLOCKED  list/foldLeft=ABSENT  I64.add=ABSENT
heldout/sample/stampedBytes      BLOCKED  clock/now=present  rand/bytes=ABSENT
heldout/nat/selectNonNegative    BLOCKED  nat/widenPos=ABSENT  nat/select=ABSENT
```

**Seven of eight held-out tasks are information-theoretically unsolvable from the
prompt they were asked with.** The model is asked to emit a 64‑hex digest it has
never been shown. Only 2 of 26 curated definitions are addressable at all, and the
nine externs are never rendered as examples, so three routes are blocked on an
extern address too.

This is not an accident; it is a documented decision that outlived its purpose.
`prompts.py`'s module docstring states: *"**No hash directory is ever supplied.**
Prediction 2 is stated in terms of 64‑hex hashes being unguessable in low-example
regimes and becoming available 'once examples supply the hashes', so hashes enter a
prompt only through examples. Handing the model a name-to-hash table would make
prediction 2 untestable, so the harness does not have one."* That was correct for
Phase A/B's prediction 2. It has silently invalidated every held-out arm since.

**Growing the store does not fix it.** Across every store the project has run,
loading the real exports and rebuilding the real prompt:

```
store      defs   prompt  reach/26  tasks addressable      which
sweep08      34    18744         2  1/8                    ['concatLength']
sweep15      41    20246         2  1/8                    ['concatLength']
sweep25      51    22175         2  1/8                    ['concatLength']
sweep41      67    25870         2  1/8                    ['concatLength']
generated    67    26138         2  1/8                    ['concatLength']
```

26 → 67 objects buys **zero** additional reachable addresses, because a generated
definition is self-contained model output and does not reference curated
definitions either. This is why every selection rule was null: selection changes
*which* definitions are shown, never *whether their addresses* are shown.

The behavioural signature is exactly what that predicts. Across 4,135 held-out
draws on record:

```
draws                            4135  100.0%
has_any_ref                      1594   38.5%
ref_to_corpus_def                 413   10.0%
ref_to_extern                    1384   33.5%
ref_to_DATA_hash(illegal)          41    1.0%
ref_to_a_REQUIRED_def             120    2.9%
ref_to_ALL_required_defs           12    0.3%
```

**0.3 %** of held-out draws reference every definition their task's route needs.
The 33.5 % extern rate is the tell: externs are the hashes that *do* leak, through
curated bodies. The model refs what it has seen and cannot ref what it has not.

### 1.3 Every held-out cell is terminated by a truncated draw

`token_budget_per_task` is a **cumulative per-cell** budget
([`runner.py:354-360`](../../prototype/experiment/runner.py)): `used += spent`, and
each draw is capped at `min(max_tokens_per_draw, budget - used)`. Every recorded
run set it to 512. A cell therefore has 512 completion tokens **in total**, and its
final draw is handed whatever fragment is left — so it truncates by construction:

```
cross-tab stop_reason x cell_done: Counter({('stop', False): 2183, ('length', True): 1952})
cells=1952  draws/cell: mean 2.12 median 2
cells terminated by a truncated draw: 1952/1952 = 100.0%
FIRST draw of each cell: mean 367 median 378
cells whose first draw alone consumed >=400 of the 512-token cell budget: 923/1952 = 47.3%
non-truncated draws per cell: mean 1.12 median 1
```

**1.12 usable draws per (task, seed) cell, median 1**, against gold answers costing
268–447 tokens. 47.2 % of all held-out draws are the terminating fragment,
contributing nothing but a `parse` tally. The "0 held-out successes over 4,135
draws" headline is really ~2,180 draws, ~1,950 of them the only real attempt their
cell ever got.

`full_corpus` is censored the same way (100 % of 312 cells, 1.64 usable draws/cell)
— but at a rate flat across store sizes (38.0 / 38.8 / 38.2 / 36.3 % for
sweep08/15/25/41), so it does **not** confound the corpus-size sweep's monotone
acc/1k tok trend directionally. That result stands exactly as its own verdict left
it: *no trend detected — underpowered, not refuted.* This plan neither assumes nor
dismisses it, and deliberately holds store size fixed so the two questions do not
contaminate each other.

### 1.4 Reproducing §1

Deliverable 1 lands this as `prototype/experiment/addressability_audit.py`. Until
then, every number above comes from `prototype/runs/*/records.jsonl` (present in
the working tree, gitignored) and the checked-in `.loom-store-*/export-resolver.json`
exports, via `corpus_registry`, `experiment.resolver`, `experiment.store_resolver`,
`experiment.prompts` and `experiment.evaluate` — no GPU, no network.

**Verification.** `prototype/experiment/addressability_audit.py` lands Deliverable
1 and reproduces every number pasted above — §1.1's five hand-solved tasks, both
§1.2 tables, the draws table, and §1.3's censoring block — independently, with no
reference to the values pasted in this section. The held-out draw universe (4,135
draws) is the explicit nine-run list in the script's module docstring: the two
`heldout-powered-{curated,generated}` runs, the four `sweep-size{08,15,25,41}`
runs, and `diverse-followup` / `sizematch-followup` / `diverse-heldout12` — the
same runs `diversity_report.py`, `corpus_size_sweep_analysis.py` and
`docs/results/2026-08-23-heldout-powered-report.md` cite. A naive glob over every
`records.jsonl` under `prototype/runs/` overcounts: it includes one exact-duplicate
file (the runlist landing commit's demo output, byte-identical to
`sweep-size08/runs/records.jsonl`) and several early Aug‑13/14 prototyping runs
(`phase-a-*`, `phase-b-*`, `followup-curated/generated/gen-turn2`,
`heldout12-curated/generated`) that predate the harness these reports actually
run on. The "required def" and "ALL required defs" rows count only the
`Task.composes` route elements that are corpus *definitions*, not the extern half
(`List.size`, `I64.add`, …) — externs get their own `ref_to_extern` row instead,
because an extern's hash is common across held-out draws regardless of task
(§1.2's 33.5%), so folding it into "required" would conflate "the model knows a
common extern" with "the model referenced this task's own route."

Run and reproduced 2026-08-24:

```
$ python3 -m experiment.addressability_audit
```

The 8-row route table (§1.2, exact match):

```
### 1.2 Per-task route addressability (curated held_out prompt)

heldout/list/concatLength        OK       list/append=present  List.size=present
heldout/list/mapLength           BLOCKED  list/map=ABSENT  List.size=present
heldout/list/reverseThen         BLOCKED  list/reverse=ABSENT  list/append=present
heldout/maybe/mapOrElse          BLOCKED  maybe/map=ABSENT  maybe/getOrElse=ABSENT
heldout/list/headOrElse          BLOCKED  list/uncons=ABSENT  maybe/getOrElse=ABSENT
heldout/list/sum                 BLOCKED  list/foldLeft=ABSENT  I64.add=ABSENT
heldout/sample/stampedBytes      BLOCKED  clock/now=present  rand/bytes=ABSENT
heldout/nat/selectNonNegative    BLOCKED  nat/widenPos=ABSENT  nat/select=ABSENT
```

The draws table (§1.2, exact match, over the 4,135-draw universe above):

```
### 1.2 Behavioural ref rates over every held-out draw on record

draws                              4135  100.0%
has_any_ref                        1594   38.5%
ref_to_corpus_def                   413   10.0%
ref_to_extern                      1384   33.5%
ref_to_DATA_hash(illegal)            41    1.0%
ref_to_a_REQUIRED_def               120    2.9%
ref_to_ALL_required_defs             12    0.3%
```

§1.1's five hand-solved tasks, §1.2's five-row store-size table, and §1.3's
censoring block (the `('length', True): 1952` / `('stop', False): 2183` cross-tab,
1952/1952 = 100.0% truncated, mean 2.12 / median 2 draws per cell, mean 367 /
median 378 first-draw tokens, 923/1952 = 47.3% first-draw ≥400, mean 1.12 / median
1 non-truncated draws per cell, and the 38.0/38.8/38.2/36.3% flat `full_corpus`
rate by store size) all reproduced exactly as well — full output in the script's
`--section` runs. §4's address-book sizing (not a pasted §1 block) also checked:
`addr-full` is 35 rows, 9,202 characters, ≈6.1k tokens, matching §3 exactly;
`addr-typed`'s per-task count under §4.2's literal codomain-erasure filter came
out 2-13 across the eight tasks rather than the inline "7-13" — one task
(`stampedBytes`, goal type `Pair I64 Bytes`) lands at 2. This is outside §1's
verification scope (§4.2 states no exact table to diff against) and does not
affect any §1 finding; noted here for whoever lands Deliverable 2.

---

## 2. The candidate levers, evaluated

The item names three. Each is judged on: what content it newly injects; why that
content could compose when the current pool's cannot; build cost; per-run cost; and
what would falsify it.

### 2.1 External corpus import — reject, and it is *blocked*, not merely weaker

**Injects:** definitions from outside the project (a transpiled prelude, a verified
library), each needing evidence at some rung of the §6 assurance lattice.

**Why it could compose:** more primitives, more reachable compositions.

**Why not:** §1.2 measures the exact intervention on a smaller scale — 26 → 67
objects — and it bought zero addressable routes and zero held-out movement.
Importing more objects makes the addressing problem strictly worse: the prompt is
already 12.0k tokens at 26 definitions, and every imported object adds an
unaddressed hash to a haystack the model already cannot search. An import
experiment run today would be uninterpretable for the same reason every previous
held-out arm was.

**Build cost:** high — a front-end from the source language into Loom IR, plus an
evidence story per import (SPEC §6). **Per-run cost:** grows with prompt length.
**Falsifying experiment:** import *N* definitions, measure held-out. It is a real
experiment; it is simply **downstream** of this plan, not competing with it.

### 2.2 Task decomposition — the designated *next* lever, not this one

**Injects:** nothing new. It changes the shape of the ask: emit a term with
`(hole TYPE ())` (SPEC §2.6), then fill each hole as its own draw against its own
goal type, assembling afterwards. The narrowing loop (SPEC §8.3) is the existing
hook.

**Why it could compose:** it attacks the length wall directly — each sub-draw is
short, carries one ref, and gets its own budget — and it gives the mask a
*checking-mode* goal at every hole, where whole-term generation gives it a
synthesis position (see §2.4).

**Why not first:** two reasons. The cheap half of its benefit is free — §4.3 removes
the budget censoring for every arm at zero cost, so decomposition must be judged on
what it adds *beyond* that. And it needs a decomposition oracle: whoever writes the
sub-goals is doing part of the composition, so unless the decomposition is derived
mechanically from the goal type the experiment measures the decomposer. That is a
solvable design problem, but it is a protocol change (multi-draw hole filling,
per-hole goal types, assembly, per-hole accounting) on top of an experiment that
cannot yet be interpreted.

**Build cost:** high. **Per-run cost:** comparable. **Falsifying experiment:**
hole-directed vs whole-term generation at matched total token budget. **This is the
pre-committed next lever if §4's addressing hypothesis is falsified** (§6).

### 2.3 Worked derivations — a confounded version of the recommendation

**Injects:** curated definitions that are themselves compositions over other
curated definitions, shown with spec text naming the composition.

**Why it could compose:** the idiom is thinly demonstrated. Only **3 of 26** curated
definitions reference another curated definition, so `(app (app (ref X) …) …)` over
store refs appears three times in a 12k‑token prompt.

**Why not:** every worked derivation *also* leaks the addresses of what it composes
— that is precisely why `list/append` and `clock/now` are the only two reachable
hashes in §1.2. So a worked-derivation arm buys idiom **and** addressing at once,
and a positive result could not be attributed to either. It is the recommendation
plus a confound. Run it *after* the addressing term is isolated, as the natural
follow-up arm.

**Build cost:** medium — author *k* compositional definitions with specs, admit them
with evidence. **Per-run cost:** +*k* × ~500 chars. **Falsifying experiment:**
worked-derivation arm vs address-only arm, which is a straight extension of §4.

### 2.4 Sharpening the mask — real, sound, and useless until addresses exist

Worth naming because it is the most Loom-native idea available and it is **the
approach I rejected**. `GoalTypePruner` already filters a `ref`'s digest by goal
(veto 5), but it *abstains* wherever the checker synthesizes — including `app`'s
function and argument, which is exactly where every held-out composition lives. A
sound spine-aware extension (a `ref` at the head of a *k*-ary application spine
checked against goal *G* must resolve to a type whose *k*-th codomain erases to *G*)
cuts the admissible ref universe hard:

```
heldout/list/reverseThen         depth=2   7/47  list/append, list/concat, list/consNat, list/flatMap, list/map, list/reverse, maybe/mapPoly
heldout/list/sum                 depth=1  13/47  I64.add, I64.sub, List.size, clock/now, list/foldLeft, ...
heldout/maybe/mapOrElse          depth=3  13/47  ...
```

47 → 7–13, and the right definitions survive the filter in every case. **One line
kills it as a first move:** a veto removes wrong choices, it cannot supply an
address the model has never seen. Masking your way to `list/reverse`'s digest is
impossible when that digest appears nowhere in the context. This becomes the right
lever the moment addressing works and precision is the residual bottleneck — it is
listed as a follow-up in §6, not as an arm here.

### 2.5 The recommendation — make the store addressable

**Injects:** the one piece of content the prompt has never carried — each `ref`‑legal
store object's own §5.2 identity, beside its name and type. Not new definitions:
new *addresses* for the definitions already there.

**Why it could compose when the pool's content could not:** §1.1 shows the
compositions exist; §1.2 shows the addresses do not. This is the only candidate
that changes the quantity §1.2 measures, and it is the only one whose absence
*already explains the entire zero*.

**Build cost:** low. One block in `build_prompt`, one config flag, one filter
function. No protocol change, no store change, no new definitions, no evidence
questions. **Per-run cost:** +51 % prompt tokens (full book) or +~19 % (filtered),
inside the existing 32,768‑token `n_ctx`. **Falsifying experiment:** §4.

---

## 3. What the lever is, concretely

A **store address book**: a block inserted between the examples and the ask,
one row per `ref`‑legal object the resolver holds, in resolver order:

```
0x23d1e0891aef622110302fe247b7148de5eb61a09f30138cfe7bd09d6cf7e6d7 I64.add : (fn I64 () (fn I64 () I64))
0x4300a5090d354a1ad4dac0ce1a3ff1e96af401c3fca2a6d5c0e685bc5dfdaca4 corpus/nat/select : (fn Bool () (fn (refine I64 …) () …))
```

35 of the resolver's 47 digests are `ref`‑legal (the other 12 are data and ability
declarations, which are not term-level references — the illegal `(ref DATA_HASH)`
draws in §1.2 are the model guessing into that gap). The full book is 9,202
characters, ≈ 6.1k prompt tokens.

The arms differ **only in which rows the block contains**. Nothing else about the
prompt, the store, the mask, the grammar or the scoring changes.

---

## 4. Pre-registration

Everything in §4 is fixed before any GPU run. No mid-run peeking; no post-hoc test
selection.

### 4.1 Hypotheses

**H1 (mechanism, primary).** Supplying object addresses raises the share of
held-out draws that reference every definition on the task's recorded route, from
its measured 0.3 % baseline.

**H2 (outcome, secondary).** Supplying object addresses produces the project's
first non-zero hand-scored held-out semantic success.

**H3 (selection).** A goal-type-filtered address book beats the full book, because
35 unsorted 64‑hex rows in an 18k‑token prompt is itself a retrieval problem for a
7B at Q4_K_M.

H1 is primary because it is mechanical, needs no rubric, and is the quantity the
lever directly manipulates. H2 is what the project cares about but is a strictly
downstream event and is reported with exact intervals rather than leaned on.

### 4.2 Arms

Three arms, `held_out` regime only, condition `gbnf+typemask`, **curated-only
resolver (26 definitions, 47 objects)** so that store size is held fixed and the
mass question of the corpus-size sweep cannot contaminate this one.

| Arm | Address block | Rows | Prompt |
|---|---|---|---|
| `addr-none` | none — byte-identical to today's prompt | 0 | ≈ 12.0k tok |
| `addr-full` | every `ref`‑legal object | 35 | ≈ 18.1k tok |
| `addr-typed` | only objects whose type can produce the task's goal | 7–13 | ≈ 14.3k tok |

`addr-none` is the honest baseline **re-run under the §4.3 harness**, because the
budget change makes every prior held-out number non-comparable. It is not a
formality: if it alone produces successes, the ceiling was the budget (§6).

**`addr-typed`'s filter uses only the task's declared type and the resolver's own
types.** It is the §2.4 codomain test applied at selection time: object *o* is
listed iff its type has some *k* ∈ {0,1,2,3} with the *k*-th codomain erasing
(§3.2.1) to the task's body goal, or its type is a `forall`. **It never consults
`Task.composes`, never consults a gold term, and is computed by a function that is
not given either.** Deliverable 2's tests pin that by construction.

### 4.3 Harness changes — confound removal, applied identically to all three arms

1. `token_budget_per_task: 6144`, `max_tokens_per_draw: 768`,
   `max_draws_per_task: 8`. Every cell gets **exactly 8 draws**, each with the
   full 768‑token cap, and no draw is handed a leftover fragment. 768 clears the
   447‑token worst-case gold answer by 72 %.
2. `n_ctx: 32768` unchanged — `addr-full`'s 18.1k prompt plus 768 completion is
   19k, well inside it. `context_required` is asserted against every arm's prompts
   in the stub check (§4.6), so a config cannot drift under its own address book.
3. `stop_on_semantic_success: false` unchanged — the mechanical floor produces
   false positives (four on record), so a cell must not stop on one.
4. `seeds: [1,2,3,4,5]`, 8 tasks → 40 cells → **320 draws per arm**.

Truncation is now a genuine rejection rather than a cell terminator. The truncated
draw fraction is reported per arm as a harness-health check; if it exceeds 10 % the
run is reported as still censored and the primary is reported but flagged.

### 4.4 Prerequisite: a gold reference term for all eight tasks

A task battery with no verified solution is not a battery. Deliverable 3 lands a
gold `(def …)` for each of the eight held-out tasks, each checked by the harness's
own `run_funnel` and `score_semantic` and hand-scored against the R3 rubric. Five
already exist (§1.1). **Any task with no gold solution under 768 completion tokens
is dropped from the battery before the run**, and the drop is recorded with its
reason. Gold terms are harness fixtures like `composes`; they are never shown to
the model, and a test asserts no gold surface appears in any built prompt.

If the battery drops below six tasks, this plan pauses and the battery is redesigned
before any GPU spend — that is a stated stopping condition, not a judgment call at
run time.

### 4.5 Primary metric and test

**Metric.** *Route-reference rate* — the share of a arm's held-out draws whose
`(ref 0x…)` digest set contains every element of that task's `composes` route
(definitions and externs alike). Mechanical, computed from `record["raw"]` by
regex, no rubric, no human.

**Baseline.** 12 / 4,135 = 0.290 % over every held-out draw the project has
recorded. Used only as the planning rate; the *test* is against the concurrent
`addr-none` arm, so a harness change cannot masquerade as an effect.

**Test.** Fisher exact, **one-sided** (address arm > `addr-none`), on the 2 × 2
draw-level table. Two comparisons — `addr-full` vs `addr-none` and `addr-typed` vs
`addr-none` — **Holm-corrected** at family-wise α = 0.05, so the smaller p must
clear 0.025. H3 (`addr-typed` vs `addr-full`) is a third, **two-sided** Fisher test
reported as exploratory and not part of the Holm family.

> **Amended by A1 (2026‑08‑25, pre‑data, after §4.9):** `addr-typed` leaves the
> family. The primary is the single comparison `addr-full` vs `addr-none`,
> one-sided Fisher at α = 0.05, no Holm. Every `addr-typed` comparison is
> exploratory.

### 4.6 Secondary metrics, recorded and reported, not leaned on

- **Hand-scored semantic success (R3 rubric)** per arm, with Clopper-Pearson 95 %
  intervals. Pre-registered Fisher one-sided vs `addr-none` at α = 0.025.
  *Amended by A1: `addr-full` vs `addr-none` at α = 0.05 (single pre-registered
  secondary comparison; ≥ 5 successes vs 0 clears, per the §4.7 table);
  `addr-typed` exploratory.*
  Every mechanical-floor candidate is hand-scored; the rubric is the one the
  diversity-harvest and sweep reports used, unchanged.
- **Any-required-reference rate** (≥ 1 route element referenced) — the weaker
  mechanical signal, baseline 2.9 %.
- **Illegal-`ref` rate** (a `(ref …)` at a digest with no reference type) —
  baseline 1.0 %; a fall here is direct evidence the model stopped guessing.
- Funnel distribution, truncated-draw fraction, acc/1k tok, prompt tokens per arm.
  **acc/1k tok is not comparable across arms** — the address block changes the
  denominator by design — and is reported for continuity only. The primary is a
  per-draw rate precisely so the token asymmetry cannot bias it.

### 4.7 Power — stated honestly, before any run

> **Amended by A1:** the primary is now a single comparison at α = 0.05, so the
> table below (computed at Holm's 0.025) is a **lower bound** on primary power;
> the secondary's clearing threshold drops from ≥ 6 to ≥ 5 successes
> (p = 0.03076 < 0.05, from the table's own Fisher values).

Simulated Fisher exact, one-sided, 4,000 replicates per cell, n = 320 per arm,
`addr-none` at its measured 0.003.

```
PRIMARY at Holm-corrected alpha=0.025 (two comparisons), n=320/arm, A0=0.003:
   A1=0.03  power=0.723
   A1=0.05  power=0.982
   A1=0.10  power=1.000

SECONDARY — hand-scored semantic success, A0 modelled at 0.001, n=320/arm, alpha=0.025:
   A1=0.01  power=0.083
   A1=0.02  power=0.529
   A1=0.03  power=0.848
   A1=0.05  power=0.997
   A1=0.10  power=1.000

   observing 4 successes in A1 vs 0 in A0 (n=320 each): Fisher one-sided p=0.06191
   observing 5 successes in A1 vs 0 in A0 (n=320 each): Fisher one-sided p=0.03076
   observing 6 successes in A1 vs 0 in A0 (n=320 each): Fisher one-sided p=0.01526
```

**Reading, fixed in advance.** The primary has **72 % power against a 3 % route-
reference rate and 98 % against 5 %** — the first adequately-powered pre-registration
this project has run, and the reason for choosing a mechanical primary over the
semantic one. The secondary needs **≥ 6 semantic successes in 320 draws** to clear
its threshold; below that it is reported as a count with an interval and explicitly
**not** as a significance claim. A null primary at this power is evidence against a
≥ 5 % effect; it is not evidence against a 1 % one, and the report will say so in
those words.

### 4.8 Stub-backend dry-run — reproduces prompt construction, no GPU

Deliverable 4, run and pasted into this plan before any instance launches:

1. The three arms' prompts for all eight tasks differ **only** by the inserted
   block — asserted by stripping the block from `addr-full` and `addr-typed` and
   comparing bytes with `addr-none`.
2. `addr-typed`'s row set contains every route element for each task it is not
   dropped for, and the filter function is called with no access to `composes` or
   to any gold term (asserted by signature and by a test that passes a resolver and
   a type and nothing else).
   *Amended by A1 — the first clause is provably false of §4.2's filter and is
   replaced:* the check now asserts (a) the blindness clause unchanged, (b) the
   typed row sets byte-match `experiment.addressability_audit --section
   addressbook`'s recomputation, and (c) the per-task route-incompleteness table
   from A1 (5 of 8 tasks route-incomplete; `reverseThen`, `sum`,
   `selectNonNegative` complete) is reproduced and pasted into the report.
3. `context_required` for each arm ≤ `n_ctx − max_tokens_per_draw`.
4. Every gold term passes `run_funnel` and `score_semantic`, and none appears as a
   substring of any built prompt.
5. Route-reference extraction, replayed over the 4,135 recorded held-out draws,
   reproduces the 12 / 4,135 baseline exactly.

> **Note filed with Deliverable 2 (2026‑08‑25), resolved by Amendment A1 below
> — check 2 is not
> satisfiable by §4.2's filter as written.** §4.2 lists object *o* iff some
> *k* ∈ {0,1,2,3} has *o*'s *k*-th codomain erasing to the task's **body goal**.
> That is a body-goal test, not §2.4's spine-aware one, and under it a route
> element whose own codomain never reaches the body goal is dropped. Recomputed
> over all eight tasks (`experiment.addressability_audit --section addressbook`,
> which now calls the landed filter directly), **`addr-typed` omits at least one
> route element for 5 of the 8 tasks**: `concatLength` loses `list/append`
> (returns a list, goal is `I64`), `mapLength` loses `list/map`, `mapOrElse`
> loses `maybe/map`, `headOrElse` loses `list/uncons`, and `stampedBytes` loses
> both `clock/now` and `rand/bytes`. `reverseThen`, `sum` and `selectNonNegative`
> keep their full routes. §2.4's "the right definitions survive the filter in
> every case" holds for the three tasks it tabulates and not for `mapOrElse`,
> which it also tabulates but does not check.
>
> Deliverable 2 implements §4.2 **literally and unchanged**, because §4.2 is the
> pre-registered filter and §4.9 forbids quietly reselecting it; the tests pin
> the exclusion as a fact rather than asserting check 2's opposite. Whether
> `addr-typed` runs on this filter, on a spine-aware one, or is dropped from the
> family is a design decision for the plan's owner and is **open before any GPU
> spend**. Nothing about `addr-none` or `addr-full` depends on it.

### 4.9 No peeking, no test-shopping

The arms, the metric, the tests, the correction and the thresholds are fixed above
before any of the three runs launch. Whatever the three route-reference numbers turn
out to be, §4.5's test is the one reported as primary.

### Amendment A1 — `addr-typed` leaves the Holm family (2026‑08‑25, pre‑data)

Filed before any GPU launch, on the Deliverable‑2 note above. This is a
documented reselection under §4.9's own standard — what §4.9 forbids is a
*quiet* one, or one made after data exist. No draw has been made under any arm.

**The defect.** §4.2's filter is a body-goal test; the §4.8 note above shows it
drops at least one route element for 5 of 8 tasks, so under §4.5's
all-route-elements metric `addr-typed` is null-by-construction on those tasks
(§2.4's own one-liner: a model cannot produce an address it has never seen).
Keeping it in the Holm family costs `addr-full` half its α for a comparison
known in advance to be handicapped, and §4.8 check 2 — the GPU gate — asserts a
property the filter provably lacks. The plan was internally inconsistent and
could not be executed as written; an amendment was forced either way.

**The repair that does not work, measured before deciding.** A demand-driven
closure filter (seed demands with the body goal; admit *o* when some *k*-th
codomain erases to a demanded type; propagate admitted objects' first-*k*
erased domain types; iterate to fixpoint — still resolver-and-declared-type
only) was probed against the landed `prompts.py` machinery over all eight
tasks (probe: `prototype/experiment/closure_filter_probe.py`):

```
task                               lit rows clo rows  lit-missing / clo-missing (route elements)
heldout/list/concatLength                13       28  ['corpus/list/append'] / ok
heldout/list/mapLength                   13       28  ['corpus/list/map'] / ok
heldout/list/reverseThen                  7       28  ok / ok
heldout/maybe/mapOrElse                  13       28  ['corpus/maybe/map'] / ok
heldout/list/headOrElse                  13       28  ['corpus/list/uncons'] / ['corpus/list/uncons']
heldout/list/sum                         13       28  ok / ok
heldout/sample/stampedBytes               2        2  ['corpus/clock/now', 'corpus/rand/bytes'] / ['corpus/clock/now', 'corpus/rand/bytes']
heldout/nat/selectNonNegative            13       28  ok / ok

literal range 2-13, closure range 2-28 (full book = 35)
```

It recovers 4 of the 5 broken tasks but balloons to 28 of 35 rows — H3's
premise (a small book vs a 35-row retrieval problem) evaporates at 28 — and it
**still fails check 2** on `headOrElse` (exact erased equality cannot see
through `list/uncons`'s polymorphic instantiation) and `stampedBytes`
(effectful/cap-typed codomains never syntactically meet a demanded type).
Repairing those needs unification-aware matching at selection time — a new
design with its own leak surface, and exactly the spine-aware machinery the
`mask-spine-refs` watch item already owns at *generation* time, where the
checker's synthesized per-position goals do the instantiation for free. No
simple sound selection-time filter satisfies check 2.

**The decision.**

1. **Primary (§4.5):** single comparison, `addr-full` vs `addr-none`, one-sided
   Fisher at α = 0.05. No Holm. Strictly more primary power than the
   pre-amendment family (§4.7's table, computed at 0.025, becomes a lower
   bound).
2. **`addr-typed` still runs, entirely exploratory,** on §4.2's literal filter,
   unchanged — the landed implementation and its tests stand. Every comparison
   involving it (vs `addr-none`, vs `addr-full`) is reported two-sided,
   exploratory, and flagged with the route-incompleteness table above. The
   handicap biases only *against* `addr-typed`, so an exploratory `addr-typed`
   win over `addr-full` remains conservative evidence for promoting
   `mask-spine-refs`; a loss is uninformative and licenses nothing.
3. **Secondary (§4.6):** semantic success pre-registered comparison is
   `addr-full` vs `addr-none` at α = 0.05 (≥ 5 successes vs 0 clears);
   `addr-typed`'s counts reported with intervals only.
4. **§4.8 check 2** is replaced as annotated in place: blindness clause
   unchanged; row sets byte-match the audit's recomputation; the
   route-incompleteness table is reproduced and carried into the report.
5. Arms, cost, seeds, budgets, and every other §4 rule are unchanged.

---

## 5. Cost

One `g2-standard-4` (1 × NVIDIA L4 24 GB, 4 vCPU), us‑central1, in **runlist mode**
— all three arms on one instance, self-deleting at the end, the shape landed in
`beed5a8`. Spot first, on-demand on stockout (the pattern the powered A/B was
forced into on 2026‑08‑23).

Duration: the corpus-size sweep measured 0.65–0.86 h per arm for 205 `full_corpus`
plus 50 `held_out` draws. This runs 320 held-out draws per arm at a 768‑token cap
(vs 512) and up to a 51 % longer prompt, so ≈ 1.6 h per arm is budgeted, plus
≈ 0.3 h boot, model load and build-cache restore: **≈ 5.1 h wall clock**.

| Line | Unit price | Quantity | Cost |
|---|---|---|---|
| `g2-standard-4` Spot, us‑central1 | $0.25/h | 5.1 h | **$1.28** |
| `g2-standard-4` on-demand (stockout fallback) | $0.85/h | 5.1 h | **$4.34** |
| Artifacts bucket, standard storage | $0.020/GB‑month | ≈ 5 GB × 6 h | < $0.01 |
| Egress fetching results to the checkout | $0.12/GB | ≈ 0.05 GB | $0.01 |
| **Total, Spot** | | | **≈ $1.29** |
| **Total, on-demand worst case** | | | **≈ $4.35** |

Both sit inside the ~$6 per-experiment scale this project has operated at. The
diversity harvest's ≈ $0.60/run on-demand anchor is reproduced here as
5.1 h × $0.85/h ÷ 3 arms ≈ $1.45/arm — higher per arm than the sweep's because each
arm runs 6.4× the held-out draws.

**Teardown is part of the run, not after it.** The runlist instance self-deletes;
the bucket and the Terraform root are destroyed by the run's own task, and the
results are copied into `prototype/runs/` *before* the bucket goes — the failure
the diversity harvest's teardown section warns about. Any IAM binding teardown that
needs a human is surfaced as an explicit ask, not attempted by an agent.

---

## 6. What each outcome licenses

| Outcome | What it licenses next |
|---|---|
| Primary significant in either address arm **and** ≥ 6 semantic successes | Addressing was the ceiling. The held-out battery is live for the first time. Worked derivations (§2.3) and external import (§2.1) become interpretable experiments; re-run the corpus-mass question on an addressable prompt, where its ≈ 800 draws/arm requirement can finally be spent on something measurable. |
| Primary significant, semantic successes < 6 | The model can now *reach* the right definitions but cannot *assemble* them. Addressing is solved; composition is the residual. Next lever: **hole-directed decomposition** (§2.2), with the spine-aware mask (§2.4) as its companion, since every hole is a checking-mode position where the mask is at its strongest. |
| Primary null in both arms | Addressing is not the binding constraint at this model scale — a real, publishable negative, and the first one this project has produced with adequate power. Retire the addressing hypothesis, go to decomposition, and put a model-scale arm (a larger or unquantized model on the same battery) on the table as an honest question rather than an excuse. |
| `addr-none` alone produces semantic successes | The 512‑token cell budget was the whole ceiling. Report it as a harness defect: **retract**, not merely qualify, every held-out conclusion this project has drawn, and re-run the diversity and corpus-size held-out arms under the §4.3 harness before any of their held-out claims are cited again. |
| `addr-typed` beats `addr-full` (exploratory) | Retrieval, not presence, is what the context is short of — which promotes the spine-aware mask (§2.4) from follow-up to lever, since it is the same filter applied at decode time rather than at prompt time. |

---

## 7. Consequences for the results already on record

Stated here so the next reader is not misled by the archive:

- The **diversity-harvest** verdict's negative — *"selecting for structural
  informativeness bought nothing measurable"* — stands for `full_corpus`. Its
  held-out half (*"zero of 22 non-vacuous definitions solve a held-out task"*) is
  **not evidence about composition**: 7 of the 8 tasks could not be solved from the
  prompt they were asked with, and each cell got ~1.1 usable draws.
- The **corpus-size sweep**'s primary result is unaffected (§1.3): its censoring is
  flat across arms, so *"no trend detected — underpowered, not refuted"* is
  unchanged. Its held-out sentence — *"Held-out semantic success remains at zero
  across every run this project has recorded"* — is true and should from now on be
  cited with the reason.
- The **powered held-out A/B** (2026‑08‑23) spent 11.28 h and $9.59 on a comparison
  whose treatment arm could not have produced a held-out success either. Its
  `full_corpus` half is unaffected.

None of these reports is edited by this plan. A one-paragraph addendum pointing at
§1 is deliverable 6.

---

## 8. Deliverables

1. `prototype/experiment/addressability_audit.py` — the §1 diagnostic as a
   runnable script: per-task route addressability, route-reference rates over
   recorded runs, cell censoring statistics, address-book sizing. No GPU, no
   network. Its output is what §1's pasted blocks must reproduce.
2. Address-book construction in `prototype/experiment/prompts.py` behind a config
   field (`address_book: "none" | "full" | "typed"`), plus the goal-type filter,
   plus tests in `prototype/test_experiment.py` pinning §4.8's assertions —
   in particular that the filter cannot see `composes` or a gold term.
3. `prototype/experiment/heldout_gold.py` — a verified gold `(def …)` for each
   surviving held-out task, with the funnel/rubric evidence and the drop record
   for any task without one.
4. `prototype/experiment/address_book_stub_check.py` — §4.8's five checks, run on
   CPU, output pasted back into this plan before launch.
5. Three configs (`addr_none`, `addr_full`, `addr_typed`) plus an
   `address-runlist.json`, matching the sweep's runlist shape.
6. `docs/results/2026-08-25-address-book-report.md` — arms, the §4.5 primary with
   its Holm correction, hand-scored secondaries with intervals, the §6 licensing
   row that actually fired, teardown evidence, and a short addendum note appended
   to the two 2026‑08‑24 reports pointing at §1.

Deliverables 1–4 are CPU-only and gate the GPU spend. Nothing launches until 4's
output is in this file.

---

## 9. What would change this plan

- **A gold term cannot be written for three or more tasks under 768 tokens.** The
  battery, not the corpus, is then the problem; §4.4's stopping condition fires and
  the battery is redesigned first.
- **The stub check shows the arms differ by more than the block.** Fix the prompt
  builder; do not launch a run whose arms are not byte-comparable.
- **`addr-full` cannot fit `n_ctx`** for some task. Drop to the `hash + name` row
  format (2,935 characters, ≈ 1.9k tokens) for both address arms together, never
  for one.
- **Someone produces a held-out semantic success on the existing harness.** Then
  §1.2's "unsolvable" claim has a counterexample and must be re-derived before this
  plan is worth running.
