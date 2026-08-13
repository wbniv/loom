"""Tests for the type-directed `fix` and `ref` rules (SPEC §3.1.3)."""

from __future__ import annotations

import unittest

import prelude
from declarations import DeclarationRegistry, declaration_hash
from matches import MatchChecker, TypeDirectionError, validate_source

I64 = [0, 2]
KEY = b"r" * 32
SIZE_HASH = bytes.fromhex("aa" * 32)
MISSING_HASH = bytes.fromhex("bb" * 32)


def resolver(mapping):
    """A store stand-in: a hash-to-type mapping that raises on a miss."""
    return lambda digest: mapping[digest]


class FixTypingTest(unittest.TestCase):
    def setUp(self):
        # List a = Nil | Cons a (List a)
        self.list_decl = [4, KEY, 1, [[], [[5, 0], [7, [[5, 0]]]]]]
        self.registry = prelude.registry()
        self.registry.add(self.list_decl)
        self.digest = declaration_hash(self.list_decl)
        self.list_i64 = f"(data 0x{self.digest.hex()} (I64))"
        self.clock = "0x" + prelude.HASH_HEX["clock"]
        self.size_type = f"(fn {self.list_i64} () I64)"
        self.measure = f"(lam {self.list_i64} (lit i64 0))"

    def definition(self, type_surface: str, term_surface: str) -> str:
        return f"(def {type_surface} {term_surface})"

    def assert_type_error(self, source: str, message: str, reference_type=None):
        with self.assertRaises(TypeDirectionError) as caught:
            validate_source(source, self.registry, reference_type)
        self.assertIn(message, str(caught.exception))

    def size_body(self, arm_body: str) -> str:
        # In the Cons arm the tail is index 0, the head 1, the argument 2, and
        # the recursive value 3 (§2.3.1).
        arms = f"((0 0 (lit i64 0)) (1 2 {arm_body}))"
        return f"(lam {self.list_i64} (match (var 0) {arms}))"

    def test_recursive_fix_binds_the_recursive_value_at_index_zero(self):
        term = f"(fix {self.size_type} {self.measure} {self.size_body('(app (var 3) (var 0))')})"
        validate_source(self.definition(self.size_type, term), self.registry)

    def test_recursive_call_arguments_use_the_constructor_binder_types(self):
        # var 1 is the I64 head, not the List tail, so the recursive call fails.
        term = f"(fix {self.size_type} {self.measure} {self.size_body('(app (var 3) (var 1))')})"
        self.assert_type_error(self.definition(self.size_type, term), "type mismatch")

    def test_fix_synthesizes_its_annotation_in_application_position(self):
        fix = f"(fix {self.size_type} {self.measure} {self.size_body('(app (var 3) (var 0))')})"
        term = f"(app {fix} (con 0x{self.digest.hex()} 0 ()))"
        validate_source(self.definition("I64", term), self.registry)

    def test_fix_annotation_must_equal_the_expected_type(self):
        wrong = f"(fn {self.list_i64} () Bool)"
        term = f"(fix {wrong} {self.measure} (lam {self.list_i64} (lit bool true)))"
        self.assert_type_error(self.definition(self.size_type, term), "fix annotation differs from the expected type")

    def test_fix_body_is_checked_against_the_annotation(self):
        term = f"(fix {self.size_type} {self.measure} (lam {self.list_i64} (lit bool true)))"
        self.assert_type_error(self.definition(self.size_type, term), "type mismatch")

    def test_measure_must_map_the_recursive_argument_to_i64(self):
        not_a_function = f"(fix {self.size_type} (lit i64 0) {self.size_body('(lit i64 0)')})"
        self.assert_type_error(self.definition(self.size_type, not_a_function), "type mismatch")
        wrong_result = f"(lam {self.list_i64} (lit bool true))"
        wrong = f"(fix {self.size_type} {wrong_result} {self.size_body('(lit i64 0)')})"
        self.assert_type_error(self.definition(self.size_type, wrong), "type mismatch")
        wrong_domain = f"(fix {self.size_type} (lam I64 (lit i64 0)) {self.size_body('(lit i64 0)')})"
        self.assert_type_error(self.definition(self.size_type, wrong_domain), "lambda parameter annotation differs")

    def test_measure_is_checked_without_the_recursive_binder(self):
        # var 0 in the measure would be the recursive value if the measure were
        # checked under the fix binder; at the definition's depth it is unbound.
        term = f"(fix {self.size_type} (var 0) {self.size_body('(lit i64 0)')})"
        with self.assertRaises(Exception) as caught:
            validate_source(self.definition(self.size_type, term), self.registry)
        self.assertIn("out of scope", str(caught.exception))

    def test_fix_at_a_non_function_type_is_refused(self):
        self.assert_type_error(self.definition("I64", "(fix I64 (lit i64 0) (var 0))"), "not implemented")

    def test_fix_body_checks_under_the_annotation_row(self):
        effectful = f"(fn (cap {self.clock}) ({self.clock}) I64)"
        measure = f"(lam (cap {self.clock}) (lit i64 0))"
        body = f"(lam (cap {self.clock}) (perform {self.clock} 0 ()))"
        validate_source(self.definition(effectful, f"(fix {effectful} {measure} {body})"), self.registry)

    def test_fix_body_cannot_exceed_the_annotation_row(self):
        pure = f"(fn (cap {self.clock}) () I64)"
        measure = f"(lam (cap {self.clock}) (lit i64 0))"
        body = f"(lam (cap {self.clock}) (perform {self.clock} 0 ()))"
        self.assert_type_error(
            self.definition(pure, f"(fix {pure} {measure} {body})"),
            "not allowed by the ambient effect row",
        )

    def test_terminates_is_not_discharged_by_this_layer(self):
        # Unconditional self-application: well-typed, obviously non-terminating.
        # §2.5/§6.2 termination is oracle evidence, not a typing rule.
        body = f"(lam {self.list_i64} (app (var 1) (var 0)))"
        term = f"(fix {self.size_type} {self.measure} {body})"
        validate_source(self.definition(self.size_type, term), self.registry)


