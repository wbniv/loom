"""Deliverable 6 — the §4.7 stub-backend gate on GPU spend. CPU only, no GPU, no network.

[`docs/plans/2026-08-26-hole-elicitation.md`](../../docs/plans/2026-08-26-hole-elicitation.md)
§4.7. **This is the gate on GPU spend**: every check below must print PASS and
the script exits non-zero the moment any one of them fails, so a failing gate
cannot be missed by skimming the tail of the output. Precedent and idiom:
`decomposition_stub_check.py` (deliverable 5 of the 2026-08-25 plan).

§4.7 cites checks **2, 3, 4, 5, 6, 8** of that gate rather than re-running them —
nothing in this design touches the machinery they pin — and re-runs **1** and
**7**, adding **9** and **10**. What the citation does *not* cover is the
surfaces this plan added, so checks 2, 5 and 6 appear here in **extended** form:
they re-run only over the four pilot blocks and the new functions, and the
2026-08-25 versions stand unchanged underneath. Check **11** is beyond §4.7's
list and is here because §4.7's whole argument rests on §1's pasted numbers: if
those no longer reproduce from the banked records, the design's premises have
moved and the gate should not open on them.

 1. **The four pilot arms differ only by their block mechanism.** Byte-level
    where the mechanism is prompt-side (B0's block is `whole` plus
    `HOLE_PROTOCOL_BLOCK`; B1 is B0 plus `hole_exemplar_block`), byte-*identical*
    where it is runner-side (B2, B3 name mechanisms `prompts.py` does not
    implement). **1b:** `closed_subtask_type` still reads the draft's own
    declared type and never a `Task`. **1c:** no held-out gold surface and no
    unseen hash in any block. **1d:** the four pilot configs and the three
    Stage-1 configs field by field, `pruners` pinned (§9), and the Stage-1
    `holes` config's `hole_block` still in its **placeholder** state, which is
    what `pilot_select --apply` fills in from Stage 0.
 2. **Blindness by signature, on every new surface** — the exemplar block, the
    B3 cut, the fill gate, the B2 note and B3 seed helpers, and check 10's own
    verdict function all take no `Task`.
 3. *(cited from 2026-08-25 §4.8 check 3 — expressibility is untouched.)*
 4. *(cited — the floor rule is untouched and load-bearing, §1.5.)*
 5. **Context**, extended to all seven configs this plan ships, so B1's ~565
    extra prompt tokens are checked against `n_ctx − max_tokens_per_draw`
    rather than assumed to fit.
 6. **No gold leak**, extended to all four blocks' skeleton prompts and to the
    exemplar block's own bytes.
 7. **A scripted stub drives one cell of each pilot arm**, extended to the
    relaxed gate: a scripted draft failing at **each** of parse / references /
    scope / typecheck, asserting the gate blocks the first three and admits the
    fourth; a rejected **bare-hole** draft, asserting §3's rule refuses it now
    that the `funnel.accepted` conjunct is gone; a relaxed-gate round, asserting
    it takes exactly one fill draw; B2's hole-demand note appearing inside its
    window and reverting after it; B3's `hole_at_error` seeding and its
    telemetry. Then E1/E2 are computed over those records **through
    `pilot_select`'s own functions**, so the selection path is exercised rather
    than described.
 8. *(cited — route-reference extraction is untouched.)*
 9. **Exemplar round-trip.** Both §2.2 exemplars: skeleton funnel-accepted, fill
    funnel-accepted, splice byte-identical to the corpus fixture, assembly
    funnel-accepted.
10. **`hole_at_error` refuses rather than guesses**, over the banked population,
    through `hole_elicitation_probe.check_ten_verdict` / `check_ten_rows` /
    `CHECK_TEN_ALLOWED` — imported, never restated, so the gate and the probe
    cannot drift apart.
11. **§1's pasted numbers reproduce** from the banked records, verbatim, through
    the probe's own `census` / `gate` / `mask` sections.

    python3 -m experiment.hole_elicitation_stub_check   (from prototype/)
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import io
import json
import re
import sys
from pathlib import Path

import corpus_registry
from transcode import def_to_surface, transcode_source

from experiment import decomposition_stub_check, heldout_gold, pilot_select, prompts, runner
from experiment.backends import Generation, StubBackend
from experiment.evaluate import run_funnel
from experiment.heldout_gold import GOLD_TERMS
from experiment.hole_elicitation_probe import (
    CHECK_TEN_ALLOWED,
    CHECK_TEN_CUT,
    CHECK_TEN_REFUSED,
    check_ten_rows,
    check_ten_verdict,
)
from experiment.hole_elicitation_probe import ARMS as BANKED_ARMS
from experiment.hole_elicitation_probe import census as probe_census
from experiment.hole_elicitation_probe import gate as probe_gate
from experiment.hole_elicitation_probe import load as load_banked
from experiment.hole_elicitation_probe import mask as probe_mask
from experiment.prompts import (
    FEW_SHOT_NAMES,
    HELD_OUT_TASKS,
    HOLE_BLOCK_CHECKER_HOLED,
    HOLE_BLOCK_EXEMPLAR,
    HOLE_BLOCK_HOLE_REQUIRED,
    HOLE_BLOCK_PROTOCOL,
    HOLE_BLOCKS,
    HOLE_EXEMPLAR_MAP_SKELETON,
    HOLE_EXEMPLAR_NOT_FILL,
    HOLE_EXEMPLAR_NOT_SKELETON,
    HOLE_PROTOCOL_BLOCK,
    PROTOCOL_HOLES,
    PROTOCOL_WHOLE,
    REGIME_HELD_OUT,
    build_fill_prompt,
    build_prompt,
    closed_subtask_type,
    declared_type_of,
    eta_skeleton,
    fill_term_skeleton,
    hole_exemplar_block,
    hole_obligations,
    splice_fill,
)
from experiment.resolver import ExperimentResolver

CONFIG_DIR = Path(__file__).resolve().parent

#: §4.2's four pilot blocks, in `hole_block` order, with the config each ships in.
PILOT_CONFIGS = {
    HOLE_BLOCK_PROTOCOL: "pilot_b0",
    HOLE_BLOCK_EXEMPLAR: "pilot_b1",
    HOLE_BLOCK_HOLE_REQUIRED: "pilot_b2",
    HOLE_BLOCK_CHECKER_HOLED: "pilot_b3",
}

#: §4.3's three Stage-1 arms.
STAGE1_CONFIGS = ("decomp2_whole", "decomp2_redraft", "decomp2_holes")

#: The two runlists deliverable 7 ships, checked for pointing at the above.
RUNLISTS = {
    "elicitation-pilot-runlist.json": [f"config/{n}.config.json" for n in PILOT_CONFIGS.values()],
    "elicitation-stage1-runlist.json": [f"config/{n}.config.json" for n in STAGE1_CONFIGS],
}

#: The only fields §4.2 licenses the four pilot configs to differ in. `hole_block`
#: *is* the manipulated variable; `hole_required_rounds` is B2's mechanism and is
#: `0` — the default, i.e. inert — everywhere else; `output_dir` and `source_path`
#: are bookkeeping.
PILOT_FIELD_EXCEPTIONS = ("hole_block", "hole_required_rounds", "output_dir", "source_path")

#: The same for Stage 1 (§4.3's table: the arms differ in their protocol, and the
#: `holes` arm additionally in the gate and the block Stage 0 will select).
STAGE1_FIELD_EXCEPTIONS = (
    "generation_protocol", "fill_gate", "hole_block", "output_dir", "source_path")

#: §4.2/§4.3's pinned settings, asserted rather than eyeballed — §9 names an
#: unpinned config as a thing that would change this plan.
PILOT_PINS = {
    "generation_protocol": PROTOCOL_HOLES,
    "fill_gate": runner.FILL_GATE_WELL_SCOPED,
    "address_book": prompts.ADDRESS_BOOK_FULL,
    "pruners": ["goal-type", "de-bruijn", "ref-hash"],
    "regimes": [REGIME_HELD_OUT],
    "conditions": [runner.CONDITION_TYPEMASK],
    "seeds": [1, 2],
    "token_budget_per_task": 4608,
    "max_tokens_per_draw": 768,
    "max_draws_per_task": 64,
    "n_ctx": 32768,
    "stop_on_semantic_success": False,
}

STAGE1_SEEDS = list(range(1, 13))

TASKS_BY_ID = {task.task_id: task for task in HELD_OUT_TASKS}

#: The task the check-7 stub cells run. Any held-out task does: every scripted
#: draft below is a definition at its *own* declared type, which is what the
#: funnel and the fill gate read (§4.7 check 1b). `headOrElse` keeps the
#: precedent's choice so the two gates' stub cells are comparable.
STUB_TASK = TASKS_BY_ID["heldout/list/headOrElse"]

HASH_RE = re.compile(r"0x[0-9a-f]{64}")


def _load(name: str) -> runner.Config:
    return runner.Config.load(CONFIG_DIR / f"{name}.config.json")


def _raw(name: str) -> dict:
    return json.loads((CONFIG_DIR / f"{name}.config.json").read_text(encoding="utf-8"))


def _blocks(resolver) -> dict[str, str]:
    """Each pilot block's *added bytes*, as `build_prompt` would insert them.

    B0 adds §3's block. B1 adds §3's block and the exemplar block. B2 and B3
    name runner-level mechanisms, so their prompt-side addition is B0's exactly
    — which is the property check 1 is for, stated as data rather than prose.
    """
    exemplar = hole_exemplar_block(resolver)
    return {
        HOLE_BLOCK_PROTOCOL: HOLE_PROTOCOL_BLOCK,
        HOLE_BLOCK_EXEMPLAR: f"{HOLE_PROTOCOL_BLOCK}\n\n{exemplar}",
        HOLE_BLOCK_HOLE_REQUIRED: HOLE_PROTOCOL_BLOCK,
        HOLE_BLOCK_CHECKER_HOLED: HOLE_PROTOCOL_BLOCK,
    }


# --------------------------------------------------------------------------
# Check 1 — the four pilot arms differ only by their block mechanism
# --------------------------------------------------------------------------


def check_1a(resolver, pilot) -> tuple[bool, list[str]]:
    lines = ["### Check 1a — the four pilot arms differ from `whole` only by their block\n"]
    lines.append(
        "Byte-level where the mechanism is prompt-side, byte-*identical* where it is\n"
        "runner-side. `whole` is the reference the 2026-08-25 §4.8 check 1 used, so the\n"
        "chain is the same one: strip the arm's added block and what is left must be the\n"
        "control's prompt, byte for byte.\n")
    added = _blocks(resolver)
    ok = True
    for task in HELD_OUT_TASKS:
        control = build_prompt(
            task, REGIME_HELD_OUT, resolver,
            address_book=prompts.ADDRESS_BOOK_FULL, generation_protocol=PROTOCOL_WHOLE)
        built = {}
        for block, config in PILOT_CONFIGS.items():
            built[block] = build_prompt(
                task, REGIME_HELD_OUT, resolver,
                address_book=pilot[config].address_book,
                generation_protocol=PROTOCOL_HOLES, hole_block=block)
        verdicts = []
        for block in PILOT_CONFIGS:
            stripped = built[block].replace(f"\n\n{added[block]}", "", 1)
            good = stripped == control
            ok = ok and good
            verdicts.append(f"{block}={'ok' if good else 'DIFFERS'}")
        # The runner-side blocks add nothing beyond B0's — byte-identical prompts.
        runner_side = (built[HOLE_BLOCK_HOLE_REQUIRED] == built[HOLE_BLOCK_PROTOCOL]
                       and built[HOLE_BLOCK_CHECKER_HOLED] == built[HOLE_BLOCK_PROTOCOL])
        # B1 is B0 plus the exemplar block and nothing else.
        exemplar_only = (built[HOLE_BLOCK_EXEMPLAR].replace(
            f"\n\n{hole_exemplar_block(resolver)}", "", 1) == built[HOLE_BLOCK_PROTOCOL])
        ok = ok and runner_side and exemplar_only
        lines.append(
            f"{task.task_id:<32} minus-block==whole: {' '.join(verdicts)}  "
            f"B2/B3==B0={'yes' if runner_side else 'NO'}  "
            f"B1==B0+exemplar={'yes' if exemplar_only else 'NO'}")
    lines.append("")
    for block, text in added.items():
        lines.append(f"  {block:<16} adds {len(text):>4} B of block "
                     f"(~{prompts.estimated_tokens(text)} tokens)")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'} — "
                 f"{len(HELD_OUT_TASKS)} tasks x {len(PILOT_CONFIGS)} blocks")
    return ok, lines


def check_1b(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 1b — the closure still reads the DRAFT's own declared type\n"]
    lines.append(
        "Pinned two ways: against the signature, the way 2026-08-25 §4.8 check 2 pins the\n"
        "other fill-path surfaces; and against the runner's single call site, which must\n"
        "pass `declared_type_of(draft)` and must never mention a task's type surface.\n")
    parameters = list(inspect.signature(closed_subtask_type).parameters)
    signature_ok = parameters == ["declared_type_surface", "obligation"]
    no_task = not any("task" in p for p in parameters)
    source = (CONFIG_DIR / "runner.py").read_text(encoding="utf-8")
    call_sites = [line.strip() for line in source.splitlines() if "closed_subtask_type(" in line
                  and not line.strip().startswith("#") and "import" not in line]
    call_ok = call_sites == ["closed = closed_subtask_type(declared_type_of(draft), obligation)"]
    leak = [line for line in source.splitlines()
            if "closed_subtask_type" in line and "expected_type_surface" in line]
    # And behaviourally: the closure's answer must not move when the *task*
    # moves under a fixed draft, which is the property the signature buys.
    draft = HOLE_EXEMPLAR_NOT_SKELETON
    obligation = hole_obligations(draft, resolver)[0]
    closed = closed_subtask_type(declared_type_of(draft), obligation)
    task_independent = closed == "(fn Bool () Bool)" != STUB_TASK.expected_type_surface
    ok = signature_ok and no_task and call_ok and not leak and task_independent
    lines.append(f"closed_subtask_type{tuple(parameters)}  "
                 f"{'as landed' if signature_ok else 'UNEXPECTED'}  "
                 f"{'no Task' if no_task else 'TAKES A TASK'}")
    lines.append(f"runner.py call sites ({len(call_sites)}): {call_sites}")
    lines.append(f"lines naming both the closure and a task's type surface: {len(leak)}")
    lines.append(f"draft {draft[:34]}… -> closed sub-task {closed} "
                 f"(the task's own type is {STUB_TASK.expected_type_surface[:34]}…)")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def check_1c(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 1c — no gold surface and no unseen hash in any block\n"]
    lines.append(
        "The exemplar block is the only block with bytes to leak. It introduces zero new\n"
        "store content (§2.2) — only a new *form* of content already in every prompt — and\n"
        "that is what this pins: every hash in it is already in the four pinned few-shot\n"
        "definitions, and no held-out gold term or type surface appears in it.\n")
    fixtures = {entry.name_path: entry.source_text().rstrip("\n")
                for entry in corpus_registry.MANIFEST}
    shown: set[str] = set()
    for name in FEW_SHOT_NAMES:
        shown |= set(HASH_RE.findall(fixtures[name]))
    ok = True
    for block, text in _blocks(resolver).items():
        hashes = set(HASH_RE.findall(text))
        unseen = sorted(hashes - shown)
        term_leaks = [t.task_id for t in HELD_OUT_TASKS
                      if t.expected_surface and t.expected_surface in text]
        type_leaks = [t.task_id for t in HELD_OUT_TASKS if t.expected_type_surface in text]
        gold_leaks = [name for name, gold in GOLD_TERMS.items() if gold in text]
        good = not unseen and not term_leaks and not type_leaks and not gold_leaks
        ok = ok and good
        lines.append(
            f"{block:<16} {len(text):>4}B  hashes={len(hashes)}  unseen={len(unseen)}  "
            f"gold-term-leaks={len(term_leaks) + len(gold_leaks)}  "
            f"gold-type-leaks={len(type_leaks)}  {'clean' if good else 'LEAK'}")
        for name in unseen:
            lines.append(f"  UNSEEN HASH — {name}")
        for name in sorted(set(term_leaks) | set(gold_leaks) | set(type_leaks)):
            lines.append(f"  LEAK — {name}")
    module_check = heldout_gold.prompt_leak_check()
    ok = ok and not module_check
    lines.append(f"\nheldout_gold.prompt_leak_check(): {module_check or 'no offenders'}")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def check_1d(pilot, stage1) -> tuple[bool, list[str]]:
    lines = ["### Check 1d — the seven shipped configs, field by field\n"]
    lines.append(
        "§9 names an unpinned config as a thing that would change this plan, so the pins\n"
        "are asserted rather than assumed. The Stage-1 `holes` config's `hole_block` is\n"
        "checked to be still in its PLACEHOLDER state (`§3-block`, the banked block and\n"
        "the field's default): Stage 0 has not run, so nothing may have selected yet, and\n"
        "`pilot_select --apply` is the only thing licensed to write that field.\n")
    ok = True

    reference = dataclasses.asdict(pilot[PILOT_CONFIGS[HOLE_BLOCK_PROTOCOL]])
    for block, name in PILOT_CONFIGS.items():
        other = dataclasses.asdict(pilot[name])
        differing = sorted(k for k in reference
                           if reference[k] != other[k] and k not in PILOT_FIELD_EXCEPTIONS)
        block_ok = other["hole_block"] == block
        pins = sorted(k for k, v in PILOT_PINS.items() if other[k] != v)
        rounds_ok = (other["hole_required_rounds"] == 3
                     if block == HOLE_BLOCK_HOLE_REQUIRED
                     else other["hole_required_rounds"] == 0)
        good = not differing and block_ok and not pins and rounds_ok
        ok = ok and good
        lines.append(
            f"{name:<16} hole_block={other['hole_block']:<14} "
            f"hole_required_rounds={other['hole_required_rounds']}  "
            f"beyond-exceptions={differing}  unpinned={pins}  "
            f"{'ok' if good else 'DRIFTED'}")

    lines.append("")
    stage_reference = dataclasses.asdict(stage1["decomp2_whole"])
    for name in STAGE1_CONFIGS:
        other = dataclasses.asdict(stage1[name])
        differing = sorted(k for k in stage_reference
                           if stage_reference[k] != other[k] and k not in STAGE1_FIELD_EXCEPTIONS)
        seeds_ok = other["seeds"] == STAGE1_SEEDS
        pruners_ok = other["pruners"] == PILOT_PINS["pruners"]
        if name == "decomp2_holes":
            gate_ok = other["fill_gate"] == runner.FILL_GATE_WELL_SCOPED
            placeholder = other["hole_block"] == HOLE_BLOCK_PROTOCOL
        else:
            gate_ok = other["fill_gate"] == runner.FILL_GATE_ACCEPTED
            placeholder = other["hole_block"] == HOLE_BLOCK_PROTOCOL
        good = not differing and seeds_ok and pruners_ok and gate_ok and placeholder
        ok = ok and good
        lines.append(
            f"{name:<16} protocol={other['generation_protocol']:<8} "
            f"fill_gate={other['fill_gate']:<12} hole_block={other['hole_block']:<10} "
            f"seeds={len(other['seeds'])}  beyond-exceptions={differing}  "
            f"{'ok' if good else 'DRIFTED'}")
    placeholder_state = stage1["decomp2_holes"].hole_block == HOLE_BLOCK_PROTOCOL
    lines.append(f"\nStage-1 `holes` hole_block placeholder intact "
                 f"({HOLE_BLOCK_PROTOCOL!r}, nothing selected yet): {placeholder_state}")

    lines.append("")
    for runlist, expected in RUNLISTS.items():
        entries = json.loads((CONFIG_DIR / runlist).read_text(encoding="utf-8"))
        keys = [entry["config_key"] for entry in entries]
        dirs_ok = all(entry["output_dir"] == entry["run_id"].join(["runs/", ""])
                      or entry["output_dir"] == f"runs/{entry['run_id']}" for entry in entries)
        good = keys == expected and dirs_ok
        ok = ok and good
        lines.append(f"{runlist:<36} {len(entries)} entries  "
                     f"{'points at the shipped configs' if good else 'MISMATCH'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 2 — blindness by signature, on every surface this plan added
# --------------------------------------------------------------------------

#: Every function this plan landed on the generation/fill path, with the
#: parameter list it landed with. 2026-08-25 §4.8 check 2 pins the pre-existing
#: ones and is cited rather than re-run; these are the new ones, and the
#: property is the same one: none of them can see a `Task`, so none of them can
#: see `composes` or `expected_surface`.
NEW_SURFACES = {
    prompts: {
        "hole_exemplar_block": ["resolver"],
        "checker_holed_cut": ["draft_source", "error_path", "resolver"],
        "hole_at_error": ["draft_source", "error_path", "resolver"],
    },
    runner: {
        "_fill_admitted": ["config", "funnel", "bare"],
        "_with_hole_required_note": ["narrowing", "round_index", "draft", "census", "config"],
        "_checker_holed_seed": ["config", "draft", "funnel", "resolver"],
    },
}


def check_2(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 2 (extended) — the new surfaces take no Task, by signature\n"]
    lines.append(
        "note: 2026-08-25 §4.8 check 2 pins `hole_obligations` / `closed_subtask_type` /\n"
        "      `fill_term_skeleton` / `splice_fill` / `build_fill_prompt` and is cited, not\n"
        "      re-run (§4.7). These are the surfaces this plan added. `build_prompt` and\n"
        "      `context_required` do take a `Task` and always have — they are the ask —\n"
        "      so the new `hole_block` argument is checked below to be a plain string in\n"
        "      the pinned vocabulary rather than anything that reads one.\n")
    ok = True
    for module, expected in NEW_SURFACES.items():
        for name, want in expected.items():
            parameters = list(inspect.signature(getattr(module, name)).parameters)
            match = parameters == want
            no_task = not any("task" in p for p in parameters)
            ok = ok and match and no_task
            lines.append(f"{module.__name__.split('.')[-1]}.{name:<24} {parameters}  "
                         f"{'as landed' if match else 'UNEXPECTED'}  "
                         f"{'no Task' if no_task else 'TAKES A TASK'}")
    verdict_parameters = list(inspect.signature(check_ten_verdict).parameters)
    verdict_ok = verdict_parameters == ["draft_source", "error_path", "resolver"]
    ok = ok and verdict_ok
    lines.append(f"probe.check_ten_verdict{tuple(verdict_parameters)}  "
                 f"{'as landed' if verdict_ok else 'UNEXPECTED'}  no Task")
    for function in (build_prompt, prompts.context_required):
        signature = inspect.signature(function)
        parameter = signature.parameters["hole_block"]
        default_ok = parameter.default == HOLE_BLOCK_PROTOCOL
        ok = ok and default_ok
        lines.append(f"{function.__name__}(hole_block=…) default={parameter.default!r}  "
                     f"{'the banked block, so pre-plan configs are byte-identical'
                        if default_ok else 'UNEXPECTED DEFAULT'}")
    vocabulary_ok = HOLE_BLOCKS == (
        HOLE_BLOCK_PROTOCOL, HOLE_BLOCK_EXEMPLAR,
        HOLE_BLOCK_HOLE_REQUIRED, HOLE_BLOCK_CHECKER_HOLED)
    ok = ok and vocabulary_ok
    lines.append(f"HOLE_BLOCKS={list(HOLE_BLOCKS)}  "
                 f"{'the four §4.2 blocks' if vocabulary_ok else 'UNEXPECTED'}")
    # And behaviourally: the exemplar block is a pure function of the store.
    stable = hole_exemplar_block(resolver) == hole_exemplar_block(resolver)
    ok = ok and stable
    lines.append(f"hole_exemplar_block(resolver) stable across calls: {stable}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 5 — context, all seven configs plus the worst-case fill prompt
# --------------------------------------------------------------------------


def check_5(resolver, configs, fixtures) -> tuple[bool, list[str]]:
    lines = ["### Check 5 (extended) — context_required <= n_ctx - max_tokens_per_draw\n"]
    lines.append(
        "note: extended to all seven configs this plan ships, because B1's exemplar block\n"
        "      is ~565 tokens of prompt the 2026-08-25 figure did not carry. The worst-case\n"
        "      *fill* prompt is built from the largest gold-derived nested draft — the same\n"
        "      fixture the 2026-08-25 check 5 used, imported from `decomposition_stub_check`\n"
        "      rather than rebuilt, so the two gates cannot drift. A fill prompt carries no\n"
        "      block, so its figure is block-independent by construction.\n")
    worst_task, worst = max(fixtures.items(), key=lambda item: len(item[1]["draft"]))
    from experiment.evaluate import narrowing_note

    narrowing = narrowing_note(run_funnel("(def Bool (lit i64 0))", resolver))
    ok = True
    for name, config in configs.items():
        threshold = config.n_ctx - config.max_tokens_per_draw
        skeleton = prompts.context_required(
            config.regimes, resolver, leave_one_out=config.leave_one_out,
            address_book=config.address_book,
            generation_protocol=config.generation_protocol,
            hole_block=config.hole_block)
        fill_prompt = build_fill_prompt(
            TASKS_BY_ID[worst_task].spec, REGIME_HELD_OUT, resolver,
            draft_source=worst["draft"], obligation=worst["obligation"],
            narrowing=narrowing, address_book=config.address_book)
        fill = prompts.estimated_tokens(fill_prompt)
        clears = max(skeleton, fill) <= threshold
        ok = ok and clears
        lines.append(
            f"{name:<16} block={config.hole_block:<14} skeleton={skeleton:>6} tok  "
            f"worst-case fill={fill:>6} tok  threshold={threshold:>6}  "
            f"{'OK' if clears else 'EXCEEDS'}")
    b0 = prompts.context_required(
        [REGIME_HELD_OUT], resolver, address_book=prompts.ADDRESS_BOOK_FULL,
        generation_protocol=PROTOCOL_HOLES, hole_block=HOLE_BLOCK_PROTOCOL)
    b1 = prompts.context_required(
        [REGIME_HELD_OUT], resolver, address_book=prompts.ADDRESS_BOOK_FULL,
        generation_protocol=PROTOCOL_HOLES, hole_block=HOLE_BLOCK_EXEMPLAR)
    lines.append(f"\nexemplar block costs {b1 - b0} prompt tokens on the longest held-out "
                 f"prompt ({b0} -> {b1}, +{(b1 - b0) / b0:.1%})")
    lines.append(f"worst-case draft: {worst_task} ({len(worst['draft'])} chars), "
                 f"carried with a narrowing note")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 6 — no gold surface in any built prompt, all four blocks
# --------------------------------------------------------------------------


def check_6(resolver, pilot, fixtures) -> tuple[bool, list[str]]:
    lines = ["### Check 6 (extended) — no gold surface appears in any pilot prompt\n"]
    lines.append(
        "note: extended over the four blocks rather than the one banked block. Fill prompts\n"
        "      are built from two draft shapes, as in 2026-08-25 §4.8 check 6: a\n"
        "      model-writable one (the eta-skeleton, gold-free by construction) and the\n"
        "      gold-derived nested draft. The harness adds nothing beyond the draft it is\n"
        "      handed, and a fill prompt carries no block, so B1 adds no fill-side surface.\n")
    offenders: list[str] = []
    skeleton_prompts = fill_prompts = 0
    for block, name in PILOT_CONFIGS.items():
        config = pilot[name]
        for task in HELD_OUT_TASKS:
            prompt = build_prompt(
                task, REGIME_HELD_OUT, resolver,
                leave_one_out=config.leave_one_out,
                address_book=config.address_book,
                generation_protocol=PROTOCOL_HOLES, hole_block=block)
            skeleton_prompts += 1
            for other, gold in GOLD_TERMS.items():
                if gold in prompt:
                    offenders.append(f"{block} skeleton {task.task_id} <- gold of {other}")
            for draft in (eta_skeleton(task.expected_type_surface),
                          fixtures[task.task_id]["draft"]):
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
                        offenders.append(f"{block} fill {task.task_id} <- gold of {other}")
    ok = not offenders
    lines.append(f"skeleton prompts checked  {skeleton_prompts:>4} "
                 f"({len(PILOT_CONFIGS)} blocks x {len(HELD_OUT_TASKS)} tasks)")
    lines.append(f"fill prompts checked      {fill_prompts:>4}")
    lines.append(f"gold surfaces searched for {len(GOLD_TERMS):>3} (every task's, in every prompt)")
    for offender in offenders:
        lines.append(f"LEAK — {offender}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 7 — a scripted stub drives one cell of each pilot arm
# --------------------------------------------------------------------------

#: An accepted draft with no hole at all. Rounds 0 and 7+ of the script, so B2's
#: hole-demand note has something to demand a hole *of*, inside its window and
#: again after it.
HOLE_FREE_DRAFT = "(def (fn Bool () Bool) (lam Bool (lit bool true)))"

#: An accepted draft with exactly one fillable hole — the §2.2 worked exemplar's
#: skeleton. Its fill splices to `corpus/bool/not`, which is a four-layer-accepted
#: assembly, so this round is the pilot's Gate E2 event in miniature.
ACCEPTED_HOLED_DRAFT = HOLE_EXEMPLAR_NOT_SKELETON

#: A **rejected** bare hole: the goal the model wrote disagrees with the position's
#: expected type, so the funnel rejects it at typecheck and §3's rule must refuse
#: it. Under the old `funnel.accepted and _is_bare_hole(draft)` conjunct this
#: draft carried `bare_hole_body=False` and a relaxed gate would have sent it to a
#: fill whose sub-task is the whole task — §2.1 consequence 1's exact defect.
BARE_HOLE_REJECTED_DRAFT = "(def (fn Bool () Bool) (lam Bool (hole I64 ())))"

#: The four-layer gate fixtures: the same holed `if` corrupted at exactly one
#: layer each. The hole is intact in all four, so what separates them is the
#: layer the funnel stops at and nothing else.
TYPECHECK_HOLED_DRAFT = (
    "(def (fn Bool () Bool) (lam Bool (if (var 0) (hole Bool ()) (lit i64 0))))")
SCOPE_HOLED_DRAFT = (
    "(def (fn Bool () Bool) (lam Bool (if (var 5) (hole Bool ()) (lit bool true))))")
REFERENCES_HOLED_DRAFT = (
    f"(def (fn Bool () (data 0x{'00' * 32} ())) "
    "(lam Bool (if (var 0) (hole Bool ()) (lit bool true))))")
PARSE_HOLED_DRAFT = "(def (fn Bool () Bool) (lam Bool (if (var 0) (hole Bool ())"

#: The script, one entry per round, in the order a cell sees them. The last entry
#: repeats for every round after it (`_ScriptedStub`), which is what lets the
#: revert half of B2's window be observed without scripting sixty rounds.
SKELETON_SCRIPT = [
    HOLE_FREE_DRAFT,           # round 0 — no hole: inside B2's window, note expected
    ACCEPTED_HOLED_DRAFT,      # round 1 — accepted + fillable hole: splice, Gate E2
    BARE_HOLE_REJECTED_DRAFT,  # round 2 — rejected bare hole: §3's rule must refuse
    TYPECHECK_HOLED_DRAFT,     # round 3 — the relaxation: admitted, one fill draw
    SCOPE_HOLED_DRAFT,         # round 4 — blocked
    REFERENCES_HOLED_DRAFT,    # round 5 — blocked
    PARSE_HOLED_DRAFT,         # round 6 — blocked
    HOLE_FREE_DRAFT,           # round 7+ — no hole, outside B2's window: no note
]

#: The fill script. `HOLE_EXEMPLAR_NOT_FILL` splices cleanly into round 1's draft
#: (assembly accepted) and equally cleanly into round 3's (assembly still rejected
#: at the *sibling* the fill never touched) — which is §1.3's prediction as a
#: fixture: the same good fill, two outcomes, decided by the draft's structure.
FILL_SCRIPT = [HOLE_EXEMPLAR_NOT_FILL]

#: Round indices the four-layer gate is read at, and what §2.1's table says.
GATE_EXPECTATIONS = {
    2: ("typecheck", False, "bare hole — §3's rule refuses it"),
    3: ("typecheck", True, "the relaxation: reached the typecheck layer"),
    4: ("scope", False, "blocked — the binder context folded into the closed type is wrong"),
    5: ("references", False, "blocked — an unresolvable hash in the declared type surface"),
    6: ("parse", False, "blocked — no IR, so no obligations and no path"),
}


class _ScriptedStub(StubBackend):
    """A stub that answers by *prompt shape*: a skeleton ask and a fill ask differ.

    Lifted in shape from `decomposition_stub_check._ScriptedStub` (the precedent),
    with one addition: `skeleton_prompts` is kept whole so check 7 can read B2's
    hole-demand note out of the *next* round's prompt rather than out of the
    record field that claims it was added.
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


