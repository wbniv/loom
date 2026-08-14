#!/usr/bin/env bash
# run-remote-experiment.sh — run the masked-generation experiment's Phase A
# matrix on a rented g6.xlarge and bring the results home.
#
# The whole rental is bracketed by this script: it uploads the repo and the
# models, applies the experiment Terraform root, waits for the runner's status
# marker, downloads runs/, and destroys the stack — including on failure and on
# Ctrl-C, because an orphaned GPU instance is the expensive mistake here. The
# instance also self-terminates when its user-data script ends, so a driver that
# dies outright still does not leave one running.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TUI_LIB="${TUI_LIB:-$HOME/python-tui-lib}"
TF_SAFE_APPLY="$TUI_LIB/scripts/tf-safe-apply.sh"

AWS_PROFILE_NAME="loom-terraform"
AWS_REGION="us-east-2"
TF_DIR="$REPO_ROOT/infrastructure/aws/experiment"
BUCKET="loom-experiment-artifacts"

MODELS_DIR="${LOOM_MODELS_DIR:-$HOME/loom-tools/models}"
CONFIG_PATH="$REPO_ROOT/prototype/experiment/phase_a.config.json"
MODEL_IDENTITY="${LOOM_MODEL_IDENTITY:-}"
GGUF_FILENAME=""
HARDWARE="g6.xlarge L4 24GB"
INSTANCE_TYPE="g6.xlarge"
REMOTE_OUTPUT_DIR="runs/phase-a-full"
DEST_DIR="$REPO_ROOT/prototype/runs/phase-a-full"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
POLL_SECONDS=60
TIMEOUT_SECONDS=$((4 * 3600))
USE_SPOT=true
KEEP_BUCKET=false
DRY_RUN=false

usage() {
    cat <<'USAGE'
Usage: scripts/run-remote-experiment.sh --model-identity NAME [options]

Runs Phase A of the masked-generation experiment on a spot g6.xlarge in
us-east-2 and downloads the results, then destroys everything it created.

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
  --run-id ID             Run identifier. Default: a UTC timestamp.
  --instance-type TYPE    Default: g6.xlarge
  --hardware STRING       Recorded hardware string. Default: "g6.xlarge L4 24GB"
  --on-demand             Use on-demand rather than spot (about 2.4x the price,
                          but not interruptible).
  --keep-bucket           Leave loom-experiment-artifacts standing on teardown,
                          so the next run does not re-upload the models. Its
                          objects expire after 7 days regardless.
  --poll-seconds N        Status poll interval. Default: 60
  --timeout-seconds N     Give up waiting after this long. Default: 14400 (4 h)
  --dry-run               Print what would happen; touch no AWS resource.
  -h, --help              Show this help and exit.

Cost: about $0.35/hour on spot, and a full matrix has been sized at under two
hours, so a complete run is well under $1 including S3 and EBS.
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
        --run-id) RUN_ID="$2"; shift 2 ;;
        --instance-type) INSTANCE_TYPE="$2"; shift 2 ;;
        --hardware) HARDWARE="$2"; shift 2 ;;
        --on-demand) USE_SPOT=false; shift ;;
        --keep-bucket) KEEP_BUCKET=true; shift ;;
        --poll-seconds) POLL_SECONDS="$2"; shift 2 ;;
        --timeout-seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { printf '%s error: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; exit 1; }

[ -n "$MODEL_IDENTITY" ] || die "--model-identity is required (see --help)"
[ -f "$CONFIG_PATH" ] || die "config not found: $CONFIG_PATH"
[ -d "$MODELS_DIR" ] || die "models directory not found: $MODELS_DIR"
[ -x "$TF_SAFE_APPLY" ] || die "tf-safe-apply.sh not found at $TF_SAFE_APPLY"
command -v aws >/dev/null || die "aws CLI not on PATH"
command -v tar >/dev/null || die "tar not on PATH"

GGUF_COUNT=$(find "$MODELS_DIR" -maxdepth 1 -name '*.gguf' | wc -l)
[ "$GGUF_COUNT" -gt 0 ] || die "no .gguf files under $MODELS_DIR"
if [ "$GGUF_COUNT" -gt 1 ] && [ -z "$GGUF_FILENAME" ]; then
    die "$GGUF_COUNT models under $MODELS_DIR — name one with --gguf"
fi

export AWS_PROFILE="$AWS_PROFILE_NAME"
export AWS_DEFAULT_REGION="$AWS_REGION"

STATUS_KEY="status/$RUN_ID.txt"
RESULTS_PREFIX="results/$RUN_ID/"

TF_VARS=(
    -var "run_id=$RUN_ID"
    -var "model_identity=$MODEL_IDENTITY"
    -var "gguf_filename=$GGUF_FILENAME"
    -var "hardware=$HARDWARE"
    -var "instance_type=$INSTANCE_TYPE"
    -var "use_spot=$USE_SPOT"
    -var "remote_output_dir=$REMOTE_OUTPUT_DIR"
)

log "run id          : $RUN_ID"
log "profile/region  : $AWS_PROFILE_NAME / $AWS_REGION"
log "model identity  : $MODEL_IDENTITY"
log "models          : $MODELS_DIR"
log "config          : $CONFIG_PATH"
log "results land in : $DEST_DIR"

if [ "$DRY_RUN" = true ]; then
    log "dry run: stopping before the first apply"
    exit 0
fi

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
        # launch_runner=false keeps the bucket and the instance role, and takes
        # the instance (the only meaningful cost) away.
        "$TF_SAFE_APPLY" "$TF_DIR" apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=false"
    else
        "$TF_SAFE_APPLY" "$TF_DIR" destroy -auto-approve "${TF_VARS[@]}"
    fi
}
push_cleanup teardown

