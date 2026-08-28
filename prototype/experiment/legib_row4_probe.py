"""Why did §6 row 4 fire? — an offline, $0 probe of the feedback-legibility
arm's reverse-direction L1 result.

`docs/plans/2026-08-27-feedback-legibility-arm.md` §6 row 4 fired on
2026-08-28: L1 (repair locality) was significant in the **reverse** direction,
the `repr` (unreadable) note producing more local repair than the `surface`
(legible) one — 263/658 = 39.97 % against 258/683 = 37.77 %, paired sign-flip
p = 0.0215. The plan's own reading was *conservatism*: an unreadable note
makes the model cautious about touching the noted region, so it repairs
locally because it cannot read enough to justify a broader rewrite. Row 4
says ESCALATE; the plan owner authorised this offline investigation at $0.

This module operationalises that reading, quantifies the rival explanations
the escalation brief named, and prints every number
`docs/investigations/2026-08-28-legib-row4-probe.md` cites. **Everything here
is exploratory and post-hoc.** No p-value below is confirmatory: the arm
pre-registered exactly one test (§2.5), it has been run, and its verdict
stands. The p-values printed here are descriptive aids to reading an effect
that already fired, and they are labelled as such at every site.

The probe's central device is an **exposure map**. The seam
(`typecheck.set_narrowing_note_render`) can only change a note that embeds a
rendered type; a note like *"measure position 1 exceeds the annotation's
1-argument curried spine"* is byte-identical under both renders. So each
rejected draw is replayed under **both** renders — the same replay
deliverable 2 used to prove byte-identity against the banked run — and
flagged `exposed` when the two renderings differ. That splits the L1
denominator into

* the **exposed** stratum, where the treatment was live, and
* the **unexposed** stratum, where both arms received the identical note and
  differ only in the trajectory that got them there.

The unexposed stratum is an internal placebo: it carries every source of
between-arm divergence except the one under test.

Run from `prototype/`::

    python3 -m experiment.legib_row4_probe
    python3 -m experiment.legib_row4_probe --section exposure --section rivals

Exit code 0 when every integrity check passes, 1 when one fails — an
integrity failure means a finding about the harness, not about the model, and
the report must say so before anything else in it is read.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import pathlib
import re
import statistics
import sys

import numpy as np

import typecheck
from .evaluate import narrowing_note, run_funnel
from .hole_elicitation_probe import RUNS
from .legibility_endpoints import _segments, repairs_locally
from .legibility_power import fit_beta_binomial
from .resolver import ExperimentResolver

#: The arm's two blocks. `legible` is the treatment (`narrowing_note_render:
#: "surface"`), `repr` the control.
LEGIBLE = "legib-legible"
REPR = "legib-repr"

#: §1.3's calibration anchor. The `repr` arm reproduced it to the draw, which
#: §0 re-asserts here rather than taking on trust from the verdict record.
BANKED = "decomp-redraft"

#: §2.2's fixed test parameters, reused verbatim so a number printed here is
#: comparable with one printed by `legibility_compare.py`. The *direction*
#: tested here is the reverse one — row 4's — because that is the result under
#: investigation.
N_PERMS = 9999
SEED = 0

#: §2.2's banked beta-binomial MLE for L1's per-cell rate, reused to simulate
#: the null in `signflip_type_one_error`. Pasted from the plan rather than
#: re-fitted, so the calibration check is against the pre-registration.
BANKED_BETA_A = 2.9925
BANKED_BETA_B = 4.9959

#: Simulations behind the type-I calibration figure. 1,000 gives a standard
#: error of ~0.009 on a 0.10 rate — enough to tell 0.09 from 0.20, which is
#: the only question being asked.
CALIBRATION_SIMS = 1000

#: Simulations behind §10's replication-power table. 500 gives a standard
#: error of ~0.02 on a 0.67 power — enough to say "not a formality", which is
#: the only claim made from it.
REPLICATION_SIMS = 500

#: Draw-index bands for the within-cell position breakdown. A cell runs until
#: its purse is spent, so late draws are a different population from early
#: ones and the bands keep that visible.
INDEX_BANDS = ("1-2", "3-5", "6-10", "11+")

#: `expected T, got U` is typecheck.py's dominant `_fail` shape and the only
#: one that hands the model a type it could copy. Used to ask whether the
#: legible note's named type turns up verbatim in the redraft.
EXPECTED_CLAUSE = re.compile(r"expected (.+?), got ", re.S)


# --------------------------------------------------------------------------
# Loading and the cell walk
# --------------------------------------------------------------------------

def load_run(run_id: str, runs_dir: pathlib.Path) -> list[dict]:
    with (runs_dir / run_id / "records.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def by_cell(records: list[dict]) -> dict[tuple[str, int], list[dict]]:
    """`(task, seed)` -> that cell's draws in round order — the same grouping
    and sort `legibility_endpoints.per_cell_counts` uses."""
    cells: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    for row in records:
        cells[(row["task"], row["seed"])].append(row)
    for rows in cells.values():
        rows.sort(key=lambda r: r["round"])
    return dict(cells)


def l1_pairs(records: list[dict]) -> list[tuple]:
    """Every `(cell, index, predecessor, draw)` L1 counts, by exactly the walk
    in `legibility_endpoints.per_cell_counts` — narrowed draws whose immediate
    predecessor was rejected. Re-expressed as pairs rather than counts because
    every question below is about *which* pairs, not how many."""
    out = []
    for cell, rows in by_cell(records).items():
        for index, row in enumerate(rows):
            if index == 0 or row.get("narrowed") is not True:
                continue
            previous = rows[index - 1]
            if previous["funnel_outcome"] == "accepted":
                continue
            out.append((cell, index, previous, row))
    return out


# --------------------------------------------------------------------------
# The exposure map — replay each rejected draw under both renders
# --------------------------------------------------------------------------

def exposure_map(records: list[dict], arm_render: str, resolver) -> tuple[dict, list]:
    """`(task, seed, round)` -> `(surface note, repr note)` for every rejected
    draw, plus the list of draws whose banked `error_message` the replay did
    not reproduce.

    The replay is deliberately the same one deliverable 2 gated the arm on:
    reconstruct the funnel from the banked `source` and rebuild the note. A
    draw is **exposed** when the two renderings differ — the only draws the
    seam could possibly have acted on. The returned mismatch list is an
    integrity check, not a statistic: a non-empty one means the records and
    today's checker disagree and nothing downstream is trustworthy.
    """
    notes: dict[tuple[str, int, int], tuple[str, str]] = {}
    mismatched = []
    try:
        for row in records:
            if row["funnel_outcome"] == "accepted":
                continue
            typecheck.set_narrowing_note_render(typecheck.NARROWING_NOTE_SURFACE)
            surface = narrowing_note(run_funnel(row["source"], resolver))
            typecheck.set_narrowing_note_render(typecheck.NARROWING_NOTE_REPR)
            raw = narrowing_note(run_funnel(row["source"], resolver))
            notes[(row["task"], row["seed"], row["round"])] = (surface, raw)
            own = surface if arm_render == typecheck.NARROWING_NOTE_SURFACE else raw
            recorded = row.get("error_message") or ""
            if not recorded or recorded not in own:
                mismatched.append((row["task"], row["seed"], row["round"]))
    finally:
        typecheck.set_narrowing_note_render(typecheck.NARROWING_NOTE_SURFACE)
    return notes, mismatched


def is_exposed(notes: dict, previous: dict) -> bool:
    surface, raw = notes[(previous["task"], previous["seed"], previous["round"])]
    return surface != raw


# --------------------------------------------------------------------------
# Endpoints and tests
# --------------------------------------------------------------------------

def strict_repair(previous: dict, row: dict) -> bool:
    """L1 with its churn loophole closed: reproducing the *same* failure at the
    *same* path no longer counts as a local repair.

    `repairs_locally` scores a successor local when its failure path shares a
    prefix with the noted path at least as long as the noted path — which a
    draw that changed nothing relevant and failed identically satisfies
    trivially. That is a defensible reading of "did not wander", but it means
    a stuck model scores maximally local, so the pre-registered endpoint is
    reported beside this variant rather than instead of it.
    """
    if row["funnel_outcome"] == "accepted":
        return True
    if (row.get("error_path") or "") == (previous.get("error_path") or ""):
        return False
    return repairs_locally(previous, row)


def landing(previous: dict, row: dict) -> str:
    """Where the next failure landed relative to the path the note named."""
    if row["funnel_outcome"] == "accepted":
        return "accepted"
    noted, landed = _segments(previous.get("error_path")), _segments(row.get("error_path"))
    shared = 0
    for left, right in zip(noted, landed):
        if left != right:
            break
        shared += 1
    if shared >= len(noted):
        return "same-path" if landed == noted else "descendant"
    if shared == len(landed):
        return "ancestor"
    return "elsewhere"


def cell_counts(pairs, predicate, keep=None) -> dict:
    counts = collections.defaultdict(lambda: [0, 0])
    for cell, index, previous, row in pairs:
        if keep is not None and not keep(cell, index, previous, row):
            continue
        counts[cell][0] += 1
        counts[cell][1] += bool(predicate(previous, row))
    return dict(counts)


def pooled(counts: dict) -> tuple[int, int]:
    return sum(v[0] for v in counts.values()), sum(v[1] for v in counts.values())


def sign_flip(counts_leg: dict, counts_rep: dict, seed: int = SEED,
              n_perms: int = N_PERMS) -> tuple[float, float, int]:
    """§2.2's paired sign-flip, reported in row 4's direction: the returned
    p-value is one-sided `repr > legible`. **Post-hoc everywhere it is called
    below** — the confirmatory use of this test was `legibility_compare.py`'s
    single pre-registered run.
    """
    keys = sorted(set(counts_leg) | set(counts_rep))
    n_leg = np.array([counts_leg.get(k, [0, 0])[0] for k in keys], dtype=np.int64)
    k_leg = np.array([counts_leg.get(k, [0, 0])[1] for k in keys], dtype=np.int64)
    n_rep = np.array([counts_rep.get(k, [0, 0])[0] for k in keys], dtype=np.int64)
    k_rep = np.array([counts_rep.get(k, [0, 0])[1] for k in keys], dtype=np.int64)
    if not n_leg.sum() or not n_rep.sum():
        return 0.0, 1.0, len(keys)
    observed = k_leg.sum() / n_leg.sum() - k_rep.sum() / n_rep.sum()
    rng = np.random.default_rng(seed)
    flip = rng.random((n_perms, len(n_leg))) < 0.5
    null = (np.where(flip, k_rep, k_leg).sum(axis=1) / np.where(flip, n_rep, n_leg).sum(axis=1)
            - np.where(flip, k_leg, k_rep).sum(axis=1) / np.where(flip, n_leg, n_rep).sum(axis=1))
    p_reverse = (1 + int(np.sum(null <= observed))) / (n_perms + 1)
    return float(observed), float(p_reverse), len(keys)


def signflip_type_one_error(counts_leg: dict, counts_rep: dict,
                            sims: int = None, seed: int = SEED) -> float:
    """How often does §2.2's test fire in *either* tail when there is no
    effect at all, at this arm's own cell sizes?

    A reverse-significant primary is the kind of result that invites "the test
    was wrong". This answers that directly rather than by argument: cell rates
    are drawn from the plan's own banked beta-binomial fit (§2.2, a = 2.9925,
    b = 4.9959), the *same* rate is used for both arms — the sharp null — and
    each arm's draws are binomial at the observed per-cell denominators. The
    returned figure is comparable against 0.10, because §6's decision rule
    reads both tails at alpha = 0.05.
    """
    sims = CALIBRATION_SIMS if sims is None else sims
    keys = sorted(set(counts_leg) | set(counts_rep))
    n_leg = np.array([counts_leg.get(k, [0, 0])[0] for k in keys], dtype=np.int64)
    n_rep = np.array([counts_rep.get(k, [0, 0])[0] for k in keys], dtype=np.int64)
    keep = (n_leg > 0) & (n_rep > 0)
    n_leg, n_rep = n_leg[keep], n_rep[keep]
    rng = np.random.default_rng(seed)
    fired = 0
    for index in range(sims):
        shared = rng.beta(BANKED_BETA_A, BANKED_BETA_B, size=len(n_leg))
        k_leg = rng.binomial(n_leg, shared)
        k_rep = rng.binomial(n_rep, shared)
        left = dict(zip(range(len(n_leg)), zip(n_leg.tolist(), k_leg.tolist())))
        right = dict(zip(range(len(n_rep)), zip(n_rep.tolist(), k_rep.tolist())))
        left = {k: list(v) for k, v in left.items()}
        right = {k: list(v) for k, v in right.items()}
        _, p_reverse, _ = sign_flip(left, right, seed=index + 1, n_perms=999)
        _, p_forward, _ = sign_flip(right, left, seed=index + 1, n_perms=999)
        if p_reverse < 0.05 or p_forward < 0.05:
            fired += 1
    return fired / sims


def rate(n: int, k: int) -> float:
    return k / n if n else 0.0


def band_of(index: int) -> str:
    return "1-2" if index <= 2 else "3-5" if index <= 5 else "6-10" if index <= 10 else "11+"


def split_definition(source: str | None) -> tuple[str | None, str | None]:
    """`(def ANNOTATION TERM)` -> `(annotation, term)`, by paren balance.

    Used only to ask whether a redraft rewrote the *type annotation* rather
    than the body — the shape a note that names an expected type might steer
    the model into. Returns `(None, None)` on anything that is not a `def`,
    so an unparseable draw drops out of that count instead of being guessed.
    """
    text = (source or "").strip()
    if not text.startswith("(def "):
        return None, None
    index, parts = len("(def "), []
    while index < len(text):
        while index < len(text) and text[index] == " ":
            index += 1
        if index >= len(text) or text[index] == ")":
            break
        if text[index] == "(":
            depth, cursor = 0, index
            while cursor < len(text):
                if text[cursor] == "(":
                    depth += 1
                elif text[cursor] == ")":
                    depth -= 1
                    if depth == 0:
                        cursor += 1
                        break
                cursor += 1
            parts.append(text[index:cursor])
            index = cursor
        else:
            cursor = index
            while cursor < len(text) and text[cursor] not in " )":
                cursor += 1
            parts.append(text[index:cursor])
            index = cursor
    return (parts[0] if parts else None, parts[1] if len(parts) > 1 else None)


def similarity(left: str | None, right: str | None) -> float:
    return difflib.SequenceMatcher(None, left or "", right or "", autojunk=False).ratio()


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def section_integrity(ctx) -> bool:
    print("### 0 — integrity: is the row-4 verdict resting on sound records?")
    print()
    ok = True

    banked_cells = by_cell(ctx["banked"])
    repr_cells = by_cell(ctx["records"][REPR])
    identical = (len(ctx["banked"]) == len(ctx["records"][REPR]) and all(
        len(banked_cells[c]) == len(repr_cells[c])
        and all(a["identity"] == b["identity"] for a, b in zip(banked_cells[c], repr_cells[c]))
        for c in repr_cells))
    print(f"  C1 re-asserted: the `repr` arm reproduces `{BANKED}` draw-for-draw by "
          f"`identity`: {identical}")
    ok &= identical

    for arm in (LEGIBLE, REPR):
        rows = ctx["records"][arm]
        duplicates = [k for k, v in collections.Counter(
            (r["task"], r["seed"], r["round"]) for r in rows).items() if v > 1]
        contiguous = all(sorted(r["round"] for r in cell) == list(range(len(cell)))
                         for cell in by_cell(rows).values())
        roles = set(r["role"] for r in rows)
        retried = set(r["retried"] for r in rows)
        round0 = sum(1 for r in rows if r["round"] == 0 and r.get("narrowed") is True)
        print(f"  {arm:<14} duplicate (task,seed,round): {len(duplicates)}   "
              f"rounds contiguous 0..n-1 in every cell: {contiguous}   "
              f"roles {sorted(roles)}   retried {sorted(retried)}   "
              f"round-0 draws flagged narrowed: {round0}")
        ok &= not duplicates and contiguous and roles == {"whole"} and retried == {False} and round0 == 0

    for arm in (LEGIBLE, REPR):
        bad = ctx["mismatched"][arm]
        rejected = sum(1 for r in ctx["records"][arm] if r["funnel_outcome"] != "accepted")
        print(f"  {arm:<14} replay reproduces the banked `error_message` on "
              f"{rejected - len(bad)}/{rejected} rejected draws; mismatches: {len(bad)}")
        ok &= not bad

    print()
    print("  L1's walk is order-sensitive (predecessor = rows[i-1] after sorting by `round`),")
    print("  so contiguity and uniqueness of `round` are what make it well-defined. Both hold.")
    print()
    counts_leg = cell_counts(ctx["pairs"][LEGIBLE], repairs_locally)
    counts_rep = cell_counts(ctx["pairs"][REPR], repairs_locally)
    hit_rate = signflip_type_one_error(counts_leg, counts_rep)
    calibrated = 0.07 <= hit_rate <= 0.13
    print(f"  Type-I calibration of the pre-registered test, at this arm's own cell sizes:")
    print(f"    P(either one-sided p < 0.05) under a no-effect beta-binomial null, "
          f"{CALIBRATION_SIMS} simulations: {hit_rate:.4f}")
    print(f"    §6's decision rule is two-tailed (rows 1 and 4 read opposite tails), so the")
    print(f"    nominal rate is 0.10. The test is {'calibrated' if calibrated else 'MISCALIBRATED'}"
          f" — row 4 is not a broken test.")
    ok &= calibrated
    print()
    print(f"  VERDICT: {'no harness defect found — the row-4 result rests on sound records' if ok else 'INTEGRITY FAILURE — read nothing below as a finding about the model'}")
    print()
    return ok


def section_exposure(ctx) -> bool:
    print("### 1 — the exposure map: how much of L1's denominator did the seam actually touch?")
    print()
    print("  A note the seam cannot change is a note with no rendered type in it. Each")
    print("  rejected draw is replayed under both renders; `exposed` means the two")
    print("  renderings differ, i.e. the two arms genuinely saw different text.")
    print()
    for arm in (LEGIBLE, REPR):
        rejected = [r for r in ctx["records"][arm] if r["funnel_outcome"] != "accepted"]
        exposed = sum(1 for r in rejected
                      if ctx["notes"][arm][(r["task"], r["seed"], r["round"])][0]
                      != ctx["notes"][arm][(r["task"], r["seed"], r["round"])][1])
        print(f"  {arm:<14} rejected draws {len(rejected):>4}   render-sensitive "
              f"{exposed:>4} = {exposed / len(rejected):6.2%}")
    print()
    for arm in (LEGIBLE, REPR):
        pairs = ctx["pairs"][arm]
        exposed = sum(1 for _, _, p, _ in pairs if is_exposed(ctx["notes"][arm], p))
        print(f"  {arm:<14} L1-eligible pairs {len(pairs):>4}   of which exposed "
              f"{exposed:>4} = {exposed / len(pairs):6.2%}")
    print()
    print("  The two arms' exposure shares are within a point of each other, so the")
    print("  stratification below is not itself an arm difference.")
    print()
    return True


def _stratum_row(ctx, label, keep, predicate=repairs_locally):
    counts = {arm: cell_counts(ctx["pairs"][arm], predicate,
                               keep(arm) if callable(keep) else keep)
              for arm in (LEGIBLE, REPR)}
    n_leg, k_leg = pooled(counts[LEGIBLE])
    n_rep, k_rep = pooled(counts[REPR])
    diff, p_rev, pairs = sign_flip(counts[LEGIBLE], counts[REPR])
    print(f"  {label:<34} legible {k_leg:>3}/{n_leg:<4} = {rate(n_leg, k_leg):6.2%}   "
          f"repr {k_rep:>3}/{n_rep:<4} = {rate(n_rep, k_rep):6.2%}   "
          f"diff {diff * 100:+6.2f} pts   p = {p_rev:.4f}  ({pairs} cell pairs)")
    return (n_leg, k_leg), (n_rep, k_rep), diff


def section_headline(ctx) -> bool:
    print("### 2 — the headline: the reverse effect lives entirely in the exposed stratum")
    print()
    print("  Paired sign-flip over `(task, seed)` cell pairs, statistic = pooled rate")
    print("  difference (legible - repr), p one-sided in row 4's direction (repr > legible),")
    print(f"  {N_PERMS} permutations, seed {SEED}. **Post-hoc: exploratory, not confirmatory.**")
    print()
    exposed = lambda arm: (lambda c, i, p, r: is_exposed(ctx["notes"][arm], p))
    unexposed = lambda arm: (lambda c, i, p, r: not is_exposed(ctx["notes"][arm], p))
    all_l1 = _stratum_row(ctx, "all L1-eligible (the verdict)", None)
    exp = _stratum_row(ctx, "exposed (note bytes differ)", exposed)
    unexp = _stratum_row(ctx, "unexposed (identical notes)", unexposed)
    print()
    (nle, kle), (nre, kre), _ = exp
    print(f"  Risk ratio in the exposed stratum: "
          f"{rate(nle, kle) / rate(nre, kre):.3f}  (legible / repr)")
    print()
    print("  The unexposed stratum is an internal placebo. Both arms received a")
    print("  byte-identical note there; they differ only in the trajectory that got")
    print("  them to it. It carries every source of between-arm divergence except the")
    print("  treatment, and it is null.")
    print()

    # Oaxaca-style split of the headline diff into composition and behaviour.
    strata = {}
    for arm, keep in ((LEGIBLE, exposed(LEGIBLE)), (REPR, exposed(REPR))):
        for flag, condition in ((True, keep),
                                (False, lambda c, i, p, r, a=arm: not is_exposed(ctx["notes"][a], p))):
            counts = cell_counts(ctx["pairs"][arm], repairs_locally,
                                 condition if flag else condition)
            strata[(arm, flag)] = pooled(counts)
    totals = {arm: sum(strata[(arm, f)][0] for f in (True, False)) for arm in (LEGIBLE, REPR)}
    base = sum(strata[(REPR, f)][1] for f in (True, False)) / totals[REPR]
    composition = sum(strata[(LEGIBLE, f)][0] * rate(*strata[(REPR, f)])
                      for f in (True, False)) / totals[LEGIBLE]
    behaviour = sum(strata[(REPR, f)][0] * rate(*strata[(LEGIBLE, f)])
                    for f in (True, False)) / totals[REPR]
    print("  Decomposition of the -2.20 pt headline (repr composition/rates as the base):")
    print(f"    composition — which kind of note the drafts earned : {100 * (composition - base):+6.2f} pts")
    print(f"    behaviour   — what the model did with the note      : {100 * (behaviour - base):+6.2f} pts")
    print()
    print("  Dilution: the exposed effect is diluted by the unexposed majority. The")
    print("  arm's pre-registered endpoint therefore *understates* the treated effect")
    print(f"  by roughly {abs(exp[2] / all_l1[2]):.1f}x.")
    print()
    return True


def section_rivals(ctx) -> bool:
    exposed = lambda arm: (lambda c, i, p, r: is_exposed(ctx["notes"][arm], p))

    print("### 3 — rival (a): prompt-length / token-budget artefact")
    print()
    for arm in (LEGIBLE, REPR):
        pairs = [(p, r) for c, i, p, r in ctx["pairs"][arm] if is_exposed(ctx["notes"][arm], p)]
        note_len = [len(p["error_message"] or "") for p, _ in pairs]
        prompt = [r["tokens_prompt"] for _, r in pairs]
        print(f"  {arm:<14} exposed pairs {len(pairs):>4}   note length "
              f"mean {statistics.mean(note_len):6.1f} chars   "
              f"prompt tokens mean {statistics.mean(prompt):8.1f}")
    print()
    print("  Dose form — L1 against note length *within* arm (a length effect would show")
    print("  up here whatever the render):")
    for arm in (LEGIBLE, REPR):
        pairs = [(p, r) for c, i, p, r in ctx["pairs"][arm] if is_exposed(ctx["notes"][arm], p)]
        x = np.array([len(p["error_message"] or "") for p, _ in pairs], dtype=float)
        y = np.array([float(repairs_locally(p, r)) for p, r in pairs])
        quartiles = np.quantile(x, [0.0, 0.25, 0.5, 0.75, 1.0])
        cells = []
        for lo, hi in zip(quartiles[:-1], quartiles[1:]):
            mask = (x >= lo) & (x <= hi)
            cells.append(f"[{int(lo)},{int(hi)}] {y[mask].mean():5.1%} (n={int(mask.sum())})")
        print(f"  {arm:<14} corr(note length, local) = {np.corrcoef(x, y)[0, 1]:+.4f}   "
              + "  ".join(cells))
    print()
    charged_on_completion = all(
        row["tokens_remaining"] == row["budget"] - row["tokens_used"]
        and row["tokens_used"] >= row["tokens_completion"]
        for arm in (LEGIBLE, REPR) for row in ctx["records"][arm])
    completion_only = all(
        row["tokens_used"] == sum(r["tokens_completion"] for r in cell[:index + 1])
        for arm in (LEGIBLE, REPR)
        for cell in by_cell(ctx["records"][arm]).values()
        for index, row in enumerate(cell))
    print(f"  The purse is charged on completion tokens only, checked rather than assumed:")
    print(f"    `tokens_remaining == budget - tokens_used` on every record: {charged_on_completion}")
    print(f"    `tokens_used` is the running sum of `tokens_completion`:     {completion_only}")
    print("  So a longer prompt costs the arm nothing it could otherwise have spent, and")
    print("  the note's length cannot buy or cost a draw.")
    print()

    print("### 4 — rival (b): wording steer — does the legible note invite restructuring?")
    print()
    print("  Did the redraft rewrite the type ANNOTATION rather than the body?")
    for flag, label in ((True, "exposed"), (False, "unexposed")):
        for arm in (LEGIBLE, REPR):
            pairs = [(p, r) for c, i, p, r in ctx["pairs"][arm]
                     if is_exposed(ctx["notes"][arm], p) is flag]
            changed = total = body = 0
            for p, r in pairs:
                a1, t1 = split_definition(p.get("source"))
                a2, t2 = split_definition(r.get("source"))
                if a1 is None or a2 is None:
                    continue
                total += 1
                changed += a1 != a2
                body += t1 != t2
            print(f"  {label:<10} {arm:<14} annotation changed {changed:>3}/{total:<4} = "
                  f"{rate(total, changed):6.2%}   body changed {body:>3}/{total:<4} = "
                  f"{rate(total, body):6.2%}")
    print()
    print("  Is an annotation rewrite itself non-local? (pooled over both arms — a")
    print("  descriptive association, not an arm contrast):")
    table = collections.defaultdict(lambda: [0, 0])
    for arm in (LEGIBLE, REPR):
        for c, i, p, r in ctx["pairs"][arm]:
            a1, _ = split_definition(p.get("source"))
            a2, _ = split_definition(r.get("source"))
            if a1 is None or a2 is None:
                continue
            table[a1 != a2][0] += 1
            table[a1 != a2][1] += repairs_locally(p, r)
    for changed in (False, True):
        n, k = table[changed]
        print(f"    annotation rewritten = {str(changed):<5}  L1 {k:>3}/{n:<4} = {rate(n, k):6.2%}")
    print()
    print("  Note-copying — does the note's named `expected T` surface turn up verbatim")
    print("  in the redraft when it was not in the draft before? (0 % under `repr` by")
    print("  construction: a `b'...'` repr is not emittable under the grammar mask.)")
    for arm in (LEGIBLE, REPR):
        eligible = copied = copied_local = 0
        for c, i, p, r in ctx["pairs"][arm]:
            if not is_exposed(ctx["notes"][arm], p):
                continue
            match = EXPECTED_CLAUSE.search(p["error_message"] or "")
            if not match or len(match.group(1).strip()) < 8:
                continue
            named = match.group(1).strip()
            eligible += 1
            fresh = named in (r.get("source") or "") and named not in (p.get("source") or "")
            copied += fresh
            copied_local += fresh and repairs_locally(p, r)
        print(f"  {arm:<14} exposed pairs naming a type {eligible:>4}   "
              f"named type newly verbatim in the redraft {copied:>3} = {rate(eligible, copied):6.2%}   "
              f"of those, local {copied_local}")
    print()

    print("### 5 — rival (c): locality-metric artefact")
    print()
    print("  (c.i) L1's structurally degenerate share — a noted path of depth <= 2")
    print("  (`''`, `definition`, `definition.term`) is local for *every* successor:")
    for arm in (LEGIBLE, REPR):
        pairs = ctx["pairs"][arm]
        degenerate = sum(1 for _, _, p, _ in pairs if len(_segments(p.get("error_path"))) <= 2)
        hits = sum(1 for _, _, p, r in pairs if repairs_locally(p, r))
        print(f"  {arm:<14} auto-local {degenerate:>3}/{len(pairs):<4} = "
              f"{rate(len(pairs), degenerate):6.2%} of the denominator, "
              f"{rate(hits, degenerate):6.1%} of all L1 hits")
    print()
    print("  (c.ii) L1 by noted-path depth, and the composition/behaviour split of the")
    print("  headline over depth:")
    print(f"  {'depth':>6}  {'legible':>18}  {'repr':>18}")
    depth_counts = {arm: collections.defaultdict(lambda: [0, 0]) for arm in (LEGIBLE, REPR)}
    for arm in (LEGIBLE, REPR):
        for c, i, p, r in ctx["pairs"][arm]:
            d = len(_segments(p.get("error_path")))
            depth_counts[arm][d][0] += 1
            depth_counts[arm][d][1] += repairs_locally(p, r)
    depths = sorted(set(depth_counts[LEGIBLE]) | set(depth_counts[REPR]))
    for d in depths:
        ln, lk = depth_counts[LEGIBLE][d]
        rn, rk = depth_counts[REPR][d]
        print(f"  {d:>6}  {lk:>4}/{ln:<4} {rate(ln, lk):7.2%}  {rk:>4}/{rn:<4} {rate(rn, rk):7.2%}")
    n_leg = sum(v[0] for v in depth_counts[LEGIBLE].values())
    n_rep = sum(v[0] for v in depth_counts[REPR].values())
    base = sum(v[1] for v in depth_counts[REPR].values()) / n_rep
    comp = sum(depth_counts[LEGIBLE][d][0] * rate(*depth_counts[REPR][d]) for d in depths) / n_leg
    behav = sum(depth_counts[REPR][d][0] * rate(*depth_counts[LEGIBLE][d]) for d in depths) / n_rep
    print(f"    depth composition effect {100 * (comp - base):+6.2f} pts   "
          f"within-depth behaviour {100 * (behav - base):+6.2f} pts")
    print()
    print("  (c.iii) redraft length — a mechanically longer redraft would drift further:")
    for arm in (LEGIBLE, REPR):
        pairs = [(p, r) for c, i, p, r in ctx["pairs"][arm]]
        print(f"  {arm:<14} predecessor {statistics.mean(len(p['source']) for p, _ in pairs):7.1f} chars   "
              f"redraft delta {statistics.mean(len(r['source']) - len(p['source']) for p, r in pairs):+7.1f}   "
              f"completion tokens {statistics.mean(r['tokens_completion'] for _, r in pairs):7.1f}")
    print()
    print("  (c.iv) L1 by draw index within the cell:")
    index_counts = {arm: collections.defaultdict(lambda: [0, 0]) for arm in (LEGIBLE, REPR)}
    for arm in (LEGIBLE, REPR):
        for c, i, p, r in ctx["pairs"][arm]:
            index_counts[arm][band_of(i)][0] += 1
            index_counts[arm][band_of(i)][1] += repairs_locally(p, r)
    for b in INDEX_BANDS:
        ln, lk = index_counts[LEGIBLE][b]
        rn, rk = index_counts[REPR][b]
        print(f"  {b:>6}  legible {lk:>3}/{ln:<4} = {rate(ln, lk):6.2%}   "
              f"repr {rk:>3}/{rn:<4} = {rate(rn, rk):6.2%}   "
              f"diff {100 * (rate(ln, lk) - rate(rn, rk)):+6.2f} pts")
    print()

    print("### 6 — rival (d): heterogeneity — broad, or a few cells?")
    print()
    task_counts = {arm: collections.defaultdict(lambda: [0, 0]) for arm in (LEGIBLE, REPR)}
    for arm in (LEGIBLE, REPR):
        for c, i, p, r in ctx["pairs"][arm]:
            task_counts[arm][c[0]][0] += 1
            task_counts[arm][c[0]][1] += repairs_locally(p, r)
    for task in sorted(task_counts[LEGIBLE]):
        ln, lk = task_counts[LEGIBLE][task]
        rn, rk = task_counts[REPR][task]
        print(f"  {task:<32} legible {lk:>3}/{ln:<4} = {rate(ln, lk):6.2%}   "
              f"repr {rk:>3}/{rn:<4} = {rate(rn, rk):6.2%}   "
              f"diff {100 * (rate(ln, lk) - rate(rn, rk)):+6.2f} pts")
    counts_leg = cell_counts(ctx["pairs"][LEGIBLE], repairs_locally)
    counts_rep = cell_counts(ctx["pairs"][REPR], repairs_locally)
    keys = sorted(set(counts_leg) | set(counts_rep))
    diffs = [rate(*counts_leg.get(k, [0, 0])) - rate(*counts_rep.get(k, [0, 0])) for k in keys]
    negative = sum(1 for d in diffs if d < 0)
    positive = sum(1 for d in diffs if d > 0)
    print()
    print(f"  per-cell rate differences over {len(keys)} pairs: "
          f"{negative} negative, {positive} positive, {len(keys) - negative - positive} exactly zero; "
          f"mean {100 * statistics.mean(diffs):+.2f} pts, median {100 * statistics.median(diffs):+.2f} pts")
    tasks_negative = sum(1 for t in task_counts[LEGIBLE]
                         if rate(*task_counts[LEGIBLE][t]) < rate(*task_counts[REPR][t]))
    print(f"  tasks with a negative difference: {tasks_negative}/{len(task_counts[LEGIBLE])}")
    print()
    return True


def section_conservatism(ctx) -> bool:
    print("### 7 — the conservatism reading's scorecard")
    print()
    print("  §6 row 4's own hypothesis: an unreadable note makes the model conservative")
    print("  about touching the noted region, so it repairs locally because it cannot")
    print("  read enough to justify a broader rewrite. That predicts, for `repr`:")
    print("  smaller edits, more of the predecessor surviving, shorter redrafts.")
    print()
    for flag, label in ((True, "exposed"), (False, "unexposed")):
        for arm in (LEGIBLE, REPR):
            pairs = [(p, r) for c, i, p, r in ctx["pairs"][arm]
                     if is_exposed(ctx["notes"][arm], p) is flag]
            sims = [similarity(p.get("source"), r.get("source")) for p, r in pairs]
            deltas = [len(r["source"]) - len(p["source"]) for p, r in pairs]
            unchanged = sum(1 for p, r in pairs if p.get("source") == r.get("source"))
            print(f"  {label:<10} {arm:<14} n={len(pairs):<4} "
                  f"similarity to predecessor mean {statistics.mean(sims):.4f} "
                  f"median {statistics.median(sims):.4f}   "
                  f"length delta {statistics.mean(deltas):+7.1f} chars   "
                  f"completion {statistics.mean(r['tokens_completion'] for _, r in pairs):6.1f} tok   "
                  f"draft reproduced verbatim {unchanged}")
    print()
    print("  Where the next failure landed, relative to the path the note named:")
    for flag, label in ((True, "exposed"), (False, "unexposed")):
        for arm in (LEGIBLE, REPR):
            pairs = [(p, r) for c, i, p, r in ctx["pairs"][arm]
                     if is_exposed(ctx["notes"][arm], p) is flag]
            counter = collections.Counter(landing(p, r) for p, r in pairs)
            n = len(pairs)
            cells = "  ".join(f"{k}={counter[k]:>3} ({rate(n, counter[k]):5.1%})"
                              for k in ("accepted", "same-path", "descendant", "ancestor", "elsewhere"))
            print(f"  {label:<10} {arm:<14} n={n:<4} {cells}")
    print()
    print("  Acceptance on the same draws — the outcome L1 is a proxy for:")
    for flag, label in ((True, "exposed"), (False, "unexposed")):
        for arm in (LEGIBLE, REPR):
            rows = [r for c, i, p, r in ctx["pairs"][arm]
                    if is_exposed(ctx["notes"][arm], p) is flag]
            accepted = sum(1 for r in rows if r["funnel_outcome"] == "accepted")
            print(f"  {label:<10} {arm:<14} accepted {accepted:>3}/{len(rows):<4} = "
                  f"{rate(len(rows), accepted):6.2%}")
    print()
    print("  Does the effect scale with how ACTIONABLE the named type is? A content-steering")
    print("  mechanism should be larger where the surface names something the model could")
    print("  copy and use. The split is arm-symmetric: it is computed from the *surface*")
    print("  rendering of the same note, which the replay gives for both arms.")
    for label, predicate in (
            ("hash-free surface (I64, Bool, (fn …))", lambda t: t is not None and "0x" not in t),
            ("hash-bearing surface ((data 0x…))", lambda t: t is not None and "0x" in t),
            ("no `expected T` clause at all", lambda t: t is None)):
        row = []
        for arm in (LEGIBLE, REPR):
            n = k = 0
            for cell, index, previous, draw in ctx["pairs"][arm]:
                if not is_exposed(ctx["notes"][arm], previous):
                    continue
                surface, _ = ctx["notes"][arm][
                    (previous["task"], previous["seed"], previous["round"])]
                match = EXPECTED_CLAUSE.search(surface)
                if not predicate(match.group(1).strip() if match else None):
                    continue
                n += 1
                k += repairs_locally(previous, draw)
            row.append((n, k))
        (n_leg, k_leg), (n_rep, k_rep) = row
        print(f"  {label:<40} legible {k_leg:>3}/{n_leg:<4} = {rate(n_leg, k_leg):6.2%}   "
              f"repr {k_rep:>3}/{n_rep:<4} = {rate(n_rep, k_rep):6.2%}   "
              f"diff {100 * (rate(n_leg, k_leg) - rate(n_rep, k_rep)):+6.2f} pts")
    print()
    return True


def section_matched(ctx) -> bool:
    print("### 8 — the matched-predecessor sub-experiment")
    print()
    print("  Both arms share `draw_seed` and every field but the render, so a cell's")
    print("  draws stay byte-identical until the first draw whose note differed. At")
    print("  that draw the two arms have the *same* predecessor draft, the same error,")
    print("  the same noted path — the cleanest one-bit contrast the arm contains.")
    print()
    matched = []
    for cell in sorted(by_cell(ctx["records"][LEGIBLE])):
        left = by_cell(ctx["records"][LEGIBLE])[cell]
        right = by_cell(ctx["records"][REPR])[cell]
        index = 0
        while index < min(len(left), len(right)) and left[index]["identity"] == right[index]["identity"]:
            index += 1
        if index == 0 or index >= min(len(left), len(right)):
            continue
        matched.append((cell, index, left[index - 1], right[index - 1], left[index], right[index]))
    print(f"  matched decision points: {len(matched)} of {len(by_cell(ctx['records'][LEGIBLE]))} cells")
    note_differed = sum(1 for _, _, pa, pb, _, _ in matched
                        if pa["error_message"] != pb["error_message"])
    print(f"  of which the predecessor's note differed between arms: {note_differed}")
    print("  (A cell cannot diverge on anything else: identical prompt + identical seed")
    print("  gives an identical draw, so divergence *is* the note.)")
    print()
    hits = {LEGIBLE: 0, REPR: 0}
    for _, _, pa, pb, ra, rb in matched:
        hits[LEGIBLE] += repairs_locally(pa, ra)
        hits[REPR] += repairs_locally(pb, rb)
    for arm in (LEGIBLE, REPR):
        print(f"  {arm:<14} L1 at the matched draw {hits[arm]:>3}/{len(matched):<4} = "
              f"{rate(len(matched), hits[arm]):6.2%}")
    both = sum(1 for _, _, pa, pb, ra, rb in matched
               if repairs_locally(pa, ra) and repairs_locally(pb, rb))
    leg_only = sum(1 for _, _, pa, pb, ra, rb in matched
                   if repairs_locally(pa, ra) and not repairs_locally(pb, rb))
    rep_only = sum(1 for _, _, pa, pb, ra, rb in matched
                   if not repairs_locally(pa, ra) and repairs_locally(pb, rb))
    neither = len(matched) - both - leg_only - rep_only
    print(f"  McNemar table: both local {both}, legible only {leg_only}, repr only "
          f"{rep_only}, neither {neither}")
    # Exact two-sided binomial on the discordant pairs, computed without SciPy.
    discordant = leg_only + rep_only
    if discordant:
        from math import comb
        tail = sum(comb(discordant, i) for i in range(min(leg_only, rep_only) + 1))
        p_exact = min(1.0, 2 * tail / (2 ** discordant))
    else:
        p_exact = 1.0
    print(f"  exact two-sided binomial on the {discordant} discordant pairs: p = {p_exact:.4f}")
    print("  **Post-hoc, and underpowered** — the matched contrast is one draw per cell.")
    print("  It is reported for its direction and its cleanliness, not for its p-value.")
    print()
    for arm, prev_idx, row_idx in ((LEGIBLE, 2, 4), (REPR, 3, 5)):
        counter = collections.Counter(landing(m[prev_idx], m[row_idx]) for m in matched)
        sims = [similarity(m[prev_idx].get("source"), m[row_idx].get("source")) for m in matched]
        deltas = [len(m[row_idx]["source"]) - len(m[prev_idx]["source"]) for m in matched]
        print(f"  {arm:<14} " + "  ".join(f"{k}={counter[k]}" for k in
              ("accepted", "same-path", "descendant", "ancestor", "elsewhere"))
              + f"   similarity {statistics.mean(sims):.4f}   length delta {statistics.mean(deltas):+.1f}")
    prompt_delta = [m[4]["tokens_prompt"] - m[5]["tokens_prompt"] for m in matched]
    print(f"  prompt-token difference at the matched draw (legible - repr): "
          f"mean {statistics.mean(prompt_delta):+.1f}, median {statistics.median(prompt_delta):+.0f}, "
          f"range [{min(prompt_delta)}, {max(prompt_delta)}]")
    print()
    return True


def section_variants(ctx) -> bool:
    print("### 9 — endpoint-variant robustness")
    print()
    print("  L1 counts a draw that reproduces the *same* failure at the *same* path as")
    print("  a local repair — a stuck model scores maximally local. `L1-strict` closes")
    print("  that loophole and nothing else. Both are shown on all three strata.")
    print(f"  **All post-hoc.** p one-sided in row 4's direction, {N_PERMS} permutations, seed {SEED}.")
    print()
    exposed = lambda arm: (lambda c, i, p, r: is_exposed(ctx["notes"][arm], p))
    unexposed = lambda arm: (lambda c, i, p, r: not is_exposed(ctx["notes"][arm], p))
    for name, predicate in (("L1 (as pre-registered)", repairs_locally),
                            ("L1-strict", strict_repair)):
        print(f"  {name}")
        _stratum_row(ctx, "  all L1-eligible", None, predicate)
        _stratum_row(ctx, "  exposed", exposed, predicate)
        _stratum_row(ctx, "  unexposed (placebo)", unexposed, predicate)
        print()
    return True


def section_replication(ctx) -> bool:
    print("### 10 — would a replication find this again?")
    print()
    print("  The exposed-stratum effect is the finding a follow-up arm would have to")
    print("  reproduce. This prices that arm before anyone proposes it: cell rates drawn")
    print("  from a beta-binomial fitted to the `repr` arm's own exposed cells, cell")
    print("  sizes held at the observed ones, the same paired sign-flip at alpha = 0.05,")
    print(f"  one-sided in row 4's direction, {REPLICATION_SIMS} simulations, seed {SEED}.")
    print()
    exposed_leg = cell_counts(ctx["pairs"][LEGIBLE], repairs_locally,
                              lambda c, i, p, r: is_exposed(ctx["notes"][LEGIBLE], p))
    exposed_rep = cell_counts(ctx["pairs"][REPR], repairs_locally,
                              lambda c, i, p, r: is_exposed(ctx["notes"][REPR], p))
    keys = sorted(set(exposed_leg) | set(exposed_rep))
    n_leg = np.array([exposed_leg.get(k, [0, 0])[0] for k in keys], dtype=np.int64)
    n_rep = np.array([exposed_rep.get(k, [0, 0])[0] for k in keys], dtype=np.int64)
    k_rep = np.array([exposed_rep.get(k, [0, 0])[1] for k in keys], dtype=np.int64)
    keep = (n_leg > 0) & (n_rep > 0)
    alpha, beta = fit_beta_binomial(n_rep[keep].astype(float), k_rep[keep].astype(float))
    observed_rr = (rate(*pooled(exposed_leg)) / rate(*pooled(exposed_rep)))
    print(f"  exposed cells {int(keep.sum())}   draws/cell: legible {n_leg[keep].mean():.2f}, "
          f"repr {n_rep[keep].mean():.2f}")
    print(f"  beta-binomial MLE on the control's exposed cells: a = {alpha:.4f}, b = {beta:.4f} "
          f"(mean {alpha / (alpha + beta):.2%})")
    print(f"  observed exposed-stratum risk ratio: {observed_rr:.3f}")
    print()
    rng = np.random.default_rng(SEED)
    for target in (observed_rr, 0.50, 0.60, 0.75, 0.85):
        fired = 0
        for index in range(REPLICATION_SIMS):
            shared = rng.beta(alpha, beta, size=int(keep.sum()))
            control = rng.binomial(n_rep[keep], shared)
            treatment = rng.binomial(n_leg[keep], np.clip(shared * target, 0.0, 1.0))
            left = {i: [int(n_leg[keep][i]), int(treatment[i])] for i in range(int(keep.sum()))}
            right = {i: [int(n_rep[keep][i]), int(control[i])] for i in range(int(keep.sum()))}
            _, p_reverse, _ = sign_flip(left, right, seed=index + 1, n_perms=999)
            fired += p_reverse < 0.05
        label = "observed" if target == observed_rr else ""
        print(f"  RR = {target:.3f} {label:<9} power {fired / REPLICATION_SIMS:.3f}")
    print()
    print("  A replication at this arm's shape is not a formality: even if the effect is")
    print("  exactly what was measured, the arm reproduces it a minority-to-bare-majority")
    print("  of the time. The observed point estimate therefore sits on the favourable")
    print("  side of a low-powered design and should be read as an upper bound.")
    print()
    return True


SECTIONS = {
    "integrity": section_integrity,
    "exposure": section_exposure,
    "headline": section_headline,
    "rivals": section_rivals,
    "conservatism": section_conservatism,
    "matched": section_matched,
    "variants": section_variants,
    "replication": section_replication,
}

ORDER = ("integrity", "exposure", "headline", "rivals", "conservatism", "matched",
         "variants", "replication")


def build_context(runs_dir: pathlib.Path) -> dict:
    resolver = ExperimentResolver()
    records = {arm: load_run(arm, runs_dir) for arm in (LEGIBLE, REPR)}
    notes, mismatched = {}, {}
    for arm, render in ((LEGIBLE, typecheck.NARROWING_NOTE_SURFACE),
                        (REPR, typecheck.NARROWING_NOTE_REPR)):
        notes[arm], mismatched[arm] = exposure_map(records[arm], render, resolver)
    return {
        "records": records,
        "banked": load_run(BANKED, runs_dir),
        "pairs": {arm: l1_pairs(records[arm]) for arm in (LEGIBLE, REPR)},
        "notes": notes,
        "mismatched": mismatched,
    }


def main(argv=None, runs_dir: pathlib.Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--section", choices=sorted(SECTIONS), action="append",
                        help="print only this section; repeatable (default: all).")
    parser.add_argument("--runs-dir", type=pathlib.Path, default=None,
                        help="where the run directories live (default: prototype/runs). "
                             "`runs/` is gitignored, so a worktree checkout points this "
                             "at the main checkout's copy rather than re-banking it.")
    arguments = parser.parse_args(argv)
    runs_dir = arguments.runs_dir or (RUNS if runs_dir is None else runs_dir)

    missing = [runs_dir / r / "records.jsonl" for r in (LEGIBLE, REPR, BANKED)
               if not (runs_dir / r / "records.jsonl").is_file()]
    if missing:
        print("missing run records, cannot probe:")
        for path in missing:
            print(f"  {path}")
        return 1

    print("## Feedback-legibility arm — §6 row 4 offline probe")
    print()
    print("Exploratory and post-hoc throughout. The arm's one pre-registered test has")
    print("been run and its verdict stands; nothing below re-tests it.")
    print()

    context = build_context(runs_dir)
    wanted = arguments.section or list(ORDER)
    ok = True
    for name in ORDER:
        if name in wanted:
            ok &= bool(SECTIONS[name](context))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
