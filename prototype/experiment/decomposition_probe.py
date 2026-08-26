"""The §1 diagnostic for hole-directed decomposition, as a runnable script.

Companion to [`docs/plans/2026-08-25-hole-decomposition.md`](../../docs/plans/2026-08-25-hole-decomposition.md).
Every number that plan's §1 and §4.7 paste is produced here, from the repository
as it stands: the checked-in corpus, the three `addr-*` record sets, and the
harness's own `run_funnel` / `score_semantic` / `build_prompt`. **No GPU, no
network, no model** — the one section that would need a tokenizer is deliberately
absent, because `heldout_gold.py` already owns that measurement.

Run every section::

    cd prototype && python3 -m experiment.decomposition_probe

or one at a time with ``--section {typeinprompt,funnel,skeleton,roundtrip,
nested,cells,holes,power}``.

What each section establishes, and why the design needs it
----------------------------------------------------------

``typeinprompt``  The task's declared type reaches the prompt for **2 of 8**
                  tasks, and only by accident (it occurs inside an example
                  definition's own surface). The other six must be guessed
                  before the mechanical floor can be met.
``funnel``        Over the three recorded `addr-*` arms: acceptance, exact-type
                  and floor counts per arm. Acceptance and type-exactness are
                  each reached often; **their conjunction — the mechanical
                  floor — essentially never is.** That conjunction is what the
                  decomposition protocol decouples.
``skeleton``      The eta-skeleton built from a task's declared type — all
                  lambdas, one hole — passes the whole funnel *and meets the
                  mechanical floor* for all eight tasks. Two facts at once: a
                  hole-bearing draft is a legal, checkable object (SPEC §2.6),
                  and `score_semantic` has a **defect** — SPEC §5.4 confines a
                  hole-bearing definition to `draft/`, so it can never be a
                  semantic success, and the floor rule does not say so.
``roundtrip``     Every gold term splits into (eta-skeleton, body) and splices
                  back byte-identically. The protocol can express every gold
                  answer — the check Amendment A1 wished it had run before
                  pre-registering `addr-typed`.
``nested``        The load-bearing case: a hole *inside* the body. Draft
                  typechecks and keeps its declared type, the sub-task's closed
                  type is derivable from the declared type alone, the fill
                  definition typechecks standalone, and the splice reproduces
                  gold. This is the mechanism end to end.
``cells``         Per-cell rates for every candidate primary metric over the
                  three recorded arms — the planning baselines §4.7 powers
                  against, plus the per-arm throughput §5 costs from.
``holes``         How often the model has *already* emitted a hole, over every
                  draw this project has recorded, and whether any such draw met
                  the floor. The floor fix is a no-op on the archive; the
                  archive also shows it was one type-guess away from firing.
``power``         Simulated one-sided Fisher power for the per-cell primary at
                  the sizes §4.7 chooses between, and the secondary's
                  success-count threshold.

The `addr-*` sections read `prototype/runs/addr-{none,full,typed}/records.jsonl`
(present in the working tree, gitignored) and are skipped with a printed notice
when they are absent, so the script still runs on a fresh checkout.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import defaultdict
from math import comb
from pathlib import Path

import sexpr
from transcode import type_to_ir, type_to_surface, transcode_source

from .evaluate import run_funnel, score_semantic
from .heldout_gold import GOLD_TERMS
from .prompts import (
    ADDRESS_BOOK_FULL,
    ADDRESS_BOOK_NONE,
    ADDRESS_BOOK_TYPED,
    HELD_OUT_TASKS,
    REGIME_HELD_OUT,
    build_prompt,
)
from .resolver import ExperimentResolver

#: The three arms of the address-book run (`docs/results/2026-08-25-address-book-report.md`).
#: They are this plan's baseline universe: same battery, same condition, same
#: store, same budgets — the only recorded runs whose numbers transfer.
ADDRESS_ARMS = ("addr-none", "addr-full", "addr-typed")

RUNS = Path("runs")

#: A `(ref 0x…)` in a canonical surface. Shared with the audit's convention so a
#: route-reference count computed here is the same quantity §4.5 reports.
REF_RE = re.compile(r"\(ref (0x[0-9a-f]{64})\)")

TASKS_BY_ID = {task.task_id: task for task in HELD_OUT_TASKS}


# --------------------------------------------------------------------------
# Type-surface plumbing — declared types only, never a gold term
# --------------------------------------------------------------------------


def peel_arrows(type_surface: str) -> tuple[list[str], list[list], str]:
    """`(domain surfaces, effect rows, body-goal surface)` of a declared type.

    Purely a function of the type. It is the whole of what the decomposition
    protocol needs to close a hole's context back into a sub-task type, and it
    is why `closed_subtask_type` never has to see a term.
    """
    ir = type_to_ir(sexpr.parse_all(type_surface)[0])
    domains: list[str] = []
    rows: list[list] = []
    current = ir
    while current[0] == 2:
        domains.append(type_to_surface(current[1]))
        rows.append(current[2])
        current = current[3]
    return domains, rows, type_to_surface(current)


def _row_surface(row) -> str:
    return "()" if not row else "(" + " ".join("0x" + digest.hex() for digest in row) + ")"


def closed_subtask_type(domains: list[str], rows: list[list], goal_surface: str) -> str:
    """Fold a hole's binder context back into a closed `(fn …)` sub-task type."""
    out = goal_surface
    for domain, row in zip(reversed(domains), reversed(rows)):
        out = f"(fn {domain} {_row_surface(row)} {out})"
    return out


