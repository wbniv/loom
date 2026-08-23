# Plan — A diversity-seeking harvest: select what enters the loop, not everything

**Date:** 2026‑08‑23
**Status:** Planned — pre-registered, not yet run.
**TODO entry:** `[wip T4] [diversity-harvest]` (TODO.md line 30).
**Parent:** [the corpus loop](2026-08-14-corpus-loop.md)'s closing verdict —
"the loop reliably buys recall (+31 % per token, stable across two turns) and
buys no measured composition … needs a larger sample **or a diversity-seeking
harvest** (turn 2 showed self-reproductions plateau) to become a claim."
Built on the same harness, the same store, and the same
[GCP L4 Spot infra](2026-08-14-gcp-experiment-infra.md).

**Visible surface:** none. The harvest is a one-line-JSON CLI and the arms are
config files; per the house rule, no mockup bundle.

---

## The finding this attacks, restated as a measurement

`harvest.py` R1 admits "what the funnel accepted, and nothing looser". Nothing
*looser* — but also nothing narrower. Applied to the recorded runs it produces a
store whose generated half is mostly noise. Measured over the shipped
`.loom-store-generated` (41 generated definitions), and over the pool of every
accepted draw this project has recorded:

| population | n | distinct normalised type signatures | bare constants |
|---|---:|---:|---:|
| `.loom-store-generated`, generated half | 41 | 21 | 19 |
| all recorded runs, distinct accepted identities | 62 | — | 23 are a single `(lit …)` |

Of the 62 distinct accepted identities across every run in
`prototype/runs/`, **42 contain no computation at all** — no `app`, `ref`,
`match`, `perform`, `handle` or `fix` anywhere in the term. 23 of them *are* a
literal: `(def I64 (lit i64 0))`, `(def Bool (lit bool true))`,
`(def Unit (lit unit))`. Sixteen of the 41 shipped generated objects came from
one task, `corpus/clock/now`, and thirteen of them share the type `I64`.

The store also holds the exact degenerate shape that produced turn 2's
hand-scored FAIL. `generated/corpus/list/append/631d16b8e72b` is

```
(def (fn (data …(I64)) () (fn (data …(I64)) () (data …(I64))))
     (lam (data …(I64)) (lam (data …(I64)) (let (data …(I64)) (var 0) (var 1)))))
```

— a two-argument function that ignores its first argument. The held-out
mechanical-floor failure the 12-seed run turned up was `λa. λb. let c = b in b`
for `heldout/list/reverseThen`: **the same skeleton, already sitting in the
model's context as a harvested example.**

So "harvest everything accepted" is not a neutral policy. It fills the loop's
context with type-correct vacuities, and at least one of them is a worked
example of precisely the failure mode the experiment is trying to move.

**One honest caveat, measured before it could flatter the hypothesis.** The
vacuity is not being *amplified* by the loop. Per-run rate of accepted draws
that are constant-valued or ignore a parameter:

| run | accepted | vacuous share of accepted | vacuous share of distinct |
|---|---:|---:|---:|
| `followup-curated` | 56 | 0.036 | 0.200 |
| `followup-generated` (turn 1) | 75 | 0.040 | 0.214 |
| `followup-gen-turn2` | 70 | 0.043 | 0.182 |
| `phase-b` | 109 | 0.358 | 0.605 |
| `phase-a-full` | 193 | 0.207 | 0.586 |

The generated arm is not more degenerate than the curated one. The vacuity in
the store comes from *where it was harvested* — `phase-b` and `phase-a` ran the
`none` and `few_shot` regimes, where a model with no corpus in context answers
with a literal. Harvest-everything then promoted those answers into the
context of every later full-corpus run. That is a selection defect, not a
degeneration spiral, and this plan fixes the selection.

---

## Rules

### R1 — Selection is a harvest-side policy, not a prompt-side filter

