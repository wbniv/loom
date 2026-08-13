"""Phase A of the masked-generation experiment (docs/plans/2026-08-13-masked-generation-experiment.md).

This package is the *harness*, not a language layer. It only ever consumes the
prototype's validation layers through their published contract entry points
(`prototype/contracts.py`); nothing here re-implements a checker, and nothing
here is on the road to the store. R1's exclusions hold throughout: no
namespaces, no leases, no policy admission, no persistence, no garbage
collection. No per-token masking either — that is Phase B, and Phase B's design
is gated on the failure distribution this package produces.

Module layout, and why it is a package rather than five more files in
`prototype/`:

``resolver.py``   R1's disposable store-shaped resolver — one hash-keyed lookup
                  surface over `DeclarationRegistry` + `DefinitionTypeRegistry`.
``prompts.py``    R4's four corpus regimes, and the task set (corpus-drawn plus
                  the held-out compositional tasks with their expected types).
``backends.py``   The pluggable model seam: prompt (+ optional grammar) to
                  tokens. A llama.cpp server backend, a llama.cpp CLI backend,
                  and a deterministic stub for tests.
``evaluate.py``   R3's funnel — parse/scope/references/typecheck classification
                  and the operationalized semantic-success rule.
``runner.py``     R2's conditions 1-3 under the shared fixed-token-budget rule,
                  the JSONL run record, and the aggregate report.

`prototype/` is a flat directory whose file table is the README's index of the
*language* prototype. Five experiment modules dropped into it would double that
table's length with files that are not part of the prototype's contract surface
at all, and would put `resolver.py`/`prompts.py`/`runner.py` — names with no
Loom meaning — next to `scope.py` and `typecheck.py`. A package keeps the
consumer/consumed boundary visible in the directory listing, and it is the
boundary the plan draws in R1.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The prototype modules this package consumes live one directory up and are
# imported by bare name (`import transcode`), matching how the prototype's own
# tests import them. That works unchanged when the caller's working directory is
# `prototype/`; this makes it work from anywhere else too, without turning the
# prototype into a package and rewriting every existing import.
_PROTOTYPE_DIR = str(Path(__file__).resolve().parent.parent)
if _PROTOTYPE_DIR not in sys.path:
    sys.path.insert(0, _PROTOTYPE_DIR)
