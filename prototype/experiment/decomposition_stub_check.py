"""Deliverable 5 — the §4.8 stub-backend dry-run, CPU only, no GPU, no network.

[`docs/plans/2026-08-25-hole-decomposition.md`](../../docs/plans/2026-08-25-hole-decomposition.md)
§4.8. **This is the gate on GPU spend**: every check below must print PASS and
the script exits non-zero the moment any one of them fails, so a failing gate
cannot be missed by skimming the tail of the output.

Eight checks, driving the landed machinery rather than a second copy of it —
`prompts.hole_obligations` / `closed_subtask_type` / `fill_term_skeleton` /
`splice_fill` / `build_fill_prompt`, `runner.run_task`'s own protocol loops,
`evaluate.run_funnel` / `score_semantic`, and the audit's own route extraction:

1. **Arms differ only by their block.** `redraft`'s draw-0 prompt is
   byte-identical to `whole`'s for all eight tasks; `holes`'s skeleton prompt
   with §3's protocol block stripped is byte-identical to `whole`'s. Plus the
   three shipped configs, field by field: they may differ in
   `generation_protocol` and `output_dir` and nothing else (§2.4's pinned
   `pruners` is checked here rather than assumed, because §9 names an
   unpinned config as a thing that would change this plan).
2. **Blindness, by signature and adversarially.** `hole_obligations`,
   `closed_subtask_type` and `build_fill_prompt` take no `Task`; and two
   `Task`s identical in `spec` and `expected_type_surface` but differing in
   `composes` and `expected_surface` produce byte-identical prompts at every
   stage of every round of a full scripted cell.
3. **Expressibility (§4.4).** All eight tasks round-trip through the full
   protocol from a gold-derived **nested** draft to a byte-identical gold
   assembly meeting the floor. §1.3 ran the nested case for `reverseThen`
   alone; this is the all-eight version, and it is the check Amendment A1
   taught us not to skip.
4. **Floor-rule regression.** The eight eta-skeletons are funnel-accepted and
   type-exact — they meet the *pre-fix* floor by construction — and
   `score_semantic` refuses every one of them on §5.4 grounds, while the
   hole-free gold term at the same type passes. Fail-then-pass, run against
   the shipped rule.
5. **Context.** `context_required` clears `n_ctx − max_tokens_per_draw` for
   every arm, and so does the worst-case *fill* prompt built from the largest
   gold-derived draft (`context_required`'s own docstring defers that figure
   to this check).
6. **No gold leak.** No gold surface appears in any built prompt — skeleton or
   fill, any arm, any task.
7. **Stub-backend end to end.** A scripted stub drives one cell of each arm and
   the check asserts the budget rule (full cap or no draw, every draw charged,
   no cell over its purse) and that the accepted-draft, rejected-draft,
   bare-hole, unfillable-hole, splice and assembly-rollback paths are each
   exercised, with round/candidate bookkeeping consistent with the records.
8. **Baseline reproduction.** Route-reference extraction over the recorded
   `addr-*` arms reproduces 1 / 10 / 21 draws exactly, through
   `address_book_analysis.arm_stats` — the address-book report's own code path.

Where §4.8's check text names a signature the landed code spells differently,
the difference is the one §8's deliverable-3/4 notes record, and the check tests
the **landed** contract and says so in a `note:` line of its own output. Nothing
here re-litigates those notes.

    python3 -m experiment.decomposition_stub_check   (from prototype/)
"""

from __future__ import annotations

import dataclasses
import inspect
import sys
from pathlib import Path

from transcode import def_to_surface, term_to_surface, transcode_source, type_to_surface

from experiment import address_book_analysis, heldout_gold, prompts, runner
from experiment.addressability_audit import _route_hashes
from experiment.backends import Generation, StubBackend
from experiment.evaluate import run_funnel, score_semantic
from experiment.heldout_gold import GOLD_TERMS
from experiment.prompts import (
    HELD_OUT_TASKS,
    KIND_HELD_OUT,
    REGIME_HELD_OUT,
    Task,
    build_fill_prompt,
    build_prompt,
    closed_subtask_type,
    declared_type_of,
    eta_skeleton,
    fill_term_skeleton,
    hole_obligations,
    peel_arrows,
    splice_fill,
)
from experiment.resolver import ExperimentResolver

CONFIG_DIR = Path(__file__).resolve().parent

#: The three §4.2 arm configs, as committed. Loaded exactly as the runner loads
#: them — `Config.load` anchors `store_export` to this directory and runs
#: `validate()`, so a check here fails the same way a real launch would.
ARMS = ("decomp-whole", "decomp-redraft", "decomp-holes")

#: The only two fields §4.2 licenses the arms to differ in.
ARM_FIELD_EXCEPTIONS = ("generation_protocol", "output_dir", "source_path")

