# Loom infrastructure

Everything Loom runs on AWS is here. There is exactly one workload — the
masked‑generation experiment's Phase A matrix, run on a rented GPU for about two
hours and then destroyed — so the stack is small on purpose.

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

## Layout

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

## Apply order

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

## The one command

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

## Conventions this stack keeps

- Every resource is named `loom-*`; the scoped IAM policy's ARN patterns depend on it.
- Every provider block carries `default_tags` with `Project`, `ManagedBy` and `Environment`.
- `prevent_destroy = true` on the state bucket and the lock table.
- No secrets anywhere in this stack, so nothing in SSM. The runner's only
  credential is its instance role, and that role can reach exactly one bucket.
- Always `~/python-tui-lib/scripts/tf-safe-apply.sh <dir> [op]`, never bare
  `terraform apply` — it handles lock diagnosis, stale digest repair and auto‑init.

## Widening permissions

Edit `iam-self/policy.tf`, apply it, then carry on. Never the console. The EC2
statements there are the interesting ones: creation calls (`RunInstances`,
`CreateSecurityGroup`, `CreateLaunchTemplate`, `RequestSpotInstances`) name
resources that do not exist yet or that AWS owns, so they cannot be ARN‑scoped
and are allowed on `*`; everything mutating afterwards is `ec2:*` gated on
`aws:ResourceTag/Project = loom`, and tag‑on‑create is gated on
`aws:RequestTag/Project = loom`, which `default_tags` always supplies.

## Emergency escape hatch

If `loom-terraform-scoped` is ever narrowed into a corner and the user can no
longer apply its own fix, the **root account** can re‑attach `AdministratorAccess`
to the `loom-terraform` user from the console:
[https://us-east-1.console.aws.amazon.com/iam/home#/users/details/loom-terraform](https://us-east-1.console.aws.amazon.com/iam/home#/users/details/loom-terraform)
→ Permissions → Add permissions → Attach policies directly → `AdministratorAccess`.
Widen `policy.tf`, apply, then detach again. This is the only reason to open the
console after setup.
