#!/usr/bin/env bash
set -euo pipefail
# test-driver-resume-aws.sh — regression guard for scripts/run-remote-experiment.sh,
# the AWS sibling of the GCP driver fixed on 2026-08-27
# (docs/plans/2026-08-27-driver-survivability-and-resume.md). Same shape, same
# exposure: a host dying mid-poll loses fetch AND teardown with no local log.
# That plan's §8 follow-up named this file explicitly as unfinished business;
# this is it.
#
# Five blocks, no AWS and no network. `aws` and `terraform` are shimmed onto
# PATH in front of a directory that *is* the bucket. Unlike the GCP driver,
# this one has no unconditional PATH prepend of its own (no
# `export PATH="$HOME/.local/bin:$PATH"`), so a plain PATH shim already wins —
# no LOOM_DRIVER_BIN_OVERRIDE-style seam is needed here. What *is* needed,
# learned the expensive way on the GCP side (plan §7: an earlier harness draft
# pointed --tf-dir at a real root and a real `terraform apply` destroyed a real
# bucket), is a throwaway Terraform root: LOOM_AWS_TF_DIR points this driver at
# an empty scratch directory that has no backend, no state and no resources,
# so even a total shim bypass finds nothing to touch.
#
#   1. Reproduce  — kill -9 the driver mid-poll; assert no teardown apply ever
#                   happened (the bug), and that the durable log and the run
#                   manifest DID (the fix's precondition).
#   2. Recover    — put the bucket into a finished-run state and assert
#                   --resume-from … --fetch-only brings the results home and
#                   tears the instance down exactly once.
#   3. Guard      — with no status marker, assert --fetch-only refuses to tear
#                   down, and says so, and exits non-zero.
#   4. Trap claim — assert the cleanup stack's EXIT trap fires on TERM/HUP/INT
#                   and not on KILL, the same measurement the GCP fix's design
#                   rests on (it is a property of cleanup-stack.sh, not of
#                   either driver, so the claim is re-checked here rather than
#                   trusted from the other test).
#   5. Detach     — assert --detach returns immediately, the child keeps the
#                   announced run id, and the child's session differs from the
#                   caller's.

usage() {
    cat <<'USAGE'
Usage: scripts/tests/test-driver-resume-aws.sh [--keep]

Regression guard for the AWS driver's survivability/resume path. Runs offline
against shimmed aws/terraform; creates and destroys its own scratch tree.

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
DRIVER="$REPO_ROOT/scripts/run-remote-experiment.sh"
[ -f "$DRIVER" ] || { echo "driver not found: $DRIVER" >&2; exit 1; }

TMP="$(mktemp -d -t loom-driver-aws-test-XXXXXX)"
if [ "$KEEP" = false ]; then
    trap 'rm -rf "$TMP"' EXIT
else
    trap 'echo "scratch tree kept at $TMP"' EXIT
fi

BUCKET=test-artifacts-bucket
MOCK_S3="$TMP/s3"
CALLS="$TMP/terraform-calls.log"
# A throwaway Terraform root, NOT a real one — the load-bearing safety property
# here, learned on the GCP side (plan §7). Even if every shim were bypassed, an
# empty directory has no backend, no state and no resources: the worst case is
# a loud "no configuration files", not a destroyed bucket.
TFROOT="$TMP/tfroot"
mkdir -p "$MOCK_S3/$BUCKET/status" "$TMP/bin" "$TMP/models" "$TMP/logdir" "$TFROOT"
: > "$CALLS"

FAILURES=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
block() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# --- Shims -------------------------------------------------------------------
cat > "$TMP/bin/aws" <<'SHIM'
#!/usr/bin/env bash
set -uo pipefail
topath() { printf '%s/%s' "$MOCK_S3" "${1#s3://}"; }

svc="${1:-}"; shift || true
[ "$svc" = "s3" ] || exit 0
sub="${1:-}"; shift || true

case "$sub" in
    cp)
        pos=()
        for a in "$@"; do
            case "$a" in --*) ;; *) pos+=("$a") ;; esac
        done
        src="${pos[0]:-}"; dst="${pos[1]:-}"
        sp="$src"
        case "$src" in s3://*) sp="$(topath "$src")" ;; esac
        if [ "$dst" = "-" ]; then
            [ -f "$sp" ] || exit 1
            cat "$sp"
            exit 0
        fi
        dp="$dst"
        case "$dst" in s3://*) dp="$(topath "$dst")" ;; esac
        [ -f "$sp" ] || exit 1
        mkdir -p "$(dirname "$dp")"
        cp "$sp" "$dp"
        ;;
    sync)
        pos=(); include_only=false; pattern="*"; prev=""
        for a in "$@"; do
            case "$prev" in
                --exclude) prev=""; continue ;;
                --include) pattern="$a"; include_only=true; prev=""; continue ;;
            esac
            case "$a" in
                --exclude) prev="--exclude" ;;
                --include) prev="--include" ;;
                --*) ;;
                *) pos+=("$a") ;;
            esac
        done
        src="${pos[0]:-}"; dst="${pos[1]:-}"
        sp="$src"
        case "$src" in s3://*) sp="$(topath "$src")" ;; esac
        dp="$dst"
        case "$dst" in s3://*) dp="$(topath "$dst")" ;; esac
        [ -d "$sp" ] || exit 1
        mkdir -p "$dp"
        if [ "$include_only" = true ]; then
            find "$sp" -maxdepth 1 -name "$pattern" -exec cp -t "$dp" {} \;
        else
            cp -a "$sp/." "$dp/"
        fi
        ;;
    rm)
        pos=()
        for a in "$@"; do case "$a" in --*) ;; *) pos+=("$a") ;; esac; done
        p="$(topath "${pos[0]:-}")"
        [ -e "$p" ] || exit 1
        rm -f "$p"
        ;;
    *) exit 0 ;;
