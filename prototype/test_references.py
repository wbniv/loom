"""Tests for canonical declarations and registry-backed reference checks."""

from __future__ import annotations

import unittest

from declarations import DeclarationError, DeclarationRegistry, declaration_hash
from references import ReferenceError, validate_source
from scope import ScopeError

I64 = [0, 2]
BOOL = [0, 1]
DATA_KEY = b"d" * 32
LIST_KEY = b"l" * 32
ABILITY_KEY = b"a" * 32


class ReferenceValidationTest(unittest.TestCase):
    def setUp(self):
        # Option a = None | Some a | Pair a a (recursive self is exercised by List).
        self.option = [4, DATA_KEY, 1, [[], [[5, 0]], [[5, 0], [5, 0]]]]
        self.list_decl = [4, LIST_KEY, 1, [[], [[5, 0], [7, [[5, 0]]]]]]
        self.ability = [5, ABILITY_KEY, [[[], I64], [[I64, BOOL], I64]]]
        self.registry = DeclarationRegistry([self.option, self.list_decl, self.ability])
        self.option_hash = declaration_hash(self.option)
        self.list_hash = declaration_hash(self.list_decl)
        self.ability_hash = declaration_hash(self.ability)

    @staticmethod
    def h(digest: bytes) -> str:
        return "0x" + digest.hex()

    def definition(self, type_surface: str, term_surface: str) -> str:
        return f"(def {type_surface} {term_surface})"

    def assert_reference_error(self, source: str, message: str):
        with self.assertRaises((ReferenceError, DeclarationError, ScopeError)) as caught:
            validate_source(source, self.registry)
        self.assertIn(message, str(caught.exception))

    def test_recursive_data_declaration_hashes_deterministically(self):
        self.assertEqual(declaration_hash(self.list_decl), declaration_hash(self.list_decl))
        self.assertEqual(len(self.list_hash), 32)

    def test_registry_rejects_wrong_supplied_hash(self):
        with self.assertRaisesRegex(DeclarationError, "does not match canonical hash"):
            DeclarationRegistry().add(self.option, b"x" * 32)

    def test_registry_snapshot_is_immune_to_caller_mutation(self):
        declaration = [4, DATA_KEY, 0, [[]]]
        registry = DeclarationRegistry([declaration])
        digest = declaration_hash(declaration)
        declaration[3].append([I64])
        self.assertEqual(registry.data(digest).field_counts, (0,))

    def test_declaration_rejects_bad_self_arity_and_ability_self(self):
        with self.assertRaisesRegex(DeclarationError, "self expects 1"):
            declaration_hash([4, DATA_KEY, 1, [[[7, []]]]])
        with self.assertRaisesRegex(DeclarationError, "self type is forbidden"):
            declaration_hash([5, ABILITY_KEY, [[[[7, []]], I64]]])

    def test_data_type_parameter_arity_and_wrong_kind(self):
        option = self.h(self.option_hash)
        ability = self.h(self.ability_hash)
        self.assert_reference_error(self.definition(f"(data {option} ())", "(lit unit)"), "expects 1 type arguments")
        self.assert_reference_error(self.definition(f"(data {ability} (I64))", "(lit unit)"), "not data")

    def test_missing_data_and_ability_references(self):
        missing = "0x" + "ff" * 32
        self.assert_reference_error(self.definition(f"(data {missing} ())", "(lit unit)"), "missing data")
        self.assert_reference_error(self.definition(f"(cap {missing})", "(lit unit)"), "missing ability")

    def test_constructor_bounds_and_arity(self):
        option = self.h(self.option_hash)
        good = self.definition(f"(data {option} (I64))", f"(con {option} 1 ((lit i64 7)))")
        validate_source(good, self.registry)
        self.assert_reference_error(self.definition("I64", f"(con {option} 3 ())"), "constructor index 3")
        self.assert_reference_error(self.definition("I64", f"(con {option} 2 ((lit i64 1)))"), "expects 2 arguments")

    def test_perform_bounds_and_arity(self):
        ability = self.h(self.ability_hash)
        validate_source(self.definition("I64", f"(perform {ability} 1 ((lit i64 1) (lit bool true)))"), self.registry)
        self.assert_reference_error(self.definition("I64", f"(perform {ability} 2 ())"), "operation index 2")
        self.assert_reference_error(self.definition("I64", f"(perform {ability} 1 ((lit i64 1)))"), "expects 2 arguments")

    def test_effect_rows_and_capabilities_require_abilities(self):
        ability = self.h(self.ability_hash)
        option = self.h(self.option_hash)
        validate_source(self.definition(f"(fn (cap {ability}) ({ability}) I64)", "(lam (cap " + ability + ") (lit i64 0))"), self.registry)
        self.assert_reference_error(self.definition(f"(fn I64 ({option}) I64)", "(lam I64 (var 0))"), "not ability")

    def test_handler_scope_and_reference_checks_share_registry(self):
        ability = self.h(self.ability_hash)
        source = self.definition("I64", f"(handle {ability} (lit i64 0) ((1 (var 2))) (var 0))")
        validate_source(source, self.registry)
        bad = self.definition("I64", f"(handle {ability} (lit i64 0) ((9 (var 0))) (var 0))")
        self.assert_reference_error(bad, "cannot resolve ability operation 9")

    def test_match_semantics_are_deliberately_not_inferred_here(self):
        # The layer traverses arms for nested references but cannot identify the
        # scrutinee's data declaration without type inference.
        validate_source(self.definition("I64", "(match (lit i64 0) ((99 0 (lit i64 1))))"), self.registry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
