"""Why the `holes` arm never reached its mechanism — the evidence, on a CPU.

Six sections, and every claim in `docs/plans/2026-08-26-hole-elicitation.md` §1
is one of them. Nothing here needs a GPU or a model: the arms are banked in
`prototype/runs/decomp-{whole,redraft,holes}/records.jsonl`, the masker runs
against a scripted vocabulary the way `spine_mask_probe` runs it, and the
exemplar block is built and driven through the real funnel.

* **census** — the hole-bearing draw rate in all three arms, with the one-sided
  Fisher that says §3's protocol block *did* induce holes (12/747 vs 2/772,
  p = 0.005). The report's "licensed but did not induce" reading is directionally
  wrong; the block works and is ~20x too weak.
* **blame** — for each of the twelve hole-bearing skeletons, whether the funnel's
  error path resolves to the hole or to a **sibling the model committed to**.
  Nine of ten rejects failed away from the hole. This is the section the whole
  re-run design turns on.
* **gate** — what §6 row 4's `accepted` -> `parses` relaxation would have bought
  on the banked draws, layer by layer, counted rather than argued.
* **mask** — is `(hole ` even reachable under the real type mask at each task's
  body goal? It is, at all eight, as one of ten admissible heads. The mask is not
  the obstacle.
* **exemplars** — builds the §3.2 exemplar block out of corpus fixtures only,
  drives both skeletons and both fills through `run_funnel`, splices each back
  and asserts byte-identity with the corpus definition, and runs the leak checks.
* **power** — the primary's power at the **measured** whole-arm baseline
  (3/64 = 0.047), not the 0.03 the 2026-08-25 plan planned against.
* **check10** — §4.7's check 10, over every banked typecheck-rejected skeleton:
  `hole_at_error` returns a draft that parses, keeps its declared type and is
  not a bare hole, or `None`, and never anything else. Also sizes B3 — how
  often the cut is available at all, and what the seeded draft then typechecks
  as. `hole_elicitation_stub_check.py` runs this same definition of the check.

Run from `prototype/`::

    python3 -m experiment.hole_elicitation_probe               # every section
    python3 -m experiment.hole_elicitation_probe --section blame
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import re
import sys
from math import comb

import corpus_registry
import sexpr
import transcode

from .backends import scripted_vocabulary
from .evaluate import run_funnel
from .masker import PRUNER_NAMES, build_masker
from .prompts import (
    FEW_SHOT_NAMES,
    bare_hole_body,
    checker_holed_cut,
    closed_subtask_type,
    declared_type_of,
    eta_skeleton,
    held_out_tasks,
    hole_at_error,
    hole_obligations,
    peel_arrows,
    splice_fill,
)
from .resolver import ExperimentResolver

RUNS = pathlib.Path(__file__).resolve().parent.parent / "runs"
ARMS = ("whole", "redraft", "holes")

#: The four funnel layers, in the order `run_funnel` applies them. A gate named
#: after a layer means "this layer and everything before it passed".
LAYERS = ("parse", "references", "scope", "typecheck")

#: Term IR tags, from `transcode.TERM_TAG`. Only the ones this probe navigates.
TAG_LAM, TAG_APP, TAG_LET, TAG_CON, TAG_MATCH, TAG_PERFORM = 3, 4, 5, 6, 7, 8
TAG_FIX, TAG_HOLE, TAG_IF = 10, 11, 12

#: `typecheck.py` builds its error paths by appending these names. Mapping each
#: to the IR index it descends is what lets `blame` resolve a recorded
#: `error_path` back to the node that actually failed — the same walk the
#: checker did, replayed without re-running it.
STEP = {
    (TAG_LAM, "body"): 2,
    (TAG_LET, "bound"): 2, (TAG_LET, "body"): 3,
    (TAG_APP, "function"): 1, (TAG_APP, "argument"): 2,
    (TAG_MATCH, "scrutinee"): 1,
    (TAG_IF, "condition"): 1, (TAG_IF, "then"): 2, (TAG_IF, "else"): 3,
    # `.measure` is IR index 3 and `.body` is 4 (typecheck.py's own naming).
    # The original entry mapped "body" to 3 — the measure. Corrected 2026-08-26
    # after B3's review; a replay showed 0 of the 12 banked blame paths traverse
    # a fix-body step, so §1's pasted evidence is unaffected by the correction.
    (TAG_FIX, "body"): 4,
    (TAG_FIX, "measure"): 3,
}

INDEXED = re.compile(r"(\w+)\[(\d+)\]")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def load(arm: str) -> list[dict]:
    path = RUNS / f"decomp-{arm}" / "records.jsonl"
    with path.open() as handle:
        return [json.loads(line) for line in handle]


def draws(records: list[dict]) -> list[dict]:
    """Every charged draw. `candidate` rows are assemblies, not draws (§8 d4)."""
    return [row for row in records if row["role"] != "candidate"]


def holed(rows: list[dict]) -> list[dict]:
    return [row for row in rows if (row.get("holes") or 0) > 0]


def fisher_one_sided(a: int, b: int, c: int, d: int) -> float:
    """P(X >= a) under the hypergeometric null for `[[a, b], [c, d]]`."""
    total, row_one, col_one = a + b + c + d, a + b, a + c
    denominator = comb(total, col_one)
    return sum(comb(row_one, x) * comb(total - row_one, col_one - x)
               for x in range(a, min(row_one, col_one) + 1)) / denominator


def wilson_lower(successes: int, n: int, z: float = 1.6449) -> float:
    """One-sided 95 % lower bound. The pilot's eligibility bar is stated on it."""
    if n == 0:
        return 0.0
    phat = successes / n
    denominator = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denominator
    half = z * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5) / denominator
    return centre - half


