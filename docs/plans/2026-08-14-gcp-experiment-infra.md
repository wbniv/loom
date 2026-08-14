# Plan — GCP infrastructure for the Phase A experiment run

**Date:** 2026‑08‑14
**Status:** Implemented; `terraform fmt` + `validate` PASS, `shellcheck` clean, apply gated on the operator running it
**Implements:** the second substrate for the live‑run half of [Masked‑generation experiment, Phase A substrate and harness](2026-08-13-experiment-phase-a.md)
**Sibling of:** [GPU infrastructure for the Phase A experiment run](2026-08-13-gpu-experiment-infra.md) — the AWS stack, whose artifact flow, driver structure and cost discipline this one mirrors deliberately

## Compute-path directive (operator, 2026-08-14)

**GCP is the compute path; do not use AWS.** The AWS G-quota was eventually
approved on appeal, but GCP runs are covered by $300 in trial credits
(≈ 490 Spot runs) while AWS bills real money. The AWS stack
(infrastructure/aws/) stays as a built, tested emergency fallback only —
launching there requires an explicit fresh operator instruction.

## Operational lesson — spot vs on-demand under trial credits (2026-08-14)

A spot L4 was preempted 30 minutes into a run, mid-build, with the exit trap
unexecuted (no status object, no synced artifacts — the driver polled a ghost
until stopped). While the $300 trial credits last, **on-demand is the default
for real runs**: 2.4× of free is free, and preemption risk goes to zero. Spot
remains the recorded default in the module for the post-credit era.

## Objective

The AWS stack is built and waiting on an EC2 GPU allocation. Google's trial
account has $300 of credits, an approved GPU quota, and L4s in us‑central1 at a
third of the AWS price. This plan builds the GCP twin so the Phase A matrix can
run on whichever cloud is ready first, with the *same* one command shape, the
*same* artifact flow, and the same guarantee: nothing survives the run.

The constraint that shapes every decision is unchanged from the AWS plan: **a run
must cost under a dollar, and must not be able to cost more than that by
accident.** It is engineered against three times here — the driver destroys on
every exit path, the instance deletes itself when the startup script ends, and a
Spot VM's `instance_termination_action = "DELETE"` removes it on preemption.

No visible surface: this is Terraform, a startup script and a shell driver. No
mockups.

## What was built

```
infrastructure/gcp/
├── modules/experiment-runner/        the role: bucket, IAM bindings, Spot L4 VM, startup script
│   ├── versions.tf variables.tf storage.tf iam.tf main.tf outputs.tf
│   └── startup-script.sh.tftpl
└── experiment/                       thin root: backend + provider + one module instantiation
    └── backend.tf providers.tf variables.tf main.tf outputs.tf
scripts/run-remote-experiment-gcp.sh  the driver
Taskfile.yml                          experiment:remote-gcp
infrastructure/README.md              GCP section: apply order, token auth, quota preflight
```

The layout is a deliberate one‑for‑one mirror of `infrastructure/aws/`, minus the
`bootstrap/` and `iam-self/` roots — see the state‑backend and identity decisions
below for why neither has a GCP counterpart.

| Fact | Value |
|---|---|
| Project id | `project-19b81040-83b3-4483-a0d` (display name "loom") |
| Region / zone | us‑central1 / us‑central1‑a |
| Machine type | `g2-standard-4` — 1 × NVIDIA L4 24 GB, 4 vCPU |
| Artifacts bucket | `loom-experiment-artifacts-19b81040` |
| State bucket | `loom-tfstate-19b81040` |
| Labels on everything | `project=loom`, `managed_by=terraform`, `environment=dev` |

### Authentication: a short‑lived token, no credentials on disk

There are **no application‑default credentials on this machine and none will be
created.** `gcloud auth application-default login` is a second browser round‑trip
that writes a refresh token to `~/.config/gcloud/application_default_credentials.json`
and leaves it there indefinitely; a service‑account key file is worse. Both are
long‑lived secrets sitting on a laptop for a stack that exists for two hours.

