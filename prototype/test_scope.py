"""Tests for stateful term/type de Bruijn scope validation."""

from __future__ import annotations

import unittest

from scope import ScopeError, validate_source

HASH = "0x" + "11" * 32
HASH_BYTES = bytes.fromhex("11" * 32)


def definition(type_surface: str, term_surface: str) -> str:
    return f"(def {type_surface} {term_surface})"


def resolver(ability: bytes, operation: int) -> int:
    table = {(HASH_BYTES, 0): 0, (HASH_BYTES, 1): 2}
    return table[(ability, operation)]


class ScopeTest(unittest.TestCase):
    def assert_valid(self, source: str, ability_arity=None):
        validate_source(source, ability_arity)

    def assert_scope_error(self, source: str, message: str, ability_arity=None):
        with self.assertRaises(ScopeError) as caught:
            validate_source(source, ability_arity)
        self.assertIn(message, str(caught.exception))

    def test_closed_definition_rejects_free_variable(self):
        self.assert_scope_error(definition("I64", "(var 0)"), "out of scope at depth 0")

    def test_lambda_and_nested_shadowing(self):
        self.assert_valid(definition("I64", "(lam I64 (lam I64 (app (var 1) (var 0))))"))
        self.assert_scope_error(definition("I64", "(lam I64 (var 1))"), "out of scope at depth 1")

    def test_let_binds_only_its_body(self):
        self.assert_valid(definition("I64", "(let I64 (lit i64 1) (var 0))"))
        self.assert_scope_error(definition("I64", "(let I64 (var 0) (var 0))"), ".bound")

    def test_match_arm_uses_declared_binder_count(self):
        self.assert_valid(definition("I64", "(match (lit i64 0) ((0 2 (app (var 1) (var 0)))))"))
        self.assert_scope_error(definition("I64", "(match (lit i64 0) ((0 1 (var 1))))"), "depth 1")

    def test_refinement_binds_refined_value_and_sees_outer_terms(self):
        self.assert_valid(definition("(refine I64 (var 0))", "(lam I64 (hole (refine I64 (var 1)) ()))"))
        self.assert_scope_error(definition("(refine I64 (var 1))", "(lit i64 0)"), "depth 1")

    def test_hole_constraint_binds_prospective_value(self):
        self.assert_valid(definition("I64", "(hole I64 ((var 0)))"))
        self.assert_scope_error(definition("I64", "(hole I64 ((var 1)))"), "depth 1")

    def test_forall_and_row_variables(self):
        polymorphic = "(forall (fn (tyvar 0) ((tyvar 0)) (tyvar 0)))"
        self.assert_valid(definition(polymorphic, f"(hole {polymorphic} ())"))
        self.assert_scope_error(definition("(tyvar 0)", "(lit unit)"), "type index 0")
        self.assert_scope_error(definition("(fn I64 ((tyvar 0)) I64)", "(lit unit)"), "type index 0")

    def test_fix_binds_self_only_in_body(self):
        self.assert_valid(definition("I64", "(fix I64 (lit i64 0) (var 0))"))
        self.assert_valid(definition("I64", "(fix I64 (lit i64 0) (lam I64 (var 1)))"))
        self.assert_scope_error(definition("I64", "(fix I64 (var 0) (var 0))"), ".measure")

    def test_handler_requires_resolver(self):
        source = definition("I64", f"(handle {HASH} (lit i64 0) ((0 (var 0))) (var 0))")
        self.assert_scope_error(source, "requires an ability", None)
        self.assert_valid(source, resolver)

    def test_handler_parameter_and_continuation_order(self):
        source = definition("I64", f"(handle {HASH} (lit i64 0) ((1 (app (var 2) (app (var 1) (var 0))))) (var 0))")
        self.assert_valid(source, resolver)
        bad = definition("I64", f"(handle {HASH} (lit i64 0) ((1 (var 3))) (var 0))")
        self.assert_scope_error(bad, "depth 3", resolver)

    def test_handler_rejects_unknown_operation(self):
        source = definition("I64", f"(handle {HASH} (lit i64 0) ((9 (var 0))) (var 0))")
        self.assert_scope_error(source, "cannot resolve ability operation 9", resolver)

    def test_refinement_predicate_preserves_ability_resolver(self):
        predicate = f"(handle {HASH} (lit i64 0) ((0 (var 0))) (var 0))"
        source = definition(f"(refine I64 {predicate})", "(lit i64 0)")
        self.assert_valid(source, resolver)

    def test_existing_examples_are_scoped_with_builtin_handler_resolution(self):
        from pathlib import Path
        import prelude

        examples = Path(__file__).resolve().parent / "examples"
        ability_arity = prelude.registry().operation_arity
        for path in sorted(examples.glob("*.loom.sexpr")):
            with self.subTest(path=path):
                self.assert_valid(path.read_text(encoding="utf-8"), ability_arity)


if __name__ == "__main__":
    unittest.main(verbosity=2)