`harvest.py` gains `--select POLICY`. The default is `all`, which is today's
behaviour **byte-for-byte**; the corpus-loop plan's recorded counts are the
regression guard (verification step 2). Prompt assembly and
`experiment/store_resolver.py` are untouched, so the origin filter keeps meaning
exactly what it meant.

**Rejected: a selection policy on `StoreResolver`.** It would have kept one
store on disk, but it would put "which generations are worth showing" into the
experiment's resolver alongside "which origins this arm reads" — two different
kinds of decision behind one flag — and the store would then hold objects it
had admitted but nothing could ever see. Admission is where the store decides
what it believes; that is the honest place for a policy about what is worth
believing.

### R2 — The pool is every recorded run, and it is a set

`--records` becomes repeatable. Candidate identities are pooled across all
given record files. Everything that made the harvest reproducible stays
reproducible: the files are processed **in sorted `provenance.source` order**,
not in command-line order, so the output is a function of the *set* of runs and
not of how the operator typed them; `sequence` is still
`SEQUENCE_BASE_GENERATED` + position among accepted records in that canonical
order; first accepted record still wins for `name` and `provenance`.

### R3 — Held-out-task draws never enter the store

`--exclude-task-prefix heldout/` is passed by every arm in this plan. A
previously-accepted answer to `heldout/list/reverseThen` is not an answer key
(prompt assembly's leave-one-out already excludes an example whose digest *is*
the expected identity), but a *wrong* answer to the very task under evaluation
is contamination that leave-one-out does not catch, and the shipped
`.loom-store-generated` contains four such objects. Excluding them makes the
new arms strictly *less* contaminated than the recorded baseline, so a win
cannot be attributed to it.

### R4 — The `distinct-shape` policy: three gates, no hyperparameters

A candidate is admitted only if it passes all three. Each is a total function
of the definition's IR and of the curated corpus; none looks at the task spec,
the run's `semantic_success`, or anything held-out.

| gate | rejects | why |
|---|---|---|
| **G1 — non-constant** | a body containing no `var`, no `ref` and no `perform` | its value is fixed at write time; it computes nothing and depends on nothing. Kills all 23 bare literals and `(if (lit …) (lit …) (lit …))`. |
| **G2 — every parameter used** | a body that binds a top-level `lam` parameter it never references | the `let c = b in b` family — type-correct functions that discard an input the type promised to consume. |
| **G3 — novel structural class** | a candidate whose (skeleton, normalised type) class already has an exemplar, in the curated corpus or among candidates already selected | a definition structurally identical to one already in the prompt, differing only in leaf constants, adds bytes and no shape. |

*Skeleton* is the term IR with every leaf payload erased — de Bruijn indices,
hashes, literal values and type annotations all replaced by a hole — keeping
term tags, tree shape, and `match` arm binder counts. *Normalised type* is the
declared type's surface with every 64‑hex hash rewritten to a single token, so
two definitions over the same data declaration land in the same class. Both are
computed from the IR through the binding structure `scope.check_term` already
defines, rather than from the surface string, so the analysis cannot drift from
the validator's own idea of what binds what.

**Rejected: a continuous structural distance with a farthest-point traversal.**
That is the textbook diversity selector and it is the wrong instrument here.
A continuous metric needs a threshold or a budget, and with a 58-candidate pool
any value would be a free parameter fitted to nothing. Exact structural-class
equality is the same idea at distance 0, is a *decision* rather than a ranking,
and has nothing to tune. It is also auditable: the results table can name the
class each rejected candidate collided with.

**Rejected: "harvest only the `full_corpus` and `held_out` regimes".** It is a
one-line provenance filter that would remove most of the same objects, because
the vacuity is concentrated in the low-context regimes. It was rejected because
it is a proxy: it would keep a vacuous `full_corpus` draw and discard a
structurally novel `few_shot` one, and it says nothing about redundancy. The
structural gates are what the finding actually names.

### R5 — Counting stays the deliverable

