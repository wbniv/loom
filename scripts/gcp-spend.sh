#!/usr/bin/env bash
# gcp-spend.sh — query GCP spend from the BigQuery billing export set up by
# infrastructure/gcp/billing-export/.
#
# That root creates the empty target dataset and enables the BigQuery API;
# the export itself is switched on manually, once, in the console (see that
# root's main.tf and docs/plans/2026-08-14-gcp-experiment-infra.md-adjacent
# infra docs for why — Cloud Billing export has no API/Terraform surface).
# Until that's done, and for up to ~24h after, the export table this script
# looks for does not exist yet; that is the loud, expected failure mode
# below, not a bug in this script.
#
# The table name is derived at runtime from the billing account id
# (`gcp_billing_export_v1_<account_id_with_underscores>`) rather than
# hardcoded, because the id is project-specific and this script has no
# business embedding it.
set -euo pipefail

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { printf '%s error: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Usage: scripts/gcp-spend.sh [options]

Queries GCP spend from the BigQuery billing export (standard usage cost
table). Net of credits, grouped by service by default.

With no options: current calendar month, totals + per-service breakdown.

Options:
  --days N        Last N days (from N days ago through now) instead of the
                   current calendar month.
  --month YYYY-MM  A specific calendar month instead of the current one.
  --by-sku        Break down by SKU instead of by service.
  --project ID    Project to query spend for. Default: project-19b81040-83b3-4483-a0d
                   (or LOOM_GCP_PROJECT_ID).
  -h, --help      Show this help and exit.

--days and --month are mutually exclusive.

Examples:
  scripts/gcp-spend.sh
  scripts/gcp-spend.sh --days 7
  scripts/gcp-spend.sh --month 2026-07
  scripts/gcp-spend.sh --days 30 --by-sku

If the export table doesn't exist yet, this means either the one manual step
(https://console.cloud.google.com/billing/export) hasn't been done, or it has
but data hasn't landed yet (first rows can take up to 24h after enabling).
USAGE
}

PROJECT_ID="${LOOM_GCP_PROJECT_ID:-project-19b81040-83b3-4483-a0d}"
DATASET_ID="${LOOM_GCP_BILLING_DATASET:-billing_export}"
DAYS=""
MONTH=""
BY_SKU=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --days)
            [[ $# -ge 2 ]] || die "--days requires a value"
            DAYS="$2"; shift 2 ;;
        --month)
            [[ $# -ge 2 ]] || die "--month requires a value"
            MONTH="$2"; shift 2 ;;
        --by-sku) BY_SKU=1; shift ;;
        --project)
            [[ $# -ge 2 ]] || die "--project requires a value"
            PROJECT_ID="$2"; shift 2 ;;
        *) die "unknown argument: $1 (see --help)" ;;
    esac
done

[[ -n "$DAYS" && -n "$MONTH" ]] && die "--days and --month are mutually exclusive"
if [[ -n "$DAYS" ]]; then
    [[ "$DAYS" =~ ^[0-9]+$ && "$DAYS" -gt 0 ]] || die "--days must be a positive integer, got: $DAYS"
fi
if [[ -n "$MONTH" ]]; then
    [[ "$MONTH" =~ ^[0-9]{4}-(0[1-9]|1[0-2])$ ]] || die "--month must be YYYY-MM, got: $MONTH"
fi

command -v bq >/dev/null 2>&1 || die "bq not found on PATH. Run 'task setup' (it symlinks bq from the Google Cloud SDK into ~/.local/bin)."
command -v gcloud >/dev/null 2>&1 || die "gcloud not found on PATH. Run 'task setup'."

# ── Resolve the export table name ───────────────────────────────────────────
log "resolving billing account for $PROJECT_ID"
BILLING_ACCOUNT="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)' 2>/dev/null || true)"
[[ -n "$BILLING_ACCOUNT" ]] || die "could not resolve a billing account for project '$PROJECT_ID' — is billing attached? (gcloud billing projects describe $PROJECT_ID)"

BILLING_ACCOUNT_ID="${BILLING_ACCOUNT#billingAccounts/}"
TABLE="gcp_billing_export_v1_${BILLING_ACCOUNT_ID//-/_}"
FULL_TABLE="${PROJECT_ID}.${DATASET_ID}.${TABLE}"

if ! bq show --format=none "${PROJECT_ID}:${DATASET_ID}.${TABLE}" >/dev/null 2>&1; then
    die "billing export table not found: $FULL_TABLE

This means either:
  1) the manual export step hasn't been done yet — go to
     https://console.cloud.google.com/billing/export, enable
     \"Standard usage cost\" (and ideally \"Detailed usage cost\") export,
     and point it at the '$DATASET_ID' dataset in project '$PROJECT_ID'; or
  2) it has been done, but no data has landed yet — first rows can take up
     to 24h after enabling.

Re-run this script once the table shows up (bq show ${PROJECT_ID}:${DATASET_ID}.${TABLE})."
fi

# ── Compute the date range ──────────────────────────────────────────────────
if [[ -n "$MONTH" ]]; then
    START="${MONTH}-01"
    END="$(date -u -d "${START} +1 month" +%Y-%m-%d)"
    RANGE_DESC="month $MONTH"
elif [[ -n "$DAYS" ]]; then
    START="$(date -u -d "-${DAYS} days" +%Y-%m-%d)"
    END="$(date -u -d "+1 day" +%Y-%m-%d)"
    RANGE_DESC="last $DAYS days"
else
    START="$(date -u +%Y-%m-01)"
    END="$(date -u -d "+1 day" +%Y-%m-%d)"
    RANGE_DESC="current month ($(date -u +%Y-%m))"
fi

GROUP_LABEL="service"
GROUP_EXPR="service.description"
if [[ "$BY_SKU" -eq 1 ]]; then
    GROUP_LABEL="sku"
    GROUP_EXPR="sku.description"
fi

# Net of credits: `cost` is gross; `credits` is a repeated record of
# discounts/promos/committed-use adjustments applied to that line.
NET_COST_EXPR="ROUND(SUM(cost) + IFNULL(SUM((SELECT SUM(c.amount) FROM UNNEST(credits) AS c)), 0), 2)"

log "querying $FULL_TABLE for $RANGE_DESC (project $PROJECT_ID)"
echo
echo "== Total — $RANGE_DESC =="
bq query --use_legacy_sql=false --format=pretty \
    --parameter="project_id::STRING:${PROJECT_ID}" \
    --parameter="start_date::TIMESTAMP:${START}" \
    --parameter="end_date::TIMESTAMP:${END}" \
    "SELECT ${NET_COST_EXPR} AS net_cost, ANY_VALUE(currency) AS currency
     FROM \`${FULL_TABLE}\`
     WHERE project.id = @project_id
       AND usage_start_time >= @start_date
       AND usage_start_time < @end_date"

echo
echo "== By ${GROUP_LABEL} — $RANGE_DESC =="
bq query --use_legacy_sql=false --format=pretty \
    --parameter="project_id::STRING:${PROJECT_ID}" \
    --parameter="start_date::TIMESTAMP:${START}" \
    --parameter="end_date::TIMESTAMP:${END}" \
    "SELECT ${GROUP_EXPR} AS ${GROUP_LABEL}, ${NET_COST_EXPR} AS net_cost, ANY_VALUE(currency) AS currency
     FROM \`${FULL_TABLE}\`
     WHERE project.id = @project_id
       AND usage_start_time >= @start_date
       AND usage_start_time < @end_date
     GROUP BY ${GROUP_LABEL}
     ORDER BY net_cost DESC"
