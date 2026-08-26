"""Tests for `docs/plans/2026-08-26-hole-elicitation.md` deliverable 3 — the
`exemplar` block (B1), its block-selection surface, and §4.7 checks 1b, 1c
and 9. Also deliverable 4 — the `hole-required` block (B2), a runner-level
mechanism with nothing on the prompt side (§2.2: "`hole-required` ... build[s]
the same bytes as `§3-block`" — pinned above by
`test_hole_required_and_checker_holed_build_the_same_bytes_as_protocol`).

Later deliverables in the same plan (B3 `checker-holed`) share this module
rather than starting their own — see the plan's §2.2 for what each block is
and §4.7 for what each numbered check pins.
"""

from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

import corpus_registry
from experiment import prompts, runner
from experiment.backends import Generation, StubBackend
from experiment.evaluate import ACCEPTED, run_funnel
from experiment.heldout_gold import GOLD_TERMS
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
    PROTOCOL_REDRAFT,
    PROTOCOL_WHOLE,
    REGIME_HELD_OUT,
    build_prompt,
    closed_subtask_type,
    declared_type_of,
    estimated_tokens,
    hole_exemplar_block,
    hole_obligations,
    splice_fill,
)
from experiment.resolver import ExperimentResolver

HERE = Path(__file__).resolve().parent

#: The maybe/map exemplar's fill. §2.2 keeps it out of the block itself — it
#: would add 383 characters of hashes to teach a shape the worked `bool/not`
#: exemplar already taught — so it lives here, needed only to drive check 9's
#: round trip the way `hole_elicitation_probe --section exemplars` does.
_MAYBE_HASH = "0x" + corpus_registry.HASHES["Maybe"].hex()
HOLE_EXEMPLAR_MAP_FILL = (
    f"(def (fn (fn I64 () I64) () (fn (data {_MAYBE_HASH} (I64)) () "
    f"(data {_MAYBE_HASH} (I64)))) (lam (fn I64 () I64) (lam (data {_MAYBE_HASH} (I64)) "
    f"(con {_MAYBE_HASH} 0 ()))))"
)

_FIXTURES = {entry.name_path: entry.source_text().rstrip("\n")
             for entry in corpus_registry.MANIFEST}


