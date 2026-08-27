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
# The driver is not, however, allowed to be the single point of failure it was
# on 2026-08-27, when the host suspended mid-poll and lost power while asleep:
# no signal reached the process, the EXIT trap never ran, and a finished run's
# results sat uncollected for seven hours behind a 150 GB disk that kept
# billing. Three things follow from that, and they are the invocation contract:
#
#   --detach    re-exec under setsid so a session or terminal tearing down its
#               process group cannot take the waiter with it.
#   the log     every run tees its own output to prototype/runs/logs/ from the
#               first line, so there is always a local record of what ran, what
#               run id it minted, and how far it got.
#   --resume    re-enter at the wait/fetch/teardown step against an existing
#               run, driven by the manifest the launch wrote next to that log:
#                 scripts/run-remote-experiment-gcp.sh \
#                   --resume-from prototype/runs/logs/driver-scale14.json \
#                   --fetch-only
#
# Authentication is deliberately tokenised rather than a key file or
# application-default credentials: every terraform invocation is preceded by a
# fresh `gcloud auth print-access-token`, exported as GOOGLE_OAUTH_ACCESS_TOKEN.
# Those tokens last an hour, which is shorter than a run — hence the refresh
# before each invocation rather than once at the top.
set -euo pipefail

# Kept verbatim so --detach can hand the same invocation to its own child, and
# so the durable log opens with exactly what was asked for.
ORIG_ARGV=("$@")

export PATH="$HOME/.local/bin:$PATH"

# An override that wins over the line above. That unconditional prepend of
# $HOME/.local/bin silently defeats a caller who has put stand-in binaries on
# PATH — which is exactly what an offline test harness does. On 2026-08-27 that
# cost a real `terraform` run, against real state, during what was meant to be a
# fully mocked test: the shimmed terraform was on PATH and lost to the real one.
# A driver whose tool resolution cannot be redirected cannot be tested; this is
# the seam that makes it testable. Not for production use.
if [ -n "${LOOM_DRIVER_BIN_OVERRIDE:-}" ]; then
    export PATH="$LOOM_DRIVER_BIN_OVERRIDE:$PATH"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TUI_LIB="${TUI_LIB:-$HOME/python-tui-lib}"

GCP_PROJECT_ID="${LOOM_GCP_PROJECT_ID:-project-19b81040-83b3-4483-a0d}"
GCP_REGION="us-central1"
GCP_ZONE="${LOOM_GCP_ZONE:-us-central1-a}"
TF_DIR="${LOOM_GCP_TF_DIR:-$REPO_ROOT/infrastructure/gcp/experiment}"
BUCKET="${LOOM_GCP_BUCKET:-loom-experiment-artifacts-19b81040}"
STATE_BUCKET="loom-tfstate-19b81040"
INSTANCE_SUFFIX=""
# Whether teardown may destroy the whole root, or only take the instance away.
# Default: instance-only. A blanket destroy is opt-in because this script's
# EXIT trap fires on any failure, including a driver killed mid-run, and a root
# that another run shares would then lose its bucket. Isolated roots
# (infrastructure/gcp/experiment-diversity) can be destroyed outright, but the
# safe default is the one that cannot cost somebody else a run.
TEARDOWN_SCOPE="instance"

MODELS_DIR="${LOOM_MODELS_DIR:-$HOME/loom-tools/models}"
CONFIG_PATH="$REPO_ROOT/prototype/experiment/phase_a.config.json"
MODEL_IDENTITY="${LOOM_MODEL_IDENTITY:-}"
GGUF_FILENAME=""
HARDWARE="g2-standard-4 L4 24GB"
MACHINE_TYPE="g2-standard-4"
REMOTE_OUTPUT_DIR="runs/phase-a-full"
DEST_DIR="$REPO_ROOT/prototype/runs/phase-a-full"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ID_SET=false
POLL_SECONDS=60
TIMEOUT_SECONDS=$((4 * 3600))
USE_SPOT=true
KEEP_BUCKET=false
DRY_RUN=false
SKIP_QUOTA_CHECK=false

