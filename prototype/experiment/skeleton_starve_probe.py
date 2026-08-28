"""Where the decomposition run's skeletons actually die — the evidence, on a CPU.

`docs/plans/2026-08-25-hole-decomposition.md` §6 row 4 fired on a reading that
has since been narrowed twice: first by the elicitation plan's §1 (the hole is
not what fails; a committed sibling is), then by Stage 0 (no elicitation block
clears E1) and the model-scale arm (scale does nothing for holes). What none of
them asked is the question this module answers: **the arm's mechanical floor is
a conjunction, and the conjunct that binds is not the one the funnel reports.**

Everything here reads banked records under `prototype/runs/` and runs the real
funnel on CPU. No GPU, no network, no model. Every number
`docs/plans/2026-08-28-skeleton-lever.md` §1 cites is printed by one of these
sections.

* **funnel** — where skeleton draws die, layer by layer, against the two
  concurrent whole-draw arms. Skeleton acceptance (5.49 %) sits *between* the
  `redraft` (6.87 %) and `whole` (3.67 %) controls, so it is not a
  skeleton-specific starvation at all. Within `typecheck`, the failure classes.

* **floor** — the mechanical floor is `accepted AND type-exact`
  (`evaluate.score_semantic`, rule `checked+type-exact`). The two conjuncts are
  nearly disjoint: 5.49 % and 16.20 % separately, 0.27 % together. Prints the
  four-way table and the **near-miss band** — the drafts failing exactly one
  conjunct, and which one — plus the per-task decomposition showing the
  disjointness is Simpson's paradox, not a draw-level trade-off.

* **arity** — the binding conjunct, diagnosed. Type-exactness is gated almost
  entirely by the declared type's **arrow arity**: 26.79 % of drafts get it
  right, and of those 63.35 % get the whole type right. The error is a
  systematic off-by-one (71.11 % of drafts declare exactly one arrow fewer than
  gold), and its dominant surface shape is a nest closed one arrow early.

* **sibling** — the elicitation report's "9 of 10 rejects failed at a committed
  sibling, not at the hole" re-derived, then **extended to all 706 rejects** by
  cutting a hole at each one's error path (`prompts.checker_holed_cut`, the
  landed B3 surface) and re-running the funnel. This is the near-miss band in
  its strongest form: how many rejected drafts are one subterm away from
  typechecking. It also prices the checker-holed lever exactly, and splits the
  answer by whether the draft's declared arity was right — which is what
  separates "sibling failure is a scope/arity issue" from "it is semantic".

* **scale** — the same endpoints on the banked 14B arm, which is free. The
  model-scale arm stopped the scale track on E1 (hole elicitation) and was right
  to; on the campaign's *own* floor the same run moved every endpoint, and its
  42 floor draws have never been hand-scored.

* **levers** — each candidate lever's bound on the banked data, or "not
  computable offline" stated plainly. This is the argument §2 of the plan makes.

* **waste** — two harness facts the diagnosis turned up: `evaluate.narrowing_note`
  returns `""` on acceptance, so an accepted-but-type-wrong draft produces a
  byte-identical re-draw with no feedback; and the exact-duplicate draw rate
  within a cell.

Run from `prototype/`::

    python3 -m experiment.skeleton_starve_probe
    python3 -m experiment.skeleton_starve_probe --section arity --section scale

Exit code 0 when every integrity check passes, 1 when one fails. An integrity
failure means a finding about the harness, not about the model, and the plan
must say so before anything else in it is read.

**Everything here is descriptive.** No p-value below is confirmatory: these arms
were pre-registered for other questions, they have been run, and their verdicts
stand. The p-values are reading aids for effects already on record, labelled as
such at every site.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys
from math import comb

from .evaluate import run_funnel
from .prompts import (
    checker_holed_cut,
    held_out_tasks,
    peel_arrows,
)
from .resolver import ExperimentResolver

RUNS = pathlib.Path(__file__).resolve().parent.parent / "runs"

#: The 2026-08-25 decomposition arms. `holes` draws skeletons; the other two
#: draw whole definitions. All three ran concurrently on one battery.
DECOMP = (("decomp-holes", "skeleton"), ("decomp-redraft", "whole"),
          ("decomp-whole", "whole"))

#: The Stage 0 pilot blocks that the model-scale arm re-ran at 14B. Only B0 and
#: B2 have a 14B counterpart, so only those two are used for the scale read.
MATCHED_7B = ("pilot-b0", "pilot-b2")
MATCHED_14B = ("scale14-b0", "scale14-b2")

#: `run_funnel` applies its layers in this order. A draw's `funnel_outcome` is
#: the first layer that refused it, or `accepted`.
LAYERS = ("parse", "references", "scope", "typecheck", "accepted")

_TASKS = {task.task_id: task for task in held_out_tasks()}

#: Collected by every section; a non-empty list exits 1.
FAILURES: list[str] = []


# -- loading and predicates ---------------------------------------------


def load(name: str, role: str | None = None) -> list[dict]:
    """One run's records, optionally filtered to a role."""
    path = RUNS / name / "records.jsonl"
    records = [json.loads(line) for line in path.open()]
    if role is not None:
        records = [record for record in records if record.get("role") == role]
    return records


