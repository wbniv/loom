"""§7.2's Gate 2 — the CPU stub gate on GPU spend for the skeleton-lever arm.
CPU only, no GPU, no network.

[`docs/plans/2026-08-28-skeleton-lever.md`](../../docs/plans/2026-08-28-skeleton-lever.md)
§7.2. **This is the gate on GPU spend**: every check below must print PASS,
and the script exits non-zero the moment any one of them fails, so a failing
gate cannot be missed by skimming the tail of the output. Ten checks, §7.2's
own numbering, driving the landed machinery rather than a second copy of it —
`prompts.build_prompt`, `runner.run_task`'s own protocol loop (`_run_whole_
protocol`, shared verbatim by `whole` and `redraft`), `evaluate.run_funnel` /
`narrowing_note`, and `skeleton_lever_compare.main` itself for check 8.

    python3 -m experiment.skeleton_lever_stub_check   (from prototype/)
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from experiment import runner
from experiment import skeleton_lever_compare as slc
from experiment.backends import StubBackend
from experiment.evaluate import ACCEPTED, narrowing_note, run_funnel
from experiment.heldout_gold import GOLD_TERMS, prompt_leak_check
from experiment.prompts import HELD_OUT_TASKS, REGIME_HELD_OUT, build_prompt, estimated_tokens
from experiment.resolver import ExperimentResolver

TASK_IDS = [t.task_id for t in HELD_OUT_TASKS]

EXPERIMENT = Path(__file__).resolve().parent
REPO_ROOT = EXPERIMENT.parent.parent

ARM_CONFIGS = {
    "skel-whole14": "skel_whole14.config.json",
    "skel-redraft14": "skel_redraft14.config.json",
}

#: The task the scripted-stub checks (4, 5, 7) drive.
STUB_TASK = next(t for t in HELD_OUT_TASKS if t.task_id == "heldout/list/sum")
GOOD_DRAFT = GOLD_TERMS[STUB_TASK.task_id]
#: A definition that fails the funnel at `typecheck` -- the rejected-draft path.
REJECTED_DRAFT = "(def Bool (lit i64 0))"

#: One scripted draft per rejecting layer, `evaluate.LAYERS` order.
_UNKNOWN_HASH = "0x" + "ab" * 32
LAYER_DRAFTS = {
    "parse": "(def Bool (lam Bool (if (var 0)",
    "scope": "(def (fn Bool () Bool) (lam Bool (var 3)))",
    "references": f"(def (data {_UNKNOWN_HASH} ()) (hole (data {_UNKNOWN_HASH} ()) ()))",
    "typecheck": REJECTED_DRAFT,
}


class _TrackingStub(StubBackend):
    """`StubBackend` plus the one thing check 5 needs and the base class
    does not record: what `max_tokens` the runner actually granted each
    draw, so "full-cap-or-no-draw" can be checked against what was
    *requested*, not just what the scripted text happened to cost."""

    def __init__(self, outputs):
        super().__init__(outputs)
        self.allotments: list[int] = []

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        self.allotments.append(max_tokens)
        return super().generate(
            prompt, grammar=grammar, max_tokens=max_tokens, seed=seed, temperature=temperature)


def _load_arms() -> dict[str, runner.Config]:
    return {name: runner.Config.load(EXPERIMENT / path) for name, path in ARM_CONFIGS.items()}


def _stub_config(arm: runner.Config, *, max_draws=2) -> runner.Config:
    config = dataclasses.replace(
        arm, backend="stub", conditions=[runner.CONDITION_GBNF], seeds=[1],
        tasks=[STUB_TASK.task_id], max_draws_per_task=max_draws,
        stop_on_semantic_success=True,
        source_path="<skeleton_lever_stub_check>")
    config.validate()
    return config


def _drive(arm: runner.Config, resolver, *, max_draws=2) -> tuple[list[dict], _TrackingStub]:
    config = _stub_config(arm, max_draws=max_draws)
    backend = _TrackingStub([REJECTED_DRAFT, GOOD_DRAFT])
    records = runner.run_task(
        STUB_TASK, config.conditions[0], REGIME_HELD_OUT, config.seeds[0],
        backend, resolver, config, runner.grammar_text())
    return records, backend


# --------------------------------------------------------------------------
# Check 1 -- both configs load, validate, and differ in exactly two keys
# --------------------------------------------------------------------------

def check_1(arms) -> tuple[bool, list[str]]:
    lines = ["### Check 1 -- both configs load, validate, differ in exactly two keys\n"]
    ok = True
    for name in ARM_CONFIGS:
        arms[name].validate()
        lines.append(f"  {name:<16} loads and validates: True")
    whole_raw = json.loads((EXPERIMENT / "skel_whole14.config.json").read_text(encoding="utf-8"))
    redraft_raw = json.loads((EXPERIMENT / "skel_redraft14.config.json").read_text(encoding="utf-8"))
    differing = sorted(k for k in whole_raw if whole_raw[k] != redraft_raw.get(k))
    two_keys = differing == ["generation_protocol", "output_dir"]
    ok = ok and two_keys
    lines.append(f"  differing keys: {differing}  {'exactly the two licensed' if two_keys else 'WRONG'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 2 -- draw 0's prompt bytes are equal across the arms, all 8 tasks
# --------------------------------------------------------------------------

def check_2(arms, resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 2 -- draw 0's prompt bytes are equal across the arms, all 8 tasks\n"]
    ok = True
    for task in HELD_OUT_TASKS:
        built = {
            name: build_prompt(
                task, REGIME_HELD_OUT, resolver,
                leave_one_out=arms[name].leave_one_out,
                address_book=arms[name].address_book,
                generation_protocol=arms[name].generation_protocol)
            for name in ARM_CONFIGS
        }
        identical = built["skel-whole14"] == built["skel-redraft14"]
        ok = ok and identical
        lines.append(f"  {task.task_id:<32} whole==redraft={'yes' if identical else 'NO'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 3 -- Arm B's note is `narrowing_note` unmodified, canonical renderer,
# for a scripted rejection at every funnel layer (§3.2's Watch-trigger claim)
# --------------------------------------------------------------------------

def check_3(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 3 -- Arm B's note == narrowing_note(unmodified renderer), every layer\n"]
    ok = True
    for layer, draft in LAYER_DRAFTS.items():
        funnel = run_funnel(draft, resolver)
        layer_ok = funnel.outcome == layer
        note = narrowing_note(funnel)
        shape_ok = (
            note.startswith("The previous answer was rejected by the ")
            and note.endswith("Write a different definition that avoids this.")
            and funnel.error_message in note
            and f"rejected by the {layer} layer" in note)
        good = layer_ok and shape_ok
        ok = ok and good
        lines.append(f"  {layer:<12} funnel.outcome={funnel.outcome:<12} "
                     f"note-shape-ok={shape_ok}  {'ok' if good else 'WRONG'}")
    accepted_funnel = run_funnel(GOLD_TERMS[STUB_TASK.task_id], resolver)
    no_note_on_accept = accepted_funnel.accepted and narrowing_note(accepted_funnel) == ""
    ok = ok and no_note_on_accept
    lines.append(f"  accepted draft carries no note: {no_note_on_accept}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 4 -- Arm A never constructs a note (narrowed False on every record)
# --------------------------------------------------------------------------

def check_4(arms, resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 4 -- Arm A (whole) never narrows: `narrowed` False on every record\n"]
    matrix = [
        (runner.PROTOCOL_WHOLE, runner.CONDITION_TYPEMASK, False),
        (runner.PROTOCOL_WHOLE, runner.CONDITION_GBNF, False),
        (runner.PROTOCOL_REDRAFT, runner.CONDITION_TYPEMASK, True),
    ]
    matrix_ok = True
    for protocol, condition, expected in matrix:
        actual = runner._narrows(runner.Config(generation_protocol=protocol), condition)
        good = actual == expected
        matrix_ok = matrix_ok and good
        lines.append(f"  _narrows(protocol={protocol!r:<9} condition={condition!r:<14}) = "
                     f"{actual!s:<5} (expected {expected!s:<5})  {'ok' if good else 'WRONG'}")
    records, _ = _drive(arms["skel-whole14"], resolver, max_draws=3)
    empirically_ok = len(records) >= 2 and all(r["narrowed"] is False for r in records)
    lines.append(f"  scripted cell (rejected then accepted, {len(records)} draws): "
                 f"narrowed={[r['narrowed'] for r in records]}  "
                 f"{'ok' if empirically_ok else 'WRONG'}")
    ok = matrix_ok and empirically_ok
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 5 -- the budget rule
# --------------------------------------------------------------------------

def check_5(arms, resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 5 -- the budget rule: full-cap-or-no-draw, every draw charged,\n"
             "###           within purse, ends when no room, cell_done on the last record\n"]
    ok = True
    for name in ARM_CONFIGS:
        config = _stub_config(arms[name])
        records, backend = _drive(arms[name], resolver)
        draws = [r for r in records if r["role"] in runner.DRAW_ROLES]
        full_cap = all(a == config.max_tokens_per_draw for a in backend.allotments)
        charged = sum(r["tokens_completion"] for r in draws) == records[-1]["tokens_used"]
        within = records[-1]["tokens_used"] <= config.token_budget_per_task
        no_room = (config.token_budget_per_task - records[-1]["tokens_used"]
                   < config.max_tokens_per_draw) or len(draws) >= config.max_draws_per_task
        done = records[-1]["cell_done"] and not any(r["cell_done"] for r in records[:-1])
        indices = [r["draw"] for r in records] == list(range(len(records)))
        good = all((full_cap, charged, within, no_room, done, indices))
        ok = ok and good
        lines.append(
            f"  {name:<16} draws={len(draws)} tokens={records[-1]['tokens_used']}/"
            f"{config.token_budget_per_task}")
        lines.append(
            f"  {'':<16} full-cap-or-no-draw={full_cap} every-draw-charged={charged} "
            f"within-purse={within} ends-when-no-room={no_room} "
            f"cell_done-on-last-only={done} draw-indices-sequential={indices}  "
            f"{'ok' if good else 'WRONG'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 6 -- no gold term or gold type surface in any prompt
# --------------------------------------------------------------------------

def check_6(arms, resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 6 -- no gold term in any built prompt; no task's own type surface\n"
             "###           spelled out in its own spec text\n"]
    lines.append(
        "note: gold TERMS are checked cross-task, against the full built prompt (every\n"
        "      task's gold against every prompt -- decomposition_stub_check's own rule,\n"
        "      safe because a full composed term is not the kind of string that\n"
        "      coincidentally recurs). A gold TYPE SURFACE is checked only against its own\n"
        "      task's *spec text*, not the full prompt: type surfaces are built from shared\n"
        "      primitives (I64, List, ...), so e.g. sum's 1-arg `List I64 -> I64` surface is\n"
        "      a literal substring of foldRight's own (unrelated, legitimately-listed)\n"
        "      curried address-book signature -- confirmed by hand, not a leak. §1.3's own\n"
        "      claim is the actual thing to regression-guard: \"the expected type surface\n"
        "      appears verbatim in 0 of 8 task specs\" -- spec text, not the whole prompt.\n")
    offenders: list[str] = []
    prompts_checked = 0
    for name in ARM_CONFIGS:
        config = arms[name]
        for task in HELD_OUT_TASKS:
            prompt = build_prompt(
                task, REGIME_HELD_OUT, resolver,
                leave_one_out=config.leave_one_out,
                address_book=config.address_book,
                generation_protocol=config.generation_protocol)
            prompts_checked += 1
            for other, gold in GOLD_TERMS.items():
                if gold in prompt:
                    offenders.append(f"{name} {task.task_id} <- gold term of {other}")
            if task.expected_type_surface in task.spec:
                offenders.append(f"{name} {task.task_id} <- its OWN type surface, in spec text")
    module_check = prompt_leak_check()
    ok = not offenders and not module_check
    lines.append(f"  prompts checked  {prompts_checked:>4} (2 arms x 8 tasks)")
    lines.append(f"  gold terms searched for {len(GOLD_TERMS):>3} (cross-task, full prompt); "
                 f"8 own-type-surface self-checks (spec text only)")
    lines.append(f"  heldout_gold.prompt_leak_check(): {module_check or 'no offenders'}")
    for offender in offenders:
        lines.append(f"  LEAK -- {offender}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 7 -- a scripted stub drives one cell of each arm end to end (`gbnf`)
# --------------------------------------------------------------------------

def check_7(arms, resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 7 -- a scripted stub drives one cell of each arm end to end (`gbnf`)\n"]
    ok = True
    for name in ARM_CONFIGS:
        records, backend = _drive(arms[name], resolver, max_draws=3)
        outcomes = [r["funnel_outcome"] for r in records]
        candidates = [r for r in records if r["candidate"]]
        bookkeeping = (len(candidates) == len(records)
                       and all(r["role"] == runner.ROLE_WHOLE for r in records))
        narrows_seen = any(r["narrowed"] for r in records)
        expect_narrows = arms[name].generation_protocol == runner.PROTOCOL_REDRAFT
        rejected_then_accepted = outcomes[0] != ACCEPTED and any(
            o == ACCEPTED for o in outcomes)
        good = bookkeeping and (narrows_seen == expect_narrows) and rejected_then_accepted
        ok = ok and good
        lines.append(
            f"  {name:<16} draws={len(records)} outcomes={outcomes} "
            f"narrowed={[r['narrowed'] for r in records]} "
            f"one-candidate-per-draw={bookkeeping} narrows={narrows_seen} "
            f"(expected {expect_narrows})  {'ok' if good else 'WRONG'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 8 -- skeleton_lever_compare returns each of 0, 2, 3, 4, 5, 6 on
# synthetic records built to trigger that row
#
# The fixtures below are this gate's own -- restated rather than imported
# from `test_skeleton_lever_arm.py` (a gate script does not depend on a test
# module, `legibility_stub_check.py`'s own rule). Every record's `source` is
# a real task's own `GOLD_TERMS` surface (or a mismatched one), so
# `skeleton_lever_compare.type_exact` evaluates it for real.
# --------------------------------------------------------------------------

def _synthetic_cells(n: int, hits: int, *, seed_start: int = 1, draws_per_cell: int = 8,
                     extra_non_type_exact: int = 2, role: str = "whole") -> list[dict]:
    """`n` cells cycling through the 8 held-out tasks, seeds advancing every
    8 cells (`n=32` reproduces Amendment A1's 8 tasks x seeds 1-4). The
    first `hits` cells have every one of their `draws_per_cell` type-exact
    draws funnel-accepted; the rest have none. `extra_non_type_exact` draws
    per cell (a different task's gold surface, always rejected) inflate E2's
    denominator without ever entering E1."""
    rows = []
    for i in range(n):
        task = TASK_IDS[i % len(TASK_IDS)]
        other = TASK_IDS[(i + 1) % len(TASK_IDS)]
        cell_seed = seed_start + i // len(TASK_IDS)
        accepted = i < hits
        for d in range(draws_per_cell):
            rows.append({
                "task": task, "seed": cell_seed, "draw": d, "role": role,
                "source": GOLD_TERMS[task],
                "funnel_outcome": ACCEPTED if accepted else "typecheck",
            })
        for d in range(draws_per_cell, draws_per_cell + extra_non_type_exact):
            rows.append({
                "task": task, "seed": cell_seed, "draw": d, "role": role,
                "source": GOLD_TERMS[other],
                "funnel_outcome": "typecheck",
            })
    return rows


def _synthetic_anchor(whole_rows: list[dict]) -> list[dict]:
    """A `scale14-b0` stand-in that reproduces `whole_rows`' own seeds-1-2
    subset exactly (relabeled `role: "candidate"`), so C1' trivially passes."""
    return [dict(row, role="candidate")
            for row in whole_rows if row["seed"] in slc.C1_OVERLAP_SEEDS]


def check_8() -> tuple[bool, list[str]]:
    lines = ["### Check 8 -- skeleton_lever_compare.py: exit codes 0, 2, 3, 4, 5, 6\n"]
    cases = {
        0: lambda: (_synthetic_cells(32, 28), _synthetic_cells(32, 4), None),
        2: lambda: (_synthetic_cells(32, 16), _synthetic_cells(32, 15), None),
        3: lambda: (_synthetic_cells(32, 16, extra_non_type_exact=2),
                    _synthetic_cells(32, 16, extra_non_type_exact=40), None),
        4: lambda: (_synthetic_cells(32, 16, draws_per_cell=2),
                    _synthetic_cells(32, 15, draws_per_cell=2), None),
        5: lambda: (_synthetic_cells(32, 4), _synthetic_cells(32, 28), None),
        6: lambda: (_synthetic_cells(32, 16), _synthetic_cells(32, 16),
                    _synthetic_cells(200, 10, draws_per_cell=1, extra_non_type_exact=0,
                                     role="candidate")),
    }
    ok = True
    for expected_rc, build in cases.items():
        redraft, whole, anchor = build()
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            for run_id, rows in {
                "skel-redraft14": redraft, "skel-whole14": whole,
                "scale14-b0": anchor if anchor is not None else _synthetic_anchor(whole),
            }.items():
                (runs / run_id).mkdir(parents=True)
                with (runs / run_id / "records.jsonl").open("w", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = slc.main(runs_dir=runs)
        good = rc == expected_rc and "§6 row" in out.getvalue()
        ok = ok and good
        lines.append(f"  expected exit {expected_rc}: got {rc}  {'ok' if good else 'WRONG'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 9 -- prompt + worst-case completion fits the context window at 14B
# --------------------------------------------------------------------------

def check_9(arms, resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 9 -- prompt + worst-case completion fits the context window\n"]
    # A realistic worst-case narrowing note, from a genuinely rejected
    # definition run through the real funnel -- not invented at a convenient
    # length (mirrors `decomposition_stub_check.prompts_worst_narrowing`).
    worst_note = narrowing_note(run_funnel(REJECTED_DRAFT, resolver))
    ok = True
    for name in ARM_CONFIGS:
        config = arms[name]
        threshold = config.n_ctx - config.max_tokens_per_draw
        narrowing = worst_note if config.generation_protocol == runner.PROTOCOL_REDRAFT else ""
        longest = max(
            estimated_tokens(build_prompt(
                task, REGIME_HELD_OUT, resolver, leave_one_out=config.leave_one_out,
                narrowing=narrowing, address_book=config.address_book,
                generation_protocol=config.generation_protocol))
            for task in HELD_OUT_TASKS)
        clears = longest <= threshold
        ok = ok and clears
        lines.append(
            f"  {name:<16} worst-case prompt={longest:>6} tok "
            f"(narrowing note carried: {bool(narrowing)})  threshold={threshold:>6}  "
            f"{'OK' if clears else 'EXCEEDS'}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 10 -- skeleton_starve_probe and skeleton_lever_power reproduce the
# plan's own pasted numbers (a regression check on §1 and §4)
# --------------------------------------------------------------------------

#: A handful of the plan's own pasted lines from §1 and §4 -- distinctive
#: enough that a regression in either probe's numbers would break the match,
#: without pinning the whole multi-section stdout verbatim.
_PLAN = Path(__file__).resolve().parent.parent.parent / "docs" / "plans" / "2026-08-28-skeleton-lever.md"
_PINNED_LINES = (
    "  decomp-holes/skeleton     747    34  4.6%    74  9.9%     1  0.1%   597 79.9%    41  5.5%",
    "  MECHANICAL FLOOR                 42/400  10.50%    2/364   0.55%  19.11   1.34e-10",
    "  floor draws 42   unique surfaces 12   cells reached 8 of 32",
    "         16           32    5.32  $   1.33  $     4.53",
    "         32           64   10.13  $   2.53  $     8.61   over ceiling on-demand",
)


def check_10() -> tuple[bool, list[str]]:
    lines = ["### Check 10 -- skeleton_starve_probe / skeleton_lever_power reproduce\n"
             "###            this plan's pasted §1/§4 numbers (regression check)\n"]
    ok = True
    plan_text = _PLAN.read_text(encoding="utf-8") if _PLAN.is_file() else ""
    for line in _PINNED_LINES:
        in_plan = line in plan_text
        ok = ok and in_plan
        lines.append(f"  plan carries pinned line ({'ok' if in_plan else 'MISSING FROM PLAN'}): "
                     f"{line.strip()[:70]}")
    lines.append("")
    starve = subprocess.run(
        [sys.executable, "-m", "experiment.skeleton_starve_probe"],
        cwd=EXPERIMENT.parent, capture_output=True, text=True)
    power = subprocess.run(
        [sys.executable, "-m", "experiment.skeleton_lever_power"],
        cwd=EXPERIMENT.parent, capture_output=True, text=True)
    exits_ok = starve.returncode == 0 and power.returncode == 2
    ok = ok and exits_ok
    lines.append(f"  skeleton_starve_probe exit={starve.returncode} (expected 0)  "
                 f"skeleton_lever_power exit={power.returncode} (expected 2)  "
                 f"{'ok' if exits_ok else 'WRONG'}")
    for line in _PINNED_LINES:
        reproduced = line in starve.stdout or line in power.stdout
        ok = ok and reproduced
        lines.append(f"  reproduced fresh ({'ok' if reproduced else 'MISSING'}): {line.strip()[:70]}")
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def main() -> int:
    resolver = ExperimentResolver()
    arms = _load_arms()
    checks = [
        ("1", lambda: check_1(arms)),
        ("2", lambda: check_2(arms, resolver)),
        ("3", lambda: check_3(resolver)),
        ("4", lambda: check_4(arms, resolver)),
        ("5", lambda: check_5(arms, resolver)),
        ("6", lambda: check_6(arms, resolver)),
        ("7", lambda: check_7(arms, resolver)),
        ("8", check_8),
        ("9", lambda: check_9(arms, resolver)),
        ("10", check_10),
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
    print("### Deliverable 5 verdict: "
          + ("ALL CHECKS PASS — the GPU gate is open"
             if all_ok else "AT LEAST ONE CHECK FAILED — do not launch"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