#: §4.6's route-reference baseline, per recorded `addr-*` arm (draws of 320).
EXPECTED_ROUTE_DRAWS = {"addr-none": 1, "addr-full": 10, "addr-typed": 21}

TASKS_BY_ID = {task.task_id: task for task in HELD_OUT_TASKS}

#: The task the check-7 stub cell runs. `headOrElse` is the one whose gold term
#: carries a nested `match`, so the same fixture yields both a fillable hole and
#: an unfillable one without a second task's worth of scaffolding.
STUB_TASK = TASKS_BY_ID["heldout/list/headOrElse"]


def _load_arms() -> dict[str, runner.Config]:
    return {name: runner.Config.load(CONFIG_DIR / f"{name}.config.json") for name in ARMS}


# --------------------------------------------------------------------------
# Gold-derived nested drafts — the fixtures checks 3, 5, 6 and 7 are built from
# --------------------------------------------------------------------------
#
# A *nested* draft is what carries the mechanism (§1.3): the eta-skeleton's one
# hole has the original task as its sub-goal, so it decomposes nothing. Choosing
# where to cut is done mechanically and from the term alone — the largest
# argument of a `ref`-headed application spine, its goal type read off the
# referenced object's **own declared type** through `peel_arrows`. Nothing here
# consults `Task.composes` or `expected_surface`; the point of §4.8 check 2 is
# that the generation path cannot, and a fixture builder that did would make
# this check's drafts unrepresentative of the ones a run will actually see.


def _term_positions(node: list, path: tuple[int, ...]):
    """`(path, node)` for every *term* position, mirroring `prompts._walk_holes`.

    The mirror is deliberate: a path this walk produces has to be a path
    `hole_obligations` will produce for the same hole, or `splice_fill` puts the
    fill somewhere else. Type annotations are not descended into — a type is not
    a position a subterm goes.
    """
    yield path, node
    tag = node[0]
    if tag == 3:  # lam TYPE BODY
        yield from _term_positions(node[2], path + (2,))
    elif tag == 4:  # app FUNCTION ARGUMENT
        yield from _term_positions(node[1], path + (1,))
        yield from _term_positions(node[2], path + (2,))
    elif tag == 5:  # let TYPE BOUND BODY
        yield from _term_positions(node[2], path + (2,))
        yield from _term_positions(node[3], path + (3,))
    elif tag in (6, 8):  # con / perform HASH INDEX (ARGS)
        for index, argument in enumerate(node[3]):
            yield from _term_positions(argument, path + (3, index))
    elif tag == 7:  # match SCRUTINEE ((INDEX ARITY BODY) …)
        yield from _term_positions(node[1], path + (1,))
        for index, arm in enumerate(node[2]):
            yield from _term_positions(arm[2], path + (2, index, 2))
    elif tag == 9:  # handle HASH HANDLED ((INDEX BODY) …) RETURN
        yield from _term_positions(node[2], path + (2,))
        for index, operation in enumerate(node[3]):
            yield from _term_positions(operation[1], path + (3, index, 1))
        yield from _term_positions(node[4], path + (4,))
    elif tag == 10:  # fix TYPE POSITION MEASURE BODY
        yield from _term_positions(node[3], path + (3,))
        yield from _term_positions(node[4], path + (4,))
    elif tag == 12:  # if CONDITION THEN ELSE
        for index in (1, 2, 3):
            yield from _term_positions(node[index], path + (index,))


def _replace_at(node, path: tuple[int, ...], replacement):
    if not path:
        return replacement
    copied = list(node)
    copied[path[0]] = _replace_at(node[path[0]], path[1:], replacement)
    return copied


def _hole_ir(goal_surface: str) -> list:
    """The `(hole GOAL ())` node, built through the transcoder rather than by hand."""
    ir, _, _ = transcode_source(f"(def Bool (hole {goal_surface} ()))")
    return ir[2]


def _blankable(gold: str, resolver: ExperimentResolver):
    """`(path, subterm surface, goal surface)` for the subterm this check blanks.

    The largest argument of any `ref`-headed application spine. Its type needs
    no synthesis: it is the k-th domain of the referenced object's declared
    type, which the resolver hands over. That keeps the fixture as blind as the
    protocol it is exercising.
    """
    ir, _, _ = transcode_source(gold)
    best = None
    for path, node in _term_positions(ir[2], (2,)):
        if node[0] != 4:  # app
            continue
        head, head_path, arguments = node, path, []
        while head[0] == 4:
            arguments.append((head_path + (2,), head[2]))
            head, head_path = head[1], head_path + (1,)
        arguments.reverse()
        if head[0] != 1:  # not a `ref`-headed spine
            continue
        domains, _rows, _goal = peel_arrows(type_to_surface(resolver.resolve(head[1]).type_ir))
        for index, (argument_path, argument) in enumerate(arguments):
            if index >= len(domains):
                continue
            surface = term_to_surface(argument)
            if best is None or len(surface) > len(best[1]):
                best = (argument_path, surface, domains[index])
    return best


