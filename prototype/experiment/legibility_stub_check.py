"""Deliverable 3 — the CPU stub gate on GPU spend for the feedback-legibility
arm. CPU only, no GPU, no network.

[`docs/plans/2026-08-27-feedback-legibility-arm.md`](../../docs/plans/2026-08-27-feedback-legibility-arm.md)
§3 deliverable 3. **This is the gate on GPU spend**: every check below must
print PASS, and the script exits non-zero the moment any one of them fails.

Four checks:

1. **Regression** — `hole_elicitation_stub_check.py`'s own gate, re-run
   unchanged. This arm's deliverable 1 (already landed, `Config.narrowing_note_render`)
   touched `typecheck.py`'s error-text construction and `runner.py`'s per-cell
   setup, both of which that gate's scripted-stub checks exercise; a
   regression there would be a defect this arm introduced, not evidence this
   arm is safe to launch.
2. **C2 — protocol invariance** (§2.4). `_narrows` (`runner.py:660`) must be
   `False` for `generation_protocol == "whole"` under every condition this
   design or its neighbours use, `True` only under `gbnf+rejection` (Phase
   A's own narrowing condition, untouched here) — checked directly against
   the function — and, empirically, a scripted `whole`-protocol cell driven
   under both renders must produce byte-identical prompts: a note that is
   never read cannot leak a rendering difference into the model's input.
3. **Config differences** — `legib_legible.config.json` and
   `legib_repr.config.json` differ from `decomp-redraft.config.json` by
   exactly `output_dir` and `narrowing_note_render`, and both validate. The
   same assertion `test_legibility_arm.py` makes as a unit test, restated
   here so the gate's own output is self-contained.
4. **A scripted stub drives one cell of each arm**, loaded from the shipped
   config files rather than reconstructed. Both cells classify the same
   rejected draft identically (C3, at the config level, not just at
   `typecheck.py`'s), and the note fed into the second draw's prompt differs
   exactly as each arm's `narrowing_note_render` says it should — `repr`
   leaks the artefact pattern, `surface` does not.

    python3 -m experiment.legibility_stub_check   (from prototype/)
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import re
import sys
from pathlib import Path

import typecheck
from experiment import decomposition_stub_check, hole_elicitation_stub_check, runner
from experiment.backends import StubBackend
from experiment.resolver import ExperimentResolver

EXPERIMENT = Path(__file__).resolve().parent

#: Mirrors `test_experiment.py`'s `_REPR_ARTEFACT` — the pattern a raw
#: `repr()` of a type-IR node leaves in rendered text (a Python list-literal
#: opener, or a bytes-literal quote) that the canonical surface never
#: produces. Restated rather than imported: a gate script does not depend on
#: a test module, and the pattern has not moved since `8ed72cd`.
_REPR_ARTEFACT = re.compile(r"expected \[|got \[|b'")

#: `decomposition_stub_check`'s fixtures: a task and the simplest draft that
#: fails `typecheck` (`Bool` declared, `I64` body) — reused rather than
#: rebuilt, same discipline as that module's own reuse of `decomposition_stub_check`.
STUB_TASK = decomposition_stub_check.STUB_TASK
REJECTED_DRAFT = decomposition_stub_check.REJECTED_DRAFT

SOURCE_CONFIG = "decomp-redraft.config.json"
#: arm -> (config filename, its narrowing_note_render, whether a rejected
#: draw's note is expected to leak the repr artefact).
ARM_CONFIGS = {
    "legib-legible": ("legib_legible.config.json", typecheck.NARROWING_NOTE_SURFACE, False),
    "legib-repr": ("legib_repr.config.json", typecheck.NARROWING_NOTE_REPR, True),
}


def _drive_stub_cell(config, resolver):
    """One narrowed cell, `REJECTED_DRAFT` on every draw, capped at 2 draws
    by `config.max_draws_per_task` — enough for draw 1's prompt to carry
    whatever draw 0's rejection fed back, and no more."""
    config.validate()
    backend = StubBackend([REJECTED_DRAFT])
    records = runner.run_task(
        STUB_TASK, config.conditions[0], runner.REGIME_HELD_OUT, config.seeds[0],
        backend, resolver, config, runner.grammar_text())
    return records, backend


