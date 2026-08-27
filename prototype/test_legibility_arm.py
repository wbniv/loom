"""Tests for `docs/plans/2026-08-27-feedback-legibility-arm.md` §3
deliverables 4 and 6 — the two `legib_*` configs and their runlist, and
`experiment/legibility_compare.py`, which executes §6's decision rows rather
than judging them. Combined in one file the way `test_scale_arm.py` combines
its own deliverable 2 (configs) and deliverable 5 (compare script) — one
arm, one test file.

**Deliverable 4.** The configs are pinned by *difference*: deliverable 4 says
they are byte-copies of `decomp-redraft.config.json` with only `output_dir`
and `narrowing_note_render` changed, so the test asserts exactly that rather
than re-listing every field — a re-listing would pass happily if the source
config drifted underneath. Same discipline as `test_scale_arm.py`'s
`ScaleArmConfigs` for the model-scale arm's `scale14_*` pair, which named this
gap for its own deliverable 3.

**Deliverable 6.** `legibility_compare` is driven with synthesized records
rather than a live run, the way `test_scale_arm.py` drives `scale_compare`:
each of §6's rows is made to fire, plus the missing-records exit and the C1
rider. `RepairsLocallyPredicate` and `PerCellCounts` test the shared
predicate module (`experiment/legibility_endpoints.py`) in isolation — the
one definition `legibility_compare.py` and `legibility_power.py` both import,
so L1's meaning cannot drift between the pre-registration and the verdict.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from experiment import legibility_compare as lc
from experiment.legibility_endpoints import per_cell_counts, repairs_locally
from experiment.runner import Config

EXPERIMENT = Path(__file__).resolve().parent / "experiment"

#: (arm config, expected output_dir, expected narrowing_note_render) — every
#: arm is a copy of the same source, `decomp-redraft.config.json` (plan §3
#: deliverable 4).
SOURCE = "decomp-redraft.config.json"
COPY_PAIRS = (
    ("legib_legible.config.json", "runs/legib-legible", "surface"),
    ("legib_repr.config.json", "runs/legib-repr", "repr"),
)


def _load(name: str) -> dict:
    return json.loads((EXPERIMENT / name).read_text(encoding="utf-8"))


class LegibilityArmConfigs(unittest.TestCase):
    def test_configs_differ_from_decomp_redraft_only_by_output_dir_and_render(self):
        src = _load(SOURCE)
        for arm, expected_out, expected_render in COPY_PAIRS:
            with self.subTest(arm=arm):
                dst = _load(arm)
                self.assertEqual(dst["output_dir"], expected_out)
                self.assertEqual(dst["narrowing_note_render"], expected_render)
                changed = {"output_dir", "narrowing_note_render"}
                self.assertEqual(
                    {k: v for k, v in src.items() if k not in changed},
                    {k: v for k, v in dst.items() if k not in changed},
                    "the arm config must be a byte-copy of decomp-redraft.config.json "
                    "apart from output_dir and narrowing_note_render "
                    "(plan §3 deliverable 4)",
                )
                # `decomp-redraft.config.json` predates the `narrowing_note_render`
                # field, so it carries no key for it at all — confirmed here so
                # the diff above cannot be vacuously true if the source ever
                # grows the key with some other value.
                self.assertNotIn("narrowing_note_render", src)

    def test_configs_validate(self):
        for arm, _, _ in COPY_PAIRS:
            with self.subTest(arm=arm):
                Config(**_load(arm))

    def test_configs_keep_the_pinned_comparison_fields(self):
        """§2.1's "everything else is a byte-copy" clause, on the fields the
        arm's whole comparison would silently stop meaning anything without."""
        for arm, _, _ in COPY_PAIRS:
            with self.subTest(arm=arm):
                cfg = Config(**_load(arm))
                self.assertEqual(cfg.generation_protocol, "redraft")
                self.assertEqual(cfg.conditions, ["gbnf+typemask"])
                self.assertEqual(cfg.regimes, ["held_out"])
                self.assertTrue(cfg.leave_one_out)
                self.assertEqual(cfg.pruners, ["goal-type", "de-bruijn", "ref-hash"])
                self.assertEqual(cfg.seeds, [1, 2, 3, 4, 5, 6, 7, 8])
                self.assertEqual(cfg.token_budget_per_task, 4608)
                self.assertEqual(cfg.max_tokens_per_draw, 768)
                self.assertEqual(cfg.address_book, "full")

    def test_runlist_names_both_shipped_configs(self):
        entries = _load("legibility-runlist.json")
        self.assertEqual(
            [e["run_id"] for e in entries], ["legib-legible", "legib-repr"])
        for entry in entries:
            with self.subTest(run=entry["run_id"]):
                config = EXPERIMENT / Path(entry["config_key"]).name
                self.assertTrue(config.is_file(), f"runlist names a missing {config}")
                self.assertEqual(_load(config.name)["output_dir"], entry["output_dir"])


# --------------------------------------------------------------------------
# The shared predicate — the one definition L1 cannot drift on
# --------------------------------------------------------------------------

