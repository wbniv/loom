"""Power and cost for the skeleton-lever arm — the arithmetic that sizes it,
and the gate that says whether it can be bought at all.

`docs/plans/2026-08-28-skeleton-lever.md` §4 and §5 are this module's output.
Nothing here needs a GPU: the design's primary endpoint has a **banked control**
— the model-scale arm's 32 14B cells — so its base rate, its per-cell draw
counts and its overdispersion are all measured rather than assumed.

The endpoint is **term acceptance**: of the draws that declared the task's type
exactly, the fraction the funnel accepted. §1 of the plan shows why that is the
endpoint and not the mechanical floor — the floor is a conjunction of two nearly
disjoint events, and at 14B the type conjunct is largely solved (59.75 %) while
the term conjunct is not (18.83 %). Term acceptance is the floor conditioned on
the half that no longer binds, which is the only form in which it has a base
rate big enough to power at this budget.

Two tables and one verdict:

* **power** — MDE by cells per arm, from a beta-binomial fitted to the banked
  14B per-cell counts, tested with the same paired sign-flip permutation the
  legibility arm used (`legibility_power.paired_power`). The probe column is
  RR = 1.87, the banked 7B `redraft` vs `whole` acceptance ratio — the only
  effect size this campaign has ever measured for the variable the arm moves.

* **cost** — hours and dollars by cells per arm at 14B's **measured** 8.52 tok/s
  (model-scale arm, both blocks within 0.4 % of each other), Spot and on-demand.

* **verdict** — the two must be satisfiable together. The pre-committed
  degradation path never drops arms (2026-08-25 §2.3), so the binding question
  is whether the largest cell count the on-demand fallback can afford is still
  powered against RR = 1.87. **It is not, at the standing $4.55 ceiling**, and
  this module exits 2 to say so. Exit 0 means a powered configuration fits.

Run from `prototype/`::

    python3 -m experiment.skeleton_lever_power
    python3 -m experiment.skeleton_lever_power --ceiling 9.00

Exit codes: 0 a powered configuration fits under the ceiling on the on-demand
fallback; 2 none does (the plan's §4 finding); 1 an integrity check failed.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import numpy as np

from . import legibility_power
from .legibility_power import (
    fit_beta_binomial,
    fisher_power,
    paired_power,
)
from .prompts import held_out_tasks

RUNS = pathlib.Path(__file__).resolve().parent.parent / "runs"

#: The banked control for this endpoint: the model-scale arm's two 14B blocks,
#: 16 cells each. Fixed here before the arm runs, as §5's control is fixed.
BANKED_14B = ("scale14-b0", "scale14-b2")

#: The effect size the arm is powered against: the banked 7B `redraft` vs
#: `whole` funnel-acceptance ratio (53/772 against 28/762, one-sided Fisher
#: p = 0.0035). It is a *reference point chosen before the run*, not an
#: expectation — the same standing the legibility plan gave its 1.25 column.
PROBE_RR = 1.87

#: Cell counts to evaluate. 16 is what the on-demand fallback affords under the
#: standing ceiling; 64 is the decomposition run's shape.
CELL_BAND = (16, 24, 32, 40, 64)

#: Measured, not modelled. Model-scale arm: B0 8.53 tok/s, B2 8.52 tok/s over
#: 63,753 and 63,824 completion tokens. Overhead is that arm's boot + model load
#: + build-cache restore, 4.68 h wall minus 4.16 h of summed arm elapsed.
TOK_PER_S_14B = 8.525
OVERHEAD_H = 0.52
PURSE = 4608

#: us-central1 `g2-standard-4`, the campaign's standing instance.
SPOT_RATE = 0.25
ONDEMAND_RATE = 0.85

#: The campaign's standing per-arm budget ceiling (2026-08-27 legibility §4).
DEFAULT_CEILING = 4.55

#: The power bar the plan holds itself to. Below this the model-scale plan's own
#: words apply: a gate keyed to it "would fire about half the time when it
#: should, and would leave the decision hostage to a coin flip".
TARGET_POWER = 0.80

SEED = 0

#: The RR grid the MDE is reported on. Coarser than the legibility arm's 0.05
#: step because this module bisects rather than scans, and a 0.05 resolution on
#: an MDE whose base rate is itself a 45/239 estimate is false precision.
GRID = np.round(np.arange(1.10, 4.01, 0.10), 2)

#: Simulation budget. `legibility_power` uses 1500 x 999 for both jobs; here the
#: MDE *search* runs at a reduced budget (it only has to locate a grid point)
#: and every number that a §6 row is keyed to — the `power@RR` column and the
#: verdict — is recomputed at the full budget. Stated rather than hidden: the
#: MDE column carries a Monte-Carlo SE of about +/- 0.016 near power 0.8, the
#: probe column about +/- 0.010.
SEARCH_SIMS, SEARCH_PERMS = 500, 399
FULL_SIMS, FULL_PERMS = 1500, 999

FAILURES: list[str] = []

_TASKS = {task.task_id: task for task in held_out_tasks()}


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
        return
    FAILURES.append(label)
    print(f"  FAIL  {label}  {detail}")


def banked_term_cells() -> tuple[np.ndarray, np.ndarray]:
    """Per-cell `(eligible draws, accepted)` on the banked 14B blocks.

    Eligible means type-exact: the endpoint's denominator is the draws that
    declared the task's type, so a cell contributes only those. Cells with no
    eligible draw are kept with `n = 0` rather than dropped — 8 of the 32 are
    empty, and hiding them would overstate the design's effective sample.
    """
    per: dict = collections.OrderedDict()
    for run in BANKED_14B:
        for line in (RUNS / run / "records.jsonl").open():
            record = json.loads(line)
            if record.get("role") != "skeleton":
                continue
            key = (run, record["task"], record["seed"])
            per.setdefault(key, [0, 0])
            task = _TASKS.get(record["task"])
            if task and record.get("type_surface") == task.expected_type_surface:
                per[key][0] += 1
                per[key][1] += 1 if record["funnel_outcome"] == "accepted" else 0
    ns = np.array([v[0] for v in per.values()], dtype=np.int64)
    ks = np.array([v[1] for v in per.values()], dtype=np.int64)
    return ns, ks


def _at_budget(sims: int, perms: int):
    """Run `body` with `legibility_power`'s simulation budget temporarily set.

    The power functions read module-level constants, so the budget is set here
    rather than threaded through. Restored unconditionally — a probe that left
    the constants moved would silently change the legibility arm's numbers.
    """

    class _Budget:
        def __enter__(self):
            self.saved = (legibility_power.N_SIMS, legibility_power.N_PERMS)
            legibility_power.N_SIMS, legibility_power.N_PERMS = sims, perms

        def __exit__(self, *exc):
            legibility_power.N_SIMS, legibility_power.N_PERMS = self.saved
            return False

    return _Budget()


def mde_bisect(power_fn, rng: np.random.Generator, grid: np.ndarray) -> float:
    """Smallest RR on `grid` reaching TARGET_POWER, by bisection.

    Power is monotone in RR at fixed n, so a scan is wasted work: bisection
    costs about log2(len(grid)) evaluations instead of up to len(grid).
    Returns NaN when even the largest grid point misses the bar.
    """
    if power_fn(float(grid[-1]), rng) < TARGET_POWER:
        return float("nan")
    low, high = 0, len(grid) - 1
    while low < high:
        mid = (low + high) // 2
        if power_fn(float(grid[mid]), rng) >= TARGET_POWER:
            high = mid
        else:
            low = mid + 1
    return float(grid[low])


def hours(cells_per_arm: int, arms: int = 2) -> float:
    """Wall-clock hours for `arms` arms of `cells_per_arm` cells at 14B."""
    return arms * cells_per_arm * PURSE / TOK_PER_S_14B / 3600 + OVERHEAD_H


def section_power(ns: np.ndarray, ks: np.ndarray) -> dict[int, tuple[float, float]]:
    rng = np.random.default_rng(SEED)
    live = ns > 0
    a, b = fit_beta_binomial(ns[live].astype(float), ks[live].astype(float))
    p_bar = ks.sum() / ns.sum()

    print("### E1 — term acceptance (funnel accepted | declared type exact)\n")
    print(f"  banked control (`scale14-b0` + `scale14-b2`, 14B): "
          f"{ks.sum()}/{ns.sum()} = {p_bar:.2%}")
    print(f"  over {len(ns)} cells, {ns.mean():.2f} eligible draws/cell "
          f"(range {ns.min()}-{ns.max()}); {int((~live).sum())} cells carry no "
          f"eligible draw at all.")
    print(f"  Beta-binomial MLE: a = {a:.4f}, b = {b:.4f} "
          f"(mean {a / (a + b):.2%}, concentration {a + b:.2f}, "
          f"ICC {1 / (1 + a + b):.3f}).")
    print(f"\n  Overdispersion is high — ICC {1 / (1 + a + b):.3f} against the "
          f"legibility arm's 0.120 — because a\n  cell is one task at one seed "
          f"and the tasks differ enormously in difficulty.\n  The paired test "
          f"is bought for validity, not power; the iid column shows the gap.\n")

    print(f"  {'cells/arm':>9}  {'MDE (RR)':>8}  {'MDE rate':>8}  "
          f"{'power@RR=' + format(PROBE_RR, '.2f'):>14}  {'iid MDE':>8}")
    table: dict[int, tuple[float, float]] = {}
    for cells in CELL_BAND:
        with _at_budget(SEARCH_SIMS, SEARCH_PERMS):
            point = mde_bisect(
                lambda rr, r: paired_power(rr, cells, a, b, ns, r), rng, GRID)
            naive = mde_bisect(
                lambda rr, r: fisher_power(rr, cells, p_bar, ns.mean(), r),
                rng, GRID)
        with _at_budget(FULL_SIMS, FULL_PERMS):
            probe = paired_power(PROBE_RR, cells, a, b, ns, rng)
        table[cells] = (point, probe)
        print(f"  {cells:>9}  {point:>8.2f}  {p_bar * point:>7.2%}  "
              f"{probe:>14.2f}  {naive:>8.2f}")

    print("\n### E2 — type-exactness (the invariance check, not a gate)\n")
    print("  The primary conditions on an event the model produces, so it is a "
          "mediator, not a\n  randomised covariate (2026-08-28 legib-row4-probe "
          "§1 makes the same disclosure).\n  E2 is the guard: the arm moves "
          "feedback, and §1 measured feedback's effect on the\n  type conjunct "
          "at RR 1.12, p = 0.16. If the arms' type-exact shares diverge by more\n"
          "  than 5 points, the strata are not comparable and E1 is reported "
          "as descriptive.")
    return table


def section_cost(ceiling: float) -> dict[int, tuple[float, float, float]]:
    print("### Cost at 14B — measured throughput, not modelled\n")
    print(f"  {TOK_PER_S_14B:.2f} tok/s (model-scale arm: B0 8.53, B2 8.52), "
          f"purse {PURSE} tok/cell,\n  overhead {OVERHEAD_H:.2f} h, "
          f"`g2-standard-4` at ${SPOT_RATE:.2f}/h Spot and "
          f"${ONDEMAND_RATE:.2f}/h on-demand.\n")
    print(f"  {'cells/arm':>9}  {'total cells':>11}  {'hours':>6}  "
          f"{'Spot':>8}  {'on-demand':>10}")
    table: dict[int, tuple[float, float, float]] = {}
    for cells in CELL_BAND:
        h = hours(cells)
        spot, demand = SPOT_RATE * h, ONDEMAND_RATE * h
        table[cells] = (h, spot, demand)
        flag = "" if demand <= ceiling else "   over ceiling on-demand"
        print(f"  {cells:>9}  {2 * cells:>11}  {h:>6.2f}  ${spot:>7.2f}  "
              f"${demand:>9.2f}{flag}")
    print(f"\n  Ceiling ${ceiling:.2f}. Spot has been preempted on four of the "
          f"campaign's last five\n  instance inserts, so the on-demand column "
          f"is the one that sizes the arm — the\n  degradation path drops "
          f"cells, never arms (2026-08-25 §2.3).")
    return table


def section_verdict(power_table, cost_table, ceiling: float) -> int:
    print("### Verdict — can a powered configuration be bought?\n")
    affordable = [c for c in CELL_BAND if cost_table[c][2] <= ceiling]
    powered = [c for c in CELL_BAND if power_table[c][1] >= TARGET_POWER]
    both = sorted(set(affordable) & set(powered))

    print(f"  affordable on the on-demand fallback (<= ${ceiling:.2f}): "
          f"{affordable or 'none'}")
    print(f"  powered against RR = {PROBE_RR:.2f} at >= {TARGET_POWER:.2f}: "
          f"{powered or 'none'}")
    print(f"  both: {both or 'NONE'}\n")

    if both:
        print(f"  LAUNCHABLE at {min(both)} cells/arm: "
              f"${cost_table[min(both)][2]:.2f} on-demand, "
              f"power {power_table[min(both)][1]:.2f}.")
        return 0

    largest = max(affordable) if affordable else None
    if largest is not None:
        print(f"  NOT LAUNCHABLE. The largest affordable configuration is "
              f"{largest} cells/arm at\n  ${cost_table[largest][2]:.2f}, whose "
              f"power against RR = {PROBE_RR:.2f} is "
              f"{power_table[largest][1]:.2f} — the coin flip the\n  "
              f"model-scale plan refused to key a row to.")
        needed = min((c for c in CELL_BAND if power_table[c][1] >= TARGET_POWER),
                     default=None)
        if needed:
            print(f"\n  A powered arm needs {needed} cells/arm = "
                  f"${cost_table[needed][2]:.2f} on-demand "
                  f"(${cost_table[needed][1]:.2f} Spot), i.e. a ceiling of\n"
                  f"  about ${cost_table[needed][2]:.2f}. Raising the ceiling "
                  f"is the plan owner's call, not this plan's:\n  ESCALATE.")
    else:
        print("  NOT LAUNCHABLE at any evaluated size.")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ceiling", type=float, default=DEFAULT_CEILING,
                        help=f"per-arm budget ceiling (default {DEFAULT_CEILING})")
    arguments = parser.parse_args(argv)

    ns, ks = banked_term_cells()
    power_table = section_power(ns, ks)
    print()
    cost_table = section_cost(arguments.ceiling)
    print()
    status = section_verdict(power_table, cost_table, arguments.ceiling)

    print("\n### Integrity\n")
    check("the banked control is the model-scale arm's 32 cells",
          len(ns) == 32, f"got {len(ns)}")
    check("the endpoint's numerator never exceeds its denominator",
          bool(np.all(ks <= ns)))
    check("the pooled banked rate reproduces the probe's 45/239",
          (int(ks.sum()), int(ns.sum())) == (45, 239),
          f"got {int(ks.sum())}/{int(ns.sum())}")
    if FAILURES:
        print(f"\nINTEGRITY FAILURES: {len(FAILURES)}")
        return 1
    return status


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
