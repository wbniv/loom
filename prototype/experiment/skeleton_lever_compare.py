"""`docs/plans/2026-08-28-skeleton-lever.md` §6's decision rows, executed
rather than judged.

Reads the arm's two live blocks — `skel-redraft14` (`generation_protocol:
"redraft"`, the treatment) and `skel-whole14` (`"whole"`, the control) — plus
the banked model-scale block `scale14-b0` (§7.3's C1′ calibration anchor),
and prints:

* per arm, total draws, cells with E1-eligible data (out of the design's
  32/arm, Amendment A1), and the pooled E1 and E2 rates;
* **C1′ — a calibration anchor, checked first** (§7.3). Arm A's (`skel-
  whole14`) funnel acceptance and type-exactness, pooled over the 16 cells
  that overlap `scale14-b0`'s own seeds (1-2), must land inside that banked
  block's 95 % Wilson intervals. A failure here is a harness/drift finding
  and fires **before any endpoint is read** — §6 row 6, exit 6;
* **E2 (invariance check, not a gate) — draw-level type-exactness.** E1
  conditions on an event the model produces (a mediator, not a randomised
  covariate — §5.1's own disclosure), so this checks the arms earned a
  comparable stratum before E1 is read as a test: if the two arms' pooled
  type-exact shares differ by more than 5 points, the strata are not
  comparable — §6 row 3, exit 3, and E1 below is reported descriptively only;
* **E1 (primary) — term acceptance.** Of the draws that declared the task's
  type exactly (`type-exact`, imported from `decomposition_analysis` so the
  predicate cannot drift from the mechanical-floor's own conjunct), the
  fraction the funnel accepted. Gated on a data-sufficiency check first — the
  banked 14B control ran 7.47 eligible (type-exact) draws/cell/arm (45/239
  over 32 cells); below 60 % of that (4.5/cell/arm, the smaller of the two
  arms) the stratum did not materialise and E1 cannot be read at all — §6
  row 4, exit 4. Above that floor, E1 is a paired sign-flip permutation test
  over the `(task, seed)` cell pairs shared by both arms, one-sided
  (redraft > whole), alpha = 0.05, 9,999 permutations, seed 0 — the
  legibility arm's test, unchanged (`paired_sign_flip`, imported rather than
  re-derived), so the machinery is already reviewed;
* the §6 row that fires.

The verdict rows, in the order they are tested (C1′ before any endpoint,
then the invariance bound, then data sufficiency, then significance):

* C1′ fails                                                -> §6 row 6
* E2 diverges by > 5 points                                -> §6 row 3, stop
* E1 denominator < 4.5 eligible draws/cell/arm (starved)   -> §6 row 4, stop
* E1 clears (redraft > whole, p < 0.05)                     -> §6 row 1
* E1 significant in the reverse direction (whole > redraft) -> §6 row 5, ESCALATE
* E1 null, denominator sufficient                           -> §6 row 2, ESCALATE

Run from `prototype/`::

    python3 -m experiment.skeleton_lever_compare

Exit code: 0 on row 1, 2 on row 2, 3 on row 3, 4 on row 4 (also when a
required run's records are entirely absent — a missing arm is the most
extreme case of "denominator too small to decide", so it is folded into the
same code rather than inventing a seventh), 5 on row 5, 6 on row 6 — the
full §6 contract, so a launch/report script can branch on it without parsing
the table.
"""

from __future__ import annotations

import collections
import json
import pathlib

from .decomposition_analysis import EXPECTED, candidate_source, type_exact  # noqa: F401 (EXPECTED re-exported for tests)
from .hole_elicitation_probe import RUNS
from .legibility_compare import paired_cell_arrays, paired_sign_flip, pooled, rate, risk_ratio, wilson_interval

#: This arm's two live blocks, in presentation order: treatment first.
BLOCKS = (
    ("skel-redraft14", "skel-redraft14 (redraft)"),
    ("skel-whole14", "skel-whole14   (whole)"),
)

#: §7.3's calibration anchor — never a control arm, only ever compared against.
C1_ANCHOR_RUN = "scale14-b0"
#: The 16 cells (8 tasks x seeds 1-2) `skel-whole14` shares with the anchor.
C1_OVERLAP_SEEDS = (1, 2)

#: Amendment A1's design: 8 tasks x seeds 1-4 = 32 cells/arm.
CELLS_PER_ARM = 32