# --------------------------------------------------------------------------
# Check 1 — regression
# --------------------------------------------------------------------------

def check_1_regression() -> tuple[bool, list[str]]:
    lines = ["### Check 1 — hole_elicitation_stub_check.py, re-run unchanged (regression)\n"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = hole_elicitation_stub_check.main()
    output = buf.getvalue()
    ok = rc == 0
    verdict = next(
        (line for line in reversed(output.splitlines()) if "verdict" in line.lower()), "")
    lines.append(f"  exit code: {rc}")
    lines.append(f"  {verdict}")
    lines.append(f"\n  result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 2 — C2: protocol invariance
# --------------------------------------------------------------------------

def check_2_c2_protocol_invariance(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 2 — C2: protocol invariance (`whole` is inert to the render seam)\n"]

    # -- the function, directly: false everywhere but gbnf+rejection, and
    #    true unconditionally for redraft/holes (this arm's own protocol) ---
    matrix = [
        (runner.PROTOCOL_WHOLE, runner.CONDITION_GBNF, False),
        (runner.PROTOCOL_WHOLE, runner.CONDITION_TYPEMASK, False),
        (runner.PROTOCOL_WHOLE, runner.CONDITION_GBNF_REJECTION, True),
        (runner.PROTOCOL_REDRAFT, runner.CONDITION_GBNF, True),
        (runner.PROTOCOL_REDRAFT, runner.CONDITION_TYPEMASK, True),
        (runner.PROTOCOL_HOLES, runner.CONDITION_GBNF, True),
    ]
    matrix_ok = True
    for protocol, condition, expected in matrix:
        actual = runner._narrows(runner.Config(generation_protocol=protocol), condition)
        good = actual == expected
        matrix_ok = matrix_ok and good
        lines.append(
            f"  _narrows(protocol={protocol!r:<10} condition={condition!r:<16}) = "
            f"{actual!s:<5} (expected {expected!s:<5})  {'ok' if good else 'WRONG'}")

    # -- empirically: a scripted `whole` cell, driven under both renders, must
    #    produce byte-identical prompts, because the note it would leak
    #    through is never computed for this protocol ---------------------
    prompt_lists = {}
    outcomes = {}
    for render in (typecheck.NARROWING_NOTE_SURFACE, typecheck.NARROWING_NOTE_REPR):
        config = runner.Config(
            backend="stub", generation_protocol=runner.PROTOCOL_WHOLE,
            conditions=[runner.CONDITION_GBNF], seeds=[1], tasks=[STUB_TASK.task_id],
            max_draws_per_task=2, token_budget_per_task=4608, max_tokens_per_draw=768,
            narrowing_note_render=render, address_book="full", leave_one_out=True,
            source_path="<legibility_stub_check:check_2>")
        records, backend = _drive_stub_cell(config, resolver)
        prompt_lists[render] = list(backend.prompts)
        outcomes[render] = [r["funnel_outcome"] for r in records]
        lines.append(f"  render={render:<7} draws={len(records)}  funnel_outcomes={outcomes[render]}")

    identical = (prompt_lists[typecheck.NARROWING_NOTE_SURFACE]
                 == prompt_lists[typecheck.NARROWING_NOTE_REPR])
    lines.append(f"  whole-protocol prompts, surface vs repr: "
                 f"{'byte-identical' if identical else 'DIFFER'}")

    ok = matrix_ok and identical
    lines.append(f"\n  result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 3 — config differences
# --------------------------------------------------------------------------

def check_3_config_differences() -> tuple[bool, list[str]]:
    lines = [f"### Check 3 — the two arm configs vs {SOURCE_CONFIG} (§3 deliverable 4)\n"]
    src = json.loads((EXPERIMENT / SOURCE_CONFIG).read_text(encoding="utf-8"))
    ok = "narrowing_note_render" not in src
    lines.append(f"  {SOURCE_CONFIG} carries no narrowing_note_render key: {ok}")
    changed = {"output_dir", "narrowing_note_render"}
    for arm, (name, render, _) in ARM_CONFIGS.items():
        dst = json.loads((EXPERIMENT / name).read_text(encoding="utf-8"))
        same = ({k: v for k, v in src.items() if k not in changed}
                == {k: v for k, v in dst.items() if k not in changed})
        render_ok = dst.get("narrowing_note_render") == render
        out_ok = dst.get("output_dir") == f"runs/{arm}"
        runner.Config(**dst).validate()
        good = same and render_ok and out_ok
        ok = ok and good
        lines.append(
            f"  {name:<28} only-two-fields-differ={same}  "
            f"output_dir={dst.get('output_dir')!r}  "
            f"narrowing_note_render={dst.get('narrowing_note_render')!r}  "
            f"validates=True  {'ok' if good else 'WRONG'}")
    lines.append(f"\n  result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 4 — a scripted stub drives one cell of each shipped arm config
# --------------------------------------------------------------------------

def check_4_scripted_stub(resolver) -> tuple[bool, list[str]]:
    lines = ["### Check 4 — a scripted stub drives one cell of each shipped arm config\n"]
    lines.append(
        "  note: driven at condition `gbnf` (the mask needs a real vocabulary) with the\n"
        "        draw cap overridden to 2 and the backend replaced with a stub; every\n"
        "        other field — including `narrowing_note_render` — is the arm's own\n"
        "        shipped config, loaded from disk rather than reconstructed.\n")
    ok = True
    outcomes = {}
    for arm, (name, render, should_leak) in ARM_CONFIGS.items():
        config = dataclasses.replace(
            runner.Config.load(EXPERIMENT / name),
            backend="stub", conditions=[runner.CONDITION_GBNF], seeds=[1],
            tasks=[STUB_TASK.task_id], max_draws_per_task=2,
            source_path="<legibility_stub_check:check_4>")
        assert config.narrowing_note_render == render  # the arm's own file, not overridden
        records, backend = _drive_stub_cell(config, resolver)
        arm_outcomes = [r["funnel_outcome"] for r in records]
        outcomes[arm] = arm_outcomes
        leaked = bool(_REPR_ARTEFACT.search(backend.prompts[1])) if len(backend.prompts) > 1 else None
        good = (len(records) == 2 and arm_outcomes == ["typecheck", "typecheck"]
                and leaked == should_leak)
        ok = ok and good
        lines.append(
            f"  {arm:<14} narrowing_note_render={config.narrowing_note_render:<7} "
            f"draws={len(records)} outcomes={arm_outcomes} "
            f"round-1-prompt-leaks-repr={leaked} (expected {should_leak})  "
            f"{'ok' if good else 'WRONG'}")
    outcomes_match = outcomes["legib-legible"] == outcomes["legib-repr"]
    ok = ok and outcomes_match
    lines.append(f"  classification invariance (C3), across arms: "
                 f"{'match' if outcomes_match else 'DIFFER'} — {outcomes}")
    lines.append(f"\n  result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def main() -> int:
    resolver = ExperimentResolver()
    checks = [
        check_1_regression,
        lambda: check_2_c2_protocol_invariance(resolver),
        check_3_config_differences,
        lambda: check_4_scripted_stub(resolver),
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
    print("### Deliverable 3 verdict: "
          + ("ALL CHECKS PASS — the GPU gate is open"
             if all_ok else "AT LEAST ONE CHECK FAILED — do not launch"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