# --- Survivability -----------------------------------------------------------
# The 2026-08-27 scale14 loss: the host suspended at 02:19:56 -06:00 while this
# driver sat in its poll loop and never resumed that boot (cold boot 11:27), so
# the process died with no signal at all and the EXIT trap never ran. The remote
# run SUCCEEDED at 05:03 into that dead window; its results sat uncollected for
# ~7 h and its 150 GB disk kept billing.
#
# Measured, not assumed: the cleanup stack's EXIT trap DOES fire on TERM, HUP
# and INT (see scripts/tests/test-driver-resume.sh, block 4). Only SIGKILL and
# host death skip it, and no trap can cover those. So the fix is not more
# trapping — it is a re-entry point plus enough recorded state to use it.
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
  --runlist FILE          Run every {config_key, output_dir, run_id} entry in
                          FILE sequentially on one instance, which self-deletes
                          when the runlist finishes. Each entry uploads its own
                          results incrementally under results/<entry-run_id>/
                          {runs,logs}/ and writes a status/<entry-run_id>.txt
                          marker as it completes; the aggregate results/$RUN_ID/
                          prefix receives only logs (the startup-script log),
                          never at any point receives arm data. Fetch therefore
                          walks the runlist and downloads each arm's own prefix
                          into DEST_DIR/<entry-run_id>/{,logs/} individually,
                          tolerating an arm that has not uploaded yet, and
                          prints a SUCCEEDED/FAILED/missing verdict per arm.
  --machine-type TYPE     Default: g2-standard-4
  --hardware STRING       Recorded hardware string.
                          Default: "g2-standard-4 L4 24GB"
  --on-demand             Use a standard VM rather than Spot (about 3.4x the
                          price, but not preemptible).
  --keep-bucket           Deprecated spelling of the default teardown scope
                          (--teardown-scope instance). Accepted so existing
                          invocations keep working.
  --tf-dir DIR            Terraform root to apply. Each root has its own
                          backend prefix, so this also chooses which state is
                          locked. Default: infrastructure/gcp/experiment.
                          Use infrastructure/gcp/experiment-diversity for a
                          run that must not contend with anything.
  --bucket NAME           Artifacts bucket. Must match the chosen root's
                          artifacts_bucket default, since the root manages it.
  --instance-suffix S     Distinguishes this run's instance from every other
                          runner in the project. Required whenever another run
                          may be in flight — two states managing one instance
                          name is the collision this option exists to stop.
  --teardown-scope WHICH  instance (default) removes only the GPU, leaving the
                          bucket and IAM standing; its objects expire after 7
                          days regardless. all destroys the whole root — only
                          safe on a root that shares no resource with another
                          run, and never the default, because this script's
                          EXIT trap fires on any failure including a kill.
  --poll-seconds N        Status poll interval. Default: 60
  --timeout-seconds N     Give up waiting after this long. Default: 14400 (4 h)
  --skip-quota-check      Skip the GPU quota preflight.
  --dry-run               Print what would happen; touch no GCP resource.
  -h, --help              Show this help and exit.

Surviving the driver's own death:
  --detach                Re-exec under `setsid nohup` in a new session, print
                          the pid and log path, and return. A terminal closing
                          or a session tearing down its process group then
                          cannot take the waiter with it. RUN_ID and the log
                          path are pinned into the child's argv, so the child
                          cannot mint a different run id than was announced.
  --log-file PATH         Where to tee this driver's own output. Default:
                          prototype/runs/logs/driver-<suffix-or-run-id>.log
                          (LOOM_DRIVER_LOG_DIR overrides the directory). The
                          log is opened before any GCP call, so even a
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
                            --resume-from prototype/runs/logs/driver-scale14.json --fetch-only
  --teardown-anyway       In resume mode, tear the instance down even though no
                          aggregate status marker says the run finished. Off by
                          default: without a marker the run may still be in
                          flight, and tearing it down would destroy a live GPU.

Cost: about $0.25/hour on Spot, and a full matrix has been sized at under two
hours, so a complete run is well under $1 including GCS and the boot disk.
While the $300 trial credits last, it is $0.
USAGE
}

