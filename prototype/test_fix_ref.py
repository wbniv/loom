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
        term = f"(fix {self.size_type} 0 {self.measure} {self.size_body('(app (var 3) (var 0))')})"
        validate_source(self.definition(self.size_type, term), self.registry)

    def test_recursive_call_arguments_use_the_constructor_binder_types(self):
        # var 1 is the I64 head, not the List tail, so the recursive call fails.
        term = f"(fix {self.size_type} 0 {self.measure} {self.size_body('(app (var 3) (var 1))')})"
        self.assert_type_error(self.definition(self.size_type, term), "type mismatch")

    def test_fix_synthesizes_its_annotation_in_application_position(self):
        fix = f"(fix {self.size_type} 0 {self.measure} {self.size_body('(app (var 3) (var 0))')})"
        term = f"(app {fix} (con 0x{self.digest.hex()} 0 ()))"
        validate_source(self.definition("I64", term), self.registry)

    def test_fix_annotation_must_equal_the_expected_type(self):
        wrong = f"(fn {self.list_i64} () Bool)"
        term = f"(fix {wrong} 0 {self.measure} (lam {self.list_i64} (lit bool true)))"
        self.assert_type_error(self.definition(self.size_type, term), "fix annotation differs from the expected type")

    def test_fix_body_is_checked_against_the_annotation(self):
        term = f"(fix {self.size_type} 0 {self.measure} (lam {self.list_i64} (lit bool true)))"
        self.assert_type_error(self.definition(self.size_type, term), "type mismatch")

    def test_measure_must_map_the_selected_argument_to_i64(self):
        not_a_function = f"(fix {self.size_type} 0 (lit i64 0) {self.size_body('(lit i64 0)')})"
        self.assert_type_error(self.definition(self.size_type, not_a_function), "type mismatch")
        wrong_result = f"(lam {self.list_i64} (lit bool true))"
        wrong = f"(fix {self.size_type} 0 {wrong_result} {self.size_body('(lit i64 0)')})"
        self.assert_type_error(self.definition(self.size_type, wrong), "type mismatch")
        wrong_domain = f"(fix {self.size_type} 0 (lam I64 (lit i64 0)) {self.size_body('(lit i64 0)')})"
        self.assert_type_error(self.definition(self.size_type, wrong_domain), "lambda parameter annotation differs")

    def test_measure_is_checked_without_the_recursive_binder(self):
        # var 0 in the measure would be the recursive value if the measure were
        # checked under the fix binder; at the definition's depth it is unbound.
        term = f"(fix {self.size_type} 0 (var 0) {self.size_body('(lit i64 0)')})"
        with self.assertRaises(Exception) as caught:
            validate_source(self.definition(self.size_type, term), self.registry)
        self.assertIn("out of scope", str(caught.exception))

    def test_fix_at_a_non_function_type_is_refused(self):
        self.assert_type_error(self.definition("I64", "(fix I64 0 (lit i64 0) (var 0))"), "not implemented")

    def test_fix_body_checks_under_the_annotation_row(self):
        effectful = f"(fn (cap {self.clock}) ({self.clock}) I64)"
        measure = f"(lam (cap {self.clock}) (lit i64 0))"
        body = f"(lam (cap {self.clock}) (perform {self.clock} 0 ()))"
        validate_source(self.definition(effectful, f"(fix {effectful} 0 {measure} {body})"), self.registry)

    def test_fix_body_cannot_exceed_the_annotation_row(self):
        pure = f"(fn (cap {self.clock}) () I64)"
        measure = f"(lam (cap {self.clock}) (lit i64 0))"
        body = f"(lam (cap {self.clock}) (perform {self.clock} 0 ()))"
        self.assert_type_error(
            self.definition(pure, f"(fix {pure} 0 {measure} {body})"),
            "not allowed by the ambient effect row",
        )

    def test_terminates_is_not_discharged_by_this_layer(self):
        # Unconditional self-application: well-typed, obviously non-terminating.
        # §2.5/§6.2 termination is oracle evidence, not a typing rule.
        body = f"(lam {self.list_i64} (app (var 1) (var 0)))"
        term = f"(fix {self.size_type} 0 {self.measure} {body})"
        validate_source(self.definition(self.size_type, term), self.registry)