def navigate(term: list, components: list[str]):
    """The node a `typecheck.py` error path names, or `(None, reason)`.

    Replays the checker's own descent rather than parsing the surface, so what
    is reported is the node the checker was looking at when it failed.
    """
    node, kind = term, "term"
    for component in components:
        indexed = INDEXED.fullmatch(component)
        if indexed:
            name, index = indexed.group(1), int(indexed.group(2))
            if name == "args" and node[0] in (TAG_CON, TAG_PERFORM):
                node, kind = node[3][index], "term"
            elif name == "arms" and node[0] == TAG_MATCH:
                node, kind = node[2][index], "arm"
            else:
                return None, f"no {name}[] on tag {node[0]}"
            continue
        if kind == "arm":
            if component != "body":
                return None, f"no arm.{component}"
            node, kind = node[2], "term"
            continue
        key = (node[0], component)
        if key not in STEP:
            return None, f"no .{component} on tag {node[0]}"
        node, kind = node[STEP[key]], "term"
    return node, None


# --------------------------------------------------------------------------
# census — did §3's block induce holes at all?
# --------------------------------------------------------------------------


def census() -> None:
    print("### Hole-bearing draw rate, all three banked arms\n")
    counts = {}
    for arm in ARMS:
        rows = draws(load(arm))
        counts[arm] = (len(holed(rows)), len(rows))
        k, n = counts[arm]
        print(f"{arm:<9} {k:>3}/{n:<4} = {k / n:.3%}")
    (hk, hn), (rk, rn), (wk, wn) = counts["holes"], counts["redraft"], counts["whole"]
    print()
    print("one-sided Fisher, `holes` > `redraft`         p = "
          f"{fisher_one_sided(hk, hn - hk, rk, rn - rk):.5f}")
    print("one-sided Fisher, `holes` > pooled controls   p = "
          f"{fisher_one_sided(hk, hn - hk, rk + wk, rn + wn - rk - wk):.5f}")
    print("\n  The §3 block is a real manipulation: it multiplies the hole rate\n"
          "  6.2x over `redraft`. It is not that it failed to induce holes; it is\n"
          "  that 1.6% is ~20x short of a rate the fill path can live on.\n")

    skeletons = [row for row in load("holes") if row["role"] == "skeleton"]
    print("### Where the twelve holes came from\n")
    first = [row for row in skeletons if row["round"] == 0]
    later = [row for row in skeletons if row["round"] > 0]
    for label, rows in (("round 0 (no narrowing note)", first),
                        ("round > 0 (narrowed)", later)):
        print(f"{label:<30} {len(holed(rows)):>3}/{len(rows):<4} = "
              f"{len(holed(rows)) / len(rows):.2%}")
    print()
    by_task = collections.Counter(row["task"] for row in holed(skeletons))
    all_task = collections.Counter(row["task"] for row in skeletons)
    for task in sorted(all_task):
        print(f"  {task:<32} {by_task.get(task, 0):>2} / {all_task[task]:<4}")
    cells = {(row["task"], row["seed"]) for row in holed(skeletons)}
    print(f"\ncells with at least one hole-bearing draft: {len(cells)} of 64")

    print("\n### In-context exemplars of a hole, over everything the prompt shows\n")
    with_hole = [entry.name_path for entry in corpus_registry.MANIFEST
                 if "(hole " in entry.source_text()]
    print(f"corpus fixtures containing a `(hole ...)` node: {len(with_hole)} "
          f"of {len(corpus_registry.MANIFEST)}")
    print(f"of the four pinned few-shot names {FEW_SHOT_NAMES}: "
          f"{sum(1 for name in FEW_SHOT_NAMES if name in with_hole)}")
    print("\n  So the model has never seen `(hole ...)` written in this surface —\n"
          "  only named once in the preamble's twelve-form grammar list and\n"
          "  described in prose by §3's block. Every worked example it is shown is\n"
          "  a complete term. §3.2's exemplar block is the repair.\n")


