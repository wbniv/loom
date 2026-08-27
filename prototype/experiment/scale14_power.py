"""Pre-registered power estimate for the model-scale arm's S1 test.

`docs/plans/2026-08-27-model-scale-arm.md` §2.1 is the specification this
supports. It answers one question, before any GPU run: at the draw budget this
arm can afford, what fill-reaching rate would 14B have to reach for S1 to
detect it — and what effects will S1 miss?

`corpus_size_sweep_power.py` is the campaign's existing power helper and the
one §3 deliverable 4 named, but it is hardcoded to that sweep's five corpus
sizes, its log1p-linear interpolation, and its recorded acceptance rates. None
of that transfers to a two-block scale comparison, so the *method* is reused
here and the numbers are not: one-sided Fisher's exact at alpha = 0.05,
simulated, exactly as the powered held-out A/B
(`docs/results/2026-08-23-heldout-powered-report.md`) and the sweep's own
pairwise leg did.

The 7B side is not a planning assumption — it is the banked `pilot-b2` record,
10 fill-reaching draws of 174 (5.75 %). The 14B side's draw count is the one
genuine unknown: the purse is fixed at 4,608 tok/cell, but tokens-per-draw at
14B is not yet measured, so draws could land either side of the pilot's 174.
Power is therefore reported across a band of plausible n, not at a point.

Two numbers come out per n: the **MDE**, the smallest true 14B rate reaching
80 % power, and the power at a *doubled* rate (11.5 %), which is the effect
size §2.1 claims the arm can see. If those two disagree, §2.1 is overclaiming
and the plan is what changes, not this file.

Usage: `python3 -m experiment.scale14_power` — deterministic (fixed seed),
prints a table. No GPU, no store, no network.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

SEED = 0

#: The banked 7B comparison, read as fixed by §2.1: `runs/pilot-b2`.
N_7B, Q_7B = 174, 10
P_7B = Q_7B / N_7B

#: Plausible 14B draw counts. The pilot's B2 budget produced 174 draws; 14B
#: emits the same purse but its tokens-per-draw is unmeasured, so bracket it.
N_14B_BAND = (140, 174, 210)

ALPHA = 0.05
TARGET_POWER = 0.80
N_SIMS = 4000

#: The effect §2.1 claims to be powered for: a doubling of the 7B rate.
P_DOUBLED = 2 * P_7B


def _power(p_14b: float, n_14b: int, rng: np.random.Generator) -> float:
    """Simulated power of a one-sided Fisher exact test, 14B > 7B.

    Both arms are drawn as binomials. The 7B side is resampled rather than
    held at exactly 10/174 because Fisher's exact conditions on both margins:
    treating a sampled quantity as fixed would overstate power, which is the
    one direction a pre-registration must not err in.
    """
    hits = 0
    for _ in range(N_SIMS):
        q14 = rng.binomial(n_14b, p_14b)
        q7 = rng.binomial(N_7B, P_7B)
        table = [[q14, n_14b - q14], [q7, N_7B - q7]]
        if stats.fisher_exact(table, alternative="greater")[1] < ALPHA:
            hits += 1
    return hits / N_SIMS


def _mde(n_14b: int, rng: np.random.Generator) -> tuple[float, float]:
    """Smallest true 14B rate reaching TARGET_POWER, by a coarse-to-fine scan."""
    lo, hi = P_7B, 0.60
    best = hi
    for p in np.arange(lo + 0.005, hi, 0.005):
        if _power(float(p), n_14b, rng) >= TARGET_POWER:
            best = float(p)
            break
    return best, _power(best, n_14b, rng)


def main() -> None:
    rng = np.random.default_rng(SEED)
    print("### S1 power — 14B fill-reaching rate against banked 7B (10/174 = 5.75%)")
    print()
    print(f"  one-sided Fisher exact, alpha = {ALPHA}, target power = {TARGET_POWER:.0%},")
    print(f"  {N_SIMS} simulations per point, seed {SEED}. Both arms resampled.")
    print()
    print(f"  {'n(14B)':>8}  {'MDE':>8}  {'power@MDE':>10}  {'power@2x (11.5%)':>18}")
    for n in N_14B_BAND:
        mde, pow_at_mde = _mde(n, rng)
        pow_doubled = _power(P_DOUBLED, n, rng)
        print(f"  {n:>8}  {mde:>7.1%}  {pow_at_mde:>10.2f}  {pow_doubled:>18.2f}")
    print()
    print("  Read: S1 detects a rate at or above the MDE column with 80% power.")
    print("  The last column is what §2.1 asserts the arm can see; if it sits")
    print("  materially below 0.80, §2.1's claim is the thing that is wrong.")


if __name__ == "__main__":
    main()
