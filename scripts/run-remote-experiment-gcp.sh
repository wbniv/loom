#!/usr/bin/env bash
# run-remote-experiment-gcp.sh — run the masked-generation experiment's Phase A
# matrix on a rented g2-standard-4 (one NVIDIA L4) in us-central1 and bring the
# results home.
#
# The GCP sibling of scripts/run-remote-experiment.sh, with the same shape: it
# uploads the repo and the models, applies the experiment Terraform root, waits
# for the runner's status marker, downloads runs/, and destroys the stack —
# including on failure and on Ctrl-C, because an orphaned GPU instance is the
# expensive mistake here. The instance also deletes itself when its startup
# script ends, so a driver that dies outright still does not leave one running.
#
# Authentication is deliberately tokenised rather than a key file or
# application-default credentials: every terraform invocation is preceded by a
# fresh `gcloud auth print-access-token`, exported as GOOGLE_OAUTH_ACCESS_TOKEN.
# Those tokens last an hour, which is shorter than a run — hence the refresh
# before each invocation rather than once at the top.
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TUI_LIB="${TUI_LIB:-$HOME/python-tui-lib}"

GCP_PROJECT_ID="${LOOM_GCP_PROJECT_ID:-project-19b81040-83b3-4483-a0d}"
GCP_REGION="us-central1"
GCP_ZONE="${LOOM_GCP_ZONE:-us-central1-a}"
TF_DIR="${LOOM_GCP_TF_DIR:-$REPO_ROOT/infrastructure/gcp/experiment}"
BUCKET="${LOOM_GCP_BUCKET:-loom-experiment-artifacts-19b81040}"
STATE_BUCKET="loom-tfstate-19b81040"

MODELS_DIR="${LOOM_MODELS_DIR:-$HOME/loom-tools/models}"
CONFIG_PATH="$REPO_ROOT/prototype/experiment/phase_a.config.json"
MODEL_IDENTITY="${LOOM_MODEL_IDENTITY:-}"
GGUF_FILENAME=""
HARDWARE="g2-standard-4 L4 24GB"
MACHINE_TYPE="g2-standard-4"
REMOTE_OUTPUT_DIR="runs/phase-a-full"
DEST_DIR="$REPO_ROOT/prototype/runs/phase-a-full"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
POLL_SECONDS=60
TIMEOUT_SECONDS=$((4 * 3600))
USE_SPOT=true
KEEP_BUCKET=false
DRY_RUN=false
SKIP_QUOTA_CHECK=false

