"""Tests for `docs/plans/2026-08-27-model-scale-arm.md` deliverables 2 and 5 —
the two `scale14_*` configs and their runlist, and `experiment/scale_compare.py`,
which executes §6's decision rows rather than judging them.

The configs are pinned by *difference*: §3 deliverable 2 says they are
byte-copies of the pilot's `pilot_b0` / `pilot_b2` with only `output_dir`
changed, so the test asserts exactly that rather than re-listing every field —
a re-listing would pass happily if the pilot's own settings drifted underneath.

`scale_compare` is driven with synthesized records rather than a live run, the
way `pilot_select`'s §4.7 check 7e drives the E1/E2 path with a scripted stub:
each of §6's three rows is made to fire, plus the fourth row's E2 rider and the
missing-records exit.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiment import scale_compare
from experiment.runner import ROLE_FILL, ROLE_SKELETON, SPLICE_SPLICED, Config

EXPERIMENT = Path(__file__).resolve().parent / "experiment"

#: The pilot config each arm config is a copy of (plan §3 deliverable 2).
COPY_PAIRS = (
    ("pilot_b0.config.json", "scale14_b0.config.json", "runs/scale14-b0"),
    ("pilot_b2.config.json", "scale14_b2.config.json", "runs/scale14-b2"),
)


def _load(name: str) -> dict:
    return json.loads((EXPERIMENT / name).read_text(encoding="utf-8"))


class ScaleArmConfigs(unittest.TestCase):
    def test_configs_differ_from_their_pilot_source_only_by_output_dir(self):
        for source, arm, expected_out in COPY_PAIRS:
            with self.subTest(arm=arm):
                src, dst = _load(source), _load(arm)
                self.assertEqual(dst["output_dir"], expected_out)
                self.assertEqual(
                    {k: v for k, v in src.items() if k != "output_dir"},
                    {k: v for k, v in dst.items() if k != "output_dir"},
                    "the arm config must be a byte-copy of its pilot source "
                    "apart from output_dir (plan §3 deliverable 2)",
                )

    def test_configs_validate(self):
        for _, arm, _ in COPY_PAIRS:
            with self.subTest(arm=arm):
                Config(**_load(arm))

    def test_configs_keep_the_pinned_comparison_fields(self):
        """§2's "held byte-identical to the pilot" clause, on the fields the
        §2.1 comparison would silently stop meaning anything without."""
        for _, arm, _ in COPY_PAIRS:
            with self.subTest(arm=arm):
                cfg = Config(**_load(arm))
                self.assertEqual(cfg.fill_gate, "well-scoped")
                self.assertEqual(cfg.seeds, [1, 2])
                self.assertEqual(cfg.pruners, ["goal-type", "de-bruijn", "ref-hash"])
                self.assertEqual(cfg.token_budget_per_task, 4608)
                self.assertEqual(cfg.generation_protocol, "holes")

    def test_runlist_names_both_shipped_configs(self):
        entries = _load("scale14-runlist.json")
        self.assertEqual([e["run_id"] for e in entries], ["scale14-b0", "scale14-b2"])
        for entry in entries:
            with self.subTest(run=entry["run_id"]):
                config = EXPERIMENT / Path(entry["config_key"]).name
                self.assertTrue(config.is_file(), f"runlist names a missing {config}")
                self.assertEqual(_load(config.name)["output_dir"], entry["output_dir"])


def _skeletons(n_draws: int, n_qualify: int, task_prefix: str = "t") -> list[dict]:
    """`n_draws` skeleton records of which `n_qualify` meet `block_stats`'s
    fill-reaching predicate. One task per record so cell counts stay legible."""
    rows = []
    for i in range(n_draws):
        qualifies = i < n_qualify
        rows.append({
            "role": ROLE_SKELETON,
            "funnel_outcome": "typecheck" if qualifies else "parse",
            "bare_hole_body": False,
            "holes_fillable": 1 if qualifies else 0,
            "task": f"{task_prefix}{i % 8}",
            "seed": 1 + (i % 2),
        })
    return rows


class ScaleCompareVerdicts(unittest.TestCase):
    """Each of §6's rows, made to fire from synthesized records."""

    def _run(self, b0, b2, banked=(174, 10), fills=(0, 0)):
        """Write records for both arm blocks plus the banked 7B run, point
        `scale_compare` at them, and return its exit code."""
        n_fill, n_spliced = fills
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            for run_id, (draws, qualify) in {
                "scale14-b0": b0, "scale14-b2": b2, "pilot-b2": banked,
            }.items():
                rows = _skeletons(draws, qualify)
                if run_id == "scale14-b2":
                    rows += [
                        {"role": ROLE_FILL, "task": "t0", "seed": 1, "round": 1,
                         "splice_outcome": SPLICE_SPLICED if i < n_spliced else "fill-rejected"}
                        for i in range(n_fill)
                    ]
                (runs / run_id).mkdir(parents=True)
                with (runs / run_id / "records.jsonl").open("w", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
            original = scale_compare.RUNS
            scale_compare.RUNS = runs
            try:
                return scale_compare.main()
            finally:
                scale_compare.RUNS = original

    def test_row_1_fires_when_e1_clears(self):
        # 40/174 = 23%, comfortably clear of the 10% Wilson-lower bar.
        self.assertEqual(self._run(b0=(174, 5), b2=(174, 40)), 0)

    def test_row_2_fires_on_a_doubling_that_misses_e1(self):
        # 22/174 = 12.6%: over the 11.5% descriptive threshold, but its
        # Wilson lower bound sits under 10%, so E1 still fails.
        rc = self._run(b0=(174, 5), b2=(174, 22))
        self.assertEqual(rc, 2)

    def test_row_3_fires_when_b2_is_below_the_threshold(self):
        # 12/174 = 6.9%: above the banked 7B rate but under 11.5%.
        self.assertEqual(self._run(b0=(174, 3), b2=(174, 12)), 3)

    def test_row_2_requires_the_reference_to_sit_below_b2(self):
        """A doubling that the no-pressure reference matches is not evidence
        that *pressure* did anything, so §6 row 2 must not fire on it.

        Both blocks are set just under E1 (23/174 and 22/174 clear the 11.5 %
        descriptive threshold but their Wilson lower bounds sit below 10 %),
        so the only thing separating row 2 from row 3 here is the ordering.
        """
        self.assertEqual(self._run(b0=(174, 23), b2=(174, 22)), 3)

    def test_missing_records_exit_4_rather_than_deciding(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = scale_compare.RUNS
            scale_compare.RUNS = Path(tmp)
            try:
                self.assertEqual(scale_compare.main(), 4)
            finally:
                scale_compare.RUNS = original

    def test_e2_rider_does_not_change_the_row_that_fires(self):
        """E2 clearing while E1 fails is reported (§6 row 4) but buys nothing
        on its own — the exit code must still be the stop row's."""
        self.assertEqual(self._run(b0=(174, 3), b2=(174, 12), fills=(5, 1)), 3)


if __name__ == "__main__":
    unittest.main()
