# Plan — GCP spend, CLI-queryable via BigQuery billing export

Dispatched as TODO item `[gcp-billing-export]` (T2). This doc doubles as the
plan and, since there's no separate infra/setup doc in `docs/` to append to
(the existing `docs/plans/2026-08-14-gcp-experiment-infra.md` and
`docs/plans/2026-08-13-gpu-experiment-infra.md` are how prior GCP infra is
documented too), the reference for how to use this.

## Objective

Make GCP spend on `project-19b81040-83b3-4483-a0d` queryable from the shell
(`task gcp:spend`) instead of only via the console, by wiring Cloud Billing's
BigQuery export end to end: the Terraform-able side (target dataset, API
enablement) plus a query script, with everything reproducible from the repo
except the one step Google exposes no API for.

## Mockups

No visible surface beyond plain terminal text (`bq query` table output via
`task gcp:spend`) — no UI, page, or TUI pane involved. Dropping the mockup
section per the plan-mockups rule.

## What was built

**`infrastructure/gcp/billing-export/`** — a new Terraform root, same
conventions as `../experiment-diversity` (own state prefix in the shared
`loom-tfstate-19b81040` bucket, token-based provider auth, no credentials on
disk). It creates:

- `google_project_service.bigquery` — enables `bigquery.googleapis.com`
  (`disable_on_destroy = false`, so destroying this root never reaches across
  and disables an API other roots or manual `bq` use depend on).
- `google_bigquery_dataset.billing_export` (id `billing_export`, location
  `US`) — the export target. No `default_table_expiration_ms`: billing
  history should persist, unlike the scratch datasets a TTL usually guards.

No IAM resource: when the console's Billing export page is pointed at this
dataset, Google grants the Cloud Billing service agent BigQuery Data Editor
on it automatically as part of that flow (see `main.tf` for the full
reasoning — there's no principal to grant to in advance since that agent's
identity is only realized when the export is enabled).

