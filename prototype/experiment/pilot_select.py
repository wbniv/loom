"""`docs/plans/2026-08-26-hole-elicitation.md` §4.2's Stage-0 selection rule,
executed rather than judged.

Reads the pilot's four block records — `pilot-b0` (`§3-block`, the reference),
`pilot-b1` (`exemplar`), `pilot-b2` (`hole-required`), `pilot-b3`
(`checker-holed`) — and prints, per block: the fill-reaching draw rate (§4.2's
primary pilot metric), its one-sided 95 % Wilson lower bound, Gate E1
(lower bound >= 10 %), and the fill-reaching *cell* rate the selection rule
sorts on. It then prints Gate E2 (pooled across all four blocks: did any fill
draw splice into a four-layer-accepted assembly?) and the selection verdict:

* no block clears E1                         -> Stage 1 does not launch (§6 row 1)
* only `checker-holed` (B3) clears E1        -> ESCALATE to the plan owner (§6 row 3)
* a candidate (B1/B2) clears E1, E2 does not -> Stage 1 does not launch (§6 row 2)
* a candidate clears E1 and E2 clears        -> select the block: highest
  fill-reaching cell rate, ties broken by draw rate, then by the fixed order
  B1 < B2 (§4.2's exact tie-break)

`§3-block` (B0) is the pilot's *reference*, not a Stage-1 candidate (§2.2:
"of which B0 is the banked one and serves as the pilot's reference") — its
row is reported for comparison but it is never selected. `checker-holed` (B3)
is barred from selection by pre-commitment (§2.2, §2.3) regardless of its own
E1 result; its only route to relevance is the escalation row above.

Stage 1's `holes`-arm config (`decomp2_holes.config.json`) ships with
`hole_block` at the `§3-block` placeholder — a valid value, so the config
validates today, but not the plan's intended arm. `--apply PATH` is "the
selection tool fills [the placeholder]" (deliverable 7): on a `select`
verdict it patches PATH's `hole_block` field to the selected block,
re-validates the result through `runner.Config`, and only then writes it.

Wilson's lower bound is `hole_elicitation_probe.wilson_lower` — imported, not
restated, per the plan's own instruction that E1/E2 are gates, not tests, so
nothing here reports a p-value as inferential (§4.4).

Run from `prototype/`::

    python3 -m experiment.pilot_select
    python3 -m experiment.pilot_select --apply experiment/decomp2_holes.config.json

Exit code: 0 on a `select` verdict, 2 if no block clears E1, 3 if E1 clears
but E2 does not, 4 on the B3-only escalation — so a launch script can branch
on it without parsing the printed table.
"""

from __future__ import annotations

import argparse
import json
import pathlib

from .hole_elicitation_probe import RUNS, wilson_lower
from .prompts import (
    HOLE_BLOCK_CHECKER_HOLED,
    HOLE_BLOCK_EXEMPLAR,
    HOLE_BLOCK_HOLE_REQUIRED,
    HOLE_BLOCK_PROTOCOL,
)
from .runner import ROLE_FILL, ROLE_SKELETON, SPLICE_SPLICED, Config

#: §4.2's eligibility bar: a block's fill-reaching draw rate must clear this
#: on its one-sided 95 % Wilson lower bound, not its point estimate.
E1_BAR = 0.10

#: Presentation and iteration order: reference first, then the two live
#: candidates, then the barred-from-selection diagnostic.
BLOCK_ORDER = (
    HOLE_BLOCK_PROTOCOL, HOLE_BLOCK_EXEMPLAR,
    HOLE_BLOCK_HOLE_REQUIRED, HOLE_BLOCK_CHECKER_HOLED,
)

#: §4.2's selection rule reads over exactly these two, in exactly this order
#: — B0 is the reference and B3 is barred by pre-commitment (§2.2), so
#: neither is ever a `select` verdict's answer. The order is the tie-break:
#: "the order B1 < B2" (§4.2), i.e. B1 wins a tie.
CANDIDATE_BLOCKS = (HOLE_BLOCK_EXEMPLAR, HOLE_BLOCK_HOLE_REQUIRED)

BLOCK_LABELS = {
    HOLE_BLOCK_PROTOCOL: "§3-block (B0, reference)",
    HOLE_BLOCK_EXEMPLAR: "exemplar (B1)",
    HOLE_BLOCK_HOLE_REQUIRED: "hole-required (B2)",
    HOLE_BLOCK_CHECKER_HOLED: "checker-holed (B3, diagnostic)",
}

