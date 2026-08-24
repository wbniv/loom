"""Pre-registered power estimate for the corpus-size sweep's trend test.

docs/plans/2026-08-24-corpus-size-sweep.md is the specification this supports.
It answers one question, honestly, before any GPU run: at the matched draw
budget the sweep can actually afford (~198 draws/arm, the same budget the
diversity-harvest runs used), how likely is the pre-registered trend test to
detect an effect the size the project's own recorded runs suggest?

The planning assumption is not invented — it is the per-draw full_corpus
acceptance rate at the two ends of the range this project has already
measured: curated (0 generated defs) 55/196 = 0.2806, and generated-41
(turn 1) 72/206 = 0.3495. Every point strictly between is a log1p-linear
interpolation; nothing here claims to know the true shape, only to size power
against the one shape the project has evidence for.

Two numbers come out: the trend test's own power, and a pairwise 0-vs-41
comparison's power at the same budget, run through Fisher's exact test the
same way the powered held-out A/B (docs/results/2026-08-23-heldout-powered-report.md)
did. The gap between them is the reason the primary claim in this sweep is a
trend, not a pairwise difference — the trend test pools information across
all five points instead of spending the whole budget on two.

Usage: `python3 corpus_size_sweep_power.py` — deterministic (fixed RNG seed),
prints the planning rates and both power estimates. No GPU, no store, no
network.
"""

from __future__ import annotations

import numpy as np
from scipy import optimize, stats

SEED = 0
SIZES = np.array([0, 8, 15, 25, 41])
N_PER_ARM = 198  # matched draw budget, per the diversity-harvest precedent
P_LO, P_HI = 0.2806, 0.3495  # curated / generated-41-turn1 recorded full_corpus rates
N_SIMS_TREND = 2000
N_SIMS_PAIRWISE = 4000
ALPHA = 0.05


def planning_rates() -> dict[int, float]:
    x = np.log1p(SIZES)
    x_norm = (x - x.min()) / (x.max() - x.min())
    rates = P_LO + (P_HI - P_LO) * x_norm
    return dict(zip(SIZES.tolist(), rates.tolist()))


def _negloglik(params, x, y):
    b0, b1 = params
    z = b0 + b1 * x
    return -np.sum(y * z - np.logaddexp(0, z))


def _lr_test(x, y) -> float:
    """Likelihood-ratio test, H0: b1 = 0, against logit(y) = b0 + b1*x."""
    res_full = optimize.minimize(_negloglik, x0=[0.0, 0.0], args=(x, y), method="BFGS")
    ll_full = -res_full.fun
    pbar = min(max(y.mean(), 1e-9), 1 - 1e-9)
    b0_null = np.log(pbar / (1 - pbar))
    ll_null = -_negloglik([b0_null, 0.0], np.zeros_like(x), y)
    stat = 2 * (ll_full - ll_null)
    return float(stats.chi2.sf(stat, df=1))


def trend_test_power(rng, rates: dict[int, float]) -> float:
    hits = 0
    for _ in range(N_SIMS_TREND):
        ys, xs = [], []
        for size, p in rates.items():
            draws = rng.binomial(1, p, N_PER_ARM)
            ys.append(draws)
            xs.append(np.full(N_PER_ARM, np.log1p(size)))
        y = np.concatenate(ys)
        x = np.concatenate(xs)
        if _lr_test(x, y) < ALPHA:
            hits += 1
    return hits / N_SIMS_TREND


def pairwise_power(rng, p1: float, p2: float) -> float:
    hits = 0
    for _ in range(N_SIMS_PAIRWISE):
        a = rng.binomial(N_PER_ARM, p1)
        b = rng.binomial(N_PER_ARM, p2)
        table = [[b, N_PER_ARM - b], [a, N_PER_ARM - a]]
        _, p = stats.fisher_exact(table)
        if p < ALPHA:
            hits += 1
    return hits / N_SIMS_PAIRWISE


def main() -> None:
    rng = np.random.default_rng(SEED)
    rates = planning_rates()
    print("planning rates (per-draw accept probability, log1p-linear interpolation):")
    for size, p in rates.items():
        print(f"  defs={size:>3}  p={p:.4f}")

    trend_power = trend_test_power(rng, rates)
    print(f"\ntrend test (logistic-regression LR test, log1p(size), alpha={ALPHA}):")
    print(f"  n_sims={N_SIMS_TREND}  power={trend_power:.3f}")

    pw_extreme = pairwise_power(rng, rates[0], rates[41])
    print(f"\ncross-check: pairwise 0-vs-41 (Fisher exact, two-sided, alpha={ALPHA}):")
    print(f"  n_sims={N_SIMS_PAIRWISE}  power={pw_extreme:.3f}")

    pw_small = pairwise_power(rng, 0.28, 0.31)
    print(f"\ncross-check: pairwise small-effect 0.28-vs-0.31 (~0.3 acc/1k tok gap):")
    print(f"  n_sims={N_SIMS_PAIRWISE}  power={pw_small:.3f}")


if __name__ == "__main__":
    main()