def eta_skeleton(type_surface: str) -> str:
    """`(def TYPE (lam D1 … (hole GOAL ())))` — the maximal skeleton a declared
    type alone licenses. One hole, no committed structure."""
    domains, _rows, goal = peel_arrows(type_surface)
    term = f"(hole {goal} ())"
    for domain in reversed(domains):
        term = f"(lam {domain} {term})"
    return f"(def {type_surface} {term})"


def split_gold(task, gold: str) -> tuple[str, str, int]:
    """`(skeleton, body surface, lambdas peeled)` for a gold term.

    Peels exactly as many `lam` nodes as the declared type has arrows, so the
    body is the term that belongs at the eta-skeleton's single hole.
    """
    from transcode import term_to_surface

    ir, _, _ = transcode_source(gold)
    domains, _rows, goal = peel_arrows(task.expected_type_surface)
    term = ir[2]
    peeled = 0
    while peeled < len(domains) and term[0] == 3:  # lam
        term = term[2]
        peeled += 1
    if peeled != len(domains):
        return "", "", peeled
    return eta_skeleton(task.expected_type_surface), term_to_surface(term), peeled


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


def load_arm(arm: str) -> list[dict] | None:
    path = RUNS / arm / "records.jsonl"
    if not path.is_file():
        return None
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def route_digests(resolver: ExperimentResolver) -> dict[str, list[str]]:
    """Each task's `composes` route as `0x…` digests.

    Read here, in the diagnostic, and never by anything on the generation path
    — the same separation §4.8's check 2c keeps.
    """
    return {
        task.task_id: ["0x" + resolver.digest_for(element).hex() for element in task.composes]
        for task in HELD_OUT_TASKS
    }


def refs_of(record: dict) -> set[str]:
    return set(REF_RE.findall(record.get("raw") or "")) | set(REF_RE.findall(record.get("source") or ""))


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


def section_typeinprompt(resolver) -> None:
    print("### The declared type is in the prompt for 2 of 8 tasks\n")
    present = 0
    for task in HELD_OUT_TASKS:
        flags = []
        for book in (ADDRESS_BOOK_NONE, ADDRESS_BOOK_FULL, ADDRESS_BOOK_TYPED):
            prompt = build_prompt(task, REGIME_HELD_OUT, resolver, address_book=book)
            flags.append(f"{book}={'YES' if task.expected_type_surface in prompt else 'no'}")
        if "YES" in flags[0]:
            present += 1
        print(f"{task.task_id:<32} type={len(task.expected_type_surface):>4}ch  " + "  ".join(flags))
    print(f"\ndeclared type reachable from the prompt: {present} of {len(HELD_OUT_TASKS)} tasks")


def section_funnel(resolver) -> None:
    print("### Acceptance and type-exactness are each common; their conjunction is not\n")
    for arm in ADDRESS_ARMS:
        records = load_arm(arm)
        if records is None:
            print(f"{arm:<11} (records absent — run not in this checkout)")
            continue
        accepted = sum(1 for r in records if r["funnel_outcome"] == "accepted")
        exact = sum(1 for r in records
                    if r["type_surface"] == TASKS_BY_ID[r["task"]].expected_type_surface)
        floor = sum(1 for r in records
                    if r["funnel_outcome"] == "accepted"
                    and r["type_surface"] == TASKS_BY_ID[r["task"]].expected_type_surface)
        print(f"{arm:<11} draws={len(records):>4}  accepted={accepted:>3}  "
              f"type-exact={exact:>3}  FLOOR(both)={floor:>3}")


