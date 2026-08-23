# Powered held-out A/B — pre-registration and result

**Date:** 2026-08-23
**Question:** [Turn 2 and the 12-seed sample](../plans/2026-08-14-corpus-loop.md#turn-2-and-the-12-seed-sample-2026-08-15)
left the held-out acceptance advantage directional and unproven: generated
7/96 vs curated 4/96, ≈1.75×, Fisher p ≈ 0.35 at n = 96/arm. This run scales
the sample until that question is statistically decided, using the harness
and store exactly as they stood after the 12-seed sample — no code change,
no harvest.

## 1. Pre-registered power analysis

**Observed rates (from the 12-seed heldout12 sample, both n = 96):**

| arm | accepted | attempts | rate |
|---|---:|---:|---:|
| curated | 4 | 96 | 0.04167 |
| generated | 7 | 96 | 0.07292 |

**Method.** Two calculations, both run before any new draw:

1. **Normal approximation**, two-proportion test, α = 0.05 two-sided, 80%
   power:

   ```
   n = [z_(α/2)·√(2·p̄·(1-p̄)) + z_β·√(p1(1-p1)+p2(1-p2))]² / (p1-p2)²
   ```

   with `p1 = 0.04167`, `p2 = 0.07292`, `p̄ = 0.05729`, `z_(α/2) = 1.96`,
   `z_β = 0.8416` → **n ≈ 867/arm**.

2. **Monte Carlo power of the actual test we will run (Fisher's exact,
   two-sided, α = 0.05)** — the normal approximation is known to
   under-count for small proportions and a discrete exact test, so it is
   not trusted alone. 20,000–30,000 simulated trials per candidate `n`,
   binomial draws at the two observed rates, `scipy.stats.fisher_exact`
   scored against α = 0.05:

   ```
   n=  96  power=0.086     n= 600  power=0.607
   n= 150  power=0.145     n= 700  power=0.679
   n= 200  power=0.205     n= 800  power=0.742
   n= 250  power=0.269     n= 850  power=0.768
   n= 300  power=0.313     n= 900  power=0.791
   n= 350  power=0.366     n= 950  power=0.817
   n= 400  power=0.424     n=1000  power=0.829
   n= 450  power=0.476     n=1050  power=0.855
   n= 500  power=0.525     n=1100  power=0.870
   ```

   Crossing 80% power under the exact test lands around **n ≈ 920–950/arm**,
   close to but slightly above the normal-approximation figure — expected,
   since Fisher's exact test is conservative relative to the asymptotic
   approximation at these small proportions.

**Pre-registered target: n = 952/arm, chosen as follows.** The held-out
regime has exactly 8 tasks (confirmed: `_held_out()` is called 8 times in
`prototype/experiment/prompts.py`), so attempts come in multiples of 8 per
seed (`attempts = seeds × 8`, matching the 12-seed sample's 12 × 8 = 96).
107 additional seeds gives 107 × 8 = 856 new attempts/arm; pooled with the
96 already run, that is 952/arm — inside the 920–950 crossing band, at
Monte Carlo power ≈ 0.817 (interpolated between the 900 and 950 rows
above), clearing the 80% target.

**Pooling decision (pre-registered, decided before any new draw).** The 96
existing attempts per arm from the heldout12 run **count toward the
total**. Justification: the new runs replicate the heldout12 arms exactly —
same store snapshot (§2), same config in every field but seeds and
`output_dir` (§3), same `n_ctx`, same conditions/pruners/regimes/tasks. The
only thing that differs is which of 12 vs 107 independent seeds drove the
sampling, and seeds are exchangeable under the harness's own design (each
seed is an independent draw stream over the same task set). Pooling two
runs that differ only in seed is therefore not a confound; refusing to pool
would throw away 96 real, already-paid-for attempts per arm for no
statistical reason. Total is a **simple sum of accepted/attempts** across
the heldout12 run and the new run, per arm.

## 2. Store snapshot — verified frozen, byte-identical to the heldout12 runs

Both new configs point at the same `store_export` the heldout12 arms used:
`.loom-store-generated/export-resolver.json`. Verified before launch:

```
$ ./store/target/debug/loom-store --store .loom-store-generated list --kind definition
count: 67 origins: {'generated': 41, 'transpiled': 26}

$ sha256sum .loom-store-generated/export-resolver.json
bd8c6e5e4c3650d5c5be64eaeec2ff3278d4084eb9a25553863f8c25bc82daa1

$ git status --short -- store/ prototype/ .loom-store .loom-store-generated
(clean — no output)
```

67 definitions (41 generated + 26 curated), matching the generated arm's
heldout12 report (`"definition": 67`) exactly, and `git status` over the
store and harness trees is clean — nothing has mutated them since the
12-seed sample (the concurrently-dispatched harvest-variant work is in an
isolated worktree and does not touch this checkout). **Store frozen,
confirmed.** This run does not harvest; the store is not written to at any
point in §4.

## 3. Run configuration — heldout12 arms replicated, seeds and n only

[`prototype/experiment/heldout_powered_curated.config.json`](../../prototype/experiment/heldout_powered_curated.config.json)
and
[`prototype/experiment/heldout_powered_generated.config.json`](../../prototype/experiment/heldout_powered_generated.config.json),
each a copy of the corresponding `heldout12_*.config.json` with two fields
changed: `seeds` (13–119, 107 fresh non-overlapping seeds — heldout12 used
1–12) and `output_dir`. `n_ctx: 32768`, `store_export`,
`include_generated`, `conditions: ["gbnf+typemask"]`, `pruners`,
`regimes: ["held_out"]`, `leave_one_out: true` are untouched. Diffed
against the originals and against each other before launch:

```
$ diff heldout12_curated.config.json heldout_powered_curated.config.json
  (seeds, output_dir only)
$ diff heldout12_generated.config.json heldout_powered_generated.config.json
  (seeds, output_dir only)
$ diff heldout_powered_curated.config.json heldout_powered_generated.config.json
  include_generated, output_dir only
```

Local stub-backend dry-run before spending anything, confirming the
resolver state matches the heldout12 reports and the cell count matches
107 × 8:

```
$ python3 -m experiment.runner --config experiment/heldout_powered_curated.config.json --dry-run
resolver objects   : {"ability": 8, "data": 4, "definition": 26, "extern": 9}
resolver origins   : {"declared": 21, "generated": 0, "transpiled": 26}  (policy: curated)
cells to run       : 856

$ python3 -m experiment.runner --config experiment/heldout_powered_generated.config.json --dry-run
resolver objects   : {"ability": 8, "data": 4, "definition": 67, "extern": 9}
resolver origins   : {"declared": 21, "generated": 41, "transpiled": 26}  (policy: all)
cells to run       : 856
```

### 3a. Zone provenance — a note against a claim nobody makes

Neither arm ran in the same GCP zone as the other, nor as the heldout12
baseline, nor as each other's own dry-run assumption: heldout12
(curated + generated, §1's baseline) ran on `europe-west4-c` (per its
`startup-script.log`); this run's curated arm launched on `us-central1-a`
but hit a GCE stockout there (no `g2-standard-4` + L4 capacity) and was
relaunched on `us-central1-c`, the zone Google's own stockout error named
as having capacity; the generated arm (§4a) is queued for whichever zone
has capacity when its quota lands. None of this is treated as a
confound: the metric this report scores — definitions accepted per 1,000
tokens generated, from a fixed model/quant/sampling/grammar pipeline
against a fixed store snapshot — has already reproduced across zones
without moving (the curated heldout12 cell matched phase-b's earlier cell
to the third decimal, and phase-b itself ran on yet another zone,
per the [corpus-loop plan's turn-2 note](../plans/2026-08-14-corpus-loop.md#turn-2-and-the-12-seed-sample-2026-08-15)).
Zone is not part of any provenance field this comparison depends on;
GPU silicon (one NVIDIA L4, Ada / sm_89, whichever zone it is racked in)
is what would matter, and that is constant across every run in this
report and its baseline.

## 4. Cost estimate and infra decision (pre-registered before launch)

Per-draw latency measured directly from the heldout12 runs (mean
latency column in their reports): curated 10.334 s/draw over 188 draws in
1958.7 s; generated 13.165 s/draw over 193 draws in 2558.1 s. Scaling
856 new attempts by each arm's own draws-per-attempt ratio from that run
(curated 188/96 = 1.958; generated 193/96 = 2.010):

| arm | new draws (est.) | new draw time | + measured overhead (build cache hit, boot, upload/download) | total instance time |
|---|---:|---:|---:|---:|
| curated | ≈ 1,677 | ≈ 4.86 h | ≈ 150 s | ≈ 4.90 h |
| generated | ≈ 1,721 | ≈ 6.34 h | ≈ 155 s | ≈ 6.38 h |
| **total** | | | | **≈ 11.28 h** |

**Spot vs on-demand.** The task named "the established GCP L4 spot infra
(~$0.61/run)" as the default, but that figure prices the original ~35–45
minute single-arm runs. [The GCP infra plan's own recorded operational
lesson](../plans/2026-08-14-gcp-experiment-infra.md#operational-lesson--spot-vs-on-demand-under-trial-credits-2026-08-14)
is explicit: *"A spot L4 was preempted 30 minutes into a run... While the
$300 trial credits last, on-demand is the default for real runs."* At
≈ 4.9 h and ≈ 6.4 h respectively, these runs are ~7–10× longer than
anything run on spot so far, and a preemption's recovery path is uncertain
here: results sync to GCS only from the `finish()` trap at the very end of
the startup script (`gsutil rsync` inside `trap finish EXIT`), and GCE's
preemption notice window (~30 s) may not be enough for that trap to run
before the instance is torn down — unlike a clean exit, there's no
guarantee of a partial upload to resume from. Losing 5–6 hours of paid
compute to a preemption, with no automatic resume, is the exact risk the
plan's own lesson exists to avoid. **Decision: run both arms `--on-demand`,
not spot.** This is a config flag on the existing driver
(`scripts/run-remote-experiment-gcp.sh --on-demand`), not a harness change.

Cost at on-demand pricing ($0.85/h, `g2-standard-4`, us-central1, per the
infra plan's own table):

| line | rate | quantity | cost |
|---|---|---|---:|
| `g2-standard-4` on-demand | $0.85/h | 11.28 h | $9.59 |
| 150 GB `pd-balanced` boot disk | $0.10/GB-month | 150 GB × 11.28 h | $0.23 |
| GCS storage (tarball + model, 7-day expiry) | $0.020/GB-month | ~5 GB × 7 d | $0.05 |
| GCS ops + egress | — | a few hundred ops, ~50 MB | < $0.02 |
| **total (estimate)** | | | **≈ $9.9** |

**Under the $15 stop-and-escalate threshold — proceeding.** (Spot pricing
would have put the same compute at ≈ $3.2; the on-demand premium here is
≈ $6.7, paid for eliminating a multi-hour redo risk on a run whose whole
point is to be decisive.)

## 4a. Parallel execution, GCP-only — pre-registered before either arm's results land

The two arms initially queued sequentially on one GCP GPU (the fixed
`google_compute_instance` name in `infrastructure/gcp/modules/experiment-runner`
forced one-instance-at-a-time). Generalized the module for N concurrent
runners (`instance_suffix`, `manage_bucket` variables) and built
`infrastructure/gcp/experiment-pair/`, a root that instantiates it twice
sharing one bucket; both `terraform validate` clean. That path turned out
to be blocked at the account level, not the config level:
`GPUS_ALL_REGIONS = 1.0` project-wide in this GCP trial project (every
region, every GPU type, checked directly against
`gcloud compute project-info describe`), so two simultaneous GCP GPU
instances could not exist regardless of how Terraform was shaped.

A cross-cloud fallback (curated on GCP, generated on the existing AWS
`g6.xlarge` sibling infra, Spot — AWS on-demand G/VT quota is 0 in this
account) was drafted and partially built (a store-export packing fix for
`scripts/run-remote-experiment.sh`) but **overridden by the user directly:
GCP only, no AWS spend, on a $300 GCP trial-credit budget.** The AWS-side
change was reverted, uncommitted, and abandoned.

**What actually ran: a GCP quota increase (`GPUS_ALL_REGIONS` and
`NVIDIA_L4_GPUS`/us-central1, 1 → 2) requested via the Cloud Quotas API
(`gcloud quotas preferences create`, both quotas flagged
`quotaIncreaseEligibility.isEligible: true` — self-service, not a support
ticket), with the curated arm launched immediately on the one GPU-slot of
quota already available, and the generated arm queued to launch the moment
the increase lands — genuinely parallel if the quota arrives in time,
otherwise sequential with no idle wait either way.** Both arms run on
identical GCP infrastructure (`g2-standard-4`, one NVIDIA L4 24 GB,
on-demand), so no cross-vendor comparability question arises at all — the
comparability question this run actually carries is the zone one (§3a),
which is smaller and already has supporting evidence from the baseline.

**Per-consumer Terraform state isolation.** The original shared
`infrastructure/gcp/experiment` root's state was found clobbered mid-run —
a concurrently-dispatched T4 agent (isolated worktree, developing a
harvest-variant experiment, out of scope for this dispatch per the
original brief) applied against the same backend prefix at the same time
and overwrote its outputs. Rather than reconcile a shared state under
concurrent writers, each arm got its own, sharing nothing but the account's
GPU quota: `infrastructure/gcp/experiment-solo/` (curated;
state prefix `experiment-solo`, bucket
`loom-experiment-artifacts-19b81040-curated`, instance name
`loom-experiment-runner-curated`) and `infrastructure/gcp/experiment-solo-b/`
(generated; prefix `experiment-solo-b`, bucket
`loom-experiment-artifacts-19b81040-generated`, instance name
`loom-experiment-runner-generated`). `scripts/run-remote-experiment-gcp.sh`
gained `LOOM_GCP_TF_DIR`/`LOOM_GCP_BUCKET` overrides (same style as the
existing `LOOM_GCP_ZONE`) so this needed no script fork. A distinct
instance name per root matters even with separate Terraform states: GCE
instance names must be unique within a project/zone regardless of which
state manages them, so both roots pin `instance_suffix` explicitly rather
than relying on state separation alone.

Laptop-independent execution: each instance's own startup script drives
the run, uploads its artifacts to GCS, and self-deletes
(`gcloud compute instances delete` in the startup script's `finish()`
trap) — none of it depends on a held SSH session or this laptop staying
awake. The model-upload step was hardened twice: first (after a
39-minute silent stall with zero progress on the first launch attempt) to
check the bucket for an existing object before touching the network and
wrap any real upload in a bounded, retried `timeout`; then to parallel
composite upload via `gcloud storage cp` with a 120-minute cap, which
uploaded the 4.7 GB model in 33 minutes. Local supervision is short,
retry-tolerant polls against GCS state directly (not a local driver
process or its log), every 10 minutes, run from a persistent background
watcher — so it doesn't matter which session's terminal actually launched
either arm's driver invocation.

**Teardown checklist (§5 must confirm all of these before this report is
closed):**

- [ ] Curated arm: instance self-deleted (confirm via
      `gcloud compute instances list` — should be absent).
- [ ] Generated arm: instance self-deleted, same check.
- [ ] **Explicit bucket removal for both arms.** Both launches used
      `--keep-bucket` (added after the stockout/relaunch on `us-central1-a`
      → `us-central1-c`, so a retry never re-pays for the model upload) —
      unlike a normal run, teardown does **not** destroy
      `loom-experiment-artifacts-19b81040-curated` or `-generated`
      automatically. Once both arms report SUCCEEDED and results are
      downloaded, remove both buckets explicitly
      (`gcloud storage rm -r gs://loom-experiment-artifacts-19b81040-curated`
      and the `-generated` twin), or leave them if a same-day re-run is
      still plausible — either way, record the decision here rather than
      leaving it silently undone.
- [ ] `infrastructure/gcp/experiment-solo/` and `-solo-b/` states destroyed
      (`launch_runner=false` re-apply or full `destroy`) so no IAM binding
      or bucket-shell resource lingers in Terraform state after the buckets
      themselves are gone.

---

## 5. Result

*(filled in after both arms complete)*
