# Plan — Corpus-size sweep: does acceptance track definition count, or content?

**Date:** 2026-08-24
**Status:** Complete. All four arms (sweep08/15/25/41) ran on 2026‑08‑24 via
runlist mode on the diversity root, all `SUCCEEDED`; results fetched to
`prototype/runs/sweep-size{08,15,25,41}/` and the root fully destroyed
(instance, bucket, IAM) per §3's teardown. The §2.7 trend test ran for real
(LR p = 0.128, Wald p = 0.131 — not significant) and the results report
(deliverable 4) is committed:
[`docs/results/2026-08-24-corpus-size-sweep-report.md`](../results/2026-08-24-corpus-size-sweep-report.md).
Verdict: **no trend detected — underpowered, not refuted**, per §2.7's own
pre-committed reading of a null result at ≈38% power.
**TODO entry:** `[corpus-size-sweep]`
**Parent:** [the diversity-harvest report](../results/2026-08-24-diversity-harvest-report.md),
["What this does not license"](../results/2026-08-24-diversity-harvest-report.md#what-this-does-not-license):
*"'Corpus mass drives acceptance' is the pattern in these numbers, and it is
suggestive rather than established: every pairwise comparison behind it is
non-significant (p = 0.29–1.00) … It earns a follow-up that varies corpus size
deliberately — the same generations at 15/25/41 definitions — not a claim."*

**Visible surface:** none. Store variants and config files only; per house
rule, no mockup bundle.

---

## 1. What is settled, and what this run decides

Three sizes recorded so far (0, 15, 41 generated definitions) each differ in
size **and** in which draws were selected — `sizematch`'s 15 and `diverse`'s
15 are different draws at the same count; `generated`'s 41 used the `all`
policy over a different pool composition than either 15. That confound is
exactly why every pairwise comparison behind the mass-vs-quality table is
non-significant: the arms differ in more than one axis at once, so even a
real trend cannot be told apart from run-to-run draw variation.

This sweep removes the confound by construction: one pool, one deterministic
ordering, four nested prefixes. If the ordering `full_corpus` 1.377 / 1.40–1.48
/ 1.73–1.80 is a real mass effect, four points along one monotone axis should
show it as a trend — not as any single pairwise win, which the diversity
harvest already showed is underpowered at this budget.

## 2. Pre-registration

### 2.1 Sampling rule

One pool: the **55 candidates** that are (a) accepted identities across every
run recorded under `prototype/runs/` as of this commit, (b) not drawn for a
`heldout/*` task (`--exclude-task-prefix heldout/`, the harvest tooling's
existing default — held-out tasks must not leak into the training-side
corpus), and (c) not already content-addressed into the curated store
(`already-held`, `harvest_select.select`'s existing `size-match` gate). This
is `harvest_select.py`'s existing `size-match:<n>` policy, unmodified — the
diversity-harvest plan already built and tested it; this sweep reuses it for
a different purpose (a nested prefix at four sizes) rather than its original
one (a neutral-size control).

**Note on the pool size named in this item's dispatch (58) vs. the measured
count (55):** re-run today, `build-store-variant.sh --select all --dry-run`
reports 61 non-heldout distinct identities, of which 6 are already
content-addressed into the curated store, leaving 55 fresh. The discrepancy
is not investigated further — 55 is what the tooling reports right now, over
every run currently on disk, and is the number this plan uses. (It is
plausible the dispatch's 58 predates one of the later-recorded runs, e.g.
`heldout-powered-{curated,generated}`, which add candidates and duplicates
to the pool.)

**Ordering: ascending by content-hash identity** (64-hex object hash),
exactly as `harvest_select.select`'s `size-match` policy already sorts —
"a content hash, so ascending order is a sample unbiased with respect to
structure" (`harvest_select.py`'s own docstring). This is the one part of
the design that must be fixed *before* looking at any candidate's content,
and hash order is the cheapest thing available that carries no information
about quality, task, or vacuity. It is not tuned per size: the same 55-item
sorted list is prefixed at each budget, so `chosen(n) ⊆ chosen(m)` for
`n < m` follows from taking a longer prefix of the *same* list, not from
re-sampling.

**Verified nested-subset property**, by direct set inclusion over the built
stores' `origin: generated` object hashes:

```
size=  8 total_objects=34 generated_count=8
size= 15 total_objects=41 generated_count=15
size= 25 total_objects=51 generated_count=25
size= 41 total_objects=67 generated_count=41
nested 8 <= 15: True
nested 15 <= 25: True
nested 25 <= 41: True
```

### 2.2 Sizes

**8, 15, 25, 41 generated definitions**, plus the recorded **0-definition
curated baseline reused as the anchor, not re-run** (`followup-curated`:
full_corpus 55/196 draws accepted, 1.377 acc/1k tok; held_out 1/47 draws,
0.081 acc/1k tok — [`docs/results/2026-08-14-followup-curated-report.md`](../results/2026-08-14-followup-curated-report.md)).
Five points on the size axis, four of them freshly run under one sampling
rule.

41 is the ceiling: it is both the largest size this project has already
characterized (the `generated` turn-1/turn-2 store) and inside the 55-item
fresh pool with margin (41 ≤ 55, leaving 14 candidates unused — needed so
`size-match` has a fresh candidate to draw from at every prefix length
without the largest arm exhausting the pool exactly at its own boundary).

### 2.3 Store construction

```
scripts/build-store-variant.sh --store .loom-store-sweep08 --select size-match:8
scripts/build-store-variant.sh --store .loom-store-sweep15 --select size-match:15
scripts/build-store-variant.sh --store .loom-store-sweep25 --select size-match:25
scripts/build-store-variant.sh --store .loom-store-sweep41 --select size-match:41
```

Each rebuilds a store from the curated corpus plus its own prefix of the same
55-item pool, `fsck`s clean, and exports its resolver. Stores are gitignored
(`.loom-store*`), same as every store variant this project has built; the
build commands above are the reproduction recipe, run against whatever
`prototype/runs/` holds — see §2.1's caveat about the pool drifting as new
runs are recorded.

### 2.4 Run configuration

Four configs,
[`prototype/experiment/sweep08.config.json`](../../prototype/experiment/sweep08.config.json),
`sweep15`, `sweep25`, `sweep41` — each a byte-for-byte copy of the
diversity-harvest's `diverse_followup.config.json` (seeds `[1, 2, 3]`,
`gbnf+typemask`, pruners `goal-type`/`de-bruijn`/`ref-hash`, regimes
`full_corpus` + `held_out`, `leave_one_out: true`, `n_ctx: 32768`) with only
`store_export` and `output_dir` changed:

```
$ diff diverse_followup.config.json sweep08.config.json
  store_export, output_dir only
```
(same diff shape for sweep15/25/41, confirmed for all four before this commit)

Reusing that exact config means the matched-budget property the diversity
harvest already demonstrated (identical seeds ⇒ identical attempt/draw counts
regardless of store content) carries over here without re-deriving it: every
arm below drew from the *same* three seeds against the *same* task set, so
draws-per-arm is fixed by the harness, not by anything about store size.

### 2.5 Stub-backend dry-run — reproduces resolver composition, no GPU

```
$ python3 -m experiment.corpus_size_sweep_stub_check
arm        size defs  digests  gen  required   n_ctx   head  recs  stub prompt tokens
sweep08       8   34       55    8     13037   32768  2.51x     4  [4645, 4645, 4693, 4693]
sweep15      15   41       62   15     14039   32768  2.33x     4  [5021, 5021, 5068, 5068]
sweep25      25   51       72   25     15325   32768  2.14x     4  [5503, 5503, 5550, 5550]
sweep41      41   67       88   41     17788   32768  1.84x     4  [6427, 6427, 6474, 6474]

sweep41 headroom: n_ctx=32768 required=17788 (1.84x)

prompt-token totals by size (must be non-decreasing): [(8, 18676), (15, 20178), (25, 22106), (41, 25802)]
OK: sweep41 fits n_ctx with headroom, and prompt tokens grow monotonically with size
```

The largest arm fits `n_ctx` with 1.84× headroom, and prompt-token totals
over a fixed two-task/one-seed sample grow strictly with declared store size
— the resolver is doing what the definition counts say it is doing.

```
$ python3 -m experiment.runner --config experiment/sweep08.config.json --dry-run
resolver objects   : {"ability": 8, "data": 4, "definition": 34, "extern": 9}
resolver origins   : {"declared": 21, "generated": 8, "transpiled": 26}  (policy: all)
cells to run       : 102

$ python3 -m experiment.runner --config experiment/sweep15.config.json --dry-run
resolver objects   : {"ability": 8, "data": 4, "definition": 41, "extern": 9}
resolver origins   : {"declared": 21, "generated": 15, "transpiled": 26}  (policy: all)
cells to run       : 102

$ python3 -m experiment.runner --config experiment/sweep25.config.json --dry-run
resolver objects   : {"ability": 8, "data": 4, "definition": 51, "extern": 9}
resolver origins   : {"declared": 21, "generated": 25, "transpiled": 26}  (policy: all)
cells to run       : 102

$ python3 -m experiment.runner --config experiment/sweep41.config.json --dry-run
resolver objects   : {"ability": 8, "data": 4, "definition": 67, "extern": 9}
resolver origins   : {"declared": 21, "generated": 41, "transpiled": 26}  (policy: all)
cells to run       : 102
```

All four arms: 102 cells, matching the diversity-harvest precedent's own
per-arm cell count (3 seeds × 2 regimes × 17 tasks) exactly, and matching
each other exactly — the matched-budget property (§2.4) confirmed directly
rather than assumed.

### 2.6 Primary metric

**`full_corpus` accepted/1,000 generated tokens (acc/1k tok), at the matched
draw budget each arm actually produces** — the same metric the diversity
harvest and both corpus-loop turns used, so this sweep's numbers sit in the
same table as the recorded 0/15/41 points without a metric change confounding
the comparison. `held_out` acc/1k tok and hand-scored semantic success are
recorded as secondary outcomes, exactly as in the diversity-harvest report,
because the mechanical floor is known (from that report and the powered A/B)
to produce false positives that need the R3 rubric before any composition
claim can be made from them.

### 2.7 Trend test — pre-registered, before any GPU run

**Primary test: logistic-regression likelihood-ratio test.** Each `full_corpus`
draw is a Bernoulli trial (accepted / not accepted). Fit
`logit(P(accepted)) = β0 + β1 · log1p(defs)` by maximum likelihood over the
pooled draws from all five points (the reused 0-def anchor plus the four
fresh arms), and test `H0: β1 = 0` via the likelihood-ratio statistic against
the intercept-only null, χ² with 1 df, two-sided, **α = 0.05**. Reported
alongside (not instead of) the Wald p-value on β1, for cross-check.

**Why this test over the alternatives named in the dispatch:**
- **Cochran-Armitage** would use the same five ordinal groups and is
  asymptotically equivalent to this logistic score test; it was not chosen
  because Python's standard stack here (`scipy`, no `statsmodels`) has no
  built-in CA implementation, and hand-rolling one adds a second numerical
  path to validate for no statistical gain over the LR test already
  implemented and checked (§below).
- **`log1p(defs)` rather than `defs` or `log(defs)`** — the anchor is
  `defs = 0`, where `log` is undefined; `log1p` is defined there, keeps the
  four fresh points' spacing close to `log`'s (which is what the diversity
  report's own read of the data — "monotone in how much generated context
  the arm carries" — suggests as the more plausible functional form than a
  linear one, since the jump from 0→8 defs plausibly matters more than
  25→41), and costs nothing at the other four points since `log1p(x) ≈
  log(x)` once `x` is not tiny.
- **A single pairwise test (e.g. 0 vs. 41) was rejected as the primary
  claim**, deliberately: §2.8 shows it is the *worse*-powered choice at this
  budget, precisely because it spends the whole draw budget on two of the
  five points instead of pooling information across all of them.

**Implementation:**
[`prototype/experiment/corpus_size_sweep_power.py`](../../prototype/experiment/corpus_size_sweep_power.py)
contains the exact LR-test code (`_lr_test`) that will be re-run on the real
draw-level data once all four arms complete; the analysis script for the
report reuses this function rather than reimplementing the test a second
time.

### 2.8 Power statement — stated honestly, before any run

Planning assumption: per-draw `full_corpus` acceptance rates interpolated
`log1p`-linearly between the two ends of the range this project has already
measured — curated (0 defs) 55/196 = 0.2806, generated-41 turn 1
72/206 = 0.3495. This is not a claim about the true rate at 8/15/25 defs; it
is the shape the pre-registered power calculation is honest about assuming,
taken from the only two points on this exact axis this project has run.

```
$ python3 prototype/experiment/corpus_size_sweep_power.py
planning rates (per-draw accept probability, log1p-linear interpolation):
  defs=  0  p=0.2806
  defs=  8  p=0.3211
  defs= 15  p=0.3317
  defs= 25  p=0.3407
  defs= 41  p=0.3495

trend test (logistic-regression LR test, log1p(size), alpha=0.05):
  n_sims=2000  power=0.377

cross-check: pairwise 0-vs-41 (Fisher exact, two-sided, alpha=0.05):
  n_sims=4000  power=0.272

cross-check: pairwise small-effect 0.28-vs-0.31 (~0.3 acc/1k tok gap):
  n_sims=4000  power=0.083
```

**Honest reading: at ~198 draws/arm (the matched budget the diversity-harvest
runs actually produced), the pre-registered trend test has ≈38% power under
this planning assumption — well under the conventional 80% threshold.** It is
nonetheless the best-powered pre-registered choice available at this budget:
the same planning assumption gives the *best-case* pairwise comparison
(0 vs. 41, the two most different arms) only ≈27% power, and a comparison
sized to the ~0.3 acc/1k tok gaps actually seen between adjacent recorded
points (§ diversity-harvest report's table) only ≈8%. The trend test pools
information the pairwise tests each throw away four-fifths of.

**What this means for interpretation.** A non-significant trend test at this
budget is not evidence *against* the mass hypothesis — it is close to a coin
flip either way under the planning assumption above. A significant one is
good evidence *for* it, since a spurious trend at ≈38% power under the true
null (no effect) still has only a 5% false-positive rate by construction
(that is what α = 0.05 means, independent of power). The report will state
the result as "trend detected" / "no trend detected — underpowered, not
refuted" rather than treating a null result as a refutation, and will name
the sample size a decisive answer would need (extrapolated from the power
curve) if the trend test comes back null.

**No mid-run peeking, no post-hoc test-shopping.** The test, its formula, and
its threshold are fixed above before any of the four GPU runs launch.
Whatever the four `full_corpus` numbers turn out to be, §2.7's test is the
one reported as primary.

---

## 3. Execution

GCP-only, on-demand, sequential (project quota: 1 GPU). Reuses the
diversity-harvest's isolated Terraform root
(`infrastructure/gcp/experiment-diversity`, own state prefix, own bucket,
`--instance-suffix diversity`) — it shares no resource with `../experiment`
or `../experiment-solo{,-b}`, and per the diversity-harvest report's teardown
section it is idle (instances: none; its own bucket was removed after that
report's runs; the isolation the root was built for means reusing it here
does not touch any other run's state).

Zone-cycling wrapper, same pattern as the diversity harvest's
`launch-diversity-runs.sh` (STOCKOUT and transient network errors retry the
next zone; anything else aborts): `europe-west4-c/b/a`, then
`us-central1-a/b/c` (no `-f`, no L4 capacity there).

Budget: 4 runs at the diversity-harvest's own measured per-run cost (≈$0.60
on-demand for a ~45 min `full_corpus`+`held_out` combined run at this task
count) ⇒ **≈$2.40, hard ceiling $6** — escalate before exceeding it, per this
item's dispatch.

Model: server-side `gcloud storage cp` from an existing bucket that already
holds the GGUF (e.g. the diversity or heldout-powered buckets, if either
still exists at launch time) rather than a laptop re-upload; the launch
wrapper checks for the object first, same as `launch-diversity-runs.sh`'s
`seed_model` background job.

Teardown: instance-only per run (the driver's own `finish()` trap); a full
root `terraform destroy` plus bucket removal once all four results are
copied into `prototype/runs/` (gitignored, matching every prior run in this
project).

## 4. Deliverables

1. This pre-registration (§2), committed before any GPU run. ✅
2. Stores `.loom-store-sweep{08,15,25,41}` and configs
   `prototype/experiment/sweep{08,15,25,41}.config.json`, stub-validated. ✅
3. Four GCP runs (`sweep08`, `sweep15`, `sweep25`, `sweep41`), sequential,
   on-demand, zone-cycled. ✅
4. [`docs/results/2026-08-24-corpus-size-sweep-report.md`](../results/2026-08-24-corpus-size-sweep-report.md):
   the four arms' full_corpus/held_out numbers, the §2.7 trend test run for
   real, hand-scoring of any held-out mechanical-floor candidates against the
   R3 rubric, and an honest verdict — confirmed / refuted / still
   underpowered, stated as such. ✅ — LR test p = 0.128 (Wald cross-check
   p = 0.131), not significant at α = 0.05: **no trend detected —
   underpowered, not refuted**, exactly the reading §2.7 pre-committed to for
   a null result at this power. One held-out mechanical-floor candidate
   arose (`sweep41` · `heldout/list/reverseThen`) and hand-scored **0**,
   matching the identical term's prior FAIL on this exact task. A decisive
   answer needs ≈800 draws/arm (≈4× this budget) against the observed effect
   size.

## 5. What would change this plan

If a run's actual draw count differs meaningfully from the 102-cells-per-arm
dry-run (§2.5) — e.g. a crash requiring a partial re-run at different
seeds — the pooled trend test in §2.7 still works (logistic regression does
not require equal group sizes), but the §2.8 power statement would need
re-deriving from the actual n. That is a re-run of
`corpus_size_sweep_power.py` with the real per-arm draw counts substituted,
not a design change.
