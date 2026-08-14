# Plan — GPU infrastructure for the Phase A experiment run

**Date:** 2026‑08‑13
**Status:** Implemented; `terraform fmt` + `terraform validate` PASS, apply gated on operator credentials
**Implements:** the live‑run half of [Masked‑generation experiment, Phase A substrate and harness](2026-08-13-experiment-phase-a.md) — the T5 model/hardware item that plan's "What the one‑command run still needs" section names
**Decides:** the AMI, the instance market, the region, and the shape of the driver/runner contract

## Objective

Phase A's harness is finished and passes on the stub backend. What it has never
had is a GPU. This plan builds the rented‑GPU substrate that runs the real Phase A
matrix end to end — one command from the operator's laptop, results back in
`prototype/runs/phase-a-full/`, and nothing left running afterwards.

The constraint that shapes every decision below: **a run must cost under a
dollar, and must not be able to cost more than that by accident.** A GPU
instance left running overnight because a driver script died is the failure mode
worth engineering against, and it is engineered against twice — the driver
destroys on every exit path, and the instance terminates itself independently.

No visible surface: this is Terraform, a user‑data script and a shell driver. No
mockups.

## What was built

```
infrastructure/aws/
├── bootstrap/main.tf                       state backend (S3 + DynamoDB), local state
├── iam-self/{backend,providers,data,policy}.tf   loom-terraform's own scoped policy
├── modules/experiment-runner/              the role: bucket, instance role, spot GPU, user-data
│   ├── versions.tf variables.tf s3.tf iam.tf main.tf outputs.tf
│   └── user-data.sh.tftpl
└── experiment/{backend,providers,variables,main,outputs}.tf   thin root
scripts/run-remote-experiment.sh            the driver
infrastructure/README.md                    layout, apply order, escape hatch
```

`bootstrap/` is the shared template from `~/python-tui-lib/templates/flutter-cloud/`
with `__PROJECT__` → `loom`, `state_region` → us‑east‑2, `aws_profile` →
`loom-terraform`. `iam-self/` is the `iam-bootstrap` skill's four files with the
same substitutions, plus the EC2 statements this stack needs.

### The AMI decision

**AWS Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)**, not vanilla
Ubuntu 24.04.

llama.cpp built with `-DGGML_CUDA=ON` needs `nvcc`, which means the CUDA
*toolkit*, not just the runtime — and it needs the NVIDIA kernel driver to run.
On vanilla Ubuntu 24.04 that is a driver install, a reboot, and a multi‑gigabyte
toolkit download before the compiler can start: roughly 15–20 minutes of a rented
GPU's clock, every run, re‑paying for something AWS has already baked into an
image it gives away. The Base variant (not the full Deep Learning AMI) is the
right one — it carries drivers, CUDA and the AWS CLI without the PyTorch/TensorFlow
Conda environments that make the full image slow to boot and large on disk.

Selected by data source rather than a pinned id, so the image tracks AWS's
patches:

```hcl
data "aws_ami" "runner" {
  most_recent = true
  owners      = ["amazon"]
  filter { name = "name"  values = ["Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)*"] }
}
```

Both the filter and the owner are module variables, so if AWS renames the family
the fix is a `-var`, not a code change. The AMI id actually used is a Terraform
output and is therefore recorded in state for any run being reproduced.

The cost of the decision is honest to state: the image is large, so the 100 GB
gp3 root volume is sized for the AMI plus llama.cpp's build tree plus a couple of
quantised GGUFs, not for the models alone.

### Spot, one‑time, self‑terminating

`g6.xlarge` — one L4 24 GB — as a **one‑time** spot request with
`instance_interruption_behavior = "terminate"`, plus
`instance_initiated_shutdown_behavior = "terminate"` on the instance itself. The
user‑data script ends in `shutdown -h now`, and those two settings together turn
that into a termination rather than a `stopped` instance quietly accruing EBS
charges. A persistent spot request is exactly wrong here: an interrupted run
should die, not respawn into a half‑finished matrix.

Interruption is survivable rather than catastrophic because
`experiment.runner` writes `records.jsonl` incrementally and resumes from it. A
re‑run with the same `--dest` restored picks up where the killed one stopped.

### The two‑phase apply, and why

The driver has to upload the repo tarball and the GGUFs *before* the instance
boots, and the bucket that receives them is part of the same stack. Rather than
split the bucket into its own root, the module gates the instance on
`launch_runner`:

1. `apply -var launch_runner=false` — bucket, instance role, security group.
2. upload tarball, run config, models.
3. `apply -var launch_runner=true` — the GPU.

Teardown reuses the same switch: `--keep-bucket` applies step 1 again (dropping
the instance, keeping the models cached for the next run), and the default path
destroys everything. Either way the only meaningful cost — the GPU — goes away
first.

### The driver/runner contract

The bucket is the entire interface. There is no SSH in the happy path, no
CloudWatch, no SSM.