#: §5.1's fixed test parameters — the legibility arm's own, unchanged.
ALPHA = 0.05
N_PERMS = 9999
SEED = 0

#: §5.1: the banked 14B control's eligible-draw density (45/239 over 32
#: cells) and 60 % of it — below this, the term stratum did not materialise.
BANKED_ELIGIBLE_PER_CELL = 239 / 32
MIN_ELIGIBLE_PER_CELL = 0.60 * BANKED_ELIGIBLE_PER_CELL

#: §5.1 E2's pre-committed invariance bound, in percentage points.
E2_DIVERGENCE_PTS = 5.0


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


def effective_records(records: list[dict]) -> list[dict]:
    """The population a `holes`-protocol run's *own* stats are read over is
    its `candidate`-role records (`decomposition_analysis.candidates_of`'s
    rule — the model's final draft per round, not its skeleton). A `whole`
    or `redraft` arm never writes a `candidate` role at all, so the same
    rule applied here — "candidate rows if any exist, otherwise every row" —
    covers both without keying off the run's name the way
    `decomposition_analysis.candidates_of` does (this module reads arms that
    function does not know the names of)."""
    candidates = [r for r in records if r.get("role") == "candidate"]
    return candidates if candidates else records


# --------------------------------------------------------------------------
# E1 / E2 — per-cell counts
# --------------------------------------------------------------------------

def per_cell_counts(records: list[dict]) -> dict[str, dict]:
    """Per `(task, seed)` cell:

    * **E2** — `(draws, type-exact draws)`, every charged draw in the cell.
    * **E1** — `(type-exact draws, of those the funnel accepted)`. A cell
      with zero type-exact draws has no E1 entry (the L1-style convention
      `legibility_endpoints.per_cell_counts` already uses) rather than a
      `(0, 0)` one, so `paired_cell_arrays` zero-fills it against the other
      arm exactly the way a genuinely untouched cell would be.
    """
    e1: dict = collections.defaultdict(lambda: [0, 0])
    e2: dict = collections.defaultdict(lambda: [0, 0])
    for row in effective_records(records):
        cell = (row["task"], row["seed"])
        e2[cell][0] += 1
        if not type_exact(row):
            continue
        e2[cell][1] += 1
        e1[cell][0] += 1
        if row["funnel_outcome"] == "accepted":
            e1[cell][1] += 1
    return {"E1": dict(e1), "E2": dict(e2)}


# --------------------------------------------------------------------------
# C1' -- the calibration anchor
# --------------------------------------------------------------------------