class RepairsLocallyPredicate(unittest.TestCase):
    """§2.2's L1 predicate, in isolation: does a narrowed draw following a
    rejected one count as a local repair of the note it was handed?"""

    def test_accepted_outright_is_always_local(self):
        previous = {"funnel_outcome": "typecheck", "error_path": "a.b"}
        row = {"funnel_outcome": "accepted", "error_path": None}
        self.assertTrue(repairs_locally(previous, row))

    def test_failure_path_at_or_below_the_noted_path_is_local(self):
        previous = {"funnel_outcome": "typecheck", "error_path": "a.b"}
        row = {"funnel_outcome": "typecheck", "error_path": "a.b.c"}
        self.assertTrue(repairs_locally(previous, row))

    def test_exact_same_path_is_local(self):
        previous = {"funnel_outcome": "typecheck", "error_path": "a.b"}
        row = {"funnel_outcome": "typecheck", "error_path": "a.b"}
        self.assertTrue(repairs_locally(previous, row))

    def test_failure_path_diverging_from_the_noted_path_is_not_local(self):
        previous = {"funnel_outcome": "typecheck", "error_path": "a.b"}
        row = {"funnel_outcome": "typecheck", "error_path": "a.z"}
        self.assertFalse(repairs_locally(previous, row))

    def test_shorter_unrelated_path_is_not_local(self):
        previous = {"funnel_outcome": "typecheck", "error_path": "a.b"}
        row = {"funnel_outcome": "typecheck", "error_path": "z"}
        self.assertFalse(repairs_locally(previous, row))

    def test_empty_noted_path_is_local_by_construction(self):
        """§2.2's fixed degenerate case: an empty noted path has length 0,
        so every successor counts as local, whatever it lands on."""
        previous = {"funnel_outcome": "typecheck", "error_path": ""}
        row = {"funnel_outcome": "typecheck", "error_path": "wholly.unrelated"}
        self.assertTrue(repairs_locally(previous, row))

    def test_missing_error_path_key_behaves_like_empty(self):
        previous = {"funnel_outcome": "typecheck"}
        row = {"funnel_outcome": "typecheck", "error_path": "x"}
        self.assertTrue(repairs_locally(previous, row))


class PerCellCounts(unittest.TestCase):
    """The cell-grouping walk both scripts read L1/L2 off."""

    def test_l1_denominator_is_narrowed_draws_after_a_rejection_only(self):
        records = [
            {"task": "t", "seed": 1, "round": 0, "narrowed": False,
             "funnel_outcome": "accepted", "error_path": None},
            # `narrowed` is defensively True here even though the predecessor
            # was itself accepted (which never legitimately happens --
            # `narrowing_note` returns "" on acceptance -- but the walk
            # guards it anyway); it must not enter L1.
            {"task": "t", "seed": 1, "round": 1, "narrowed": True,
             "funnel_outcome": "accepted", "error_path": None},
        ]
        counts = per_cell_counts(records)
        self.assertEqual(counts["L1"], {})
        self.assertEqual(counts["L2"], {("t", 1): [2, 2]})

    def test_l1_and_l2_over_two_cells(self):
        records = [
            {"task": "a", "seed": 1, "round": 0, "narrowed": False,
             "funnel_outcome": "typecheck", "error_path": "x.y"},
            {"task": "a", "seed": 1, "round": 1, "narrowed": True,
             "funnel_outcome": "typecheck", "error_path": "x.y.z"},
            {"task": "b", "seed": 1, "round": 0, "narrowed": False,
             "funnel_outcome": "typecheck", "error_path": "x.y"},
            {"task": "b", "seed": 1, "round": 1, "narrowed": True,
             "funnel_outcome": "typecheck", "error_path": "q"},
        ]
        counts = per_cell_counts(records)
        self.assertEqual(counts["L1"], {("a", 1): [1, 1], ("b", 1): [1, 0]})
        self.assertEqual(counts["L2"], {("a", 1): [2, 0], ("b", 1): [2, 0]})

    def test_rows_are_sorted_by_round_before_pairing(self):
        """A `records.jsonl` interleaves cells in draw order, not within one
        -- the walk must not assume the input list is already per-cell
        ordered."""
        records = [
            {"task": "t", "seed": 1, "round": 1, "narrowed": True,
             "funnel_outcome": "typecheck", "error_path": "a.b.c"},
            {"task": "t", "seed": 1, "round": 0, "narrowed": False,
             "funnel_outcome": "typecheck", "error_path": "a.b"},
        ]
        counts = per_cell_counts(records)
        self.assertEqual(counts["L1"], {("t", 1): [1, 1]})


# --------------------------------------------------------------------------
# `legibility_compare` end to end, against synthesized run directories
# --------------------------------------------------------------------------

