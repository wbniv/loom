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
import json
import re
import tempfile
import unittest
from pathlib import Path

import corpus_registry
from experiment import prompts, runner
from experiment.backends import Generation, StubBackend
from experiment.evaluate import ACCEPTED, run_funnel
from experiment.heldout_gold import GOLD_TERMS
from experiment.hole_elicitation_probe import (
    CHECK_TEN_ALLOWED,
    CHECK_TEN_CUT,
    CHECK_TEN_REFUSED,
    check_ten_rows,
    check_ten_verdict,
)
from experiment.hole_elicitation_probe import load as load_banked
from experiment.pilot_select import (
    BLOCK_RUN_DIRS,
    CANDIDATE_BLOCKS,
    EXIT_ESCALATE,
    EXIT_NO_LAUNCH_E1,
    EXIT_NO_LAUNCH_E2,
    EXIT_SELECT,
    apply_selection,
    assembly_liveness,
    block_stats,
    load_block,
    main as pilot_select_main,
    selection_verdict,
)
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
    checker_holed_cut,
    closed_subtask_type,
    declared_type_of,
    estimated_tokens,
    hole_at_error,
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


# --------------------------------------------------------------------------
# Deliverable 5 — `hole_at_error` and the `checker-holed` block (B3)
# --------------------------------------------------------------------------
#
# B3 is the plan's only optional deliverable and its only *barred* one: §2.2
# pre-commits it out of the primary family because the harness choosing where
# to cut breaks 2026-08-25 §2.1's no-oracle property. So these tests are
# written to two standards at once — the mechanism does what §2.2 says, and it
# cannot leak into any arm that did not ask for it.

#: The plan's own §2.1 exemplar, one step earlier: `corpus/bool/not` with an
#: `I64` literal where the `then` branch should be `Bool`. Reaches the
#: typecheck layer, fails at `definition.term.body.then` — a cut site — and the
#: cut turns it into `HOLE_EXEMPLAR_NOT_SKELETON` exactly, whose fill
#: (`HOLE_EXEMPLAR_NOT_FILL`) `ExemplarRoundTripCheck9Test` has already
#: round-tripped. One fixture, three deliverables, no hand-built surfaces.
_THEN_BRANCH_REJECTED = (
    "(def (fn Bool () Bool) (lam Bool (if (var 0) (lit i64 1) (lit bool true))))")

#: Two errors, one at a cut site and one below it in a sibling. The cut
#: repairs the first and the second survives — §1.2's whole finding in one
#: draft, and the fixture for "a seed is not waved past the gate".
_TWO_ERRORS_REJECTED = (
    "(def (fn Bool () Bool) (lam Bool (if (var 0) (lit i64 1) (lit i64 2))))")

#: `(hole Bool ())` under the single top-level lambda: what the cut on
#: `_THEN_BRANCH_REJECTED` must produce, byte for byte.
_THEN_BRANCH_SEEDED = HOLE_EXEMPLAR_NOT_SKELETON