def _stub_config(arm: runner.Config) -> runner.Config:
    """The pilot arm's config, pointed at the stub and one cell.

    Everything §4.2 pins about the *budget* and about the mechanism — purse,
    per-draw cap, draw cap, `fill_gate`, `hole_block`, `hole_required_rounds`,
    `fills_per_round_max` / `fill_attempts_per_hole` — is the arm's own. Two
    things are not: `backend` is the stub, and the condition is `gbnf` rather
    than `gbnf+typemask`, because the mask needs a real vocabulary. A masked
    draw and a grammared draw are one full-cap grant against one purse, so the
    gate and protocol paths checked here are condition-independent.
    """
    config = dataclasses.replace(
        arm,
        backend="stub",
        conditions=[runner.CONDITION_GBNF],
        seeds=[1],
        tasks=[STUB_TASK.task_id],
        stub_outputs=[HOLE_FREE_DRAFT],
        stub_grammar_outputs=[HOLE_FREE_DRAFT],
        source_path="<hole_elicitation_stub_check>",
    )
    config.validate()
    return config


def _drive(arm: runner.Config, resolver):
    config = _stub_config(arm)
    backend = _ScriptedStub(SKELETON_SCRIPT, FILL_SCRIPT)
    records = runner.run_task(
        STUB_TASK, config.conditions[0], REGIME_HELD_OUT, config.seeds[0],
        backend, resolver, config, runner.grammar_text())
    return config, records, backend


