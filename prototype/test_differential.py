"""Tests for L0, the differential harness.

Two properties, and they are the only two the export has to have:

**Internally consistent.** Every accepted case's canonical bytes re-hash to the
identity recorded beside them; every rejected case carries a nonempty error
class, and one the contract for that layer actually declares. An export that
fails either is worse than no export, because a Rust port would gate against it.

**Reproducible.** Two independent processes over the same tree produce
byte-identical output. This is checked over the fixture-only scope, which drives
the 26 corpus entries, the 5 examples, and the pinned declarations, obligations
and policies — the full scope additionally runs the prototype test suite, which
would make this file take two minutes. `LOOM_DIFFERENTIAL_FULL=1` opts into that
larger check.

Everything runs in a subprocess. The harness patches module-level entry points
process-wide, and this test module is itself inside the set the full export
runs, so an in-process export here would nest one capture inside another.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

import contracts
from differential import SCHEMA_VERSION
from differential.recorder import LAYER_ORDER
from differential.spec import DECLARED_ERRORS, ENTRY_POINTS, METHOD_ENTRY_POINTS

PROTOTYPE_DIR = Path(__file__).resolve().parent

#: Contract entry points that are deliberately not wrapped, each with the
#: reason. A name that is in `contracts.py` and in neither this set nor
#: `spec.py` fails `EntryPointCoverageTest` — which is the whole point of
#: keeping the list here rather than in a comment.
UNCAPTURED = {
    # Constructed, not called. Every case reaches it through `validate_source`.
    "typecheck.MatchChecker": "class; captured through typecheck.validate_source",
    # Constructed, not called. `DeclarationRegistry.add` is the accept/reject
    # decision and is captured as a method entry point.
    "declarations.DeclarationRegistry": "class; captured as DeclarationRegistry.add",
    # A pure function of a script that every refinements record already carries
    # in full, together with this hash.
    "refinements.script_hash": "pure function of the recorded script text",
}


def export(scope: str) -> str:
    """Run the exporter in a clean process and return its JSONL text.

    `LOOM_DIFFERENTIAL_FULL` is stripped from the child's environment, and that
    is load-bearing rather than tidy. A full-scope export runs the prototype's
    test suite, which includes *this module*. Left set, the opt-in full-scope
    reproducibility test below would fire inside the export it is checking and
    launch two more full exports, each of which would launch two more — an
    unbounded fork bomb that presents as a very slow test. Stripping the
    variable makes the nested run skip it, so the recursion stops at depth one.
    """
    environment = dict(os.environ)
    environment.pop("LOOM_DIFFERENTIAL_FULL", None)
    completed = subprocess.run(
        [sys.executable, "-m", "differential", "export", "--only", scope, "--stdout"],
        cwd=PROTOTYPE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


class ExportShapeTest(unittest.TestCase):
    """The export's own invariants, over the fixture scope."""

    @classmethod
    def setUpClass(cls):
        cls.text = export("fixtures")
        records = [json.loads(line) for line in cls.text.splitlines()]
        cls.header = records[0]
        cls.environments = [record for record in records if record["record"] == "environment"]
        cls.cases = [record for record in records if record["record"] == "case"]

    def test_the_header_comes_first_and_names_the_contract_versions_cut_against(self):
        self.assertEqual(self.header["record"], "header")
        self.assertEqual(self.header["schema_version"], SCHEMA_VERSION)
        self.assertEqual(self.header["contracts"], dict(contracts.VERSIONS))
        self.assertEqual(self.header["layers"], list(LAYER_ORDER))

    def test_the_header_counts_are_the_records_that_follow(self):
        self.assertEqual(self.header["totals"]["cases"], len(self.cases))
        self.assertEqual(self.header["totals"]["environments"], len(self.environments))
        for layer in LAYER_ORDER:
            expected = self.header["counts"][layer]
            for verdict in ("accept", "reject"):
                observed = sum(
                    1 for case in self.cases if case["layer"] == layer and case["verdict"] == verdict
                )
                self.assertEqual(expected[verdict], observed, f"{layer}/{verdict}")

    def test_every_accepted_canonical_byte_string_rehashes_to_its_identity(self):
        checked = 0
        for case in self.cases:
            encoded, identity = case["canonical_bytes_hex"], case["identity_hash"]
            if encoded is None or identity is None:
                continue
            with self.subTest(case=case["case_id"]):
                self.assertEqual(hashlib.sha256(bytes.fromhex(encoded)).hexdigest(), identity)
            checked += 1
        self.assertGreater(checked, 0, "no case carried both bytes and an identity")

    def test_every_accepted_case_carries_no_error_class(self):
        for case in self.cases:
            if case["verdict"] == "accept":
                self.assertIsNone(case["error_class"], case["case_id"])

    def test_every_rejection_carries_an_error_class_some_contract_declares(self):
        rejections = [case for case in self.cases if case["verdict"] == "reject"]
        self.assertGreater(len(rejections), 0)
        declared = {name for classes in DECLARED_ERRORS.values() for name in classes}
        for case in rejections:
            with self.subTest(case=case["case_id"]):
                self.assertTrue(case["error_class"])
                # A layer may legitimately reject with an *earlier* layer's
                # class — `typecheck.validate_source` runs scope and references
                # first — so the check is that the class belongs to some
                # contract, not that it belongs to this one.
                self.assertIn(case["error_class"], declared)

    def test_every_case_carries_provenance_and_a_known_layer(self):
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                self.assertIn(case["layer"], LAYER_ORDER)
                self.assertTrue(case["provenance"])
                for entry in case["provenance"]:
                    self.assertIn(entry["origin"], ("fixture", "test", "harness"))

    def test_no_case_input_was_recorded_lossily(self):
        self.assertEqual(self.header["totals"]["opaque_inputs"], 0)

    def test_every_referenced_environment_is_present(self):
        available = {record["environment"] for record in self.environments}
        for case in self.cases:
            if case["environment"] is not None:
                self.assertIn(case["environment"], available, case["case_id"])

    def test_the_26_corpus_fixtures_and_the_5_examples_are_all_covered(self):
        names = {
            entry["module"].split("#", 1)[0]
            for case in self.cases
            for entry in case["provenance"]
            if entry["origin"] == "fixture"
        }
        self.assertEqual(self.header["fixtures"], {"corpus": 26, "examples": 5})
        self.assertEqual(len([name for name in names if name.startswith("corpus/")]), 26)
        self.assertEqual(len([name for name in names if name.startswith("examples/")]), 5)

    def test_the_worked_example_of_spec_4_4_is_in_the_export_with_its_pinned_identity(self):
        # SPEC.md §4.4's identity, pinned independently in test_roundtrip. If
        # L0 ever disagreed with it, L0 would be the thing that is wrong.
        matched = [
            case
            for case in self.cases
            if case["entry_point"] == "transcode.parse_source"
            and case["extra"].get("rendered_surface") == "(def (fn I64 () I64) (lam I64 (var 0)))"
        ]
        self.assertGreaterEqual(len(matched), 1)
        for case in matched:
            self.assertEqual(case["canonical_bytes_hex"], "83008402820002808200028303820002820000")
            self.assertEqual(
                case["identity_hash"],
                "76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605",
            )

    def test_every_layer_produces_at_least_one_case(self):
        for layer in LAYER_ORDER:
            with self.subTest(layer=layer):
                self.assertGreater(self.header["counts"][layer]["accept"] + self.header["counts"][layer]["reject"], 0)

    def test_records_are_sorted_in_migration_order(self):
        keys = [(LAYER_ORDER.index(case["layer"]), case["entry_point"], case["case_id"]) for case in self.cases]
        self.assertEqual(keys, sorted(keys))

    def test_the_file_is_one_json_object_per_line_with_a_terminal_newline(self):
        self.assertTrue(self.text.endswith("\n"))
        self.assertNotIn("\n\n", self.text)


