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
#
# The driver is not, however, allowed to be the single point of failure that
# its GCP sibling (scripts/run-remote-experiment-gcp.sh) turned out to be on
# 2026-08-27, when the host suspended mid-poll and lost power while asleep: no
# signal reached the process, the EXIT trap never ran, and a finished run's
# results sat uncollected for seven hours behind a disk that kept billing. Same
# shape here, same exposure, so the same three things follow — see
# docs/plans/2026-08-27-driver-survivability-and-resume.md for the incident and
# the design this ports:
#
#   --detach    re-exec under setsid so a session or terminal tearing down its
#               process group cannot take the waiter with it.
#   the log     every run tees its own output to prototype/runs/logs/ from the
#               first line, so there is always a local record of what ran, what
#               run id it minted, and how far it got.
#   --resume    re-enter at the wait/fetch/teardown step against an existing
#               run, driven by the manifest the launch wrote next to that log:
#                 scripts/run-remote-experiment.sh \
#                   --resume-from prototype/runs/logs/driver-<tag>.json \
#                   --fetch-only
set -euo pipefail

# Kept verbatim so --detach can hand the same invocation to its own child, and
# so the durable log opens with exactly what was asked for.
ORIG_ARGV=("$@")

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TUI_LIB="${TUI_LIB:-$HOME/python-tui-lib}"
TF_SAFE_APPLY="$TUI_LIB/scripts/tf-safe-apply.sh"

AWS_PROFILE_NAME="loom-terraform"
AWS_REGION="us-east-2"
# Overridable, unlike the GCP sibling's PATH prepend problem: this driver never
# prepends anything ahead of a caller's PATH (it has no equivalent of GCP's
# `export PATH="$HOME/.local/bin:$PATH"`), so a plain PATH shim already wins
# here — no LOOM_DRIVER_BIN_OVERRIDE seam is needed. What *does* need to be
# overridable for an offline test harness is which Terraform root and bucket
# get touched, since both are hardcoded constants below production has no
# reason to vary; the GCP incident (docs/plans/2026-08-27-driver-survivability-
# and-resume.md §7) was a real `terraform` run against real state because its
# test pointed --tf-dir at a real root. These two env vars are this driver's
# equivalent of a throwaway --tf-dir: a test sets them to an empty scratch
# directory and a scratch bucket name that resolve to nothing real.
TF_DIR="${LOOM_AWS_TF_DIR:-$REPO_ROOT/infrastructure/aws/experiment}"
BUCKET="${LOOM_AWS_BUCKET:-loom-experiment-artifacts}"

MODELS_DIR="${LOOM_MODELS_DIR:-$HOME/loom-tools/models}"
CONFIG_PATH="$REPO_ROOT/prototype/experiment/phase_a.config.json"
MODEL_IDENTITY="${LOOM_MODEL_IDENTITY:-}"
GGUF_FILENAME=""
HARDWARE="g6.xlarge L4 24GB"
INSTANCE_TYPE="g6.xlarge"
REMOTE_OUTPUT_DIR="runs/phase-a-full"
DEST_DIR="$REPO_ROOT/prototype/runs/phase-a-full"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ID_SET=false
POLL_SECONDS=60
TIMEOUT_SECONDS=$((4 * 3600))
USE_SPOT=true
KEEP_BUCKET=false
DRY_RUN=false

# --- Survivability -----------------------------------------------------------
# Ported from the GCP driver's 2026-08-27 fix (same plan, §8 follow-up: "the
# AWS sibling ... has the same wait-loop-then-fetch-then-trap shape and the
# same exposure"). Measured there, not assumed: cleanup-stack's EXIT trap DOES
# fire on TERM, HUP and INT — only SIGKILL and host death skip it, and no trap
# can cover those. So the fix is not more trapping, it is a re-entry point plus
# enough recorded state to use it.
RESUME=false
TEARDOWN_ANYWAY=false
DETACH=false
# Armed = teardown() is allowed to touch infrastructure. Always true for a run
# we launched ourselves; in resume mode only once the run is provably finished,
# because --fetch-only against a live run must not destroy its GPU.
TEARDOWN_ARMED=true
LOG_DIR="${LOOM_DRIVER_LOG_DIR:-$REPO_ROOT/prototype/runs/logs}"
DRIVER_LOG=""