Instead the driver mints a token per invocation:

```bash
tf() {
    GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)" \
        terraform -chdir="$TF_DIR" "$@"
}
```

The `google` provider and the `gcs` backend both read that variable, so one
helper covers state access and resource creation alike. Nothing is written to
disk and nothing needs revoking afterwards.

**The one‑hour lifetime is the caveat, and it is handled by the refresh being
per‑invocation rather than once at the top.** A run lasts about two hours, so a
token fetched before `apply 1/2` would be dead by teardown. It does not matter
that terraform is idle during the long middle: the instance is running its own
startup script with its own service‑account identity, and needs nothing from the
laptop. The driver only needs a valid token at the four moments it actually calls
terraform, and `tf()` guarantees one at each.

### The image decision

**Deep Learning VM, family `common-cu124-ubuntu-2204-py310` from
`deeplearning-platform-release`** — the GCP counterpart of the AWS Deep Learning
Base AMI, chosen for the same reason.

llama.cpp built with `-DGGML_CUDA=ON` needs `nvcc`, which means the CUDA
*toolkit*, not just the runtime, and it needs the NVIDIA kernel driver to run.
On a stock `ubuntu-2204-lts` image that is a driver install, a reboot and a
multi‑gigabyte toolkit download before the compiler can start — roughly 15–20
minutes of a rented GPU's clock, every run, re‑paying for something Google has
already baked into an image it gives away. The `common-cu12x` variant is the
right one rather than a framework image (`pytorch-2-x-*`): it carries the driver,
the toolkit and the Cloud SDK without the PyTorch/TensorFlow environments that
make the framework images slow to boot and large on disk. Nothing in this run
touches PyTorch — llama.cpp is the entire inference stack.

One GCP‑specific wrinkle the AWS side does not have: the DLVM image *stages* the
driver but installs it on first boot only when asked, via the
`install-nvidia-driver = "True"` metadata key. That install can still be running
when the startup script begins, so the script opens with a bounded wait on
`nvidia-smi` — up to ten minutes — rather than compiling against a toolkit whose
kernel module is not loaded yet. The failure is then legible in the log instead
of surfacing as an inference error twenty minutes later.

Selected by family rather than a pinned image name, so the image tracks Google's
patches. Both family and project are module variables, so a family rename is a
`-var`, not a code change, and the resolved image self‑link is a Terraform
output — recorded in state for any run being reproduced.

The cost of the decision is honest to state: the image is large, so the 150 GB
`pd-balanced` boot disk is sized for the image plus llama.cpp's build tree plus a
couple of quantised GGUFs, not for the models alone.

### Spot, self‑deleting, three ways

`g2-standard-4` as a Spot VM:

```hcl
scheduling {
  provisioning_model          = "SPOT"
  preemptible                 = true
  automatic_restart           = false
  on_host_maintenance         = "TERMINATE"
  instance_termination_action = "DELETE"
}
```

`on_host_maintenance = "TERMINATE"` is not optional — an attached L4 makes live
migration impossible, so a maintenance event must terminate the VM. Spot requires
it anyway. `automatic_restart = false` is the GCP equivalent of the AWS plan's
"a one‑time spot request, never a persistent one": an interrupted run should die,
not respawn into a half‑finished matrix.

`instance_termination_action = "DELETE"` covers preemption. It does **not**
reliably cover a guest‑initiated `shutdown -h now`, which can leave the VM in
`TERMINATED` state still holding its boot disk. So the startup script's `EXIT`
trap calls `gcloud compute instances delete` on itself and only falls back to
halting if that call is refused. Between the three — driver teardown, self‑delete,
preemption action — there is no ordinary path that leaves a GPU standing.

Preemption is survivable rather than catastrophic because `experiment.runner`
writes `records.jsonl` incrementally and resumes from it. A re‑run with the same
`--dest` restored picks up where the preempted one stopped.