# --- 1. Bucket and instance role, without the GPU ---------------------------
# The driver has to upload before the instance boots, so the bucket is applied
# on its own first.
log "apply 1/2: artifacts bucket and instance role"
"$TF_SAFE_APPLY" "$TF_DIR" init
"$TF_SAFE_APPLY" "$TF_DIR" apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=false"

# --- 2. Upload the repo, the config and the models --------------------------
log "packing the repo"
tar -czf "$TARBALL" \
    -C "$REPO_ROOT" \
    --exclude='prototype/runs' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    prototype Taskfile.yml

log "uploading the repo tarball ($(du -h "$TARBALL" | cut -f1))"
aws s3 cp "$TARBALL" "s3://$BUCKET/repo/repo.tar.gz" --only-show-errors

log "uploading the run config"
aws s3 cp "$CONFIG_PATH" "s3://$BUCKET/config/run.config.json" --only-show-errors

log "uploading models from $MODELS_DIR (skipping anything already there)"
aws s3 sync "$MODELS_DIR" "s3://$BUCKET/models/" --exclude '*' --include '*.gguf' --size-only

# A stale marker from a previous run with the same id would end the poll
# immediately. There should not be one; make sure.
aws s3 rm "s3://$BUCKET/$STATUS_KEY" --only-show-errors 2>/dev/null || true

# --- 3. Launch ---------------------------------------------------------------
log "apply 2/2: launching the runner"
"$TF_SAFE_APPLY" "$TF_DIR" apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=true"

# --- 4. Wait for the marker --------------------------------------------------
log "waiting for s3://$BUCKET/$STATUS_KEY (every ${POLL_SECONDS}s, up to ${TIMEOUT_SECONDS}s)"
DEADLINE=$(( $(date +%s) + TIMEOUT_SECONDS ))
RUN_STATUS=""
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    if RUN_STATUS=$(aws s3 cp "s3://$BUCKET/$STATUS_KEY" - 2>/dev/null); then
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
mkdir -p "$DEST_DIR"
log "downloading s3://$BUCKET/${RESULTS_PREFIX}runs/ into $DEST_DIR"
aws s3 sync "s3://$BUCKET/${RESULTS_PREFIX}runs/" "$DEST_DIR" --only-show-errors || true
log "downloading logs into $DEST_DIR/logs"
aws s3 sync "s3://$BUCKET/${RESULTS_PREFIX}logs/" "$DEST_DIR/logs" --only-show-errors || true

if [ -z "$RUN_STATUS" ]; then
    die "timed out after ${TIMEOUT_SECONDS}s with no status marker; see $DEST_DIR/logs"
fi
if [ "$RUN_STATUS" != "SUCCEEDED" ]; then
    die "the remote run reported $RUN_STATUS; see $DEST_DIR/logs/user-data.log"
fi

log "done: results in $DEST_DIR"
