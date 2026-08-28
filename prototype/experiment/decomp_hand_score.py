"""Hand-scoring evidence for a decomposition-family run's mechanical-floor
candidates — behavioral, by execution, not by eye.

Each unique candidate surface is evaluated on the reference interpreter and
compared against the task's verified gold term (heldout_gold.GOLD_TERMS) on a
concrete input battery. The R3 rubric's criterion is behavioral correctness
against the spec; the gold term is the spec's verified executable form, so
`candidate(args) == gold(args)` across the battery is the verdict's evidence.
A fuel exhaustion or crash on any input is a fail.

A record's `role` is deliberately not filtered on. Under the `holes`
generation protocol every round emits a paired `skeleton` record and a
`candidate` record; when the round needed no fill they carry byte-identical
source, so the `seen`-keyed dedup below collapses the pair into one verdict
line plus one `duplicate-surface` line, and a genuinely distinct surface
never collides with them. That is also what makes this loop already correct,
unmodified, on `decomp-holes` (2026‑08‑25 plan §1) and on the 14B `scale14-*`
runs (2026‑08‑28 plan §1.6) without any role-aware branching.

Which runs are scored is a **run list**, not a hard-coded arm tuple: pass
run directory names as CLI arguments (each read from `RUNS/<name>/
records.jsonl`) to score any population. With no arguments the run list
defaults to `DEFAULT_ARMS` — the original three decomposition arms — so the
bare invocation's output is unchanged from before this module took an
argument.

Exit code is the integrity contract: 0 whether or not any candidate passes
(a clean run with zero genuine successes is still exit 0 — see
2026‑08‑28 plan §6 rows D0‑a/D0‑b), and a **non-zero exit only when the
rubric itself could not be executed** — a run directory or `records.jsonl`
missing, a task with no `BATTERY` entry or no `GOLD_TERMS` entry, or the
gold term itself failing to evaluate. Those are left as uncaught exceptions
(Python's own exit-1-on-traceback) rather than caught and downgraded to a
printed line, because a surface this rubric cannot even attempt to score is
not evidence about that surface — it is a gap in the rubric's coverage,
which is what D0‑c calls out. A *candidate* that fails to evaluate, or that
exhausts fuel or crashes on one of the battery's inputs, is not an
integrity failure — the module docstring's own rule is that such an outcome
is a fail verdict, caught and printed as one.

Run from `prototype/`: `python3 -m experiment.decomp_hand_score`
Or against another run list: `python3 -m experiment.decomp_hand_score
scale14-b0 scale14-b2`
"""

import argparse
import json
from pathlib import Path

import corpus_registry
import interp
from experiment.evaluate import extract_definition
from experiment.heldout_gold import GOLD_TERMS
from experiment.resolver import ExperimentResolver
from interp import TRUE, FALSE, Interpreter, corpus_definition_terms, i64, i64_list

RUNS = Path(__file__).resolve().parent.parent / "runs"
#: The original three decomposition arms — the default run list, preserved
#: so the bare invocation's output is byte-identical to before this module
#: took a run-list argument.
DEFAULT_ARMS = ("decomp-whole", "decomp-redraft", "decomp-holes")


def machine():
    terms = corpus_definition_terms()
    return Interpreter(
        corpus_registry.registry(),
        reference_term=terms.reference_term,
        externs=interp.DEFAULT_EXTERNS,
        fuel=200_000,
    )


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "runs", nargs="*", default=list(DEFAULT_ARMS),
        help=f"run directory names under {RUNS}, each read as <name>/records.jsonl",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
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
        # (List I64) -> (List I64) -> I64 — same shape as reverseThen's
        # battery, covering both-empty, second-empty and neither-empty.
        "heldout/list/concatLength": [((i64_list([1, 2, 3]), i64_list([])), None),
                                      ((i64_list([]), i64_list([4, 5])), None),
                                      ((i64_list([1, 2]), i64_list([3, 4, 5])), None)],
        # Bool -> POS -> NAT -> NAT — both branches of the bool, at the POS/
        # NAT boundary values (POS >= 1, NAT >= 0) and away from it.
        "heldout/nat/selectNonNegative": [((TRUE, i64(5), i64(3)), None),
                                          ((FALSE, i64(5), i64(3)), None),
                                          ((TRUE, i64(1), i64(0)), None)],
    }

    seen = set()
    for arm in args.runs:
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
            for call_args, _ in BATTERY[r["task"]]:
                try:
                    got = m.apply(cand, *call_args)
                    want = m.apply(gold, *call_args)
                    verdicts.append("match" if got == want else "MISMATCH")
                except Exception as exc:
                    verdicts.append(f"ERROR:{type(exc).__name__}")
            verdict = "PASS" if all(v == "match" for v in verdicts) else "FAIL"
            print(f"{tag}  {verdict}  inputs={verdicts}")


if __name__ == "__main__":
    main()