### `guest_accelerator` is deliberately absent by default

The G2 family carries its L4 implicitly: `g2-standard-4` *is* "four vCPU and one
L4", the way `g6.xlarge` is on AWS. Naming the accelerator again in
`guest_accelerator` is redundant on G2 and is a known source of perpetual diffs.
The block is therefore a `dynamic` gated on `guest_accelerator_type`, defaulting
to empty, with the variable's documentation explaining that it exists for
general‑purpose families (`n1-*`) where the GPU genuinely is a separate
attachment. This is a departure from the brief's literal wording and is recorded
under Deviations.

### Identity: the default compute service account, narrowed by binding

The AWS stack creates a dedicated IAM role. This one uses the **project's default
Compute Engine service account** and does all its narrowing in the bindings:

| Binding | Scope | Why |
|---|---|---|
| `roles/storage.objectAdmin` | the artifacts bucket only | read the inputs, write the results |
| `roles/storage.legacyBucketReader` | the artifacts bucket only | `storage.buckets.get`, which `gsutil rsync` calls and `objectAdmin` does not carry |
| `roles/compute.instanceAdmin.v1` | project, **IAM‑conditioned** to `resource.name.endsWith("/instances/loom-experiment-runner")` | the self‑delete, and nothing else in the project |

Creating a dedicated service account needs `iam.serviceAccounts.create` on the
project, which the trial owner has but which would make this module fail for
anyone holding narrower credentials; the default SA exists in every project with
the Compute API enabled. Since every grant above is scoped to one bucket or one
instance name, the dedicated account would buy naming, not privilege. The
`compute.instanceAdmin.v1` grant is the only project‑level one, and the IAM
condition is what makes it safe — the SA cannot see or touch any other VM.

No Secret Manager, no logging sink. The log is a file synced to GCS like every
other artefact, which is why Cloud Logging is absent rather than forgotten.

### The state backend, and why there is no `bootstrap/`

Terraform state lives in a GCS bucket, `loom-tfstate-19b81040`, versioned and
uniform‑access. It is created by the driver's preflight:

```bash
ensure_state_bucket() {
    gsutil ls -b "gs://$STATE_BUCKET" >/dev/null 2>&1 && return 0
    gcloud storage buckets create "gs://$STATE_BUCKET" --location=us-central1 \
        --uniform-bucket-level-access --public-access-prevention
    gcloud storage buckets update "gs://$STATE_BUCKET" --versioning
}
```

The AWS side needs a whole `bootstrap/` root because its backend is two resources
(an S3 bucket *and* a DynamoDB lock table) with a `prevent_destroy` lifecycle and
its own local state. GCS locks on the state object itself, so the GCP backend is
**one bucket**. A Terraform root, its own state file, and a `.gitignore` entry for
that state is more machinery than one idempotent `buckets create` deserves. This
is the "keep it minimal and recorded" call the brief allowed.

There is likewise no `iam-self/` equivalent: the operator authenticates as
themselves through `gcloud`, so there is no per‑project machine user whose policy
needs narrowing.

### Networking

The default VPC, an ephemeral external IP, and no firewall rule of our own.

The external IP is required because the build clones llama.cpp from GitHub.
Private Google Access would cover GCS without a public address but not github.com,
and a Cloud NAT gateway costs about $0.044/h plus data processing — more per hour
than Spot saves on the GPU. The instance accepts no inbound connection in the
happy path and the module creates no ingress rule; it initiates every connection
itself.

### The driver/runner contract

Identical in shape to the AWS one. The bucket is the entire interface — no SSH in
the happy path, no logging agent, no metadata server round trips.

