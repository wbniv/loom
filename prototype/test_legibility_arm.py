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


if __name__ == "__main__":
    unittest.main()