# --------------------------------------------------------------------------
# blame — was the hole the reason the draft was rejected?
# --------------------------------------------------------------------------


def blame() -> None:
    rows = holed([row for row in load("holes") if row["role"] == "skeleton"])
    print("### The twelve hole-bearing skeletons: what actually failed\n")
    print(f"{'task':<30}{'seed':>4}  {'funnel':<11}{'failing node':<14}{'verdict'}")
    tally = collections.Counter()
    for row in sorted(rows, key=lambda r: (r["task"], r["seed"], r["draw"])):
        path = row.get("error_path") or ""
        if row["funnel_outcome"] == "accepted":
            tally["accepted (bare hole, §3 ends the round)"] += 1
            verdict, node = "bare hole — §3 ends the round unfilled", "-"
        elif path.startswith("definition.type"):
            tally["declared type, not the hole"] += 1
            verdict, node = "the DECLARED TYPE — not the hole", "type"
        else:
            term = transcode.def_to_ir(sexpr.parse_all(row["source"])[0])[2]
            found, reason = navigate(term, path.split(".")[2:])
            if found is None:
                tally[f"unresolved ({reason})"] += 1
                verdict, node = f"path unresolved: {reason}", "?"
            elif found[0] == TAG_HOLE:
                tally["the hole itself"] += 1
                verdict, node = "THE HOLE itself", "hole"
            else:
                tally["a committed sibling, not the hole"] += 1
                verdict = "a committed sibling — not the hole"
                node = f"tag {found[0]}"
        print(f"{row['task']:<30}{row['seed']:>4}  "
              f"{row['funnel_outcome']:<11}{node:<14}{verdict}")
    print()
    for label, count in tally.most_common():
        print(f"  {count:>2}  {label}")

    accepted_holed = sum(1 for row in rows if row["funnel_outcome"] == "accepted")
    skeletons = [row for row in load("holes") if row["role"] == "skeleton"]
    free = [row for row in skeletons if not (row.get("holes") or 0)]
    accepted_free = sum(1 for row in free if row["funnel_outcome"] == "accepted")
    print("\n### Hole-bearing drafts are not the worse drafts\n")
    print(f"hole-bearing accepted {accepted_holed}/{len(rows)} = "
          f"{accepted_holed / len(rows):.1%}")
    print(f"hole-free    accepted {accepted_free}/{len(free)} = "
          f"{accepted_free / len(free):.1%}")
    print("one-sided Fisher, hole-bearing > hole-free acceptance: p = "
          f"{fisher_one_sided(accepted_holed, len(rows) - accepted_holed, accepted_free, len(free) - accepted_free):.4f}")
    print("\n  Not significant at n = 12, and the direction is the opposite of the\n"
          "  report's causal chain: writing a hole did not make a draft likelier to\n"
          "  be rejected. What rejects a draft is the structure around the hole.\n")

    print("### What the checker knows about a rejection — B3's sizing\n")
    print(f"{'arm':<9}{'rejected':>9}{'raw-IR note':>13}{'expected type':>15}")
    for arm in ARMS:
        rejected = [row for row in draws(load(arm))
                    if row["funnel_outcome"] != "accepted"]
        messages = [row.get("error_message") or "" for row in rejected]
        raw = sum(1 for m in messages if re.search(r"expected \[|got \[|b'", m))
        recoverable = sum(1 for m in messages if "type mismatch: expected" in m)
        print(f"{arm:<9}{len(rejected):>9}{raw:>9} {raw / len(rejected):>3.0%}"
              f"{recoverable:>11} {recoverable / len(rejected):>3.0%}")
    print("\n  Two readings of the same column. **B3's sizing:** 41% of the `holes`\n"
          "  arm's rejections name an expected type at the failing node, so a\n"
          "  checker-holed seed has something to write into the hole that often.\n"
          "  **The feedback-legibility defect (§2.4):** the same 42% of §8.3\n"
          "  narrowing notes hand the model a raw Python `repr` of the type IR —\n"
          "  `expected [0, 2], got [1, b'?\\xf2\\x10G...']` — in an encoding it has\n"
          "  never seen in the surface. That is a real lever and a different one;\n"
          "  it would move `redraft` and `holes` together and is not folded in here.\n")