#: The pilot's own runlist naming (`elicitation-pilot-runlist.json`): each
#: block's `output_dir` is `runs/pilot-bN`.
BLOCK_RUN_DIRS = {
    HOLE_BLOCK_PROTOCOL: "pilot-b0",
    HOLE_BLOCK_EXEMPLAR: "pilot-b1",
    HOLE_BLOCK_HOLE_REQUIRED: "pilot-b2",
    HOLE_BLOCK_CHECKER_HOLED: "pilot-b3",
}

#: Exit codes a launch script can branch on without parsing stdout.
EXIT_SELECT = 0
EXIT_NO_LAUNCH_E1 = 2
EXIT_NO_LAUNCH_E2 = 3
EXIT_ESCALATE = 4


def load_block(block: str, runs_dir: pathlib.Path = RUNS) -> list[dict]:
    """Every record from one pilot block's run, or a `SystemExit` naming the
    run that has not happened yet — the same failure shape `Config.load`
    uses for a missing config, so a launch script sees one kind of error."""
    path = runs_dir / BLOCK_RUN_DIRS[block] / "records.jsonl"
    if not path.is_file():
        raise SystemExit(
            f"pilot records not found: {path}. Run the Stage-0 pilot first — "
            "`elicitation-pilot-runlist.json` launches all four blocks.")
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def block_stats(records: list[dict]) -> dict:
    """§4.2's primary pilot metric and Gate E1, for one block's records.

    "A skeleton draw counts iff it (a) reached the typecheck layer, (b) is
    not a bare-hole body under §3's rule evaluated unconditionally, and (c)
    has >= 1 fillable hole." Under `fill_gate: "well-scoped"` (every pilot
    cell's setting) `bare_hole_body` is already computed unconditionally by
    the runner (`runner.py`'s relaxed-gate branch), so this reads the field
    as recorded rather than recomputing it the way the banked-data probe's
    `gate()` section has to.
    """
    skeletons = [r for r in records if r.get("role") == ROLE_SKELETON]

    def qualifies(row):
        reached_typecheck = row["funnel_outcome"] not in ("parse", "references", "scope")
        return (reached_typecheck and not row.get("bare_hole_body")
                and (row.get("holes_fillable") or 0) > 0)

    qualifying = [r for r in skeletons if qualifies(r)]
    draws, hits = len(skeletons), len(qualifying)
    cells_total = {(r["task"], r["seed"]) for r in skeletons}
    cells_hit = {(r["task"], r["seed"]) for r in qualifying}
    lower = wilson_lower(hits, draws)
    return {
        "draws": draws,
        "qualifying": hits,
        "draw_rate": hits / draws if draws else 0.0,
        "wilson_lower": lower,
        "cells_total": len(cells_total),
        "cells_qualifying": len(cells_hit),
        "cell_rate": len(cells_hit) / len(cells_total) if cells_total else 0.0,
        "e1_pass": lower >= E1_BAR,
    }


def assembly_liveness(all_records: dict[str, list[dict]]) -> dict:
    """Gate E2, pooled across every block in the pilot: has any fill draw,
    anywhere, spliced into an assembly that passed all four funnel layers?
    `splice_outcome == "spliced"` already *is* that check (`runner.py`'s
    round loop only reaches it once `assembled_funnel.accepted`), so this is
    a count, not a recomputation."""
    hits = [
        {"block": block, "task": row["task"], "seed": row["seed"], "round": row.get("round")}
        for block, records in all_records.items()
        for row in records
        if row.get("role") == ROLE_FILL and row.get("splice_outcome") == SPLICE_SPLICED
    ]
    return {"cleared": bool(hits), "hits": hits}


