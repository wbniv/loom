"""Tests for nominal constructor instantiation and match validation."""

from __future__ import annotations

import unittest

from declarations import DeclarationRegistry, declaration_hash
from matches import TypeDirectionError, constructor_fields, validate_source

I64 = [0, 2]
BOOL = [0, 1]
KEY = b"m" * 32


class MatchValidationTest(unittest.TestCase):
    def setUp(self):
        # List a = Nil | Cons a (List a)
        self.list_decl = [4, KEY, 1, [[], [[5, 0], [7, [[5, 0]]]]]]
        self.registry = DeclarationRegistry([self.list_decl])
        self.digest = declaration_hash(self.list_decl)
        self.hash = "0x" + self.digest.hex()
        self.list_i64 = f"(data {self.hash} (I64))"

    def definition(self, type_surface: str, term_surface: str) -> str:
        return f"(def {type_surface} {term_surface})"

    def assert_type_error(self, source: str, message: str):
        with self.assertRaises(TypeDirectionError) as caught:
            validate_source(source, self.registry)
        self.assertIn(message, str(caught.exception))

    def test_recursive_self_and_parameter_substitution(self):
        fields = constructor_fields(self.registry, [1, self.digest, [I64]], 1, "test")
        self.assertEqual(fields, [I64, [1, self.digest, [I64]]])

    def test_exhaustive_parameterized_match_and_binder_order(self):
        # In Cons, tail is index 0 and head is index 1.
        term = f"(lam {self.list_i64} (match (var 0) ((0 0 (lit i64 0)) (1 2 (var 1)))))"
        validate_source(self.definition(f"(fn {self.list_i64} () I64)", term), self.registry)

    def test_missing_duplicate_and_out_of_range_arms(self):
        missing = f"(lam {self.list_i64} (match (var 0) ((0 0 (lit i64 0)))))"
        self.assert_type_error(self.definition(f"(fn {self.list_i64} () I64)", missing), "missing constructors [1]")
        duplicate = f"(lam {self.list_i64} (match (var 0) ((0 0 (lit i64 0)) (0 0 (lit i64 1)) (1 2 (lit i64 2)))))"
        self.assert_type_error(self.definition(f"(fn {self.list_i64} () I64)", duplicate), "duplicate constructor arm 0")
        bad_index = f"(lam {self.list_i64} (match (var 0) ((0 0 (lit i64 0)) (2 0 (lit i64 1)))))"
        self.assert_type_error(self.definition(f"(fn {self.list_i64} () I64)", bad_index), "constructor index 2")

    def test_wrong_binder_count(self):
        term = f"(lam {self.list_i64} (match (var 0) ((0 0 (lit i64 0)) (1 1 (lit i64 1)))))"
        self.assert_type_error(self.definition(f"(fn {self.list_i64} () I64)", term), "binder count 1")

    def test_arm_result_types_must_agree(self):
        term = f"(lam {self.list_i64} (match (var 0) ((0 0 (lit i64 0)) (1 2 (lit bool true)))))"
        self.assert_type_error(self.definition(f"(fn {self.list_i64} () I64)", term), "arm result type")

    def test_match_scrutinee_must_be_nominal_data(self):
        self.assert_type_error(self.definition("I64", "(match (lit i64 0) ())"), "nominal data type")

    def test_constructor_check_uses_expected_type_arguments(self):
        nil = f"(con {self.hash} 0 ())"
        validate_source(self.definition(self.list_i64, nil), self.registry)
        cons = f"(con {self.hash} 1 ((lit i64 7) {nil}))"
        validate_source(self.definition(self.list_i64, cons), self.registry)
        bad = f"(con {self.hash} 1 ((lit bool true) {nil}))"
        self.assert_type_error(self.definition(self.list_i64, bad), "type mismatch")

    def test_nested_match_is_traversed(self):
        inner = f"(match (var 0) ((0 0 (lit i64 0)) (1 2 (var 1))))"
        outer = f"(lam {self.list_i64} (match (var 0) ((0 0 (lit i64 0)) (1 2 {inner}))))"
        validate_source(self.definition(f"(fn {self.list_i64} () I64)", outer), self.registry)

    def test_unsupported_nodes_fail_explicitly(self):
        self.assert_type_error(self.definition("I64", "(fix I64 0 (lit i64 0) (var 0))"), "not implemented")

    def test_checked_arm_mismatch_attribution(self):
        # A mismatch at the arm body itself is reported as an arm-result mismatch.
        top = f"(lam {self.list_i64} (match (var 0) ((0 0 (lit bool true)) (1 2 (lit i64 1)))))"
        with self.assertRaises(TypeDirectionError) as caught:
            validate_source(self.definition(f"(fn {self.list_i64} () I64)", top), self.registry)
        self.assertIn("arm result type differs", str(caught.exception))
        # A mismatch nested deeper inside the arm keeps its own path and message.
        nested = f"(lam {self.list_i64} (match (var 0) ((0 0 (lam I64 (lit bool true))) (1 2 (lam I64 (var 2))))))"
        with self.assertRaises(TypeDirectionError) as caught:
            validate_source(self.definition(f"(fn {self.list_i64} () (fn I64 () I64))", nested), self.registry)
        self.assertNotIn("arm result type differs", str(caught.exception))
        self.assertIn(".body.body", caught.exception.path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