# Defined up here rather than after the argument loop, because --resume-from
# has to be able to refuse a missing manifest in the same voice as everything
# else.
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { printf '%s error: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; exit 1; }

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

Surviving the driver's own death:
  --detach                Re-exec under `setsid nohup` in a new session, print
                          the pid and log path, and return. A terminal closing
                          or a session tearing down its process group then
                          cannot take the waiter with it. RUN_ID and the log
                          path are pinned into the child's argv, so the child
                          cannot mint a different run id than was announced.
  --log-file PATH         Where to tee this driver's own output. Default:
                          prototype/runs/logs/driver-<run-id>.log
                          (LOOM_DRIVER_LOG_DIR overrides the directory). The
                          log is opened before any AWS call, so even a
                          preflight refusal is on disk afterwards.

Recovering a run whose driver died (the whole point of the two above):
  --resume                Skip the bucket apply, the uploads and the launch.
                          Go straight to waiting for the marker, fetching the
                          results and tearing the instance down — the same code
                          paths a normal run uses, not a second copy of them.
                          Requires --run-id (and the launch's other settings),
                          which is what --resume-from supplies for you.
  --fetch-only            --resume with a zero-length wait: read the marker
                          once, fetch whatever is in the bucket, tear down.
  --resume-from FILE      Read a run manifest written by an earlier invocation
                          (prototype/runs/logs/driver-<tag>.json) and restore
                          every setting from it. Flags placed AFTER this one
                          override what the manifest says. Usually all you need:
                            --resume-from prototype/runs/logs/driver-<tag>.json --fetch-only
  --teardown-anyway       In resume mode, tear the instance down even though no
                          status marker says the run finished. Off by default:
                          without a marker the run may still be in flight, and
                          tearing it down would destroy a live GPU.

Cost: about $0.35/hour on spot, and a full matrix has been sized at under two
hours, so a complete run is well under $1 including S3 and EBS.
USAGE
}

# --- Run manifest ------------------------------------------------------------
# Written at launch, read by --resume-from. Its whole job is to carry the one
# value that made recovering the GCP incident a manual archaeology exercise:
# RUN_ID, which defaults to a UTC timestamp minted inside this process and is
# otherwise knowable only from a log that may not have survived whatever killed
# the driver.
write_manifest() {
    mkdir -p "$(dirname "$MANIFEST_PATH")"
    LOOM_M_RUN_ID="$RUN_ID" \
    LOOM_M_BUCKET="$BUCKET" \
    LOOM_M_TF_DIR="$TF_DIR" \
    LOOM_M_DEST_DIR="$DEST_DIR" \
    LOOM_M_MODEL_IDENTITY="$MODEL_IDENTITY" \
    LOOM_M_GGUF_FILENAME="$GGUF_FILENAME" \
    LOOM_M_HARDWARE="$HARDWARE" \
    LOOM_M_INSTANCE_TYPE="$INSTANCE_TYPE" \
    LOOM_M_USE_SPOT="$USE_SPOT" \
    LOOM_M_REMOTE_OUTPUT_DIR="$REMOTE_OUTPUT_DIR" \
    LOOM_M_KEEP_BUCKET="$KEEP_BUCKET" \
    LOOM_M_MODELS_DIR="$MODELS_DIR" \
    LOOM_M_DRIVER_LOG="$DRIVER_LOG" \
    LOOM_M_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    LOOM_M_PID="$$" \
    MANIFEST_PATH="$MANIFEST_PATH" \
    python3 -c '
import json, os
keys = ["run_id", "bucket", "tf_dir", "dest_dir", "model_identity",
        "gguf_filename", "hardware", "instance_type", "use_spot",
        "remote_output_dir", "keep_bucket", "models_dir", "driver_log",
        "started_at", "pid"]
doc = {k: os.environ["LOOM_M_" + k.upper()] for k in keys}
with open(os.environ["MANIFEST_PATH"], "w") as fh:
    json.dump(doc, fh, indent=2, sort_keys=True)
    fh.write("\n")
'
}

# Restore a manifest's settings. Applied in argument order, so a flag placed
# after --resume-from wins over the manifest — the usual "later flag wins" rule
# this loop already has for everything else.
load_manifest() {
    local file="$1" key value
    [ -f "$file" ] || die "run manifest not found: $file"
    command -v python3 >/dev/null || die "python3 is required to read a run manifest"
    while IFS=$'\t' read -r key value; do
        case "$key" in
            run_id)            RUN_ID="$value"; RUN_ID_SET=true ;;
            bucket)            BUCKET="$value" ;;
            tf_dir)            TF_DIR="$value" ;;
            dest_dir)          DEST_DIR="$value" ;;
            model_identity)    MODEL_IDENTITY="$value" ;;
            gguf_filename)     GGUF_FILENAME="$value" ;;
            hardware)          HARDWARE="$value" ;;
            instance_type)     INSTANCE_TYPE="$value" ;;
            use_spot)          USE_SPOT="$value" ;;
            remote_output_dir) REMOTE_OUTPUT_DIR="$value" ;;
            keep_bucket)       KEEP_BUCKET="$value" ;;
            models_dir)        MODELS_DIR="$value" ;;
            *)                 : ;;
        esac
    done < <(LOOM_MANIFEST="$file" python3 -c '
import json, os, sys
doc = json.load(open(os.environ["LOOM_MANIFEST"]))
for key, value in doc.items():
    if isinstance(value, bool):
        value = "true" if value else "false"
    sys.stdout.write("%s\t%s\n" % (key, "" if value is None else value))
')
    RESUME=true
}

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --model-identity) MODEL_IDENTITY="$2"; shift 2 ;;
        --models-dir) MODELS_DIR="$2"; shift 2 ;;
        --gguf) GGUF_FILENAME="$2"; shift 2 ;;
        --config) CONFIG_PATH="$2"; shift 2 ;;
        --dest) DEST_DIR="$2"; shift 2 ;;
        --run-id) RUN_ID="$2"; RUN_ID_SET=true; shift 2 ;;
        --instance-type) INSTANCE_TYPE="$2"; shift 2 ;;
        --hardware) HARDWARE="$2"; shift 2 ;;
        --on-demand) USE_SPOT=false; shift ;;
        --keep-bucket) KEEP_BUCKET=true; shift ;;
        --poll-seconds) POLL_SECONDS="$2"; shift 2 ;;
        --timeout-seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --resume) RESUME=true; shift ;;
        --fetch-only) RESUME=true; TIMEOUT_SECONDS=0; shift ;;
        --resume-from) load_manifest "$2"; shift 2 ;;
        --teardown-anyway) TEARDOWN_ANYWAY=true; shift ;;
        --detach) DETACH=true; shift ;;
        --log-file) DRIVER_LOG="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

