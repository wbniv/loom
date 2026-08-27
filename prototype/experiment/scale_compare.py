"""`docs/plans/2026-08-27-model-scale-arm.md` §6's decision rows, executed
rather than judged.

Reads the model-scale arm's two block records — `scale14-b0` (`§3-block`, the
reference) and `scale14-b2` (`hole-required`) — plus the banked 7B pilot
record they are read against, and prints:

* per block, the fill-reaching draw rate, its one-sided 95 % Wilson lower
  bound, Gate E1 (bound >= 10 %), and the fill-reaching cell rate;
* Gate E2, pooled across both blocks: did any fill draw splice into a
  four-layer-accepted assembly?
* S1, the scale comparison: B2@14B against the banked B2@7B (10/174), by
  one-sided Fisher exact. **Reported, not decided on** — §2.1 measured its
  power at a doubled rate as 0.54, so §6's rows key on a descriptive
  threshold instead;
* the §6 row that fires.

The verdict rows, in the order they are tested:

* E1 clears at either block             -> scale is the lever (§6 row 1)
* E1 fails, B2 >= 11.5 % and B0 < B2    -> license the 32B arm (§6 row 2)
* E1 fails, B2 < 11.5 %                 -> stop the scale track (§6 row 3)

E2 clearing while E1 fails is reported as §6's fourth row alongside whichever
of the above fired, since it changes what the next reader should re-read
rather than what is bought next.

Every number here comes from `pilot_select`'s own functions — `block_stats`
for E1 and the fill-reaching predicate, `assembly_liveness` for E2,
`wilson_lower` underneath both. Imported, never restated: a scale comparison
whose numerator is defined differently on each side would be measuring the
definition rather than the model. Only the *loading* is local, because
`pilot_select.load_block` resolves block names through `BLOCK_RUN_DIRS`, which
knows the four pilot directories and not this arm's two.

Run from `prototype/`::

    python3 -m experiment.scale_compare

Exit code: 0 when E1 clears, 2 on the 32B-licensing row, 3 on the stop row,
4 when a required run directory is missing — so a launch script can branch on
it without parsing the table.
"""

from __future__ import annotations

import json
import pathlib
import sys

from scipy import stats

from .hole_elicitation_probe import RUNS
from .pilot_select import E1_BAR, assembly_liveness, block_stats
from .runner import ROLE_FILL

#: The banked 7B comparison, fixed by §2.1: `runs/pilot-b2`.
BANKED_7B_RUN = "pilot-b2"

#: §6 row 2's descriptive trigger: a doubling of the banked 7B rate.
DOUBLING_THRESHOLD = 0.115

#: This arm's two blocks, in presentation order: reference first.
BLOCKS = (
    ("scale14-b0", "§3-block (B0, reference)"),
    ("scale14-b2", "hole-required (B2)"),
)


def load_run(run_id: str, runs_dir: pathlib.Path = RUNS) -> list[dict]:
    """Every record from one run directory, by run id rather than block name."""
    path = runs_dir / run_id / "records.jsonl"
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def missing_runs(run_ids, runs_dir: pathlib.Path = RUNS) -> list[pathlib.Path]:
    return [runs_dir / r / "records.jsonl" for r in run_ids
            if not (runs_dir / r / "records.jsonl").is_file()]


