#!/usr/bin/env bash
# The SML FFI generator spike, end to end: batch 2's amendment A2 said
# writing a build-time struct-layout generator was "a day's work" and
# scored SML's FFI criterion at 3 partly on that claim. This script is what
# turns the claim into measured fact -- see
# docs/investigations/2026-08-14-language-eval-batch-2.md's SML FFI section
# for the verdict this run produced.
#
# Steps, each printed with its own timing:
#   1. generate.py: compile+run a C probe against the REAL pinned llama.h,
#      measure offsetof/sizeof for every field llama_ffi.py's ctypes shim
#      mirrors, emit offsets.json + a static_assert drift-check C file +
#      generated SML accessors/_import decls.
#   2. Compile the static_assert file -- compilation success IS the drift
#      check (see generate.py's docstring for why compiling it today is
#      necessarily a pass, and what protects future builds).
#   3. cross_check.py: compare the measured offsets against what ctypes
#      itself computes for llama_ffi.py's hand-written structs. A mismatch
#      is a finding about the Python shim, reported loudly, not papered
#      over.
#   4. If MLton is available (fetched into ~/.local on first run if not),
#      compile the generated SML plus a hand-written smoke test that calls
#      into the real libllama.so and round-trips a struct field through a
#      generated accessor. If MLton genuinely cannot be obtained or run,
#      this step is skipped with a clear message -- the spike degrades
#      gracefully rather than faking a compile.
#
# Usage: run.sh [--llama-root DIR]
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: run.sh [--llama-root DIR]

Run the SML FFI generator spike end to end: generate offset-derived C and
SML artifacts from the pinned llama.h, verify the C-side static_assert
drift gate compiles, cross-check against ctypes, and (if MLton is
available, fetching it into ~/.local on first run) compile and run an SML
smoke test against the real libllama.so.

  --llama-root DIR   pinned llama.cpp checkout (default: ~/loom-tools/llama.cpp)
  -h, --help         show this help and exit
EOF
}

LLAMA_ROOT="$HOME/loom-tools/llama.cpp"
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --llama-root) LLAMA_ROOT="$2"; shift 2 ;;
        *) echo "run.sh: unrecognized argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

#: Pinned MLton release. Recorded here, not just in prose, so a re-run
#: fetches the exact same bits: https://github.com/MLton/mlton/releases/tag/on-20241230-release
MLTON_VERSION="20241230"
MLTON_ASSET="mlton-${MLTON_VERSION}-1.amd64-linux.ubuntu-24.04_static.tgz"
MLTON_URL="https://github.com/MLton/mlton/releases/download/on-20241230-release/${MLTON_ASSET}"
MLTON_OPT_DIR="$HOME/.local/opt/mlton-${MLTON_VERSION}"
MLTON_BIN_DIR="$HOME/.local/bin"

#: MLton's runtime needs gmp.h/libgmp at compile time. Most systems with a
#: C toolchain already have libgmp-dev; this box didn't, so this vendors
#: just the header+lib locally (no sudo, no system package install) as a
#: fallback. Recorded honestly in the verdict as a real (if minor) friction
#: point of the toolchain, not smoothed over.
GMP_DEV_DIR="$HOME/.local/opt/gmp-dev"
GMP_INC_DIR="$GMP_DEV_DIR/usr/include/x86_64-linux-gnu"
GMP_LIB_DIR="$GMP_DEV_DIR/usr/lib/x86_64-linux-gnu"

elapsed() { echo "$(( $(date +%s%N) - $1 ))"; }  # nanoseconds
fmt_ms() { awk -v ns="$1" 'BEGIN { printf "%.0fms", ns / 1e6 }'; }

step_start=$(date +%s%N)
total_start=$step_start

echo "== [1/4] generate.py: measure the real header, emit offsets + drift gate + SML =="
python3 generate.py --llama-root "$LLAMA_ROOT"
echo "   ($(fmt_ms "$(elapsed "$step_start")"))"
echo

step_start=$(date +%s%N)
echo "== [2/4] compile offsets_check.c standalone (repeat of generate.py's own check, isolated) =="
cc -std=gnu11 -Wall -c -I "$LLAMA_ROOT/include" -I "$LLAMA_ROOT/ggml/include" \
    -o /tmp/offsets_check.o generated/offsets_check.c
rm -f /tmp/offsets_check.o
echo "   PASS -- static_assert drift gate compiles clean ($(fmt_ms "$(elapsed "$step_start")"))"
echo