def section_skeleton(resolver) -> None:
    print("### The eta-skeleton checks — and meets today's floor, which is the defect\n")
    for task in HELD_OUT_TASKS:
        skeleton = eta_skeleton(task.expected_type_surface)
        funnel = run_funnel(skeleton, resolver)
        semantic = score_semantic(task, funnel, skeleton)
        fixed = semantic.success and "(hole " not in skeleton
        print(f"{task.task_id:<32} chars={len(skeleton):>4}  funnel={funnel.outcome:<9} "
              f"floor_today={semantic.success}  floor_with_hole_free_clause={fixed}")
    print("\nSPEC §5.4: a definition containing a hole lives in `draft/` and can never be "
          "the target of a binding. The floor rule does not say so yet.")


def section_roundtrip(resolver) -> None:
    print("### Every gold term splits into (skeleton, body) and splices back exactly\n")
    for task in HELD_OUT_TASKS:
        gold = GOLD_TERMS[task.task_id]
        skeleton, body, peeled = split_gold(task, gold)
        if not skeleton:
            print(f"{task.task_id:<32} NOT EXPRESSIBLE — peeled {peeled} lambdas")
            continue
        hole = skeleton[skeleton.index("(hole "):skeleton.index(" ())", skeleton.index("(hole ")) + 4]
        assembled = skeleton.replace(hole, body)
        funnel = run_funnel(assembled, resolver)
        semantic = score_semantic(task, funnel, assembled)
        print(f"{task.task_id:<32} lams={peeled}  gold={len(gold):>4}ch  skel={len(skeleton):>4}ch  "
              f"body={len(body):>4}ch  identical={assembled == gold}  "
              f"funnel={funnel.outcome:<9} floor={semantic.success}")


def section_nested(resolver) -> None:
    print("### The nested case: draft -> closed sub-task -> fill -> splice -> re-check\n")
    task = TASKS_BY_ID["heldout/list/reverseThen"]
    gold = GOLD_TERMS[task.task_id]
    # The inner subterm is located by shape, not by name: the single one-argument
    # application of a store reference to a bound variable. Nothing here consults
    # `composes` — the point is that the *harness* never needs to.
    match = re.search(r"\(app \(ref 0x[0-9a-f]{64}\) \(var 1\)\)", gold)
    if match is None:
        print("no one-argument inner application found in the gold term; section skipped")
        return
    inner = match.group(0)
    domains, rows, _goal = peel_arrows(task.expected_type_surface)
    hole_goal = domains[0]  # the reversed list has the same type as the first argument
    hole = f"(hole {hole_goal} ())"
    draft = gold.replace(inner, hole)

    draft_funnel = run_funnel(draft, resolver)
    print(f"draft            funnel={draft_funnel.outcome:<9} "
          f"declared-type-preserved={draft_funnel.type_surface == task.expected_type_surface}")

    closed = closed_subtask_type(domains, rows, hole_goal)
    fill_def = (f"(def {closed} " + "".join(f"(lam {d} " for d in domains) + inner
                + ")" * len(domains) + ")")
    fill_funnel = run_funnel(fill_def, resolver)
    print(f"closed sub-task  {len(closed)}ch, derived from the declared type alone")
    print(f"fill definition  funnel={fill_funnel.outcome:<9} chars={len(fill_def)}")

    assembled = draft.replace(hole, inner)
    funnel = run_funnel(assembled, resolver)
    semantic = score_semantic(task, funnel, assembled)
    print(f"assembled        identical-to-gold={assembled == gold}  "
          f"funnel={funnel.outcome:<9} floor={semantic.success}")


