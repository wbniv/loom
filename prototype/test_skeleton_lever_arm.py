"""Tests for `docs/plans/2026-08-28-skeleton-lever.md` §7.4 deliverables 3,
4 and 6 — the two `skel_*` configs and their runlist, and
`experiment/skeleton_lever_compare.py`, which executes §6's decision rows
rather than judging them. One file for one arm, the way `test_legibility_arm.py`
combines its own configs/runlist/compare tests and `test_scale_arm.py` combines
its configs/compare tests.

**Deliverable 3.** The configs are pinned by *difference*: §3.1 says the two
arms are "one config field" apart — `output_dir` and `generation_protocol` —
so the test asserts exactly that between the two shipped files, the same
byte-copy-with-pinned-difference discipline `test_legibility_arm.py`'s
`LegibilityArmConfigs` and `test_scale_arm.py`'s `ScaleArmConfigs` use,
rather than re-listing every field (which would pass happily if the files
drifted apart in some *other* field). §3.1's draw-0 byte-identity claim and
§3.2's note-byte claim are checked directly against the landed
`prompts.build_prompt` / `evaluate.narrowing_note`, not re-derived.

**Deliverable 6.** The runlist names both shipped configs and their
`output_dir`s agree.

**Deliverable 4.** `skeleton_lever_compare` is driven with synthesized
records rather than a live run, the way `test_legibility_arm.py` drives
`legibility_compare`: each of §6's six exit codes (0, 2, 3, 4, 5, 6) is made
to fire from records built to trigger that row — §7.2 check 8's own
requirement, executed here as a unit test rather than only read off the stub
check's stdout. Every synthetic record's `source` is a real task's own
`heldout_gold.GOLD_TERMS` surface (or a mismatched one), so `type_exact` —
imported from `decomposition_analysis`, never re-derived — evaluates it for
real rather than being handed a pre-computed boolean.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import typecheck
from experiment import skeleton_lever_compare as slc
from experiment.evaluate import narrowing_note, run_funnel
from experiment.heldout_gold import GOLD_TERMS
from experiment.prompts import HELD_OUT_TASKS, REGIME_HELD_OUT, build_prompt
from experiment.resolver import ExperimentResolver
from experiment.runner import Config

EXPERIMENT = Path(__file__).resolve().parent / "experiment"
TASK_IDS = [t.task_id for t in HELD_OUT_TASKS]

#: (arm config, expected output_dir, expected generation_protocol) -- the
#: two shipped arms, deliverable 3.
ARM_CONFIGS = (
    ("skel_whole14.config.json", "runs/skel-whole14", "whole"),
    ("skel_redraft14.config.json", "runs/skel-redraft14", "redraft"),
)


def _load(name: str) -> dict:
    return json.loads((EXPERIMENT / name).read_text(encoding="utf-8"))


class SkeletonLeverConfigs(unittest.TestCase):
    def test_configs_differ_by_exactly_output_dir_and_generation_protocol(self):
        whole = _load("skel_whole14.config.json")
        redraft = _load("skel_redraft14.config.json")
        changed = {"output_dir", "generation_protocol"}
        self.assertEqual(
            {k: v for k, v in whole.items() if k not in changed},
            {k: v for k, v in redraft.items() if k not in changed},
            "§3.1: the arms are one config field apart -- output_dir and "
            "generation_protocol, and nothing else",
        )
        self.assertEqual(whole["generation_protocol"], "whole")
        self.assertEqual(redraft["generation_protocol"], "redraft")
        self.assertEqual(whole["output_dir"], "runs/skel-whole14")
        self.assertEqual(redraft["output_dir"], "runs/skel-redraft14")

    def test_configs_validate(self):
        for name, _, _ in ARM_CONFIGS:
            with self.subTest(arm=name):
                Config(**_load(name))

    def test_configs_keep_amendment_a1_and_plan_pinned_fields(self):
        """§3.1's "everything else is identical" clause, on the fields the
        arm's whole comparison would silently stop meaning anything
        without, plus Amendment A1's 32-cells/arm sizing (8 tasks x
        seeds 1-4)."""
        for name, _, _ in ARM_CONFIGS:
            with self.subTest(arm=name):
                cfg = Config(**_load(name))
                self.assertEqual(cfg.conditions, ["gbnf+typemask"])
                self.assertEqual(cfg.regimes, ["held_out"])
                self.assertTrue(cfg.leave_one_out)
                self.assertEqual(cfg.pruners, ["goal-type", "de-bruijn", "ref-hash"])
                self.assertEqual(cfg.seeds, [1, 2, 3, 4])
                self.assertEqual(len(cfg.seeds) * len(TASK_IDS), 32)
                self.assertEqual(cfg.token_budget_per_task, 4608)
                self.assertEqual(cfg.address_book, "full")
                self.assertFalse(cfg.include_generated)
                # narrowing_note_render is not overridden by either arm -- it
                # carries the default (surface), which is §3.2's claim.
                self.assertNotIn("narrowing_note_render", _load(name))
                self.assertEqual(cfg.narrowing_note_render, typecheck.NARROWING_NOTE_SURFACE)

    def test_draw_0_prompt_bytes_are_equal_across_arms_for_all_eight_tasks(self):
        """§3.1: draw 0 of every cell is byte-identical across the two arms --
        `build_prompt`'s own docstring pins this; `redraft` differs from
        `whole` only in the runner's loop, never in the prompt."""
        resolver = ExperimentResolver()
        whole = Config(**_load("skel_whole14.config.json"))
        redraft = Config(**_load("skel_redraft14.config.json"))
        for task in HELD_OUT_TASKS:
            with self.subTest(task=task.task_id):
                built_whole = build_prompt(
                    task, REGIME_HELD_OUT, resolver,
                    leave_one_out=whole.leave_one_out,
                    address_book=whole.address_book,
                    generation_protocol=whole.generation_protocol)
                built_redraft = build_prompt(
                    task, REGIME_HELD_OUT, resolver,
                    leave_one_out=redraft.leave_one_out,
                    address_book=redraft.address_book,
                    generation_protocol=redraft.generation_protocol)
                self.assertEqual(built_whole, built_redraft)

    def test_runlist_names_both_shipped_configs(self):
        entries = json.loads(
            (EXPERIMENT / "skeleton-lever-runlist.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [e["run_id"] for e in entries], ["skel-redraft14", "skel-whole14"])
        for entry in entries:
            with self.subTest(run=entry["run_id"]):
                config = EXPERIMENT / Path(entry["config_key"]).name
                self.assertTrue(config.is_file(), f"runlist names a missing {config}")
                self.assertEqual(_load(config.name)["output_dir"], entry["output_dir"])


# --------------------------------------------------------------------------
# Deliverable 3, §3.2 -- Arm B's note is `narrowing_note`, unmodified,
# rendered by the canonical (surface) renderer, at every funnel layer.
# --------------------------------------------------------------------------

#: A synthetic 64-hex-digit hash `references` will never resolve.
_UNKNOWN_HASH = "0x" + "ab" * 32

#: One scripted draft per rejecting layer, `evaluate.LAYERS` order. `accepted`
#: is not a rejection and carries no note (`narrowing_note` returns "").
_LAYER_DRAFTS = {
    "parse": "(def Bool (lam Bool (if (var 0)",
    "scope": "(def (fn Bool () Bool) (lam Bool (var 3)))",
    "references": f"(def (data {_UNKNOWN_HASH} ()) (hole (data {_UNKNOWN_HASH} ()) ()))",
    "typecheck": "(def Bool (lit i64 1))",
}


class NoteByteClaim(unittest.TestCase):
    """§3.2: "Arm B's note is `evaluate.narrowing_note` unchanged, rendered
    by the landed `8ed72cd` canonical renderer" -- checked at every rejecting
    funnel layer, not just typecheck."""

    def setUp(self):
        self.resolver = ExperimentResolver()

    def test_note_is_narrowing_note_unmodified_at_every_layer(self):
        for layer, draft in _LAYER_DRAFTS.items():
            with self.subTest(layer=layer):
                funnel = run_funnel(draft, self.resolver)
                self.assertEqual(funnel.outcome, layer)
                note = narrowing_note(funnel)
                self.assertNotEqual(note, "")
                self.assertIn(f"rejected by the {layer} layer", note)
                # No renderer transformation happens between `narrowing_note`'s
                # output and what a redraft round would carry forward -- Arm B's
                # config sets no `narrowing_note_render`, so the contextvar
                # default (surface) is what produced `funnel.error_message`
                # above, and `narrowing_note` adds nothing but the fixed
                # preface/suffix text around it (asserted, not assumed).
                self.assertTrue(note.startswith("The previous answer was rejected by the "))
                self.assertTrue(note.endswith("Write a different definition that avoids this."))
                self.assertIn(funnel.error_message, note)

    def test_accepted_draft_carries_no_note(self):
        funnel = run_funnel(GOLD_TERMS["heldout/list/sum"], self.resolver)
        self.assertTrue(funnel.accepted)
        self.assertEqual(narrowing_note(funnel), "")


# --------------------------------------------------------------------------
# `skeleton_lever_compare` end to end, against synthesized run directories
# --------------------------------------------------------------------------

def _cells(n: int, hits: int, *, seed_start: int = 1, draws_per_cell: int = 8,
          extra_non_type_exact: int = 2, role: str = "whole") -> list[dict]:
    """`n` cells cycling through the 8 held-out tasks, seeds advancing every
    8 cells (so `n=32` reproduces Amendment A1's 8 tasks x seeds 1-4 exactly).
    The first `hits` cells have every one of their `draws_per_cell` type-exact
    draws (source = the task's own gold surface) funnel-accepted; the rest
    have none. Every cell also carries `extra_non_type_exact` draws whose
    source is a *different* task's gold surface (never type-exact, always
    rejected) -- E2's denominator, never counted by E1.
    """
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
                "funnel_outcome": "accepted" if accepted else "typecheck",
            })
        for d in range(draws_per_cell, draws_per_cell + extra_non_type_exact):
            rows.append({
                "task": task, "seed": cell_seed, "draw": d, "role": role,
                "source": GOLD_TERMS[other],
                "funnel_outcome": "typecheck",
            })
    return rows