# --- Durable local log, opened before anything else can fail -----------------
# The point of the GCP incident this ports from: an undiagnosable loss is worse
# than a diagnosable one. A log under prototype/runs/logs/ survives whatever
# killed the driver and sits next to the results it was supposed to fetch.
RUN_TAG="$RUN_ID"
MANIFEST_PATH="$LOG_DIR/driver-$RUN_TAG.json"
[ -n "$DRIVER_LOG" ] || DRIVER_LOG="$LOG_DIR/driver-$RUN_TAG.log"
mkdir -p "$LOG_DIR" "$(dirname "$DRIVER_LOG")"

# --- Detach, so a dying parent cannot take the waiter with it ----------------
# setsid puts the child in its own session and process group, out of reach of a
# terminal hang-up or a process-group kill aimed at whatever launched us. It is
# no defence at all against the host losing power — that is what --resume is
# for.
if [ "$DETACH" = true ] && [ -z "${LOOM_DRIVER_DETACHED:-}" ]; then
    command -v setsid >/dev/null || die "--detach needs setsid (util-linux)"
    # RUN_ID and the log path are pinned into the child's argv: without them the
    # child would mint its own timestamp run id, and the id printed here — the
    # one the manifest and the bucket keys use — would be a lie.
    # SC2094: $DRIVER_LOG appears twice, but only one of the two is a
    # redirection — the other is the literal argument that tells the child
    # which file that is. Nothing reads it.
    # shellcheck disable=SC2094
    LOOM_DRIVER_DETACHED=1 setsid nohup "${BASH_SOURCE[0]}" \
        "${ORIG_ARGV[@]}" --run-id "$RUN_ID" --log-file "$DRIVER_LOG" \
        </dev/null >>"$DRIVER_LOG" 2>&1 &
    log "detached: pid $!, log $DRIVER_LOG"
    log "resume with: ${BASH_SOURCE[0]} --resume-from $MANIFEST_PATH --fetch-only"
    exit 0
