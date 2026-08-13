"""Pins the validation-contract versions and checks the record against the code.

Changing a version in `contracts.py` requires editing `PINNED_VERSIONS` here.
That edit is the point at which the change gets checked against the bump rules
in `CONTRACTS.md`.
"""

import dataclasses
import importlib
import inspect
import re
import unittest
from pathlib import Path

import contracts

HERE = Path(__file__).resolve().parent
NARRATIVE = HERE / "CONTRACTS.md"

# Seeded at 1.0 for every layer as of the commit that introduced contracts.py.
# Historical versions are deliberately not reconstructed.
PINNED_VERSIONS = {
    "parser": (1, 0),
    "scope": (1, 0),
    "references": (1, 0),
    "typecheck": (1, 0),
    "declarations": (1, 0),
    "refinements": (1, 0),
    "policies": (1, 0),
}

_KEYWORD_RESOLVER = re.compile(r"^(?P<target>[\w.]+)\((?P<keyword>\w+)=\)$")


def _resolve(dotted):
    module_name, _, attribute = dotted.rpartition(".")
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


class ContractVersionTest(unittest.TestCase):
    def test_pinned_versions_match_the_record(self):
        self.assertEqual(contracts.VERSIONS.keys(), PINNED_VERSIONS.keys())
        for name, expected in PINNED_VERSIONS.items():
            with self.subTest(contract=name):
                self.assertEqual(contracts.contract(name).version, expected)

    def test_version_strings_agree_with_tuples(self):
        for name, item in contracts.CONTRACTS.items():
            with self.subTest(contract=name):
                self.assertEqual(item.version_string, f"{item.major}.{item.minor}")
                self.assertEqual(contracts.version(name), item.version_string)

    def test_versions_are_well_formed(self):
        for name, item in contracts.CONTRACTS.items():
            with self.subTest(contract=name):
                self.assertIsInstance(item.version, tuple)
                self.assertEqual(len(item.version), 2)
                for part in item.version:
                    self.assertIsInstance(part, int)
                    self.assertFalse(isinstance(part, bool))
                    self.assertGreaterEqual(part, 0)
                self.assertGreaterEqual(item.major, 1, "no contract is published below 1.0")

    def test_unknown_contract_names_the_known_ones(self):
        with self.assertRaises(KeyError) as caught:
            contracts.contract("parsr")
        message = str(caught.exception)
        self.assertIn("parsr", message)
        self.assertIn("parser", message)

    def test_str_is_the_conformance_claim_shape(self):
        self.assertEqual(str(contracts.contract("scope")), "scope contract 1.0")
        self.assertEqual(len(contracts.summary_lines()), len(contracts.CONTRACTS))


class ContractRecordTest(unittest.TestCase):
    def test_names_and_modules_are_unique(self):
        names = [item.name for item in contracts.CONTRACTS.values()]
        modules = [item.module for item in contracts.CONTRACTS.values()]
        self.assertCountEqual(names, set(names))
        self.assertCountEqual(modules, set(modules))

    def test_contracts_mapping_is_read_only(self):
        with self.assertRaises(TypeError):
            contracts.CONTRACTS["parser"] = None
        with self.assertRaises(TypeError):
            contracts.VERSIONS["parser"] = "9.9"

    def test_contracts_are_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            contracts.contract("parser").version = (2, 0)

    def test_watch_trigger_layers_are_all_versioned(self):
        for name in contracts.WATCH_TRIGGER_LAYERS:
            with self.subTest(layer=name):
                self.assertIn(name, contracts.CONTRACTS)

    def test_coverage_lists_are_stated_and_disjoint(self):
        self.assertTrue(contracts.COVERED)
        self.assertTrue(contracts.NOT_COVERED)
        self.assertFalse(set(contracts.COVERED) & set(contracts.NOT_COVERED))

    def test_error_text_is_explicitly_not_covered(self):
        joined = " ".join(contracts.NOT_COVERED)
        self.assertIn("error message text", joined)
        self.assertIn("path strings", joined)

    def test_every_contract_has_a_summary_and_entry_points(self):
        for name, item in contracts.CONTRACTS.items():
            with self.subTest(contract=name):
                self.assertTrue(item.summary.strip())
                self.assertTrue(item.entry_points)


class ContractSurfaceTest(unittest.TestCase):
    def test_entry_points_resolve_and_are_callable(self):
        for name, item in contracts.CONTRACTS.items():
            for dotted in item.entry_points:
                with self.subTest(contract=name, entry_point=dotted):
                    self.assertTrue(
                        dotted.startswith(item.module + "."),
                        "an entry point belongs to its own contract's module",
                    )
                    self.assertTrue(callable(_resolve(dotted)))

    def test_resolver_conventions_resolve(self):
        seen = 0
        for name, item in contracts.CONTRACTS.items():
            for declared in item.resolvers:
                seen += 1
                with self.subTest(contract=name, resolver=declared):
                    match = _KEYWORD_RESOLVER.match(declared)
                    if match is None:
                        self.assertIsNotNone(_resolve(declared))
                        continue
                    target = _resolve(match.group("target"))
                    parameters = inspect.signature(target).parameters
                    self.assertIn(match.group("keyword"), parameters)
        self.assertGreater(seen, 0)

    def test_injected_resolvers_are_declared_where_they_exist(self):
        self.assertIn("scope.AbilityArityResolver", contracts.contract("scope").resolvers)
        self.assertIn(
            "typecheck.ReferenceTypeResolver", contracts.contract("typecheck").resolvers
        )

    def test_pinned_artifacts_resolve(self):
        for name, item in contracts.CONTRACTS.items():
            self.assertTrue(item.pinned, f"{name} pins no artifact")
            for entry in item.pinned:
                with self.subTest(contract=name, pinned=entry):
                    if (HERE / entry).exists():
                        continue
                    self.assertIsNotNone(_resolve(entry))


class ContractNarrativeTest(unittest.TestCase):
    def setUp(self):
        self.text = NARRATIVE.read_text(encoding="utf-8")

    def test_narrative_states_every_contract_and_its_current_version(self):
        for name, item in contracts.CONTRACTS.items():
            with self.subTest(contract=name):
                self.assertIn(f"`{name}`", self.text)
                self.assertRegex(
                    self.text,
                    rf"\|\s*`{re.escape(name)}`\s*\|\s*{re.escape(item.version_string)}\s*\|",
                )

    def test_narrative_states_the_bump_rules(self):
        for token in ("MAJOR", "MINOR", "rejected loudly"):
            with self.subTest(token=token):
                self.assertIn(token, self.text)


if __name__ == "__main__":
    unittest.main()