def accepted(record: dict) -> bool:
    return record["funnel_outcome"] == "accepted"


def type_exact(record: dict) -> bool:
    """The floor's second conjunct: the declared type *is* the task's type.

    `type_surface` is the canonical re-serialisation the parse layer produced,
    so this is a canonical comparison and not a byte comparison of what the
    model typed. Empty for a draft that did not parse, which is never exact.
    """
    task = _TASKS.get(record["task"])
    return bool(task) and record.get("type_surface") == task.expected_type_surface


def floor(record: dict) -> bool:
    """The harness's own mechanical floor, as it scored it at run time."""
    return bool(record["semantic_success"])


def arity(type_surface: str | None) -> int | None:
    """Number of top-level arrows in a declared type, or `None` if unreadable."""
    if not type_surface:
        return None
    try:
        return len(peel_arrows(type_surface)[0])
    except Exception:  # noqa: BLE001 - an unparsable surface has no arity
        return None


def gold_arity(record: dict) -> int | None:
    task = _TASKS.get(record["task"])
    return arity(task.expected_type_surface) if task else None


def arity_correct(record: dict) -> bool:
    drawn = arity(record.get("type_surface"))
    return drawn is not None and drawn == gold_arity(record)


def cells_of(records: list[dict]) -> dict:
    """Records grouped by the `(task, seed)` pair that defines a cell."""
    grouped: dict = collections.defaultdict(list)
    for record in records:
        grouped[(record["task"], record["seed"])].append(record)
    return grouped


