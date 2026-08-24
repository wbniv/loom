#!/usr/bin/env bash
# build-store-variant.sh — seed a store with the pinned corpus and then harvest
# a *selection* of the recorded runs' accepted draws into it as
# origin=generated.
#
# docs/plans/2026-08-23-diversity-harvest.md is the specification. The corpus
# loop's original `task store:harvest` builds exactly one store from exactly one
# run; the diversity A/B needs several stores that differ only in which draws
# were selected from the same pool, so the pool and the policy are arguments
# here rather than constants in the Taskfile.
#
# The pool is discovered, not listed: every prototype/runs/*/records.jsonl whose
# sibling summary.json records a model_identity. A run without a recorded
# identity is skipped and named, because the harvest refuses to admit
# generations that cannot say which model produced them (corpus-loop R2.1,
# "recorded, not reconstructed") — and a skipped run must be visible, not
# silently absent from a pool that a later result depends on.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS_DIR="$REPO_ROOT/prototype/runs"
STORE=""
POLICY="all"
EXCLUDE_PREFIXES=("heldout/")
DRY_RUN=false

usage() {
    cat <<'USAGE'
Usage: scripts/build-store-variant.sh --store DIR [options]

Seeds DIR with the pinned corpus, harvests a selection of the recorded runs'
accepted draws into it as origin=generated, fscks it, and writes its
export-resolver.json.

Required:
  --store DIR             Store directory, e.g. .loom-store-diverse. Relative
                          paths are taken from the repo root. Deleted and
                          rebuilt from scratch, so the result is a function of
                          the pool and the policy alone.

Options:
  --select POLICY         all (default) | distinct-shape | size-match:<n>
  --runs DIR              Where to look for */records.jsonl.
                          Default: <repo>/prototype/runs
  --exclude-task-prefix P Drop candidates whose task starts with P. Repeatable.
                          Defaults to a single "heldout/"; passing any value
                          replaces the default entirely.
  --no-exclude            Keep held-out-task draws in the pool.
  --dry-run               Print the pool and the counts; touch no store.
  -h, --help              This text.

Examples:
  scripts/build-store-variant.sh --store .loom-store-diverse --select distinct-shape
  scripts/build-store-variant.sh --store .loom-store-sizematch --select size-match:15
USAGE
}

explicit_excludes=false
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --store) STORE="$2"; shift 2 ;;
        --select) POLICY="$2"; shift 2 ;;
        --runs) RUNS_DIR="$2"; shift 2 ;;
        --exclude-task-prefix)
            if [ "$explicit_excludes" = false ]; then EXCLUDE_PREFIXES=(); explicit_excludes=true; fi
            EXCLUDE_PREFIXES+=("$2"); shift 2 ;;
        --no-exclude) EXCLUDE_PREFIXES=(); explicit_excludes=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[ -n "$STORE" ] || { echo "--store is required" >&2; usage >&2; exit 2; }
case "$STORE" in /*) ;; *) STORE="$REPO_ROOT/$STORE" ;; esac

STORE_BIN="$REPO_ROOT/store/target/debug/loom-store"
[ -x "$STORE_BIN" ] || { echo "no loom-store binary at $STORE_BIN; run 'task store:build'" >&2; exit 3; }

# --- discover the pool -------------------------------------------------------
# `find | sort` rather than a glob so the order is the same on every machine.
# The harvest re-sorts by its own machine-independent source label anyway; this
# only keeps the *log* deterministic.
RECORD_ARGS=()
POOLED=0
while IFS= read -r records; do
    summary="$(dirname "$records")/summary.json"
    if [ ! -f "$summary" ]; then
        echo "skip $(basename "$(dirname "$records")"): no summary.json (no recorded model identity)" >&2
        continue
    fi
    identity="$(python3 -c "
import json,sys
try:
    config = json.load(open(sys.argv[1])).get('config') or {}
except Exception:
    config = {}
print(config.get('model_identity') or '')
" "$summary")"
    if [ -z "$identity" ]; then
        echo "skip $(basename "$(dirname "$records")"): summary records no model_identity" >&2
        continue
    fi
    RECORD_ARGS+=(--records "$records")
    POOLED=$((POOLED + 1))
done < <(find "$RUNS_DIR" -mindepth 2 -maxdepth 3 -name records.jsonl | sort)

[ "$POOLED" -gt 0 ] || { echo "no runs with a recorded model identity under $RUNS_DIR" >&2; exit 4; }
echo "pooling $POOLED run(s) from $RUNS_DIR under policy '$POLICY'" >&2

EXCLUDE_ARGS=()
for prefix in ${EXCLUDE_PREFIXES+"${EXCLUDE_PREFIXES[@]}"}; do
    EXCLUDE_ARGS+=(--exclude-task-prefix "$prefix")
done

if [ "$DRY_RUN" = true ]; then
    exec python3 "$REPO_ROOT/prototype/harvest.py" \
        "${RECORD_ARGS[@]}" ${EXCLUDE_ARGS+"${EXCLUDE_ARGS[@]}"} \
        --select "$POLICY" --dry-run \
        --resolver "$REPO_ROOT/.loom-store/export-resolver.json"
fi

# --- build -------------------------------------------------------------------
rm -rf "$STORE"
export LOOM_STORE="$STORE"
export LOOM_PROTOTYPE="$REPO_ROOT/prototype"
"$STORE_BIN" init --from-oracle
"$STORE_BIN" admit --corpus
python3 "$REPO_ROOT/prototype/harvest.py" \
    "${RECORD_ARGS[@]}" ${EXCLUDE_ARGS+"${EXCLUDE_ARGS[@]}"} \
    --select "$POLICY" \
    --store "$STORE" --store-bin "$STORE_BIN"
"$STORE_BIN" fsck
"$STORE_BIN" export-resolver --out "$STORE/export-resolver.json"