class MeasureSelectionTest(unittest.TestCase):
    """§2.5's position field: which curried argument the measure describes."""

    def setUp(self):
        self.list_decl = [4, KEY, 1, [[], [[5, 0], [7, [[5, 0]]]]]]
        self.registry = prelude.registry()
        self.registry.add(self.list_decl)
        self.digest = declaration_hash(self.list_decl)
        self.list_i64 = f"(data 0x{self.digest.hex()} (I64))"
        self.clock = "0x" + prelude.HASH_HEX["clock"]
        # foldRight : (I64 -> I64 -> I64) -> I64 -> List I64 -> I64
        self.combine = "(fn I64 () (fn I64 () I64))"
        self.fold_type = f"(fn {self.combine} () (fn I64 () (fn {self.list_i64} () I64)))"
        self.size = f"(lam {self.list_i64} (lit i64 0))"
        # rec=5, f=4, z=3, l=2, x=1, xs=0 inside the Cons arm (§2.3.1).
        cons = "(app (app (var 4) (var 1)) (app (app (app (var 5) (var 4)) (var 3)) (var 0)))"
        arms = f"((0 0 (var 1)) (1 2 {cons}))"
        self.fold_body = f"(lam {self.combine} (lam I64 (lam {self.list_i64} (match (var 0) {arms}))))"

    def definition(self, type_surface: str, term_surface: str) -> str:
        return f"(def {type_surface} {term_surface})"

    def assert_type_error(self, source: str, message: str, reference_type=None):
        with self.assertRaises(TypeDirectionError) as caught:
            validate_source(source, self.registry, reference_type)
        self.assertIn(message, str(caught.exception))

    def test_a_measure_over_the_third_argument_typechecks(self):
        term = f"(fix {self.fold_type} 2 {self.size} {self.fold_body})"
        validate_source(self.definition(self.fold_type, term), self.registry)

    def test_the_same_recursion_cannot_state_its_measure_at_position_zero(self):
        # Position 0 is the combining function, so `size` no longer matches: this
        # is exactly the case §2.5's selector exists to make expressible.
        term = f"(fix {self.fold_type} 0 {self.size} {self.fold_body})"
        self.assert_type_error(self.definition(self.fold_type, term), "lambda parameter annotation differs")

    def test_the_measure_domain_follows_the_position(self):
        # Position 1 selects the accumulator, so an I64 measure is what fits.
        accumulator = "(lam I64 (lit i64 0))"
        validate_source(
            self.definition(self.fold_type, f"(fix {self.fold_type} 1 {accumulator} {self.fold_body})"),
            self.registry,
        )
        self.assert_type_error(
            self.definition(self.fold_type, f"(fix {self.fold_type} 1 {self.size} {self.fold_body})"),
            "lambda parameter annotation differs",
        )

    def test_a_position_past_the_curried_spine_is_refused(self):
        term = f"(fix {self.fold_type} 3 {self.size} {self.fold_body})"
        self.assert_type_error(self.definition(self.fold_type, term), "measure position 3 exceeds the annotation's 3-argument curried spine")

    def test_rows_walked_past_by_the_selector_are_untouched(self):
        # Reaching argument 1 performs a clock effect; only the measure's own row
        # must be empty, because the walked rows say nothing about how many times
        # the recursion runs (§2.5).
        annotation = f"(fn (cap {self.clock}) ({self.clock}) (fn I64 () I64))"
        measure = "(lam I64 (lit i64 0))"
        body = f"(lam (cap {self.clock}) (lam I64 (perform {self.clock} 0 ())))"
        self.assert_type_error(self.definition(annotation, f"(fix {annotation} 1 {measure} {body})"), "not allowed by the ambient effect row")
        pure_body = f"(lam (cap {self.clock}) (lam I64 (var 0)))"
        validate_source(self.definition(annotation, f"(fix {annotation} 1 {measure} {pure_body})"), self.registry)

    def test_a_measure_over_two_arguments_is_not_expressible(self):
        # The recorded v0.1 limit: one measure over one argument. A `merge`-style
        # recursion needing `size xs + size ys` must take `div` instead.
        both = f"(lam {self.combine} (lam I64 (lit i64 0)))"
        term = f"(fix {self.fold_type} 0 {both} {self.fold_body})"
        self.assert_type_error(self.definition(self.fold_type, term), "type mismatch")


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
        term = f"(fix {self.size_type} 0 {self.size} {body})"
        validate_source(self.definition(self.size_type, term), self.registry, self.resolve)

    def test_a_stored_reference_measures_a_non_initial_argument(self):
        # The payoff: `(ref #List.size)` is the measure of a curried recursion
        # whose decreasing argument is its third, with no eta-reordering.
        combine = "(fn I64 () (fn I64 () I64))"
        fold_type = f"(fn {combine} () (fn I64 () (fn {self.list_i64} () I64)))"
        cons = "(app (app (var 4) (var 1)) (app (app (app (var 5) (var 4)) (var 3)) (var 0)))"
        arms = f"((0 0 (var 1)) (1 2 {cons}))"
        body = f"(lam {combine} (lam I64 (lam {self.list_i64} (match (var 0) {arms}))))"
        term = f"(fix {fold_type} 2 {self.size} {body})"
        validate_source(self.definition(fold_type, term), self.registry, self.resolve)

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