class HoleBlockSelectionTest(unittest.TestCase):
    """§4.2's block-selection surface, pinned the way `address_book: none` is."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.tasks = HELD_OUT_TASKS

    def test_protocol_is_the_default_and_the_known_values_are_the_plans(self):
        self.assertEqual(
            inspect.signature(build_prompt).parameters["hole_block"].default,
            HOLE_BLOCK_PROTOCOL)
        self.assertEqual(
            HOLE_BLOCKS,
            ("§3-block", "exemplar", "hole-required", "checker-holed"))

    def test_protocol_changes_not_one_byte_from_todays_holes_prompt(self):
        for task in self.tasks:
            default = build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                    generation_protocol=PROTOCOL_HOLES)
            pinned = build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                   generation_protocol=PROTOCOL_HOLES,
                                   hole_block=HOLE_BLOCK_PROTOCOL)
            self.assertEqual(default, pinned, task.task_id)
            self.assertNotIn(HOLE_EXEMPLAR_NOT_SKELETON, default, task.task_id)

    def test_hole_required_and_checker_holed_build_the_same_bytes_as_protocol(self):
        """Both name runner-level mechanisms this module does not implement
        (§2.2): a hole-demand note and `hole_at_error` seeding, neither of
        which touches the prompt. Until they land, both build `§3-block`."""
        for task in self.tasks:
            reference = build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                      generation_protocol=PROTOCOL_HOLES)
            for block in (HOLE_BLOCK_HOLE_REQUIRED, HOLE_BLOCK_CHECKER_HOLED):
                self.assertEqual(
                    reference,
                    build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                  generation_protocol=PROTOCOL_HOLES,
                                  hole_block=block),
                    f"{block} {task.task_id}")

    def test_exemplar_differs_from_protocol_only_by_the_exemplar_block(self):
        """§4.7 check 1: strip the exemplar addition and B0's bytes come back —
        the same byte-comparison discipline `test_holes_differs_from_whole_
        only_by_the_protocol_block` in `test_experiment.py` already applies to
        the arm this block sits inside."""
        block = hole_exemplar_block(self.resolver)
        for task in self.tasks:
            control = build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                    generation_protocol=PROTOCOL_HOLES)
            armed = build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                  generation_protocol=PROTOCOL_HOLES,
                                  hole_block=HOLE_BLOCK_EXEMPLAR)
            self.assertIn(HOLE_PROTOCOL_BLOCK, armed, task.task_id)
            self.assertIn(block, armed, task.task_id)
            self.assertEqual(
                armed.replace(f"\n\n{block}", "", 1), control, task.task_id)

    def test_the_block_is_identical_across_every_held_out_task(self):
        """The task instructions' check: the block is identical across tasks
        within an arm. `hole_exemplar_block` is a function of the resolver's
        own fixtures alone, so every task's prompt carries the same bytes."""
        block = hole_exemplar_block(self.resolver)
        for task in self.tasks:
            armed = build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                  generation_protocol=PROTOCOL_HOLES,
                                  hole_block=HOLE_BLOCK_EXEMPLAR)
            self.assertIn(block, armed, task.task_id)
        # And calling the constructor twice gives back the same bytes, not
        # merely an equal-looking string built differently each time.
        self.assertEqual(block, hole_exemplar_block(self.resolver))

    def test_whole_and_redraft_are_unmoved_by_hole_block(self):
        """`hole_block` is only ever read for `generation_protocol == "holes"`;
        a value has to be *known* (§4.2's four names) but not-`"holes"` arms
        never reach the block itself."""
        for task in self.tasks:
            for protocol in (PROTOCOL_WHOLE, PROTOCOL_REDRAFT):
                self.assertEqual(
                    build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                  generation_protocol=protocol),
                    build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                  generation_protocol=protocol,
                                  hole_block=HOLE_BLOCK_EXEMPLAR),
                    task.task_id)

    def test_an_unknown_hole_block_is_refused_by_name(self):
        with self.assertRaises(ValueError) as raised:
            build_prompt(self.tasks[0], REGIME_HELD_OUT, self.resolver,
                          generation_protocol=PROTOCOL_HOLES, hole_block="freestyle")
        self.assertIn("freestyle", str(raised.exception))

    def test_the_exemplar_block_sits_after_the_protocol_block_and_before_narrowing(self):
        armed = build_prompt(
            self.tasks[0], REGIME_HELD_OUT, self.resolver,
            generation_protocol=PROTOCOL_HOLES, hole_block=HOLE_BLOCK_EXEMPLAR,
            narrowing="REJECTED: nope")
        self.assertLess(armed.index(HOLE_PROTOCOL_BLOCK),
                         armed.index(HOLE_EXEMPLAR_NOT_SKELETON))
        self.assertLess(armed.index(HOLE_EXEMPLAR_NOT_SKELETON), armed.index("REJECTED"))
        self.assertLess(armed.index("REJECTED"), armed.index(self.tasks[0].spec))


class ExemplarBlockCheck1bTest(unittest.TestCase):
    """§4.7 check 1b: the sub-task inside the block is derived from the
    exemplar's own declared type, never a task's — pinned by signature the
    way `ClosedSubtaskTypeTest.test_the_closure_is_never_handed_anything_
    that_knows_the_route` pins `closed_subtask_type` itself."""

    def test_hole_exemplar_block_takes_no_task(self):
        parameters = inspect.signature(hole_exemplar_block).parameters
        self.assertEqual(list(parameters), ["resolver"])
        for name in parameters:
            self.assertNotIn("task", name)

    def test_the_shape_exemplars_subtask_comes_from_its_own_declared_type(self):
        resolver = ExperimentResolver()
        obligation, = hole_obligations(HOLE_EXEMPLAR_MAP_SKELETON, resolver)
        expected = closed_subtask_type(
            declared_type_of(HOLE_EXEMPLAR_MAP_SKELETON), obligation)
        self.assertIn(expected, hole_exemplar_block(resolver))