| Key | Written by | Meaning |
|---|---|---|
| `repo/repo.tar.gz` | driver | `prototype/` + `Taskfile.yml`, minus `runs/`, `.git`, `__pycache__` |
| `models/*.gguf` | driver | uploaded with `--size-only`, so a re‑run skips them |
| `config/run.config.json` | driver | the operator's own Phase A config, verbatim |
| `results/<run_id>/runs/` | runner | the synced output directory |
| `results/<run_id>/logs/` | runner | `user-data.log` and `llama-server.log` |
| `status/<run_id>.txt` | runner | `SUCCEEDED` or `FAILED` — the marker the driver polls |
| `control/<run_id>.nohalt` | operator | if present, the runner skips its own shutdown |

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
instance. Pinned rather than tracked because the GBNF grammar's acceptance and
the server's token accounting are both properties of a specific llama.cpp, and
Phase A's numbers are only reproducible against a named one. `llama-server` is
started with `-ngl 99 -c 16384 --parallel 1` on `127.0.0.1:8080`; one slot keeps
per‑draw latency comparable across cells.

### IAM

Two principals, both minimal.

The **runner instance role** (`loom-experiment-runner`) can `ListBucket` on
`loom-experiment-artifacts` and get/put/delete objects inside it. Nothing else —
no other bucket, no SSM, no CloudWatch. The log is a file synced to S3 like every
other artefact, which is why CloudWatch is absent rather than forgotten.

The **`loom-terraform` user** gains EC2 in `iam-self/policy.tf`, in three
statements, because EC2 does not scope cleanly by ARN:

- `EC2CreateAndLaunch` — `RunInstances`, `RequestSpotInstances`,
  `CreateSecurityGroup`, `CreateLaunchTemplate*`, `CreateVolume`,
  `CreateNetworkInterface`, key‑pair creation, on `*`. These name resources that
  do not exist yet, or AWS‑owned ones (the DLAMI and its snapshots), so there is
  no ARN to scope against.
- `EC2TagOnCreate` — `ec2:CreateTags` gated on `aws:RequestTag/Project = loom`,
  which every provider in this repo supplies through `default_tags`.
- `EC2MutateProjectTagged` — `ec2:*` on `*` gated on
  `aws:ResourceTag/Project = loom`. This is what actually protects the account:
  `TerminateInstances`, `DeleteSecurityGroup`, `DeleteTags` and friends can only
  touch resources this project created. `Describe*` is already covered by
  `ReadAll`.

Plus `iam:PassRole` scoped to `role/loom-*` **and** conditioned on
`iam:PassedToService = ec2.amazonaws.com`, and `instance-profile/loom-*` added to
the existing `IAMProjectScope` ARN list.

## Cost

Prices are us‑east‑2, on‑demand and recent spot, August 2026.

| Line | Unit price | Quantity per run | Cost |
|---|---|---|---|
| `g6.xlarge` spot | $0.35/h | ≤ 2 h | **$0.70** |
| 100 GB gp3 root (instance lifetime) | $0.08/GB‑month | 100 GB × 2 h | $0.02 |
| S3 PUT/GET requests | $0.005/1 000 PUT | a few hundred | < $0.01 |
| S3 storage (tarball + 2 GGUFs, 7‑day expiry) | $0.023/GB‑month | ~10 GB × 7 days | $0.05 |
| Data transfer out (results download) | $0.09/GB | ~50 MB | < $0.01 |
| DynamoDB state lock | on‑demand, per request | tens of requests | < $0.01 |
| | | **total** | **≈ $0.78** |

**Under $1 per full run.** The 7‑day S3 line is the only cost that outlives the
run, and only with `--keep-bucket`; the default teardown removes it.

Fallbacks and comparisons:

| Alternative | Price | Note |
|---|---|---|
| `g6.xlarge` on‑demand, us‑east‑2 | $0.8048/h | `--on-demand`; ~$1.65/run. Use when spot capacity is unavailable. |
| `g6.xlarge` spot, us‑east‑1 | ~$0.79/h | Why the region is us‑east‑2 at all. |
| `g5.xlarge` spot, us‑east‑2 | ~$0.40/h | A10G 24 GB. Not cheaper, older silicon. |

Ongoing cost when idle: **$0.00.** Nothing in this stack persists between runs
except Terraform state (cents per month) and, optionally, the artifacts bucket.

## Deviations

- **State bucket name.** The `iam-bootstrap` skill's `backend.tf` says
  `<project>-terraform-state`, but the shared bootstrap template it tells you to
  copy creates `<project>-terraform-state-<account_id>`. The backend must name
  the bucket that actually exists, so both `backend.tf` files and the
  `aws-bootstrap` task use `loom-terraform-state-353144603271`.
- **`use_lockfile` and DynamoDB together.** The skill's backend block uses
  `use_lockfile = true`; the bootstrap template still creates the DynamoDB lock
  table, and `tf-safe-apply.sh` diagnoses stale DynamoDB digests. Both are kept —
  the table costs nothing unused and the wrapper expects it.
- **The bootstrap template emits a provider warning** (`aws_s3_bucket_lifecycle_configuration`
  with no `filter` or `prefix`). It is a warning, not an error, under the pinned
  `~> 5.0` provider. Left as the template has it rather than diverging our copy
  from the shared source; the fix belongs upstream in `python-tui-lib`.
