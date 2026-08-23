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

## 4a. Cross-cloud parallel execution — pre-registered before either arm's results land

The two arms initially queued sequentially on one GCP GPU (the fixed
`google_compute_instance` name in `infrastructure/gcp/modules/experiment-runner`
forced one-instance-at-a-time). Generalized the module for N concurrent
runners (`instance_suffix`, `manage_bucket` variables — commit
`<module-fix>`) and built `infrastructure/gcp/experiment-pair/`, a root that
instantiates it twice sharing one bucket; both `terraform validate` clean.
That path turned out to be blocked at the account level, not the config
level: `GPUS_ALL_REGIONS = 1.0` project-wide in this GCP trial project (every
region, every GPU type, checked directly against
`gcloud compute project-info describe`), so two simultaneous GCP GPU
instances cannot exist regardless of how Terraform is shaped. A quota
increase was filed for next time; it does not help this run.

**Decision: cross-cloud parallel instead — curated arm stays on GCP
(`g2-standard-4`, on-demand, §4), generated arm moves to the existing AWS
sibling infra (`infrastructure/aws/`, `g6.xlarge`) on Spot** (AWS on-demand
G/VT quota is 0 in this account — `L-DB2E81BA` — so Spot is the only
available AWS path; Spot G/VT quota is 8 vCPUs, comfortably covering one
`g6.xlarge`'s 4). Both instance types carry the same silicon: one NVIDIA L4
24 GB. Same pinned llama.cpp revision
(`1f368f354d9edcfea9fd6a1e0989b3e7335a050f`), same GGUF, same quantization,
same sampling config, same `n_ctx`, same store snapshot (§2) — only the
compute host differs.

**Pre-registered comparability assumption, stated before either result is
known:** per-token acceptance rate from seeded, budget-limited draws is a
property of the model + quantization + sampling + grammar/mask pipeline, not
of which cloud's identical-GPU instance executed it — GCP and AWS L4s run the
same CUDA compute capability (Ada, sm_89) and the harness's `acc/1k tok`
metric is defined over tokens generated and definitions accepted, neither of
which is a wall-clock or vendor-specific quantity. The supporting evidence is
the curated arm's own replication history: the curated heldout12 cell on GCP
(§1) reproduced phase-b's earlier cells to the third decimal
([turn 2 note](../plans/2026-08-14-corpus-loop.md#turn-2-and-the-12-seed-sample-2026-08-15)),
i.e. this metric has already been shown stable across repeated independent
runs on the *same* cloud; the untested step is *across* clouds on the same
GPU architecture, which is a materially smaller assumption. If the two arms'
`mean lat s` columns diverge sharply in the final report (a real hardware or
driver difference, e.g. differing CPU generation feeding the GPU, differing
memory bandwidth), that is flagged in §5 as a caveat on the comparison, but
latency is not part of the accept/attempt count the Fisher test scores.

Laptop-independent execution is ported to both paths: each instance's own
startup/user-data script drives the run, uploads its artifacts to its
cloud's own object store, and self-terminates
(`gcloud compute instances delete` in `finish()` on GCP;
`shutdown -h now` under `instance_initiated_shutdown_behavior = "terminate"`
on AWS) — neither depends on a held SSH session or this laptop staying
awake. The GCP driver's model-upload step was hardened
(`scripts/run-remote-experiment-gcp.sh`) after a 39-minute silent stall with
zero progress on the first launch attempt: it now checks the bucket for an
existing object before touching the network, and wraps any real upload in a
bounded, retried `timeout` instead of blocking indefinitely. Local
supervision from here on is short, retry-tolerant polls only — no long
foreground blocking calls.

---

## 5. Result

*(filled in after both arms complete)*