esac
SHIM

cat > "$TMP/bin/terraform" <<'SHIM'
#!/usr/bin/env bash
set -uo pipefail
printf '%s\n' "$*" >> "$TERRAFORM_CALLS"
SHIM

chmod +x "$TMP/bin/aws" "$TMP/bin/terraform"

# --- Fixtures ----------------------------------------------------------------
echo '{}' > "$TMP/run.config.json"
echo "not a real model" > "$TMP/models/fake-model.gguf"

RUN_ID=awstest-20260827
MANIFEST="$TMP/logdir/driver-$RUN_ID.json"
DRIVER_LOG="$TMP/logdir/driver-$RUN_ID.log"

export PATH="$TMP/bin:$PATH"
export MOCK_S3 TERRAFORM_CALLS="$CALLS"
export LOOM_DRIVER_LOG_DIR="$TMP/logdir"
export LOOM_AWS_TF_DIR="$TFROOT"
export LOOM_AWS_BUCKET="$BUCKET"

# Refuse to run at all unless the shims actually win. This driver has no PATH
# prepend of its own to fight (see the header comment), but a stray earlier
# PATH entry or a broken $TMP/bin could still shadow the shim, and the whole
# safety property of this harness rests on it not doing so.
resolved_tf="$(command -v terraform)"
if [ "$resolved_tf" != "$TMP/bin/terraform" ]; then
    echo "refusing to run: terraform resolves to $resolved_tf, not the shim at $TMP/bin/terraform" >&2
    echo "the driver would talk to real infrastructure" >&2
    exit 1
fi
resolved_aws="$(command -v aws)"
if [ "$resolved_aws" != "$TMP/bin/aws" ]; then
    echo "refusing to run: aws resolves to $resolved_aws, not the shim at $TMP/bin/aws" >&2
    exit 1
fi

driver_args=(
    --model-identity "Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M"
    --models-dir "$TMP/models"
    --gguf fake-model.gguf
    --config "$TMP/run.config.json"
    --keep-bucket
    --run-id "$RUN_ID"
    --dest "$TMP/dest-launch"
    --poll-seconds 1
)

# apply 1/2 is itself a launch_runner=false apply (bucket + role, no GPU), and
# --keep-bucket's teardown is also launch_runner=false, so "no teardown ran" is
# "the count did not grow past the one the launch path always makes" — the
# same counting trick the GCP test uses, and for the same reason: it makes the
# launch apply and the teardown apply distinguishable from tf-safe-apply.sh's
# own auto-init calls (which carry no -var flags at all).
count_teardown_applies() {
    grep -c -- '-var launch_runner=false' "$CALLS" 2>/dev/null || true
}

# --- Block 1: reproduce the loss ---------------------------------------------
block "1. SIGKILL mid-poll skips the EXIT trap"

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

if [ "$(count_teardown_applies)" -eq 1 ] && [ "$applies_before_kill" -eq 1 ]; then
    pass "SIGKILL ran no teardown apply — the EXIT trap was skipped"