# --------------------------------------------------------------------------
# gate — what §6 row 4's relaxation buys, counted
# --------------------------------------------------------------------------


def gate() -> None:
    skeletons = [row for row in load("holes") if row["role"] == "skeleton"]
    outcomes = collections.Counter(row["funnel_outcome"] for row in skeletons)
    print("### Funnel outcome, all 747 skeleton draws\n")
    for layer in (*LAYERS, "accepted"):
        print(f"  {layer:<12}{outcomes.get(layer, 0):>4}")
    reached = len(skeletons) - sum(outcomes.get(x, 0) for x in ("parse", "references", "scope"))
    print(f"\nreached the typecheck layer (parse+references+scope passed): "
          f"{reached}/{len(skeletons)} = {reached / len(skeletons):.1%}")

    print("\n### What each candidate gate admits to a fill, on the banked draws\n")
    rows = holed(skeletons)
    for name, blocked in (("accepted (as run)", ("parse", "references", "scope", "typecheck")),
                          ("well-scoped (the §4.2 gate)", ("parse", "references", "scope")),
                          ("parses, literally", ("parse",))):
        admitted = [row for row in rows if row["funnel_outcome"] not in blocked]
        fillable = [row for row in admitted
                    if not row.get("bare_hole_body") and (row.get("holes_fillable") or 0) > 0]
        # `runner.py:828` computes `bare_hole_body` as `funnel.accepted and
        # _is_bare_hole(draft)`, so every rejected draft carries `False`
        # whatever its shape. Under a relaxed gate that conjunct is a hole in
        # the guard, so recompute §3's rule here the way the re-run must.
        recomputed, caught_bare = [], 0
        for row in fillable:
            try:
                term = transcode.def_to_ir(sexpr.parse_all(row["source"])[0])[2]
            except Exception:  # noqa: BLE001 - an unparseable draw is data
                continue
            while term[0] == TAG_LAM:
                term = term[2]
            if term[0] == TAG_HOLE:
                caught_bare += 1
            else:
                recomputed.append(row)
        cells = {(row["task"], row["seed"]) for row in recomputed}
        print(f"  {name:<28} rounds reaching a fill: {len(recomputed):>2}   "
              f"cells: {len(cells):>2}/64   "
              f"(+{caught_bare} rejected-but-bare, caught only once §3's rule is "
              f"evaluated unconditionally)")
    print("\n  The relaxed gate would have produced eight fill draws where the run\n"
          "  produced zero — and `blame` says every one of those eight drafts fails\n"
          "  at a sibling the fill does not touch, so §2.2 step 6 rolls the\n"
          "  assembly back for exactly the reason the draft was rejected. The one\n"
          "  draft whose error *was* at the hole is the ninth, and it is a bare\n"
          "  hole under zero lambdas: §3's rule refuses it, but only once that\n"
          "  rule stops being conjoined with `funnel.accepted`. **The gate alone\n"
          "  buys mechanism exposure, not composed definitions.** That is why the\n"
          "  re-run cannot be row 4's remedy on its own.\n")