# --- Run manifest ------------------------------------------------------------
# Written at launch, read by --resume-from. Its whole job is to carry the one
# value that made the 2026-08-27 recovery a manual archaeology exercise: RUN_ID,
# which defaults to a UTC timestamp minted inside this process and was therefore
# knowable only from a log that lived in /tmp and did not survive the reboot.
write_manifest() {
    local runlist_field="${RUNLIST_PATH:-}"
    mkdir -p "$(dirname "$MANIFEST_PATH")"
    LOOM_M_RUN_ID="$RUN_ID" \
    LOOM_M_BUCKET="$BUCKET" \
    LOOM_M_TF_DIR="$TF_DIR" \
    LOOM_M_DEST_DIR="$DEST_DIR" \
    LOOM_M_RUNLIST="$runlist_field" \
    LOOM_M_INSTANCE_SUFFIX="$INSTANCE_SUFFIX" \
    LOOM_M_MODEL_IDENTITY="$MODEL_IDENTITY" \
    LOOM_M_GGUF_FILENAME="$GGUF_FILENAME" \
    LOOM_M_HARDWARE="$HARDWARE" \
    LOOM_M_MACHINE_TYPE="$MACHINE_TYPE" \
    LOOM_M_USE_SPOT="$USE_SPOT" \
    LOOM_M_REMOTE_OUTPUT_DIR="$REMOTE_OUTPUT_DIR" \
    LOOM_M_TEARDOWN_SCOPE="$TEARDOWN_SCOPE" \
    LOOM_M_MODELS_DIR="$MODELS_DIR" \
    LOOM_M_DRIVER_LOG="$DRIVER_LOG" \
    LOOM_M_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    LOOM_M_PID="$$" \
    MANIFEST_PATH="$MANIFEST_PATH" \
    python3 -c '
import json, os
keys = ["run_id", "bucket", "tf_dir", "dest_dir", "runlist", "instance_suffix",
        "model_identity", "gguf_filename", "hardware", "machine_type",
        "use_spot", "remote_output_dir", "teardown_scope", "models_dir",
        "driver_log", "started_at", "pid"]
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
            runlist)           if [ -n "$value" ]; then RUNLIST_PATH="$value"; fi ;;
            instance_suffix)   INSTANCE_SUFFIX="$value" ;;
            model_identity)    MODEL_IDENTITY="$value" ;;
            gguf_filename)     GGUF_FILENAME="$value" ;;
            hardware)          HARDWARE="$value" ;;
            machine_type)      MACHINE_TYPE="$value" ;;
            use_spot)          USE_SPOT="$value" ;;
            remote_output_dir) REMOTE_OUTPUT_DIR="$value" ;;
            teardown_scope)    TEARDOWN_SCOPE="$value" ;;
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
        --remote-output-dir) REMOTE_OUTPUT_DIR="$2"; shift 2 ;;
        --run-id) RUN_ID="$2"; RUN_ID_SET=true; shift 2 ;;
        --machine-type) MACHINE_TYPE="$2"; shift 2 ;;
        --hardware) HARDWARE="$2"; shift 2 ;;
        --on-demand) USE_SPOT=false; shift ;;
        --keep-bucket) KEEP_BUCKET=true; TEARDOWN_SCOPE="instance"; shift ;;
        --tf-dir) TF_DIR="$2"; shift 2 ;;
        --bucket) BUCKET="$2"; shift 2 ;;
        --instance-suffix) INSTANCE_SUFFIX="$2"; shift 2 ;;
        --teardown-scope)
            case "$2" in
                instance|all) TEARDOWN_SCOPE="$2" ;;
                *) echo "--teardown-scope takes 'instance' or 'all', got '$2'" >&2; exit 2 ;;
            esac
            shift 2 ;;
        --runlist) RUNLIST_PATH="$2"; shift 2 ;;
        --poll-seconds) POLL_SECONDS="$2"; shift 2 ;;
        --timeout-seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
        --skip-quota-check) SKIP_QUOTA_CHECK=true; shift ;;
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
# The scale14 loss was undiagnosable rather than merely unlucky: the driver's
# only output went to a /tmp scratch file that the reboot erased, so afterwards
# there was no record that it had ever started, what run id it minted, or how
# far it got. A log under prototype/runs/logs/ survives a reboot and sits next
# to the results it was supposed to fetch.
RUN_TAG="${INSTANCE_SUFFIX:-$RUN_ID}"
MANIFEST_PATH="$LOG_DIR/driver-$RUN_TAG.json"
[ -n "$DRIVER_LOG" ] || DRIVER_LOG="$LOG_DIR/driver-$RUN_TAG.log"
mkdir -p "$LOG_DIR" "$(dirname "$DRIVER_LOG")"