usage() {
    cat <<'USAGE'
Usage: scripts/run-remote-experiment-gcp.sh --model-identity NAME [options]

Runs the masked-generation experiment on a Spot g2-standard-4 (one NVIDIA
L4 24 GB) in us-central1 and downloads the results, then destroys everything
it created.

Which phase it runs is read out of --config, not configured here. A config
whose conditions are Phase A's is served over llama-server; a config asking
for "gbnf+typemask" (Phase B condition 4) runs in process over the pinned
libllama.so instead, because a per-token mask needs logits the HTTP API does
not expose. Mixing the two in one config is refused on the instance.

  Phase B condition 4:
    scripts/run-remote-experiment-gcp.sh \
      --model-identity "Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M" \
      --gguf qwen2.5-coder-7b-instruct-q4_k_m.gguf \
      --config prototype/experiment/phase_b.config.json \
      --remote-output-dir runs/phase-b --dest prototype/runs/phase-b

Required:
  --model-identity NAME   Recorded model identity, e.g.
                          "Qwen2.5-Coder-7B-Instruct-Q5_K_M". The runner
                          refuses a live backend without it (R2.1).
                          May also be given as LOOM_MODEL_IDENTITY.

Options:
  --models-dir DIR        Directory of .gguf files to upload.
                          Default: $HOME/loom-tools/models (LOOM_MODELS_DIR).
  --gguf NAME             Which uploaded .gguf to serve. Default: the only one.
  --config PATH           Run config to send up. Its matrix is used verbatim;
                          only the backend seam and the recorded identity
                          fields are rewritten on the instance.
                          Default: prototype/experiment/phase_a.config.json
  --dest DIR              Where to put the returned runs/ output.
                          Default: prototype/runs/phase-a-full
  --remote-output-dir DIR Output directory on the instance, and the name the
                          results are stored under in the bucket.
                          Default: runs/phase-a-full
  --run-id ID             Run identifier. Default: a UTC timestamp.
  --machine-type TYPE     Default: g2-standard-4
  --hardware STRING       Recorded hardware string.
                          Default: "g2-standard-4 L4 24GB"
  --on-demand             Use a standard VM rather than Spot (about 3.4x the
                          price, but not preemptible).
  --keep-bucket           Leave the artifacts bucket standing on teardown, so
                          the next run does not re-upload the models. Its
                          objects expire after 7 days regardless.
  --poll-seconds N        Status poll interval. Default: 60
  --timeout-seconds N     Give up waiting after this long. Default: 14400 (4 h)
  --skip-quota-check      Skip the GPU quota preflight.
  --dry-run               Print what would happen; touch no GCP resource.
  -h, --help              Show this help and exit.

Cost: about $0.25/hour on Spot, and a full matrix has been sized at under two
hours, so a complete run is well under $1 including GCS and the boot disk.
While the $300 trial credits last, it is $0.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --model-identity) MODEL_IDENTITY="$2"; shift 2 ;;
        --models-dir) MODELS_DIR="$2"; shift 2 ;;
        --gguf) GGUF_FILENAME="$2"; shift 2 ;;
        --config) CONFIG_PATH="$2"; shift 2 ;;
        --dest) DEST_DIR="$2"; shift 2 ;;
        --remote-output-dir) REMOTE_OUTPUT_DIR="$2"; shift 2 ;;
        --run-id) RUN_ID="$2"; shift 2 ;;
        --machine-type) MACHINE_TYPE="$2"; shift 2 ;;
        --hardware) HARDWARE="$2"; shift 2 ;;
        --on-demand) USE_SPOT=false; shift ;;
        --keep-bucket) KEEP_BUCKET=true; shift ;;
        --poll-seconds) POLL_SECONDS="$2"; shift 2 ;;
        --timeout-seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
        --skip-quota-check) SKIP_QUOTA_CHECK=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { printf '%s error: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; exit 1; }

[ -n "$MODEL_IDENTITY" ] || die "--model-identity is required (see --help)"
[ -f "$CONFIG_PATH" ] || die "config not found: $CONFIG_PATH"
[ -d "$MODELS_DIR" ] || die "models directory not found: $MODELS_DIR"
command -v terraform >/dev/null || die "terraform not on PATH — run 'task setup'"
command -v gcloud >/dev/null || die "gcloud not on PATH — run 'task setup'"
command -v gsutil >/dev/null || die "gsutil not on PATH — run 'task setup'"
command -v tar >/dev/null || die "tar not on PATH"
command -v python3 >/dev/null || die "python3 not on PATH"

GGUF_COUNT=$(find "$MODELS_DIR" -maxdepth 1 -name '*.gguf' | wc -l)
[ "$GGUF_COUNT" -gt 0 ] || die "no .gguf files under $MODELS_DIR"
if [ "$GGUF_COUNT" -gt 1 ] && [ -z "$GGUF_FILENAME" ]; then
    die "$GGUF_COUNT models under $MODELS_DIR — name one with --gguf"
fi

export CLOUDSDK_CORE_PROJECT="$GCP_PROJECT_ID"
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

STATUS_KEY="status/$RUN_ID.txt"
RESULTS_PREFIX="results/$RUN_ID/"

TF_VARS=(
    -var "project_id=$GCP_PROJECT_ID"
    -var "region=$GCP_REGION"
    -var "zone=$GCP_ZONE"
    -var "artifacts_bucket=$BUCKET"
    -var "run_id=$RUN_ID"
    -var "model_identity=$MODEL_IDENTITY"
    -var "gguf_filename=$GGUF_FILENAME"
    -var "hardware=$HARDWARE"
    -var "machine_type=$MACHINE_TYPE"
    -var "use_spot=$USE_SPOT"
    -var "remote_output_dir=$REMOTE_OUTPUT_DIR"
)

# --- terraform with a token that is never more than a moment old -------------
# There is no tf-safe-apply.sh path here: that wrapper's lock diagnosis is
# DynamoDB-specific and it hard-requires the aws CLI. The GCS backend takes its
# lock on the state object itself, so plain terraform is the whole story.
tf() {
    GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)" \
        terraform -chdir="$TF_DIR" "$@"
}

require_auth() {
    local account
    account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
    [ -n "$account" ] || die "no active gcloud account — run 'gcloud auth login'"
    log "gcloud account  : $account"
}

# --- Quota preflight ---------------------------------------------------------
# A GPU quota of zero fails the apply several minutes in, with a message that
# names an internal quota id rather than the thing to ask for. Check it up
# front and name the missing quota plainly.
quota_value() {
    # quota_value <scope: project|region> <metric>
    local scope="$1" metric="$2" json
    if [ "$scope" = project ]; then
        json="$(gcloud compute project-info describe --format=json 2>/dev/null || true)"
    else
        json="$(gcloud compute regions describe "$GCP_REGION" --format=json 2>/dev/null || true)"
    fi
    [ -n "$json" ] || { echo "unknown"; return 0; }
    METRIC="$metric" python3 -c '
import json, os, sys
metric = os.environ["METRIC"]
try:
    doc = json.load(sys.stdin)
except ValueError:
    print("unknown"); sys.exit(0)
for quota in doc.get("quotas", []):
    if quota.get("metric") == metric:
        print(quota.get("limit", 0)); sys.exit(0)
print("unknown")
' <<<"$json"
}