# --------------------------------------------------------------------------
# mask — is `(hole ` reachable where it matters?
# --------------------------------------------------------------------------

HEADS = (b"(var ", b"(ref ", b"(lit ", b"(lam ", b"(app ", b"(let ", b"(con ",
         b"(match ", b"(perform ", b"(handle ", b"(fix ", b"(hole ", b"(if ")


def mask() -> None:
    resolver = ExperimentResolver()
    tasks = held_out_tasks()
    skeletons = [eta_skeleton(task.expected_type_surface) for task in tasks]
    vocabulary = scripted_vocabulary(
        [*skeletons, *(task.expected_type_surface for task in tasks)], max_piece=1)
    masker = build_masker(vocabulary, resolver, names=list(PRUNER_NAMES))

    print("### Admissible term heads at each task's body goal, under the real mask\n")
    print(f"{'task':<32}{'n':>3}  heads")
    for task, skeleton in zip(tasks, skeletons):
        prefix = skeleton[:skeleton.rindex("(hole ")].encode()
        masker.reset()
        for byte in prefix:
            token = vocabulary.lookup(bytes((byte,)))
            if token not in masker.step().allowed:
                print(f"{task.task_id:<32}  PREFIX REJECTED at {byte!r}")
                break
            masker.accept_token(token)
        else:
            admissible = []
            for head in HEADS:
                grammar_state, type_state = masker.gstate, masker.tstate
                for byte in head:
                    token = vocabulary.lookup(bytes((byte,)))
                    if token not in masker.step().allowed:
                        break
                    masker.accept_token(token)
                else:
                    admissible.append(head.decode().strip("( "))
                masker.gstate, masker.tstate = grammar_state, type_state
            flag = "" if "hole" in admissible else "   <-- HOLE PRUNED"
            print(f"{task.task_id:<32}{len(admissible):>3}  "
                  f"{' '.join(admissible)}{flag}")
    print("\n  `hole` is admissible at every task's body goal, as one of ten heads.\n"
          "  Neither the grammar nor the type mask is what suppresses it — the\n"
          "  model's prior over those ten heads is, and that prior is set by four\n"
          "  in-context examples that contain no hole (see `census`).\n")


# --------------------------------------------------------------------------
# exemplars — the §3.2 block, built and driven end to end
# --------------------------------------------------------------------------

MAYBE = "0x3ff2104702aeeb53b4dfbc5a09c0441df19f12883e6cf66e21a3bd85420b4e2f"

#: The worked exemplar: `corpus/bool/not` with its `then` branch holed. Chosen
#: because it is 78 characters, carries no hash at all, and its round-trip is
#: the whole protocol in three lines.
NOT_SKELETON = ("(def (fn Bool () Bool) (lam Bool (if (var 0) (hole Bool ()) "
                "(lit bool true))))")
NOT_FILL = "(def (fn Bool () Bool) (lam Bool (lit bool false)))"

#: The shape exemplar: `corpus/maybe/map` with one match arm's body holed. Shown
#: as draft + sub-task only; its fill line would add 383 characters of hashes to
#: teach a shape the worked exemplar already taught.
def maybe_map_skeleton(source: str) -> str:
    return source.replace(f"(0 0 (con {MAYBE} 0 ()))",
                          f"(0 0 (hole (data {MAYBE} (I64)) ()))")


