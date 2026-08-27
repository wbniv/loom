"""Pre-registered power estimate for the feedback-legibility arm.

`docs/plans/2026-08-27-feedback-legibility-arm.md` §2.2 is the specification
this supports. It answers one question, before any GPU run: at the cell budget
this arm can afford, how large would the narrowing-note legibility effect have
to be for each of the arm's two endpoints to detect it — and what will they
miss?

Method, reused from `scale14_power.py` (one-sided, simulated, alpha = 0.05,
fixed seed) with three changes forced by this arm's shape:

1. **The comparison is paired, not two-sample.** Both arms run the same
   8 tasks x S seeds, so cell `(task, seed)` exists in both. The test is a
   sign-flip randomization test over those pairs (§2.2), not Fisher on pooled
   draws.
2. **Draws cluster inside cells, hard.** In the banked `decomp-redraft`
   records, 42 of 53 accepted draws sit in one task (`heldout/maybe/mapOrElse`,
   19.3 %) while two tasks accept nothing. The ANOVA intra-cluster correlation
   is 0.043 for funnel acceptance (design effect 1.47) and 0.120 for repair
   locality (design effect 2.11). Treating draws as independent Bernoullis
   would overstate power by about those factors, which is the one direction a
   pre-registration must not err in. Cells are therefore simulated
   beta-binomially with (a, b) fitted by MLE to the 64 banked cells, so the
   measured over-dispersion is carried rather than assumed away.
3. **The per-cell draw count is itself random.** The purse is fixed at
   4,608 tok/cell, not at a draw count; banked cells ran 7 to 31 draws
   (mean 12.06). Both arms' cell sizes are resampled from that banked
   empirical distribution independently, so the test faces unequal
   denominators exactly as it will on the day.

Both endpoints take their control (`repr`) truth from the banked
`runs/decomp-redraft` record, which is a valid estimate of the `repr` arm
because that run *is* the pre-fix rendering (2026-08-26 05:43/09:07, against
`8ed72cd` at 13:55). The treatment (`legible`) arm is modelled as a
multiplicative shift RR on each cell's rate.

**L1 — repair locality (the primary gate).** Over narrowed draws following a
rejected draft, did the next draft's failure land at or below the path the
note named, or was it accepted? Banked rate 263/658 = 39.97 %. This is the
endpoint the intervention directly targets: a note that renders the type as
`[1, b'...']` names a node the model cannot parse, so it has nothing to
localize on.

**L2 — draw-level funnel acceptance (descriptive).** The endpoint the TODO
Watch entry named, 53/772 = 6.87 %. Reported with its p-value; §2.2 explains
why no decision row is keyed to it.

Usage: `python3 -m experiment.legibility_power` — deterministic (fixed seed),
prints a table. No GPU, no store, no network.
"""

from __future__ import annotations

import collections
import json
import pathlib

import numpy as np
from scipy import optimize, special, stats

SEED = 0

#: The banked control, fixed by §2.2: `runs/decomp-redraft`, the 2026-08-26
#: decomposition run's standard-protocol arm, drawn under the pre-fix renderer.
BANKED_RUN = "decomp-redraft"

#: Cell counts per arm to evaluate. 64 = 8 tasks x 8 seeds, the banked shape
#: and this arm's Spot plan; 40 is §4's pre-committed on-demand degradation.
CELL_BAND = (40, 48, 64)

ALPHA = 0.05
TARGET_POWER = 0.80
N_SIMS = 1500
N_PERMS = 999


# --------------------------------------------------------------------------
# Endpoint extraction from the banked records
# --------------------------------------------------------------------------

def _segments(path: str | None) -> list[str]:
    return [] if not path else path.split(".")


def banked_endpoints(runs_dir: pathlib.Path) -> dict[str, tuple]:
    """Per-cell (draws, hits) for each endpoint, off the banked control arm.

    L1's denominator is narrowed draws whose predecessor was rejected (the
    draws that actually carry a note); L2's is every charged draw, which is
    what the 53/772 baseline counts.
    """
    path = runs_dir / BANKED_RUN / "records.jsonl"
    by_cell: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    with path.open() as handle:
        for line in handle:
            row = json.loads(line)
            by_cell[(row["task"], row["seed"])].append(row)

    l1: dict[tuple[str, int], list[int]] = collections.defaultdict(
        lambda: [0, 0])
    l2: dict[tuple[str, int], list[int]] = collections.defaultdict(
        lambda: [0, 0])
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
            noted = _segments(previous.get("error_path"))
            landed = _segments(row.get("error_path"))
            shared = 0
            for left, right in zip(noted, landed):
                if left != right:
                    break
                shared += 1
            l1[cell][0] += 1
            if row["funnel_outcome"] == "accepted" or shared >= len(noted):
                l1[cell][1] += 1

    def pack(table):
        ns = np.array([v[0] for v in table.values()], dtype=np.int64)
        ks = np.array([v[1] for v in table.values()], dtype=np.int64)
        return ns, ks

    return {"L1": pack(l1), "L2": pack(l2)}


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def fit_beta_binomial(ns: np.ndarray, ks: np.ndarray) -> tuple[float, float]:
    """MLE fit of a beta-binomial to the banked per-cell counts.

    Parameterised as (mean, concentration) and optimised in log space so the
    optimiser cannot wander negative; returned as the (a, b) shape pair.
    """

    def negll(theta: np.ndarray) -> float:
        mu = special.expit(theta[0])
        conc = float(np.exp(theta[1]))
        a, b = mu * conc, (1.0 - mu) * conc
        return -float(np.sum(
            special.betaln(ks + a, ns - ks + b) - special.betaln(a, b)))

    start = np.array([special.logit(ks.sum() / ns.sum()), np.log(20.0)])
    result = optimize.minimize(negll, start, method="Nelder-Mead",
                               options={"xatol": 1e-8, "fatol": 1e-8,
                                        "maxiter": 4000})
    mu = float(special.expit(result.x[0]))
    conc = float(np.exp(result.x[1]))
    return mu * conc, (1.0 - mu) * conc