check_quota() {
    local metric scope have
    scope="$1"; metric="$2"
    have="$(quota_value "$scope" "$metric")"
    if [ "$have" = unknown ]; then
        log "quota $metric: could not be read; continuing"
        return 0
    fi
    log "quota $metric: $have"
    python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) >= 1 else 1)' "$have" && return 0
    die "GPU quota $metric is $have in ${scope} scope (${GCP_REGION}); request at least 1 at
    https://console.cloud.google.com/iam-admin/quotas?project=$GCP_PROJECT_ID
  and re-run. Pass --skip-quota-check to bypass this check."
}

preflight_quota() {
    check_quota project GPUS_ALL_REGIONS
    if [ "$USE_SPOT" = true ]; then
        check_quota region PREEMPTIBLE_NVIDIA_L4_GPUS
    else
        check_quota region NVIDIA_L4_GPUS
    fi
}

# --- Terraform state bucket --------------------------------------------------
# One versioned bucket is less machinery than a bootstrap Terraform root with
# its own local state, so it is created here, idempotently.
ensure_state_bucket() {
    if gsutil ls -b "gs://$STATE_BUCKET" >/dev/null 2>&1; then
        log "state bucket    : gs://$STATE_BUCKET (exists)"
        return 0
    fi
    log "creating the terraform state bucket gs://$STATE_BUCKET"
    gcloud storage buckets create "gs://$STATE_BUCKET" \
        --project="$GCP_PROJECT_ID" \
        --location="$GCP_REGION" \
        --uniform-bucket-level-access \
        --public-access-prevention
    gcloud storage buckets update "gs://$STATE_BUCKET" --versioning
}

log "run id          : $RUN_ID"
log "project/zone    : $GCP_PROJECT_ID / $GCP_ZONE"
log "machine type    : $MACHINE_TYPE (spot=$USE_SPOT)"
log "model identity  : $MODEL_IDENTITY"
log "models          : $MODELS_DIR"
log "config          : $CONFIG_PATH"
log "results land in : $DEST_DIR"

if [ "$DRY_RUN" = true ]; then
    log "dry run: stopping before any GCP call"
    exit 0
fi

require_auth
if [ "$SKIP_QUOTA_CHECK" = true ]; then
    log "quota preflight skipped by request"
else
    preflight_quota
fi
ensure_state_bucket

# --- Cleanup, LIFO ----------------------------------------------------------
# Registered before the first apply so a Ctrl-C between apply and poll still
# tears the instance down. cleanup-stack owns the single EXIT trap; handlers run
# in reverse registration order, so the tarball is removed after the destroy.
# shellcheck source=/dev/null
source "$TUI_LIB/scripts/cleanup-stack.sh"

TARBALL="$(mktemp -t loom-repo-XXXXXX.tar.gz)"
push_cleanup "rm -f '$TARBALL'"

teardown() {
    log "teardown: destroying the experiment stack"
    if [ "$KEEP_BUCKET" = true ]; then
        # launch_runner=false keeps the bucket and the IAM bindings, and takes
        # the instance (the only meaningful cost) away.
        tf apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=false"
    else
        tf destroy -auto-approve "${TF_VARS[@]}"
    fi
}
push_cleanup teardown

# --- 1. Bucket and IAM bindings, without the GPU ----------------------------
# The driver has to upload before the instance boots, so the bucket is applied
# on its own first.
log "apply 1/2: artifacts bucket and IAM bindings"
tf init -input=false
tf apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=false"

# --- 2. Upload the repo, the config and the models --------------------------
log "packing the repo"
# The corpus-loop follow-up's config resolves store_export relative to the
# config file, landing on <repo>/.loom-store-generated/export-resolver.json.
# Pack that one derived file when it exists so the path resolves on the
# instance too; a run that does not use it is unaffected.
STORE_EXPORT=""
[ -f "$REPO_ROOT/.loom-store-generated/export-resolver.json" ] \
    && STORE_EXPORT=".loom-store-generated/export-resolver.json"
tar -czf "$TARBALL" \
    -C "$REPO_ROOT" \
    --exclude='prototype/runs' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    prototype Taskfile.yml $STORE_EXPORT

log "uploading the repo tarball ($(du -h "$TARBALL" | cut -f1))"
gsutil -q cp "$TARBALL" "gs://$BUCKET/repo/repo.tar.gz"

log "uploading the run config"
gsutil -q cp "$CONFIG_PATH" "gs://$BUCKET/config/run.config.json"

