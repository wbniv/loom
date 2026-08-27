#!/usr/bin/env bash
set -euo pipefail
# test-driver-resume.sh — regression guard for the 2026-08-27 scale14 loss.
#
# What was lost, and why: the driver
# (scripts/run-remote-experiment-gcp.sh) was sitting in its 60 s poll loop when
# the laptop suspended at 02:19:56 -06:00 and lost power while asleep. Nothing
# signalled the process, so bash never ran the EXIT trap that push_cleanup hangs
# teardown off. The remote run SUCCEEDED at 05:03 into that dead window; its two
# arms' results sat uncollected in GCS for ~7 h, its instance was never removed,
# and its 150 GB disk kept billing. There was no local driver log to diagnose
# any of it from, because the only output went to a /tmp scratch file the reboot
# erased.
#
# Four blocks, no GCP and no network. `gsutil`, `gcloud` and `terraform` are
# shimmed onto PATH in front of a directory that *is* the bucket.
#
#   1. Reproduce  — kill -9 the driver mid-poll; assert no teardown apply ever
#                   happened (the bug), and that the durable log and the run
#                   manifest DID (the fix's precondition).
#   2. Recover    — put the bucket into the state the real one was in at 05:03
#                   and assert --resume-from … --fetch-only brings both arms
#                   home and tears the instance down exactly once.
#   3. Guard      — with no aggregate marker, assert --fetch-only refuses to
#                   tear down, and says so, and exits non-zero.
#   4. Trap claim — assert the cleanup stack's EXIT trap fires on TERM/HUP/INT
#                   and not on KILL, which is the measurement the fix's design
#                   rests on. If a future bash changes that, this fails loudly
#                   instead of the design note quietly rotting.

usage() {
    cat <<'USAGE'
Usage: scripts/tests/test-driver-resume.sh [--keep]

Regression guard for the 2026-08-27 scale14 driver loss. Runs offline against
shimmed gsutil/gcloud/terraform; creates and destroys its own scratch tree.

  --keep        Leave the scratch tree in place and print its path.
  -h, --help    Show this help and exit.
USAGE
}

KEEP=false
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --keep) KEEP=true; shift ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DRIVER="$REPO_ROOT/scripts/run-remote-experiment-gcp.sh"
[ -f "$DRIVER" ] || { echo "driver not found: $DRIVER" >&2; exit 1; }

TMP="$(mktemp -d -t loom-driver-test-XXXXXX)"
if [ "$KEEP" = false ]; then
    trap 'rm -rf "$TMP"' EXIT
else
    trap 'echo "scratch tree kept at $TMP"' EXIT
fi

BUCKET=test-artifacts-bucket
MOCK_GCS="$TMP/gcs"
CALLS="$TMP/terraform-calls.log"
# A throwaway Terraform root, NOT a real one. This is the load-bearing safety
# property of this harness, learned the expensive way on 2026-08-27: an earlier
# draft pointed --tf-dir at infrastructure/gcp/experiment-diversity, the real
# terraform won the PATH race against the shim, and a real `apply` with the
# test's --bucket destroyed the real artifacts bucket and its IAM bindings.
# Even if every shim were bypassed, an empty directory has no backend, no state
# and no resources, so the worst case is a loud "no configuration files".
TFROOT="$TMP/tfroot"
mkdir -p "$MOCK_GCS/$BUCKET/status" "$MOCK_GCS/loom-tfstate-19b81040" \
         "$TMP/bin" "$TMP/models" "$TMP/logdir" "$TFROOT"
: > "$CALLS"

FAILURES=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
block() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# --- Shims -------------------------------------------------------------------
cat > "$TMP/bin/gsutil" <<'SHIM'
#!/usr/bin/env bash
set -uo pipefail
topath() { printf '%s/%s' "$MOCK_GCS" "${1#gs://}"; }
bucket_probe=false
args=()
for a in "$@"; do
    case "$a" in
        -q|-m|-r) ;;
        -b) bucket_probe=true ;;
        *) args+=("$a") ;;
    esac