# --- Detach, so a dying parent cannot take the waiter with it ----------------
# setsid puts the child in its own session and process group, out of reach of a
# terminal hang-up or a process-group kill aimed at whatever launched us. It is
# no defence at all against the host losing power, which is what actually
# happened on 2026-08-27 — that is what --resume is for.
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
command -v terraform >/dev/null || die "terraform not on PATH — run 'task setup'"
command -v gcloud >/dev/null || die "gcloud not on PATH — run 'task setup'"
command -v gsutil >/dev/null || die "gsutil not on PATH — run 'task setup'"
command -v python3 >/dev/null || die "python3 not on PATH"
# jq walks the runlist in both the upload path and the fetch path; it has always
# been a hard dependency of --runlist and has never been declared here.
if [ -n "${RUNLIST_PATH:-}" ]; then
    command -v jq >/dev/null || die "jq not on PATH — required by --runlist"
fi

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

# `instance_suffix` exists only on the roots that support concurrent runners
# (experiment-diversity, experiment-pair). Passing an undeclared variable is an
# error, so it is appended only when asked for, which keeps a plain
# ../experiment invocation byte-identical to what it was.
if [ -n "$INSTANCE_SUFFIX" ]; then
    TF_VARS+=(-var "instance_suffix=$INSTANCE_SUFFIX")
fi

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

log "mode            : $([ "$RESUME" = true ] && echo "resume (no upload, no launch)" || echo launch)"
log "run id          : $RUN_ID"
log "run manifest    : $MANIFEST_PATH"
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
if [ "$RESUME" = true ]; then
    log "quota preflight skipped (resume mode requests no GPU)"
elif [ "$SKIP_QUOTA_CHECK" = true ]; then
    log "quota preflight skipped by request"
else
    preflight_quota
fi
ensure_state_bucket

# --- Somebody else's runner is already up ------------------------------------
# GPU quota in this project is one accelerator, and every root here names its
# instance loom-experiment-runner[-suffix]. On 2026-08-23 two drivers started
# minutes apart against the same Terraform state; nothing was destroyed only
# because the second had not reached its launch apply yet. This is the check
# that would have stopped it at the preflight instead of at the apply: if a
# runner that is not this invocation's is already standing, abort before
# touching any state.
preflight_no_foreign_runner() {
    local ours="loom-experiment-runner"
    [ -n "$INSTANCE_SUFFIX" ] && ours="loom-experiment-runner-$INSTANCE_SUFFIX"
    local standing
    standing="$(gcloud compute instances list \
        --filter="name~^loom-experiment-runner AND name!=$ours" \
        --format='value(name,zone,status)' 2>/dev/null || true)"
    if [ -n "$standing" ]; then
        die "another experiment runner is already up:
$standing
GPU quota here is 1, and a second run would contend for it. Wait for that run
to finish, or pass a --instance-suffix and confirm quota has been raised."
    fi
    log "no foreign runner standing (ours would be $ours)"
}
preflight_no_foreign_runner

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
# owns it. Arming waits until the aggregate status marker proves the run is
# over; --teardown-anyway is the explicit override. A --fetch-only aimed at a
# run that is still in flight would otherwise destroy a live GPU mid-arm.
if [ "$RESUME" = true ] && [ "$TEARDOWN_ANYWAY" = false ]; then
    TEARDOWN_ARMED=false
fi