def selection_verdict(stats: dict[str, dict], e2: dict) -> dict:
    """§4.2's selection rule, evaluated in the order §6's outcome table
    presents its rows: E1-for-everyone first, then the B3-only escalation,
    then E2, then the tie-broken pick among the blocks left standing."""
    if not any(s["e1_pass"] for s in stats.values()):
        return {"kind": "no_launch_e1",
                "message": "No block clears Gate E1 (§6 row 1). Hole-directed "
                            "decomposition is not elicitable at this scale under "
                            "prompt or feedback pressure. Stage 1 is not launched."}
    candidates_passing = [b for b in CANDIDATE_BLOCKS if stats[b]["e1_pass"]]
    if not candidates_passing:
        if stats[HOLE_BLOCK_CHECKER_HOLED]["e1_pass"]:
            return {"kind": "escalate",
                    "message": "Only `checker-holed` (B3) clears Gate E1 (§6 row 3). "
                                "The model cannot place a hole but the checker can — "
                                "that breaks the no-oracle property (§2.1). ESCALATE "
                                "to the plan owner; Stage 1 does not launch on this "
                                "verdict alone."}
        return {"kind": "no_launch_e1",
                "message": "Neither `exemplar` (B1) nor `hole-required` (B2) clears "
                            "Gate E1, and `checker-holed` (B3) does not either. No "
                            "viable Stage-1 candidate; Stage 1 is not launched."}
    if not e2["cleared"]:
        return {"kind": "no_launch_e2",
                "message": "Gate E1 clears but Gate E2 does not: no fill draw in the "
                            "whole pilot spliced into a four-layer-accepted assembly "
                            "(§6 row 2). §1.2's prediction is confirmed under "
                            "treatment — decomposition cannot repair a draft whose "
                            "committed structure is wrong. Stage 1 is not launched."}

    def key(block):
        row = stats[block]
        return (-row["cell_rate"], -row["draw_rate"], CANDIDATE_BLOCKS.index(block))

    selected = sorted(candidates_passing, key=key)[0]
    return {"kind": "select", "block": selected,
            "message": f"Selected block: {BLOCK_LABELS[selected]}. Highest "
                        "fill-reaching cell rate among the blocks clearing Gate E1 "
                        "(ties broken by draw rate, then by the fixed order B1 < B2)."}


def print_table(stats: dict[str, dict]) -> None:
    print("### Stage 0 pilot — per-block fill-reaching draw/cell rates\n")
    header = (f"{'block':<28}{'draws':>7}{'qualify':>9}{'draw_rate':>11}"
              f"{'wilson_lo':>11}{'cells':>8}{'cell_rate':>11}{'E1':>6}")
    print(header)
    for block in BLOCK_ORDER:
        row = stats[block]
        print(f"{BLOCK_LABELS[block]:<28}{row['draws']:>7}{row['qualifying']:>9}"
              f"{row['draw_rate']:>10.2%} {row['wilson_lower']:>10.2%} "
              f"{row['cells_qualifying']:>3}/{row['cells_total']:<4}"
              f"{row['cell_rate']:>10.2%}{'PASS' if row['e1_pass'] else 'fail':>6}")
    print(f"\nGate E1 bar: one-sided 95% Wilson lower bound >= {E1_BAR:.0%}. "
          "Stated on the lower bound, not the point estimate (§4.2).")


def print_e2(e2: dict) -> None:
    print("\n### Gate E2 — assembly liveness, pooled across the whole pilot\n")
    if e2["cleared"]:
        print(f"  {len(e2['hits'])} fill draw(s) spliced into a four-layer-accepted "
              "assembly:")
        for hit in e2["hits"]:
            print(f"    {BLOCK_LABELS[hit['block']]:<28} {hit['task']}  "
                  f"seed={hit['seed']}  round={hit['round']}")
        print("  Gate E2: CLEAR")
    else:
        print("  No fill draw, in any block, spliced into a four-layer-accepted "
              "assembly.")
        print("  Gate E2: NOT CLEAR")


def apply_selection(config_path: pathlib.Path, block: str) -> None:
    """§4.2's "placeholder the selection tool fills": patch `config_path`'s
    `hole_block` field to `block`, re-validate through `runner.Config`, and
    only then write — so a bad selection cannot land a config that would
    refuse to run."""
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    patched = {**raw, "hole_block": block}
    Config(**patched).validate()
    config_path.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
    print(f"\napplied: {config_path} hole_block -> {block!r} (re-validated)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs-dir", type=pathlib.Path, default=RUNS,
                        help="directory containing pilot-b0..pilot-b3 (default: "
                             "prototype/runs)")
    parser.add_argument("--apply", type=pathlib.Path, default=None,
                        help="on a 'select' verdict, patch this Stage-1 holes "
                             "config's hole_block field to the selected block")
    arguments = parser.parse_args(argv)

    all_records = {block: load_block(block, arguments.runs_dir) for block in BLOCK_ORDER}
    stats = {block: block_stats(records) for block, records in all_records.items()}
    e2 = assembly_liveness(all_records)

    print_table(stats)
    print_e2(e2)
    result = selection_verdict(stats, e2)
    print(f"\n### Verdict\n\n{result['message']}")

    if result["kind"] == "select" and arguments.apply:
        apply_selection(arguments.apply, result["block"])

    return {
        "select": EXIT_SELECT,
        "no_launch_e1": EXIT_NO_LAUNCH_E1,
        "no_launch_e2": EXIT_NO_LAUNCH_E2,
        "escalate": EXIT_ESCALATE,
    }[result["kind"]]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