- **The module owns the S3 bucket**, not the root, so the whole role — storage,
  identity, compute — is one instantiation. The brief allowed either.
- **Terraform is not installed on this machine.** `fmt` and `validate` were run
  from a Terraform 1.9.8 binary fetched into the session scratchpad. No AWS call
  was made; `validate` ran after `init -backend=false`.

## Verification

The apply steps below are the operator's, and are **gated on the
`loom-terraform` credentials, which do not exist yet**. What was run here is
`terraform fmt` and `terraform validate` (with `-backend=false`, so no AWS
contact), plus a syntax check of the rendered user‑data and the driver script.

### 1. `terraform fmt -recursive infrastructure/`

```
infrastructure/aws/bootstrap/main.tf
fmt-exit=0
```

Only the copied bootstrap template needed reformatting. **PASS**

### 2. `terraform validate` — every configuration

```
=== infrastructure/aws/bootstrap ===
Warning: Invalid Attribute Combination

  with aws_s3_bucket_lifecycle_configuration.terraform_state,
  on main.tf line 96, in resource "aws_s3_bucket_lifecycle_configuration" "terraform_state":
  96: resource "aws_s3_bucket_lifecycle_configuration" "terraform_state" {

No attribute specified when one (and only one) of
[rule[0].filter,rule[0].prefix] is required

This will be an error in a future version of the provider
Success! The configuration is valid, but there were some validation warnings
as shown above.

=== infrastructure/aws/iam-self ===
Success! The configuration is valid.

=== infrastructure/aws/modules/experiment-runner ===
Success! The configuration is valid.

=== infrastructure/aws/experiment ===
Success! The configuration is valid.
```

**PASS** (the one warning is the inherited template's, recorded under Deviations).

### 3. The rendered user‑data is valid bash

Template rendered with representative values, then `bash -n`:

```
CompletedProcess(args=['bash', '-n', '.../rendered-user-data.sh'], returncode=0, stdout='', stderr='')
```

**PASS**

### 4. The driver script parses, lints and handles `--help`

```
$ bash -n scripts/run-remote-experiment.sh && echo "bash -n OK"
bash -n OK

$ shellcheck scripts/run-remote-experiment.sh
(no output)

$ ./scripts/run-remote-experiment.sh --help | head -4
Usage: scripts/run-remote-experiment.sh --model-identity NAME [options]

Runs Phase A of the masked-generation experiment on a spot g6.xlarge in
us-east-2 and downloads the results, then destroys everything it created.

$ ./scripts/run-remote-experiment.sh --dry-run --model-identity test --models-dir /tmp
2026-08-14T03:33:10Z error: no .gguf files under /tmp
```

`--help` exits 0 before any argument parsing or AWS call; preflight rejects a
models directory with nothing in it. **PASS**

### 5. The Taskfile parses and carries both new tasks

```
$ python3 -c "import yaml; print(sorted(yaml.safe_load(open('Taskfile.yml'))['tasks']))"
['aws-bootstrap', 'experiment:mask-sanity', 'experiment:phase-a', 'experiment:remote', 'grammar:test', 'prototype:test', 'todo:fix', 'todo:init', 'todo:lint', 'todo:stale']
```

**PASS**

### 6–9. Operator steps, gated on credentials

Not run — no `loom-terraform` credentials exist. In order, once they do:

```bash
# 6. state backend
task aws-bootstrap

# 7. scoped IAM alongside the broad policies
~/python-tui-lib/scripts/tf-safe-apply.sh infrastructure/aws/iam-self init
~/python-tui-lib/scripts/tf-safe-apply.sh infrastructure/aws/iam-self apply -auto-approve

# 8. verify the scoped policy alone suffices, then detach Admin/ReadOnly
#    (full simulate-principal-policy command in infrastructure/README.md)
AWS_PROFILE=loom-terraform aws iam list-attached-user-policies --user-name loom-terraform
#    must show ONLY: loom-terraform-scoped

# 9. the run
task experiment:remote -- --model-identity "<the GGUF's recorded identity>"
```

Step 9 is expected to print a two‑apply/poll/download/destroy trace and leave
`prototype/runs/phase-a-full/{records.jsonl,summary.json,report.md,logs/}` behind,
with no EC2 instance in `describe-instances` afterwards.

## Completion criteria

- [x] `bootstrap/` and `iam-self/` in place, substituted for loom/us‑east‑2/dev.
- [x] EC2 + instance‑profile + PassRole statements in the scoped policy.
- [x] `modules/experiment-runner/` with bucket, role, spot instance, user‑data.
- [x] `experiment/` root instantiating it, with the three default tags.
- [x] Driver script with `set -euo pipefail`, `-h`/`--help`, LIFO cleanup, destroy on every exit path.
- [x] `aws-bootstrap` and `experiment:remote` Taskfile entries.
- [x] `infrastructure/README.md` with layout, apply order and escape hatch.
- [x] `fmt` + `validate` clean.
- [ ] A real Phase A run, recorded against this plan — gated on the operator's credentials.