teardown() {
    if [ "$TEARDOWN_ARMED" != true ]; then
        log "teardown: NOT armed (resume mode, run not known to be finished);"
        log "          pass --teardown-anyway to remove the instance regardless"
        return 0
    fi
    # Scoped on purpose. This trap fires on *any* exit — a failed apply, a
    # Ctrl-C, a driver killed while another run is in flight — so what it is
    # allowed to reach matters more than what it usually reaches.
    #
    # `instance` (the default) applies launch_runner=false, which removes the
    # GPU (the only meaningful cost) and leaves the bucket and IAM bindings
    # standing. Bucket objects expire after 7 days by lifecycle rule, so the
    # residue is bounded without this trap having to be destructive.
    #
    # `all` is a full `terraform destroy` of the root and is only correct when
    # the root shares no resource with another run — see
    # infrastructure/gcp/experiment-diversity, which owns its bucket outright
    # for exactly this reason.
    if [ "$TEARDOWN_SCOPE" = "all" ]; then
        log "teardown: destroying the whole root ($TF_DIR)"
        tf destroy -auto-approve "${TF_VARS[@]}"
    else
        log "teardown: removing the runner instance, leaving the bucket standing"
        tf apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=false"
    fi
}
push_cleanup teardown

# Written before the first apply, so a run that dies at any point after this
# line is recoverable with a single --resume-from. The value that matters most
# is RUN_ID: it defaults to a timestamp minted inside this process, and on
# 2026-08-27 it was recoverable only by reading the GCS key listing and
# guessing which prefix belonged to which driver.
if [ "$RESUME" = false ]; then
    write_manifest
    log "run manifest written: $MANIFEST_PATH"
fi

if [ "$RESUME" = true ]; then
    # --- Resume: phases 1-3 already happened, in a process that is gone -------
    # Nothing is uploaded and nothing is launched. The point of re-entering here
    # rather than in a second script is that the wait, the per-arm fetch and the
    # teardown below stay a single copy: the fetch path's runlist walk was got
    # wrong once already (see the note above section 5) and a duplicate would
    # have re-acquired that bug on its own schedule.
    log "resume mode: skipping bucket apply, uploads and launch"
    # teardown applies against this root, so the backend still has to be
    # initialised — the same -reconfigure the launch path uses, and for the same
    # reason (a .terraform/ left by another root would offer to migrate state).
    tf init -input=false -reconfigure
    if [ -n "${RUNLIST_PATH:-}" ]; then
        [ -f "$RUNLIST_PATH" ] || die "runlist not found: $RUNLIST_PATH"
        TF_VARS+=(-var "runlist_key=runlist/$(basename "$RUNLIST_PATH")")
    fi
