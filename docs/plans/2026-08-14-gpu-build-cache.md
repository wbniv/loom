# Plan — GPU build cache for the experiment runner

**Date:** 2026-08-14
**Status:** In progress (live capture armed; template patch landing)
**Parent:** [GCP experiment infra](2026-08-14-gcp-experiment-infra.md)

## Objective

Stop paying the ~10–15 minute CUDA llama.cpp compile on every instance boot.
Each Phase A run currently rebuilds the pinned revision from source on a
4-vCPU box before any GPU work starts — pure rented-clock waste after the
first build.

## Rules

### R1 — A revision-keyed tarball in GCS, not a custom image

The cache is one object:

```
gs://loom-experiment-artifacts-<suffix>/builds/llama-<revision>-cu129-g2.tar.gz
```

The startup script checks it before building: hit → download and extract
(~30 s in-region); miss → build as today, then upload the `build/` tree so
every later run hits. The key embeds the pinned llama.cpp revision and the
CUDA/machine flavor, so bumping the pin or changing GPU family invalidates
naturally — no manual cache management, ever.

**Rejected: a custom VM image.** It would also skip the apt step (~1 min
more saved) but costs a 20+ GB managed artifact, an image-bake workflow, and
a second thing to rebuild on revision bumps. The tarball is ~300 MB, lives
in the bucket that already exists, and expires with the bucket's lifecycle
if unused. **Rejected: a container registry** — same benefits as the
tarball with strictly more moving parts (Artifact Registry, docker pulls)
for a single-binary payload.

### R2 — Opportunistic capture from the live run

The currently running instance is compiling that exact build. A background
waiter polls for `build/bin/llama-server` over SSH and, the moment it
exists, has the *instance* tar its build tree directly into the cache path
(the instance's service account already holds objectAdmin on the bucket).
If the capture wins, even the next run skips the compile; if it loses a
race with the run's self-deletion, the template patch guarantees the run
after that seeds the cache instead. Either way the cache converges.

### R3 — Failure honesty

A cache-download failure falls back to building from source (the cache is
an optimization, never a dependency). The upload after a fresh build is
best-effort (`|| log`-and-continue): a failed upload must not fail a
successful run.

## Work

- [x] Arm the live capture against the in-flight instance.
- [ ] Patch `startup-script.sh.tftpl`: cache check → extract, else build →
  best-effort upload.
- [ ] Render-check the template (`bash -n` on rendered output) and
  `terraform fmt`/`validate` the module.
- [ ] Record the capture outcome (won or lost the race) here.

## Verification

```sh
terraform -chdir=infrastructure/gcp/modules/experiment-runner fmt -check
bash -n <rendered startup script>
task todo:lint
git diff --check
```

plus the operational proof: the next remote run's serial log shows
`build cache hit` and reaches "server up" minutes faster; recorded here
after that run.

## Completion criteria

- The cache object exists (from capture or first post-patch run).
- A subsequent run boots to a serving llama-server without invoking cmake.
- A deliberate cache miss (revision bump) still builds and re-seeds.