def _cells(n: int, hits: int, task_prefix: str, *, seed: int = 1,
          accepted: int = 0) -> list[dict]:
    """`n` two-round `(task_prefix{i}, seed)` cells. Round 0 always rejects
    (typecheck, path `a.b`) and round 1 is narrowed: the first `accepted`
    cells' round 1 is accepted outright (an L1 *and* L2 hit), the next
    `hits - accepted` land at or below the noted path without being accepted
    (an L1-only hit), and the remainder miss both.
    """
    rows = []
    for i in range(n):
        task = f"{task_prefix}{i}"
        rows.append({"task": task, "seed": seed, "round": 0, "narrowed": False,
                     "funnel_outcome": "typecheck", "error_path": "a.b",
                     "role": "whole"})
        if i < accepted:
            outcome, path = "accepted", None
        elif i < hits:
            outcome, path = "typecheck", "a.b.c"
        else:
            outcome, path = "typecheck", "z"
        rows.append({"task": task, "seed": seed, "round": 1, "narrowed": True,
                     "funnel_outcome": outcome, "error_path": path,
                     "role": "whole"})
    return rows


class LegibilityCompareVerdicts(unittest.TestCase):
    """Each of §6's rows, made to fire from synthesized records."""

    def _run(self, legible, repr_, banked=None):
        """Write records for both live blocks plus the banked calibration
        anchor, point `legibility_compare` at them, and return its exit code
        and captured stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            for run_id, rows in {
                "legib-legible": legible, "legib-repr": repr_,
                "decomp-redraft": banked or _cells(64, 25, "b", accepted=10),
            }.items():
                (runs / run_id).mkdir(parents=True)
                with (runs / run_id / "records.jsonl").open("w", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = lc.main(runs_dir=runs)
            return rc, out.getvalue()

    def test_row_1_fires_when_l1_clears(self):
        # 18/20 = 90% vs 2/20 = 10%: comfortably significant at seed 0.
        rc, out = self._run(_cells(20, 18, "t"), _cells(20, 2, "t"))
        self.assertEqual(rc, 0)
        self.assertIn("§6 row 1", out)

    def test_row_2_fires_on_l1_null_with_l2_rr_at_or_above_threshold(self):
        # Both arms at 40% L1 (paired-null); L2 15% vs 7.5% is RR 2.0.
        leg = _cells(20, 8, "t", accepted=6)
        rep = _cells(20, 8, "t", accepted=3)
        rc, out = self._run(leg, rep)
        self.assertEqual(rc, 2)
        self.assertIn("§6 row 2", out)

    def test_row_3_fires_on_l1_null_with_l2_rr_below_threshold(self):
        # Both arms identical on L1 and L2 -- RR 1.0, well under 1.5x.
        leg = _cells(20, 8, "t", accepted=4)
        rep = _cells(20, 8, "t", accepted=4)
        rc, out = self._run(leg, rep)
        self.assertEqual(rc, 3)
        self.assertIn("§6 row 3", out)

    def test_row_4_fires_when_l1_is_significant_in_reverse(self):
        # repr 90% vs legible 10%: the opposite-direction gate.
        rc, out = self._run(_cells(20, 2, "t"), _cells(20, 18, "t"))
        self.assertEqual(rc, 5)
        self.assertIn("REVERSE", out)
        self.assertIn("§6 row 4", out)

    def test_missing_records_exit_4_rather_than_deciding(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = lc.main(runs_dir=Path(tmp))
            self.assertEqual(rc, 4)
            self.assertIn("cannot decide", out.getvalue())

    def test_c1_out_is_reported_but_does_not_change_the_verdict_row(self):
        """A `repr` arm rate outside the banked Wilson interval is a
        harness-drift finding (§2.4), not a reason to pick a different row:
        the primary comparison stays within-run."""
        # repr's L1 rate (90%) sits far outside the banked anchor's interval,
        # but L1 is still null between the two live arms, so row 3 fires.
        leg = _cells(20, 18, "t", accepted=0)
        rep = _cells(20, 18, "t", accepted=0)
        banked = _cells(64, 25, "b", accepted=10)  # banked L1 ~ 39%
        rc, out = self._run(leg, rep, banked=banked)
        self.assertEqual(rc, 3)
        self.assertIn("C1 is OUT", out)
        self.assertIn("§6 row 3", out)

    def test_narrowed_only_secondary_is_reported(self):
        rc, out = self._run(_cells(20, 8, "t", accepted=4),
                            _cells(20, 8, "t", accepted=4))
        self.assertIn("secondary, narrowed draws only", out)

    def test_banked_c1_figures_are_computed_live_not_pasted(self):
        """The banked anchor's own L1/L2 rate must reflect whatever
        `decomp-redraft` records were actually loaded, so a test-supplied
        banked run controls C1 exactly rather than being ignored in favour
        of a hardcoded constant."""
        banked = _cells(10, 5, "b", accepted=0)  # L1 = 5/10 = 50%
        rc, out = self._run(_cells(20, 8, "t", accepted=4),
                            _cells(20, 8, "t", accepted=4), banked=banked)
        self.assertIn("L1  banked 5/10 = 50.00%", out)


if __name__ == "__main__":
    unittest.main()