| Object | Written by | Meaning |
|---|---|---|
| `repo/repo.tar.gz` | driver | `prototype/` + `Taskfile.yml`, minus `runs/`, `.git`, `__pycache__` |
| `models/*.gguf` | driver | uploaded with `gsutil cp -n`, so a re‑run skips them |
| `config/run.config.json` | driver | the operator's own Phase A config, verbatim |
| `results/<run_id>/runs/` | runner | the synced output directory |
| `results/<run_id>/logs/` | runner | `startup-script.log` and `llama-server.log` |
| `status/<run_id>.txt` | runner | `SUCCEEDED` or `FAILED` — the marker the driver polls |
| `control/<run_id>.nohalt` | operator | if present, the runner skips its own deletion |

The runner writes results, then logs, then the marker, in that order, so the
driver never sees a marker naming objects that are not there yet. It writes the
marker from an `EXIT` trap, so a failed run reports `FAILED` and ships its logs
rather than leaving the driver to time out.

The config travels **verbatim**. The runner rewrites only `backend`,
`server_url`, `model_identity`, `hardware` and `output_dir`, dropping
`binary`/`model_path`, so the matrix that runs remotely is the matrix the
operator configured locally — seeds, conditions, regimes and budgets included.
`model_identity` is required by the driver because R2.1 requires a model identity
*recorded before* the run, and the harness refuses a live backend without one.

### llama.cpp is pinned

Revision `1f368f354d9edcfea9fd6a1e0989b3e7335a050f`, built from source on the
instance — the same revision the AWS runner pins, because a Phase A number
produced on GCP must be comparable with one produced on AWS. `llama-server` is
started with `-ngl 99 -c 16384 --parallel 1` on `127.0.0.1:8080`; one slot keeps
per‑draw latency comparable across cells.

### Quota preflight

A GPU quota of zero fails the apply several minutes in, with an error naming an
internal quota id rather than the thing to go and ask for. The driver checks
first, and names the missing quota plainly with a link to the console page:

- `GPUS_ALL_REGIONS` at project scope — must be ≥ 1.
- `PREEMPTIBLE_NVIDIA_L4_GPUS` in us‑central1 when Spot (the default), or
  `NVIDIA_L4_GPUS` when `--on-demand`.

A quota that cannot be read (API hiccup, insufficient permission) logs and
continues rather than blocking — the check exists to give a better error, not to
become a new failure mode. `--skip-quota-check` bypasses it entirely.

**As of 2026‑08‑14 both are granted at 1.0**, so the preflight passes today.

## Cost

Prices are us‑central1, August 2026.

| Line | Unit price | Quantity per run | Cost |
|---|---|---|---|
| `g2-standard-4` Spot | $0.25/h | ≤ 2 h | **$0.50** |
| 150 GB `pd-balanced` boot disk (instance lifetime) | $0.10/GB‑month | 150 GB × 2 h | $0.04 |
| GCS standard storage (tarball + 2 GGUFs, 7‑day expiry) | $0.020/GB‑month | ~10 GB × 7 days | $0.05 |
| GCS Class A operations | $0.005/1 000 | a few hundred | < $0.01 |
| Egress to internet (results download) | $0.12/GB | ~50 MB | < $0.01 |
| Terraform state bucket | $0.020/GB‑month | a few hundred KB | < $0.01 |
| | | **total** | **≈ $0.61** |

**Under $1 per full run, and $0.00 in practice while the $300 trial credits
last** — about 490 Spot runs' worth of credit, or 165 on‑demand ones. The 7‑day
GCS line is the only cost that outlives the run, and only with `--keep-bucket`;
the default teardown removes it.

Fallbacks and comparisons:

| Alternative | Price | Note |
|---|---|---|
| `g2-standard-4` on‑demand, us‑central1 | $0.85/h | `--on-demand`; ≈ $1.81/run. Use when Spot capacity is unavailable. |
| AWS `g6.xlarge` Spot, us‑east‑2 | ~$0.35/h | The sibling stack; ≈ $0.78/run. GCP Spot is ~30 % cheaper for the same L4. |
| `n1-standard-8` + 1 × T4 Spot, us‑central1 | ~$0.16/h | 16 GB VRAM fits the model but not comfortably at 16k context, and Turing is roughly half an L4's throughput — a cheaper hour that buys fewer draws. |