fi

# A detached child's stdout is already the durable log; teeing again would
# double every line into it.
if [ -z "${LOOM_DRIVER_DETACHED:-}" ]; then
    exec > >(tee -a "$DRIVER_LOG") 2>&1
fi

log "driver log     : $DRIVER_LOG"
log "argv           : ${ORIG_ARGV[*]}"

[ -n "$MODEL_IDENTITY" ] || die "--model-identity is required (see --help)"
[ -x "$TF_SAFE_APPLY" ] || die "tf-safe-apply.sh not found at $TF_SAFE_APPLY"
command -v aws >/dev/null || die "aws CLI not on PATH"
command -v python3 >/dev/null || die "python3 not on PATH"

# Resume mode uploads nothing and launches nothing, so the inputs that only the
# upload path reads must not be able to block a recovery. A models directory
# cleaned out after the run, or a config moved, is not a reason to leave
# results uncollected and a disk billing.
if [ "$RESUME" = true ]; then
    [ "$RUN_ID_SET" = true ] || die "--resume needs the launch's --run-id (or --resume-from a manifest that carries it)"
else
    [ -f "$CONFIG_PATH" ] || die "config not found: $CONFIG_PATH"
    [ -d "$MODELS_DIR" ] || die "models directory not found: $MODELS_DIR"
    command -v tar >/dev/null || die "tar not on PATH"

    GGUF_COUNT=$(find "$MODELS_DIR" -maxdepth 1 -name '*.gguf' | wc -l)
    [ "$GGUF_COUNT" -gt 0 ] || die "no .gguf files under $MODELS_DIR"
    if [ "$GGUF_COUNT" -gt 1 ] && [ -z "$GGUF_FILENAME" ]; then
        die "$GGUF_COUNT models under $MODELS_DIR — name one with --gguf"
    fi
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

log "mode            : $([ "$RESUME" = true ] && echo "resume (no upload, no launch)" || echo launch)"
log "run id          : $RUN_ID"
log "run manifest    : $MANIFEST_PATH"
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

TARBALL=""
if [ "$RESUME" = false ]; then
    TARBALL="$(mktemp -t loom-repo-XXXXXX.tar.gz)"
    push_cleanup "rm -f '$TARBALL'"
fi

# Resume mode did not launch this instance, so it does not yet know whether it
# owns it. Arming waits until the status marker proves the run is over;
# --teardown-anyway is the explicit override. A --fetch-only aimed at a run
# that is still in flight would otherwise destroy a live GPU mid-arm.
if [ "$RESUME" = true ] && [ "$TEARDOWN_ANYWAY" = false ]; then
    TEARDOWN_ARMED=false