done
cmd="${args[0]:-}"
rest=("${args[@]:1}")
case "$cmd" in
    ls)
        target="${rest[${#rest[@]}-1]}"
        p="$(topath "$target")"
        if [ "$bucket_probe" = true ]; then mkdir -p "$p"; exit 0; fi
        if [ -d "$p" ]; then
            out="$(find "$p" -mindepth 1 2>/dev/null || true)"
            [ -n "$out" ] || exit 1
            printf '%s\n' "$out"
            exit 0
        fi
        [ -e "$p" ] && { printf '%s\n' "$target"; exit 0; }
        exit 1 ;;
    cat)
        p="$(topath "${rest[0]}")"
        [ -f "$p" ] || exit 1
        cat "$p" ;;
    stat)
        p="$(topath "${rest[0]}")"
        [ -f "$p" ] || exit 1 ;;
    rm)
        p="$(topath "${rest[0]}")"
        [ -e "$p" ] || exit 1
        rm -f "$p" ;;
    cp)
        src="${rest[0]}"; dst="${rest[1]}"
        sp="$src"; dp="$dst"
        case "$src" in gs://*) sp="$(topath "$src")" ;; esac
        case "$dst" in gs://*) dp="$(topath "$dst")" ;; esac
        mkdir -p "$(dirname "$dp")"
        cp "$sp" "$dp" ;;
    rsync)
        src="${rest[0]}"; dst="${rest[1]}"
        sp="$src"; dp="$dst"
        case "$src" in gs://*) sp="$(topath "$src")" ;; esac
        case "$dst" in gs://*) dp="$(topath "$dst")" ;; esac
        [ -d "$sp" ] || exit 1
        mkdir -p "$dp"
        cp -a "$sp/." "$dp/" ;;
    *) exit 0 ;;
esac
SHIM

cat > "$TMP/bin/gcloud" <<'SHIM'
#!/usr/bin/env bash
set -uo pipefail
sub="${1:-} ${2:-}"
case "$sub" in
    "auth print-access-token") echo fake-access-token ;;
    "auth list") echo "tester@example.invalid" ;;
    "compute instances") ;;                    # no foreign runner standing
    "compute project-info"|"compute regions") echo '{"quotas":[]}' ;;
    "storage cp")
        args=()
        for a in "$@"; do
            case "$a" in --*) ;; *) args+=("$a") ;; esac
        done
        src="${args[2]}"; dst="${args[3]}"
        dp="$dst"
        case "$dst" in gs://*) dp="$MOCK_GCS/${dst#gs://}" ;; esac
        mkdir -p "$(dirname "$dp")"
        cp "$src" "$dp" ;;
    *) ;;
esac
SHIM

cat > "$TMP/bin/terraform" <<'SHIM'
#!/usr/bin/env bash
set -uo pipefail
printf '%s\n' "$*" >> "$TERRAFORM_CALLS"
SHIM

chmod +x "$TMP/bin/gsutil" "$TMP/bin/gcloud" "$TMP/bin/terraform"

# --- Fixtures ----------------------------------------------------------------
# Two arms named as the incident's were, over configs that exist in this repo:
# the driver refuses a runlist whose config_key has no local file.
cat > "$TMP/runlist.json" <<'JSON'
[
  { "config_key": "config/decomp-whole.config.json",
    "output_dir": "runs/scale14-b0", "run_id": "scale14-b0" },
  { "config_key": "config/decomp-holes.config.json",
    "output_dir": "runs/scale14-b2", "run_id": "scale14-b2" }
]
JSON
echo '{}' > "$TMP/run.config.json"
echo "not a real model" > "$TMP/models/fake-14b.gguf"

RUN_ID=testrun-20260827
MANIFEST="$TMP/logdir/driver-scale14.json"
DRIVER_LOG="$TMP/logdir/driver-scale14.log"

