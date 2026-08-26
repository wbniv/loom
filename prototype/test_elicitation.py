"""Tests for `docs/plans/2026-08-26-hole-elicitation.md` deliverable 3 — the
`exemplar` block (B1), its block-selection surface, and §4.7 checks 1b, 1c
and 9.

Later deliverables in the same plan (B2 `hole-required`, B3 `checker-holed`)
share this module rather than each starting their own — see the plan's §2.2
for what each block is and §4.7 for what each numbered check pins.
"""

from __future__ import annotations

import inspect
import re
import unittest

import corpus_registry
from experiment import prompts
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