class HoleAtErrorTest(unittest.TestCase):
    """§2.2 B3's pure function. `None` is the default answer, not the fallback:
    it cuts only where the goal is *derivable* from the draft's own declared
    type and the annotations above the failing node, and refuses everywhere
    else rather than inventing a goal.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def _cut(self, source):
        """`(funnel, cut)` for a draft, driven through the real funnel so the
        error path under test is the one the checker actually reported."""
        funnel = run_funnel(source, self.resolver)
        return funnel, checker_holed_cut(source, funnel.error_path, self.resolver)

    # -- the signature and the blindness -------------------------------------

    def test_the_plans_signature_works_with_two_positional_arguments(self):
        """§2.2 spells it `hole_at_error(source, error_path) -> str | None`.
        The resolver is one optional argument beyond that and buys exactly one
        cut site (`con` arguments); everything else must work without it."""
        parameters = list(inspect.signature(hole_at_error).parameters)
        self.assertEqual(parameters[:2], ["draft_source", "error_path"])
        self.assertEqual(
            inspect.signature(hole_at_error).parameters["resolver"].default, None)
        self.assertEqual(
            hole_at_error(_THEN_BRANCH_REJECTED, "definition.term.body.then"),
            _THEN_BRANCH_SEEDED)

    def test_it_is_never_handed_a_task_so_it_cannot_consult_a_route_or_a_gold(self):
        """The adversarial pin every function on the fill path carries (§4.7
        check 1b's discipline): a `Task` is what holds `composes` and
        `expected_surface`, so a signature that cannot accept one cannot read
        one. Checked against the parameter list rather than by inspecting
        behaviour, because a behavioural check passes for a function that reads
        a task it happens not to have been given yet."""
        for function in (hole_at_error, checker_holed_cut):
            names = set(inspect.signature(function).parameters)
            self.assertNotIn("task", names, function.__name__)
            self.assertEqual(
                names, {"draft_source", "error_path", "resolver"}, function.__name__)

    def test_the_cut_reads_the_drafts_own_declared_type_and_never_the_tasks(self):
        """The same property §4.7 check 1b pins for `closed_subtask_type`,
        restated for B3: hand the same draft and error path to the function
        while eight different held-out tasks are notionally in play and the
        answer cannot move, because the task is not an input. The goal written
        into the hole comes from the draft's own `(def TYPE …)`."""
        _funnel, cut = self._cut(_THEN_BRANCH_REJECTED)
        self.assertEqual(cut.goal_surface, "Bool")
        self.assertEqual(
            declared_type_of(cut.source), declared_type_of(_THEN_BRANCH_REJECTED))
        for task in HELD_OUT_TASKS:
            self.assertEqual(
                hole_at_error(_THEN_BRANCH_REJECTED, "definition.term.body.then",
                              self.resolver),
                cut.source, task.task_id)

    def test_no_gold_surface_can_reach_the_repaired_draft(self):
        """A cut is a *deletion* — a subtree replaced by a hole — so the
        repaired draft is a subset of the model's own bytes plus one goal type
        read off that same draft. Pinned against the held-out gold terms
        directly, the way check 1c pins the exemplar block."""
        for source in (_THEN_BRANCH_REJECTED, _TWO_ERRORS_REJECTED):
            _funnel, cut = self._cut(source)
            for name, gold in GOLD_TERMS.items():
                self.assertNotIn(gold, cut.source, name)

    # -- the cut itself ------------------------------------------------------

    def test_it_cuts_at_the_failing_if_branch_and_lands_the_plans_exemplar(self):
        """§2.2's walk, on the case the plan itself uses to argue B3 escapes
        §2.5: the draft's own declared type is the model's, the goal at the cut
        is derived from it, and the result is a genuinely nested skeleton — the
        `bool/not` shape, byte-identical to the exemplar block's."""
        funnel, cut = self._cut(_THEN_BRANCH_REJECTED)
        self.assertEqual(funnel.outcome, "typecheck")
        self.assertEqual(funnel.error_path, "definition.term.body.then")
        self.assertEqual(cut.source, _THEN_BRANCH_SEEDED)
        self.assertEqual(cut.path, (2, 2, 2))
        self.assertEqual(cut.reason, "")
        self.assertEqual(run_funnel(cut.source, self.resolver).outcome, ACCEPTED,
                         "a hole inhabits its goal type by fiat (SPEC §2.6), so "
                         "cutting the failing node repairs this draft outright")
        obligations = hole_obligations(cut.source, self.resolver)
        self.assertEqual(len(obligations), 1)
        self.assertTrue(obligations[0].fillable)
        self.assertEqual(obligations[0].path, cut.path,
                         "the hole the fill path will find is the one B3 cut")

    def test_it_cuts_at_the_nearest_ancestor_not_the_outermost_one(self):
        """"Walk *up* to the nearest ancestor" is load-bearing: cutting higher
        would delete structure the model committed to and got right, which is
        the whole difference between decomposition and starting over."""
        source = ("(def (fn Bool () Bool) (lam Bool (if (var 0) "
                  "(if (var 0) (lit i64 1) (lit bool true)) (lit bool false))))")
        funnel, cut = self._cut(source)
        self.assertEqual(funnel.error_path, "definition.term.body.then.then")
        self.assertEqual(cut.path, (2, 2, 2, 2), "the inner branch, not the outer one")
        self.assertIn("(if (var 0) (hole Bool ()) (lit bool true))", cut.source,
                      "the inner if's own else branch survives the cut")
        self.assertTrue(cut.source.endswith("(lit bool false))))"),
                        "and so does the outer if's")

    def test_a_match_arm_body_and_a_con_argument_are_cut_sites(self):
        """Two of §2.2's five positions, each needing something the other does
        not: an arm body needs the walk to step through `arms[i]`, and a `con`
        argument needs the data declaration, which is the one thing the
        resolver is here for."""
        maybe = "0x" + corpus_registry.HASHES["Maybe"].hex()
        arm = (f"(def (fn (data {maybe} (I64)) () Bool) (lam (data {maybe} (I64)) "
               f"(match (var 0) ((0 0 (lit bool true)) "
               f"(1 1 (if (lit bool true) (lit i64 9) (lit bool false)))))))")
        _funnel, cut = self._cut(arm)
        self.assertEqual(cut.path, (2, 2, 2, 1, 2, 2))
        self.assertEqual(cut.goal_surface, "Bool")
        constructor = f"(def (data {maybe} (Bool)) (con {maybe} 1 ((lit i64 3))))"
        _funnel, cut = self._cut(constructor)
        self.assertEqual(cut.path, (2, 3, 0))
        self.assertEqual(cut.goal_surface, "Bool",
                         "the constructor's field type, instantiated at the "
                         "data type's own argument")

    def test_a_con_argument_is_not_a_cut_site_without_a_resolver(self):
        """"under a **known** data type" is a property of what can be looked
        up. With no resolver the field types are not derivable, and the walk
        climbs past rather than guessing — which here means refusing."""
        maybe = "0x" + corpus_registry.HASHES["Maybe"].hex()
        source = f"(def (data {maybe} (Bool)) (con {maybe} 1 ((lit i64 3))))"
        funnel = run_funnel(source, self.resolver)
        self.assertIsNotNone(hole_at_error(source, funnel.error_path, self.resolver))
        self.assertIsNone(hole_at_error(source, funnel.error_path))

    # -- the refusals --------------------------------------------------------

    def test_it_refuses_when_the_nearest_holeable_ancestor_is_the_whole_body(self):
        """§3's bare-hole rule, reached from B3's side. Climbing further only
        makes a barer draft, so this is a refusal rather than a reason to keep
        walking — and it is the *commonest* refusal on the banked records,
        which is what "refusing is the default answer" means in practice."""
        funnel, cut = self._cut(_HOLELESS_REJECTED)
        self.assertEqual(funnel.error_path, "definition.term")
        self.assertEqual(cut.source, "")
        self.assertIn("bare-hole rule", cut.reason)
        self.assertIsNone(hole_at_error(
            _HOLELESS_REJECTED, funnel.error_path, self.resolver))

    def test_a_let_bound_and_an_app_argument_are_not_cut_sites(self):
        """§2.2 enumerates five positions and this walk descends no others. A
        `let`'s bound term and an `app`'s argument are both genuinely in
        checking position, and both are excluded — the `app` argument because
        its type comes from *synthesizing* the function rather than from the
        declared type, and the `let` bound because §2.2 does not list it. Both
        drafts here therefore climb to the top-level body and refuse."""
        for source in (
            "(def (fn Bool () Bool) (lam Bool (let Bool (lit i64 1) (var 0))))",
            "(def (fn Bool () Bool) (lam Bool (app (lam Bool (var 0)) (lit i64 1))))",
        ):
            funnel, cut = self._cut(source)
            self.assertEqual(funnel.outcome, "typecheck", source)
            self.assertEqual(cut.source, "", source)

    def test_it_refuses_an_error_path_that_names_no_term_node(self):
        """A `definition.type…` failure, an empty path, and a draft that does
        not parse. None of the three has a failing *term* node to walk up from,
        and each gets a distinct reason so a refusal histogram stays
        diagnostic rather than a single opaque bucket."""
        cases = {
            "definition.type.codomain": "no term node",
            "": "no term node",
        }
        for error_path, expected in cases.items():
            cut = checker_holed_cut(_THEN_BRANCH_REJECTED, error_path, self.resolver)
            self.assertEqual(cut.source, "", error_path)
            self.assertIn(expected, cut.reason, error_path)
        cut = checker_holed_cut("(def Bool", "definition.term", self.resolver)
        self.assertEqual(cut.source, "")
        self.assertIn("does not parse", cut.reason)

    def test_an_unknown_path_component_truncates_rather_than_derailing(self):
        """`.effect-row`, `.function-row` and anything `typecheck.py` grows
        later are not term steps. The walk stops at the deepest node it is sure
        of — a genuine ancestor of the failure — instead of mis-stepping into
        a sibling."""
        cut = checker_holed_cut(
            _THEN_BRANCH_REJECTED, "definition.term.body.then.effect-row",
            self.resolver)
        self.assertEqual(cut.path, (2, 2, 2),
                         "stopped at `.then`, the deepest known step")
        cut = checker_holed_cut(
            _THEN_BRANCH_REJECTED, "definition.term.body.then.invented",
            self.resolver)
        self.assertEqual(cut.path, (2, 2, 2))

    # -- check 10, as a property of every case above -------------------------

    def test_check_ten_holds_on_every_synthetic_case(self):
        """§4.7 check 10's contract — parses, keeps its declared type, is not a
        bare hole, or `None`, never anything else — asserted through the
        probe's own `check_ten_verdict`, which re-derives each clause from the
        funnel's machinery rather than trusting the function under test."""
        sources = [
            _THEN_BRANCH_REJECTED, _TWO_ERRORS_REJECTED, _HOLELESS_REJECTED,
            _HOLELESS_ACCEPTED, _HOLED_ACCEPTED, _BARE_HOLE_ACCEPTED,
            "(def (fn Bool () Bool) (lam Bool (let Bool (lit i64 1) (var 0))))",
            "(def Bool (lit i64 1))",
            "(def (fn Bool () Bool) (lam I64 (lit bool true)))",
        ]
        for source in sources:
            funnel = run_funnel(source, self.resolver)
            for error_path in (funnel.error_path, "", "definition.term",
                               "definition.type", "definition.term.body.args[9]",
                               "definition.term.body.arms[0].body"):
                verdict = check_ten_verdict(source, error_path, self.resolver)
                self.assertIn(verdict, CHECK_TEN_ALLOWED,
                              f"{source} @ {error_path}: {verdict}")


@unittest.skipUnless(
    (HERE / "runs" / "decomp-holes" / "records.jsonl").is_file(),
    "the banked decomposition run is gitignored; check 10 runs where it exists")
class CheckTenBankedTest(unittest.TestCase):
    """§4.7 check 10 over its own stated population — "every banked
    typecheck-rejected skeleton" — which is what the stub-check gate on GPU
    spend (deliverable 6) will run. Skipped where the runs are not present:
    they are gitignored, so this is a check that fires on the machine that
    holds the evidence and stays honest about being absent elsewhere.
    """

    def test_no_banked_draft_produces_anything_but_a_cut_or_a_refusal(self):
        resolver = ExperimentResolver()
        verdicts: dict[str, int] = {}
        for arm in ("whole", "redraft", "holes"):
            for row in check_ten_rows(load_banked(arm)):
                verdict = check_ten_verdict(
                    row["source"], row.get("error_path") or "", resolver)
                verdicts[verdict] = verdicts.get(verdict, 0) + 1
        violations = {v: n for v, n in verdicts.items() if v not in CHECK_TEN_ALLOWED}
        self.assertEqual(violations, {})
        self.assertGreater(verdicts.get(CHECK_TEN_CUT, 0), 0,
                           "a check that never exercises the cut path proves nothing")
        self.assertGreater(verdicts.get(CHECK_TEN_REFUSED, 0),
                           verdicts.get(CHECK_TEN_CUT, 0),
                           "refusing is the default answer, not the fallback")


class CheckerHoledBlockTest(unittest.TestCase):
    """Deliverable 5's runner half, 2026-08-26 plan §2.2 B3: on a
    typecheck-rejected skeleton the `checker-holed` arm seeds the round from
    `hole_at_error` and sends the repaired draft to the fill path. Every other
    block's round is untouched, pinned the way `fill_gate` and
    `hole_required_rounds` are.
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

    # -- the selection surface, pinned ---------------------------------------

    def test_hole_block_defaults_to_the_banked_block_and_configs_are_unmoved(self):
        self.assertEqual(runner.Config().hole_block, HOLE_BLOCK_PROTOCOL)
        for name in ("decomp-whole.config.json", "decomp-redraft.config.json",
                     "decomp-holes.config.json"):
            config = runner.Config.load(HERE / "experiment" / name)
            self.assertEqual(config.hole_block, HOLE_BLOCK_PROTOCOL, name)

    def test_an_unknown_hole_block_is_refused_by_the_config(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(hole_block="freestyle").validate()
        self.assertIn("hole_block", str(raised.exception))

    def test_hole_block_is_echoed_on_every_record(self):
        """E1 and E2 are per-block rates whose numerator lives on fill records
        and whose denominator on skeleton records, so a pooled pilot
        `records.jsonl` has to partition on this one field."""
        records, _, _ = self._run(
            [_HOLED_ACCEPTED, _HOLELESS_ACCEPTED], [_HOLED_ACCEPTED_FILL],
            hole_block=HOLE_BLOCK_CHECKER_HOLED)
        self.assertTrue(records)
        for record in records:
            self.assertEqual(record["hole_block"], HOLE_BLOCK_CHECKER_HOLED)
        roles = {record["role"] for record in records}
        self.assertIn("fill", roles, "the echo is pinned on a fill record too")

    # -- the unselected arms, byte-identical ---------------------------------

    def test_the_other_three_blocks_never_seed_however_rejected_the_draft(self):
        """The pinning discipline the whole plan runs on: a block that does
        not ask for `hole_at_error` gets a round that never calls it, and the
        records to prove it. `_THEN_BRANCH_REJECTED` is the draft B3 cuts
        successfully, so this is the strongest possible negative case."""
        for block in (HOLE_BLOCK_PROTOCOL, HOLE_BLOCK_EXEMPLAR,
                      HOLE_BLOCK_HOLE_REQUIRED):
            records, summary, backend = self._run(
                [_THEN_BRANCH_REJECTED], max_draws_per_task=1, hole_block=block,
                fill_gate=runner.FILL_GATE_WELL_SCOPED)
            skeleton = self._by_role(records, "skeleton")[0]
            self.assertEqual(skeleton["funnel_outcome"], "typecheck", block)
            self.assertFalse(skeleton["checker_holed_eligible"], block)
            self.assertFalse(skeleton["checker_holed"], block)
            self.assertEqual(skeleton["checker_holed_source"], "", block)
            self.assertEqual(backend.fill_prompts, [], block)
            self.assertEqual(summary["protocol"]["checker_holed_seeds"], 0, block)
            self.assertNotIn("Checker-holed seeds",
                             runner.render_report(summary, records), block)

    def test_the_prompt_identical_blocks_produce_identical_records(self):
        """Not merely "no seed": `§3-block` and `hole-required` build the same
        prompt bytes (§2.2) and, at `hole_required_rounds: 0`, must produce the
        same round field for field. `hole_block` is the only key allowed to
        differ, because it is the arm label. `exemplar` is excluded here and
        only here: it legitimately changes the prompt, which moves
        `tokens_prompt` — its no-seeding property is pinned by the test
        above."""
        shape = {}
        for block in (HOLE_BLOCK_PROTOCOL, HOLE_BLOCK_HOLE_REQUIRED):
            records, _, _ = self._run(
                [_THEN_BRANCH_REJECTED], max_draws_per_task=1, hole_block=block,
                fill_gate=runner.FILL_GATE_WELL_SCOPED)
            shape[block] = [
                {k: v for k, v in record.items()
                 if k not in ("hole_block", "latency_s")}
                for record in records]
        self.assertEqual(shape[HOLE_BLOCK_HOLE_REQUIRED], shape[HOLE_BLOCK_PROTOCOL])

    # -- the mechanism -------------------------------------------------------

    def test_a_typecheck_rejection_is_seeded_and_the_seed_reaches_a_fill(self):
        """The round §2.2 B3 describes, end to end: the model's draft is
        rejected at typecheck, the checker's own error path names a cut site,
        the repaired draft typechecks (SPEC §2.6 — the hole cannot be wrong),
        and the fill path runs against it. The skeleton record still reports
        what the *model* wrote, which is what it is answerable for."""
        records, summary, backend = self._run(
            [_THEN_BRANCH_REJECTED], [_HOLED_ACCEPTED_FILL],
            max_draws_per_task=2, hole_block=HOLE_BLOCK_CHECKER_HOLED)
        skeleton = self._by_role(records, "skeleton")[0]
        self.assertEqual(skeleton["source"], _THEN_BRANCH_REJECTED,
                         "the record reports the model's draft, not the harness's")
        self.assertEqual(skeleton["funnel_outcome"], "typecheck")
        self.assertEqual(skeleton["holes"], 0)
        self.assertTrue(skeleton["checker_holed_eligible"])
        self.assertTrue(skeleton["checker_holed"])
        self.assertEqual(skeleton["checker_holed_reason"], "")
        self.assertEqual(skeleton["checker_holed_source"], _THEN_BRANCH_SEEDED)
        self.assertEqual(skeleton["checker_holed_goal"], "Bool")
        self.assertEqual(skeleton["checker_holed_path"], "2.2.2")
        self.assertEqual(skeleton["checker_holed_outcome"], ACCEPTED)
        self.assertEqual(len(backend.fill_prompts), 1,
                         "the seeded hole reached a fill draw")
        candidate = self._by_role(records, "candidate")[0]
        self.assertTrue(candidate["checker_holed"],
                        "the round's outcome is attributable to the seed")
        self.assertEqual(summary["protocol"]["checker_holed_eligible"], 1)
        self.assertEqual(summary["protocol"]["checker_holed_seeds"], 1)
        self.assertEqual(summary["protocol"]["checker_holed_accepted"], 1)
        report = runner.render_report(summary, records)
        self.assertIn("Checker-holed seeds (§2.2 B3):** 1 of 1", report)
        self.assertIn("barred from the primary family", report,
                      "the report must not let B3 read as a primary arm")

    def test_a_refused_cut_leaves_the_round_exactly_as_it_was(self):
        """B3 refuses far more often than it cuts, and a refusal must be inert
        rather than degrading: the round falls back to plain §8.3 narrowing,
        which is what the other blocks would have done anyway."""
        records, summary, backend = self._run(
            [_HOLELESS_REJECTED, _HOLELESS_ACCEPTED], max_draws_per_task=2,
            hole_block=HOLE_BLOCK_CHECKER_HOLED,
            fill_gate=runner.FILL_GATE_WELL_SCOPED)
        skeleton = self._by_role(records, "skeleton")[0]
        self.assertTrue(skeleton["checker_holed_eligible"])
        self.assertFalse(skeleton["checker_holed"])
        self.assertIn("bare-hole rule", skeleton["checker_holed_reason"])
        self.assertEqual(skeleton["checker_holed_source"], "")
        self.assertEqual(backend.fill_prompts, [])
        self.assertIn("rejected by the typecheck layer", backend.skeleton_prompts[1],
                      "§8.3 narrowing is untouched by the refusal")
        self.assertEqual(summary["protocol"]["checker_holed_seeds"], 0)
        self.assertEqual(
            list(summary["protocol"]["checker_holed_refusals"].values()), [1])

    def test_an_accepted_draft_is_never_eligible(self):
        """B3 runs on a typecheck rejection and nothing else. An accepted draft
        has no failing node, and a parse/scope/references rejection has no
        meaningful error path into a term (§2.1's table is why those three
        layers block a fill at all)."""
        for draft in (_HOLELESS_ACCEPTED, "(def Bool", "(def Bool (var 7))"):
            records, _, _ = self._run(
                [draft], max_draws_per_task=1,
                hole_block=HOLE_BLOCK_CHECKER_HOLED,
                fill_gate=runner.FILL_GATE_WELL_SCOPED)
            skeleton = self._by_role(records, "skeleton")[0]
            self.assertNotEqual(skeleton["funnel_outcome"], "typecheck", draft)
            self.assertFalse(skeleton["checker_holed_eligible"], draft)
            self.assertFalse(skeleton["checker_holed"], draft)

    # -- the seed is judged, not exempted ------------------------------------

    def test_the_seed_is_admitted_by_the_accepted_gate_on_its_own_merits(self):
        """"Straight to the fill path" is not "past the gate". A cut that
        repairs the typecheck failure produces a draft the *default* gate
        accepts, so B3 needs no relaxation to work — which matters, because a
        mechanism that only functions under a second manipulation cannot be
        told apart from that manipulation."""
        records, _, backend = self._run(
            [_THEN_BRANCH_REJECTED], [_HOLED_ACCEPTED_FILL], max_draws_per_task=2,
            hole_block=HOLE_BLOCK_CHECKER_HOLED,
            fill_gate=runner.FILL_GATE_ACCEPTED)
        self.assertEqual(records[0]["checker_holed_outcome"], ACCEPTED)
        self.assertEqual(len(backend.fill_prompts), 1)

    def test_a_seed_that_still_fails_typecheck_is_refused_by_the_accepted_gate(self):
        """§1.2's finding, mechanized: the cut repairs the error it replaced
        and leaves every sibling error standing. Such a seed is *not* waved
        through — under the default gate it gets no fill at all, and only the
        §2.1 relaxation admits it."""
        for gate, expected_fills in ((runner.FILL_GATE_ACCEPTED, 0),
                                     (runner.FILL_GATE_WELL_SCOPED, 1)):
            records, _, backend = self._run(
                [_TWO_ERRORS_REJECTED], [_HOLED_ACCEPTED_FILL],
                max_draws_per_task=2, hole_block=HOLE_BLOCK_CHECKER_HOLED,
                fill_gate=gate)
            skeleton = records[0]
            self.assertTrue(skeleton["checker_holed"], gate)
            self.assertEqual(skeleton["checker_holed_outcome"], "typecheck", gate)
            self.assertEqual(len(backend.fill_prompts), expected_fills, gate)

    def test_a_relaxed_round_is_capped_on_the_models_draft_not_on_the_seed(self):
        """§2.1 consequence 4 caps a round whose *draft* the funnel did not
        accept. A cut that repairs the draft must not buy the harness a
        full-purse round it did not earn — so the cap is read off the
        skeleton draw, before any seeding."""
        records, _, backend = self._run(
            [_THEN_BRANCH_REJECTED], ["(def Bool (lit i64 1))"],
            max_draws_per_task=6, hole_block=HOLE_BLOCK_CHECKER_HOLED,
            fill_gate=runner.FILL_GATE_WELL_SCOPED)
        self.assertEqual(records[0]["checker_holed_outcome"], ACCEPTED,
                         "the seed itself typechecks; the model's draft did not")
        per_round: dict[int, int] = {}
        for fill in self._by_role(records, "fill"):
            per_round[fill["round"]] = per_round.get(fill["round"], 0) + 1
        self.assertTrue(per_round, "the seeded rounds did reach the fill path")
        self.assertEqual(set(per_round.values()), {1},
                         "one fill draw per round, per §2.1 consequence 4 — not "
                         "the §4.3.6 constants the seed's own acceptance would buy")

    def test_b3_does_not_change_the_prompt_bytes(self):
        """§2.2: `checker-holed` is a runner-level mechanism. Its skeleton
        prompt is the `§3-block` prompt, so the pilot's B0-vs-B3 contrast is
        the seeding and nothing else."""
        under_b3 = self._run(
            [_THEN_BRANCH_REJECTED], max_draws_per_task=1,
            hole_block=HOLE_BLOCK_CHECKER_HOLED)[2].skeleton_prompts
        under_b0 = self._run(
            [_THEN_BRANCH_REJECTED], max_draws_per_task=1,
            hole_block=HOLE_BLOCK_PROTOCOL)[2].skeleton_prompts
        self.assertEqual(under_b3, under_b0)


class PilotSelectTest(unittest.TestCase):
    """Deliverable 7's selector: `docs/plans/2026-08-26-hole-elicitation.md`
    §4.2's Stage-0 selection rule, run over fabricated records shaped exactly
    like `runner.py`'s emitted fields rather than over a live run — the rule
    itself is what is under test, not the harness that produces its inputs.
    """

    @staticmethod
    def _skeleton(task, seed, *, outcome="typecheck", bare=False, fillable=1):
        return {"role": runner.ROLE_SKELETON, "task": task, "seed": seed,
                "funnel_outcome": outcome, "bare_hole_body": bare,
                "holes_fillable": fillable}

    @staticmethod
    def _fill(task, seed, round_index, *, spliced):
        return {"role": runner.ROLE_FILL, "task": task, "seed": seed,
                "round": round_index,
                "splice_outcome": runner.SPLICE_SPLICED if spliced
                                   else runner.SPLICE_ROLLED_BACK}

    # -- block_stats -----------------------------------------------------

    def test_block_stats_counts_only_qualifying_skeleton_draws(self):
        """(a) reached typecheck, (b) not bare, (c) >= 1 fillable hole — all
        three, per §4.2. One row fails each condition; only the fourth and
        fifth (two cells) count toward both the draw rate and the cell rate."""
        records = [
            self._skeleton("t1", 1, outcome="parse"),               # (a) fails
            self._skeleton("t1", 2, bare=True),                      # (b) fails
            self._skeleton("t2", 1, fillable=0),                     # (c) fails
            self._skeleton("t2", 2),                                 # qualifies
            self._skeleton("t3", 1),                                 # qualifies
            {"role": runner.ROLE_FILL, "task": "t2", "seed": 2},     # not a skeleton
        ]
        stats = block_stats(records)
        self.assertEqual(stats["draws"], 5)
        self.assertEqual(stats["qualifying"], 2)
        self.assertAlmostEqual(stats["draw_rate"], 0.4)
        self.assertEqual(stats["cells_total"], 5)
        self.assertEqual(stats["cells_qualifying"], 2)
        self.assertAlmostEqual(stats["cell_rate"], 0.4)
        # accepted also counts as "reached typecheck"
        accepted_only = block_stats([self._skeleton("t1", 1, outcome=ACCEPTED)])
        self.assertEqual(accepted_only["qualifying"], 1)

    def test_block_stats_e1_gate_is_the_wilson_lower_bound_not_the_point_estimate(self):
        """§4.2's own worked example, reproduced through `block_stats` rather
        than `hole_elicitation_probe.wilson_lower` directly: at n=180, an
        observed 10% point estimate has a lower bound of 6.9% (below the 10%
        bar — 'a lucky pilot cannot promote a block'), while an observed 15%
        clears it at 11.1%."""
        def rows(n, k):
            return [self._skeleton("t", i, outcome=("typecheck" if i < k else "parse"))
                    for i in range(n)]

        stats = block_stats(rows(180, 18))  # obs=10%
        self.assertAlmostEqual(stats["wilson_lower"], 0.069, places=3)
        self.assertFalse(stats["e1_pass"], "the plan's own bar: 10% observed does not clear")

        stats = block_stats(rows(180, 27))  # obs=15%
        self.assertAlmostEqual(stats["wilson_lower"], 0.111, places=3)
        self.assertTrue(stats["e1_pass"])

    # -- assembly_liveness -------------------------------------------------

    def test_assembly_liveness_pools_across_blocks_and_ignores_rollbacks(self):
        all_records = {
            prompts.HOLE_BLOCK_PROTOCOL: [self._fill("t1", 1, 0, spliced=False)],
            prompts.HOLE_BLOCK_EXEMPLAR: [self._fill("t2", 1, 0, spliced=False),
                                          self._fill("t2", 1, 1, spliced=True)],
        }
        e2 = assembly_liveness(all_records)
        self.assertTrue(e2["cleared"])
        self.assertEqual(len(e2["hits"]), 1)
        self.assertEqual(e2["hits"][0]["block"], prompts.HOLE_BLOCK_EXEMPLAR)

    def test_assembly_liveness_not_cleared_when_every_fill_rolls_back(self):
        all_records = {
            prompts.HOLE_BLOCK_PROTOCOL: [self._fill("t1", 1, 0, spliced=False)],
        }
        self.assertFalse(assembly_liveness(all_records)["cleared"])

    # -- selection_verdict ---------------------------------------------------

    def _stats_all(self, *, e1_pass):
        """`{block: {"e1_pass": ..., "cell_rate": 0.0, "draw_rate": 0.0}}` for
        every block, `e1_pass` a `{block: bool}` override."""
        base = {"cell_rate": 0.0, "draw_rate": 0.0, "e1_pass": False}
        stats = {b: dict(base) for b in
                 (prompts.HOLE_BLOCK_PROTOCOL, *CANDIDATE_BLOCKS, prompts.HOLE_BLOCK_CHECKER_HOLED)}
        for block, passed in e1_pass.items():
            stats[block]["e1_pass"] = passed
        return stats

    def test_no_block_clears_e1(self):
        stats = self._stats_all(e1_pass={})
        result = selection_verdict(stats, assembly_liveness({}))
        self.assertEqual(result["kind"], "no_launch_e1")

    def test_only_checker_holed_clears_e1_is_an_escalation(self):
        stats = self._stats_all(e1_pass={prompts.HOLE_BLOCK_CHECKER_HOLED: True})
        result = selection_verdict(stats, assembly_liveness({}))
        self.assertEqual(result["kind"], "escalate")

    def test_e1_clears_but_e2_does_not_blocks_stage_one(self):
        stats = self._stats_all(e1_pass={prompts.HOLE_BLOCK_EXEMPLAR: True})
        e2 = {"cleared": False, "hits": []}
        result = selection_verdict(stats, e2)
        self.assertEqual(result["kind"], "no_launch_e2")

    def test_selects_highest_cell_rate_among_e1_passers(self):
        stats = self._stats_all(
            e1_pass={prompts.HOLE_BLOCK_EXEMPLAR: True, prompts.HOLE_BLOCK_HOLE_REQUIRED: True})
        stats[prompts.HOLE_BLOCK_EXEMPLAR]["cell_rate"] = 0.25
        stats[prompts.HOLE_BLOCK_HOLE_REQUIRED]["cell_rate"] = 0.50
        e2 = {"cleared": True, "hits": [{"block": prompts.HOLE_BLOCK_HOLE_REQUIRED,
                                          "task": "t", "seed": 1, "round": 1}]}
        result = selection_verdict(stats, e2)
        self.assertEqual(result["kind"], "select")
        self.assertEqual(result["block"], prompts.HOLE_BLOCK_HOLE_REQUIRED)

    def test_ties_break_to_b1_over_b2(self):
        """§4.2: 'ties broken by draw rate, then by the order B1 < B2.'"""
        stats = self._stats_all(
            e1_pass={prompts.HOLE_BLOCK_EXEMPLAR: True, prompts.HOLE_BLOCK_HOLE_REQUIRED: True})
        for block in CANDIDATE_BLOCKS:
            stats[block]["cell_rate"] = 0.25
            stats[block]["draw_rate"] = 0.20
        e2 = {"cleared": True, "hits": [{"block": prompts.HOLE_BLOCK_EXEMPLAR,
                                          "task": "t", "seed": 1, "round": 1}]}
        result = selection_verdict(stats, e2)
        self.assertEqual(result["block"], prompts.HOLE_BLOCK_EXEMPLAR)

    def test_reference_block_b0_is_never_selected_even_if_it_clears_e1(self):
        """B0 is the pilot's reference (§2.2), not a Stage-1 candidate — a
        pathological pilot where only B0 clears E1 must not select it."""
        stats = self._stats_all(e1_pass={prompts.HOLE_BLOCK_PROTOCOL: True})
        result = selection_verdict(stats, assembly_liveness({}))
        self.assertNotEqual(result.get("block"), prompts.HOLE_BLOCK_PROTOCOL)
        self.assertEqual(result["kind"], "no_launch_e1")

    # -- load_block / apply_selection / main --------------------------------

    def test_load_block_missing_records_names_the_runlist(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit) as raised:
                load_block(prompts.HOLE_BLOCK_PROTOCOL, Path(directory))
            self.assertIn("elicitation-pilot-runlist.json", str(raised.exception))

    def test_apply_selection_patches_hole_block_and_revalidates(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "decomp2_holes.config.json"
            config_path.write_text(
                (Path(__file__).resolve().parent / "experiment"
                 / "decomp2_holes.config.json").read_text(encoding="utf-8"),
                encoding="utf-8")
            apply_selection(config_path, prompts.HOLE_BLOCK_HOLE_REQUIRED)
            patched = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(patched["hole_block"], prompts.HOLE_BLOCK_HOLE_REQUIRED)
            # Still a config `runner.Config` accepts and validates.
            runner.Config.load(config_path)

    def _write_pilot_run(self, runs_dir, block, records):
        block_dir = runs_dir / BLOCK_RUN_DIRS[block]
        block_dir.mkdir(parents=True)
        with (block_dir / "records.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def test_main_end_to_end_selects_and_applies(self):
        """A whole pilot on disk: B0 (reference) and B3 stay low, B1 clears E1
        with the higher cell rate, B2 clears E1 too but lower — `main` prints
        a `select` verdict for B1, exits 0, and (with `--apply`) patches a
        Stage-1 holes config to it."""
        with tempfile.TemporaryDirectory() as directory:
            runs_dir = Path(directory) / "runs"
            low = [self._skeleton("t", i, outcome="parse") for i in range(20)]
            self._write_pilot_run(runs_dir, prompts.HOLE_BLOCK_PROTOCOL, low)
            self._write_pilot_run(runs_dir, prompts.HOLE_BLOCK_CHECKER_HOLED, low)
            b2_rows = [self._skeleton("t", i, outcome=("typecheck" if i < 6 else "parse"))
                       for i in range(20)]  # 6/20 cells qualify = 30%, clears E1 but well below B1
            self._write_pilot_run(runs_dir, prompts.HOLE_BLOCK_HOLE_REQUIRED, b2_rows)
            b1_rows = ([self._skeleton(f"t{i}", 1) for i in range(8)]
                       + [self._skeleton(f"t{i}", 2) for i in range(8)])  # 16 cells, all qualify
            b1_rows.append(self._fill("t0", 1, 1, spliced=True))
            self._write_pilot_run(runs_dir, prompts.HOLE_BLOCK_EXEMPLAR, b1_rows)

            config_path = Path(directory) / "decomp2_holes.config.json"
            config_path.write_text(
                (Path(__file__).resolve().parent / "experiment"
                 / "decomp2_holes.config.json").read_text(encoding="utf-8"),
                encoding="utf-8")

            exit_code = pilot_select_main([
                "--runs-dir", str(runs_dir), "--apply", str(config_path)])
            self.assertEqual(exit_code, EXIT_SELECT)
            patched = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(patched["hole_block"], prompts.HOLE_BLOCK_EXEMPLAR)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