else
    # --- 1. Bucket and IAM bindings, without the GPU ------------------------
    # The driver has to upload before the instance boots, so the bucket is
    # applied on its own first.
    log "apply 1/2: artifacts bucket and IAM bindings"
    # -reconfigure, not a plain init: each root pins its own backend prefix in
    # its own backend.tf, and a .terraform/ left behind by a different root in
    # the same directory tree would otherwise have terraform offer to *migrate*
    # one run's state into another's prefix. Reconfiguring discards the cached
    # backend and takes the one the root actually declares.
    tf init -input=false -reconfigure
    tf apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=false"

    # --- 2. Upload the repo, the config and the models ----------------------
    log "packing the repo"
    # An arm's config resolves store_export relative to the config file, landing
    # on <repo>/<some .loom-store*>/export-resolver.json. Pack *every* store
    # variant's export that exists, so the path resolves on the instance
    # whichever arm is being run: the diversity-harvest plan alone builds three
    # of them (.loom-store-generated, -diverse, -sizematch) and a fourth is one
    # config file away. Naming one path here is what made a new arm need a
    # driver edit. Only the derived JSON travels — never a whole store dir.
    STORE_EXPORTS=()
    while IFS= read -r export_path; do
        STORE_EXPORTS+=("${export_path#"$REPO_ROOT/"}")
    done < <(find "$REPO_ROOT" -maxdepth 2 -path "$REPO_ROOT/.loom-store*" \
                 -name export-resolver.json | sort)
    if [ ${#STORE_EXPORTS[@]} -gt 0 ]; then
        log "  packing ${#STORE_EXPORTS[@]} store export(s): ${STORE_EXPORTS[*]}"
    fi
    tar -czf "$TARBALL" \
        -C "$REPO_ROOT" \
        --exclude='prototype/runs' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.git' \
        prototype Taskfile.yml ${STORE_EXPORTS+"${STORE_EXPORTS[@]}"}

    log "uploading the repo tarball ($(du -h "$TARBALL" | cut -f1))"
    gsutil -q cp "$TARBALL" "gs://$BUCKET/repo/repo.tar.gz"

    log "uploading the run config"
    gsutil -q cp "$CONFIG_PATH" "gs://$BUCKET/config/run.config.json"

    # Runlist mode (--runlist FILE): the instance runs every {config_key,
    # output_dir, run_id} entry sequentially and self-deletes at the end, so
    # this driver's own lifetime stops mattering once apply 2/2 returns — built
    # 2026-08-24 so a multi-arm sweep can finish with the operator offline. Each
    # entry's config_key is expected to name prototype/experiment/<basename>.
    if [ -n "${RUNLIST_PATH:-}" ]; then
        [ -f "$RUNLIST_PATH" ] || die "runlist not found: $RUNLIST_PATH"
        RUNLIST_KEY="runlist/$(basename "$RUNLIST_PATH")"
        log "uploading runlist $RUNLIST_KEY and its configs"
        gsutil -q cp "$RUNLIST_PATH" "gs://$BUCKET/$RUNLIST_KEY"
        while IFS= read -r cfg_key; do
            local_cfg="$REPO_ROOT/prototype/experiment/$(basename "$cfg_key")"
            [ -f "$local_cfg" ] || die "runlist names $cfg_key but $local_cfg does not exist"
            gsutil -q cp "$local_cfg" "gs://$BUCKET/$cfg_key"
        done < <(jq -r '.[].config_key' "$RUNLIST_PATH")
        TF_VARS+=(-var "runlist_key=$RUNLIST_KEY")
    fi

    log "uploading models from $MODELS_DIR (skipping anything already in the bucket)"
    # A `gsutil stat` existence check up front means a re-run with --keep-bucket
    # (or a second arm sharing the same bucket) touches the network at all only
    # for models it does not already have — cheaper and faster than relying on
    # `cp -n` alone to discover that server-side. The upload itself is still
    # wrapped in a bounded retry: a stalled multi-GB transfer previously hung
    # for 39 minutes with zero progress and no error (2026-08-23), silently
    # eating a run's wall clock. `timeout` turns a silent hang into a loud,
    # bounded retry instead.
    while IFS= read -r gguf; do
        name="$(basename "$gguf")"
        if gsutil -q stat "gs://$BUCKET/models/$name" >/dev/null 2>&1; then
            log "  $name (already in bucket, skipping)"
            continue
        fi
        log "  $name"
        # `gcloud storage cp` rather than `gsutil cp`: parallel composite upload
        # (multi-stream, much faster on multi-GB files) and a persistent
        # resumable tracker, so a killed attempt continues where it stopped
        # instead of restarting from byte 0 — the 30-min-cap-with-restart
        # combination killed a ~29.5-min 3B upload three times in a row at ~99%
        # (2026-08-23). The per-attempt timeout is sized for the largest model
        # at a slow uplink (4.7 GB at ~1 MB/s ≈ 80 min), not the average case.
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

    # --- 3. Launch ----------------------------------------------------------
    log "apply 2/2: launching the runner"
    tf apply -auto-approve "${TF_VARS[@]}" -var "launch_runner=true"
fi

# --- 4. Wait for the marker --------------------------------------------------
if [ "$TIMEOUT_SECONDS" -eq 0 ]; then
    log "not waiting: reading gs://$BUCKET/$STATUS_KEY once, then fetching"
else
    log "waiting for gs://$BUCKET/$STATUS_KEY (every ${POLL_SECONDS}s, up to ${TIMEOUT_SECONDS}s)"
fi
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
if [ -n "${RUNLIST_PATH:-}" ]; then
    # Runlist mode uploads incrementally per arm — results/<entry-run_id>/
    # {runs,logs}/ and a status/<entry-run_id>.txt marker — and the aggregate
    # results/$RUN_ID/ prefix never receives arm data, only logs at runlist
    # completion. Fetching only the aggregate prefix (the non-runlist path
    # below) silently downloads nothing for every arm; that gap was found by
    # hand twice on 2026-08-25/26 and rescued with an ad hoc rsync per arm.
    # Walk the runlist instead and fetch each arm's own prefix.
    log "runlist mode: fetching each arm's results individually"
    ARM_SUMMARY=()
    while IFS= read -r arm_run_id; do
        arm_dest="$DEST_DIR/$arm_run_id"
        mkdir -p "$arm_dest/logs"
        if gsutil -q ls "gs://$BUCKET/results/$arm_run_id/runs/" >/dev/null 2>&1; then
            log "  $arm_run_id: runs/ found, downloading"
            gsutil -q -m rsync -r "gs://$BUCKET/results/$arm_run_id/runs/" "$arm_dest" || true
        else
            log "  $arm_run_id: no runs/ prefix in the bucket (not uploaded, or arm never ran)"
        fi
        if gsutil -q ls "gs://$BUCKET/results/$arm_run_id/logs/" >/dev/null 2>&1; then
            gsutil -q -m rsync -r "gs://$BUCKET/results/$arm_run_id/logs/" "$arm_dest/logs" || true
        else
            log "  $arm_run_id: no logs/ prefix in the bucket"
        fi
        arm_status=$(gsutil -q cat "gs://$BUCKET/status/$arm_run_id.txt" 2>/dev/null | tr -d '[:space:]' || true)
        [ -z "$arm_status" ] && arm_status="missing"
        ARM_SUMMARY+=("  $arm_run_id: $arm_status")
    done < <(jq -r '.[].run_id' "$RUNLIST_PATH")
    # The aggregate prefix still carries the startup-script log even in
    # runlist mode, so keep fetching it into the top-level logs dir.
    log "downloading aggregate logs (startup-script log) into $DEST_DIR/logs"
    gsutil -q -m rsync -r "gs://$BUCKET/${RESULTS_PREFIX}logs/" "$DEST_DIR/logs" || true
    log "per-arm status:"
    printf '%s\n' "${ARM_SUMMARY[@]}"
else
    log "downloading gs://$BUCKET/${RESULTS_PREFIX}runs/ into $DEST_DIR"
    gsutil -q -m rsync -r "gs://$BUCKET/${RESULTS_PREFIX}runs/" "$DEST_DIR" || true
    log "downloading logs into $DEST_DIR/logs"
    gsutil -q -m rsync -r "gs://$BUCKET/${RESULTS_PREFIX}logs/" "$DEST_DIR/logs" || true
fi

if [ -z "$RUN_STATUS" ]; then
    # One post-loop grace poll: a laptop suspend freezes this process while the
    # wall clock runs on, so the deadline can pass without a single live poll
    # in hours. Seen 2026-08-14: suspend 08:34–12:47 UTC swallowed a run that
    # had SUCCEEDED at 11:14; the loop woke already past deadline and died
    # without looking. The marker check is cheap; look once more before dying.
    RUN_STATUS=$(gsutil -q cat "gs://$BUCKET/$STATUS_KEY" 2>/dev/null | tr -d '[:space:]' || true)
    [ -n "$RUN_STATUS" ] && log "runner reported (post-deadline grace poll): $RUN_STATUS"
fi

# Resume mode held teardown back until the run was known to be over. It is over
# exactly when the aggregate marker exists — the runner writes it last, after
# the results and the logs are already in the bucket.
if [ "$RESUME" = true ] && [ "$TEARDOWN_ARMED" = false ] && [ -n "$RUN_STATUS" ]; then
    log "resume: aggregate marker reads $RUN_STATUS — the run is over, arming teardown"
    TEARDOWN_ARMED=true
fi

if [ -z "$RUN_STATUS" ]; then
    if [ "$RESUME" = true ]; then
        die "no aggregate status marker at gs://$BUCKET/$STATUS_KEY — the run may still be
in flight, so nothing was torn down. Whatever was already in the bucket has been
fetched into $DEST_DIR. Re-run this once the run finishes, or pass
--teardown-anyway if you are certain the instance should go."
    fi
    die "timed out after ${TIMEOUT_SECONDS}s with no status marker; see $DEST_DIR/logs"
fi
if [ "$RUN_STATUS" != "SUCCEEDED" ]; then
    die "the remote run reported $RUN_STATUS; see $DEST_DIR/logs/startup-script.log"
fi

log "done: results in $DEST_DIR"