The report line gains a `selection` block: the policy, the pool size, the count
surviving each gate, and the tally of rejections by gate. `not_selected` joins
`admitted` / `exists` / `refused_on_readmission` and the count invariant grows
to include it, so the line still cannot quietly lose a draw.

### R6 — Out of scope

Re-running the loop for a turn 3; any ranking of generated objects by quality;
promotion, evidence objects or curation tiers; changing the model, the
conditions or the token budget; any spec change.

---

## The arms, and why a size-matched control is not optional

The `distinct-shape` policy over the pooled runs yields **15** definitions from
58 candidates (58 → 29 after G1 → 22 after G2 → 15 after G3). The recorded
generated baseline had 41. **Corpus size is the largest effect this experiment
has ever measured** (95.8 % → 71.5 % rejection, `none` → `full_corpus`), so a
15-definition arm compared only against a 41-definition arm would confound
selection with size — and in the direction that makes a null uninterpretable.

There is no way to remove the confound by matching counts upward: the entire
pool contains only 22 non-vacuous identities, so a count-matched diverse-41
does not exist. The confound is therefore controlled with a third arm rather
than designed away.

| arm | generated objects | selected from | status |
|---|---:|---|---|
| `curated` | 0 | — | **recorded**: 4/96 held-out, 0.081 acc/1k tok, replicates to the third decimal |
| `generated` | 41 | harvest-everything over `phase-b` + turn 1 | **recorded**: 7/96 held-out, 0.142 acc/1k tok |
| **`diverse`** | 15 | `distinct-shape` over the 58-candidate pool | **new** |
| **`sizematch`** | 15 | the same pool, ascending identity hash | **new** |

`sizematch` is the control that makes a null informative. It draws the same
count from the same pool; identity is a content hash, so ascending-hash order is
an unbiased sample with respect to structure, and it is perfectly reproducible.
`diverse` vs `sizematch` differs in exactly one thing: **which** 15.

Everything else is held at the recorded baselines' values — `n_ctx` 32,768 in
every arm (a differing transport parameter is a confound for no gain), the same
condition `gbnf+typemask`, the same pruners, the same 512‑token budget, the same
temperature 0.8, the same seeds.

### What the four arms actually are, as built

Measured from each store's own `export-resolver.json`, re-analysed
independently of the selector (verification steps 3 and 4):

| arm | generated defs | surface chars | vacuous share | distinct structural classes |
|---|---:|---:|---:|---:|
| `curated` | 0 | 0 | — | — |
| `generated` (recorded) | 41 | 7,916 | 0.610 | 26 of 41 |
| `sizematch` | 15 | 1,998 | **0.667** | 10 of 15 |
| `diverse` | 15 | 4,015 | **0.000** | 15 of 15 |

**The honest limitation: the arms are count-matched, not byte-matched.** A
non-vacuous definition is simply longer than `(def I64 (lit i64 0))`, so
`diverse` occupies 4,015 surface characters against `sizematch`'s 1,998 — about
1,300 extra prompt tokens on an ~12,000‑token base. Matching count *and* bytes
while changing content is not possible, and the asymmetry runs **toward**
`diverse`, so a `diverse` win is partly attributable to context mass. It is
recorded here rather than argued away, and the recorded `generated` arm is the
useful third point: 41 definitions and 7,916 characters — twice `diverse`'s
bytes and nearly three times its count — at essentially `sizematch`'s vacuity.
If `diverse` matches or beats *that*, mass is not what was doing the work.

### Runs

Revised from this plan's first draft, before anything was launched, on the
grounds that **the held-out regime cannot settle anything at n = 96**: the
recorded arms are 4/96 and 7/96, Fisher p ≈ 0.35, and more underpowered
held-out arms buy more of the same. The `full_corpus` regime is where the
measurement has power — 206 draws, 55–72 accepted — so the controlled
`diverse` vs `sizematch` contrast is run *there*, and the 12‑seed held-out
sample is spent on `diverse` alone, where it is comparable to two recorded
baselines and is the only place a semantic success could appear.