def exemplars() -> None:
    resolver = ExperimentResolver()
    fixtures = {entry.name_path: entry.source_text().rstrip("\n")
                for entry in corpus_registry.MANIFEST}
    tasks = held_out_tasks()

    print("### Both exemplars, driven through the real funnel and splice\n")
    cases = []
    skeleton = maybe_map_skeleton(fixtures["corpus/maybe/map"])
    assert skeleton != fixtures["corpus/maybe/map"], "maybe/map arm not found"
    maybe_fill = (
        f"(def (fn (fn I64 () I64) () (fn (data {MAYBE} (I64)) () "
        f"(data {MAYBE} (I64)))) (lam (fn I64 () I64) (lam (data {MAYBE} (I64)) "
        f"(con {MAYBE} 0 ()))))")
    cases.append(("corpus/bool/not", NOT_SKELETON, NOT_FILL))
    cases.append(("corpus/maybe/map", skeleton, maybe_fill))

    for name, draft, fill in cases:
        obligations = hole_obligations(draft, resolver)
        closed = closed_subtask_type(declared_type_of(draft), obligations[0])
        assembled = splice_fill(draft, obligations[0], fill)
        print(f"{name}")
        print(f"  draft      chars={len(draft):>4}  funnel={run_funnel(draft, resolver).outcome}"
              f"  holes={len(obligations)} fillable={sum(o.fillable for o in obligations)}")
        print(f"  sub-task   chars={len(closed):>4}  (derived from the draft's own "
              f"declared type)")
        print(f"  fill       chars={len(fill):>4}  funnel={run_funnel(fill, resolver).outcome}")
        print(f"  assembled  funnel={run_funnel(assembled, resolver).outcome}"
              f"  identical-to-fixture={assembled == fixtures[name]}")

    print("\n### Leak checks on the block's bytes\n")
    # The landed constructor (prompts.hole_exemplar_block, commit 4f7b450) is
    # the single source of the block's bytes; this probe's local pieces must
    # reproduce it exactly, so the plan's pasted numbers cannot drift from
    # what the arm actually ships.
    from experiment.prompts import hole_exemplar_block
    block = hole_exemplar_block(resolver)
    local = "\n".join([NOT_SKELETON, NOT_FILL, skeleton,
                       closed_subtask_type(declared_type_of(skeleton),
                                           hole_obligations(skeleton, resolver)[0])])
    assert block == local, "probe's exemplar pieces diverge from prompts.hole_exemplar_block"
    surfaces = {t.task_id: (t.expected_surface, t.expected_type_surface) for t in tasks}
    leaks = [task for task, (term, _type) in surfaces.items() if term and term in block]
    type_leaks = [task for task, (_term, type_) in surfaces.items() if type_ in block]
    print(f"  held-out gold TERM surfaces appearing in the block: {len(leaks)} {leaks}")
    print(f"  held-out gold TYPE surfaces appearing in the block: "
          f"{len(type_leaks)} {type_leaks}")
    hashes = set(re.findall(r"0x[0-9a-f]{64}", block))
    shown = set()
    for name in FEW_SHOT_NAMES:
        shown |= set(re.findall(r"0x[0-9a-f]{64}", fixtures[name]))
    print(f"  hashes in the block not already in the four pinned few-shot "
          f"definitions: {len(hashes - shown)}")
    print(f"\n  block size: {len(block)} characters of definition surface, "
          f"~{int(len(block) / 1.5) + 1} tokens at the pinned 1.5 chars/token.")
    print("  Against the 18.8k-token held-out prompt that is a ~4% prompt "
          "increase\n  and zero completion-token cost.\n")


# --------------------------------------------------------------------------
# power
# --------------------------------------------------------------------------


