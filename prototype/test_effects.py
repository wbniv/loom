"""Tests for effect rows, capabilities, operations, and handlers."""

from __future__ import annotations

import os
import unittest

import prelude
from matches import MatchChecker, TypeDirectionError, validate_source


class EffectTypingTest(unittest.TestCase):
    def setUp(self):
        self.registry = prelude.registry()
        self.clock = "0x" + prelude.HASH_HEX["clock"]

    def definition(self, type_surface: str, term_surface: str) -> str:
        return f"(def {type_surface} {term_surface})"

    def assert_type_error(self, source: str, message: str):
        with self.assertRaises(TypeDirectionError) as caught:
            validate_source(source, self.registry)
        self.assertIn(message, str(caught.exception))

    def test_perform_uses_declared_row_capability_and_result(self):
        type_surface = f"(fn (cap {self.clock}) ({self.clock}) I64)"
        term = f"(lam (cap {self.clock}) (perform {self.clock} 0 ()))"
        validate_source(self.definition(type_surface, term), self.registry)

    def test_perform_requires_ambient_ability(self):
        type_surface = f"(fn (cap {self.clock}) () I64)"
        term = f"(lam (cap {self.clock}) (perform {self.clock} 0 ()))"
        self.assert_type_error(self.definition(type_surface, term), "not allowed by the ambient effect row")

    def test_perform_requires_capability_in_scope(self):
        type_surface = f"(fn Unit ({self.clock}) I64)"
        term = f"(lam Unit (perform {self.clock} 0 ()))"
        self.assert_type_error(self.definition(type_surface, term), "no capability value in scope")

    def test_operation_arguments_and_result_are_checked(self):
        type_surface = f"(fn (cap {self.clock}) ({self.clock}) Unit)"
        good = f"(lam (cap {self.clock}) (perform {self.clock} 1 ((lit i64 5))))"
        validate_source(self.definition(type_surface, good), self.registry)
        bad = f"(lam (cap {self.clock}) (perform {self.clock} 1 ((lit bool true))))"
        self.assert_type_error(self.definition(type_surface, bad), "type mismatch")

    def full_clock_handler(self, handled: str, operations: str | None = None) -> str:
        clauses = operations or "((0 (app (var 0) (lit i64 7))) (1 (app (var 0) (lit unit))))"
        return f"(handle {self.clock} {handled} {clauses} (var 0))"

    def test_handler_discharges_effect_and_types_continuations(self):
        type_surface = f"(fn (cap {self.clock}) () I64)"
        handled = f"(perform {self.clock} 0 ())"
        term = f"(lam (cap {self.clock}) {self.full_clock_handler(handled)})"
        validate_source(self.definition(type_surface, term), self.registry)

    def test_handler_requires_complete_unique_clauses(self):
        type_surface = f"(fn (cap {self.clock}) () I64)"
        handled = f"(perform {self.clock} 0 ())"
        missing = f"(lam (cap {self.clock}) {self.full_clock_handler(handled, '((0 (app (var 0) (lit i64 7))))')})"
        self.assert_type_error(self.definition(type_surface, missing), "missing operation clauses [1]")
        duplicate_clauses = "((0 (app (var 0) (lit i64 7))) (0 (app (var 0) (lit i64 8))) (1 (app (var 0) (lit unit))))"
        duplicate = f"(lam (cap {self.clock}) {self.full_clock_handler(handled, duplicate_clauses)})"
        self.assert_type_error(self.definition(type_surface, duplicate), "duplicate operation clause 0")

    def test_handler_clause_result_is_checked(self):
        type_surface = f"(fn (cap {self.clock}) () I64)"
        handled = f"(perform {self.clock} 0 ())"
        clauses = "((0 (lit bool true)) (1 (app (var 0) (lit unit))))"
        term = f"(lam (cap {self.clock}) {self.full_clock_handler(handled, clauses)})"
        self.assert_type_error(self.definition(type_surface, term), "type mismatch")

    def test_effectful_function_application_checks_row_and_capability(self):
        function_type = f"(fn Unit ({self.clock}) I64)"
        function = f"(lam Unit (perform {self.clock} 0 ()))"
        outer_type = f"(fn (cap {self.clock}) ({self.clock}) I64)"
        body = f"(let {function_type} {function} (app (var 0) (lit unit)))"
        validate_source(self.definition(outer_type, f"(lam (cap {self.clock}) {body})"), self.registry)
        direct = f"(app {function} (lit unit))"
        self.assert_type_error(
            self.definition(outer_type, f"(lam (cap {self.clock}) {direct})"),
            "not allowed by the ambient effect row",
        )

    def test_call_checks_effect_allowance_but_not_a_redundant_capability(self):
        clock_bytes = prelude.HASHES["clock"]
        function_type = [2, [0, 0], [clock_bytes], [0, 2]]
        term = [4, [0, 0], [2, 0]]
        checker = MatchChecker(self.registry)
        self.assertEqual(checker.synth(term, [function_type], (clock_bytes,), "test"), [0, 2])
        with self.assertRaisesRegex(TypeDirectionError, "not allowed"):
            checker.synth(term, [function_type], (), "test")

    def test_synthesized_lambda_is_pure_and_cannot_escape_a_handler(self):
        # Regression: an unannotated lambda performing the handled ability must
        # not synthesize a pure type and escape through the return clause.
        type_surface = f"(fn (cap {self.clock}) () (fn Unit () I64))"
        handled = f"(lam Unit (perform {self.clock} 0 ()))"
        term = f"(lam (cap {self.clock}) {self.full_clock_handler(handled)})"
        self.assert_type_error(self.definition(type_surface, term), "not allowed by the ambient effect row")

    def test_synthesized_lambda_body_ignores_ambient_allowance(self):
        clock_bytes = prelude.HASHES["clock"]
        checker = MatchChecker(self.registry)
        lam = [3, [0, 0], [8, clock_bytes, 0, []]]
        with self.assertRaisesRegex(TypeDirectionError, "not allowed"):
            checker.synth(lam, [[4, clock_bytes]], (clock_bytes,), "test")

    def test_operationless_ability_cannot_be_handled(self):
        div = "0x" + prelude.HASH_HEX["div"]
        type_surface = f"(fn (cap {div}) () I64)"
        term = f"(lam (cap {div}) (handle {div} (lit i64 1) () (var 0)))"
        self.assert_type_error(self.definition(type_surface, term), "cannot be handled")

    def test_clock_handler_documentation_fixture(self):
        path = os.path.join(os.path.dirname(__file__), "examples", "05_clock_handler.loom.sexpr")
        with open(path, encoding="utf-8") as source_file:
            validate_source(source_file.read(), self.registry)

    def test_row_polymorphism_fails_explicitly(self):
        checker = MatchChecker(self.registry)
        with self.assertRaisesRegex(TypeDirectionError, "row-polymorphic"):
            checker.check([3, [0, 0], [2, 0]], [2, [0, 0], [[5, 0]], [0, 0]], [], (), "test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