def section_cells(resolver) -> None:
    print("### Per-cell rates for every candidate primary, and per-arm throughput\n")
    routes = route_digests(resolver)
    for arm in ADDRESS_ARMS:
        records = load_arm(arm)
        if records is None:
            print(f"{arm:<11} (records absent — run not in this checkout)\n")
            continue
        cells: dict[tuple, list[dict]] = defaultdict(list)
        for record in records:
            cells[(record["task"], record["seed"])].append(record)

        def accepted(record):
            return record["funnel_outcome"] == "accepted"

        def type_exact(record):
            return record["type_surface"] == TASKS_BY_ID[record["task"]].expected_type_surface

        def floor(record):
            return accepted(record) and type_exact(record) and "(hole " not in (record["source"] or "")

        def route_complete(record):
            return all(digest in refs_of(record) for digest in routes[record["task"]])

        for label, predicate in (
            ("funnel-accepted", accepted),
            ("type-exact", type_exact),
            ("PRIMARY composed-definition", floor),
            ("route-complete refs", route_complete),
        ):
            hit = sum(1 for rows in cells.values() if any(predicate(r) for r in rows))
            draws = sum(1 for r in records if predicate(r))
            print(f"{arm:<11} {label:<28} cells {hit:>2}/{len(cells)} ({100 * hit / len(cells):5.1f}%)"
                  f"   draws {draws:>3}/{len(records)}")
        tokens = sum(r["tokens_completion"] for r in records)
        latency = sum(r["latency_s"] for r in records)
        print(f"{arm:<11} completion tokens={tokens}  latency={latency / 3600:.2f}h  "
              f"rate={tokens / latency:.1f} completion tok/s  "
              f"draws/cell={len(records) / len(cells):.1f}\n")


def section_holes(resolver) -> None:
    print("### Holes the model has already emitted, over every run directory on record\n")
    total = 0
    with_hole = 0
    hole_floor = 0
    accepted_examples: list[str] = []
    for path in sorted(RUNS.glob("*/records.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            total += 1
            source = record.get("source") or ""
            if "(hole " not in source:
                continue
            with_hole += 1
            if record.get("semantic_success"):
                hole_floor += 1
            elif record["funnel_outcome"] == "accepted":
                accepted_examples.append(f"{path.parent.name} {record['task']}: {source[:90]}")
    if not total:
        print("(no records.jsonl under runs/ — run directories absent from this checkout)")
        return
    print(f"draws scanned                        {total:>6}")
    print(f"draws whose source contains a hole   {with_hole:>6}")
    print(f"…of those, meeting today's floor     {hole_floor:>6}")
    print("\nfunnel-accepted hole-bearing draws (the floor fix is one type-guess away from firing):")
    for example in accepted_examples[:5]:
        print(f"  {example}")


def _fisher_one_sided(a: int, b: int, c: int, d: int) -> float:
    """`P(X >= a)` under the hypergeometric null for the 2x2 table `[[a,b],[c,d]]`."""
    n1, n2 = a + b, c + d
    drawn = a + c
    return sum(
        comb(n1, x) * comb(n2, drawn - x) for x in range(a, min(n1, drawn) + 1)
    ) / comb(n1 + n2, drawn)


def section_power(resolver) -> None:
    print("### Simulated power, one-sided Fisher at alpha=0.05, per-cell primary\n")
    random.seed(11)
    replicates = 6000
    for n in (48, 64, 80):
        for a0 in (0.02, 0.03, 0.05):
            cells = []
            for a1 in (0.10, 0.15, 0.20, 0.25, 0.30):
                hits = 0
                for _ in range(replicates):
                    x = sum(random.random() < a1 for _ in range(n))
                    y = sum(random.random() < a0 for _ in range(n))
                    if _fisher_one_sided(x, n - x, y, n - y) < 0.05:
                        hits += 1
                cells.append(f"A1={a1:.2f}:{hits / replicates:.3f}")
            print(f"n={n:>3}/arm A0={a0:.2f}  " + "  ".join(cells))
    print("\nSECONDARY — k hand-scored successes in `holes` vs 0 in `whole`, one-sided Fisher:\n")
    for n in (48, 64, 80):
        row = "  ".join(f"k={k}:p={_fisher_one_sided(k, n - k, 0, n):.5f}" for k in range(1, 7))
        print(f"n={n:>3}  {row}")


SECTIONS = {
    "typeinprompt": section_typeinprompt,
    "funnel": section_funnel,
    "skeleton": section_skeleton,
    "roundtrip": section_roundtrip,
    "nested": section_nested,
    "cells": section_cells,
    "holes": section_holes,
    "power": section_power,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m experiment.decomposition_probe",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument("--section", choices=sorted(SECTIONS), default="",
                        help="run one section instead of all of them")
    arguments = parser.parse_args(argv)

    resolver = ExperimentResolver()
    wanted = [arguments.section] if arguments.section else list(SECTIONS)
    for index, name in enumerate(wanted):
        if index:
            print()
        SECTIONS[name](resolver)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