def power(reps: int = 6000) -> None:
    random.seed(20260826)

    def simulate(n: int, a0: float, a1: float, alpha: float = 0.05) -> float:
        hits = 0
        for _ in range(reps):
            treated = sum(random.random() < a1 for _ in range(n))
            control = sum(random.random() < a0 for _ in range(n))
            if fisher_one_sided(treated, n - treated, control, n - control) <= alpha:
                hits += 1
        return hits / reps

    print("### P2 power, one-sided Fisher at alpha=0.05, per-cell composed-definition\n")
    print("A0 = 0.047 — the MEASURED `whole` rate (3/64), not the 0.03 the "
          "2026-08-25 plan\nplanned against. The baseline moved up, which costs "
          "power at every A1.\n")
    for a0 in (0.047, 0.03):
        print(f"  A0={a0}")
        for n in (64, 96, 128, 160):
            cells = "  ".join(f"A1={a1:.2f}:{simulate(n, a0, a1):.3f}"
                              for a1 in (0.10, 0.15, 0.20, 0.25, 0.30))
            print(f"    n={n:>4}/arm  {cells}")
        print()

    print("### P1 pilot: draw-level fillable-non-bare-hole rate, Wilson lower 95%\n")
    print("The pilot's eligibility bar is stated on the lower bound, not the point\n"
          "estimate, so a lucky pilot cannot promote a block into Stage 1.\n")
    for n in (120, 180, 240):
        row = "  ".join(f"obs={r:.0%}->lo={wilson_lower(int(r * n), n):.1%}"
                        for r in (0.10, 0.15, 0.20, 0.30, 0.50))
        print(f"  n={n:>4} draws:  {row}")
    print()


# --------------------------------------------------------------------------
# check10 — `hole_at_error` refuses rather than guesses (§4.7 check 10)
# --------------------------------------------------------------------------


#: Check 10's verdict vocabulary. `CHECK_TEN_CUT` and `CHECK_TEN_REFUSED` are
#: the two the check *permits*; everything else is a violation, and the check
#: is "no draft over the banked records lands on any other verdict".
CHECK_TEN_CUT = "cut"
CHECK_TEN_REFUSED = "refused"
CHECK_TEN_ALLOWED = (CHECK_TEN_CUT, CHECK_TEN_REFUSED)


def check_ten_verdict(draft_source: str, error_path: str, resolver) -> str:
    """One draft's check-10 verdict (2026-08-26 plan §4.7 check 10).

    > Over every banked typecheck-rejected skeleton, `hole_at_error` either
    > returns a draft that parses, keeps its declared type, and is not a bare
    > hole, or returns `None`. Never anything else.

    So the verdict is `"refused"` for `None`, `"cut"` for a repaired draft that
    satisfies all three clauses, and a **named violation** for anything else —
    the violation names being what a failing check has to print in order to be
    actionable. Re-derives each clause from the funnel's own machinery
    (`transcode_source`, `declared_type_of`, `bare_hole_body`) rather than
    trusting `hole_at_error`'s internal enforcement, since trusting the thing
    under test is not a check.

    Exported rather than inlined into `check10` below because
    `hole_elicitation_stub_check.py` — the gate on GPU spend (deliverable 6) —
    runs the same check over the same records and must run *this* definition of
    it, not a second one that could drift.
    """
    try:
        repaired = hole_at_error(draft_source, error_path, resolver)
    except Exception as error:  # noqa: BLE001 - a raise is itself a violation
        return f"VIOLATION: raised {type(error).__name__}: {error}"
    if repaired is None:
        return CHECK_TEN_REFUSED
    if not isinstance(repaired, str):
        return f"VIOLATION: returned a {type(repaired).__name__}, not a str or None"
    try:
        transcode.transcode_source(repaired)
    except Exception as error:  # noqa: BLE001
        return f"VIOLATION: the repaired draft does not parse: {error}"
    if declared_type_of(repaired) != declared_type_of(draft_source):
        return "VIOLATION: the repaired draft's declared type moved"
    if bare_hole_body(repaired):
        return "VIOLATION: the repaired draft is a bare hole (§3's rule)"
    return CHECK_TEN_CUT