class ReproducibilityTest(unittest.TestCase):
    def test_two_processes_produce_byte_identical_fixture_exports(self):
        self.assertEqual(export("fixtures"), export("fixtures"))

    def test_the_full_scope_opt_in_does_not_reach_a_nested_export(self):
        # Regression guard. A full-scope export runs this module, so if the
        # child inherited LOOM_DIFFERENTIAL_FULL the opt-in test would fire
        # inside the export it is checking and fork two more full exports per
        # level, without bound. Observed as three concurrent `--only all`
        # processes before `export` began scrubbing the variable.
        import test_differential

        seen = {}

        class _Completed:
            stdout = ""

        def _record(command, **keywords):
            seen.update(keywords)
            return _Completed()

        with unittest.mock.patch.dict(os.environ, {"LOOM_DIFFERENTIAL_FULL": "1"}), \
                unittest.mock.patch.object(test_differential.subprocess, "run", _record):
            export("fixtures")
            self.assertEqual(
                os.environ["LOOM_DIFFERENTIAL_FULL"], "1", "the parent's environment is untouched"
            )

        self.assertIn("env", seen)
        self.assertNotIn("LOOM_DIFFERENTIAL_FULL", seen["env"])

    @unittest.skipUnless(
        os.environ.get("LOOM_DIFFERENTIAL_FULL") == "1",
        "set LOOM_DIFFERENTIAL_FULL=1 to reproduce the full export twice (~3 minutes)",
    )
    def test_two_processes_produce_byte_identical_full_exports(self):
        self.assertEqual(export("all"), export("all"))