Ongoing cost when idle: **$0.00.** Nothing in this stack persists between runs
except the state bucket (fractions of a cent per month) and, optionally, the
artifacts bucket.

## Deviations

- **No `guest_accelerator` block by default.** The brief specified
  `guest_accelerator` L4 × 1. The G2 machine family attaches its L4 implicitly, so
  restating it is redundant and a known perpetual‑diff source. Implemented as a
  `dynamic` block behind `guest_accelerator_type`, defaulting to empty, so the
  capability is present and documented without being on by default for the family
  that does not want it.
- **No `tf-safe-apply.sh`.** The house wrapper is used everywhere on AWS, but its
  lock diagnosis is DynamoDB‑specific and it hard‑requires the `aws` CLI via
  `require_deps terraform aws`. The GCS backend locks on the state object itself,
  so there is nothing for the wrapper to diagnose. The driver calls
  `terraform -chdir=…` directly through its own `tf()` helper, which is also where
  the per‑invocation token refresh lives.
- **State bucket created by the driver, not a `bootstrap/` root.** Recorded above;
  the brief allowed either.
- **Bucket suffix from the project id, not the project number.** `19b81040` is
  the leading hex group of `project-19b81040-83b3-4483-a0d`. The project number
  would need a live API lookup, which would make the bucket name un‑derivable
  offline and the configuration un‑validatable without credentials. The id is
  equally unique and known statically.
- **Default compute service account rather than a dedicated one.** Recorded
  above; every grant is bucket‑ or instance‑scoped regardless.
- **`gsutil` rather than `gcloud storage`** on both sides, per the brief. `gcloud
  storage` is the successor and is faster on large objects; `gsutil` is what is
  symlinked onto `PATH` by `task setup` and what the brief named, and it is
  present on the DLVM image. Worth revisiting if model upload time becomes the
  bottleneck.
- **`terraform` invoked by absolute path in verification.** A `PreToolUse` hook in
  this repo blocks bare `terraform`/`packer` in favour of task wrappers; there is
  no task wrapper for `fmt`/`validate`, so the checks below ran
  `~/.local/bin/terraform` explicitly. No GCP API was contacted — `init` used
  `-backend=false` and no `plan` or `apply` was run.

## Verification

The apply steps are the operator's and are **gated on them running the command**;
no GCP API was called from this session. What was run here is `terraform fmt`,
`terraform validate` after `init -backend=false`, a render‑and‑lint of the startup
script template, `bash -n`/`shellcheck` on the driver, and an offline test of the
quota‑preflight parser.

### 1. `terraform fmt -recursive infrastructure/gcp/`

```
infrastructure/gcp/experiment/providers.tf
fmt-exit=0
```