class ReferenceTypingTest(unittest.TestCase):
    def setUp(self):
        self.list_decl = [4, KEY, 1, [[], [[5, 0], [7, [[5, 0]]]]]]
        self.registry = prelude.registry()
        self.registry.add(self.list_decl)
        self.digest = declaration_hash(self.list_decl)
        self.list_i64 = f"(data 0x{self.digest.hex()} (I64))"
        self.clock = "0x" + prelude.HASH_HEX["clock"]
        self.size_type = f"(fn {self.list_i64} () I64)"
        self.size_ir = [2, [1, self.digest, [I64]], [], I64]
        self.size = f"(ref 0x{SIZE_HASH.hex()})"
        self.resolve = resolver({SIZE_HASH: self.size_ir})

    def definition(self, type_surface: str, term_surface: str) -> str:
        return f"(def {type_surface} {term_surface})"

    def assert_type_error(self, source: str, message: str, reference_type=None):
        with self.assertRaises(TypeDirectionError) as caught:
            validate_source(source, self.registry, reference_type)
        self.assertIn(message, str(caught.exception))

    def test_reference_checks_against_its_resolved_type(self):
        validate_source(self.definition(self.size_type, self.size), self.registry, self.resolve)

    def test_reference_synthesizes_its_resolved_type_in_application_position(self):
        term = f"(app {self.size} (con 0x{self.digest.hex()} 0 ()))"
        validate_source(self.definition("I64", term), self.registry, self.resolve)

    def test_reference_type_mismatch_is_reported(self):
        self.assert_type_error(self.definition("I64", self.size), "type mismatch", self.resolve)

    def test_reference_serves_as_a_fix_measure(self):
        arms = "((0 0 (lit i64 0)) (1 2 (app (var 3) (var 0))))"
        body = f"(lam {self.list_i64} (match (var 0) {arms}))"
        term = f"(fix {self.size_type} {self.size} {body})"
        validate_source(self.definition(self.size_type, term), self.registry, self.resolve)

    def test_unresolved_hash_is_refused(self):
        missing = f"(ref 0x{MISSING_HASH.hex()})"
        self.assert_type_error(self.definition(self.size_type, missing), "has no resolvable type", self.resolve)

    def test_absent_resolver_is_refused_rather_than_guessed(self):
        self.assert_type_error(self.definition(self.size_type, self.size), "no reference-type resolver")

    def test_resolver_returning_a_non_type_is_refused(self):
        self.assert_type_error(
            self.definition(self.size_type, self.size),
            "has no resolvable type",
            resolver({SIZE_HASH: None}),
        )

    def test_effectful_reference_obeys_the_ambient_row(self):
        effectful = resolver({SIZE_HASH: [2, I64, [prelude.HASHES["clock"]], I64]})
        call = f"(lam Unit (app {self.size} (lit i64 1)))"
        allowed = f"(fn Unit ({self.clock}) I64)"
        validate_source(self.definition(allowed, call), self.registry, effectful)
        self.assert_type_error(
            self.definition("(fn Unit () I64)", call),
            "not allowed by the ambient effect row",
            effectful,
        )

    def test_resolved_types_are_isolated_copies(self):
        checker = MatchChecker(self.registry, self.resolve)
        first = checker.synth([1, SIZE_HASH], [], (), "term")
        first[3] = [0, 1]
        second = checker.synth([1, SIZE_HASH], [], (), "term")
        self.assertEqual(second, self.size_ir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