class ExemplarBlockCheck1cTest(unittest.TestCase):
    """§4.7 check 1c: no gold surface and no new hash enters a prompt via the
    block (§2.2's leak checks, already pasted into the plan; re-run here
    rather than only cited, since this is the deliverable that lands them)."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.block = hole_exemplar_block(cls.resolver)

    def test_no_held_out_gold_term_or_type_surface_appears_in_the_block(self):
        for task in HELD_OUT_TASKS:
            self.assertNotIn(GOLD_TERMS[task.task_id], self.block, task.task_id)
            self.assertNotIn(task.expected_type_surface, self.block, task.task_id)

    def test_every_hash_in_the_block_is_already_in_the_four_few_shot_definitions(self):
        shown = set()
        for name in FEW_SHOT_NAMES:
            shown |= set(_hex_hashes(_FIXTURES[name]))
        block_hashes = set(_hex_hashes(self.block))
        self.assertTrue(block_hashes, "the block should carry at least the Maybe hash")
        self.assertTrue(block_hashes <= shown, block_hashes - shown)

    def test_the_block_size_is_the_plans_pinned_figure(self):
        """§2.2: 847 characters of definition surface, ~565 tokens — the whole
        cost model (`~3%` of an 18.8k-token prompt) is stated against this
        number, so a drift here is a drift in the plan's cost accounting."""
        self.assertEqual(len(self.block), 847)
        self.assertEqual(estimated_tokens(self.block), 565)


def _hex_hashes(text: str) -> list[str]:
    return re.findall(r"0x[0-9a-f]{64}", text)