export PATH="$TMP/bin:$PATH"
export MOCK_GCS TERRAFORM_CALLS="$CALLS"
export LOOM_DRIVER_LOG_DIR="$TMP/logdir"
# The driver prepends $HOME/.local/bin to PATH itself, which outranks the line
# above; LOOM_DRIVER_BIN_OVERRIDE is the seam that outranks *that*.
export LOOM_DRIVER_BIN_OVERRIDE="$TMP/bin"

# Refuse to run at all unless the shims actually win. Mirrors the driver's own
# two PATH lines rather than trusting them.
resolved="$(PATH="$LOOM_DRIVER_BIN_OVERRIDE:$HOME/.local/bin:$PATH" command -v terraform)"
if [ "$resolved" != "$TMP/bin/terraform" ]; then
    echo "refusing to run: terraform resolves to $resolved, not the shim at $TMP/bin/terraform" >&2
    echo "the driver would talk to real infrastructure" >&2
    exit 1
fi

driver_args=(
    --model-identity "Qwen2.5-Coder-14B-Instruct GGUF Q4_K_M"
    --models-dir "$TMP/models"
    --gguf fake-14b.gguf
    --config "$TMP/run.config.json"
    --runlist "$TMP/runlist.json"
    --bucket "$BUCKET"
    --tf-dir "$TFROOT"
    --instance-suffix scale14
    --run-id "$RUN_ID"
    --dest "$TMP/dest-launch"
    --skip-quota-check
    --poll-seconds 1
)

count_teardown_applies() {
    grep -c -- '-var launch_runner=false' "$CALLS" 2>/dev/null || true
}

# --- Block 1: reproduce the loss ---------------------------------------------
block "1. SIGKILL mid-poll skips the EXIT trap (the 2026-08-27 failure)"

bash "$DRIVER" "${driver_args[@]}" --timeout-seconds 600 >"$TMP/block1.out" 2>&1 &
driver_pid=$!

reached_wait=false
for _ in $(seq 1 200); do
    if grep -q 'still running' "$TMP/block1.out" 2>/dev/null; then
        reached_wait=true
        break
    fi
    kill -0 "$driver_pid" 2>/dev/null || break
    sleep 0.2
done

if [ "$reached_wait" = true ]; then
    pass "driver reached the poll loop"
else
    fail "driver never reached the poll loop; output follows"
    sed 's/^/      /' "$TMP/block1.out" | tail -25
fi

applies_before_kill="$(count_teardown_applies)"
kill -9 "$driver_pid" 2>/dev/null || true
wait "$driver_pid" 2>/dev/null || true

# apply 1/2 is itself a launch_runner=false apply, so "no teardown" is "the
# count did not grow past the one the launch path always makes".
if [ "$(count_teardown_applies)" -eq 1 ] && [ "$applies_before_kill" -eq 1 ]; then
    pass "SIGKILL ran no teardown apply — the EXIT trap was skipped, as in the incident"
else
    fail "expected exactly 1 launch_runner=false apply (apply 1/2), saw $(count_teardown_applies)"
fi

if grep -q 'launch_runner=true' "$CALLS"; then
    pass "the instance had been launched, so it was left standing"
else
    fail "the launch apply never happened; the reproduction is not faithful"
fi

# The part that did not exist on 2026-08-27, and without which none of this was
# diagnosable: a local log and a manifest that outlive the process.
if [ -s "$DRIVER_LOG" ] && grep -q "driver log" "$DRIVER_LOG" && grep -q "$RUN_ID" "$DRIVER_LOG"; then
    pass "durable driver log survives the kill and names the run id"
else
    fail "no usable driver log at $DRIVER_LOG"
fi

if [ -f "$MANIFEST" ] && [ "$(jq -r .run_id "$MANIFEST")" = "$RUN_ID" ]; then
    pass "run manifest survives the kill and carries the run id"
else
    fail "no usable run manifest at $MANIFEST"
fi

# --- Block 2: recover ---------------------------------------------------------
block "2. --resume-from … --fetch-only recovers everything the kill left behind"

