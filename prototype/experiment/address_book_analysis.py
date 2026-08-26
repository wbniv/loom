"""Deliverable 6's numbers: the address-book run, analyzed per §4.5-§4.7 as
amended by Amendment A1 (docs/plans/2026-08-24-next-lever.md).

Reads prototype/runs/addr-{none,full,typed}/records.jsonl and prints every
statistic the report cites. Reuses the audit's own route machinery
(`_route_hashes`, `_REF_RE`) so the arm numbers share a code path with the
12/4,135 baseline.

Primary metric per §4.5's letter: a draw counts iff its `(ref 0x…)` set
contains EVERY element of the task's `composes` route, definitions and
externs alike. The quoted 0.290% baseline was computed definitions-only
(`addressability_audit.refs`), so the definitions-only variant is printed
beside it; the concurrent-control test makes the choice non-corrupting, and
both are reported.

Run from `prototype/`: `python3 -m experiment.address_book_analysis`
"""

import json
from math import comb
from pathlib import Path

from experiment.addressability_audit import HELD_OUT_TASKS, _REF_RE, _route_hashes
from experiment.resolver import ExperimentResolver, KIND_DATA, KIND_DEFINITION, KIND_EXTERN

ARMS = ("addr-none", "addr-full", "addr-typed")
RUNS = Path(__file__).resolve().parent.parent / "runs"


def fisher_one_sided(k1, n1, k0, n0):
    """P(X >= k1) for the 2x2 table under the null, X hypergeometric —
    one-sided 'arm 1 rate > arm 0 rate'."""
    successes, total = k1 + k0, n1 + n0
    denom = comb(total, successes)
    return sum(
        comb(n1, k) * comb(n0, successes - k)
        for k in range(k1, min(successes, n1) + 1)
        if 0 <= successes - k <= n0
    ) / denom


def fisher_two_sided(k1, n1, k0, n0):
    """Two-sided Fisher: sum of all table probabilities <= observed's."""
    successes, total = k1 + k0, n1 + n0
    denom = comb(total, successes)
    p_obs = comb(n1, k1) * comb(n0, successes - k1)
    return sum(
        p for k in range(max(0, successes - n0), min(successes, n1) + 1)
        if (p := comb(n1, k) * comb(n0, successes - k)) <= p_obs + 1e-9 * p_obs
    ) / denom


def clopper_pearson(k, n, alpha=0.05):
    """Exact binomial interval by bisection on the binomial tail."""
    def binom_cdf(x, n, p):
        return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(x + 1))

    def solve(f, lo, hi):
        for _ in range(80):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - binom_cdf(k - 1, n, p) >= alpha / 2, 0.0, k / n)
    upper = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p) <= alpha / 2, k / n, 1.0)
    return lower, upper


