"""Conformance tests for the canonical Loom S-expression surface."""

from __future__ import annotations

import glob
import os
import unittest

import sexpr
import cbor_canonical
from transcode import SurfaceError, def_to_surface, parse_source, transcode_source

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "examples")
HASH_A = "0x" + "11" * 32
HASH_B = "0x" + "22" * 32
WORKED_EXAMPLE_HASH = "76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605"
WORKED_EXAMPLE_BYTES = "83008402820002808200028303820002820000"


def definition(type_surface: str, term_surface: str) -> str:
    return f"(def {type_surface} {term_surface})"


class CanonicalSurfaceTest(unittest.TestCase):
    def assert_round_trip(self, source: str):
        ir = parse_source(source)
        self.assertEqual(def_to_surface(ir), source.removesuffix("\n"))
        self.assertEqual(parse_source(def_to_surface(ir)), ir)

    def assert_rejected(self, source: str, message: str | None = None):
        with self.assertRaises((SurfaceError, sexpr.ParseError)) as caught:
            parse_source(source)
        if message is not None:
            self.assertIn(message, str(caught.exception))

    def test_worked_example_matches_spec_4_4(self):
        path = os.path.join(EXAMPLES_DIR, "01_id.loom.sexpr")
        with open(path, encoding="utf-8") as source_file:
            ir, encoded, digest = transcode_source(source_file.read())
        self.assertEqual(def_to_surface(ir), "(def (fn I64 () I64) (lam I64 (var 0)))")
        self.assertEqual(encoded.hex(), WORKED_EXAMPLE_BYTES)
        self.assertEqual(digest, WORKED_EXAMPLE_HASH)
        self.assertEqual(len(encoded), 19)

    def test_cbor_map_keys_use_rfc_8949_length_first_order(self):
        # The one-byte encoded key 0 sorts before the two-byte text key "a".
        self.assertEqual(cbor_canonical.encode({"a": 1, 0: 2}).hex(), "a20002616101")

    def test_every_example_is_canonical_and_round_trips(self):
        paths = sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.loom.sexpr")))
        self.assertEqual(len(paths), 5)
        for path in paths:
            with self.subTest(path=path), open(path, encoding="utf-8") as source_file:
                self.assert_round_trip(source_file.read())

    def test_every_term_tag_round_trips(self):
        terms = [
            "(var 0)",
            f"(ref {HASH_A})",
            "(lit unit)",
            "(lam I64 (var 0))",
            "(app (var 0) (lit i64 1))",
            "(let I64 (lit i64 1) (var 0))",
            f"(con {HASH_A} 0 ((lit unit)))",
            "(match (var 0) ((0 1 (var 0))))",
            f"(perform {HASH_A} 2 ((lit bool true)))",
            f"(handle {HASH_A} (perform {HASH_A} 0 ()) ((0 (var 0))) (var 0))",
            "(fix (fn I64 () I64) (lam I64 (var 0)) (lam I64 (var 0)))",
            "(hole I64 ((lit bool true)))",
        ]
        for term in terms:
            with self.subTest(term=term):
                self.assert_round_trip(definition("I64", term))

    def test_every_type_tag_and_row_variable_round_trips(self):
        types = [
            "Unit", "Bool", "I64", "F64", "Text", "Bytes",
            f"(data {HASH_A} (I64 Text))",
            f"(fn I64 ({HASH_A} {HASH_B} (tyvar 0)) Text)",
            "(refine I64 (lit bool true))",
            f"(cap {HASH_A})",
            "(tyvar 0)",
            "(forall (fn (tyvar 0) ((tyvar 1)) (tyvar 0)))",
        ]
        for type_surface in types:
            with self.subTest(type_surface=type_surface):
                self.assert_round_trip(definition(type_surface, "(hole " + type_surface + " ())"))

    def test_every_literal_kind_and_boundaries_round_trips(self):
        literals = [
            ("Unit", "(lit unit)"),
            ("Bool", "(lit bool false)"),
            ("Bool", "(lit bool true)"),
            ("I64", f"(lit i64 {-2**63})"),
            ("I64", f"(lit i64 {2**63 - 1})"),
            ("F64", "(lit f64 0x8000000000000000)"),
            ("F64", "(lit f64 0x7ff0000000000000)"),
            ("F64", "(lit f64 0x7ff8000000000000)"),
            ("Text", '(lit text "a;b \\"quoted\\" café")'),
            ("Bytes", "(lit bytes 0x)"),
            ("Bytes", "(lit bytes 0x00ff10)"),
        ]
        for type_surface, literal in literals:
            with self.subTest(literal=literal):
                self.assert_round_trip(definition(type_surface, literal))

    def test_optional_single_terminal_newline_is_canonical(self):
        source = definition("Unit", "(lit unit)")
        self.assertEqual(parse_source(source), parse_source(source + "\n"))

    def test_noncanonical_aliases_are_rejected(self):
        cases = [
            ("(def (base I64) (lit i64 1))", "unknown or malformed type"),
            (definition("I64", "(lit i64 01)"), "noncanonical integer"),
            (definition("I64", "(lit i64 -0)"), "negative zero"),
            (definition("I64", "(var -1)"), "nonnegative integer"),
            (definition("Bool", "(lit bool truthy)"), "true or false"),
            (definition("F64", "(lit f64 0x7ff0000000000001)"), "noncanonical NaN"),
            (definition("Text", '(lit text "e\\u0301")'), "NFC-normalized"),
            (definition("Text", '(lit text "\\ud800")'), "surrogate"),
            (definition("Bytes", "(lit bytes 0x0)"), "even number"),
            (definition("I64", f"(ref 0x{'11' * 31})"), "exactly 64"),
            (definition("I64", f"(ref 0x{'AA' * 32})"), "lowercase"),
            (definition(f"(fn I64 ({HASH_B} {HASH_A}) I64)", "(var 0)"), "sorted"),
            (definition(f"(fn I64 ({HASH_A} {HASH_A}) I64)", "(var 0)"), "unique"),
            (" (def Unit (lit unit))", "noncanonical surface"),
            ("(def  Unit (lit unit))", "noncanonical surface"),
            ("(def Unit (lit unit))\n\n", "noncanonical surface"),
            ("(def Unit (lit unit)) ; comment", "comments are not part"),
        ]
        for source, message in cases:
            with self.subTest(source=source):
                self.assert_rejected(source, message)

    def test_integer_overflow_is_rejected(self):
        self.assert_rejected(definition("I64", f"(lit i64 {2**63})"), "outside signed 64-bit")
        self.assert_rejected(definition("I64", f"(lit i64 {-2**63 - 1})"), "outside signed 64-bit")

    def test_malformed_s_expressions_have_deliberate_errors(self):
        cases = [
            ("(def Unit (lit unit)", "unclosed"),
            ("(def Unit (lit unit)))", "unexpected ')'"),
            ('(def Text (lit text "unterminated))', "unterminated string"),
            ("", "exactly one"),
            ("(def Unit (lit unit)) (def Unit (lit unit))", "exactly one"),
            ("(wat Unit (lit unit))", "expected (def"),
            ("(def Unit (unknown))", "unknown term"),
            ("(def Unit (lit unit extra))", "malformed lit"),
        ]
        for source, message in cases:
            with self.subTest(source=source):
                self.assert_rejected(source, message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