| # | arm | config shape | draws | compares against |
|---|---|---|---:|---|
| 1 | `diverse` | full_corpus + held_out, 3 seeds | ~230 | turn 1 1.803 · turn 2 1.728 · curated 1.377 |
| 2 | `sizematch` | full_corpus + held_out, 3 seeds | ~230 | run 1 — the controlled contrast, at power |
| 3 | `diverse` | held_out, 12 seeds | 96 attempts | curated 4/96 · generated 7/96 |
| 4 (reserve) | `sizematch` | held_out, 12 seeds | 96 attempts | run 3, if runs 1–3 make it worth it |

Three runs, a fourth held in reserve. Prior runs of these shapes took
1,959–3,031 s, so ~2.5 h of g2‑standard‑4 Spot.

### Two things the implementation settled that the first draft had not

**The pool is 8 runs, not 11.** `phase-a-full-attempt1`,
`phase-b-partial-batchassert` and `phase-b-partial-oom` have no `summary.json`
and therefore no *recorded* model identity, and corpus-loop R2.1 refuses to
admit a generation that cannot say which model produced it.
`scripts/build-store-variant.sh` skips them **by name on stderr** rather than
silently. It costs nothing: the 8 pooled runs still yield all 62 distinct
accepted identities, so the aborted runs contributed no identity the survivors
did not.

**`size-match:<n>` counts objects that will actually enter the store.** The
first build of the control arm asked for 15 and landed **13**: two of the
hash-ordered picks were byte-identical to curated corpus objects, so content
addressing deduped them into the curated object and the control quietly stopped
matching the size it was named for. Candidates the store already holds are now
rejected at their own gate (`already-held`) before the budget is applied, and a
budget larger than the available pool is an error rather than a smaller arm.

---

## Cost