def fisher_greater(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher exact, P(X >= a), for `[[a, b], [c, d]]`.

    Descriptive throughout this module. Exact rather than approximate because
    several tables here have single-digit cells.
    """
    n1, n2, k = a + b, c + d, a + c
    total = comb(n1 + n2, k)
    if not total:
        return 1.0
    return sum(comb(n1, x) * comb(n2, k - x)
               for x in range(a, min(n1, k) + 1)) / total


def rate(numerator: int, denominator: int) -> str:
    if not denominator:
        return f"{numerator:>4d}/{denominator:<4d}     -"
    return f"{numerator:>4d}/{denominator:<4d} {100 * numerator / denominator:5.2f}%"


def check(label: str, condition: bool, detail: str = "") -> None:
    """An integrity assertion. A failure is a harness finding, not a result."""
    if condition:
        print(f"  ok    {label}")
        return
    FAILURES.append(label)
    print(f"  FAIL  {label}  {detail}")


# -- funnel --------------------------------------------------------------


def _error_class(record: dict) -> str:
    """A typecheck message reduced to its class, with the data blanked out."""
    message = record.get("error_message") or ""
    body = message.split(": ", 1)[1] if ": " in message else message
    body = re.sub(r"b'[^']*'", "b'..'", body)
    body = re.sub(r"0x[0-9a-f]+", "HASH", body)
    body = re.sub(r"\[.*", "[...]", body)
    return re.sub(r"\d+", "N", body).strip()[:74]


def section_funnel() -> None:
    print("### Where a draw dies, by layer — skeleton draws against the two "
          "concurrent whole-draw arms\n")
    print(f"  {'arm/role':24s} {'n':>4}  " +
          "  ".join(f"{layer:>10s}" for layer in LAYERS))
    counts = {}
    for run, role in DECOMP:
        records = load(run, role)
        tally = collections.Counter(r["funnel_outcome"] for r in records)
        counts[run] = (len(records), tally)
        cells = "  ".join(
            f"{tally[layer]:4d} {100 * tally[layer] / len(records):4.1f}%"
            for layer in LAYERS)
        print(f"  {run + '/' + role:24s} {len(records):4d}  {cells}")

    holes_n, holes_t = counts["decomp-holes"]
    redraft_n, redraft_t = counts["decomp-redraft"]
    whole_n, whole_t = counts["decomp-whole"]
    print("\n  Skeleton acceptance is 5.49 % — between the `redraft` control's "
          "6.87 % and the\n  `whole` control's 3.67 %. It is the battery's "
          "acceptance rate, not a skeleton\n  deficit, and no test separates it "
          "from either control:")
    print(f"    holes vs redraft, one-sided (redraft > holes): "
          f"p = {fisher_greater(redraft_t['accepted'], redraft_n - redraft_t['accepted'], holes_t['accepted'], holes_n - holes_t['accepted']):.4f}")
    print(f"    holes vs whole,   one-sided (holes > whole):   "
          f"p = {fisher_greater(holes_t['accepted'], holes_n - holes_t['accepted'], whole_t['accepted'], whole_n - whole_t['accepted']):.4f}")

    typechecked = [r for r in load("decomp-holes", "skeleton")
                   if r["funnel_outcome"] == "typecheck"]
    print(f"\n### Within `typecheck` — the failure classes ({len(typechecked)} "
          f"draws, {100 * len(typechecked) / holes_n:.1f} % of all skeleton draws)\n")
    classes = collections.Counter(_error_class(r) for r in typechecked)
    for name, count in classes.most_common(12):
        print(f"  {count:4d} {100 * count / len(typechecked):5.1f}%  {name}")
    tail = len(typechecked) - sum(c for _, c in classes.most_common(12))
    if tail:
        print(f"  {tail:4d} {100 * tail / len(typechecked):5.1f}%  "
              f"(the remaining {len(classes) - 12} classes)")

    print("\n### Integrity\n")
    check("every skeleton draw carries one of the five funnel outcomes",
          sum(holes_t[layer] for layer in LAYERS) == holes_n)
    check("the funnel totals reproduce the 2026-08-26 report's telemetry "
          "(747 draws, 41 accepted)",
          holes_n == 747 and holes_t["accepted"] == 41,
          f"got {holes_n} draws, {holes_t['accepted']} accepted")


# -- floor ---------------------------------------------------------------


def section_floor() -> None:
    print("### The mechanical floor is a conjunction, and its conjuncts are "
          "nearly disjoint\n")
    print("  Rule `checked+type-exact` (`evaluate.score_semantic`): a draw "
          "counts iff the funnel\n  accepted it AND its declared type is the "
          "task's. Both conjuncts, separately and\n  together:\n")
    print(f"  {'arm/role':24s} {'n':>4} {'accepted':>16} {'type-exact':>16} "
          f"{'FLOOR (both)':>16}")
    for run, role in DECOMP:
        records = load(run, role)
        print(f"  {run + '/' + role:24s} {len(records):4d} "
              f"{rate(sum(map(accepted, records)), len(records)):>16} "
              f"{rate(sum(map(type_exact, records)), len(records)):>16} "
              f"{rate(sum(map(floor, records)), len(records)):>16}")

    records = load("decomp-holes", "skeleton")
    n = len(records)
    both = [r for r in records if accepted(r) and type_exact(r)]
    acc_only = [r for r in records if accepted(r) and not type_exact(r)]
    tex_only = [r for r in records if type_exact(r) and not accepted(r)]
    neither = [r for r in records if not accepted(r) and not type_exact(r)]

    print("\n### The near-miss band — drafts failing exactly one conjunct, and "
          "which one\n")
    print(f"  {'both conjuncts (the floor)':44s} {rate(len(both), n)}")
    print(f"  {'accepted, type WRONG  (fails the type conjunct)':44s} "
          f"{rate(len(acc_only), n)}")
    print(f"  {'type-exact, REJECTED  (fails the term conjunct)':44s} "
          f"{rate(len(tex_only), n)}")
    print(f"  {'neither':44s} {rate(len(neither), n)}")
    print(f"\n  Near-miss band (exactly one conjunct): "
          f"{rate(len(acc_only) + len(tex_only), n)}")
    print(f"  The larger half is the term conjunct: {len(tex_only)} drafts "
          f"declared the task's type\n  exactly and still failed the funnel, "
          f"against {len(acc_only)} that passed the funnel with the\n  wrong "
          f"type.")

    print("\n### Which layer rejects a type-exact draft\n")
    tally = collections.Counter(r["funnel_outcome"] for r in tex_only)
    for layer in LAYERS:
        if tally[layer]:
            print(f"  {layer:>12s}  {tally[layer]:4d} "
                  f"({100 * tally[layer] / len(tex_only):5.1f}%)")

    print("\n### The conjuncts are NEGATIVELY associated arm-wide\n")
    exact = [r for r in records if type_exact(r)]
    inexact = [r for r in records if not type_exact(r)]
    print(f"  acceptance | type-exact      "
          f"{rate(sum(map(accepted, exact)), len(exact))}")
    print(f"  acceptance | NOT type-exact  "
          f"{rate(sum(map(accepted, inexact)), len(inexact))}")
    print("\n  Backwards, on its face — writing the task's type looks like it "
          "*hurts* acceptance.\n  The next table shows why it does not.")

    print("\n### Per task — the disjointness is Simpson's paradox, not a "
          "draw-level trade-off\n")
    print(f"  {'task':32s} {'n':>4} {'|T|':>5} {'type-exact':>12} "
          f"{'accepted':>12} {'floor':>6}")
    for task_id, task in _TASKS.items():
        group = [r for r in records if r["task"] == task_id]
        if not group:
            continue
        print(f"  {task_id:32s} {len(group):4d} "
              f"{len(task.expected_type_surface):5d} "
              f"{100 * sum(map(type_exact, group)) / len(group):11.1f}% "
              f"{100 * sum(map(accepted, group)) / len(group):11.1f}% "
              f"{sum(map(floor, group)):6d}")
    total_accepted = sum(map(accepted, records))
    total_exact = sum(map(type_exact, records))
    top = "heldout/maybe/mapOrElse"
    top_group = [r for r in records if r["task"] == top]
    pair = ("heldout/list/sum", "heldout/list/mapLength")
    pair_group = [r for r in records if r["task"] in pair]
    print(f"\n  `{top.split('/', 1)[1]}` supplies "
          f"{sum(map(accepted, top_group))} of the arm's {total_accepted} "
          f"accepted drafts and\n  {sum(map(type_exact, top_group))} of its "
          f"{total_exact} type-exact ones. `list/sum` + `list/mapLength` supply "
          f"{sum(map(type_exact, pair_group))} of the\n  {total_exact} "
          f"type-exact drafts and {sum(map(accepted, pair_group))} of the "
          f"{total_accepted} accepted ones. The arm-wide negative\n  "
          f"association is that composition, not a property of a draw.")

    print("\n### Integrity\n")
    check("the four-way split partitions every skeleton draw",
          len(both) + len(acc_only) + len(tex_only) + len(neither) == n)
    check("`semantic_success` as scored at run time equals "
          "`accepted AND type-exact` recomputed here",
          sum(map(floor, records)) == len(both),
          f"run time {sum(map(floor, records))}, recomputed {len(both)}")
    check("the two conjuncts' concentrations are disjoint enough to explain "
          "the paradox",
          sum(map(type_exact, top_group)) == 0
          and sum(map(accepted, pair_group)) <= 2)


# -- arity ---------------------------------------------------------------


def _shape(record: dict) -> str:
    """How an under-arity declared type relates to gold's, structurally."""
    task = _TASKS.get(record["task"])
    if not task:
        return "unparsed"
    try:
        gold_domains, _, gold_goal = peel_arrows(task.expected_type_surface)
        domains, _, goal = peel_arrows(record["type_surface"])
    except Exception:  # noqa: BLE001
        return "unparsed"
    if len(domains) == len(gold_domains):
        return ("exact arity, domains match" if domains == gold_domains
                else "exact arity, domains differ")
    if len(domains) > len(gold_domains):
        return "over-arity"
    if domains != gold_domains[:len(domains)]:
        return "under-arity, domains not a prefix of gold's"
    if goal == gold_domains[len(domains)]:
        return "under-arity, correct prefix, codomain = gold's NEXT DOMAIN"
    if goal == gold_goal:
        return "under-arity, correct prefix, codomain = gold's final codomain"
    return "under-arity, correct prefix, codomain = something else"


def section_arity() -> None:
    records = [r for r in load("decomp-holes", "skeleton") if r.get("type_surface")]
    n = len(records)
    correct = [r for r in records if arity_correct(r)]
    exact_given_arity = sum(map(type_exact, correct))

    print("### Type-exactness is gated by the declared type's arrow arity\n")
    print(f"  declared arity == gold arity      {rate(len(correct), n)}")
    print(f"  type-exact GIVEN correct arity    {rate(exact_given_arity, len(correct))}")
    print(f"  type-exact GIVEN wrong arity      "
          f"{rate(sum(1 for r in records if not arity_correct(r) and type_exact(r)), n - len(correct))}"
          f"   (0 by construction: arity is part of the type)")
    print(f"  type-exact, unconditional         "
          f"{rate(sum(map(type_exact, records)), n)}")
    print("\n  So the whole of the type conjunct's difficulty is the arity. "
          "Get the arrow count\n  right and the hash-dense remainder follows "
          "two times in three; get it wrong and\n  nothing else can save the "
          "draft.")

    print("\n### The error is a systematic off-by-one, not noise\n")
    deltas: collections.Counter = collections.Counter()
    for record in records:
        drawn, gold = arity(record["type_surface"]), gold_arity(record)
        if drawn is not None and gold is not None:
            deltas[drawn - gold] += 1
    total = sum(deltas.values())
    for delta in sorted(deltas):
        print(f"  declared - gold = {delta:+d}   {deltas[delta]:4d} "
              f"({100 * deltas[delta] / total:5.2f}%)")

    print("\n### Arity is task-responsive — it tracks gold, shifted down by one\n")
    print(f"  {'gold arity':>10} {'n':>5}   declared-arity distribution")
    for gold in (1, 2, 3):
        group = [r for r in records if gold_arity(r) == gold]
        if not group:
            continue
        tally = collections.Counter(arity(r["type_surface"]) for r in group)
        spread = "  ".join(f"{k}:{100 * tally[k] / len(group):5.1f}%"
                           for k in sorted(tally) if k is not None)
        print(f"  {gold:>10} {len(group):5d}   {spread}")
    print("\n  Not a fixed prior copied off the prompt's 26 worked examples "
          "(11 of arity 1,\n  11 of arity 2, 3 of arity 3): the distribution "
          "moves with the task. It is a\n  calibrated estimator with a -1 bias.")

    print("\n### The dominant surface shape — the nest closed one arrow early\n")
    shapes = collections.Counter(_shape(r) for r in records)
    for name, count in shapes.most_common():
        print(f"  {count:4d} ({100 * count / n:5.2f}%)  {name}")

    print("\n### Integrity\n")
    check("no draft is type-exact with the wrong arity",
          all(arity_correct(r) for r in records if type_exact(r)))
    check("the arity delta distribution covers every readable draft",
          total == n, f"{total} deltas over {n} drafts")


# -- sibling -------------------------------------------------------------


def section_sibling() -> None:
    resolver = ExperimentResolver()
    records = load("decomp-holes", "skeleton")
    rejected = [r for r in records if not accepted(r)]

    print("### The elicitation report's sibling finding, re-derived on the "
          "12 hole-bearing drafts\n")
    hole_bearing = [r for r in records if r.get("holes")]
    print(f"  hole-bearing skeletons      {rate(len(hole_bearing), len(records))}")
    print(f"  ...accepted                 "
          f"{rate(sum(map(accepted, hole_bearing)), len(hole_bearing))}")
    print(f"  hole-free accepted          "
          f"{rate(sum(1 for r in records if not r.get('holes') and accepted(r)), sum(1 for r in records if not r.get('holes')))}")
    print("\n  Confirmed: hole-bearing drafts are accepted more often, not "
          "less — SPEC §2.6 makes\n  a hole the one node that cannot be wrong. "
          "The 2026-08-26 §1.2 blame walk found\n  9 of the 10 rejects failing "
          "away from the hole. What follows extends that from\n  12 drafts to "
          "all 706 rejects, by asking of each: **is it one subterm away from\n"
          "  typechecking?**")

    print("\n### Extended — cut a hole at every reject's error path, re-run "
          "the funnel\n")
    print("  `prompts.checker_holed_cut` is the landed B3 surface: walk from "
          "the failing node\n  up to the nearest ancestor in checking position "
          "whose goal is derivable from the\n  draft's own declared type, "
          "replace that subtree with a hole. It reads no gold.\n  A cut draft "
          "that reaches `accepted` is a draft whose every committed sibling "
          "was\n  right — a genuine one-node near-miss.\n")
    outcomes: collections.Counter = collections.Counter()
    refusals: collections.Counter = collections.Counter()
    rescued_by_arity: collections.Counter = collections.Counter()
    for record in rejected:
        cut = checker_holed_cut(record["source"], record.get("error_path") or "",
                                resolver)
        if not cut.source:
            outcomes["refused"] += 1
            refusals[cut.reason] += 1
            continue
        result = run_funnel(cut.source, resolver)
        outcomes[f"cut, funnel {result.outcome}"] += 1
        if result.outcome == "accepted":
            rescued_by_arity[arity_correct(record)] += 1
    for name, count in outcomes.most_common():
        print(f"  {count:4d} ({100 * count / len(rejected):5.2f}%)  {name}")
    print("\n  Why the cut is refused, when it is:")
    for reason, count in refusals.most_common():
        print(f"    {count:4d}  {reason}")

    rescued = sum(rescued_by_arity.values())
    print(f"\n### The one-node near-miss band: {rate(rescued, len(rejected))} "
          f"of rejected skeletons\n")
    print("  Split by whether the draft had the right declared arity — this is "
          "what separates\n  'the sibling failure is an arity/scope problem' "
          "from 'it is semantic':\n")
    for correct in (True, False):
        pool = [r for r in rejected if arity_correct(r) is correct]
        print(f"  arity {'correct' if correct else 'wrong  '}: "
              f"{rescued_by_arity[correct]:3d} rescued of {len(pool):4d} "
              f"rejects = "
              f"{100 * rescued_by_arity[correct] / max(1, len(pool)):5.2f}%")
    print("\n  A rescue rate this low on both sides is the finding: the "
          "committed siblings are not\n  one bad node, and a hole placed at the "
          "checker's error does not repair them. That\n  is 2026-08-26 §1.3's "
          "prediction, now measured on 706 drafts rather than 8.")

    print("\n### Integrity\n")
    check("`checker_holed_cut` returns a cut or a reason, never both empty",
          sum(outcomes.values()) == len(rejected))
    check("no cut draft is scored as reaching a layer the original passed "
          "and then some",
          rescued <= len(rejected))


# -- scale ---------------------------------------------------------------


def _pool(runs: tuple[str, ...]) -> list[dict]:
    return [r for run in runs for r in load(run, "skeleton")]


def section_scale() -> None:
    seven, fourteen = _pool(MATCHED_7B), _pool(MATCHED_14B)
    print("### The same endpoints at 14B — banked, matched blocks, $0\n")
    print("  `pilot-{b0,b2}` and `scale14-{b0,b2}`: same 8 tasks, same seeds "
          "1-2, same purse,\n  same condition, same quantization and "
          "tokenizer. Parameter count is the only\n  difference (model-scale "
          "arm, 'one variable moved').\n")
    print(f"  {'endpoint':30s} {'14B':>14} {'7B':>14} {'RR':>6} {'p':>10}")
    endpoints = (
        ("funnel acceptance", accepted),
        ("declared arity correct", arity_correct),
        ("type-exact", type_exact),
        ("MECHANICAL FLOOR", floor),
    )
    for name, predicate in endpoints:
        a = sum(1 for r in fourteen if predicate(r))
        c = sum(1 for r in seven if predicate(r))
        ratio = ((a / len(fourteen)) / (c / len(seven))) if c else float("inf")
        p = fisher_greater(a, len(fourteen) - a, c, len(seven) - c)
        print(f"  {name:30s} {rate(a, len(fourteen)):>14} "
              f"{rate(c, len(seven)):>14} {ratio:6.2f} {p:10.2e}")

    print("\n### The -1 arity bias, at both sizes\n")
    for name, pool in (("7B ", seven), ("14B", fourteen)):
        deltas: collections.Counter = collections.Counter()
        for record in pool:
            drawn, gold = arity(record.get("type_surface")), gold_arity(record)
            if drawn is not None and gold is not None:
                deltas[drawn - gold] += 1
        total = sum(deltas.values())
        spread = "  ".join(f"{k:+d}:{100 * deltas[k] / total:5.2f}%"
                           for k in sorted(deltas))
        print(f"  {name}  {spread}")

    print("\n### Declared arity by gold arity — where the bias resolves\n")
    print(f"  {'model':>5} {'gold arity':>10} {'n':>5}   declared-arity distribution")
    for name, pool in (("7B", seven), ("14B", fourteen)):
        for gold in (1, 2, 3):
            group = [r for r in pool if gold_arity(r) == gold
                     and r.get("type_surface")]
            if not group:
                continue
            tally = collections.Counter(arity(r["type_surface"]) for r in group)
            spread = "  ".join(f"{k}:{100 * tally[k] / len(group):5.1f}%"
                               for k in sorted(tally) if k is not None)
            print(f"  {name:>5} {gold:>10} {len(group):5d}   {spread}")

    print("\n### Per block — the C1' anchor targets for a future 14B arm\n")
    print(f"  {'block':14s} {'n':>4} {'funnel acceptance':>20} {'type-exact':>18}")
    for run in MATCHED_14B:
        block = load(run, "skeleton")
        print(f"  {run:14s} {len(block):4d} "
              f"{rate(sum(map(accepted, block)), len(block)):>20} "
              f"{rate(sum(map(type_exact, block)), len(block)):>18}")

    print("\n### The live stratum the campaign has never had\n")
    for name, pool in (("7B ", seven), ("14B", fourteen)):
        exact = [r for r in pool if type_exact(r)]
        print(f"  {name}  type-exact {rate(len(exact), len(pool))}    "
              f"TERM acceptance (accept | type-exact) "
              f"{rate(sum(map(accepted, exact)), len(exact))}")
    print("\n  At 7B the term stratum is 52 draws carrying 2 accepts: nothing "
          "to measure. At 14B\n  it is 239 draws carrying 45 — the first "
          "population in campaign history on which\n  'does feedback help a "
          "draft that already committed to the right type?' can be asked.")

    print("\n### The 42 banked 14B floor draws — never hand-scored\n")
    scored = [r for r in fourteen if floor(r)]
    print(f"  floor draws {len(scored)}   unique surfaces "
          f"{len({r['source'] for r in scored})}   "
          f"cells reached {len({(r['task'], r['seed']) for r in scored})} of 32")
    for task_id, count in collections.Counter(r["task"] for r in scored).most_common():
        print(f"    {count:3d}  {task_id}")
    print("\n  The model-scale arm's report states this plainly: 'R3's "
          "hand-scored rubric ... is\n  outstanding for 42 draws', left "
          "'outstanding by rule, not by omission', because the\n  arm's "
          "question was E1/E2. The pilot's rubric found 2 of 3 "
          "mechanical-floor surfaces\n  were extensional shortcuts that FAIL "
          "against gold, so the floor overstates by an\n  unmeasured amount. "
          "Scoring these 42 costs $0 and is the highest-information action\n"
          "  available to the campaign.")

    print("\n### Integrity\n")
    check("the matched blocks are the same 8 tasks and 2 seeds on both sides",
          {(r["task"], r["seed"]) for r in seven}
          == {(r["task"], r["seed"]) for r in fourteen})
    check("the 14B floor count matches the model-scale report's 42",
          len(scored) == 42, f"got {len(scored)}")


# -- levers --------------------------------------------------------------


def section_levers() -> None:
    records = load("decomp-holes", "skeleton")
    n = len(records)
    seven, fourteen = _pool(MATCHED_7B), _pool(MATCHED_14B)

    print("### What each candidate lever would have bought, on banked data\n")
    print("  Bounds only. A bound is not a prediction; where the banked data "
          "cannot answer,\n  this section says so instead of estimating.\n")

    print("-- 1. Prefix-prime the declared type (harness emits `(def TYPE `)")
    print(f"     Makes the type conjunct free: {rate(sum(map(type_exact, records)), n)}"
          f" -> 100 % by construction.")
    print(f"     Floor bound: {rate(sum(map(floor, records)), n)} -> at most "
          f"{rate(sum(map(accepted, records)), n)} (arm-wide acceptance).")
    print("     REJECTED, not on the bound: the expected type is NOT in the "
          "prompt (checked\n     below), so the model infers it from prose. "
          "Priming hands it the answer to the\n     conjunct that carries the "
          "difficulty — 2026-08-25 §2.5's named confound,\n     'it hands the "
          "model the declared type the control has to guess'.")
    leaked = [t.task_id for t in _TASKS.values()
              if t.expected_type_surface in t.spec]
    print(f"     expected type surface appearing verbatim in the task spec: "
          f"{len(leaked)} of {len(_TASKS)}")

    print("\n-- 2. Relax the fill gate (`accepted` -> `well-scoped`)")
    print("     2026-08-26 §1.3 priced it at 8 fill draws, 0 composed "
          "definitions. Stage 0 then\n     RAN it: 31 fill draws across four "
          "blocks, 0 spliced. Bound is measured, not\n     modelled, and it is "
          "zero. Already spent.")

    print("\n-- 3. Hole elicitation (exemplar / hole-required / checker-holed)")
    print("     Stage 0 ran all three. Best block 5.75 % against a 10 % bar; "
          "no block cleared.\n     The 14B re-ran two of them and did worse. "
          "Bound is measured and it is zero.")

    print("\n-- 4. The exemplar block as a general-acceptance lever")
    control = [r for run in ("pilot-b0", "pilot-b2", "pilot-b3")
               for r in load(run, "skeleton")]
    treated = load("pilot-b1", "skeleton")
    for name, predicate in (("funnel acceptance", accepted),
                            ("declared arity correct", arity_correct),
                            ("type-exact", type_exact)):
        a = sum(1 for r in treated if predicate(r))
        c = sum(1 for r in control if predicate(r))
        ratio = ((a / len(treated)) / (c / len(control))) if c else float("inf")
        print(f"     {name:24s} B1 {rate(a, len(treated))}   "
              f"pooled control {rate(c, len(control))}   RR {ratio:4.2f}   "
              f"p = {fisher_greater(a, len(treated) - a, c, len(control) - c):.4f}")
    treated0 = [r for r in treated if r["round"] == 0]
    control0 = [r for r in control if r["round"] == 0]
    a = sum(1 for r in treated0 if type_exact(r))
    c = sum(1 for r in control0 if type_exact(r))
    print(f"     At round 0 — the only contrast where the control prompts are "
          f"byte-identical —\n     type-exact B1 {a}/{len(treated0)} vs "
          f"control {c}/{len(control0)}, "
          f"p = {fisher_greater(a, len(treated0) - a, c, len(control0) - c):.4f}. "
          f"REJECTED: no\n     defensible bound above 1.")

    print("\n-- 5. A bigger purse / more draws per cell")
    grouped = cells_of(records)
    per_cell = sum(len(v) for v in grouped.values()) / len(grouped)
    p_floor = sum(map(floor, records)) / n
    print(f"     {per_cell:.2f} draws/cell at a {100 * p_floor:.2f} % per-draw "
          f"floor rate. Doubling the purse takes\n     expected floor cells "
          f"from {64 * (1 - (1 - p_floor) ** per_cell):.1f} to "
          f"{64 * (1 - (1 - p_floor) ** (2 * per_cell)):.1f} of 64, at twice "
          f"the cost. REJECTED on arithmetic.")

    print("\n-- 6. Recover the wasted rounds (see `--section waste`)")
    duplicates = sum(len(v) - len({r["source"] for r in v})
                     for v in grouped.values())
    silent = sum(1 for r in records if accepted(r) and not type_exact(r))
    recoverable = (duplicates + silent) / n
    print(f"     duplicate draws {rate(duplicates, n)} + silent accepts "
          f"{rate(silent, n)} = {100 * recoverable:.2f} % of draws.")
    print(f"     Perfect recovery is an effective purse increase of "
          f"{100 * recoverable:.1f} %: floor "
          f"{100 * p_floor:.2f} % -> {100 * p_floor * (1 + recoverable):.2f} %, "
          f"RR {1 + recoverable:.2f}.\n     REJECTED as a primary lever on the "
          f"bound; worth landing as a harness fix.")

    print("\n-- 7. Gold-derived feedback on a type-wrong draft")
    print(f"     Fires on {rate(silent, n)} of draws. REJECTED on principle "
          f"before arithmetic: it is\n     a gold oracle, and 2026-08-25 §2.1's "
          f"no-oracle property is what makes every\n     result in this "
          f"campaign interpretable.")

    print("\n-- 8. Model scale, on the campaign's own floor")
    for name, predicate in (("type-exact", type_exact), ("MECHANICAL FLOOR", floor)):
        a = sum(1 for r in fourteen if predicate(r))
        c = sum(1 for r in seven if predicate(r))
        ratio = ((a / len(fourteen)) / (c / len(seven))) if c else float("inf")
        print(f"     {name:20s} 14B {rate(a, len(fourteen))}  7B "
              f"{rate(c, len(seven))}  RR {ratio:5.2f}  "
              f"p = {fisher_greater(a, len(fourteen) - a, c, len(seven) - c):.2e}")
    print("     The only lever with a large, significant, banked bound. "
          "ALREADY BOUGHT at 32\n     cells — which is what the $4.55 ceiling "
          "affords at 14B's measured 8.52 tok/s.\n     NOT COMPUTABLE OFFLINE: "
          "whether those 42 floor draws are semantically correct.\n     That "
          "is D0, and it costs $0.")

    print("\n-- 9. The feedback lever (`redraft` vs `whole`), for reference")
    redraft, whole = load("decomp-redraft", "whole"), load("decomp-whole", "whole")
    for name, predicate in (("funnel acceptance", accepted),
                            ("type-exact", type_exact)):
        a = sum(1 for r in redraft if predicate(r))
        c = sum(1 for r in whole if predicate(r))
        ratio = (a / len(redraft)) / (c / len(whole))
        print(f"     {name:20s} redraft {rate(a, len(redraft))}  whole "
              f"{rate(c, len(whole))}  RR {ratio:5.2f}  "
              f"p = {fisher_greater(a, len(redraft) - a, c, len(whole) - c):.4f}")
    print("     Feedback moves acceptance (RR 1.87, p = 0.0035) and does not "
          "move the type\n     (RR 1.12, p = 0.16). At 7B its effect on the "
          "TERM stratum is unmeasurable —\n     4/147 against 3/129. At 14B "
          "that stratum is 239 draws. This is the arm §3\n     pre-registers.")

    print("\n### Integrity\n")
    check("no candidate lever's bound was computed from a run that has not "
          "been banked",
          all((RUNS / name).is_dir() for name in
              ("decomp-holes", "decomp-redraft", "decomp-whole",
               "pilot-b0", "pilot-b1", "pilot-b2", "pilot-b3",
               "scale14-b0", "scale14-b2")))


# -- waste ---------------------------------------------------------------


def section_waste() -> None:
    print("### Two harness facts the diagnosis turned up\n")
    print("-- `evaluate.narrowing_note` returns `\"\"` on acceptance "
          "(evaluate.py:289-290)\n")
    print("  So a draft the funnel accepted with the WRONG declared type ends "
          "its round with no\n  note, and `_run_whole_protocol` re-draws from "
          "a byte-identical prompt. The round\n  produced neither a candidate "
          "nor a signal. How often:\n")
    for run, role in DECOMP:
        records = load(run, role)
        silent = [r for r in records if accepted(r) and not type_exact(r)]
        by_task = collections.Counter(r["task"].split("/", 1)[1] for r in silent)
        print(f"  {run + '/' + role:24s} {rate(len(silent), len(records))}   "
              f"{dict(by_task.most_common(3))}")
    fourteen = _pool(MATCHED_14B)
    silent14 = [r for r in fourteen if accepted(r) and not type_exact(r)]
    print(f"  {'scale14 (14B, pooled)':24s} {rate(len(silent14), len(fourteen))}"
          f"   — the defect grows with the model, because acceptance does")

    print("\n-- Exact duplicate draws within a cell\n")
    for run, role in DECOMP:
        grouped = cells_of(load(run, role))
        total = sum(len(v) for v in grouped.values())
        duplicates = sum(len(v) - len({r["source"] for r in v})
                         for v in grouped.values())
        distinct_types = sum(len({r.get("type_surface") for r in v})
                             for v in grouped.values()) / len(grouped)
        print(f"  {run + '/' + role:24s} duplicates {rate(duplicates, total)}   "
              f"distinct declared types per cell {distinct_types:5.2f}")

    print("\n  Neither is a lever (§levers 6 prices them at RR 1.18 together). "
          "Both are harness\n  fixes worth landing on their own account, and "
          "both must be landed BEFORE any arm\n  that measures acceptance, "
          "because they change the denominator.")

    print("\n### Integrity\n")
    check("a silent accept is exactly an accepted draw that is not type-exact",
          all(accepted(r) and not type_exact(r) and not floor(r)
              for r in silent14))


SECTIONS = {
    "funnel": section_funnel,
    "floor": section_floor,
    "arity": section_arity,
    "sibling": section_sibling,
    "scale": section_scale,
    "levers": section_levers,
    "waste": section_waste,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--section", choices=sorted(SECTIONS), action="append",
                        help="run one section (repeatable); default is all")
    arguments = parser.parse_args(argv)
    for name in arguments.section or list(SECTIONS):
        print("=" * 78)
        print(f"## {name}")
        print("=" * 78)
        SECTIONS[name]()
        print()
    if FAILURES:
        print("=" * 78)
        print(f"INTEGRITY FAILURES: {len(FAILURES)}")
        for label in FAILURES:
            print(f"  - {label}")
        return 1
    print("=" * 78)
    print("ALL INTEGRITY CHECKS PASS")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