class ExemplarRoundTripCheck9Test(unittest.TestCase):
    """§4.7 check 9: both §2.2 exemplars, driven end to end — skeleton
    funnel-accepted, fill funnel-accepted, splice byte-identical to the corpus
    fixture, assembly funnel-accepted. Already pasted into the plan as
    `hole_elicitation_probe --section exemplars`' output; this is the same
    round trip run as a regression test against `prompts.py`'s own names."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def _round_trip(self, name, draft, fill):
        obligations = hole_obligations(draft, self.resolver)
        self.assertEqual(len(obligations), 1, name)
        obligation, = obligations
        self.assertTrue(obligation.fillable, name)
        self.assertEqual(run_funnel(draft, self.resolver).outcome, ACCEPTED, name)
        self.assertEqual(run_funnel(fill, self.resolver).outcome, ACCEPTED, name)
        assembled = splice_fill(draft, obligation, fill)
        self.assertEqual(assembled, _FIXTURES[name], name)
        self.assertEqual(run_funnel(assembled, self.resolver).outcome, ACCEPTED, name)

    def test_the_worked_exemplar_bool_not_round_trips_to_the_fixture(self):
        self._round_trip(
            "corpus/bool/not", HOLE_EXEMPLAR_NOT_SKELETON, HOLE_EXEMPLAR_NOT_FILL)

    def test_the_shape_exemplar_maybe_map_round_trips_to_the_fixture(self):
        self._round_trip(
            "corpus/maybe/map", HOLE_EXEMPLAR_MAP_SKELETON, HOLE_EXEMPLAR_MAP_FILL)


class _RoundScriptedBackend(StubBackend):
    """A stub that answers by *prompt shape*: skeleton asks and fill asks
    differ (`prompts.FILL_HEADER` marks a fill prompt), each served from its
    own script and repeating its last entry once exhausted. The same split
    `test_experiment.py`'s `_ScriptedBackend` makes for the fill-gate tests,
    kept local here so this module never has to import from a sibling test
    file that a concurrent change might be mid-editing.
    """

    def __init__(self, skeletons, fills=()):
        super().__init__(list(skeletons))
        self.skeleton_script = list(skeletons)
        self.fill_script = list(fills) or ["(def Bool (lit bool true))"]
        self.skeleton_prompts: list[str] = []
        self.fill_prompts: list[str] = []

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        fill = prompts.FILL_HEADER in prompt
        script = self.fill_script if fill else self.skeleton_script
        seen = self.fill_prompts if fill else self.skeleton_prompts
        text = script[min(len(seen), len(script) - 1)]
        seen.append(prompt)
        self.prompts.append(prompt)
        self.draws += 1
        natural = max(1, len(text) // 4)
        used = min(natural, max_tokens)
        return Generation(
            text=text, completion_tokens=used, prompt_tokens=max(1, len(prompt) // 4),
            latency_s=0.0, stop_reason="length" if used < natural else "stop",
            backend=self.name)


#: Holeless, funnel-accepted. `HOLE_EXEMPLAR_NOT_FILL` is exactly this shape —
#: already round-tripped by `ExemplarRoundTripCheck9Test` — reused rather than
#: hand-built so a drift in one shows up as a failure in the other too.
_HOLELESS_ACCEPTED = HOLE_EXEMPLAR_NOT_FILL

#: Holeless, typecheck-rejected: a `Bool`-declared definition whose body is an
#: `I64` literal. Reaches the typecheck layer (parse, scope and references all
#: pass — `layers_passed == 3`) and carries no `hole` node anywhere.
_HOLELESS_REJECTED = "(def Bool (lit i64 1))"

#: One fillable, non-bare hole, funnel-accepted. `HOLE_EXEMPLAR_NOT_SKELETON`
#: and its own fill, both already round-tripped by the same check.
_HOLED_ACCEPTED = HOLE_EXEMPLAR_NOT_SKELETON
_HOLED_ACCEPTED_FILL = HOLE_EXEMPLAR_NOT_FILL

#: A bare hole under zero binders: the body IS the hole, so `bare_hole_body`
#: is true even though the census counts one (fillable) hole. §3's rule
#: already refuses this one a fill; B2's condition ("no hole, or a bare-hole
#: body") is what this fixture is for.
_BARE_HOLE_ACCEPTED = "(def Bool (hole Bool ()))"


class HoleRequiredBlockTest(unittest.TestCase):
    """Deliverable 4, 2026-08-26 hole-elicitation plan §2.2 B2: for the first
    `hole_required_rounds` rounds of a cell, a round whose draft carried no
    hole at all — or nothing but a bare one — gets the hole-demand note
    appended to, never substituted for, that round's §8.3 narrowing note.
    `0` (default) is the pre-existing behaviour, byte for byte, the same
    pinning discipline `FillGateTest` in `test_experiment.py` uses for
    `fill_gate`.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.task = HELD_OUT_TASKS[0]

    def _config(self, **overrides):
        config = runner.Config(
            backend="stub",
            seeds=[1],
            conditions=[runner.CONDITION_GBNF],
            regimes=[REGIME_HELD_OUT],
            tasks=[self.task.task_id],
            token_budget_per_task=6000,
            max_tokens_per_draw=60,
            max_draws_per_task=2,
            generation_protocol=PROTOCOL_HOLES,
            source_path="<test>",
        )
        for key, value in overrides.items():
            setattr(config, key, value)
        config.validate()
        return config

    def _run(self, skeletons, fills=(), **overrides):
        config = self._config(**overrides)
        backend = _RoundScriptedBackend(skeletons, fills)
        records, summary = runner.run(config, resolver=self.resolver, backend=backend)
        return records, summary, backend

    @staticmethod
    def _by_role(records, role):
        return [r for r in records if r["role"] == role]

    # -- the default, pinned -------------------------------------------------

    def test_hole_required_rounds_defaults_to_zero_and_shipped_configs_are_unmoved(self):
        self.assertEqual(runner.Config().hole_required_rounds, 0)
        for name in ("decomp-whole.config.json", "decomp-redraft.config.json",
                     "decomp-holes.config.json"):
            config = runner.Config.load(HERE / "experiment" / name)
            self.assertEqual(config.hole_required_rounds, 0, name)

    def test_a_negative_hole_required_rounds_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(hole_required_rounds=-1).validate()
        self.assertIn("hole_required_rounds", str(raised.exception))

    def test_unselected_arm_never_appends_the_note_however_holeless_the_drafts(self):
        """`hole_required_rounds=0` (every pre-existing config): a run of
        nothing but holeless drafts is byte-identical in mechanism to a plain
        `holes` run — the demand note never fires, whatever the drafts look
        like."""
        records, summary, backend = self._run(
            [_HOLELESS_ACCEPTED, _HOLELESS_ACCEPTED, _HOLELESS_ACCEPTED],
            max_draws_per_task=3)
        skeletons = self._by_role(records, "skeleton")
        self.assertEqual(len(skeletons), 3)
        for record in skeletons:
            self.assertFalse(record["hole_required_note_added"])
            self.assertEqual(record["hole_required_rounds"], 0)
        for prompt in backend.skeleton_prompts:
            self.assertNotIn(runner.HOLE_REQUIRED_NOTE, prompt)
        self.assertEqual(summary["protocol"]["hole_required_notes_added"], 0)
        report = runner.render_report(summary, records)
        self.assertNotIn("Hole-required notes added", report)

    # -- the mechanism, and its window ---------------------------------------

    def test_the_note_is_appended_for_the_first_k_rounds_then_reverts_exactly(self):
        """`hole_required_rounds=2`, four holeless rounds in a row (round
        indices 0-3): rounds 0 and 1 each earn the note for the *next*
        round's prompt (0 < 2, 1 < 2), round 2 does not (2 is not < 2) — so
        round 3's incoming prompt, fed from round 2, is the one that proves
        "reverts exactly": the window closes one round after the K-th, not
        gradually."""
        records, summary, backend = self._run(
            [_HOLELESS_ACCEPTED] * 4, max_draws_per_task=4, hole_required_rounds=2)
        skeletons = self._by_role(records, "skeleton")
        self.assertEqual(len(skeletons), 4)
        self.assertEqual(
            [r["hole_required_note_added"] for r in skeletons],
            [True, True, False, False])
        self.assertEqual(len(backend.skeleton_prompts), 4)
        self.assertNotIn(runner.HOLE_REQUIRED_NOTE, backend.skeleton_prompts[0],
                          "round 0's prompt is the cell's first; nothing has narrowed yet")
        self.assertIn(runner.HOLE_REQUIRED_NOTE, backend.skeleton_prompts[1],
                       "fed from round 0, which earned it (0 < 2)")
        self.assertIn(runner.HOLE_REQUIRED_NOTE, backend.skeleton_prompts[2],
                       "fed from round 1, which earned it (1 < 2)")
        self.assertNotIn(runner.HOLE_REQUIRED_NOTE, backend.skeleton_prompts[3],
                          "fed from round 2, which did not (2 is not < 2) -- reverted exactly")
        self.assertEqual(summary["protocol"]["hole_required_notes_added"], 2)
        report = runner.render_report(summary, records)
        self.assertIn("**Hole-required notes added (§2.2 B2):** 2", report)

    def test_the_note_is_appended_never_substituted_for_the_ordinary_narrowing(self):
        """A round that is both rejected AND holeless must feed the *next*
        prompt both notes — the plan's own wording, "appended to ... never
        substituted for" — with the ordinary §8.3 text first and the demand
        note after it."""
        records, _, backend = self._run(
            [_HOLELESS_REJECTED, _HOLELESS_ACCEPTED],
            max_draws_per_task=2, hole_required_rounds=1)
        self.assertEqual(records[0]["funnel_outcome"], "typecheck")
        second_prompt = backend.skeleton_prompts[1]
        self.assertIn("rejected by the typecheck layer", second_prompt)
        self.assertIn(runner.HOLE_REQUIRED_NOTE, second_prompt)
        self.assertLess(
            second_prompt.index("rejected by the typecheck layer"),
            second_prompt.index(runner.HOLE_REQUIRED_NOTE),
            "appended after the ordinary note, not before and not in place of it")

    def test_a_hole_bearing_non_bare_draft_never_earns_the_note(self):
        """A draft that already carries a genuine, fillable hole is exactly
        what B2 wants — no demand note is owed, and the round proceeds to a
        fill exactly as it would under any other block."""
        records, _, backend = self._run(
            [_HOLED_ACCEPTED, _HOLELESS_ACCEPTED], [_HOLED_ACCEPTED_FILL],
            max_draws_per_task=3, hole_required_rounds=3)
        skeleton = self._by_role(records, "skeleton")[0]
        self.assertFalse(skeleton["hole_required_note_added"])
        self.assertEqual(skeleton["holes"], 1)
        fills = self._by_role(records, "fill")
        self.assertEqual(len(fills), 1, "the fillable hole still reaches a fill")
        self.assertNotIn(runner.HOLE_REQUIRED_NOTE, backend.skeleton_prompts[1])

    def test_a_bare_hole_draft_earns_the_note_despite_carrying_a_hole(self):
        """§2.2's parenthetical: "no hole (or a bare-hole body)". A bare hole
        counts as a census hole (it IS one), so the "no hole at all" leg does
        not fire — the bare-hole leg has to be checked on its own, or this
        case would wrongly slip through unnoticed."""
        records, _, backend = self._run(
            [_BARE_HOLE_ACCEPTED, _HOLELESS_ACCEPTED],
            max_draws_per_task=2, hole_required_rounds=1)
        skeleton = records[0]
        self.assertEqual(skeleton["holes"], 1)
        self.assertTrue(skeleton["bare_hole_body"])
        self.assertTrue(skeleton["hole_required_note_added"])
        self.assertIn(runner.HOLE_REQUIRED_NOTE, backend.skeleton_prompts[1])
        self.assertEqual(backend.fill_prompts, [],
                          "§3's rule still refuses the bare hole a fill, unrelated to B2")

    # -- composition with the §2.1 fill gate ---------------------------------

    def test_composes_with_the_well_scoped_fill_gate_without_interference(self):
        """A holeless, typecheck-rejected draft: under `fill_gate: well-scoped`
        the gate admits the round (layers_passed >= 3, not bare) but there is
        nothing to fill (zero obligations), so no fill draw happens either
        way. B2 fires independently of that admission decision — the two
        mechanisms answer different questions and neither one's outcome
        depends on the other's."""
        records, summary, backend = self._run(
            [_HOLELESS_REJECTED, _HOLELESS_ACCEPTED], max_draws_per_task=2,
            hole_required_rounds=1, fill_gate=runner.FILL_GATE_WELL_SCOPED)
        skeleton = records[0]
        self.assertEqual(skeleton["funnel_outcome"], "typecheck")
        self.assertEqual(skeleton["fill_gate"], runner.FILL_GATE_WELL_SCOPED)
        self.assertTrue(skeleton["hole_required_note_added"])
        self.assertEqual(backend.fill_prompts, [], "no obligations to fill, gate aside")
        self.assertIn(runner.HOLE_REQUIRED_NOTE, backend.skeleton_prompts[1])
        self.assertEqual(summary["protocol"]["hole_required_notes_added"], 1)

    # -- config echo -----------------------------------------------------

    def test_hole_required_rounds_is_echoed_on_every_record(self):
        records, _, _ = self._run(
            [_HOLELESS_ACCEPTED, _HOLELESS_ACCEPTED], max_draws_per_task=2,
            hole_required_rounds=2)
        for record in records:
            self.assertEqual(record["hole_required_rounds"], 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