def paired_power(rr: float, cells: int, a: float, b: float,
                 n_pool: np.ndarray, rng: np.random.Generator) -> float:
    """Simulated power of the §2.2 paired sign-flip test at effect `rr`."""
    hits = 0
    for _ in range(N_SIMS):
        p = rng.beta(a, b, size=cells)
        n_leg = rng.choice(n_pool, size=cells)
        n_rep = rng.choice(n_pool, size=cells)
        k_leg = rng.binomial(n_leg, np.minimum(1.0, p * rr))
        k_rep = rng.binomial(n_rep, p)

        observed = k_leg.sum() / n_leg.sum() - k_rep.sum() / n_rep.sum()

        # Sign-flip: swapping a pair's arm labels swaps both its k and its n.
        flip = rng.random((N_PERMS, cells)) < 0.5
        null = (np.where(flip, k_rep, k_leg).sum(axis=1)
                / np.where(flip, n_rep, n_leg).sum(axis=1)
                - np.where(flip, k_leg, k_rep).sum(axis=1)
                / np.where(flip, n_leg, n_rep).sum(axis=1))

        # +1 correction: the observed labelling is itself one of the draws.
        if (1 + int(np.sum(null >= observed))) / (N_PERMS + 1) < ALPHA:
            hits += 1
    return hits / N_SIMS


def fisher_power(rr: float, cells: int, p_bar: float, draws_per_cell: float,
                 rng: np.random.Generator) -> float:
    """Simulated power of an unpaired one-sided Fisher exact on pooled draws
    with draws treated as iid — the naive comparator, printed to show what
    clustering costs."""
    n = int(round(cells * draws_per_cell))
    hits = 0
    for _ in range(N_SIMS):
        q_leg = rng.binomial(n, min(1.0, p_bar * rr))
        q_rep = rng.binomial(n, p_bar)
        table = [[q_leg, n - q_leg], [q_rep, n - q_rep]]
        if stats.fisher_exact(table, alternative="greater")[1] < ALPHA:
            hits += 1
    return hits / N_SIMS


def mde(power_fn, rng: np.random.Generator,
        grid: np.ndarray) -> tuple[float, float]:
    """Smallest RR on `grid` reaching TARGET_POWER."""
    for rr in grid:
        power = power_fn(float(rr), rng)
        if power >= TARGET_POWER:
            return float(rr), power
    return float("nan"), 0.0


def report(name: str, blurb: str, ns: np.ndarray, ks: np.ndarray,
           grid: np.ndarray, probe_rr: float,
           rng: np.random.Generator) -> None:
    a, b = fit_beta_binomial(ns, ks)
    p_bar = ks.sum() / ns.sum()
    draws_per_cell = ns.mean()

    print(f"### {name} — {blurb}")
    print()
    print(f"  banked control (`{BANKED_RUN}`): {ks.sum()}/{ns.sum()} "
          f"= {p_bar:.2%} over {len(ns)} cells, {draws_per_cell:.2f} "
          f"draws/cell (range {ns.min()}-{ns.max()}).")
    print(f"  Beta-binomial MLE: a = {a:.4f}, b = {b:.4f} "
          f"(mean {a / (a + b):.2%}, concentration {a + b:.2f}).")
    print()
    print(f"  {'cells/arm':>9}  {'MDE (RR)':>8}  {'MDE rate':>8}  "
          f"{'power@MDE':>9}  {'power@RR=' + format(probe_rr, '.2f'):>14}  "
          f"{'iid MDE':>8}")
    for cells in CELL_BAND:
        point, power_at = mde(
            lambda rr, r: paired_power(rr, cells, a, b, ns, r), rng, grid)
        probe = paired_power(probe_rr, cells, a, b, ns, rng)
        naive, _ = mde(
            lambda rr, r: fisher_power(rr, cells, p_bar, draws_per_cell, r),
            rng, grid)
        print(f"  {cells:>9}  {point:>8.2f}  {p_bar * point:>7.2%}  "
              f"{power_at:>9.2f}  {probe:>14.2f}  {naive:>8.2f}")
    print()


def main() -> None:
    rng = np.random.default_rng(SEED)
    runs_dir = pathlib.Path(__file__).resolve().parents[1] / "runs"
    endpoints = banked_endpoints(runs_dir)

    print("### Feedback-legibility arm — pre-registered power")
    print()
    print(f"  Paired sign-flip randomization test, one-sided "
          f"(legible > repr), alpha = {ALPHA},")
    print(f"  target power = {TARGET_POWER:.0%}, {N_SIMS} simulations x "
          f"{N_PERMS} permutations, seed {SEED}.")
    print("  Cell sizes resampled per arm; cell rates beta-binomial, fitted "
          "to the banked cells.")
    print("  `iid MDE` is the same MDE computed as if draws were independent "
          "and unpaired —")
    print("  the gap to the MDE column is what clustering costs net of what "
          "pairing buys.")
    print()

    report("L1 (primary gate)", "repair locality",
           *endpoints["L1"], np.arange(1.02, 2.01, 0.02), 1.25, rng)
    report("L2 (descriptive)", "draw-level funnel acceptance",
           *endpoints["L2"], np.arange(1.05, 3.51, 0.05), 1.25, rng)


if __name__ == "__main__":
    main()
