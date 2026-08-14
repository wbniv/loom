"""L0 — the differential harness (Track P prerequisite).

A JSON-lines export from this Python reference implementation, covering the
26 corpus fixtures, the 5 examples, and every rejection case the prototype's
tests exercise, so that a future non-Python implementation can be held to the
seven versioned contracts in `prototype/CONTRACTS.md` input by input.

Design: `docs/plans/2026-08-14-production-language-decision.md`, R7 / Track P.

The harness never re-states a case. Cases are *observed*: every contract entry
point named in `contracts.py` is wrapped, the prototype's own test suite is run
against the wrapped entry points, and each call — its input, its accept/reject
verdict, its error class, and whatever canonical bytes and hashes the layer
emits — becomes a record. The tests' assertions are untouched; the harness only
watches what they already do. A fixture pass adds the 26 corpus entries and the
5 examples through every layer, so those 31 inputs are present whether or not a
test happens to reach them.

Entry point: `python3 -m differential export` (run from `prototype/`).
"""

from __future__ import annotations

#: Bumped when the record shape changes in a way a consumer must notice.
SCHEMA_VERSION = 1

__all__ = ["SCHEMA_VERSION"]