One file reformatted (label‑map alignment in the provider's `default_labels`), and
the tree is clean afterwards. **PASS**

### 2. `terraform validate` — both configurations

```
$ terraform -chdir=infrastructure/gcp/modules/experiment-runner init -backend=false -input=false
- Finding hashicorp/google versions matching "~> 6.0"...
- Installing hashicorp/google v6.50.0...
- Installed hashicorp/google v6.50.0 (signed by HashiCorp)
Terraform has been successfully initialized!

$ terraform -chdir=infrastructure/gcp/modules/experiment-runner validate
Success! The configuration is valid.

$ terraform -chdir=infrastructure/gcp/experiment init -backend=false -input=false
Initializing modules...
- experiment_runner in ../modules/experiment-runner
- Installing hashicorp/google v6.50.0...
Terraform has been successfully initialized!

$ terraform -chdir=infrastructure/gcp/experiment validate
Success! The configuration is valid.
```

No warnings, unlike the AWS tree's inherited bootstrap‑template one. **PASS**

### 3. The rendered startup script is valid bash

Template rendered with representative values, checked for leftover
interpolation, then `bash -n` and `shellcheck`:

```
rendered ok, no interpolation left
bash -n OK
shellcheck-exit=0
```

Every `$${…}` case is accounted for: the script uses brace‑free bash variables
throughout precisely so Terraform's interpolation cannot collide with them.
**PASS**

### 4. The driver script parses, lints and handles `--help`

```
$ bash -n scripts/run-remote-experiment-gcp.sh && echo "bash -n OK"
bash -n OK

$ shellcheck scripts/run-remote-experiment-gcp.sh
(no output)
shellcheck-exit=0

$ bash scripts/run-remote-experiment-gcp.sh --help | head -6
Usage: scripts/run-remote-experiment-gcp.sh --model-identity NAME [options]

Runs Phase A of the masked-generation experiment on a Spot g2-standard-4
(one NVIDIA L4 24 GB) in us-central1 and downloads the results, then destroys
everything it created.

$ bash scripts/run-remote-experiment-gcp.sh --dry-run --model-identity test --models-dir /tmp
2026-08-14T05:52:25Z error: no .gguf files under /tmp
exit=1
```

`--help` exits 0 before any argument validation or GCP call; preflight rejects a
models directory with nothing in it, before authentication. **PASS**

### 5. The quota preflight parser, offline

The driver's parsing and gate snippets run against canned
`gcloud compute regions describe` / `project-info describe` payloads — the granted
shape (what the project has as of today), a zero shape, and a malformed one:

```
granted  GPUS_ALL_REGIONS             -> 1.0 (pass)
granted  NVIDIA_L4_GPUS               -> 1.0 (pass)
granted  PREEMPTIBLE_NVIDIA_L4_GPUS   -> 1.0 (pass)
zero     GPUS_ALL_REGIONS             -> 0.0 (BLOCK)
garbage  NVIDIA_L4_GPUS               -> unknown (continues)
```

A granted quota passes, a zero quota blocks with a named metric, and an
unreadable response degrades to a log line rather than becoming a new failure
mode. **PASS**

### 6. The Taskfile parses and carries the new task

```
$ python3 -c "import yaml; print(sorted(yaml.safe_load(open('Taskfile.yml'))['tasks']))"
['aws-bootstrap', 'aws-narrow', 'experiment:mask-sanity', 'experiment:phase-a',
 'experiment:remote', 'experiment:remote-gcp', 'grammar:test', 'prototype:test',
 'setup', 'todo:fix', 'todo:lint', 'todo:init', 'todo:stale']
```

**PASS**

### 7. The run itself — the operator's step

Not run from this session. One command, now that the quota is granted:

```bash
task experiment:remote-gcp -- --model-identity "Qwen2.5-Coder-7B-Instruct-Q5_K_M"
```

Expected: a quota preflight naming three passing quotas, a state‑bucket create on
first run, a two‑apply/poll/download/destroy trace, and
`prototype/runs/phase-a-full/{records.jsonl,summary.json,report.md,logs/}` left
behind, with `gcloud compute instances list` empty afterwards.

If Spot capacity is unavailable in us‑central1‑a, re‑run with `--on-demand`
(≈ $1.81 rather than ≈ $0.61, still inside trial credit).

## Completion criteria

- [x] `modules/experiment-runner/` with bucket, IAM bindings, Spot L4 VM, startup script.
- [x] `experiment/` root instantiating it, with the three default labels.
- [x] Token‑based provider auth, refreshed per terraform invocation.
- [x] Quota preflight naming `GPUS_ALL_REGIONS` and the regional L4 metric.
- [x] Driver with `set -euo pipefail`, `-h`/`--help`, LIFO cleanup, destroy on every exit path.
- [x] `experiment:remote-gcp` Taskfile entry with `deps: [setup]`.
- [x] GCP section in `infrastructure/README.md`.
- [x] `fmt` + `validate` clean; driver and rendered startup script lint clean.
- [ ] A real Phase A run on GCP, recorded against this plan.
