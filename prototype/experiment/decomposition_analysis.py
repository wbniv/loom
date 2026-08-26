"""Deliverable 7's numbers: the decomposition run, analyzed per plan §4.5-§4.7
(docs/plans/2026-08-25-hole-decomposition.md).

Reads prototype/runs/decomp-{whole,redraft,holes}/records.jsonl and prints every
statistic the report cites. Candidates per §4.5: every draw in `whole` and
`redraft`; every `role == "candidate"` record in `holes`. A cell succeeds iff
some candidate is (a) funnel-accepted, (b) hole-free (`hole_obligations` finds
none), (c) type-exact (its declared type surface, canonicalized, equals the
task's `expected_type_surface`).

Run from `prototype/`: `python3 -m experiment.decomposition_analysis`
"""

import json
import random
from pathlib import Path

from experiment.address_book_analysis import clopper_pearson, fisher_one_sided
from experiment.addressability_audit import _REF_RE, _route_hashes
from experiment.evaluate import extract_definition
from experiment.prompts import HELD_OUT_TASKS, declared_type_of, hole_obligations
from experiment.resolver import ExperimentResolver
import sexpr
from transcode import type_to_ir

ARMS = ("decomp-whole", "decomp-redraft", "decomp-holes")
RUNS = Path(__file__).resolve().parent.parent / "runs"

EXPECTED = {t.task_id: t.expected_type_surface for t in HELD_OUT_TASKS}