def nested_case(task: Task, resolver: ExperimentResolver) -> dict:
    """One task's gold-derived nested draft and everything the protocol makes of it.

    Every step after the blanking is the **landed** machinery: obligations out
    of the draft, the closure out of the draft's own declared type, the splice
    through `splice_fill`, the verdict through `run_funnel` + `score_semantic`.
    """
    gold = GOLD_TERMS[task.task_id]
    ir, _, _ = transcode_source(gold)
    path, subterm, goal = _blankable(gold, resolver)
    draft = def_to_surface(_replace_at(ir, path, _hole_ir(goal)))
    row = {
        "task": task.task_id,
        "gold": gold,
        "draft": draft,
        "path": path,
        "subterm": subterm,
        "draft_funnel": run_funnel(draft, resolver),
    }
    row["type_preserved"] = row["draft_funnel"].type_surface == task.expected_type_surface
    row["nested"] = not prompts.bare_hole_body(draft)
    obligations = hole_obligations(draft, resolver)
    row["obligation"] = next((o for o in obligations if o.path == path), None)
    if row["obligation"] is None or not row["obligation"].fillable:
        return row
    obligation = row["obligation"]
    closed = closed_subtask_type(declared_type_of(draft), obligation)
    fill = f"(def {closed} {fill_term_skeleton(obligation).replace(obligation.surface, subterm)})"
    row["closed"] = closed
    row["fill"] = fill
    row["fill_funnel"] = run_funnel(fill, resolver)
    assembled = splice_fill(draft, obligation, fill)
    row["assembled"] = assembled
    row["identical"] = assembled == gold
    row["assembled_funnel"] = run_funnel(assembled, resolver)
    row["floor"] = score_semantic(task, row["assembled_funnel"], assembled).success
    return row


def _nested_cases(resolver: ExperimentResolver) -> dict[str, dict]:
    return {task.task_id: nested_case(task, resolver) for task in HELD_OUT_TASKS}


# --------------------------------------------------------------------------
# Check 1 — the arms differ only by their block (and by nothing in the configs)
# --------------------------------------------------------------------------