def check_7(resolver, pilot) -> tuple[bool, list[str], dict]:
    lines = ["### Check 7 — a scripted stub drives one cell of each pilot arm\n"]
    lines.append(
        "note: the cell runs at condition `gbnf` (the mask needs a real vocabulary); the\n"
        "      purse, the caps, the gate and the block are the arm's own. Rounds 2-6 are\n"
        "      the §2.1 four-layer gate, one layer each; round 1 is the accepted path and\n"
        "      Gate E2's event; round 3 is the relaxation, capped at one fill draw by §2.1\n"
        "      consequence 4. B2's window is read out of the NEXT round's prompt bytes,\n"
        "      not out of the record field that claims the note was added.\n")
    ok = True
    all_records: dict[str, list[dict]] = {}
    for block, name in PILOT_CONFIGS.items():
        config, records, backend = _drive(pilot[name], resolver)
        all_records[block] = records
        skeletons = {r["round"]: r for r in records if r["role"] == runner.ROLE_SKELETON}
        fills = [r for r in records if r["role"] == runner.ROLE_FILL]
        draws = [r for r in records if r["role"] in runner.DRAW_ROLES]
        fills_by_round: dict[int, list[dict]] = {}
        for row in fills:
            fills_by_round.setdefault(row["round"], []).append(row)

        # -- the budget rule, as the precedent states it ---------------------
        full_cap = all(a == config.max_tokens_per_draw for a in backend.allotments)
        charged = sum(r["tokens_completion"] for r in draws) == records[-1]["tokens_used"]
        within = records[-1]["tokens_used"] <= config.token_budget_per_task
        no_room = (config.token_budget_per_task - records[-1]["tokens_used"]
                   < config.max_tokens_per_draw) or len(draws) >= config.max_draws_per_task
        done = records[-1]["cell_done"] and not any(r["cell_done"] for r in records[:-1])
        budget_ok = all((full_cap, charged, within, no_room, done))

        # -- the §2.1 four-layer gate ---------------------------------------
        gate_rows = []
        gate_ok = True
        for round_index, (layer, admitted, why) in GATE_EXPECTATIONS.items():
            row = skeletons[round_index]
            reached = len(fills_by_round.get(round_index, []))
            # B3 may replace round 3's draft with a cut before the gate reads
            # it, and round 2's cut is refused by §3's rule; the *gate* verdict
            # is unchanged either way, which is what is asserted.
            layer_ok = row["funnel_outcome"] == layer
            admit_ok = (reached > 0) == admitted
            good = layer_ok and admit_ok
            gate_ok = gate_ok and good
            gate_rows.append(
                f"{'':<16}   round {round_index}  funnel={row['funnel_outcome']:<11} "
                f"bare={str(bool(row.get('bare_hole_body'))):<6}"
                f"fill-draws={reached}  expected={'admit' if admitted else 'block'}  "
                f"{'ok' if good else 'WRONG'}   {why}")

        # -- §2.1 consequence 4: the relaxed round takes exactly one fill draw
        relaxed_fills = len(fills_by_round.get(3, []))
        accepted_fills = len(fills_by_round.get(1, []))
        cap_ok = relaxed_fills == 1
        # -- the accepted round splices; the relaxed one rolls back (§1.3) ---
        spliced = [r for r in fills if r["splice_outcome"] == runner.SPLICE_SPLICED]
        rolled = [r for r in fills if r["splice_outcome"] == runner.SPLICE_ROLLED_BACK]
        if block == HOLE_BLOCK_CHECKER_HOLED:
            # B3 cuts round 3's ill-typed `else` branch out before the fill
            # path sees it, so the sibling error §1.3 predicts is gone and the
            # assembly is accepted. That is the whole diagnostic — the residual
            # was structure, and the checker removed the structure — so a
            # rollback is *not* expected on this arm, and demanding one would
            # be scripting the harness to fail.
            splice_ok = len(spliced) == 2 and not rolled
            splice_text = ("spliced=2 rolled-back=0 — B3 cut the sibling error out, "
                           "so the assembly the other arms roll back is accepted here")
        else:
            splice_ok = bool(spliced) and bool(rolled)
            splice_text = (f"spliced={len(spliced)} rolled-back={len(rolled)} — the same "
                           "good fill, two outcomes, decided by the draft (§1.3)")
        # §3's rule, evaluated unconditionally: round 2's draft is a bare hole
        # the funnel REJECTED, which is exactly the shape the old
        # `funnel.accepted and _is_bare_hole(draft)` conjunct recorded as False.
        bare_ok = (bool(skeletons[2].get("bare_hole_body"))
                   and skeletons[2]["funnel_outcome"] != "accepted"
                   and not fills_by_round.get(2))

        # -- B2's window ----------------------------------------------------
        note = runner.HOLE_REQUIRED_NOTE
        in_window = [i for i in (1, 2, 3) if note in backend.skeleton_prompts[i]]
        after_window = [i for i in range(4, len(backend.skeleton_prompts))
                        if note in backend.skeleton_prompts[i]]
        if block == HOLE_BLOCK_HOLE_REQUIRED:
            # Rounds 0 (no hole) and 2 (bare hole) are inside the window and
            # demand a hole; their notes land in rounds 1 and 3's prompts.
            b2_ok = in_window == [1, 3] and not after_window
            b2_text = f"note in rounds {in_window} prompts, none after (window=3 rounds)"
        else:
            b2_ok = not in_window and not after_window
            b2_text = "no hole-demand note anywhere (hole_required_rounds=0)"

        # -- B3's seeding ---------------------------------------------------
        eligible = [r for r in skeletons.values() if r.get("checker_holed_eligible")]
        cut = [r for r in skeletons.values() if r.get("checker_holed")]
        refused = [r for r in eligible if not r.get("checker_holed")]
        if block == HOLE_BLOCK_CHECKER_HOLED:
            # Rounds 2 and 3 are the typecheck rejections: 2 is refused by §3's
            # bare-hole rule, 3 is cut at the ill-typed `else` branch.
            b3_ok = (len(eligible) >= 2 and len(cut) >= 1 and len(refused) >= 1
                     and skeletons[3].get("checker_holed")
                     and not skeletons[2].get("checker_holed"))
            b3_text = (f"eligible={len(eligible)} cut={len(cut)} refused={len(refused)}; "
                       f"round 3 cut at {skeletons[3].get('checker_holed_path')!r} "
                       f"goal={skeletons[3].get('checker_holed_goal')!r}; "
                       f"round 2 refused: {skeletons[2].get('checker_holed_reason')}")
        else:
            b3_ok = not eligible and not cut
            b3_text = "no `hole_at_error` seeding (this arm is not B3)"

        good = all((budget_ok, gate_ok, cap_ok, splice_ok, bare_ok, b2_ok, b3_ok))
        ok = ok and good
        lines.append(
            f"{block:<16} records={len(records):>4} draws={len(draws):>3} "
            f"rounds={len(skeletons):>3} fills={len(fills):>2} "
            f"tokens={records[-1]['tokens_used']:>5}/{config.token_budget_per_task}")
        lines.append(
            f"{'':<16} budget: full-cap-or-no-draw={full_cap} every-draw-charged={charged} "
            f"within-purse={within} ends-when-no-room={no_room} one-cell_done={done}")
        lines.append(f"{'':<16} §2.1 four-layer gate:")
        lines.extend(gate_rows)
        lines.append(
            f"{'':<16} §2.1 consequence 4: accepted round fill-draws={accepted_fills} "
            f"(caps {config.fills_per_round_max}/{config.fill_attempts_per_hole})  "
            f"relaxed round fill-draws={relaxed_fills} (capped at 1)  "
            f"{'ok' if cap_ok else 'WRONG'}")
        lines.append(f"{'':<16} splice outcomes: {splice_text}  "
                     f"{'ok' if splice_ok else 'WRONG'}")
        lines.append(f"{'':<16} §3's rule, unconditional: round 2 funnel="
                     f"{skeletons[2]['funnel_outcome']} bare_hole_body="
                     f"{bool(skeletons[2].get('bare_hole_body'))}, fill-draws="
                     f"{len(fills_by_round.get(2, []))}  "
                     f"{'ok' if bare_ok else 'WRONG'}")
        lines.append(f"{'':<16} B2: {b2_text}  {'ok' if b2_ok else 'WRONG'}")
        lines.append(f"{'':<16} B3: {b3_text}  {'ok' if b3_ok else 'WRONG'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines, all_records


def check_7e(all_records) -> tuple[bool, list[str]]:
    """E1/E2 computed over check 7's records by `pilot_select`'s own functions."""
    lines = ["### Check 7e — the E1/E2 computation path, through `pilot_select` itself\n"]
    lines.append(
        "The pilot's selection is executed by a committed script, not judged (§4.8), so the\n"
        "script's own functions are what compute here — `block_stats`, `assembly_liveness`,\n"
        "`selection_verdict` — over check 7's stub records. This is a check of the\n"
        "MECHANICS, not a result: one scripted cell per block, identical by construction,\n"
        "so the verdict below is arithmetic on a fixture and says nothing about any model.\n")
    ok = True
    stats = {block: pilot_select.block_stats(records)
             for block, records in all_records.items()}
    header = (f"{'block':<28}{'draws':>7}{'qualify':>9}{'draw_rate':>11}"
              f"{'wilson_lo':>11}{'cells':>8}{'cell_rate':>11}{'E1':>6}")
    lines.append(header)
    for block in pilot_select.BLOCK_ORDER:
        row = stats[block]
        lines.append(
            f"{pilot_select.BLOCK_LABELS[block]:<28}{row['draws']:>7}{row['qualifying']:>9}"
            f"{row['draw_rate']:>10.2%} {row['wilson_lower']:>10.2%} "
            f"{row['cells_qualifying']:>3}/{row['cells_total']:<4}"
            f"{row['cell_rate']:>10.2%}{'PASS' if row['e1_pass'] else 'fail':>6}")
        # Every block's scripted cell contains rounds 1 and 3 — an accepted
        # holed draft and a well-scoped rejected one — so the fill-reaching
        # metric must count at least those two and the cell must qualify.
        counted = row["qualifying"] >= 2 and row["cells_qualifying"] == 1
        ok = ok and counted
    e2 = pilot_select.assembly_liveness(all_records)
    lines.append(f"\nGate E2 (assembly liveness, pooled): "
                 f"{'CLEAR' if e2['cleared'] else 'NOT CLEAR'} — "
                 f"{len(e2['hits'])} fill draw(s) spliced into a four-layer-accepted "
                 f"assembly")
    ok = ok and e2["cleared"] and len(e2["hits"]) >= len(all_records)
    verdict = pilot_select.selection_verdict(stats, e2)
    lines.append(f"selection_verdict kind={verdict['kind']!r} "
                 f"block={verdict.get('block', '-')!r}")
    lines.append(f"  {verdict['message']}")
    # The fixture's own verdict is `no_launch_e1` and must be: one scripted cell
    # of 62 rounds, mostly hole-free by script, is a 3.2 % fill-reaching draw
    # rate, and §4.2's bar is a 10 % Wilson lower bound. Asserting a `select`
    # here would mean scripting a cell to clear a pre-registered gate, which is
    # the opposite of what a gate is for. What is asserted is that the verdict
    # is well-formed and drawn from the pre-committed vocabulary.
    fixture_ok = (verdict["kind"] in ("select", "escalate", "no_launch_e1", "no_launch_e2")
                  and bool(verdict["message"]))
    ok = ok and fixture_ok
    lines.append(f"  (a fixture, not a result: 3.2 % against a 10 % bar, so `no_launch_e1`\n"
                 f"   is the correct answer and any other would mean the bar had moved)  "
                 f"{'ok' if fixture_ok else 'WRONG'}")

    lines.append("\n§4.2's selection rule itself, over constructed stats — every branch:\n")
    scenarios = [
        ("no block clears E1", {b: 0.05 for b in pilot_select.BLOCK_ORDER}, True,
         "no_launch_e1", None),
        ("only B3 clears E1 (§6 row 3)",
         {HOLE_BLOCK_PROTOCOL: 0.05, HOLE_BLOCK_EXEMPLAR: 0.05,
          HOLE_BLOCK_HOLE_REQUIRED: 0.05, HOLE_BLOCK_CHECKER_HOLED: 0.40}, True,
         "escalate", None),
        ("B1 and B2 clear, E2 does not (§6 row 2)",
         {HOLE_BLOCK_PROTOCOL: 0.05, HOLE_BLOCK_EXEMPLAR: 0.40,
          HOLE_BLOCK_HOLE_REQUIRED: 0.40, HOLE_BLOCK_CHECKER_HOLED: 0.05}, False,
         "no_launch_e2", None),
        ("B1 and B2 tie -> the fixed order B1 < B2",
         {HOLE_BLOCK_PROTOCOL: 0.05, HOLE_BLOCK_EXEMPLAR: 0.40,
          HOLE_BLOCK_HOLE_REQUIRED: 0.40, HOLE_BLOCK_CHECKER_HOLED: 0.05}, True,
         "select", HOLE_BLOCK_EXEMPLAR),
        ("B2 strictly higher cell rate -> B2",
         {HOLE_BLOCK_PROTOCOL: 0.05, HOLE_BLOCK_EXEMPLAR: 0.40,
          HOLE_BLOCK_HOLE_REQUIRED: 0.60, HOLE_BLOCK_CHECKER_HOLED: 0.05}, True,
         "select", HOLE_BLOCK_HOLE_REQUIRED),
    ]
    for label, rates, e2_clear, want_kind, want_block in scenarios:
        # `block_stats`' own arithmetic, over synthetic counts at n = 184 draws
        # per block (§4.2's pilot size) — the rate is constructed, the Wilson
        # bound and the E1 verdict are `pilot_select`'s.
        constructed = {}
        for block, rate in rates.items():
            hits, draws_n = round(rate * 184), 184
            constructed[block] = {
                "draws": draws_n, "qualifying": hits, "draw_rate": hits / draws_n,
                "wilson_lower": pilot_select.wilson_lower(hits, draws_n),
                "cells_total": 16, "cells_qualifying": round(rate * 16),
                "cell_rate": round(rate * 16) / 16,
                "e1_pass": pilot_select.wilson_lower(hits, draws_n) >= pilot_select.E1_BAR,
            }
        got = pilot_select.selection_verdict(
            constructed, {"cleared": e2_clear, "hits": [1] if e2_clear else []})
        good = got["kind"] == want_kind and (
            want_block is None or got.get("block") == want_block)
        ok = ok and good
        lines.append(f"  {label:<44} -> kind={got['kind']:<14} "
                     f"block={got.get('block', '-'):<14} {'ok' if good else 'WRONG'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 9 — exemplar round-trip
# --------------------------------------------------------------------------


def check_9(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 9 — both §2.2 exemplars round-trip to their corpus fixture\n"]
    lines.append(
        "Driven through the landed constants in `prompts.py` — the single source of the\n"
        "block's bytes — and the landed protocol functions, never a second copy. The\n"
        "`maybe/map` fill is not in the block (§2.2 shows that exemplar as draft +\n"
        "sub-task only); it is reconstructed here from `fill_term_skeleton` so the\n"
        "round-trip can be checked end to end all the same.\n")
    fixtures = {entry.name_path: entry.source_text().rstrip("\n")
                for entry in corpus_registry.MANIFEST}
    map_obligation = hole_obligations(HOLE_EXEMPLAR_MAP_SKELETON, resolver)[0]
    map_subterm = f"(con 0x{corpus_registry.HASHES['Maybe'].hex()} 0 ())"
    map_fill = (
        f"(def {closed_subtask_type(declared_type_of(HOLE_EXEMPLAR_MAP_SKELETON), map_obligation)}"
        f" {fill_term_skeleton(map_obligation).replace(map_obligation.surface, map_subterm)})")
    cases = [
        ("corpus/bool/not", HOLE_EXEMPLAR_NOT_SKELETON, HOLE_EXEMPLAR_NOT_FILL),
        ("corpus/maybe/map", HOLE_EXEMPLAR_MAP_SKELETON, map_fill),
    ]
    ok = True
    for name, draft, fill in cases:
        obligations = hole_obligations(draft, resolver)
        draft_funnel = run_funnel(draft, resolver)
        closed = closed_subtask_type(declared_type_of(draft), obligations[0])
        fill_funnel = run_funnel(fill, resolver)
        assembled = splice_fill(draft, obligations[0], fill)
        assembled_funnel = run_funnel(assembled, resolver)
        identical = assembled == fixtures[name]
        good = (draft_funnel.accepted and len(obligations) == 1 and obligations[0].fillable
                and fill_funnel.accepted and identical and assembled_funnel.accepted)
        ok = ok and good
        lines.append(f"{name}")
        lines.append(f"  draft      chars={len(draft):>4}  funnel={draft_funnel.outcome}"
                     f"  holes={len(obligations)} "
                     f"fillable={sum(o.fillable for o in obligations)}")
        lines.append(f"  sub-task   chars={len(closed):>4}  (derived from the draft's own "
                     f"declared type)")
        lines.append(f"  fill       chars={len(fill):>4}  funnel={fill_funnel.outcome}")
        lines.append(f"  assembled  funnel={assembled_funnel.outcome}"
                     f"  identical-to-fixture={identical}")
    block = hole_exemplar_block(resolver)
    lines.append(f"\nblock size: {len(block)} characters of definition surface, "
                 f"~{prompts.estimated_tokens(block)} tokens")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 10 — `hole_at_error` refuses rather than guesses, over the banked run
# --------------------------------------------------------------------------


def check_10(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 10 — `hole_at_error` refuses rather than guesses\n"]
    lines.append(
        "Over every banked typecheck-rejected skeleton in all three arms, through the\n"
        "probe's own `check_ten_rows` / `check_ten_verdict` / `CHECK_TEN_ALLOWED` —\n"
        "imported, not restated, so this gate and the probe cannot answer differently.\n"
        "A verdict outside the allowed two is a violation and is printed with the draft.\n")
    ok = True
    totals = {CHECK_TEN_CUT: 0, CHECK_TEN_REFUSED: 0}
    violations: list[str] = []
    for arm in BANKED_ARMS:
        rows = check_ten_rows(load_banked(arm))
        counts = {CHECK_TEN_CUT: 0, CHECK_TEN_REFUSED: 0}
        arm_violations = 0
        for row in rows:
            verdict = check_ten_verdict(
                row["source"], row.get("error_path") or "", resolver)
            if verdict not in CHECK_TEN_ALLOWED:
                arm_violations += 1
                if len(violations) < 5:
                    violations.append(f"{arm} {row['task']} seed={row['seed']} "
                                      f"draw={row['draw']}: {verdict}")
                continue
            counts[verdict] += 1
            totals[verdict] += 1
        ok = ok and arm_violations == 0
        lines.append(f"{arm:<9} typecheck-rejected {len(rows):>4}   "
                     f"cut {counts[CHECK_TEN_CUT]:>4}   "
                     f"refused {counts[CHECK_TEN_REFUSED]:>4}   "
                     f"violations {arm_violations}")
    lines.append(f"\n{'total':<9} cut {totals[CHECK_TEN_CUT]:>4}   "
                 f"refused {totals[CHECK_TEN_REFUSED]:>4}   "
                 f"violations {len(violations)}")
    for violation in violations:
        lines.append(f"  VIOLATION — {violation}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 11 — §1's pasted numbers reproduce from the banked records
# --------------------------------------------------------------------------

#: Every line §1 of the plan pastes as evidence, matched as a substring against
#: the probe section that produced it. Not a re-derivation: the probe is the
#: plan's own evidence script (§8 deliverable 1), so this asserts that running
#: it today still prints what the plan says it printed. If any of these moved,
#: §1's premises moved and the gate must not open on them.
BASELINE_EXPECTATIONS = {
    "census": [
        "whole       1/762  = 0.131%",
        "redraft     2/772  = 0.259%",
        "holes      12/747  = 1.606%",
        "one-sided Fisher, `holes` > `redraft`         p = 0.00528",
        "one-sided Fisher, `holes` > pooled controls   p = 0.00023",
        "corpus fixtures containing a `(hole ...)` node: 0 of 26",
        "of the four pinned few-shot names",
    ],
    "gate": [
        "  parse         34",
        "  references    74",
        "  scope          1",
        "  typecheck    597",
        "  accepted      41",
        "reached the typecheck layer (parse+references+scope passed): 638/747 = 85.4%",
        "accepted (as run)            rounds reaching a fill:  0   cells:  0/64   (+0 ",
        "well-scoped (the §4.2 gate)  rounds reaching a fill:  8   cells:  8/64   (+1 ",
        "parses, literally            rounds reaching a fill:  8   cells:  8/64   (+2 ",
    ],
    "mask": [
        "heldout/list/concatLength        10  var ref lit app let match perform handle hole if",
        "heldout/nat/selectNonNegative    10  var ref lit app let match perform handle hole if",
    ],
}


def check_11() -> tuple[bool, list[str]]:
    lines = ["### Check 11 (new) — §1's pasted numbers still reproduce\n"]
    lines.append(
        "§4.7's argument is that checks 2-6 and 8 can be *cited* because the machinery they\n"
        "pin is untouched. That citation is only as good as §1's numbers, which are the\n"
        "premises the whole design rests on. Each line below is a substring the plan pastes\n"
        "in §1, matched against today's output of the probe section that produced it.\n")
    sections = {"census": probe_census, "gate": probe_gate, "mask": probe_mask}
    ok = True
    for name, function in sections.items():
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            function()
        text = buffer.getvalue()
        missing = [line for line in BASELINE_EXPECTATIONS[name] if line not in text]
        ok = ok and not missing
        lines.append(f"--section {name:<8} {len(BASELINE_EXPECTATIONS[name]):>2} pinned lines  "
                     f"{'all reproduce' if not missing else f'{len(missing)} MOVED'}")
        for line in missing:
            lines.append(f"  MOVED — {line!r}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def main() -> int:
    resolver = ExperimentResolver()
    pilot = {name: _load(name) for name in PILOT_CONFIGS.values()}
    stage1 = {name: _load(name) for name in STAGE1_CONFIGS}
    configs = {**pilot, **stage1}
    # The 2026-08-25 gate's own gold-derived nested drafts, imported rather than
    # rebuilt: checks 5 and 6 need a realistic large draft with a fillable hole,
    # and a second copy of that fixture builder is a second thing to drift.
    fixtures = decomposition_stub_check._nested_cases(resolver)

    ok_7, lines_7, stub_records = check_7(resolver, pilot)
    checks = [
        lambda: check_1a(resolver, pilot),
        lambda: check_1b(resolver),
        lambda: check_1c(resolver),
        lambda: check_1d(pilot, stage1),
        lambda: check_2(resolver),
        lambda: check_5(resolver, configs, fixtures),
        lambda: check_6(resolver, pilot, fixtures),
        lambda: (ok_7, lines_7),
        lambda: check_7e(stub_records),
        lambda: check_9(resolver),
        lambda: check_10(resolver),
        check_11,
    ]
    all_ok = True
    for index, function in enumerate(checks):
        if index:
            print()
        ok, lines = function()
        for line in lines:
            print(line)
        all_ok = all_ok and ok

    print()
    print("### Deliverable 6 verdict: "
          + ("ALL CHECKS PASS — the GPU gate is open"
             if all_ok else "AT LEAST ONE CHECK FAILED — do not launch"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
