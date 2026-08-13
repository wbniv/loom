"""Integrity and reference-validation tests for the builtin ability prelude."""

from __future__ import annotations

import unittest

import prelude
from declarations import DeclarationError, declaration_hash
from references import ReferenceError, validate_source

EXPECTED_HASHES = {
    "clock": "e6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d",
    "rand": "0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475",
    "fsRead": "98e9d59d0eee7d7cdddf1f06b690d2dbcd0dd79e3dde97cf3e119281962e6772",
    "fsWrite": "078fa6902f2133ad6cf9c1c18835aad6ebd875006e99c184f4fe703194c73050",
    "net": "0a87ba35788ecab52716934cc1b3ae9c8a943ad543066d7e74af665f516cc65f",
    "spawn": "9f647c04e8191162b08c6575d0fd115d2823f4487a7fa76dd6551b8d3b0d1451",
    "div": "74d0a12b01b77d554d53344d6ef0565cbb622c3d1becd95560f8482ccf8ce269",
    "ffi": "a87de5c170b63c3e59d998253246b68e69da1070b785cd129783753e252c76fd",
}


class PreludeTest(unittest.TestCase):
    def setUp(self):
        self.registry = prelude.registry()

    @staticmethod
    def h(name: str) -> str:
        return "0x" + prelude.HASH_HEX[name]

    def test_hashes_are_pinned_and_nominally_distinct(self):
        self.assertEqual(dict(prelude.HASH_HEX), EXPECTED_HASHES)
        self.assertEqual(len(set(prelude.HASHES.values())), 8)

    def test_exported_declarations_reproduce_pinned_hashes(self):
        for name, expected in EXPECTED_HASHES.items():
            with self.subTest(name=name):
                self.assertEqual(declaration_hash(prelude.declaration(name)).hex(), expected)

    def test_declaration_returns_an_isolated_copy(self):
        value = prelude.declaration("clock")
        value[2].clear()
        self.assertEqual(len(prelude.declaration("clock")[2]), 2)

    def test_operation_names_match_canonical_operation_counts(self):
        for name, names in prelude.OPERATION_NAMES.items():
            with self.subTest(name=name):
                self.assertEqual(self.registry.ability(prelude.HASHES[name]).parameter_counts, tuple(len(op[0]) for op in prelude.declaration(name)[2]))
                self.assertEqual(len(names), len(prelude.declaration(name)[2]))

    def test_representative_performs_validate(self):
        clock = self.h("clock")
        rand = self.h("rand")
        read = self.h("fsRead")
        cases = [
            f"(def I64 (perform {clock} 0 ()))",
            f"(def Unit (perform {clock} 1 ((lit i64 0))))",
            f"(def Bytes (perform {rand} 0 ((lit i64 16))))",
            f"(def I64 (perform {rand} 1 ()))",
            f'(def Bytes (perform {read} 0 ((lit text "/tmp/input"))))',
        ]
        for source in cases:
            with self.subTest(source=source):
                validate_source(source, self.registry)

    def test_capability_effect_row_and_handler_validate(self):
        clock = self.h("clock")
        source = f"(def (fn (cap {clock}) ({clock}) I64) (lam (cap {clock}) (handle {clock} (perform {clock} 0 ()) ((1 (var 1))) (var 0))))"
        validate_source(source, self.registry)

    def test_div_is_an_effect_marker_not_a_performable_operation(self):
        div = self.h("div")
        source = f"(def Unit (perform {div} 0 ()))"
        with self.assertRaises((ReferenceError, DeclarationError)) as caught:
            validate_source(source, self.registry)
        self.assertIn("operation index 0", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
