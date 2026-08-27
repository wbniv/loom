"""`docs/plans/2026-08-27-feedback-legibility-arm.md` §6's decision rows,
executed rather than judged.

Reads the arm's two live blocks — `legib-legible` (`narrowing_note_render:
"surface"`, the treatment) and `legib-repr` (`"repr"`, the control) — plus
the banked pre-fix run `decomp-redraft` (§1.3's calibration anchor, never
the control itself), and prints:

* per arm, total draws, cells with L1-eligible data (out of the design's
  64/arm), and the pooled L1 and L2 rates;
* **L1 (primary gate) — repair locality.** Paired sign-flip randomization
  over the `(task, seed)` cell pairs shared by both arms, one-sided
  (legible > repr), alpha = 0.05, 9,999 permutations, seed 0 (§2.2). Its
  predicate — does a narrowed draw's failure land at or below the path the
  rejected draft's note named, or accept outright — is imported from
  `legibility_endpoints.py`, the one definition this script shares with
  `legibility_power.py`'s pre-registration, so the endpoint cannot drift
  between the two;
* **L2 (descriptive) — draw-level funnel acceptance**, the same test, plus
  the narrowed-only secondary (§2.2's post-treatment-selection caveat).
  No verdict row is keyed to L2's p-value;
* **C1 — drift anchor.** The `repr` arm's L1 and L2 rates against the banked
  arm's 95 % Wilson intervals. Reported, never decisive (§2.4);
* the §6 row that fires.

The verdict rows, in the order they are tested:

* L1 clears (legible > repr, p < 0.05)                    -> §6 row 1
* L1 null, L2 point estimate >= 1.5x                       -> §6 row 2, ESCALATE
* L1 null, L2 point estimate < 1.5x                         -> §6 row 3, stop
* L1 significant in the reverse direction (repr > legible) -> §6 row 4, ESCALATE

Run from `prototype/`::

    python3 -m experiment.legibility_compare

Exit code: 0 when L1 clears, 2 on the L2-escalation row, 3 on the stop row,
5 on the reverse-direction escalation, 4 when a required run directory is
missing — so a launch script can branch on it without parsing the table.
"""

from __future__ import annotations

import json
import pathlib

import numpy as np

from .hole_elicitation_probe import RUNS
from .legibility_endpoints import per_cell_counts

#: The banked pre-fix run, §1.3's calibration anchor — never the control arm.
BANKED_RUN = "decomp-redraft"

#: This arm's two live blocks, in presentation order: treatment first.
BLOCKS = (
    ("legib-legible", "legib-legible (surface)"),
    ("legib-repr", "legib-repr    (repr)"),
)

#: §2.1's design: 8 tasks x seeds 1-8 = 64 cells/arm. The banked control ran
#: exactly this shape (`legibility_power.py`'s own banked report: "over 64
#: cells" for both L1 and L2), so it is the reference denominator for the
#: "cells" column even on a degraded 40-cell run.
CELLS_PER_ARM = 64

#: §2.2's fixed test parameters.
ALPHA = 0.05
N_PERMS = 9999
SEED = 0

#: §6 row 2's descriptive trigger: a 1.5x point-estimate RR on L2.
L2_ESCALATION_RR = 1.5

#: Deliverable 5's powered MDE table (`legibility_power.py`, §2.2), pasted
#: rather than recomputed here — the pre-registration is fixed before the
#: run, not re-derived from it. `(RR, MDE rate)` per cells/arm.
MDE_TABLE = {
    "L1": {40: (1.26, 0.5036), 48: (1.24, 0.4956), 64: (1.20, 0.4796)},
    "L2": {40: (2.05, 0.1407), 48: (1.95, 0.1339), 64: (1.75, 0.1201)},
}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_run(run_id: str, runs_dir: pathlib.Path = RUNS) -> list[dict]:
    """Every record from one run directory, by run id."""
    path = runs_dir / run_id / "records.jsonl"
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def missing_runs(run_ids, runs_dir: pathlib.Path = RUNS) -> list[pathlib.Path]:
    return [runs_dir / r / "records.jsonl" for r in run_ids
            if not (runs_dir / r / "records.jsonl").is_file()]


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

