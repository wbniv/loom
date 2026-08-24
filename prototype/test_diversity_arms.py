"""The diversity-harvest arms, as shipped: their configs and their stores.

`docs/plans/2026-08-23-diversity-harvest.md` verification steps 3, 4 and 6 are
what this file automates. It is the sibling of
`test_harvest.FollowUpConfigTest`, which does the same job for the corpus loop's
two arms, and it exists separately because the property it guards is different:
the corpus-loop arms differ in **one flag over one store**, while these differ
in **which objects are in the store at all**.

Two populations of test, and the split matters:

* **Config shape** needs nothing on disk. Four shipped configs must agree about
  everything except which store they read and where they write, or the A/B is
  measuring transport instead of selection.
* **Store contents** need the built stores, which are gitignored build products
  (`task store:diverse` / `store:sizematch`). Those tests **skip** when the
  stores are absent, the same way `test_store`'s equivalence tests skip without
  a seeded `.loom-store`. Skipping is honest here: the alternative is a fixture
  that re-implements the selector, which would assert that the code agrees with
  itself.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import harvest_select
from experiment import prompts, runner

CONFIG_DIR = Path(__file__).resolve().parent / "experiment"
REPO_ROOT = Path(__file__).resolve().parent.parent

DIVERSE_STORE = REPO_ROOT / ".loom-store-diverse" / "export-resolver.json"
SIZEMATCH_STORE = REPO_ROOT / ".loom-store-sizematch" / "export-resolver.json"
CURATED_STORE = REPO_ROOT / ".loom-store" / "export-resolver.json"

#: The count both new arms land, and the number the plan's control arm is named
#: for. Asserted rather than read from the store, because "both arms have the
#: same number of generated definitions" is the property the A/B rests on and a
#: store that quietly landed 13 would otherwise pass.
ARM_SIZE = 15

FOLLOWUP_ARMS = ("diverse_followup", "sizematch_followup")
ALL_ARMS = FOLLOWUP_ARMS + ("diverse_heldout12", "sizematch_heldout12")


def load(name: str):
    return runner.Config.load(CONFIG_DIR / f"{name}.config.json")


def generated_definitions(export: Path) -> list[dict]:
    document = json.loads(export.read_text(encoding="utf-8"))
    return [
        sidecar
        for sidecar in document["objects"]
        if sidecar.get("kind") == "definition"
        and (sidecar.get("provenance") or {}).get("origin") == "generated"
    ]


class ArmConfigTest(unittest.TestCase):
    """What the four shipped configs must agree and disagree about."""

    def test_the_two_followup_arms_differ_only_in_the_store_and_the_output(self):
        diverse, sizematch = (vars(load(name)) for name in FOLLOWUP_ARMS)
        differing = {key for key in diverse if diverse[key] != sizematch[key]}
        self.assertEqual(differing, {"store_export", "output_dir", "source_path"})

    def test_every_arm_reads_its_own_store(self):
        stores = {name: load(name).store_export for name in ALL_ARMS}
        self.assertTrue(stores["diverse_followup"].endswith(
            ".loom-store-diverse/export-resolver.json"))
        self.assertTrue(stores["sizematch_followup"].endswith(
            ".loom-store-sizematch/export-resolver.json"))
        self.assertEqual(stores["diverse_followup"], stores["diverse_heldout12"])
        self.assertEqual(stores["sizematch_followup"], stores["sizematch_heldout12"])

    def test_no_two_arms_write_to_the_same_output_directory(self):
        outputs = [load(name).output_dir for name in ALL_ARMS]
        self.assertEqual(len(set(outputs)), len(outputs), outputs)

    def test_every_arm_includes_generated_objects(self):
        # An arm reading .loom-store-diverse with include_generated false would
        # be the curated baseline wearing a different store's name — and it
        # would replicate the curated numbers, which is the most confusing
        # possible way for this experiment to fail.
        for name in ALL_ARMS:
            self.assertTrue(load(name).include_generated, name)

    def test_the_transport_is_identical_across_every_arm_and_the_baselines(self):
        """`n_ctx` and the budget are held fixed, or the A/B has two variables."""
        for name in ALL_ARMS:
            config = load(name)
            self.assertEqual(config.n_ctx, 32768, name)
            self.assertEqual(config.conditions, ["gbnf+typemask"], name)
            self.assertEqual(config.token_budget_per_task, 512, name)
            self.assertEqual(config.max_tokens_per_draw, 512, name)
            self.assertEqual(config.temperature, 0.8, name)
            self.assertEqual(
                sorted(config.pruners), ["de-bruijn", "goal-type", "ref-hash"], name
            )

    def test_the_followup_arms_match_the_recorded_baselines_shape(self):
        for name in FOLLOWUP_ARMS:
            config = load(name)
            self.assertEqual(config.regimes, ["full_corpus", "held_out"], name)
            self.assertEqual(config.seeds, [1, 2, 3], name)

    def test_the_heldout12_arms_match_the_recorded_12_seed_shape(self):
        for name in ("diverse_heldout12", "sizematch_heldout12"):
            config = load(name)
            self.assertEqual(config.regimes, ["held_out"], name)
            self.assertEqual(config.seeds, list(range(1, 13)), name)


@unittest.skipUnless(
    DIVERSE_STORE.is_file() and SIZEMATCH_STORE.is_file() and CURATED_STORE.is_file(),
    "needs the built store variants (task store:diverse && task store:sizematch)",
)
class ArmStoreTest(unittest.TestCase):
    """Verification steps 3 and 4, re-derived from the stores themselves.

    Every assertion here reads the store's own export and re-analyses the
    surfaces. Nothing consults the selection report: a gate that silently
    stopped firing would still produce a report saying it had, and the store is
    the only artefact the experiment actually runs against.
    """

    @classmethod
    def setUpClass(cls):
        cls.diverse = generated_definitions(DIVERSE_STORE)
        cls.sizematch = generated_definitions(SIZEMATCH_STORE)
        cls.curated_classes = harvest_select.curated_classes(
            json.loads(CURATED_STORE.read_text(encoding="utf-8"))
        )

    def test_both_arms_hold_the_same_number_of_generated_definitions(self):
        self.assertEqual(len(self.diverse), ARM_SIZE)
        self.assertEqual(len(self.sizematch), ARM_SIZE)

    def test_the_diverse_arm_holds_nothing_vacuous(self):
        offenders = []
        for sidecar in self.diverse:
            shape = harvest_select.shape_of(sidecar["surface"])
            if shape.is_constant or shape.unused_parameters:
                offenders.append(sidecar["name"])
        self.assertEqual(offenders, [])

    def test_every_diverse_definition_is_its_own_structural_class(self):
        classes = [
            harvest_select.shape_of(sidecar["surface"]).structural_class
            for sidecar in self.diverse
        ]
        self.assertEqual(len(set(classes)), len(classes))

    def test_no_diverse_definition_repeats_a_curated_shape(self):
        for sidecar in self.diverse:
            shape = harvest_select.shape_of(sidecar["surface"])
            self.assertNotIn(shape.structural_class, self.curated_classes, sidecar["name"])

    def test_the_control_arm_is_a_genuine_contrast(self):
        """The control must be *different*, or it controls for nothing.

        Not a check that the control is bad — a neutral draw could in principle
        come back clean. It is a check that the manipulation happened at all: if
        these two ever became the same 15 objects, every comparison in the
        results document would be noise reported as a finding.
        """
        diverse = {sidecar["hash"] for sidecar in self.diverse}
        sizematch = {sidecar["hash"] for sidecar in self.sizematch}
        self.assertNotEqual(diverse, sizematch)
        vacuous = sum(
            1
            for sidecar in self.sizematch
            if (
                harvest_select.shape_of(sidecar["surface"]).is_constant
                or harvest_select.shape_of(sidecar["surface"]).unused_parameters
            )
        )
        self.assertGreater(vacuous, 0, "the neutral draw landed no vacuous object")

    def test_both_arms_have_context_for_their_own_longest_prompt(self):
        """The `n_ctx` trap that has already cost one launch, per arm."""
        for name in ALL_ARMS:
            config = load(name)
            resolver = runner.make_resolver(config)
            required = prompts.context_required(
                config.regimes, resolver, draw_tokens=config.max_tokens_per_draw
            )
            self.assertGreater(
                config.n_ctx,
                2 * required,
                f"{name}: n_ctx {config.n_ctx} against {required} required",
            )

    def test_each_arm_resolves_the_curated_corpus_plus_its_own_fifteen(self):
        for name in ALL_ARMS:
            resolver = runner.make_resolver(load(name))
            self.assertEqual(len(list(resolver.definitions())), 26 + ARM_SIZE, name)


if __name__ == "__main__":
    unittest.main()