step_start=$(date +%s%N)
echo "== [3/4] cross_check.py: ctypes vs the real header =="
cross_check_status=0
python3 cross_check.py || cross_check_status=$?
echo "   ($(fmt_ms "$(elapsed "$step_start")"))"
echo

step_start=$(date +%s%N)
echo "== [4/4] MLton: fetch if needed, compile + run the SML smoke test =="
mlton_ok=false
if [ -x "$MLTON_BIN_DIR/mlton" ] && "$MLTON_BIN_DIR/mlton" 2>/dev/null | grep -q "MLton $MLTON_VERSION"; then
    mlton_ok=true
fi
if [ "$mlton_ok" = false ]; then
    echo "   fetching MLton $MLTON_VERSION -> $MLTON_OPT_DIR"
    echo "   ($MLTON_URL)"
    tmp_download=$(mktemp -d)
    if curl -fsSL -o "$tmp_download/mlton.tgz" "$MLTON_URL"; then
        mkdir -p "$HOME/.local/opt" "$MLTON_BIN_DIR"
        tar -xzf "$tmp_download/mlton.tgz" -C "$tmp_download"
        rm -rf "$MLTON_OPT_DIR"
        mv "$tmp_download"/mlton-*-1.amd64-linux.ubuntu-24.04_static "$MLTON_OPT_DIR"
        # A plain symlink breaks MLton's launcher: it resolves its lib/ dir
        # via `dirname "$0"`, which is lexical and does not follow symlinks,
        # so bin/ and lib/ must stay siblings as seen through argv[0]. A
        # one-line exec wrapper hands it a correct argv[0].
        for bin in mlton mllex mlyacc; do
            printf '#!/bin/sh\nexec "%s/bin/%s" "$@"\n' "$MLTON_OPT_DIR" "$bin" \
                > "$MLTON_BIN_DIR/$bin"
            chmod +x "$MLTON_BIN_DIR/$bin"
        done
    else
        echo "   could not download MLton -- skipping (network unavailable?)"
    fi
    rm -rf "$tmp_download"
fi

if [ -x "$MLTON_BIN_DIR/mlton" ]; then
    cc_opt=""
    link_opt="-L$LLAMA_ROOT/build/bin -lllama -Wl,-rpath,$LLAMA_ROOT/build/bin"
    if ! echo '#include <gmp.h>' | cc -E - >/dev/null 2>&1; then
        if [ ! -f "$GMP_INC_DIR/gmp.h" ]; then
            echo "   system has no gmp.h; vendoring libgmp-dev locally (no sudo) -> $GMP_DEV_DIR"
            mkdir -p "$GMP_DEV_DIR"
            gmp_tmp=$(mktemp -d)
            if (cd "$gmp_tmp" && apt-get download libgmp-dev) 2>/dev/null; then
                dpkg -x "$gmp_tmp"/libgmp-dev_*.deb "$GMP_DEV_DIR"
            fi
            rm -rf "$gmp_tmp"
        fi
        if [ -f "$GMP_INC_DIR/gmp.h" ]; then
            cc_opt="-I$GMP_INC_DIR"
            link_opt="-L$GMP_LIB_DIR $link_opt"
        else
            echo "   no gmp.h available (system or vendored) -- MLton cannot compile here"
        fi
    fi

    if [ -n "$cc_opt" ] || echo '#include <gmp.h>' | cc -E - >/dev/null 2>&1; then
        rm -f ffi_spike
        mlton_args=(-link-opt "$link_opt")
        if [ -n "$cc_opt" ]; then
            mlton_args+=(-cc-opt "$cc_opt")
        fi
        if "$MLTON_BIN_DIR/mlton" "${mlton_args[@]}" ffi_spike.mlb; then
            echo "   compiled -- running the smoke test against the real libllama.so:"
            ./ffi_spike
            rm -f ffi_spike
            echo "   PASS ($(fmt_ms "$(elapsed "$step_start")"))"
        else
            echo "   MLton compile FAILED -- generated SML exists but is not verified to compile"
            echo "   ($(fmt_ms "$(elapsed "$step_start")"))"
        fi
    fi
else
    echo "   MLton not available -- degrading gracefully: SML generated, C-side verified,"
    echo "   SML compile NOT attempted. Not faked."
fi
echo

rm -rf __pycache__
echo "== total: $(fmt_ms "$(elapsed "$total_start")") =="
exit "$cross_check_status"
