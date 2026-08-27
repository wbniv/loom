"""L1/L2 endpoint definitions for the feedback-legibility arm, factored out
of `legibility_power.py` so `legibility_compare.py` (deliverable 6) reads the
same predicate rather than carrying a second copy that can drift — the plan's
own instruction (`docs/plans/2026-08-27-feedback-legibility-arm.md` §2.2:
"the predicate lives in one definition shared by `legibility_power.py` and
`legibility_compare.py` so the two cannot drift").

Both endpoints are defined over one run's records, grouped into cells by
`(task, seed)`:

* **L1 — repair locality.** Over narrowed draws that follow a rejected draft,
  the fraction whose next draft's failure path lies at or below the path the
  note named (common prefix >= the noted path's length), or which are
  accepted outright. The degenerate empty-noted-path case (length 0) is local
  by construction — every successor counts — which is §2.2's fixed rule, not
  a choice made here.
* **L2 — draw-level funnel acceptance.** `funnel_outcome == "accepted"` over
  every charged draw, unconditional on narrowing.

`repairs_locally` is the one definition importers must share; `per_cell_counts`
is exposed alongside it because both `legibility_power.py`'s banked-rate fit
and `legibility_compare.py`'s live/banked comparisons need the identical
cell-grouping walk, and a second copy of *that* would be exactly the kind of
drift risk the predicate sharing is meant to close.
"""

from __future__ import annotations

import collections

#: A cell's key, everywhere in this arm: `(task, seed)`.
Cell = tuple[str, int]

#: Per-cell (draws, hits), keyed by cell. Only cells that were touched appear
#: — a cell with zero L1-eligible draws (e.g. every draw in it landed on the
#: first try) has no entry in the L1 table, not a `(0, 0)` one.
CellCounts = dict[Cell, list[int]]


def _segments(path: str | None) -> list[str]:
    return [] if not path else path.split(".")


def repairs_locally(previous: dict, row: dict) -> bool:
    """§2.2's L1 predicate: does `row` — a narrowed draw following `previous`,
    a rejected one — count as a local repair?

    True when `row` is accepted outright, or when its own failure path
    shares a prefix with the noted path at least as long as the noted path
    itself. This is the one definition `legibility_power.py` and
    `legibility_compare.py` both import, so L1's meaning cannot drift
    between the pre-registration and the verdict.
    """
    if row["funnel_outcome"] == "accepted":
        return True
    noted = _segments(previous.get("error_path"))
    landed = _segments(row.get("error_path"))
    shared = 0
    for left, right in zip(noted, landed):
        if left != right:
            break
        shared += 1
    return shared >= len(noted)


def per_cell_counts(records: list[dict]) -> dict[str, CellCounts]:
    """Per-cell (draws, hits) for L1 and L2, keyed by `(task, seed)`.

    L1's denominator is narrowed draws whose predecessor was rejected — the
    draws that actually carry a note. L2's is every charged draw. Rows are
    sorted by `round` within a cell before either walk, since a `records.jsonl`
    is written in draw order across cells interleaved, not within one.
    """
    by_cell: dict[Cell, list[dict]] = collections.defaultdict(list)
    for row in records:
        by_cell[(row["task"], row["seed"])].append(row)

    l1: CellCounts = collections.defaultdict(lambda: [0, 0])
    l2: CellCounts = collections.defaultdict(lambda: [0, 0])
    for cell, rows in by_cell.items():
        rows.sort(key=lambda r: r["round"])
        for index, row in enumerate(rows):
            l2[cell][0] += 1
            if row["funnel_outcome"] == "accepted":
                l2[cell][1] += 1
            if index == 0 or row.get("narrowed") is not True:
                continue
            previous = rows[index - 1]
            if previous["funnel_outcome"] == "accepted":
                continue
            l1[cell][0] += 1
            if repairs_locally(previous, row):
                l1[cell][1] += 1
    return {"L1": dict(l1), "L2": dict(l2)}