**`scripts/gcp-spend.sh`** — queries the export table via
`bq query --use_legacy_sql=false`. Default: current calendar month, total +
per-service breakdown, net of credits. `--days N`, `--month YYYY-MM`,
`--by-sku`, `--project ID`. The table name
(`gcp_billing_export_v1_<billing_account_id_with_underscores>`) is resolved
at runtime from `gcloud billing projects describe`, never hardcoded. When the
table doesn't exist yet, the script fails loudly with both possible causes
(manual step not done yet / done but data hasn't landed) and the exact `bq
show` command to re-check.

**Taskfile**: `infra:billing-export` (apply this root) and `gcp:spend`
(passthrough to the script, e.g. `task gcp:spend -- --days 7`). Also added
`billing-export` to the `infra:validate` root list, and — since `bq` turned
out not to be symlinked into `~/.local/bin` by `task setup` even though
`gcloud`/`gsutil` are — added that symlink to `task setup` (idempotent,
outside the install/already-installed branch so a re-run picks it up either
way).

## The one manual step

Cloud Billing export configuration lives on the *billing account*, not the
project, and Google exposes no API or Terraform resource for turning it on —
only the console page. This is the one thing this change cannot automate:

1. Open [console.cloud.google.com/billing/export](https://console.cloud.google.com/billing/export).
2. Under **BigQuery export**, enable **Standard usage cost** (ideally also
   **Detailed usage cost**).
3. Point it at the `billing_export` dataset in `project-19b81040-83b3-4483-a0d`
   (created by `task infra:billing-export`, already applied).

First rows can take up to 24 h to land after enabling. Until then —and
before step 1–3 are done at all— `task gcp:spend` fails with a clear
explanation rather than a raw BigQuery "table not found" error.

## Cost

Dataset storage at billing-export volumes (a handful of rows/day for one
project) is effectively $0, well under BigQuery's free tier
(10 GiB storage / 1 TiB queries per month). `bq query` runs from
`gcp-spend.sh` scan at most a few MB — pennies at most, practically $0 given
the free tier. `google_project_service.bigquery` has no cost of its own.

## Usage

```
task gcp:spend                        # current month, total + by-service
task gcp:spend -- --days 7            # last 7 days
task gcp:spend -- --month 2026-07     # a specific month
task gcp:spend -- --days 30 --by-sku  # breakdown by SKU instead of service
task gcp:spend -- --help
```

## Verification

### 1. `terraform init && terraform validate`

```
$ export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"
$ terraform -chdir=infrastructure/gcp/billing-export init -input=false
...
Terraform has been successfully initialized!

$ terraform -chdir=infrastructure/gcp/billing-export validate
Success! The configuration is valid.
```

PASS.

### 2. `terraform plan`

```
Terraform will perform the following actions:

  # google_bigquery_dataset.billing_export will be created
  + resource "google_bigquery_dataset" "billing_export" {
      + dataset_id    = "billing_export"
      + location      = "US"
      + project       = "project-19b81040-83b3-4483-a0d"
      ...
    }

  # google_project_service.bigquery will be created
  + resource "google_project_service" "bigquery" {
      + disable_on_destroy = false
      + project            = "project-19b81040-83b3-4483-a0d"
      + service            = "bigquery.googleapis.com"
    }

Plan: 2 to add, 0 to change, 0 to destroy.
```

Plan showed only the dataset + API enablement, nothing else — matches the
pre-authorized apply scope, so this root was applied (see below), not left
pending.

PASS.

### 3. `terraform apply` (pre-authorized: plan was dataset + service only)

```
google_project_service.bigquery: Creating...
google_project_service.bigquery: Creation complete after 3s [id=project-19b81040-83b3-4483-a0d/bigquery.googleapis.com]
google_bigquery_dataset.billing_export: Creating...
google_bigquery_dataset.billing_export: Creation complete after 1s [id=projects/project-19b81040-83b3-4483-a0d/datasets/billing_export]

Apply complete! Resources: 2 added, 0 changed, 0 destroyed.

Outputs:

dataset_id = "billing_export"
dataset_location = "US"
self_link = "https://bigquery.googleapis.com/bigquery/v2/projects/project-19b81040-83b3-4483-a0d/datasets/billing_export"
```

PASS. Dataset exists; export is not yet turned on (that's the manual step
above).

### 4. `bash -n` + `shellcheck` on `scripts/gcp-spend.sh`

```
$ bash -n scripts/gcp-spend.sh && echo "syntax OK"
syntax OK
$ shellcheck scripts/gcp-spend.sh; echo "shellcheck exit: $?"
shellcheck exit: 0
```

PASS.

### 5. `scripts/gcp-spend.sh --help`

```
$ scripts/gcp-spend.sh --help; echo "exit: $?"
Usage: scripts/gcp-spend.sh [options]
...
exit: 0
```

PASS.

### 6. Not-yet-exported error path (real run — export genuinely isn't
   enabled yet)

```
$ scripts/gcp-spend.sh
2026-08-28T19:56:55Z resolving billing account for project-19b81040-83b3-4483-a0d
2026-08-28T19:57:04Z error: billing export table not found: project-19b81040-83b3-4483-a0d.billing_export.gcp_billing_export_v1_01C122_FCD47D_B347D4

This means either:
  1) the manual export step hasn't been done yet — go to
     https://console.cloud.google.com/billing/export, enable
     "Standard usage cost" (and ideally "Detailed usage cost") export,
     and point it at the 'billing_export' dataset in project 'project-19b81040-83b3-4483-a0d'; or
  2) it has been done, but no data has landed yet — first rows can take up
     to 24h after enabling.

Re-run this script once the table shows up (bq show project-19b81040-83b3-4483-a0d:billing_export.gcp_billing_export_v1_01C122_FCD47D_B347D4).
exit: 1
```

PASS — this is the demonstrable path today; there's no way to demonstrate
the success path until the manual step is done and ~24h of data has landed.

### 7. `task infra:validate` (all GCP roots, sandboxed copy, no backend/GCP call)

Adding `billing-export` to this task's root list and running the same
sandboxed-copy validate loop it uses:

```
── infrastructure/gcp/experiment
Success! The configuration is valid.

── infrastructure/gcp/experiment-pair
Success! The configuration is valid.

── infrastructure/gcp/experiment-diversity
Success! The configuration is valid.

── infrastructure/gcp/billing-export
Success! The configuration is valid.
```

PASS for all four roots. Note: the `task infra:validate` *task* itself
currently fails before reaching any root, on a pre-existing `terraform fmt`
drift in `infrastructure/gcp/modules/experiment-runner/tests/self_delete.tftest.hcl`
(alignment-only diff, unrelated to this change — confirmed via `git diff`
that this file is untouched by this work). Out of scope to fix here.

`terraform fmt -check -recursive infrastructure/gcp/billing-export` on its
own: exit 0, no diff.

## Completion

Both sides of the one manual step are done: the dataset exists
(`billing_export` in `project-19b81040-83b3-4483-a0d`, `US` location), the
query tooling is in place and fails loudly/correctly today. Turning the
export on itself is the owner's one remaining click, linked above.