# The bucket as it stood at 05:03:34Z on 2026-08-27: both arms uploaded, both
# per-arm markers SUCCEEDED, aggregate marker written last.
for arm in scale14-b0 scale14-b2; do
    mkdir -p "$MOCK_GCS/$BUCKET/results/$arm/runs" "$MOCK_GCS/$BUCKET/results/$arm/logs"
    echo "{\"arm\": \"$arm\"}" > "$MOCK_GCS/$BUCKET/results/$arm/runs/records.jsonl"
    echo "log for $arm" > "$MOCK_GCS/$BUCKET/results/$arm/logs/startup-script.log"
    echo SUCCEEDED > "$MOCK_GCS/$BUCKET/status/$arm.txt"
done
mkdir -p "$MOCK_GCS/$BUCKET/results/$RUN_ID/logs"
echo "aggregate runner log" > "$MOCK_GCS/$BUCKET/results/$RUN_ID/logs/startup-script.log"
echo SUCCEEDED > "$MOCK_GCS/$BUCKET/status/$RUN_ID.txt"

applies_before_resume="$(count_teardown_applies)"
resume_rc=0
bash "$DRIVER" --resume-from "$MANIFEST" --fetch-only --dest "$TMP/dest-resume" \
    >"$TMP/block2.out" 2>&1 || resume_rc=$?

if [ "$resume_rc" -eq 0 ]; then
    pass "resume exited 0"
else
    fail "resume exited $resume_rc; output follows"
    sed 's/^/      /' "$TMP/block2.out" | tail -25
fi

for arm in scale14-b0 scale14-b2; do
    if [ -f "$TMP/dest-resume/$arm/records.jsonl" ] \
       && [ -f "$TMP/dest-resume/$arm/logs/startup-script.log" ]; then
        pass "$arm results and logs landed in --dest"
    else
        fail "$arm was not fetched into $TMP/dest-resume/$arm"
    fi
done

if [ -f "$TMP/dest-resume/logs/startup-script.log" ]; then
    pass "aggregate startup-script log fetched"
else
    fail "aggregate startup-script log not fetched"
fi

if grep -q 'scale14-b0: SUCCEEDED' "$TMP/block2.out" \
   && grep -q 'scale14-b2: SUCCEEDED' "$TMP/block2.out"; then
    pass "per-arm verdicts printed"
else
    fail "per-arm verdicts missing from the output"
fi

if [ "$(count_teardown_applies)" -eq $((applies_before_resume + 1)) ]; then
    pass "teardown applied launch_runner=false exactly once"
else
    fail "expected one new teardown apply, count went $applies_before_resume -> $(count_teardown_applies)"
fi

if [ ! -f "$MOCK_GCS/$BUCKET/repo/repo.tar.gz" ] || \
   [ "$(find "$MOCK_GCS/$BUCKET/models" -name '*.gguf' | wc -l)" -eq 1 ]; then
    pass "resume uploaded nothing new"
else
    fail "resume mode touched the upload path"
fi

# --- Block 3: the guard against tearing down a live run ----------------------
block "3. --fetch-only refuses to tear down a run that may still be in flight"

rm -f "$MOCK_GCS/$BUCKET/status/$RUN_ID.txt"
applies_before_guard="$(count_teardown_applies)"
guard_rc=0
bash "$DRIVER" --resume-from "$MANIFEST" --fetch-only --dest "$TMP/dest-guard" \
    >"$TMP/block3.out" 2>&1 || guard_rc=$?

if [ "$guard_rc" -ne 0 ]; then
    pass "exited non-zero ($guard_rc) with no aggregate marker"
else
    fail "exited 0 despite having no aggregate marker"
fi

if [ "$(count_teardown_applies)" -eq "$applies_before_guard" ]; then
    pass "no teardown apply — a live GPU would have survived this"
else
    fail "teardown ran without a marker; a live run would have been destroyed"
fi

if grep -q 'NOT armed' "$TMP/block3.out"; then
    pass "said plainly that teardown was not armed"
else
    fail "no 'NOT armed' explanation in the output"
fi

if [ -f "$TMP/dest-guard/scale14-b0/records.jsonl" ]; then
    pass "still fetched what the bucket did have"
else
    fail "refused the teardown and also skipped the fetch"