def c1_prime(whole_records: list[dict], anchor_records: list[dict]):
    """§7.3: `skel-whole14`'s seeds-1-2 cells against `scale14-b0`'s own 95 %
    Wilson intervals, on both funnel acceptance and type-exactness. Returns
    `(ok, detail dict)`.
    """
    overlap = [r for r in whole_records if r.get("seed") in C1_OVERLAP_SEEDS]
    n_a = len(overlap)
    k_acc_a = sum(1 for r in overlap if r["funnel_outcome"] == "accepted")
    k_te_a = sum(1 for r in overlap if type_exact(r))
    acc_rate_a, te_rate_a = rate(n_a, k_acc_a), rate(n_a, k_te_a)

    anchor = effective_records(anchor_records)
    n_anchor = len(anchor)
    k_acc_anchor = sum(1 for r in anchor if r["funnel_outcome"] == "accepted")
    k_te_anchor = sum(1 for r in anchor if type_exact(r))
    lo_acc, hi_acc = wilson_interval(k_acc_anchor, n_anchor)
    lo_te, hi_te = wilson_interval(k_te_anchor, n_anchor)
    in_acc = lo_acc <= acc_rate_a <= hi_acc
    in_te = lo_te <= te_rate_a <= hi_te

    return in_acc and in_te, {
        "n_a": n_a, "acc_rate_a": acc_rate_a, "te_rate_a": te_rate_a,
        "n_anchor": n_anchor,
        "acc_anchor": rate(n_anchor, k_acc_anchor), "acc_lo": lo_acc, "acc_hi": hi_acc,
        "te_anchor": rate(n_anchor, k_te_anchor), "te_lo": lo_te, "te_hi": hi_te,
        "in_acc": in_acc, "in_te": in_te,
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def main(argv=None, runs_dir: pathlib.Path | None = None) -> int:
    # Resolved at call time, not bound as a default: the module global is
    # what tests repoint, and a default argument would freeze it at import.
    runs_dir = RUNS if runs_dir is None else runs_dir
    needed = [r for r, _ in BLOCKS] + [C1_ANCHOR_RUN]
    if (absent := missing_runs(needed, runs_dir)):
        print("missing run records, cannot decide (§6 row 4 -- the extreme case")
        print("of a denominator too small to read E1 from):")
        for path in absent:
            print(f"  {path}")
        print()
        print("Run the arm first -- `skeleton-lever-runlist.json` launches both blocks.")
        return 4

    records = {run_id: load_run(run_id, runs_dir) for run_id, _ in BLOCKS}
    counts = {run_id: per_cell_counts(rows) for run_id, rows in records.items()}
    anchor_records = load_run(C1_ANCHOR_RUN, runs_dir)

    redraft_id, whole_id = BLOCKS[0][0], BLOCKS[1][0]

    print("### Skeleton-lever arm -- redraft vs whole, term-stratum acceptance")
    print()
    print(f"{'arm':<28}{'draws':>7}{'cells':>9}{'E1 rate':>10}{'E2 rate':>10}")
    for run_id, label in BLOCKS:
        n_e1, k_e1 = pooled(counts[run_id]["E1"])
        n_e2, k_e2 = pooled(counts[run_id]["E2"])
        cells_e1 = len(counts[run_id]["E1"])
        print(f"{label:<28}{len(effective_records(records[run_id])):>7}"
              f"{cells_e1:>4}/{CELLS_PER_ARM:<4}"
              f"{rate(n_e1, k_e1):>10.2%}{rate(n_e2, k_e2):>10.2%}")
    print()

    # --- C1' -- checked before any endpoint is read (§7.3) -------------------
    c1_ok, c1 = c1_prime(records[whole_id], anchor_records)
    print("### C1' -- calibration anchor against the banked model-scale block "
          f"({C1_ANCHOR_RUN})")
    print()
    print(f"  skel-whole14, seeds {C1_OVERLAP_SEEDS}: n={c1['n_a']}  "
          f"acceptance {c1['acc_rate_a']:.2%}  type-exact {c1['te_rate_a']:.2%}")
    print(f"  {C1_ANCHOR_RUN} (n={c1['n_anchor']}):  "
          f"acceptance {c1['acc_anchor']:.2%}  95% Wilson [{c1['acc_lo']:.2%}, {c1['acc_hi']:.2%}]  "
          f"{'in' if c1['in_acc'] else 'OUT'}")
    print(f"  {'':<{len(C1_ANCHOR_RUN) + 8}}type-exact {c1['te_anchor']:.2%}  "
          f"95% Wilson [{c1['te_lo']:.2%}, {c1['te_hi']:.2%}]  "
          f"{'in' if c1['in_te'] else 'OUT'}")
    print()

    if not c1_ok:
        print("### Verdict")
        print()
        print("  C1' FAILS: skel-whole14's seeds-1-2 figures fall outside "
              f"{C1_ANCHOR_RUN}'s 95% Wilson intervals (§6 row 6).")
        print("  A harness, driver or environment finding, checked before any endpoint is")
        print("  read. No result below may be cited until this is explained -- the")
        print("  drift-free property the legibility arm established would be broken and")
        print("  every banked §1 comparison re-opens.")
        return 6

    # --- E2 (invariance check, not a gate) ------------------------------------
    n_e2_red, k_e2_red = pooled(counts[redraft_id]["E2"])
    n_e2_who, k_e2_who = pooled(counts[whole_id]["E2"])
    rate_red, rate_who = rate(n_e2_red, k_e2_red), rate(n_e2_who, k_e2_who)
    diverge_pts = abs(rate_red - rate_who) * 100

    print("### E2 -- draw-level type-exactness (invariance check, not a gate)")
    print()
    print(f"  redraft {k_e2_red}/{n_e2_red} = {rate_red:.2%}   "
          f"whole {k_e2_who}/{n_e2_who} = {rate_who:.2%}   "
          f"diverge {diverge_pts:.2f} pts (bound {E2_DIVERGENCE_PTS:.1f} pts)")
    print()

    if diverge_pts > E2_DIVERGENCE_PTS:
        print("### Verdict")
        print()
        print(f"  E2 diverges by {diverge_pts:.2f} pts (> {E2_DIVERGENCE_PTS:.1f}), "
              "so the arms earned different strata (§6 row 3).")
        print("  E1 below is descriptive only, never a test. Report the divergence,")
        print("  re-specify the endpoint before any further spend.")
        keys, n_leg, k_leg, n_rep, k_rep = paired_cell_arrays(
            counts[redraft_id]["E1"], counts[whole_id]["E1"])
        if n_leg.sum() and n_rep.sum():
            e1_red, e1_who = rate(n_leg.sum(), k_leg.sum()), rate(n_rep.sum(), k_rep.sum())
            print(f"  (descriptive) E1: redraft {e1_red:.2%}  whole {e1_who:.2%}")
        return 3

    # --- E1 (primary) ----------------------------------------------------------
    keys1, n_red1, k_red1, n_who1, k_who1 = paired_cell_arrays(
        counts[redraft_id]["E1"], counts[whole_id]["E1"])
    n_pairs = len(keys1)
    total_red, total_who = int(n_red1.sum()), int(n_who1.sum())
    eligible_red, eligible_who = total_red / CELLS_PER_ARM, total_who / CELLS_PER_ARM
    eligible_min = min(eligible_red, eligible_who)

    print("### E1 -- term acceptance (PRIMARY)")
    print()
    print(f"  eligible (type-exact) draws/cell/arm: redraft {eligible_red:.2f}  "
          f"whole {eligible_who:.2f}  (banked 14B control {BANKED_ELIGIBLE_PER_CELL:.2f}, "
          f"floor {MIN_ELIGIBLE_PER_CELL:.2f})")

    if eligible_min < MIN_ELIGIBLE_PER_CELL:
        print(f"\n  STARVED: {eligible_min:.2f} < {MIN_ELIGIBLE_PER_CELL:.2f} (§6 row 4).")
        print()
        print("### Verdict")
        print()
        print(f"  E1's denominator is starved ({eligible_min:.2f} < "
              f"{MIN_ELIGIBLE_PER_CELL:.2f} eligible draws/cell/arm) -- the term stratum")
        print("  did not materialise. Inconclusive and stop -- a fourth starved primary")
        print("  needs the plan owner's decision, not another endpoint.")
        return 4

    red_rate1, who_rate1 = rate(total_red, int(k_red1.sum())), rate(total_who, int(k_who1.sum()))
    diff1, p_fwd1, p_rev1 = paired_sign_flip(n_red1, k_red1, n_who1, k_who1, seed=SEED, n_perms=N_PERMS)

    print(f"  redraft {int(k_red1.sum())}/{total_red} = {red_rate1:.2%}   "
          f"whole {int(k_who1.sum())}/{total_who} = {who_rate1:.2%}   "
          f"diff {diff1 * 100:+.2f} pts (RR {risk_ratio(red_rate1, who_rate1):.2f})")
    print(f"  paired sign-flip over {n_pairs} cell pairs, one-sided (redraft > whole),")
    print(f"  alpha = {ALPHA}, {N_PERMS} permutations, seed {SEED}:  "
          f"p = {p_fwd1:.4f}   {'significant' if p_fwd1 < ALPHA else 'null'}")
    print()

    print("### Verdict")
    print()
    if p_fwd1 < ALPHA and diff1 > 0:
        print(f"  E1 clears: redraft {red_rate1:.2%} > whole {who_rate1:.2%}, "
              f"p = {p_fwd1:.4f} (§6 row 1).")
        print("  Iteration with feedback is the lever on the term conjunct, at the scale")
        print("  where the type conjunct is solved. Take redraft as the standard held-out")
        print("  protocol at 14B; the next question is the content of the note.")
        return 0
    if p_rev1 < ALPHA and diff1 < 0:
        print(f"  E1 is significant in the REVERSE direction: whole {who_rate1:.2%} > "
              f"redraft {red_rate1:.2%}, p = {p_rev1:.4f} (§6 row 5).")
        print("  Feedback hurts the term stratum. Not a rounding error at this MDE.")
        print("  ESCALATE before any further spend.")
        return 5
    print(f"  E1 is null (p = {p_fwd1:.4f}); denominator sufficient "
          f"({eligible_min:.2f} >= {MIN_ELIGIBLE_PER_CELL:.2f}) (§6 row 2).")
    print("  The stratum was live, the treatment ran, and feedback did not help a draft")
    print("  that had already committed to the right type. ESCALATE to the plan owner")
    print("  with both numbers -- §3.4's dilution caveat applies to this null.")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