def check_1(arms, resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 1 — the arms differ only by §3's block\n"]
    ok = True
    for task in HELD_OUT_TASKS:
        built = {
            protocol: build_prompt(
                task, REGIME_HELD_OUT, resolver,
                address_book=arms["decomp-whole"].address_book,
                generation_protocol=protocol)
            for protocol in prompts.GENERATION_PROTOCOLS
        }
        redraft_identical = built[prompts.PROTOCOL_REDRAFT] == built[prompts.PROTOCOL_WHOLE]
        block = prompts.HOLE_PROTOCOL_BLOCK
        stripped = built[prompts.PROTOCOL_HOLES].replace(f"\n\n{block}", "", 1)
        holes_identical = stripped == built[prompts.PROTOCOL_WHOLE]
        ok = ok and redraft_identical and holes_identical
        lines.append(
            f"{task.task_id:<32} redraft==whole={'yes' if redraft_identical else 'NO':<3}  "
            f"holes-minus-block==whole={'yes' if holes_identical else 'NO':<3}  "
            f"block={len(block)}B"
        )

    lines.append("")
    reference = dataclasses.asdict(arms["decomp-whole"])
    for name in ARMS[1:]:
        other = dataclasses.asdict(arms[name])
        differing = sorted(
            key for key in reference
            if reference[key] != other[key] and key not in ARM_FIELD_EXCEPTIONS)
        ok = ok and not differing
        lines.append(f"{name:<16} config fields differing from decomp-whole "
                     f"beyond {list(ARM_FIELD_EXCEPTIONS[:2])}: {differing}")
    for name in ARMS:
        pinned = arms[name].pruners == ["goal-type", "de-bruijn", "ref-hash"]
        ok = ok and pinned
        lines.append(f"{name:<16} pruners={arms[name].pruners} "
                     f"{'pinned' if pinned else 'DRIFTED'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'} — "
                 f"{len(HELD_OUT_TASKS)} tasks, {len(ARMS)} configs")
    return ok, lines


# --------------------------------------------------------------------------
# Check 2 — blindness, by signature and adversarially
# --------------------------------------------------------------------------


def check_2a(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 2a — the new surfaces take no Task, by signature\n"]
    lines.append(
        "note: §4.8 spells the closure `closed_subtask_type(…, context)`; the landed "
        "signature is\n      `(declared_type_surface, obligation)` — a `HoleObligation` "
        "*is* the hole's context\n      (§8 deliverable 3, first bullet). The pin below is "
        "against the landed spelling.\n")
    expected = {
        "hole_obligations": ["source", "resolver"],
        "closed_subtask_type": ["declared_type_surface", "obligation"],
        "fill_term_skeleton": ["obligation"],
        "splice_fill": ["draft_source", "obligation", "fill_source"],
        "build_fill_prompt": [
            "spec", "regime", "resolver", "draft_source", "obligation", "narrowing",
            "address_book", "exclude_identity"],
    }
    ok = True
    for name, want in expected.items():
        parameters = list(inspect.signature(getattr(prompts, name)).parameters)
        match = parameters == want
        no_task = not any("task" in parameter for parameter in parameters)
        ok = ok and match and no_task
        lines.append(f"{name:<22} {parameters}  "
                     f"{'as landed' if match else 'UNEXPECTED'}  "
                     f"{'no Task' if no_task else 'TAKES A TASK'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


#: The adversarial pair: same `spec`, same `expected_type_surface`, different
#: `composes` and `expected_surface`. If any of the three protocols' prompts
#: could see either of those two fields, these two cells' prompt streams would
#: diverge; §4.8 check 2 is that they cannot.
def _adversarial_pair() -> tuple[Task, Task]:
    honest = STUB_TASK
    return (
        dataclasses.replace(
            honest, task_id="adversary/a", kind=KIND_HELD_OUT,
            composes=honest.composes, expected_surface=GOLD_TERMS[honest.task_id]),
        dataclasses.replace(
            honest, task_id="adversary/b", kind=KIND_HELD_OUT,
            composes=("corpus/list/append", "corpus/list/reverse"),
            expected_surface=GOLD_TERMS["heldout/list/reverseThen"]),
    )


def check_2b(arms, resolver, fixtures) -> tuple[bool, list[str]]:
    lines = ["### Check 2b — adversarial: composes/expected_surface cannot reach a prompt\n"]
    left, right = _adversarial_pair()
    lines.append("two Tasks, identical spec and expected_type_surface:")
    lines.append(f"  {left.task_id:<14} composes={list(left.composes)}")
    lines.append(f"  {right.task_id:<14} composes={list(right.composes)}")
    lines.append("")
    ok = True
    for name in ARMS:
        config = _stub_config(arms[name])
        streams = []
        for task in (left, right):
            backend = _ScriptedStub(_skeleton_script(fixtures), _fill_script(fixtures))
            runner.run_task(
                task, config.conditions[0], REGIME_HELD_OUT, config.seeds[0],
                backend, resolver, config, runner.grammar_text())
            streams.append(tuple(backend.prompts))
        identical = streams[0] == streams[1]
        ok = ok and identical and len(streams[0]) > 1
        lines.append(f"{name:<16} {len(streams[0])} prompts per cell  "
                     f"{'byte-identical' if identical else 'DIVERGED'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 3 — expressibility: all eight tasks, nested round-trip (§4.4)
# --------------------------------------------------------------------------


def check_3(fixtures) -> tuple[bool, list[str]]:
    lines = ["### Check 3 — all eight gold answers round-trip through a NESTED draft\n"]
    lines.append(
        "note: §1.3 ran this for `reverseThen` alone. The subterm blanked here is chosen\n"
        "      mechanically — the largest argument of a `ref`-headed application spine, its\n"
        "      goal type read off the referenced object's own declared type — never from\n"
        "      `composes`. `nested=True` is `bare_hole_body(draft)` being False: the hole is\n"
        "      strictly inside the body, so the sub-goal is genuinely smaller than the task.\n")
    ok = True
    dropped = []
    for task in HELD_OUT_TASKS:
        row = fixtures[task.task_id]
        good = (
            row["draft_funnel"].accepted
            and row["type_preserved"]
            and row["nested"]
            and row.get("obligation") is not None
            and row["obligation"].fillable
            and row.get("fill_funnel") is not None
            and row["fill_funnel"].accepted
            and row.get("identical")
            and row["assembled_funnel"].accepted
            and row.get("floor")
        )
        ok = ok and good
        if not good:
            dropped.append(task.task_id)
        lines.append(
            f"{task.task_id:<32} draft={row['draft_funnel'].outcome:<9} "
            f"type-preserved={str(row['type_preserved']):<5} nested={str(row['nested']):<5} "
            f"sub={len(row['subterm']):>4}ch closed={len(row.get('closed', '')):>4}ch "
            f"fill={(row.get('fill_funnel').outcome if row.get('fill_funnel') else 'n/a'):<9} "
            f"identical={str(row.get('identical')):<5} floor={row.get('floor')}"
        )
    lines.append(f"\ntasks expressible: {len(HELD_OUT_TASKS) - len(dropped)} of "
                 f"{len(HELD_OUT_TASKS)}; dropped: {dropped or 'none'}")
    lines.append("§4.4's stopping condition (battery below six tasks) does not fire."
                 if len(HELD_OUT_TASKS) - len(dropped) >= 6
                 else "§4.4's stopping condition FIRES: the battery is below six tasks.")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 4 — the floor rule refuses a hole-bearing definition (§4.3.1)
# --------------------------------------------------------------------------


def check_4(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 4 — floor-rule regression: fail-then-pass on the eight eta-skeletons\n"]
    lines.append(
        "`would_have_met` is the *pre-fix* rule (accepted ∧ type-exact) recomputed here: it is\n"
        "True for every skeleton, which is what makes this a regression proof rather than a\n"
        "restatement. `floor_now` is the shipped `score_semantic`.\n")
    ok = True
    for task in HELD_OUT_TASKS:
        skeleton = eta_skeleton(task.expected_type_surface)
        funnel = run_funnel(skeleton, resolver)
        semantic = score_semantic(task, funnel, skeleton)
        would_have_met = funnel.accepted and funnel.type_surface == task.expected_type_surface
        gold = GOLD_TERMS[task.task_id]
        gold_semantic = score_semantic(task, run_funnel(gold, resolver), gold)
        good = would_have_met and not semantic.success and gold_semantic.success
        ok = ok and good
        lines.append(
            f"{task.task_id:<32} skeleton funnel={funnel.outcome:<9} "
            f"would_have_met={str(would_have_met):<5} floor_now={str(semantic.success):<5} "
            f"gold_floor={gold_semantic.success}"
        )
    detail = score_semantic(
        HELD_OUT_TASKS[0],
        run_funnel(eta_skeleton(HELD_OUT_TASKS[0].expected_type_surface), resolver),
        eta_skeleton(HELD_OUT_TASKS[0].expected_type_surface)).detail
    lines.append(f"\nrefusal detail: {detail}")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 5 — context, skeleton prompts and the worst-case fill prompt
# --------------------------------------------------------------------------


def check_5(arms, resolver, fixtures) -> tuple[bool, list[str]]:
    lines = ["### Check 5 — context_required <= n_ctx - max_tokens_per_draw, every arm\n"]
    ok = True
    worst_task, worst = max(
        fixtures.items(), key=lambda item: len(item[1]["draft"]))
    for name in ARMS:
        config = arms[name]
        threshold = config.n_ctx - config.max_tokens_per_draw
        skeleton = prompts.context_required(
            config.regimes, resolver, leave_one_out=config.leave_one_out,
            address_book=config.address_book,
            generation_protocol=config.generation_protocol)
        fill_prompt = build_fill_prompt(
            TASKS_BY_ID[worst_task].spec, REGIME_HELD_OUT, resolver,
            draft_source=worst["draft"], obligation=worst["obligation"],
            narrowing=prompts_worst_narrowing(worst, resolver),
            address_book=config.address_book)
        fill = prompts.estimated_tokens(fill_prompt)
        longest = max(skeleton, fill)
        clears = longest <= threshold
        ok = ok and clears
        lines.append(
            f"{name:<16} skeleton={skeleton:>6} tok  worst-case fill={fill:>6} tok  "
            f"threshold={threshold:>6}  {'OK' if clears else 'EXCEEDS'}"
        )
    lines.append(f"\nworst-case draft: {worst_task} ({len(worst['draft'])} chars), "
                 f"carried with a narrowing note")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def prompts_worst_narrowing(row, resolver) -> str:
    """A realistic narrowing note for the worst-case fill prompt.

    A fill retry carries one (§2.2 step 6), so the worst case includes it; it is
    produced by the harness's own `narrowing_note` over a genuinely rejected
    definition rather than invented at a convenient length.
    """
    from experiment.evaluate import narrowing_note

    return narrowing_note(run_funnel("(def Bool (lit i64 0))", resolver))


# --------------------------------------------------------------------------
# Check 6 — no gold surface in any built prompt, skeleton or fill
# --------------------------------------------------------------------------


def check_6(arms, resolver, fixtures) -> tuple[bool, list[str]]:
    lines = ["### Check 6 — no gold surface appears in any built prompt\n"]
    lines.append(
        "note: a fill prompt carries the *draft*, which in a run is the model's own. Both\n"
        "      draft shapes are checked: a model-writable one (the eta-skeleton, gold-free by\n"
        "      construction) and check 3's gold-derived one. In neither does any task's gold\n"
        "      surface appear — the harness adds nothing beyond the draft it was handed.\n")
    offenders: list[str] = []
    skeleton_prompts = fill_prompts = 0
    for name in ARMS:
        config = arms[name]
        for task in HELD_OUT_TASKS:
            prompt = build_prompt(
                task, REGIME_HELD_OUT, resolver,
                leave_one_out=config.leave_one_out,
                address_book=config.address_book,
                generation_protocol=config.generation_protocol)
            skeleton_prompts += 1
            for other, gold in GOLD_TERMS.items():
                if gold in prompt:
                    offenders.append(f"{name} skeleton {task.task_id} <- gold of {other}")
            # Two drafts: the model-writable eta-skeleton, and check 3's
            # gold-derived nested draft.
            drafts = [eta_skeleton(task.expected_type_surface), fixtures[task.task_id]["draft"]]
            for draft in drafts:
                obligation = next(
                    (o for o in hole_obligations(draft, resolver) if o.fillable), None)
                if obligation is None:
                    continue
                prompt = build_fill_prompt(
                    task.spec, REGIME_HELD_OUT, resolver,
                    draft_source=draft, obligation=obligation,
                    address_book=config.address_book,
                    exclude_identity=task.expected_identity if config.leave_one_out else "")
                fill_prompts += 1
                for other, gold in GOLD_TERMS.items():
                    if gold in prompt:
                        offenders.append(f"{name} fill {task.task_id} <- gold of {other}")
    module_check = heldout_gold.prompt_leak_check()
    ok = not offenders and not module_check
    lines.append(f"skeleton prompts checked  {skeleton_prompts:>4}")
    lines.append(f"fill prompts checked      {fill_prompts:>4}")
    lines.append(f"gold surfaces searched for {len(GOLD_TERMS):>3} (every task's, in every prompt)")
    lines.append(f"heldout_gold.prompt_leak_check(): {module_check or 'no offenders'}")
    for offender in offenders:
        lines.append(f"LEAK — {offender}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 7 — a scripted stub drives one cell of each arm
# --------------------------------------------------------------------------


class _ScriptedStub(StubBackend):
    """A stub that answers by *prompt shape*: a skeleton ask and a fill ask differ.

    The `holes` protocol makes two kinds of call inside one cell, so a single
    round-robin script cannot express a scenario. This keeps a script per kind
    and repeats each script's last entry, which is what `fill_attempts_per_hole`
    needs: the same bad fill offered twice. `allotments` records what the runner
    granted each draw, which is how the full-cap-or-no-draw rule is checked from
    the outside rather than read off the loop that implements it.
    """

    def __init__(self, skeletons, fills):
        super().__init__(list(skeletons))
        self.skeleton_script = list(skeletons)
        self.fill_script = list(fills)
        self.skeleton_prompts: list[str] = []
        self.fill_prompts: list[str] = []
        self.allotments: list[int] = []

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        is_fill = prompts.FILL_HEADER in prompt
        script = self.fill_script if is_fill else self.skeleton_script
        seen = self.fill_prompts if is_fill else self.skeleton_prompts
        text = script[min(len(seen), len(script) - 1)]
        seen.append(prompt)
        self.prompts.append(prompt)
        self.allotments.append(max_tokens)
        self.draws += 1
        natural = max(1, len(text) // 4)
        used = min(natural, max_tokens)
        return Generation(
            text=text, completion_tokens=used, prompt_tokens=max(1, len(prompt) // 4),
            latency_s=0.0, stop_reason="length" if used < natural else "stop",
            backend=self.name)


#: A definition that fails the funnel outright — the rejected-draft path.
REJECTED_DRAFT = "(def Bool (lit i64 0))"


def _unfillable_draft(row) -> str:
    """The check-3 draft's blanked position moved *under a `match` arm binder*.

    A match's arms have the match's own type, so the hole's goal is the same
    surface check 3 already derived — no new type knowledge, and no synthesis,
    which is exactly the thing §2.2 step 3 says v1 cannot do for the *binder*.
    """
    ir, _, _ = transcode_source(row["gold"])
    match_path = row["path"]
    match_node = ir
    for step in match_path:
        match_node = match_node[step]
    if match_node[0] != 7:  # not a match — no unfillable fixture from this task
        return ""
    goal = row["obligation"].goal_surface
    # Arm 1 of `headOrElse`'s outer match binds one variable, so every hole
    # beneath it is `fillable=False` with the `match` reason.
    arm_index = next(
        (index for index, arm in enumerate(match_node[2]) if arm[1] >= 1), None)
    if arm_index is None:
        return ""
    return def_to_surface(
        _replace_at(ir, match_path + (2, arm_index, 2), _hole_ir(goal)))


def _skeleton_script(fixtures) -> list[str]:
    """The five skeleton draws §4.8 check 7 needs, in the order a cell sees them."""
    row = fixtures[STUB_TASK.task_id]
    return [
        row["draft"],              # round 0: accepted, one fillable hole -> spliced
        REJECTED_DRAFT,            # round 1: rejected-draft path
        eta_skeleton(STUB_TASK.expected_type_surface),  # round 2: bare-hole path
        _unfillable_draft(row),    # round 3: unfillable-hole path
        row["draft"],              # round 4+: accepted, but the fills go wrong
    ]


def _fill_script(fixtures) -> list[str]:
    """A good fill, then a fill that typechecks at the wrong type — the rollback.

    §8's deliverable-4 note: a fill's declared type is *not* checked against the
    closed sub-task type, so a fill that typechecks standalone at some other type
    splices cleanly and is refused by the re-check. That is the rollback path's
    most realistic trigger, and this is it: the same binders, an `I64` body where
    the hole's goal is not `I64`.
    """
    row = fixtures[STUB_TASK.task_id]
    obligation = row["obligation"]
    good = row["fill"]
    wrong = dataclasses.replace(obligation, goal_surface="I64")
    bad = (f"(def {closed_subtask_type(declared_type_of(row['draft']), wrong)} "
           f"{fill_term_skeleton(wrong).replace(wrong.surface, '(lit i64 0)')})")
    return [good, bad]


def _stub_config(arm: runner.Config) -> runner.Config:
    """The arm's config, pointed at the stub and one cell.

    Everything §4.3 pins about the *budget* is kept exactly — purse, per-draw
    cap, draw cap, `stop_on_semantic_success` — because the budget rule is what
    this check is for. Two things are not the arm's: `backend` is the stub, and
    the condition is `gbnf` rather than `gbnf+typemask`, because the mask needs a
    real vocabulary. `_CellRun` is the same object under either condition — a
    masked draw and a grammared draw are one full-cap grant against one purse —
    so the budget and protocol paths checked here are condition-independent.
    """
    config = dataclasses.replace(
        arm,
        backend="stub",
        conditions=[runner.CONDITION_GBNF],
        seeds=[1],
        tasks=[STUB_TASK.task_id],
        stub_outputs=[REJECTED_DRAFT],
        stub_grammar_outputs=[REJECTED_DRAFT],
        source_path="<decomposition_stub_check>",
    )
    config.validate()
    return config


def _drive(arm: runner.Config, fixtures, resolver) -> tuple[list[dict], _ScriptedStub]:
    config = _stub_config(arm)
    backend = _ScriptedStub(_skeleton_script(fixtures), _fill_script(fixtures))
    records = runner.run_task(
        STUB_TASK, config.conditions[0], REGIME_HELD_OUT, config.seeds[0],
        backend, resolver, config, runner.grammar_text())
    return records, backend


def check_7(arms, resolver, fixtures) -> tuple[bool, list[str]]:
    lines = ["### Check 7 — a scripted stub drives one cell of each arm\n"]
    lines.append(
        "note: the cell runs at condition `gbnf` (the mask needs a real vocabulary); the\n"
        "      purse, the per-draw cap and the draw cap are the arm's own. `_CellRun` is the\n"
        "      same object under either condition, so the budget rule checked here is the\n"
        "      one that will bind on the GPU. §4.3.6's constants are config fields (§8\n"
        "      deliverable 4), so the round is driven to its limits without editing the\n"
        "      harness.\n")
    ok = True
    for name in ARMS:
        config = _stub_config(arms[name])
        records, backend = _drive(arms[name], fixtures, resolver)
        draws = [r for r in records if r["role"] in runner.DRAW_ROLES]
        candidates = [r for r in records if r["candidate"]]
        # -- the budget rule ------------------------------------------------
        full_cap = all(a == config.max_tokens_per_draw for a in backend.allotments)
        charged = sum(r["tokens_completion"] for r in draws) == records[-1]["tokens_used"]
        within = records[-1]["tokens_used"] <= config.token_budget_per_task
        no_room = (config.token_budget_per_task - records[-1]["tokens_used"]
                   < config.max_tokens_per_draw) or len(draws) >= config.max_draws_per_task
        done = records[-1]["cell_done"] and not any(r["cell_done"] for r in records[:-1])
        zero_cost = all(
            r["tokens_completion"] == 0 for r in records if r["role"] == runner.ROLE_CANDIDATE)
        indices = [r["draw"] for r in records] == list(range(len(records)))
        budget_ok = all((full_cap, charged, within, no_room, done, zero_cost, indices))
        # -- the protocol paths ---------------------------------------------
        skeletons = [r for r in records if r["role"] == runner.ROLE_SKELETON]
        fills = [r for r in records if r["role"] == runner.ROLE_FILL]
        outcomes = {r["splice_outcome"] for r in fills}
        paths = {
            "accepted-draft": any(r["funnel_outcome"] == "accepted" for r in skeletons or draws),
            "rejected-draft": any(r["funnel_outcome"] != "accepted" for r in skeletons or draws),
            "bare-hole": any(r.get("bare_hole_body") for r in records),
            "unfillable-hole": any(
                r["holes"] > 0 and r["holes_fillable"] == 0 for r in records),
            "spliced": runner.SPLICE_SPLICED in outcomes,
            "assembly-rollback": runner.SPLICE_ROLLED_BACK in outcomes,
        }
        if name == "decomp-holes":
            rounds = sorted({r["round"] for r in records})
            bookkeeping = (
                rounds == list(range(len(rounds)))
                and all(sum(1 for r in records
                            if r["round"] == n and r["role"] == runner.ROLE_SKELETON) == 1
                        for n in rounds)
                and all(sum(1 for r in records
                            if r["round"] == n and r["role"] == runner.ROLE_CANDIDATE) == 1
                        for n in rounds)
                and len(candidates) == len(rounds))
            protocol_ok = all(paths.values()) and bookkeeping
            floor_hit = any(r["semantic_success"] for r in candidates)
            protocol_ok = protocol_ok and floor_hit
        else:
            # `whole`/`redraft` write no holes: every draw is its own candidate,
            # and `redraft` is the arm that narrows.
            bookkeeping = (len(candidates) == len(draws)
                           and all(r["role"] == runner.ROLE_WHOLE for r in draws))
            narrows = any(r["narrowed"] for r in records)
            protocol_ok = bookkeeping and (
                narrows if arms[name].generation_protocol == prompts.PROTOCOL_REDRAFT
                else not narrows)
        ok = ok and budget_ok and protocol_ok
        lines.append(
            f"{name:<16} records={len(records):>3} draws={len(draws):>3} "
            f"candidates={len(candidates):>3} rounds={len({r['round'] for r in records}):>3} "
            f"tokens={records[-1]['tokens_used']:>5}/{config.token_budget_per_task}"
        )
        lines.append(
            f"{'':<16} budget: full-cap-or-no-draw={full_cap} every-draw-charged={charged} "
            f"within-purse={within} ends-when-no-room={no_room} candidate-cost-0={zero_cost}"
        )
        if name == "decomp-holes":
            lines.append(f"{'':<16} paths: " + " ".join(
                f"{path}={'yes' if hit else 'NO'}" for path, hit in paths.items()))
            lines.append(f"{'':<16} bookkeeping: one skeleton + one candidate per round="
                         f"{bookkeeping}  a candidate met the floor={floor_hit}")
        else:
            lines.append(f"{'':<16} bookkeeping: every draw is its own candidate={bookkeeping}  "
                         f"narrowed={any(r['narrowed'] for r in records)}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 8 — route-reference extraction reproduces the recorded baseline
# --------------------------------------------------------------------------


def check_8(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 8 — route-reference extraction over the recorded addr-* arms\n"]
    lines.append(
        "Through `address_book_analysis.arm_stats`, which is the address-book report's own\n"
        "code path (it reuses the audit's `_route_hashes` / `_REF_RE`) — so every arm number\n"
        "in the decomposition report shares a code path with that report's.\n")
    required_all = _route_hashes(resolver, definitions_only=False)
    required_defs = _route_hashes(resolver, definitions_only=True)
    ok = True
    for arm, expected in EXPECTED_ROUTE_DRAWS.items():
        try:
            records = address_book_analysis.load(arm)
        except FileNotFoundError:
            lines.append(f"{arm:<12} records absent — run not in this checkout")
            ok = False
            continue
        stats = address_book_analysis.arm_stats(records, resolver, required_all, required_defs)
        match = stats["route_all"] == expected and stats["draws"] == 320
        ok = ok and match
        lines.append(
            f"{arm:<12} draws={stats['draws']:>4} (expected 320)  "
            f"route-complete draws={stats['route_all']:>3} (expected {expected:>2})  "
            f"{'match' if match else 'MISMATCH'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def main() -> int:
    resolver = ExperimentResolver()
    arms = _load_arms()
    fixtures = _nested_cases(resolver)
    checks = [
        ("1", lambda: check_1(arms, resolver)),
        ("2a", lambda: check_2a(resolver)),
        ("2b", lambda: check_2b(arms, resolver, fixtures)),
        ("3", lambda: check_3(fixtures)),
        ("4", lambda: check_4(resolver)),
        ("5", lambda: check_5(arms, resolver, fixtures)),
        ("6", lambda: check_6(arms, resolver, fixtures)),
        ("7", lambda: check_7(arms, resolver, fixtures)),
        ("8", lambda: check_8(resolver)),
    ]
    all_ok = True
    for index, (_number, function) in enumerate(checks):
        if index:
            print()
        ok, lines = function()
        for line in lines:
            print(line)
        all_ok = all_ok and ok

    print()
    print(f"### Deliverable 5 verdict: "
          f"{'ALL CHECKS PASS — the GPU gate is open' if all_ok else 'AT LEAST ONE CHECK FAILED — do not launch'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
