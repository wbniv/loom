"""Hand-scoring evidence for the decomposition run's mechanical-floor
candidates — behavioral, by execution, not by eye.

Each unique candidate surface is evaluated on the reference interpreter and
compared against the task's verified gold term (heldout_gold.GOLD_TERMS) on a
concrete input battery. The R3 rubric's criterion is behavioral correctness
against the spec; the gold term is the spec's verified executable form, so
`candidate(args) == gold(args)` across the battery is the verdict's evidence.
A fuel exhaustion or crash on any input is a fail.

Run from `prototype/`: `python3 -m experiment.decomp_hand_score`
"""

import json
from pathlib import Path

import corpus_registry
import interp
from experiment.evaluate import extract_definition
from experiment.heldout_gold import GOLD_TERMS
from experiment.resolver import ExperimentResolver
from interp import Interpreter, corpus_definition_terms, i64_list

RUNS = Path(__file__).resolve().parent.parent / "runs"
ARMS = ("decomp-whole", "decomp-redraft", "decomp-holes")


def machine():
    terms = corpus_definition_terms()
    return Interpreter(
        corpus_registry.registry(),
        reference_term=terms.reference_term,
        externs=interp.DEFAULT_EXTERNS,
        fuel=200_000,
    )


def main():
    resolver = ExperimentResolver()
    m = machine()

    add_hex = resolver.digest_for("I64.add").hex()
    plus_one = m.evaluate_source(
        f"(def (fn I64 () I64) (lam I64 (app (app (ref 0x{add_hex}) (var 0)) (lit i64 1))))")

    BATTERY = {
        "heldout/list/sum": [((i64_list([]),), None), ((i64_list([1, 2, 3]),), None),
                             ((i64_list([5, -2]),), None)],
        "heldout/list/reverseThen": [((i64_list([1, 2]), i64_list([3])), None),
                                     ((i64_list([]), i64_list([4])), None),
                                     ((i64_list([7, 8, 9]), i64_list([])), None)],
        "heldout/list/mapLength": [((plus_one, i64_list([])), None),
                                   ((plus_one, i64_list([1, 2, 3])), None),
                                   ((plus_one, i64_list([0])), None)],
    }

    seen = set()
    for arm in ARMS:
        for r in map(json.loads, open(RUNS / arm / "records.jsonl", encoding="utf-8")):
            if not r.get("semantic_success"):
                continue
            src = extract_definition(r.get("source") or r.get("raw", ""))
            key = (r["task"], src)
            tag = f"[{arm.split('-')[1]}] {r['task']} seed={r['seed']} draw={r.get('draw')}"
            if key in seen:
                print(f"{tag}  duplicate-surface (verdict above applies)")
                continue
            seen.add(key)
            gold = m.evaluate_source(GOLD_TERMS[r["task"]])
            try:
                cand = m.evaluate_source(src)
            except Exception as exc:
                print(f"{tag}  FAIL (candidate does not evaluate: {type(exc).__name__})")
                continue
            verdicts = []
            for args, _ in BATTERY[r["task"]]:
                try:
                    got = m.apply(cand, *args)
                    want = m.apply(gold, *args)
                    verdicts.append("match" if got == want else "MISMATCH")
                except Exception as exc:
                    verdicts.append(f"ERROR:{type(exc).__name__}")
            verdict = "PASS" if all(v == "match" for v in verdicts) else "FAIL"
            print(f"{tag}  {verdict}  inputs={verdicts}")


if __name__ == "__main__":
    main()