log "uploading models from $MODELS_DIR (skipping anything already in the bucket)"
# A `gsutil stat` existence check up front means a re-run with --keep-bucket
# (or a second arm sharing the same bucket) touches the network at all only
# for models it does not already have — cheaper and faster than relying on
# `cp -n` alone to discover that server-side. The upload itself is still
# wrapped in a bounded retry: a stalled multi-GB transfer previously hung for
# 39 minutes with zero progress and no error (2026-08-23), silently eating a
# run's wall clock. `timeout` turns a silent hang into a loud, bounded retry
# instead.
while IFS= read -r gguf; do
    name="$(basename "$gguf")"
    if gsutil -q stat "gs://$BUCKET/models/$name" >/dev/null 2>&1; then
        log "  $name (already in bucket, skipping)"
        continue
    fi
    log "  $name"
    # `gcloud storage cp` rather than `gsutil cp`: parallel composite upload
    # (multi-stream, much faster on multi-GB files) and a persistent resumable
    # tracker, so a killed attempt continues where it stopped instead of
    # restarting from byte 0 — the 30-min-cap-with-restart combination killed
    # a ~29.5-min 3B upload three times in a row at ~99% (2026-08-23). The
    # per-attempt timeout is sized for the largest model at a slow uplink
    # (4.7 GB at ~1 MB/s ≈ 80 min), not for the average case.
    attempt=1
    until timeout 7200 gcloud storage cp --no-clobber "$gguf" "gs://$BUCKET/models/$name"; do
        [ "$attempt" -ge 3 ] && die "upload of $name stalled or failed $attempt times in a row (120 min each) — see the gcloud storage output above"
        log "  $name: upload attempt $attempt stalled or failed, retrying (resumes from tracker)"
        attempt=$((attempt + 1))
    done
done < <(find "$MODELS_DIR" -maxdepth 1 -name '*.gguf' | sort)

# A stale marker from a previous run with the same id would end the poll
# immediately. There should not be one; make sure.
gsutil -q rm "gs://$BUCKET/$STATUS_KEY" 2>/dev/null || true

# --- 3. Launch ---------------------------------------------------------------
log "apply 2/2: launching the runner"
tf apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=true"

# --- 4. Wait for the marker --------------------------------------------------
log "waiting for gs://$BUCKET/$STATUS_KEY (every ${POLL_SECONDS}s, up to ${TIMEOUT_SECONDS}s)"
DEADLINE=$(( $(date +%s) + TIMEOUT_SECONDS ))
RUN_STATUS=""
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    if RUN_STATUS=$(gsutil -q cat "gs://$BUCKET/$STATUS_KEY" 2>/dev/null); then
        RUN_STATUS="$(printf '%s' "$RUN_STATUS" | tr -d '[:space:]')"
        log "runner reported: $RUN_STATUS"
        break
    fi
    RUN_STATUS=""
    remaining=$(( DEADLINE - $(date +%s) ))
    log "still running (${remaining}s of budget left)"
    sleep "$POLL_SECONDS"
done

# --- 5. Bring the results home ----------------------------------------------
# Unconditional: a failed run still has partial records.jsonl and the two logs,
# and those are what say why it failed.
mkdir -p "$DEST_DIR" "$DEST_DIR/logs"
log "downloading gs://$BUCKET/${RESULTS_PREFIX}runs/ into $DEST_DIR"
gsutil -q -m rsync -r "gs://$BUCKET/${RESULTS_PREFIX}runs/" "$DEST_DIR" || true
log "downloading logs into $DEST_DIR/logs"
gsutil -q -m rsync -r "gs://$BUCKET/${RESULTS_PREFIX}logs/" "$DEST_DIR/logs" || true

if [ -z "$RUN_STATUS" ]; then
    # One post-loop grace poll: a laptop suspend freezes this process while the
    # wall clock runs on, so the deadline can pass without a single live poll
    # in hours. Seen 2026-08-14: suspend 08:34–12:47 UTC swallowed a run that
    # had SUCCEEDED at 11:14; the loop woke already past deadline and died
    # without looking. The marker check is cheap; look once more before dying.
    RUN_STATUS=$(gsutil -q cat "gs://$BUCKET/$STATUS_KEY" 2>/dev/null | tr -d '[:space:]' || true)
    [ -n "$RUN_STATUS" ] && log "runner reported (post-deadline grace poll): $RUN_STATUS"
fi
if [ -z "$RUN_STATUS" ]; then
    die "timed out after ${TIMEOUT_SECONDS}s with no status marker; see $DEST_DIR/logs"
fi
if [ "$RUN_STATUS" != "SUCCEEDED" ]; then
    die "the remote run reported $RUN_STATUS; see $DEST_DIR/logs/startup-script.log"
fi

log "done: results in $DEST_DIR"
