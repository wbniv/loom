"""Tests for the refinement-to-SMT-LIB translation of SPEC.md §3.2.1."""

from __future__ import annotations

import hashlib
import unittest

import sexpr
from declarations import DeclarationRegistry, declaration_hash
from refinements import (
    ObligationTranslator,
    SmtError,
    check_translatable,
    obligation_script,
    script_hash,
    subtype_script,
)

UNIT = [0, 0]
BOOL = [0, 1]
I64 = [0, 2]
F64 = [0, 3]
TEXT = [0, 4]
BYTES = [0, 5]

LT = hashlib.sha256(b"loom:test:lt").digest()
ADD = hashlib.sha256(b"loom:test:add").digest()
EQ_TEXT = hashlib.sha256(b"loom:test:eqText").digest()
LEN = hashlib.sha256(b"loom:test:len").digest()
IS_MIDDLE = hashlib.sha256(b"loom:test:isMiddleOf").digest()
READER = hashlib.sha256(b"loom:test:reader").digest()
CLOCK = hashlib.sha256(b"loom:test:clockAbility").digest()

SIGNATURES = {
    LT: [2, I64, [], [2, I64, [], BOOL]],
    ADD: [2, I64, [], [2, I64, [], I64]],
    EQ_TEXT: [2, TEXT, [], [2, TEXT, [], BOOL]],
    LEN: [2, TEXT, [], I64],
    IS_MIDDLE: [2, F64, [], [2, F64, [], BOOL]],
    READER: [2, TEXT, [CLOCK], BOOL],
}
INTERPRETATIONS = {LT: "<", ADD: "+", EQ_TEXT: "="}

DATA_KEY = b"r" * 32
# List a = Nil | Cons a (List a)
LIST_DECLARATION = [4, DATA_KEY, 1, [[], [[5, 0], [7, [[5, 0]]]]]]
# Colour = Red | Green
COLOUR_DECLARATION = [4, b"c" * 32, 0, [[], []]]

COMMANDS = ("set-logic", "declare-sort", "declare-datatypes", "declare-const", "declare-fun", "assert", "check-sat", "exit")
DECLARATIONS = ("declare-sort", "declare-datatypes", "declare-const", "declare-fun")


def ref(digest, *arguments):
    term = [1, digest]
    for argument in arguments:
        term = [4, term, argument]
    return term


def i64(value):
    return [2, 2, value]