class EntryPointCoverageTest(unittest.TestCase):
    """The harness must not quietly stop watching a contract entry point."""

    def test_every_contract_entry_point_is_captured_or_listed_as_uncaptured(self):
        captured = {entry.name for entry in ENTRY_POINTS}
        captured |= {entry.name for entry, _ in METHOD_ENTRY_POINTS}
        for name, contract in contracts.CONTRACTS.items():
            for point in contract.entry_points:
                with self.subTest(contract=name, entry_point=point):
                    self.assertTrue(
                        point in captured or point in UNCAPTURED,
                        f"{point} is a {name} entry point that L0 neither captures nor exempts",
                    )

    def test_no_stale_exemption(self):
        every = {point for contract in contracts.CONTRACTS.values() for point in contract.entry_points}
        for name in UNCAPTURED:
            self.assertIn(name, every, f"{name} is exempted but is no longer a contract entry point")

    def test_every_captured_layer_is_a_contract(self):
        for entry in ENTRY_POINTS:
            self.assertIn(entry.layer, contracts.CONTRACTS)
        self.assertEqual(sorted(LAYER_ORDER), sorted(contracts.CONTRACTS))

    def test_every_layer_declares_the_error_classes_it_rejects_with(self):
        self.assertEqual(sorted(DECLARED_ERRORS), sorted(LAYER_ORDER))


class InstrumentationTransparencyTest(unittest.TestCase):
    """Wrapping must not change a verdict — the export would be worthless."""

    def test_a_wrapped_entry_point_returns_and_raises_exactly_what_it_did(self):
        import transcode
        from differential import instrument
        from differential.recorder import Recorder

        if instrument.is_installed():
            # This module is inside the set the full export runs. Installing
            # and then uninstalling here would tear the wrappers out from under
            # an export already in progress.
            self.skipTest("instrumentation is already installed by an enclosing export")

        source = "(def Unit (lit unit))"
        before_ir = transcode.parse_source(source)
        with self.assertRaises(transcode.SurfaceError):
            transcode.parse_source("(def  Unit (lit unit))")

        recorder = Recorder()
        instrument.install(recorder)
        recorder.enabled = True
        try:
            self.assertEqual(transcode.parse_source(source), before_ir)
            with self.assertRaises(transcode.SurfaceError):
                transcode.parse_source("(def  Unit (lit unit))")
        finally:
            recorder.enabled = False
            instrument.uninstall()

        self.assertEqual(recorder.counts()["parser"]["accept"] and True, True)
        self.assertEqual(transcode.parse_source(source), before_ir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