def load(arm):
    with open(RUNS / arm / "records.jsonl", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def candidates_of(arm, records):
    if arm == "decomp-holes":
        return [r for r in records if r.get("role") == "candidate"]
    return records


def canonical_type_ir(source_or_surface, *, is_definition):
    """The declared type as IR — formatting-proof comparison."""
    try:
        surface = declared_type_of(extract_definition(source_or_surface)) \
            if is_definition else source_or_surface
        return type_to_ir(sexpr.parse_all(surface)[0])
    except Exception:
        return None


def candidate_source(record):
    """The candidate's definition text: `source` on a holes-arm candidate
    record (its `raw` is empty — a zero-token record), `raw` on a draw."""
    return record.get("source") or record.get("raw", "")


def type_exact(record):
    got = canonical_type_ir(candidate_source(record), is_definition=True)
    want = canonical_type_ir(EXPECTED[record["task"]], is_definition=False)
    return got is not None and got == want


def is_composed(record, resolver):
    if record["funnel_outcome"] != "accepted":
        return False
    try:
        if hole_obligations(extract_definition(candidate_source(record)), resolver):
            return False
    except Exception:
        return False
    return type_exact(record)


def main():
    resolver = ExperimentResolver()
    required_defs = _route_hashes(resolver, definitions_only=True)

    per_arm = {}
    for arm in ARMS:
        records = load(arm)
        cands = candidates_of(arm, records)
        cells = sorted({(r["task"], r["seed"]) for r in records})
        cell_ok, cell_accept, cell_typeexact, cell_route = {}, {}, {}, {}
        mech = []
        draws = [r for r in records if r.get("role") != "candidate"]
        for r in cands:
            key = (r["task"], r["seed"])
            ok = is_composed(r, resolver)
            cell_ok[key] = cell_ok.get(key, False) or ok
            cell_accept[key] = cell_accept.get(key, False) or r["funnel_outcome"] == "accepted"
            cell_typeexact[key] = cell_typeexact.get(key, False) or type_exact(r)
            if r.get("semantic_success"):
                mech.append(r)
        for r in draws:
            key = (r["task"], r["seed"])
            refs = {m.lower() for m in _REF_RE.findall(r.get("raw", ""))}
            req = required_defs[r["task"]]
            cell_route[key] = cell_route.get(key, False) or (bool(req) and req <= refs)
        per_arm[arm] = {
            "cells": cells,
            "cell_ok": cell_ok,
            "n_ok": sum(cell_ok.values()),
            "n_accept": sum(cell_accept.values()),
            "n_typeexact": sum(cell_typeexact.values()),
            "n_route": sum(cell_route.values()),
            "candidates": len(cands),
            "draws": len(draws),
            "truncated": sum(1 for r in draws if r["stop_reason"] == "length"),
            "accepted_draws": sum(1 for r in draws if r["funnel_outcome"] == "accepted"),
            "tokens_completion": sum(r.get("tokens_completion", 0) for r in draws),
            "tokens_prompt": sum(r.get("tokens_prompt", 0) for r in draws),
            "mech": mech,
        }

    print("### Per-arm cell table (64 cells each)\n")
    print(f"{'metric':<30}" + "".join(f"{a.split('-')[1]:>10}" for a in ARMS))
    for key, label in (("n_ok", "composed (PRIMARY unit)"), ("n_accept", "funnel-accepted cell"),
                       ("n_typeexact", "type-exact cell"), ("n_route", "full-route cell"),
                       ("candidates", "candidates"), ("draws", "charged draws"),
                       ("accepted_draws", "accepted draws"), ("truncated", "truncated draws"),
                       ("tokens_completion", "completion tokens"), ("tokens_prompt", "prompt tokens")):
        print(f"{label:<30}" + "".join(f"{per_arm[a][key]:>10}" for a in ARMS))
    print(f"{'truncated %':<30}" + "".join(
        f"{100*per_arm[a]['truncated']/per_arm[a]['draws']:>9.1f}%" for a in ARMS))

    n = 64
    kh, kw, kr = (per_arm[a]["n_ok"] for a in ARMS[::-1][0:1]) if False else (
        per_arm["decomp-holes"]["n_ok"], per_arm["decomp-whole"]["n_ok"],
        per_arm["decomp-redraft"]["n_ok"])
    print("\n### Primary: holes > whole, one-sided Fisher, alpha=0.05, cell-level\n")
    p = fisher_one_sided(kh, n, kw, n)
    print(f"holes {kh}/64 vs whole {kw}/64  p={p:.6g}")
    print("\n### Attribution gate (H2): holes > redraft, one-sided, alpha=0.05\n")
    p2 = fisher_one_sided(kh, n, kr, n)
    print(f"holes {kh}/64 vs redraft {kr}/64  p={p2:.6g}")
    print(f"(context: redraft {kr}/64 vs whole {kw}/64  "
          f"p={fisher_one_sided(kr, n, kw, n):.6g}, one-sided)")

    print("\n### Task-stratified permutation sensitivity (10,000 perms, seed 20260826)\n")
    rng = random.Random(20260826)
    for other in ("decomp-whole", "decomp-redraft"):
        obs = (per_arm["decomp-holes"]["n_ok"] - per_arm[other]["n_ok"]) / n
        count = 0
        by_task = {}
        for (task, seed), ok in per_arm["decomp-holes"]["cell_ok"].items():
            by_task.setdefault(task, []).append(ok)
        for (task, seed), ok in per_arm[other]["cell_ok"].items():
            by_task.setdefault(task, []).append(ok)
        for _ in range(10000):
            diff = 0
            for task, vals in by_task.items():
                shuffled = vals[:]
                rng.shuffle(shuffled)
                half = len(shuffled) // 2
                diff += sum(shuffled[:half]) - sum(shuffled[half:])
            if diff / n >= obs - 1e-12:
                count += 1
        print(f"holes vs {other.split('-')[1]}: observed diff {obs:+.4f}, "
              f"one-sided permutation p={count/10000:.4f}")

    print("\n### Secondary: mechanical-floor candidates (pending hand rubric)\n")
    for arm in ARMS:
        k = len(per_arm[arm]["mech"])
        lo, hi = clopper_pearson(min(k, n), n)
        print(f"{arm}: {k} candidate(s)  cell-CP95=[{lo:.4f}, {hi:.4f}]")
        for r in per_arm[arm]["mech"]:
            print(f"    {r['task']} seed={r['seed']} draw={r.get('draw')} "
                  f"role={r.get('role','whole')} rule={r.get('semantic_rule')}")

    print("\n### Holes-arm protocol telemetry\n")
    hrecs = load("decomp-holes")
    skels = [r for r in hrecs if r.get("role") == "skeleton"]
    cands = [r for r in hrecs if r.get("role") == "candidate"]
    acc = [r for r in skels if r["funnel_outcome"] == "accepted"]
    print(f"skeleton draws {len(skels)}, accepted {len(acc)} "
          f"({100*len(acc)/len(skels):.1f}%)")
    withholes = [r for r in acc if r.get("holes", 0) > 0]
    bare = [r for r in withholes if r.get("bare_hole_body")]
    nonbare = [r for r in withholes if not r.get("bare_hole_body")]
    print(f"accepted skeletons: hole-free {len(acc)-len(withholes)}, "
          f"bare-hole {len(bare)} (round ends unfilled by §3's rule), "
          f"non-bare with holes {len(nonbare)}")
    fillable = sum(1 for r in nonbare if r.get("holes_fillable", 0) > 0)
    reasons = {}
    for r in nonbare:
        for reason in r.get("hole_reasons", []) or []:
            reasons[reason] = reasons.get(reason, 0) + 1
    print(f"accepted non-bare skeletons with >=1 fillable hole: {fillable}; "
          f"unfillable reasons: {reasons or 'n/a'}")
    rej_holes = [r for r in skels if r.get("holes", 0) > 0
                 and r["funnel_outcome"] != "accepted"]
    print(f"hole-bearing skeletons rejected by the funnel: {len(rej_holes)} "
          f"(outcomes: { {r['funnel_outcome']: sum(1 for x in rej_holes if x['funnel_outcome']==r['funnel_outcome']) for r in rej_holes} })")
    fills = sum(r.get("fills_attempted", 0) for r in cands)
    print(f"fills attempted {fills}, spliced {sum(r.get('fills_spliced',0) for r in cands)}, "
          f"rolled back {sum(r.get('fills_rolled_back',0) for r in cands)}")
    hole_hist = {}
    for r in skels:
        hole_hist[r.get("holes", 0)] = hole_hist.get(r.get("holes", 0), 0) + 1
    print(f"holes-per-skeleton histogram: {dict(sorted(hole_hist.items()))}")


if __name__ == "__main__":
    main()
