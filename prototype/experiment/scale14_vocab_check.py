"""`docs/plans/2026-08-27-model-scale-arm.md` deliverable 1 — the compatibility
gate on the model-scale arm.

The per-token type mask is a boolean vector over the model's logits. Every
number the arm's §2.1 comparison rests on assumes the 14B model presents the
*same* vocabulary the banked 7B run masked over; if it does not, the mask is
being applied to a different index space and the comparison is measuring the
tokenizer rather than the model. That failure would be silent — the run would
complete, the records would look ordinary, and the rates would be nonsense.

So this asks the question the way the runner will: load each GGUF through
`llama_ffi` (the same FFI the masked-draw path uses), read `n_vocab` off the
loaded vocab, and require the 14B's to equal both the 7B's and the value the
banked pilot telemetry recorded under `masking.vocab_size`.

Loading happens on CPU (`n_gpu_layers=0`) with a small context — this is a
metadata question, not a generation one, and it has to run on a laptop before
any GPU is rented.

Run from `prototype/`::

    python3 -m experiment.scale14_vocab_check

Exit code: 0 when the vocabularies agree, 1 when they do not (the arm must not
launch), 2 when a model file or the banked telemetry is missing.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

from .hole_elicitation_probe import RUNS
from .llama_ffi import FfiUnavailable, LlamaModel

MODELS = pathlib.Path(os.environ.get("LOOM_MODELS_DIR", pathlib.Path.home() / "loom-tools/models"))

MODEL_7B = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
MODEL_14B = "qwen2.5-coder-14b-instruct-q4_k_m.gguf"

#: The 14B GGUF's published size, from the HF blob listing. Checked because a
#: truncated download reads as a valid GGUF header for a long way in.
EXPECTED_14B_BYTES = 8_988_110_272

#: Where the banked run recorded the vocabulary its masks were built over.
BANKED_RUN = "pilot-b2"
BANKED_CELL = "gbnf+typemask|held_out"


def banked_vocab_size() -> int:
    summary = RUNS / BANKED_RUN / "summary.json"
    cell = json.loads(summary.read_text(encoding="utf-8"))["cells"][BANKED_CELL]
    return int(cell["masking"]["vocab_size"])


def model_vocab_size(path: pathlib.Path) -> int:
    """`n_vocab` as the masked-draw path sees it, from a CPU load."""
    model = LlamaModel(path, n_ctx=256, n_gpu_layers=0)
    try:
        return int(model.n_vocab)
    finally:
        close = getattr(model, "close", None) or getattr(model, "__exit__", None)
        if close is not None:
            try:
                close() if close.__name__ == "close" else close(None, None, None)
            except Exception:  # pragma: no cover - teardown must not mask a verdict
                pass


def main() -> int:
    path_7b, path_14b = MODELS / MODEL_7B, MODELS / MODEL_14B

    print("### Deliverable 1 — vocabulary compatibility for the 14B arm")
    print()

    for path in (path_7b, path_14b):
        if not path.is_file():
            print(f"  missing model: {path}")
            return 2

    size = path_14b.stat().st_size
    print(f"  14B GGUF size: {size:,} bytes "
          f"({'matches' if size == EXPECTED_14B_BYTES else 'DOES NOT MATCH'} "
          f"the published {EXPECTED_14B_BYTES:,})")
    if size != EXPECTED_14B_BYTES:
        print("  refusing to read a vocabulary off a file of the wrong size.")
        return 1

    try:
        banked = banked_vocab_size()
    except (OSError, KeyError) as exc:
        print(f"  banked telemetry unreadable ({exc}); cannot anchor the comparison.")
        return 2

    try:
        v7 = model_vocab_size(path_7b)
        v14 = model_vocab_size(path_14b)
    except FfiUnavailable as exc:
        print(f"  llama.cpp FFI unavailable: {exc}")
        return 2

    print(f"  banked {BANKED_RUN} masking.vocab_size : {banked:,}")
    print(f"  7B  n_vocab (loaded)                  : {v7:,}")
    print(f"  14B n_vocab (loaded)                  : {v14:,}")
    print()

    if v14 == v7 == banked:
        print("  result: PASS — the 14B masks over the same index space as the banked run.")
        return 0

    print("  result: FAIL — the vocabularies disagree. The mask would be applied to a")
    print("  different index space than the banked run's, so §2.1's comparison would")
    print("  measure the tokenizer, not the model. Do not launch this arm (§7).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