fi

# --- Block 4: the measurement the design rests on ----------------------------
block "4. cleanup-stack's EXIT trap fires on TERM/HUP/INT, not on KILL"

cat > "$TMP/victim.sh" <<'VICTIM'
#!/usr/bin/env bash
set -euo pipefail
source "${TUI_LIB:-$HOME/python-tui-lib}/scripts/cleanup-stack.sh"
push_cleanup "echo TRAP_RAN >> $1"
echo started >> "$1"
sleep 30
VICTIM
chmod +x "$TMP/victim.sh"

probe_signal() {
    local sig="$1" f="$TMP/probe-$1.txt" pid
    : > "$f"
    bash "$TMP/victim.sh" "$f" &
    pid=$!
    for _ in $(seq 1 100); do
        grep -q started "$f" 2>/dev/null && break
        sleep 0.1
    done
    kill -"$sig" "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    grep -c TRAP_RAN "$f" 2>/dev/null || true
}

for sig in TERM HUP INT; do
    if [ "$(probe_signal "$sig")" -ge 1 ]; then
        pass "SIG$sig runs the cleanup stack (so no extra trap is needed for it)"
    else
        fail "SIG$sig did NOT run the cleanup stack — the design note is now wrong"
    fi
done

if [ "$(probe_signal KILL)" -eq 0 ]; then
    pass "SIGKILL does not run the cleanup stack — which is why --resume exists"
else
    fail "SIGKILL ran the cleanup stack, which is not possible; the probe is broken"
fi

# --- Block 5: --detach really leaves the caller's session --------------------
block "5. --detach puts the waiter in its own session, with the run id it announced"

detach_out="$TMP/block5.out"
bash "$DRIVER" "${driver_args[@]}" --timeout-seconds 600 \
    --instance-suffix detachtest --run-id detachrun --detach \
    >"$detach_out" 2>&1
detach_rc=$?

if [ "$detach_rc" -eq 0 ] && grep -q 'detached: pid' "$detach_out"; then
    pass "parent returned immediately and named the child's pid and log"
else
    fail "parent did not detach cleanly (rc=$detach_rc)"
    sed 's/^/      /' "$detach_out"
fi

if grep -q -- '--resume-from .*driver-detachtest.json --fetch-only' "$detach_out"; then
    pass "parent printed the exact resume command for this run"
else
    fail "parent did not print a usable resume command"
fi

detach_log="$TMP/logdir/driver-detachtest.log"
for _ in $(seq 1 200); do
    grep -q 'still running' "$detach_log" 2>/dev/null && break
    sleep 0.2
done

# The child must be using the run id the parent announced, not a fresh
# timestamp of its own — otherwise the manifest, the bucket keys and the message
# the operator was given all disagree.
if grep -q 'run id          : detachrun' "$detach_log" 2>/dev/null; then
    pass "child kept the announced run id rather than minting its own"
else
    fail "child's run id does not match what the parent announced"
fi

child_pid="$(pgrep -f -- '--log-file .*driver-detachtest\.log' | head -1 || true)"
if [ -n "$child_pid" ]; then
    child_sid="$(ps -o sid= -p "$child_pid" 2>/dev/null | tr -d ' ' || true)"
    own_sid="$(ps -o sid= -p $$ 2>/dev/null | tr -d ' ' || true)"
    if [ -n "$child_sid" ] && [ -n "$own_sid" ] && [ "$child_sid" != "$own_sid" ]; then
        pass "child session $child_sid differs from this shell's $own_sid — a process-group kill here cannot reach it"
    else
        fail "child session ($child_sid) is not separate from ours ($own_sid)"
    fi
    kill -9 "$child_pid" 2>/dev/null || true
else
    fail "could not find the detached child to check its session"
fi

# --- Verdict -----------------------------------------------------------------
printf '\n'
if [ "$FAILURES" -eq 0 ]; then
    printf '\033[32mall checks passed\033[0m\n'
    exit 0
fi
printf '\033[31m%d check(s) failed\033[0m\n' "$FAILURES"
exit 1
