# Loom infrastructure

Everything Loom runs on rented hardware is here. There is exactly one workload —
the masked‑generation experiment's Phase A matrix, run on a rented GPU for about
two hours and then destroyed — so the stack is small on purpose.

It exists twice, once per cloud, because GPU allocation is the scarce thing and
whichever cloud is ready first should be usable without a rewrite:
[`aws/`](#aws) and [`gcp/`](#gcp). The two are deliberate mirrors — same artifact
flow, same two‑stage apply, same driver interface, same pinned llama.cpp — so a
Phase A number from one is comparable with a number from the other.

## AWS

| Setting | Value |
|---|---|
| Project slug | `loom` |
| AWS account | 353144603271 |
| AWS profile | `loom-terraform` |
| Region | us‑east‑2 |
| Environment tag | `dev` |

us‑east‑2 is chosen on price: `g6.xlarge` spot runs about **$0.33–0.35/h** there
against about **$0.79/h** in us‑east‑1. Nothing in this stack is latency‑sensitive
— a driver script on a laptop talks to S3 and nothing else — so the cheapest
region with L4 capacity wins outright.

### Layout

```
infrastructure/aws/
├── bootstrap/                  Terraform state backend (S3 + DynamoDB), local state
├── iam-self/                   The loom-terraform user's own scoped policy
├── modules/
│   └── experiment-runner/      The GPU runner: bucket, instance role, spot instance, user-data
└── experiment/                 Thin root: backend + provider + one module instantiation
```

`modules/experiment-runner/` is where every decision lives; `experiment/` exists
only to pin the backend, the provider and the three required tags. One module per
server role, per the house convention — this stack has exactly one role.

### Apply order

Once — and only once — per machine:

```bash
task aws-bootstrap                     # Phase A prompt + Phase B state backend
```

Then the self‑narrowing IAM, per the `iam-bootstrap` skill:

```bash
# Phase C — attach the scoped policy alongside Admin/ReadOnly
~/python-tui-lib/scripts/tf-safe-apply.sh infrastructure/aws/iam-self init
~/python-tui-lib/scripts/tf-safe-apply.sh infrastructure/aws/iam-self apply -auto-approve

# Phase D — verify the scoped policy alone is sufficient, then detach the broad ones
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::353144603271:user/loom-terraform \
  --action-names s3:CreateBucket s3:PutObject dynamodb:CreateTable iam:CreateRole \
                 iam:CreateInstanceProfile iam:PassRole ec2:RunInstances \
                 ec2:TerminateInstances ec2:CreateSecurityGroup sts:GetCallerIdentity \
  --resource-arns \
    "arn:aws:s3:::loom-experiment-artifacts" \
    "arn:aws:s3:::loom-experiment-artifacts/repo/repo.tar.gz" \
    "arn:aws:dynamodb:us-east-2:353144603271:table/loom-terraform-locks" \
    "arn:aws:iam::353144603271:role/loom-experiment-runner" \
    "*"

cd infrastructure/aws/iam-self
terraform import aws_iam_user_policy_attachment.admin \
  'loom-terraform/arn:aws:iam::aws:policy/AdministratorAccess'
terraform import aws_iam_user_policy_attachment.readonly \
  'loom-terraform/arn:aws:iam::aws:policy/ReadOnlyAccess'
# No resource blocks exist for those two, so the next apply detaches them.
~/python-tui-lib/scripts/tf-safe-apply.sh infrastructure/aws/iam-self apply -auto-approve

AWS_PROFILE=loom-terraform aws iam list-attached-user-policies --user-name loom-terraform
# Must show ONLY: loom-terraform-scoped
```

The experiment root is never applied by hand — the driver script owns its whole
lifecycle, including the destroy.

### The one command

```bash
task experiment:remote -- --model-identity "Qwen2.5-Coder-7B-Instruct-Q5_K_M"
```

That uploads the repo and the GGUFs from `~/loom-tools/models`, applies
`infrastructure/aws/experiment`, waits for the runner's status marker, downloads
`runs/` into `prototype/runs/phase-a-full/`, and destroys the stack — on success,
on failure and on Ctrl‑C alike. `scripts/run-remote-experiment.sh --help` lists
the knobs. Belt and braces: the instance also self‑terminates when its user‑data
script finishes, so a driver that is killed outright still does not leave a GPU
running.

### Conventions this stack keeps

- Every resource is named `loom-*`; the scoped IAM policy's ARN patterns depend on it.
- Every provider block carries `default_tags` with `Project`, `ManagedBy` and `Environment`.
- `prevent_destroy = true` on the state bucket and the lock table.
- No secrets anywhere in this stack, so nothing in SSM. The runner's only
  credential is its instance role, and that role can reach exactly one bucket.
- Always `~/python-tui-lib/scripts/tf-safe-apply.sh <dir> [op]`, never bare
  `terraform apply` — it handles lock diagnosis, stale digest repair and auto‑init.

### Widening permissions

Edit `iam-self/policy.tf`, apply it, then carry on. Never the console. The EC2
statements there are the interesting ones: creation calls (`RunInstances`,
`CreateSecurityGroup`, `CreateLaunchTemplate`, `RequestSpotInstances`) name
resources that do not exist yet or that AWS owns, so they cannot be ARN‑scoped
and are allowed on `*`; everything mutating afterwards is `ec2:*` gated on
`aws:ResourceTag/Project = loom`, and tag‑on‑create is gated on
`aws:RequestTag/Project = loom`, which `default_tags` always supplies.

### Emergency escape hatch

If `loom-terraform-scoped` is ever narrowed into a corner and the user can no
longer apply its own fix, the **root account** can re‑attach `AdministratorAccess`
to the `loom-terraform` user from the console:
[https://us-east-1.console.aws.amazon.com/iam/home#/users/details/loom-terraform](https://us-east-1.console.aws.amazon.com/iam/home#/users/details/loom-terraform)
→ Permissions → Add permissions → Attach policies directly → `AdministratorAccess`.
Widen `policy.tf`, apply, then detach again. This is the only reason to open the
console after setup.

## GCP

The sibling stack. Same workload, same artifact flow, cheaper GPU. Designed in
[docs/plans/2026-08-14-gcp-experiment-infra.md](../docs/plans/2026-08-14-gcp-experiment-infra.md).

| Setting | Value |
|---|---|
| Project slug | `loom` |
| GCP project id | `project-19b81040-83b3-4483-a0d` (display name "loom") |
| Region / zone | us‑central1 / us‑central1‑a |
| Machine type | `g2-standard-4` — 1 × NVIDIA L4 24 GB, 4 vCPU |
| Artifacts bucket | `loom-experiment-artifacts-19b81040` |
| State bucket | `loom-tfstate-19b81040` |
| Labels | `project=loom`, `managed_by=terraform`, `environment=dev` |

us‑central1 is chosen on price and capacity: `g2-standard-4` Spot runs about
**$0.25/h** there, against about **$0.35/h** for the equivalent AWS `g6.xlarge`
Spot in us‑east‑2. Nothing here is latency‑sensitive — a driver script on a laptop
talks to GCS and nothing else — so the cheapest region with L4 capacity wins.

### Layout

```
infrastructure/gcp/
├── modules/
│   └── experiment-runner/      The GPU runner: bucket, IAM bindings, Spot L4 VM, startup script
└── experiment/                 Thin root: backend + provider + one module instantiation
```

There is no `bootstrap/` — GCS locks on the state object itself, so the whole
backend is one bucket, created idempotently by the driver's preflight rather than
by a Terraform root of its own. There is no `iam-self/` either: the operator
authenticates as themselves, so there is no machine user whose policy needs
narrowing.

### Authentication — read this before applying

**There are no application‑default credentials on this machine, and none should be
created.** The driver mints a short‑lived token per terraform invocation instead:

```bash
GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)" terraform -chdir=… …
```

Both the `google` provider and the `gcs` backend read that variable, so one
export covers state and resources alike, and nothing long‑lived is written to
disk.

**The token lives one hour, which is shorter than a run.** That is why the driver
refreshes it before *every* terraform call rather than once at the top — in
particular before the teardown, which happens two hours after the first apply.
The long middle needs no local credential at all: the instance is running its own
startup script under its own service account, and needs nothing from the laptop.

Applying by hand carries the same requirement:

```bash
export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"   # re-run if it expires
terraform -chdir=infrastructure/gcp/experiment init
```

### Quota preflight

GPU quota is the thing that blocks a first run, and a zero quota fails the apply
several minutes in with an error naming an internal id rather than the thing to
ask for. The driver therefore checks up front and names the missing quota:

| Metric | Scope | Needed |
|---|---|---|
| `GPUS_ALL_REGIONS` | project | ≥ 1 |
| `PREEMPTIBLE_NVIDIA_L4_GPUS` | us‑central1 | ≥ 1 (Spot, the default) |
| `NVIDIA_L4_GPUS` | us‑central1 | ≥ 1 (only with `--on-demand`) |

All are granted at 1.0 as of 2026‑08‑14. Request more at
[https://console.cloud.google.com/iam-admin/quotas?project=project-19b81040-83b3-4483-a0d](https://console.cloud.google.com/iam-admin/quotas?project=project-19b81040-83b3-4483-a0d).
`--skip-quota-check` bypasses the check; an unreadable quota logs and continues
rather than blocking.

### Apply order

Nothing to do once per machine beyond `gcloud auth login` and `task setup`. The
state bucket is created by the driver on its first run, and the experiment root
is never applied by hand — the driver owns its whole lifecycle, including the
destroy.

### The one command

```bash
task experiment:remote-gcp -- --model-identity "Qwen2.5-Coder-7B-Instruct-Q5_K_M"
```

That checks quota, creates the state bucket if absent, applies
`infrastructure/gcp/experiment` without the GPU, uploads the repo and the GGUFs
from `~/loom-tools/models`, applies again *with* the GPU, waits for the runner's
status marker in GCS, downloads `runs/` into `prototype/runs/phase-a-full/`, and
destroys the stack — on success, on failure and on Ctrl‑C alike.
`scripts/run-remote-experiment-gcp.sh --help` lists the knobs. Add `--on-demand`
if Spot capacity is unavailable (≈ $1.81 rather than ≈ $0.61 per run).

Belt and braces, three deep: the driver destroys on every exit path, the startup
script deletes the instance when it finishes, and the Spot VM's
`instance_termination_action = "DELETE"` removes it on preemption.

### Conventions this stack keeps

- Every resource is named `loom-*`; GCS names carry the `-19b81040` suffix because
  the bucket namespace is global.
- Every provider block carries `default_labels` with `project`, `managed_by` and
  `environment` — GCP's labels are lowercase, unlike AWS's tags.
- No secrets anywhere in this stack. The runner's only credential is its service
  account, and that account can reach exactly one bucket plus one named instance.
- No `tf-safe-apply.sh` here: its lock diagnosis is DynamoDB‑specific and it
  requires the `aws` CLI. Plain `terraform -chdir=…` through the driver's `tf()`
  helper, which is where the token refresh lives.