else
    fail "expected exactly 1 launch_runner=false apply (apply 1/2), saw $(count_teardown_applies)"
fi

if grep -q 'launch_runner=true' "$CALLS"; then
    pass "the instance had been launched, so it was left standing"
else
    fail "the launch apply never happened; the reproduction is not faithful"
fi

if [ -s "$DRIVER_LOG" ] && grep -q "driver log" "$DRIVER_LOG" && grep -q "$RUN_ID" "$DRIVER_LOG"; then
    pass "durable driver log survives the kill and names the run id"
else
    fail "no usable driver log at $DRIVER_LOG"
fi

if [ -f "$MANIFEST" ] && [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$MANIFEST")" = "$RUN_ID" ]; then
    pass "run manifest survives the kill and carries the run id"
else
    fail "no usable run manifest at $MANIFEST"
fi

# --- Block 2: recover ---------------------------------------------------------
block "2. --resume-from … --fetch-only recovers everything the kill left behind"

mkdir -p "$MOCK_S3/$BUCKET/results/$RUN_ID/runs" "$MOCK_S3/$BUCKET/results/$RUN_ID/logs"
echo '{"ok": true}' > "$MOCK_S3/$BUCKET/results/$RUN_ID/runs/records.jsonl"
echo "user-data log" > "$MOCK_S3/$BUCKET/results/$RUN_ID/logs/user-data.log"
echo SUCCEEDED > "$MOCK_S3/$BUCKET/status/$RUN_ID.txt"

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

if [ -f "$TMP/dest-resume/records.jsonl" ] && [ -f "$TMP/dest-resume/logs/user-data.log" ]; then
    pass "results and logs landed in --dest"
else
    fail "results were not fetched into $TMP/dest-resume"
fi

if grep -q 'runner reported (post-deadline grace poll): SUCCEEDED' "$TMP/block2.out"; then
    pass "fetch-only's zero-length wait read the marker via the grace poll"
else
    fail "no grace-poll marker read in the output — --fetch-only would never learn the run finished"
fi

if [ "$(count_teardown_applies)" -eq $((applies_before_resume + 1)) ]; then
    pass "teardown applied launch_runner=false exactly once"
else
    fail "expected one new teardown apply, count went $applies_before_resume -> $(count_teardown_applies)"
fi

if [ "$(find "$MOCK_S3/$BUCKET/models" -name '*.gguf' | wc -l)" -eq 1 ]; then
    pass "resume uploaded nothing new"
else
    fail "resume mode touched the upload path"
fi

# --- Block 3: the guard against tearing down a live run ----------------------
block "3. --fetch-only refuses to tear down a run that may still be in flight"

rm -f "$MOCK_S3/$BUCKET/status/$RUN_ID.txt"
applies_before_guard="$(count_teardown_applies)"
guard_rc=0
bash "$DRIVER" --resume-from "$MANIFEST" --fetch-only --dest "$TMP/dest-guard" \
    >"$TMP/block3.out" 2>&1 || guard_rc=$?

if [ "$guard_rc" -ne 0 ]; then
    pass "exited non-zero ($guard_rc) with no status marker"
else
    fail "exited 0 despite having no status marker"
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

if [ -f "$TMP/dest-guard/records.jsonl" ]; then
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
    --run-id detachrun --detach \
    >"$detach_out" 2>&1
detach_rc=$?

if [ "$detach_rc" -eq 0 ] && grep -q 'detached: pid' "$detach_out"; then
    pass "parent returned immediately and named the child's pid and log"
else
    fail "parent did not detach cleanly (rc=$detach_rc)"
    sed 's/^/      /' "$detach_out"
fi

if grep -q -- '--resume-from .*driver-detachrun.json --fetch-only' "$detach_out"; then
    pass "parent printed the exact resume command for this run"
else
    fail "parent did not print a usable resume command"
fi

detach_log="$TMP/logdir/driver-detachrun.log"
for _ in $(seq 1 200); do
    grep -q 'still running' "$detach_log" 2>/dev/null && break
    sleep 0.2
done

if grep -q 'run id          : detachrun' "$detach_log" 2>/dev/null; then
    pass "child kept the announced run id rather than minting its own"
else
    fail "child's run id does not match what the parent announced"
fi

child_pid="$(pgrep -f -- '--log-file .*driver-detachrun\.log' | head -1 || true)"
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