class RefinementTranslationTest(unittest.TestCase):
    def setUp(self):
        self.registry = DeclarationRegistry([LIST_DECLARATION, COLOUR_DECLARATION])
        self.list_hash = declaration_hash(LIST_DECLARATION)
        self.colour_hash = declaration_hash(COLOUR_DECLARATION)

    # ------------------------------------------------------------- helpers

    def script(self, context, hypotheses, goal):
        return obligation_script(context, hypotheses, goal, self.registry, SIGNATURES, INTERPRETATIONS)

    def assert_smt_error(self, message, context, hypotheses, goal):
        with self.assertRaises(SmtError) as caught:
            self.script(context, hypotheses, goal)
        self.assertIn(message, str(caught.exception))

    def assert_well_formed(self, script: str):
        """Structural conformance: command shape and ordering, one negated goal."""
        self.assertTrue(script.endswith("\n"))
        lines = script[:-1].split("\n")
        forms = sexpr.parse_all(script)
        self.assertEqual(len(forms), len(lines))
        heads = []
        for form in forms:
            self.assertIsInstance(form, list)
            self.assertIsInstance(form[0], str)
            self.assertIn(form[0], COMMANDS)
            heads.append(form[0])
        self.assertEqual(heads[0], "set-logic")
        self.assertEqual(forms[0][1], "ALL")
        self.assertEqual(heads[-2:], ["check-sat", "exit"])
        self.assertEqual(heads[-3], "assert")
        self.assertEqual(forms[-3][1][0], "not")
        first_assert = heads.index("assert")
        self.assertTrue(all(head in DECLARATIONS for head in heads[1:first_assert]))
        self.assertTrue(all(head == "assert" for head in heads[first_assert:-2]))
        return forms

    # -------------------------------------------------------------- golden

    def test_linear_arithmetic_subtype_script_is_golden(self):
        weaker = ref(LT, [0, 0], i64(10))
        stronger = ref(LT, [0, 0], i64(100))
        script = subtype_script(I64, weaker, stronger, self.registry, SIGNATURES, INTERPRETATIONS)
        self.assertEqual(
            script,
            "(set-logic ALL)\n"
            "(declare-const loom.x0 Int)\n"
            "(assert (and (<= (- 9223372036854775808) loom.x0) (<= loom.x0 9223372036854775807)))\n"
            "(assert (< loom.x0 10))\n"
            "(assert (not (< loom.x0 100)))\n"
            "(check-sat)\n"
            "(exit)\n",
        )
        self.assert_well_formed(script)

    def test_script_hash_is_stable_and_content_addressed(self):
        goal = ref(LT, [0, 0], i64(10))
        first = self.script([I64], [], goal)
        second = self.script([I64], [], goal)
        self.assertEqual(first, second)
        self.assertEqual(script_hash(first), hashlib.sha256(first.encode("utf-8")).hexdigest())
        self.assertNotEqual(script_hash(first), script_hash(self.script([I64], [], ref(LT, [0, 0], i64(11)))))

    def test_negative_literal_and_outer_context(self):
        goal = ref(LT, [0, 0], ref(ADD, [0, 1], i64(-3)))
        script = self.script([I64, I64], [], goal)
        self.assertIn("(< loom.x0 (+ loom.x1 (- 3)))", script)
        self.assertIn("(declare-const loom.x1 Int)", script)
        self.assert_well_formed(script)

    # --------------------------------------------------------------- sorts

    def test_base_sorts_and_opaque_literal_distinctness(self):
        goal = ref(EQ_TEXT, [2, 4, "alpha"], [2, 4, "beta"])
        script = self.script([TEXT], [], goal)
        self.assertIn("(declare-sort Loom.Text 0)", script)
        self.assertIn("(assert (distinct loom.text.", script)
        # The context variable is opaque, so it carries no I64 domain axiom.
        self.assertNotIn("9223372036854775807", script)
        self.assert_well_formed(script)

    def test_unit_bool_and_bytes_context_sorts(self):
        translator = ObligationTranslator(self.registry, SIGNATURES, INTERPRETATIONS)
        script = translator.script([UNIT, BOOL, BYTES, F64], [], [0, 1])
        self.assertIn("(declare-datatypes ((Loom.Unit 0)) (((loom.unit))))", script)
        self.assertIn("(declare-const loom.x0 Loom.Unit)", script)
        self.assertIn("(declare-const loom.x1 Bool)", script)
        self.assertIn("(declare-const loom.x2 Loom.Bytes)", script)
        self.assertIn("(declare-const loom.x3 Loom.F64)", script)
        self.assertEqual(script.count("(declare-sort "), 2)
        self.assert_well_formed(script)

    def test_refinements_erase_to_their_base_sort(self):
        refined = [3, I64, ref(LT, [0, 0], i64(4))]
        script = self.script([refined], [], ref(LT, [0, 0], i64(9)))
        self.assertIn("(declare-const loom.x0 Int)", script)
        # Erasure is not a hypothesis: the inner predicate is dropped, not asserted.
        self.assertNotIn("(assert (< loom.x0 4))", script)

    def test_recursive_parameterized_data_is_monomorphized(self):
        list_i64 = [1, self.list_hash, [I64]]
        # match xs { Cons head tail -> head < 10 ; Nil -> true }
        goal = [7, [0, 0], [[1, 2, ref(LT, [0, 1], i64(10))], [0, 0, [2, 1, True]]]]
        script = self.script([list_i64], [], goal)
        forms = self.assert_well_formed(script)
        datatypes = [form for form in forms if form[0] == "declare-datatypes"]
        self.assertEqual(len(datatypes), 1)
        self.assertEqual(len(datatypes[0][1]), 1)
        sort = datatypes[0][1][0][0]
        self.assertTrue(sort.startswith("Loom.D") and len(sort) == 70)
        # The Cons tail field is the same monomorphic sort: recursion closes.
        self.assertIn(f"({sort}.c1.f1 {sort})", script)
        self.assertIn(f"(match loom.x0 (({sort}.c0 true) (({sort}.c1 loom.b0 loom.b1) (< loom.b0 10))))", script)

    def test_distinct_type_arguments_give_distinct_sorts(self):
        of_i64 = self.script([[1, self.list_hash, [I64]]], [], [2, 1, True])
        of_bool = self.script([[1, self.list_hash, [BOOL]]], [], [2, 1, True])
        self.assertNotEqual(of_i64, of_bool)

    def test_match_arm_order_does_not_change_the_script(self):
        list_i64 = [1, self.list_hash, [I64]]
        forwards = [7, [0, 0], [[0, 0, [2, 1, True]], [1, 2, ref(LT, [0, 1], i64(10))]]]
        backwards = [7, [0, 0], [[1, 2, ref(LT, [0, 1], i64(10))], [0, 0, [2, 1, True]]]]
        self.assertEqual(self.script([list_i64], [], forwards), self.script([list_i64], [], backwards))

    def test_monomorphic_constructor_and_let(self):
        colour = [1, self.colour_hash, []]
        # let c : Colour = Red in match c { Red -> true ; Green -> false }
        goal = [5, colour, [6, self.colour_hash, 0, []], [7, [0, 0], [[0, 0, [2, 1, True]], [1, 0, [2, 1, False]]]]]
        script = self.script([], [], goal)
        self.assertIn("(let ((loom.b0 ", script)
        self.assert_well_formed(script)

    def test_if_translates_to_ite_without_growing_the_allowlist(self):
        # §3.2.1: `if` is the one node whose translation costs the trusted theory
        # surface nothing, because `ite` was already an admitted symbol.
        goal = ref(LT, [12, ref(LT, [0, 0], i64(0)), i64(1), [0, 0]], i64(10))
        script = self.script([I64], [], goal)
        self.assertIn("(< (ite (< loom.x0 0) 1 loom.x0) 10)", script)
        self.assert_well_formed(script)

    def test_if_requires_a_bool_condition_and_one_branch_sort(self):
        self.assert_smt_error("condition", [I64], [], [12, [0, 0], [2, 1, True], [2, 1, False]])
        self.assert_smt_error("expected sort Int", [I64], [], [12, [2, 1, True], i64(1), [2, 1, False]])

    # ----------------------------------------------- uninterpreted symbols

    def test_unmapped_reference_becomes_an_uninterpreted_function(self):
        goal = ref(IS_MIDDLE, [0, 0], [0, 1])
        script = self.script([F64, F64], [], goal)
        self.assertIn(f"(declare-fun loom.f{IS_MIDDLE.hex()} (Loom.F64 Loom.F64) Bool)", script)
        self.assertIn(f"(loom.f{IS_MIDDLE.hex()} loom.x0 loom.x1)", script)
        self.assert_well_formed(script)

    def test_nullary_reference_is_declared_with_an_empty_argument_list(self):
        digest = hashlib.sha256(b"loom:test:flag").digest()
        script = obligation_script([], [], [1, digest], self.registry, {digest: BOOL}, {})
        self.assertIn(f"(declare-fun loom.f{digest.hex()} () Bool)", script)
        self.assert_well_formed(script)

    # ---------------------------------------------------- fragment refusal

    def test_out_of_fragment_terms_are_rejected(self):
        cases = [
            ("`lam`", [3, I64, [2, 1, True]]),
            ("`perform`", [8, CLOCK, 0, []]),
            ("`handle`", [9, CLOCK, [2, 1, True], [], [0, 0]]),
            ("`fix`", [10, BOOL, 0, i64(0), [0, 0]]),
            ("`hole`", [11, BOOL, []]),
        ]
        for label, term in cases:
            with self.subTest(label):
                self.assert_smt_error(label, [], [], term)

    def test_out_of_fragment_sorts_are_rejected(self):
        cases = [
            ("function type", [2, I64, [], I64]),
            ("capability type", [4, CLOCK]),
            ("type variable type", [5, 0]),
            ("forall type", [6, I64]),
        ]
        for label, type_ir in cases:
            with self.subTest(label):
                self.assert_smt_error(label, [type_ir], [], [2, 1, True])

    def test_partial_application_and_missing_signature(self):
        self.assert_smt_error("partial application is out of fragment", [I64], [], ref(LT, [0, 0]))
        unknown = hashlib.sha256(b"loom:test:unknown").digest()
        self.assert_smt_error("has no signature", [], [], [1, unknown])

    def test_effectful_reference_is_rejected(self):
        self.assert_smt_error("is effectful", [TEXT], [], ref(READER, [0, 0]))

    def test_nonlinear_multiplication_and_variable_division(self):
        mul = hashlib.sha256(b"loom:test:mul").digest()
        div = hashlib.sha256(b"loom:test:div").digest()
        signatures = {**SIGNATURES, mul: [2, I64, [], [2, I64, [], I64]], div: [2, I64, [], [2, I64, [], I64]]}
        interpretations = {**INTERPRETATIONS, mul: "*", div: "div"}

        def run(goal):
            return obligation_script([I64, I64], [], goal, self.registry, signatures, interpretations)

        run(ref(LT, ref(mul, [0, 0], i64(3)), i64(9)))
        with self.assertRaises(SmtError) as caught:
            run(ref(LT, ref(mul, [0, 0], [0, 1]), i64(9)))
        self.assertIn("nonlinear", str(caught.exception))
        run(ref(LT, ref(div, [0, 0], i64(2)), i64(9)))
        with self.assertRaises(SmtError) as caught:
            run(ref(LT, ref(div, [0, 0], [0, 1]), i64(9)))
        self.assertIn("nonzero integer literal divisor", str(caught.exception))

    def test_interpretation_table_is_checked(self):
        bogus = hashlib.sha256(b"loom:test:bogus").digest()
        with self.assertRaises(SmtError) as caught:
            ObligationTranslator(self.registry, {bogus: BOOL}, {bogus: "str.++"})
        self.assertIn("not an admitted interpreted SMT-LIB symbol", str(caught.exception))
        mismatched = {LT: "<"}
        signatures = {LT: [2, TEXT, [], [2, TEXT, [], BOOL]]}
        with self.assertRaises(SmtError) as caught:
            obligation_script([TEXT], [], ref(LT, [0, 0], [0, 0]), self.registry, signatures, mismatched)
        self.assertIn("expects two Int arguments", str(caught.exception))

    def test_argument_sort_and_goal_sort_are_checked(self):
        self.assert_smt_error("expected sort Int", [TEXT], [], ref(LT, [0, 0], i64(1)))
        self.assert_smt_error("a goal must translate to Bool", [I64], [], [0, 0])
        self.assert_smt_error("a hypothesis must translate to Bool", [I64], [[0, 0]], [2, 1, True])

    def test_match_and_constructor_refusals(self):
        list_i64 = [1, self.list_hash, [I64]]
        self.assert_smt_error("non-exhaustive match", [list_i64], [], [7, [0, 0], [[0, 0, [2, 1, True]]]])
        duplicate = [7, [0, 0], [[0, 0, [2, 1, True]], [0, 0, [2, 1, True]], [1, 2, [2, 1, True]]]]
        self.assert_smt_error("duplicate constructor arm 0", [list_i64], [], duplicate)
        wrong_binders = [7, [0, 0], [[0, 0, [2, 1, True]], [1, 1, [2, 1, True]]]]
        self.assert_smt_error("binder count 1", [list_i64], [], wrong_binders)
        arm_sorts = [7, [0, 0], [[0, 0, [2, 1, True]], [1, 2, i64(0)]]]
        self.assert_smt_error("arm sort Int differs from Bool", [list_i64], [], arm_sorts)
        self.assert_smt_error("match scrutinee does not have a datatype sort", [I64], [], [7, [0, 0], []])
        self.assert_smt_error("parameterized constructor", [], [], [6, self.list_hash, 0, []])
        self.assert_smt_error("missing data declaration", [], [], [6, b"z" * 32, 0, []])

    def test_variable_out_of_context(self):
        self.assert_smt_error("has no sort in the obligation environment", [], [], [0, 0])

    # ------------------------------------------------------ helper surface

    def test_check_translatable(self):
        check_translatable([3, I64, ref(LT, [0, 0], i64(4))], self.registry, SIGNATURES, INTERPRETATIONS)
        with self.assertRaises(SmtError) as caught:
            check_translatable([3, I64, [0, 0]], self.registry, SIGNATURES, INTERPRETATIONS)
        self.assertIn("a goal must translate to Bool", str(caught.exception))
        with self.assertRaises(SmtError) as caught:
            check_translatable(I64, self.registry, SIGNATURES, INTERPRETATIONS)
        self.assertIn("expected a refinement type node", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