| line | unit price | quantity | cost |
|---|---|---|---:|
| `g2-standard-4` Spot, us‑central1 | $0.25/h | 3 runs × ≤ 2 h | $1.50 |
| boot disk, GCS, egress (per the infra plan's ≈ $0.61 all-in) | — | 3 runs | ≈ $0.33 |
| | | **total** | **≈ $1.83** |

Charged against the $300 GCP trial credit, so $0.00 in practice. Well under the
dispatch's ~$15 escalation threshold. Instances are torn down by the driver's
`EXIT` trap and delete themselves when their startup script ends. A fourth run
(`sizematch` at the `full_corpus` shape) is held in reserve and costs another
≈ $0.61 if runs 1–3 make the full-corpus comparison worth controlling too.

---

## Pre-registered predictions

Written before any of the three runs is launched. Scored in the results doc
whatever they say.

**P1 — held-out acceptance, `diverse`.** `held_out` acc/1k tok lands in
[0.08, 0.25], i.e. statistically indistinguishable from *both* recorded
baselines at n = 96. Confidence **0.7**.

**P2 — held-out semantic success, `diverse`.** Zero draws score 1 under the
hand-scoring rubric below. Confidence **0.85**. This is the prediction the
whole plan would most like to be wrong about.

**P3 — the mechanism test.** `diverse` beats `sizematch` on `held_out`
acc/1k tok. Confidence **0.6** — deliberately weak, because this is the only
prediction that tests whether *selection* rather than *size* or *noise* is
doing anything, and the honest prior after two flat turns is close to a coin.

**P4 — content, not mass.** `diverse`'s `full_corpus` acc/1k tok is ≥ 1.377
(the curated baseline) and within ±15 % of 1.803 / 1.728, **despite 63 % fewer
generated definitions**. Confidence **0.6**. If it holds, the loop's recall gain
is about what the examples show, not how many bytes they occupy — which is a
positive result even if P2 and P3 both fail.

**P5 — repeat rate.** `diverse`'s repeat rate (1 − distinct/accepted) falls
below the 0.836–0.847 band both prior arms sat in. Confidence **0.5**.

**P6 — degeneracy of the output.** The vacuous share of `diverse`'s accepted
draws (G1 ∪ G2 applied to what the model *emits*, not to what was harvested) is
lower than `sizematch`'s. Confidence **0.55**. Baseline for the `full_corpus`
shape is 0.040 (turn 1) / 0.043 (turn 2); for `held_out` at 12 seeds it is
0.143 (1 of 7).

### Hand-scoring rubric — written before any draw is looked at

The R3 pattern, and the same rubric that caught turn 2's false positive. It
applies to every held-out draw that clears the mechanical floor (funnel
`accepted` **and** exact declared-type match), and to nothing else.

Procedure: read the task's spec text first, then the term's normal form, then
score. Record the term, the spec, the score and the one-line reason in the
results document **for every scored draw regardless of outcome**.

Score **1** only if the term computes the function the spec describes for every
input of the declared type.

Score **0**, explicitly and without further argument, when any of these hold:

1. the term ignores a parameter the spec requires it to consume;
2. the term returns a constant where the spec requires dependence on an input;
3. the term reaches the declared type by projecting or discarding structure the
   spec requires it to preserve (turn 2's `let c = b in b`);
4. the term is correct only on a proper subset of the declared input type;
5. the reviewer cannot determine the term's normal form — an undecided draw is
   a 0, never an omission.

A draw scored 1 is reported with its full surface so the score can be
challenged.

---

## Work

- [ ] `prototype/harvest_select.py` — skeleton, normalised type, the three
      gates, the `all` / `distinct-shape` / `size-match:<n>` policies (R1, R4).
- [ ] `prototype/test_harvest_select.py` — the gates as assertions, including
      the `let c = b in b` regression case and the "default policy is
      byte-identical" guard.
- [ ] `harvest.py`: repeatable `--records`, `--select`, `--exclude-task-prefix`,
      the `selection` block and the widened count invariant (R2, R3, R5).
- [ ] `scripts/run-remote-experiment-gcp.sh`: pack **every**
      `.loom-store*/export-resolver.json`, not the one hardcoded path — three
      store variants now exist and a fourth is a config file away.
- [ ] Taskfile: `store:harvest-select` building a named store variant from the
      pooled runs.
- [ ] Three arm configs + their stub-backend guard tests.
- [ ] Runs 1–3, results in `docs/results/`, verification recorded below.

---

## Verification

1. `task prototype:test` green, including the new selection tests; the existing
   `test_harvest.py` passes **unmodified** — the default policy did not move a
   byte.
2. `--select all` over `phase-b` alone reproduces the corpus-loop plan's
   recorded counts exactly: 773 records, 109 accepted, 38 distinct identities,
   34 admitted, 75 exists, 0 refused.
3. The `diverse` store's generated half, read back from its own
   `export-resolver.json` and re-analysed independently of the selector: 15
   definitions, none constant-valued, none ignoring a parameter, all in
   distinct structural classes, none sharing a class with a curated definition.
4. The `sizematch` store: 15 generated definitions, drawn from the same pool,
   with its vacuity composition reported as a number.
5. `fsck` exit 0 on both new stores; every arm's prompts under
   `include_generated: false` byte-identical to the curated arm's.
6. All three arm configs run end-to-end on the stub backend, with each arm's
   longest prompt and its `context_required` reported against `n_ctx`.
7. Runs 1–3 complete; the metrics table against the recorded baselines, every
   pre-registered prediction scored, and the hand-scoring rubric applied to
   every held-out draw that met the mechanical floor.
8. `task todo:lint`; `git diff --check`.

## Recorded verification

Steps 1–6 and 8 run 2026‑08‑23 on branch `diversity-harvest` (worktree
`/home/will/loom-wt-diversity`). The numbered steps are the plan's own,
unchanged; raw output follows each. **Step 7 is the GPU run and is
outstanding** — see the note under it.

### 1. `task prototype:test` green, including the new selection tests; the existing `test_harvest.py` passes **unmodified** — the default policy did not move a byte

```
----------------------------------------------------------------------
Ran 737 tests in 79.790s

OK (skipped=2)
```

`test_harvest.py` on its own, and untouched by this branch:

```
$ python3 -m unittest test_harvest
................................................
----------------------------------------------------------------------
Ran 48 tests in 1.742s

OK

$ git diff main -- prototype/test_harvest.py
(no output: the file is untouched by this branch)
```

New tests: 29 in `test_harvest_select`, 14 in `test_diversity_arms`.

**PASS.**

### 2. `--select all` over `phase-b` alone reproduces the corpus-loop plan's recorded counts exactly: 773 records, 109 accepted, 38 distinct identities, 34 admitted, 75 exists, 0 refused

```
$ python3 harvest.py --records .../runs/phase-b/records.jsonl --dry-run \
      --resolver .../.loom-store/export-resolver.json
{
 "accepted": 109, "admitted": 34, "distinct_identities": 38, "dry_run": true,
 "exists": 75, "not_selected": 0, "records": 773, "refusals": [],
 "refused_on_readmission": 0,
 "selection": {"policy": "all", "pool": 38, "rejected_by_gate": {},
               "selected": 38,
               "stages": [{"stage": "pool", "surviving": 38},
                          {"stage": "selected", "surviving": 38}]},
 "status": "harvested"
}
```

Every number matches the corpus-loop plan's recorded line. `not_selected: 0`
and an empty `rejected_by_gate` are the new fields saying, in the report itself,
that the default policy turned nothing away.

**PASS.**

### 3. The `diverse` store's generated half, read back from its own `export-resolver.json` and re-analysed independently of the selector: 15 definitions, none constant-valued, none ignoring a parameter, all in distinct structural classes, none sharing a class with a curated definition

The build, over the pooled runs:

```
$ task store:diverse
skip phase-a-full-attempt1: no summary.json (no recorded model identity)
skip phase-b-partial-batchassert: no summary.json (no recorded model identity)
skip phase-b-partial-oom: no summary.json (no recorded model identity)
pooling 8 run(s) under policy 'distinct-shape'
{"accepted": 514, "admitted": 15, "distinct_identities": 62, "exists": 41,
 "not_selected": 458, "records": 4296, "refused_on_readmission": 0,
 "selection": {"policy": "distinct-shape", "pool": 62,
   "rejected_by_gate": {"constant": 29, "excluded-task": 4,
                        "redundant-shape": 7, "unused-parameter": 7},
   "selected": 15,
   "stages": [{"stage": "pool", "surviving": 62},
              {"stage": "task-filter", "surviving": 58},
              {"stage": "g1-non-constant", "surviving": 29},
              {"stage": "g2-parameters-used", "surviving": 22},
              {"stage": "g3-novel-shape", "surviving": 15}]}}
{"ok": true, "rows": 63}
```

`15 + 41 + 458 = 514`, so the widened count invariant holds. `rows: 63` is
48 store objects + 15 generated.

Re-analysed from the store's own export rather than from the report
(`test_diversity_arms.ArmStoreTest`, and the same numbers printed directly):

| arm | generated defs | constant | ignores a parameter | distinct classes | clashing with curated | surface chars |
|---|---:|---:|---:|---:|---:|---:|
| `diverse` | 15 | **0** | **0** | **15 of 15** | **0** | 4,015 |
| `sizematch` | 15 | 10 | 1 | 10 of 15 | 0 | 1,998 |
| `generated` (recorded, for reference) | 41 | 20 | 6 | 26 of 41 | 2 | 7,916 |

**PASS.**

### 4. The `sizematch` store: 15 generated definitions, drawn from the same pool, with its vacuity composition reported as a number

```
$ task store:sizematch
pooling 8 run(s) under policy 'size-match:15'
{"accepted": 514, "admitted": 15, "distinct_identities": 62, "exists": 26,
 "not_selected": 473, "records": 4296,
 "selection": {"policy": "size-match:15", "pool": 62,
   "rejected_by_gate": {"already-held": 4, "excluded-task": 4, "over-budget": 39},
   "selected": 15,
   "stages": [{"stage": "pool", "surviving": 62},
              {"stage": "task-filter", "surviving": 58},
              {"stage": "not-already-held", "surviving": 54},
              {"stage": "selected", "surviving": 15}]}}
{"ok": true, "rows": 63}
```

Vacuity composition: **10 of 15 constant-valued, 1 ignoring a parameter,
10 distinct structural classes** — against `diverse`'s 0, 0 and 15. The
manipulation is real and in the intended direction. Overlap: `diverse` and
`sizematch` share 5 of their 15 objects, so the arms are neither disjoint nor
near-identical.

`already-held: 4` is the finding from the first build attempt, now visible on
the line: four pool identities are byte-identical to curated corpus objects and
would dedupe away, so they no longer consume budget. Before that fix this arm
asked for 15 and landed 13.

**PASS.**

### 5. `fsck` exit 0 on both new stores; every arm's prompts under `include_generated: false` byte-identical to the curated arm's

`fsck` is the `{"ok": true, "rows": 63}` line in steps 3 and 4 — exit 0 on both,
63 objects and 63 index rows each.

The byte-identity half is proven by `test_harvest.OriginFilterTest`, untouched
by this branch, which builds `34 tasks × 4 regimes × 2 leave-one-out = 272`
prompt pairs through a harvested export and asserts byte equality on every one.
This branch adds no code between the origin filter and `build_prompt`:

```
$ git diff main --stat -- prototype/experiment/prompts.py \
                          prototype/experiment/store_resolver.py
(no output: neither file is touched by this branch)
```

**PASS.**

### 6. All three arm configs run end-to-end on the stub backend, with each arm's longest prompt and its `context_required` reported against `n_ctx`

All *four* configs, since the reserve arm ships too:

```
$ python3 -m experiment.diversity_stub_check
arm                    defs  digests  gen  required   n_ctx   head  recs  stub prompt tokens
diverse_followup         41       62   15     15331   32768  2.14x     4  [5506, 5506, 5553, 5553]
sizematch_followup       41       62   15     13987   32768  2.34x     4  [5001, 5001, 5049, 5049]
diverse_heldout12        41       62   15     15331   32768  2.14x     2  [5553, 5553]
sizematch_heldout12      41       62   15     13987   32768  2.34x     2  [5049, 5049]

diverse vs sizematch prompt tokens : [5506, 5506, 5553, 5553] vs [5001, 5001, 5049, 5049]
context required                   : 15331 vs 13987
OK: the arms differ in what the model is shown
```

Every arm resolves 26 curated + 15 generated definitions; every arm clears its
own longest prompt with more than 2× headroom at the baselines' `n_ctx` of
32,768; and the arms differ in **what the model is shown**, not only in what
resolves — the escalation the corpus-loop plan raised, restated for these arms
and asserted rather than hoped.

The 15,331 vs 13,987 gap is the byte asymmetry named above, as a number:
1,344 tokens, about 9 % of the smaller requirement.

**PASS.**

### 6b. The scoring is pre-registered as code, and checked against the recorded baselines

Not one of the numbered steps. `experiment/diversity_report.py` computes the
metrics table, scores P1–P6 and emits the hand-scoring worksheet; it was
committed **before any arm was launched**, so the post-run job is to read
numbers out rather than to decide which numbers to read. Run today against the
recorded baselines alone:

```
$ python3 -m experiment.diversity_report --runs-dir .../runs --run followup-curated …
arm / run                 regime         draws  acc   acc/1k distinct  repeat  sem  vacuous
followup-curated          full_corpus      196   55    1.377        9   0.836    5    0.036
followup-generated        full_corpus      206   72    1.803       11   0.847    6    0.042
followup-gen-turn2        full_corpus      206   69    1.728       10   0.855    6    0.043
heldout12-curated         held_out         188    4    0.081        2   0.500    0    0.000
heldout12-generated       held_out         193    7    0.142        5   0.286    1    0.143
```

Every published figure reproduces exactly — 1.377, 1.803, 1.728, 4/96 at 0.081,
7/96 at 0.142 — so the scorer agrees with the recorded reports before it is
asked about anything new. P1–P6 all print `NOT RUN`, which is the correct
answer today.

**And the worksheet found the right draw by itself.** The mechanical-floor
selector — funnel `accepted` *and* exact declared-type match — surfaced exactly
one draw across every recorded run: `heldout12-generated`,
`heldout/list/reverseThen`, seed 4 draw 0. That is precisely the draw turn 2
hand-scored FAIL, recovered without being told to look for it.

**A finding worth its own line: the G2 gate reproduces that hand-scored FAIL
mechanically.** The `vacuous` column above is G1 ∪ G2 applied to what the model
*emitted*, and `heldout12-generated`'s held-out share is 0.143 — one draw of
seven — which is the same draw. A reviewer reading the term concluded
"type-correct, ignores its first argument, reverses nothing"; the de Bruijn walk
concluded "binds a top-level parameter it never references". They agree, on the
only case where both have an opinion.

That is one case, so it is a promising sign and not a validated proxy — the
rubric stays partly human for exactly the reasons R3 gave. But it does mean the
vacuity metric is measuring the thing it was introduced to measure, which is
more than could be said for it an hour ago.

### 7. Runs 1–3 complete; the metrics table against the recorded baselines, every pre-registered prediction scored, and the hand-scoring rubric applied to every held-out draw that met the mechanical floor

**OUTSTANDING — not run.** GPU quota in the project is one accelerator and the
powered held-out A/B has priority on it, so no arm of this plan has been
launched. Everything the runs depend on is built and verified above, and every
prediction in this document was written before any of them.

One infrastructure finding came out of the attempt, recorded because it is a
finding and not a detour. Launching against the shared Terraform root while
another run held the same state **overwrote that run's `results_prefix` and
`status_key` outputs**. Nothing was destroyed — no instance existed yet — but
two roots that share a state prefix are one lock and one set of outputs however
carefully their variables differ, and a minute later there would have been two
drivers contending for one `loom-experiment-runner` name and one GPU.
`infrastructure/gcp/experiment-diversity` now gives these arms their own
backend prefix, instance suffix and artifacts bucket; the driver's EXIT-trap
teardown defaults to instance-only rather than a blanket destroy; and a new
preflight refuses to start while a runner that is not this invocation's is
standing. See step 8's `infra:validate`.

### 8. `task todo:lint`; `git diff --check`

```
$ task todo:lint
TODO.md: clean
todo:lint exit=0

$ git diff --check
(no output)
```

Not one of the numbered steps, recorded because this branch adds a Terraform
root and `fmt`/`validate` is the cheapest evidence it is not broken:

```
$ task infra:validate
── infrastructure/gcp/experiment
Success! The configuration is valid.
── infrastructure/gcp/experiment-pair
Success! The configuration is valid.
── infrastructure/gcp/experiment-diversity
Success! The configuration is valid.
```

**PASS.**

## Completion criteria

- The selection is reproducible: the same pool and policy yield the same store,
  byte-identically, on a fresh checkout.
- The default harvest is unchanged, proven by the recorded counts.
- Every pre-registered prediction is scored against the runs, including the
  ones that fail.
- The verdict is written whichever way it goes — "diversity harvest does not
  move composition either" is a result and gets the same treatment as a win.