def main(argv=None, runs_dir: pathlib.Path | None = None) -> int:
    # Resolved at call time, not bound as a default: the module global is what
    # tests repoint, and a default argument would freeze it at import.
    runs_dir = RUNS if runs_dir is None else runs_dir
    needed = [r for r, _ in BLOCKS] + [BANKED_7B_RUN]
    if (absent := missing_runs(needed, runs_dir)):
        print("missing run records, cannot decide:")
        for path in absent:
            print(f"  {path}")
        print()
        print("Run the arm first — `scale14-runlist.json` launches both blocks.")
        return 4

    records = {run_id: load_run(run_id, runs_dir) for run_id, _ in BLOCKS}
    stats_by_run = {run_id: block_stats(rows) for run_id, rows in records.items()}

    print("### Model-scale arm — 14B against the banked 7B")
    print()
    print(f"{'block':<26}{'draws':>7}{'qualify':>9}{'draw_rate':>11}"
          f"{'wilson_lo':>11}{'cells':>9}{'cell_rate':>11}{'E1':>6}")
    for run_id, label in BLOCKS:
        s = stats_by_run[run_id]
        cells = f"{s['cells_qualifying']}/{s['cells_total']}"
        print(f"{label:<26}{s['draws']:>7}{s['qualifying']:>9}"
              f"{s['draw_rate']:>10.2%}{s['wilson_lower']:>11.2%}"
              f"{cells:>9}{s['cell_rate']:>11.2%}"
              f"{'pass' if s['e1_pass'] else 'fail':>6}")

    print()
    print(f"Gate E1 bar: one-sided 95% Wilson lower bound >= {E1_BAR:.0%}. "
          "Stated on the bound, not the point estimate (§2.1).")
    print()

    # --- Gate E2, pooled across both blocks ------------------------------
    e2 = assembly_liveness({label: records[run_id] for run_id, label in BLOCKS})
    fill_draws = sum(1 for rows in records.values()
                     for row in rows if row.get("role") == ROLE_FILL)
    print("### Gate E2 — assembly liveness, pooled across both blocks")
    print()
    print(f"  {fill_draws} fill draws, {len(e2['hits'])} spliced into a "
          "four-layer-accepted assembly.")
    print(f"  Gate E2: {'CLEAR' if e2['cleared'] else 'NOT CLEAR'}")
    print()

    # --- S1: reported, never decided on ----------------------------------
    banked = block_stats(load_run(BANKED_7B_RUN, runs_dir))
    b2 = stats_by_run["scale14-b2"]
    table = [[b2["qualifying"], b2["draws"] - b2["qualifying"]],
             [banked["qualifying"], banked["draws"] - banked["qualifying"]]]
    p_value = stats.fisher_exact(table, alternative="greater")[1]

    print("### S1 — scale comparison, B2@14B vs banked B2@7B")
    print()
    print(f"  14B: {b2['qualifying']}/{b2['draws']} = {b2['draw_rate']:.2%}   "
          f"7B: {banked['qualifying']}/{banked['draws']} = {banked['draw_rate']:.2%}")
    print(f"  one-sided Fisher exact, alpha = 0.05: p = {p_value:.4f}   "
          f"{'significant' if p_value < 0.05 else 'not significant'}")
    print("  Reported only. §2.1 measured S1's power at a doubled rate as 0.54,")
    print("  so no §6 row is keyed to this p-value.")
    print()

    # --- The §6 row that fires -------------------------------------------
    b0 = stats_by_run["scale14-b0"]
    cleared = [label for run_id, label in BLOCKS if stats_by_run[run_id]["e1_pass"]]

    print("### Verdict")
    print()
    if cleared:
        print(f"  Gate E1 clears at: {', '.join(cleared)}.")
        print("  Elicitation is a scale phenomenon and 7B was below threshold (§6 row 1).")
        print("  Re-open Stage 1's design against 14B; make the A100 quota request a")
        print("  priority rather than a background errand.")
        rc = 0
    elif b2["draw_rate"] >= DOUBLING_THRESHOLD and b0["draw_rate"] < b2["draw_rate"]:
        print(f"  No block clears E1, but B2 reaches {b2['draw_rate']:.2%} "
              f"(>= {DOUBLING_THRESHOLD:.1%}) and the reference sits below it at "
              f"{b0['draw_rate']:.2%}.")
        print("  Scale moves elicitation without clearing the bar (§6 row 2): license")
        print("  the 32B arm, request A100 quota, and re-plan with this slope.")
        rc = 2
    else:
        print(f"  No block clears E1 and B2 sits at {b2['draw_rate']:.2%}, below the "
              f"{DOUBLING_THRESHOLD:.1%} descriptive threshold (§6 row 3).")
        print("  Scale is not the lever at any size reachable from here. Stop the scale")
        print("  track; hand back the feedback-legibility lever (2026-08-26 §2.4).")
        rc = 3

    if e2["cleared"] and not cleared:
        print()
        print("  Also: E2 cleared while E1 failed (§6 row 4). Fills are reaching")
        print("  assembly at a low rate — the first live fill evidence in the campaign.")
        print("  Re-read 2026-08-26 §1.2's blame analysis against a non-empty population.")

    return rc


if __name__ == "__main__":
    sys.exit(main())