def pooled(counts: dict) -> tuple[int, int]:
    """(draws, hits) pooled across every cell in a `per_cell_counts` table."""
    n = sum(v[0] for v in counts.values())
    k = sum(v[1] for v in counts.values())
    return n, k


def rate(n: int, k: int) -> float:
    return k / n if n else 0.0


def risk_ratio(leg_rate: float, rep_rate: float) -> float:
    if rep_rate == 0:
        return float("inf") if leg_rate > 0 else 1.0
    return leg_rate / rep_rate


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Two-sided 95 % Wilson interval — C1's own bound, distinct from the
    one-sided lower bound `pilot_select` and `scale_compare` gate E1 on."""
    if n == 0:
        return 0.0, 0.0
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def paired_cell_arrays(counts_leg: dict, counts_rep: dict):
    """Align both arms' per-cell (n, k) onto the union of `(task, seed)` keys
    each has data for, zero-filling whichever arm is missing a cell — the
    same index in every returned array names the same cell pair."""
    keys = sorted(set(counts_leg) | set(counts_rep))
    n_leg = np.array([counts_leg.get(k, [0, 0])[0] for k in keys], dtype=np.int64)
    k_leg = np.array([counts_leg.get(k, [0, 0])[1] for k in keys], dtype=np.int64)
    n_rep = np.array([counts_rep.get(k, [0, 0])[0] for k in keys], dtype=np.int64)
    k_rep = np.array([counts_rep.get(k, [0, 0])[1] for k in keys], dtype=np.int64)
    return keys, n_leg, k_leg, n_rep, k_rep


def paired_sign_flip(n_leg, k_leg, n_rep, k_rep,
                     seed: int = SEED, n_perms: int = N_PERMS):
    """§2.2's test: pooled rate difference (legible - repr), sign-flipped by
    cell pair. Returns `(observed diff, p one-sided legible>repr, p
    one-sided repr>legible)` — the reverse-direction p-value is what §6's
    reverse-significance row is keyed to, from the same null draws.
    """
    observed = k_leg.sum() / n_leg.sum() - k_rep.sum() / n_rep.sum()
    rng = np.random.default_rng(seed)
    flip = rng.random((n_perms, len(n_leg))) < 0.5
    null = (np.where(flip, k_rep, k_leg).sum(axis=1)
            / np.where(flip, n_rep, n_leg).sum(axis=1)
            - np.where(flip, k_leg, k_rep).sum(axis=1)
            / np.where(flip, n_leg, n_rep).sum(axis=1))
    p_forward = (1 + int(np.sum(null >= observed))) / (n_perms + 1)
    p_reverse = (1 + int(np.sum(null <= observed))) / (n_perms + 1)
    return float(observed), float(p_forward), float(p_reverse)


def narrowed_only(records: list[dict]) -> tuple[int, int]:
    """L2's secondary (§2.2): funnel acceptance over narrowed draws only —
    post-treatment selection, reported with that caveat, never a gate."""
    narrowed = [r for r in records if r.get("narrowed") is True]
    n = len(narrowed)
    k = sum(1 for r in narrowed if r["funnel_outcome"] == "accepted")
    return n, k


def nearest_band(n_cells: int) -> int:
    """The `MDE_TABLE` row closest to the cell count actually paired —
    64 and 40 are the two committed shapes (§4); 48 covers a partial
    degradation the power table also priced."""
    return min(MDE_TABLE["L1"], key=lambda band: abs(band - n_cells))


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def main(argv=None, runs_dir: pathlib.Path | None = None) -> int:
    # Resolved at call time, not bound as a default: the module global is
    # what tests repoint, and a default argument would freeze it at import.
    runs_dir = RUNS if runs_dir is None else runs_dir
    needed = [r for r, _ in BLOCKS] + [BANKED_RUN]
    if (absent := missing_runs(needed, runs_dir)):
        print("missing run records, cannot decide:")
        for path in absent:
            print(f"  {path}")
        print()
        print("Run the arm first — `legibility-runlist.json` launches both blocks.")
        return 4

    records = {run_id: load_run(run_id, runs_dir) for run_id, _ in BLOCKS}
    counts = {run_id: per_cell_counts(rows) for run_id, rows in records.items()}
    banked_records = load_run(BANKED_RUN, runs_dir)
    banked_counts = per_cell_counts(banked_records)

    print("### Feedback-legibility arm — legible vs repr, redraft protocol")
    print()
    print(f"{'arm':<26}{'draws':>7}{'cells':>9}{'L1 rate':>10}{'L2 rate':>10}")
    for run_id, label in BLOCKS:
        n_l1, k_l1 = pooled(counts[run_id]["L1"])
        n_l2, k_l2 = pooled(counts[run_id]["L2"])
        cells_l1 = len(counts[run_id]["L1"])
        print(f"{label:<26}{len(records[run_id]):>7}"
              f"{cells_l1:>4}/{CELLS_PER_ARM:<4}"
              f"{rate(n_l1, k_l1):>10.2%}{rate(n_l2, k_l2):>10.2%}")
    print()

    leg_id, rep_id = BLOCKS[0][0], BLOCKS[1][0]

    # --- L1 (primary gate) ------------------------------------------------
    keys1, n_leg1, k_leg1, n_rep1, k_rep1 = paired_cell_arrays(
        counts[leg_id]["L1"], counts[rep_id]["L1"])
    n_pairs = len(keys1)
    leg_l1, rep_l1 = rate(n_leg1.sum(), k_leg1.sum()), rate(n_rep1.sum(), k_rep1.sum())
    diff1, p_fwd1, p_rev1 = paired_sign_flip(n_leg1, k_leg1, n_rep1, k_rep1)
    band1 = nearest_band(n_pairs)
    mde_rr1, mde_rate1 = MDE_TABLE["L1"][band1]

    print("### L1 -- repair locality (PRIMARY GATE)")
    print()
    print(f"  legible {int(k_leg1.sum())}/{int(n_leg1.sum())} = {leg_l1:.2%}   "
          f"repr {int(k_rep1.sum())}/{int(n_rep1.sum())} = {rep_l1:.2%}   "
          f"diff {diff1 * 100:+.2f} pts (RR {risk_ratio(leg_l1, rep_l1):.2f})")
    print(f"  paired sign-flip over {n_pairs} cell pairs, one-sided (legible > repr),")
    print(f"  alpha = {ALPHA}, {N_PERMS} permutations, seed {SEED}:  "
          f"p = {p_fwd1:.4f}   {'significant' if p_fwd1 < ALPHA else 'null'}")
    n_bl1, k_bl1 = pooled(banked_counts["L1"])
    l1_banked_rate = rate(n_bl1, k_bl1)
    print(f"  powered MDE at this n (deliverable 5): RR {mde_rr1:.2f}  "
          f"({l1_banked_rate:.2%} -> {mde_rate1:.2%})")
    print()

    # --- L2 (descriptive) --------------------------------------------------
    keys2, n_leg2, k_leg2, n_rep2, k_rep2 = paired_cell_arrays(
        counts[leg_id]["L2"], counts[rep_id]["L2"])
    leg_l2, rep_l2 = rate(n_leg2.sum(), k_leg2.sum()), rate(n_rep2.sum(), k_rep2.sum())
    diff2, p_fwd2, _ = paired_sign_flip(n_leg2, k_leg2, n_rep2, k_rep2)
    l2_rr = risk_ratio(leg_l2, rep_l2)

    print("### L2 -- draw-level funnel acceptance (DESCRIPTIVE)")
    print()
    print(f"  legible {int(k_leg2.sum())}/{int(n_leg2.sum())} = {leg_l2:.2%}   "
          f"repr {int(k_rep2.sum())}/{int(n_rep2.sum())} = {rep_l2:.2%}   "
          f"diff {diff2 * 100:+.2f} pts (RR {l2_rr:.2f})")
    print(f"  same test:  p = {p_fwd2:.4f}   "
          f"{'significant' if p_fwd2 < ALPHA else 'null'}")
    print("  Reported only. §2.2 measured L2's power against a 1.25x effect as 0.23,")
    print("  so no §6 row is keyed to this p-value. A null here means \"no effect")
    print("  >= 1.75x\", not \"no effect\".")
    n_narrow_leg, k_narrow_leg = narrowed_only(records[leg_id])
    n_narrow_rep, k_narrow_rep = narrowed_only(records[rep_id])
    print("  secondary, narrowed draws only (post-treatment selection -- see §2.2):")
    print(f"    legible {k_narrow_leg}/{n_narrow_leg} = {rate(n_narrow_leg, k_narrow_leg):.2%}   "
          f"repr {k_narrow_rep}/{n_narrow_rep} = {rate(n_narrow_rep, k_narrow_rep):.2%}")
    print()

    # --- C1 -- drift anchor, reported never decisive ------------------------
    # The banked figures are computed live from the loaded `decomp-redraft`
    # records (via the same `per_cell_counts` walk L1/L2 use above), not
    # pasted as constants — §2.2's 263/658 and 53/772 are what this
    # computation produces, not a separate source of truth to drift from it.
    n_bl2, k_bl2 = pooled(banked_counts["L2"])
    lo1, hi1 = wilson_interval(k_bl1, n_bl1)
    lo2, hi2 = wilson_interval(k_bl2, n_bl2)
    c1_l1_in = lo1 <= rep_l1 <= hi1
    c1_l2_in = lo2 <= rep_l2 <= hi2

    print("### C1 -- drift anchor against the banked pre-fix run (decomp-redraft)")
    print()
    print(f"  L1  banked {k_bl1}/{n_bl1} = {l1_banked_rate:.2%}  "
          f"95% Wilson [{lo1:.2%}, {hi1:.2%}]   repr arm {rep_l1:.2%}  "
          f"{'in' if c1_l1_in else 'OUT'}")
    print(f"  L2  banked {k_bl2}/{n_bl2} = {rate(n_bl2, k_bl2):.2%}  "
          f"95% Wilson [{lo2:.2%}, {hi2:.2%}]   repr arm {rep_l2:.2%}  "
          f"{'in' if c1_l2_in else 'OUT'}")
    print("  Reported, never decisive (§2.4). OUT means the banked numbers cannot be")
    print("  cited alongside this arm's -- not that the primary is invalid.")
    print()

    # --- Verdict -------------------------------------------------------------
    print("### Verdict")
    print()
    if p_fwd1 < ALPHA and diff1 > 0:
        print(f"  L1 clears: legible {leg_l1:.2%} > repr {rep_l1:.2%}, "
              f"p = {p_fwd1:.4f} (§6 row 1).")
        print("  The model can act on a readable note and could not act on a repr.")
        print("  Feedback legibility is a live lever: promote the note surface to a")
        print("  first-class design object and re-open prefix-primed repair.")
        rc = 0
    elif p_rev1 < ALPHA and diff1 < 0:
        print(f"  L1 is significant in the REVERSE direction: repr {rep_l1:.2%} > "
              f"legible {leg_l1:.2%}, p = {p_rev1:.4f} (§6 row 4).")
        print("  Genuinely surprising, not a rounding error. ESCALATE to the plan")
        print("  owner before any further spend. Do not revert the repr fix on this")
        print("  evidence -- it is a correctness fix independent of this arm.")
        rc = 5
    elif l2_rr >= L2_ESCALATION_RR:
        print(f"  L1 is null (p = {p_fwd1:.4f}), but L2's point estimate reaches "
              f"RR {l2_rr:.2f} (>= {L2_ESCALATION_RR:.1f}x) (§6 row 2).")
        print("  The mechanism gate says the model does not act more locally, but the")
        print("  outcome moved further than L1's null would predict. ESCALATE to the")
        print("  plan owner with both numbers -- do not read the L2 point estimate")
        print("  as a result on its own.")
        rc = 2
    else:
        print(f"  L1 is null (p = {p_fwd1:.4f}) and L2 sits at RR {l2_rr:.2f}, below "
              f"{L2_ESCALATION_RR:.1f}x (§6 row 3).")
        print("  Legibility is not a lever at 7B on this protocol. Stop the")
        print("  feedback-surface track. Keep the repr fix as a standing improvement")
        print("  -- it is landed, free and correct -- but not as a lever to build on.")
        rc = 3

    if not c1_l1_in or not c1_l2_in:
        print()
        print("  Also: C1 is OUT on "
              + " and ".join(name for name, ok in
                              (("L1", c1_l1_in), ("L2", c1_l2_in)) if not ok)
              + ". Harness drift since 2026-08-26 -- filed as its own item before")
        print("  the next arm is planned; the primary above still stands (within-run).")

    return rc


if __name__ == "__main__":
    import sys
    sys.exit(main())