def load(arm):
    with open(RUNS / arm / "records.jsonl", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def arm_stats(records, resolver, required_all, required_defs):
    n = len(records)
    stats = {
        "draws": n,
        "route_all": 0,       # §4.5 letter: every route element, externs included
        "route_defs": 0,      # baseline-consistent: definition elements only
        "any_required": 0,    # >=1 required definition referenced
        "has_any_ref": 0,
        "illegal_data_ref": 0,
        "truncated": 0,
        "accepted": 0,
        "mech_floor": 0,
        "tokens_completion": 0,
        "funnel": {},
        "mech_candidates": [],
        "cells": {},
    }
    for r in records:
        refs = {m.lower() for m in _REF_RE.findall(r.get("raw", ""))}
        task = r["task"]
        if refs:
            stats["has_any_ref"] += 1
        req_all = required_all[task]
        req_defs = required_defs[task]
        if req_all and req_all <= refs:
            stats["route_all"] += 1
        if req_defs and req_defs <= refs:
            stats["route_defs"] += 1
        if refs & req_defs:
            stats["any_required"] += 1
        for h in refs:
            try:
                if resolver.resolve(bytes.fromhex(h[2:])).kind == KIND_DATA:
                    stats["illegal_data_ref"] += 1
                    break
            except (LookupError, ValueError):
                continue
        if r["stop_reason"] == "length":
            stats["truncated"] += 1
        outcome = r["funnel_outcome"]
        stats["funnel"][outcome] = stats["funnel"].get(outcome, 0) + 1
        if outcome == "accepted":
            stats["accepted"] += 1
        if r.get("semantic_success"):
            stats["mech_floor"] += 1
            stats["mech_candidates"].append(
                {"task": task, "seed": r["seed"], "draw": r["draw"],
                 "rule": r.get("semantic_rule"), "raw": r.get("raw", "")})
        stats["tokens_completion"] += r.get("tokens_completion", 0)
        stats["cells"].setdefault((task, r["seed"]), 0)
        stats["cells"][(task, r["seed"])] += 1
    return stats


def main():
    resolver = ExperimentResolver()
    required_all = _route_hashes(resolver, definitions_only=False)
    required_defs = _route_hashes(resolver, definitions_only=True)
    arms = {arm: arm_stats(load(arm), resolver, required_all, required_defs) for arm in ARMS}

    print("### Per-arm draw table\n")
    hdr = f"{'metric':<28}" + "".join(f"{arm:>12}" for arm in ARMS)
    print(hdr)
    for key in ("draws", "route_all", "route_defs", "any_required", "has_any_ref",
                "illegal_data_ref", "truncated", "accepted", "mech_floor"):
        print(f"{key:<28}" + "".join(f"{arms[a][key]:>12}" for a in ARMS))
    print(f"{'tokens_completion':<28}" + "".join(f"{arms[a]['tokens_completion']:>12}" for a in ARMS))
    print(f"{'accepted/1k tok':<28}" + "".join(
        f"{1000*arms[a]['accepted']/arms[a]['tokens_completion']:>12.3f}" for a in ARMS))
    print(f"{'truncated %':<28}" + "".join(
        f"{100*arms[a]['truncated']/arms[a]['draws']:>11.1f}%" for a in ARMS))

    print("\n### Cell integrity (exactly 8 full-cap draws per cell)\n")
    for a in ARMS:
        cells = arms[a]["cells"]
        bad = {k: v for k, v in cells.items() if v != 8}
        print(f"{a}: cells={len(cells)} draws-per-cell ok={not bad}"
              + (f" ANOMALY: {bad}" if bad else ""))

    print("\n### Funnel distribution\n")
    outcomes = sorted({o for a in ARMS for o in arms[a]["funnel"]})
    print(f"{'outcome':<28}" + "".join(f"{arm:>12}" for arm in ARMS))
    for o in outcomes:
        print(f"{o:<28}" + "".join(f"{arms[a]['funnel'].get(o, 0):>12}" for a in ARMS))

    n = {a: arms[a]["draws"] for a in ARMS}
    print("\n### Primary (A1): addr-full vs addr-none, one-sided Fisher, alpha=0.05\n")
    for metric in ("route_all", "route_defs"):
        k1, k0 = arms["addr-full"][metric], arms["addr-none"][metric]
        p = fisher_one_sided(k1, n["addr-full"], k0, n["addr-none"])
        tag = "PRIMARY (route incl. externs, §4.5 letter)" if metric == "route_all" \
            else "baseline-consistent variant (defs only)"
        print(f"{tag}: full {k1}/{n['addr-full']} vs none {k0}/{n['addr-none']}"
              f"  p={p:.6g}")

    print("\n### Exploratory (A1): addr-typed, two-sided Fisher — flagged, route-incomplete for 5/8 tasks\n")
    for metric in ("route_all", "route_defs"):
        for other in ("addr-none", "addr-full"):
            k1, k0 = arms["addr-typed"][metric], arms[other][metric]
            p = fisher_two_sided(k1, n["addr-typed"], k0, n[other])
            print(f"typed vs {other} [{metric}]: {k1}/{n['addr-typed']} vs {k0}/{n[other]}"
                  f"  p={p:.6g}")

    print("\n### Secondary: mechanical-floor semantic candidates (pending hand rubric)\n")
    for a in ARMS:
        k = arms[a]["mech_floor"]
        lo, hi = clopper_pearson(k, n[a])
        print(f"{a}: {k}/{n[a]}  CP95=[{lo:.4f}, {hi:.4f}]")
        for c in arms[a]["mech_candidates"]:
            print(f"    candidate: {c['task']} seed={c['seed']} draw={c['draw']} rule={c['rule']}")
    k1, k0 = arms["addr-full"]["mech_floor"], arms["addr-none"]["mech_floor"]
    print(f"semantic secondary full vs none (pre-hand-score): "
          f"p={fisher_one_sided(k1, n['addr-full'], k0, n['addr-none']):.6g}")

    print("\n### Per-task route_all hits\n")
    for a in ARMS:
        per_task = {}
        for r in load(a):
            refs = {m.lower() for m in _REF_RE.findall(r.get("raw", ""))}
            req = required_all[r["task"]]
            if req and req <= refs:
                per_task[r["task"]] = per_task.get(r["task"], 0) + 1
        if per_task:
            for t, c in sorted(per_task.items()):
                print(f"{a}: {t} {c}/40")
        else:
            print(f"{a}: (no task with a full-route draw)")


if __name__ == "__main__":
    main()