def _matching_anchor(whole_rows: list[dict]) -> list[dict]:
    """A synthetic `scale14-b0` that reproduces `whole_rows`' own seeds-1-2
    subset exactly (relabeled `role: "candidate"`, the anchor's own
    population per `effective_records`), so C1' trivially passes -- every
    test below except the dedicated C1'-failure test wants that."""
    return [dict(row, role="candidate")
            for row in whole_rows if row["seed"] in slc.C1_OVERLAP_SEEDS]


class SkeletonLeverCompareVerdicts(unittest.TestCase):
    """Each of §6's six exit codes, made to fire from synthesized records."""

    def _run(self, redraft, whole, anchor=None):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            for run_id, rows in {
                "skel-redraft14": redraft, "skel-whole14": whole,
                "scale14-b0": anchor if anchor is not None else _matching_anchor(whole),
            }.items():
                (runs / run_id).mkdir(parents=True)
                with (runs / run_id / "records.jsonl").open("w", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = slc.main(runs_dir=runs)
            return rc, out.getvalue()

    def test_row_1_fires_when_e1_clears(self):
        rc, out = self._run(_cells(32, 28), _cells(32, 4))
        self.assertEqual(rc, 0)
        self.assertIn("§6 row 1", out)

    def test_row_2_fires_on_e1_null_with_sufficient_denominator(self):
        rc, out = self._run(_cells(32, 16), _cells(32, 15))
        self.assertEqual(rc, 2)
        self.assertIn("§6 row 2", out)

    def test_row_3_fires_when_e2_diverges(self):
        # Same E1 shape (identical hit counts, so E1 alone would be null),
        # but the `whole` arm's type-exact *share* is diluted by a much
        # larger non-type-exact tail -- an E2 divergence far past 5 points.
        redraft = _cells(32, 16, extra_non_type_exact=2)
        whole = _cells(32, 16, extra_non_type_exact=40)
        rc, out = self._run(redraft, whole)
        self.assertEqual(rc, 3)
        self.assertIn("§6 row 3", out)

    def test_row_4_fires_when_e1_denominator_is_starved(self):
        # draws_per_cell=2: 32 cells x 2 = 64 type-exact draws / 32 cells =
        # 2.0 eligible/cell/arm, under the 4.5 floor, for both arms equally
        # (so E2 does not diverge and row 3 does not pre-empt this).
        redraft = _cells(32, 16, draws_per_cell=2)
        whole = _cells(32, 15, draws_per_cell=2)
        rc, out = self._run(redraft, whole)
        self.assertEqual(rc, 4)
        self.assertIn("§6 row 4", out)
        self.assertIn("STARVED", out)

    def test_row_4_fires_when_records_are_entirely_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = slc.main(runs_dir=Path(tmp))
            self.assertEqual(rc, 4)
            self.assertIn("cannot decide", out.getvalue())

    def test_row_5_fires_when_e1_is_significant_in_reverse(self):
        rc, out = self._run(_cells(32, 4), _cells(32, 28))
        self.assertEqual(rc, 5)
        self.assertIn("REVERSE", out)
        self.assertIn("§6 row 5", out)

    def test_row_6_fires_when_c1_prime_fails(self):
        whole = _cells(32, 16)
        # An anchor whose acceptance rate sits nowhere near `whole`'s
        # seeds-1-2 subset (16/32 hit cells -> ~50% acceptance): a tight,
        # far-off anchor at 5%.
        anchor = _cells(200, 10, draws_per_cell=1, extra_non_type_exact=0,
                        seed_start=1, role="candidate")
        rc, out = self._run(_cells(32, 16), whole, anchor=anchor)
        self.assertEqual(rc, 6)
        self.assertIn("§6 row 6", out)
        self.assertIn("C1' FAILS", out)

    def test_c1_prime_pooled_figures_are_computed_live_not_pasted(self):
        """The anchor's own funnel-acceptance/type-exact figures must reflect
        whatever `scale14-b0` records were actually loaded, so a
        test-supplied anchor controls C1' exactly rather than a hardcoded
        constant being consulted instead."""
        whole = _cells(32, 16)
        anchor = _matching_anchor(whole)
        expected_n = len(anchor)
        rc, out = self._run(_cells(32, 16), whole, anchor=anchor)
        self.assertIn(f"n={expected_n}", out)


if __name__ == "__main__":
    unittest.main()
