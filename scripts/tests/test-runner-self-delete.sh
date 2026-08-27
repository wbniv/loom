#!/usr/bin/env bash
set -euo pipefail
# test-runner-self-delete.sh — regression guard for the 2026-08-27 scale14
# self-delete loss (docs/plans/2026-08-27-runner-self-delete.md).
#
# What broke: infrastructure/gcp/modules/experiment-runner/main.tf passed the
# startup script a *literal* `instance_name = "${var.project}-experiment-runner"`,
# ignoring `var.instance_suffix`, while the instance Terraform actually creates
# (and the self-delete IAM condition) were both keyed off `local.instance_name`,
# which includes the suffix. Every real root sets a non-empty suffix, so the
# script's `gcloud compute instances delete "$INSTANCE_NAME"` always named an
# instance that did not exist under that identity — refused, hence the
# `shutdown -h now` fallback that left a TERMINATED instance billing on its
# 150 GB disk overnight.
#
# Nobody can integration-test a real self-delete offline (that needs a live GPU
# boot and a real IAM decision), so this checks the two provable halves
# instead:
#
#   1. Well-formed script — `bash -n` and shellcheck on the rendered template,
#      via scripts/render-gcp-startup-script.py (catches unknown interpolation
#      and bash syntax errors, not this bug specifically).
#   2. Name agreement — `terraform test` against the real module with
#      `mock_provider`, asserting the instance Terraform creates and the
#      INSTANCE_NAME baked into its own startup script can never drift apart
#      again. This is the check that would have caught the actual bug; see
#      infrastructure/gcp/modules/experiment-runner/tests/self_delete.tftest.hcl
#      for the assertions and the full explanation.
#
# Both run fully offline: no GCP credentials, no network calls beyond a local
# Terraform provider plugin cache, no resource created.

usage() {
    cat <<'USAGE'
Usage: scripts/tests/test-runner-self-delete.sh [--keep]

Offline regression guard for the 2026-08-27 runner self-delete loss. Checks
the GCP runner startup script is well-formed and that the instance Terraform
creates always agrees with the instance name baked into its own startup
script. No GCP credentials, no network, no resource created.

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
MODULE_DIR="$REPO_ROOT/infrastructure/gcp/modules/experiment-runner"
RENDER="$REPO_ROOT/scripts/render-gcp-startup-script.py"
[ -d "$MODULE_DIR" ] || { echo "module not found: $MODULE_DIR" >&2; exit 1; }
[ -f "$RENDER" ] || { echo "renderer not found: $RENDER" >&2; exit 1; }

TF="$HOME/.local/bin/terraform"
[ -x "$TF" ] || TF="$(command -v terraform || true)"
[ -n "$TF" ] || { echo "terraform not found on PATH or in ~/.local/bin" >&2; exit 1; }

TMP="$(mktemp -d -t loom-self-delete-test-XXXXXX)"
if [ "$KEEP" = false ]; then
    trap 'rm -rf "$TMP"' EXIT
else
    trap 'echo "scratch tree kept at $TMP"' EXIT
fi

FAILURES=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
block() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# --- 1. The rendered startup script is well-formed --------------------------
block "1. startup script well-formed (bash -n, shellcheck)"

RENDERED="$TMP/startup-script.sh"
if python3 "$RENDER" "$RENDERED" >"$TMP/render.log" 2>&1; then
    pass "renders with no unknown template interpolation"
else
    fail "render failed: $(cat "$TMP/render.log")"
fi

if [ -f "$RENDERED" ]; then
    if bash -n "$RENDERED" 2>"$TMP/bashn.log"; then
        pass "bash -n parses the rendered script"
    else
        fail "bash -n rejected the rendered script: $(cat "$TMP/bashn.log")"
    fi

    if command -v shellcheck >/dev/null 2>&1; then
        # -S warning: style/info notices pre-existing in the template (e.g.
        # SC2015 on an unrelated best-effort cache upload) are not this bug and
        # are not this guard's job to police; warning and above still fails.
        if shellcheck -S warning "$RENDERED" >"$TMP/shellcheck.log" 2>&1; then
            pass "shellcheck clean (warning severity and above)"
        else
            fail "shellcheck findings: $(cat "$TMP/shellcheck.log")"
        fi
    else
        echo "  (shellcheck not installed — skipping; bash -n above still ran)"
    fi
fi

# --- 2. The instance name and the startup script's INSTANCE_NAME agree ------
block "2. terraform test: instance name == startup script INSTANCE_NAME"

# A throwaway copy, never the real module directory: a concurrent apply
# elsewhere in the project may hold that directory's .terraform/ lock, and
# `terraform test` with mock_provider needs nothing from the real tree.
cp -r "$MODULE_DIR" "$TMP/mod"

# Reuse whatever provider build is already cached from a prior `terraform
# init` elsewhere in the project, so this stays offline; init falls back to
# the registry only if nothing is cached yet, at which point this check
# depends on the network for that one run same as infra:validate does.
CACHE="$HOME/.terraform.d/plugin-cache"
mkdir -p "$CACHE"
for populated in "$REPO_ROOT"/infrastructure/gcp/*/.terraform/providers; do
    [ -d "$populated" ] || continue
    cp -aln "$populated"/. "$CACHE"/ 2>/dev/null || true
done
export TF_PLUGIN_CACHE_DIR="$CACHE"

if ( cd "$TMP/mod" && "$TF" init -input=false ) >"$TMP/tfinit.log" 2>&1; then
    pass "terraform init (mock provider, no credentials)"
else
    fail "terraform init failed: $(tail -n 20 "$TMP/tfinit.log")"
fi

if ( cd "$TMP/mod" && "$TF" test -no-color ) >"$TMP/tftest.log" 2>&1; then
    pass "terraform test: instance name and startup script agree, in both the suffixed and unsuffixed cases"
else
    fail "terraform test found a name mismatch — see infrastructure/gcp/modules/experiment-runner/tests/self_delete.tftest.hcl: $(tail -n 40 "$TMP/tftest.log")"
fi

# --- Verdict -----------------------------------------------------------------
printf '\n'
if [ "$FAILURES" -eq 0 ]; then
    printf '\033[32mall checks passed\033[0m\n'
    exit 0
fi
printf '\033[31m%d check(s) failed\033[0m\n' "$FAILURES"
exit 1