def check_ten_rows(rows: list[dict]) -> list[dict]:
    """The population check 10 is defined over: **typecheck-rejected skeletons**.

    `role != "candidate"` is `draws`' own rule (a candidate is an assembly, not
    a draw); the typecheck filter is check 10's own wording. A `whole`-arm draw
    is a skeleton in this sense — it is the definition the model wrote in one
    piece — which is what lets the check run over all three banked arms and
    2,281 draws rather than the 747 of one.
    """
    return [row for row in draws(rows) if row["funnel_outcome"] == "typecheck"]


def check10() -> None:
    resolver = ExperimentResolver()
    print("### Check 10 — `hole_at_error` refuses rather than guesses\n")
    print("Over every banked typecheck-rejected skeleton: a draft that parses,\n"
          "keeps its declared type and is not a bare hole, or `None`. Never\n"
          "anything else. Refusal is the default answer, not the fallback.\n")
    totals: collections.Counter = collections.Counter()
    refusals: collections.Counter = collections.Counter()
    fillable = 0
    seeded_outcomes: collections.Counter = collections.Counter()
    for arm in ARMS:
        rows = check_ten_rows(load(arm))
        counts: collections.Counter = collections.Counter()
        for row in rows:
            verdict = check_ten_verdict(row["source"], row.get("error_path") or "", resolver)
            counts[verdict] += 1
            totals[verdict] += 1
            if verdict != CHECK_TEN_CUT:
                if verdict == CHECK_TEN_REFUSED:
                    cut = checker_holed_cut(row["source"], row.get("error_path") or "", resolver)
                    refusals[cut.reason] += 1
                continue
            repaired = hole_at_error(row["source"], row.get("error_path") or "", resolver)
            seeded_outcomes[run_funnel(repaired, resolver).outcome] += 1
            if any(o.fillable for o in hole_obligations(repaired, resolver)):
                fillable += 1
        violations = sum(n for v, n in counts.items() if v not in CHECK_TEN_ALLOWED)
        print(f"  {arm:<9} typecheck-rejected {len(rows):>5}   "
              f"cut {counts[CHECK_TEN_CUT]:>4}   refused {counts[CHECK_TEN_REFUSED]:>5}   "
              f"violations {violations}")
    violations = {v: n for v, n in totals.items() if v not in CHECK_TEN_ALLOWED}
    print(f"\n  total     cut {totals[CHECK_TEN_CUT]}   "
          f"refused {totals[CHECK_TEN_REFUSED]}   violations {sum(violations.values())}")
    for verdict, count in sorted(violations.items()):
        print(f"    {count:>5}  {verdict}")
    print(f"\n  CHECK 10: {'PASS' if not violations else 'FAIL'}\n")

    print("  Refusals, by reason (refusing is the mechanism working):")
    for reason, count in refusals.most_common():
        print(f"    {count:>5}  {reason}")
    print("\n  Seeded drafts, by funnel outcome (a hole inhabits its goal type by")
    print("  fiat — SPEC §2.6 — so a cut often repairs the failure outright):")
    for outcome, count in seeded_outcomes.most_common():
        print(f"    {count:>5}  {outcome}")
    total_draws = sum(len(draws(load(arm))) for arm in ARMS)
    print(f"\n  seeds with >= 1 fillable hole: {fillable} "
          f"= {fillable / total_draws:.2%} of all {total_draws} banked draws")
    print("  (B3's reference value for §4.2's fill-reaching draw rate, on drafts\n"
          "   drawn under the OTHER blocks — a floor, not a prediction.)\n")


SECTIONS = {
    "census": census, "blame": blame, "gate": gate,
    "mask": mask, "exemplars": exemplars, "power": power,
    "check10": check10,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--section", choices=sorted(SECTIONS), action="append",
                        help="run one section (repeatable); default is all")
    arguments = parser.parse_args(argv)
    for name in arguments.section or list(SECTIONS):
        print("=" * 78)
        print(f"## {name}")
        print("=" * 78)
        SECTIONS[name]()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