fi

teardown() {
    if [ "$TEARDOWN_ARMED" != true ]; then
        log "teardown: NOT armed (resume mode, run not known to be finished);"
        log "          pass --teardown-anyway to remove the instance regardless"
        return 0
    fi
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

# Written before the first apply, so a run that dies at any point after this
# line is recoverable with a single --resume-from. The value that matters most
# is RUN_ID: it defaults to a timestamp minted inside this process and is
# otherwise recoverable only by reading the S3 key listing and guessing which
# prefix belonged to which driver.
if [ "$RESUME" = false ]; then
    write_manifest
    log "run manifest written: $MANIFEST_PATH"
fi

if [ "$RESUME" = true ]; then
    # --- Resume: phases 1-3 already happened, in a process that is gone -------
    # Nothing is uploaded and nothing is launched. Re-entering here rather than
    # in a second script keeps the wait and the fetch a single copy each.
    log "resume mode: skipping bucket apply, uploads and launch"
    # teardown applies against this root, so the backend still has to be
    # initialised — the same init the launch path runs at apply 1/2.
    "$TF_SAFE_APPLY" "$TF_DIR" init
else
    # --- 1. Bucket and instance role, without the GPU ------------------------
    # The driver has to upload before the instance boots, so the bucket is
    # applied on its own first.
    log "apply 1/2: artifacts bucket and instance role"
    "$TF_SAFE_APPLY" "$TF_DIR" init
    "$TF_SAFE_APPLY" "$TF_DIR" apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=false"

    # --- 2. Upload the repo, the config and the models -----------------------
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

    # --- 3. Launch -------------------------------------------------------------
    log "apply 2/2: launching the runner"
    "$TF_SAFE_APPLY" "$TF_DIR" apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=true"
fi

# --- 4. Wait for the marker --------------------------------------------------
if [ "$TIMEOUT_SECONDS" -eq 0 ]; then
    log "not waiting: reading s3://$BUCKET/$STATUS_KEY once, then fetching"
else
    log "waiting for s3://$BUCKET/$STATUS_KEY (every ${POLL_SECONDS}s, up to ${TIMEOUT_SECONDS}s)"
fi
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
    # One post-loop grace poll: with --fetch-only (TIMEOUT_SECONDS=0) the wait
    # loop above runs zero iterations by design — its condition is false before
    # the first check — so this is also the *only* read of the marker in that
    # mode, not just a suspend-safety net. Without it, --fetch-only would never
    # actually learn whether the run finished.
    RUN_STATUS=$(aws s3 cp "s3://$BUCKET/$STATUS_KEY" - 2>/dev/null | tr -d '[:space:]' || true)
    [ -n "$RUN_STATUS" ] && log "runner reported (post-deadline grace poll): $RUN_STATUS"
fi

# Resume mode held teardown back until the run was known to be over. It is over
# exactly when the status marker exists — the runner writes it last, after the
# results and the logs are already in the bucket.
if [ "$RESUME" = true ] && [ "$TEARDOWN_ARMED" = false ] && [ -n "$RUN_STATUS" ]; then
    log "resume: status marker reads $RUN_STATUS — the run is over, arming teardown"
    TEARDOWN_ARMED=true
fi

if [ -z "$RUN_STATUS" ]; then
    if [ "$RESUME" = true ]; then
        die "no status marker at s3://$BUCKET/$STATUS_KEY — the run may still be in
flight, so nothing was torn down. Whatever was already in the bucket has been
fetched into $DEST_DIR. Re-run this once the run finishes, or pass
--teardown-anyway if you are certain the instance should go."
    fi
    die "timed out after ${TIMEOUT_SECONDS}s with no status marker; see $DEST_DIR/logs"
fi
if [ "$RUN_STATUS" != "SUCCEEDED" ]; then
    die "the remote run reported $RUN_STATUS; see $DEST_DIR/logs/user-data.log"
fi

log "done: results in $DEST_DIR"
