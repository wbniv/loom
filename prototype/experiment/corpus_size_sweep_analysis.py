"""Real-data run of the pre-registered §2.7 trend test for the corpus-size sweep.

docs/plans/2026-08-24-corpus-size-sweep.md §2.7 is the specification. This
script does not reimplement the test: it imports `_lr_test` from
`corpus_size_sweep_power.py`, the same function whose power was estimated
before any GPU run, and applies it to the real per-draw `full_corpus` outcomes
recorded across the five points on the size axis (the reused 0-def anchor
`followup-curated` plus the four fresh arms `sweep-size{08,15,25,41}`).

Also reports the Wald p-value on beta1 as a cross-check (§2.7 asks for it
"alongside, not instead of" the LR test). No `statsmodels` in this stack, so
the Wald SE is computed from the analytic Fisher information of the fitted
logistic model (I = X^T W X, W = diag(p(1-p))) rather than approximated from
BFGS's inverse-Hessian estimate.

Usage: `python3 -m experiment.corpus_size_sweep_analysis` from `prototype/`.
No GPU, no store, no network — reads only the committed run directories.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import stats

from experiment.corpus_size_sweep_power import _lr_test, _negloglik  # reuse, not reimplement

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

# (size, run directory relative to RUNS_DIR, records.jsonl path)
POINTS = [
    (0, RUNS_DIR / "followup-curated" / "records.jsonl"),
    (8, RUNS_DIR / "sweep-size08" / "runs" / "records.jsonl"),
    (15, RUNS_DIR / "sweep-size15" / "runs" / "records.jsonl"),
    (25, RUNS_DIR / "sweep-size25" / "runs" / "records.jsonl"),
    (41, RUNS_DIR / "sweep-size41" / "runs" / "records.jsonl"),
]


def load_full_corpus_outcomes(path: Path) -> np.ndarray:
    """1 = accepted, 0 = not, over every full_corpus-regime draw in the file."""
    ys = []
    with path.open() as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("regime") != "full_corpus":
                continue
            ys.append(1 if rec.get("funnel_outcome") == "accepted" else 0)
    return np.array(ys, dtype=float)


def wald_p_value(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Wald test on beta1 from the MLE fit, analytic Fisher information."""
    from scipy import optimize

    res = optimize.minimize(_negloglik, x0=[0.0, 0.0], args=(x, y), method="BFGS")
    b0, b1 = res.x
    z = b0 + b1 * x
    p = 1.0 / (1.0 + np.exp(-z))
    w = p * (1 - p)
    design = np.column_stack([np.ones_like(x), x])
    fisher_info = design.T @ (design * w[:, None])
    cov = np.linalg.inv(fisher_info)
    se_b1 = np.sqrt(cov[1, 1])
    z_stat = b1 / se_b1
    p_wald = 2 * stats.norm.sf(abs(z_stat))
    return b1, se_b1, p_wald


def main() -> None:
    xs, ys, per_arm = [], [], []
    for size, path in POINTS:
        outcomes = load_full_corpus_outcomes(path)
        n = len(outcomes)
        acc = int(outcomes.sum())
        per_arm.append((size, acc, n, acc / n))
        xs.append(np.full(n, np.log1p(size)))
        ys.append(outcomes)
    x = np.concatenate(xs)
    y = np.concatenate(ys)

    print("full_corpus draws pooled for the trend test:")
    for size, acc, n, rate in per_arm:
        print(f"  defs={size:>3}  accepted={acc:>4}/{n:<4}  rate={rate:.4f}")
    print(f"  total draws pooled: {len(y)}")

    p_lr = _lr_test(x, y)
    print(f"\nLR test (H0: beta1=0, log1p(defs), alpha=0.05):")
    print(f"  p = {p_lr:.4f}  -> {'SIGNIFICANT' if p_lr < 0.05 else 'not significant'} at alpha=0.05")

    b1, se_b1, p_wald = wald_p_value(x, y)
    print(f"\nWald cross-check on beta1:")
    print(f"  beta1 = {b1:.4f}  se = {se_b1:.4f}  z = {b1/se_b1:.4f}  p = {p_wald:.4f}"
          f"  -> {'SIGNIFICANT' if p_wald < 0.05 else 'not significant'} at alpha=0.05")


if __name__ == "__main__":
    main()
