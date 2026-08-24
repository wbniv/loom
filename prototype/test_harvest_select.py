"""The diversity-seeking harvest's gates, as assertions.

`docs/plans/2026-08-23-diversity-harvest.md` R4 is the specification. Four
things have to be true for the plan's A/B to mean anything, and each has its own
class below:

1. **The default policy changes nothing.** `--select all` must admit exactly
   what the pre-selection harvest admitted, or the corpus-loop plan's recorded
   counts stop being a baseline. `test_harvest.py` proves this from the other
   side by passing unmodified; `DefaultPolicyTest` proves it here.
2. **The gates reject what the plan says they reject**, including the specific
   term that produced turn 2's hand-scored FAIL — the regression guard for the
   finding this whole increment exists to attack.
3. **The analysis agrees with the scope checker about binding.** A free-variable
   walk that disagrees with `scope.check_term` would silently mis-report which
   parameters a definition uses, and G2 would then admit or reject the wrong
   objects with no visible symptom.
4. **Selection is reproducible.** Same pool, same policy, same answer,
   independent of the order the operator names the runs.
"""

from __future__ import annotations

import unittest

import harvest_select
from harvest_select import Candidate

# A data declaration hash, borrowed from the corpus so the surfaces below are
# the shape the transcoder really sees. Nothing here resolves it — the selector
# never asks a resolver anything, which is the point of it being a total
# function of the term.
LIST = "3ff2104702aeeb53b4dfbc5a09c0441df19f12883e6cf66e21a3bd85420b4e2f"

CONSTANT = "(def I64 (lit i64 0))"
CONSTANT_OTHER = "(def I64 (lit i64 1633072800000))"
CONSTANT_IF = "(def I64 (if (lit bool true) (lit i64 1) (lit i64 0)))"
IDENTITY = "(def (fn I64 () I64) (lam I64 (var 0)))"
NOT = "(def (fn Bool () Bool) (lam Bool (if (var 0) (lit bool false) (lit bool true))))"
APPLY = (
    "(def (fn (fn I64 () I64) () (fn I64 () I64)) "
    "(lam (fn I64 () I64) (lam I64 (app (var 1) (var 0)))))"
)

#: Turn 2's hand-scored FAIL, and the object harvest-everything put in the
#: store: a two-argument function whose body returns its second argument and
#: never mentions its first. Type-correct, semantically vacuous, and the exact
#: skeleton the model reproduced for `heldout/list/reverseThen`.
IGNORES_FIRST_ARGUMENT = (
    f"(def (fn (data 0x{LIST} (I64)) () (fn (data 0x{LIST} (I64)) () (data 0x{LIST} (I64)))) "
    f"(lam (data 0x{LIST} (I64)) (lam (data 0x{LIST} (I64)) "
    f"(let (data 0x{LIST} (I64)) (var 0) (var 1)))))"
)

#: Same skeleton as `IGNORES_FIRST_ARGUMENT`, but the body's `let` body names
#: the outer parameter, so both are used. G2 must tell these two apart, and it
#: can only do so with a correct de Bruijn walk: the two terms differ by one
#: integer.
USES_BOTH_ARGUMENTS = (
    f"(def (fn (data 0x{LIST} (I64)) () (fn (data 0x{LIST} (I64)) () (data 0x{LIST} (I64)))) "
    f"(lam (data 0x{LIST} (I64)) (lam (data 0x{LIST} (I64)) "
    f"(let (data 0x{LIST} (I64)) (var 0) (var 2)))))"
)


def candidate(name: str, surface: str, task: str = "corpus/x/y") -> Candidate:
    """A candidate whose identity is a stable stand-in, not a real hash.

    Real 64-hex identities would make the `size-match` ordering assertions
    unreadable. `size-match` sorts by identity and nothing else, so a short
    sortable string exercises the same code path.
    """
    return Candidate(identity=name, task=task, surface=surface)


class ShapeTest(unittest.TestCase):
    """G1 and G2 as properties of one definition."""

    def test_a_bare_literal_is_constant(self):
        self.assertTrue(harvest_select.shape_of(CONSTANT).is_constant)

    def test_an_if_over_literals_is_constant(self):
        # The term has structure and still computes a fixed value. This is the
        # case a "body is a single leaf" check would miss.
        self.assertTrue(harvest_select.shape_of(CONSTANT_IF).is_constant)

    def test_a_term_that_reads_a_binder_is_not_constant(self):
        self.assertFalse(harvest_select.shape_of(IDENTITY).is_constant)

    def test_a_function_that_ignores_its_first_argument_is_caught(self):
        shape = harvest_select.shape_of(IGNORES_FIRST_ARGUMENT)
        self.assertEqual(shape.unused_parameters, (0,))

    def test_the_same_shape_with_one_index_changed_uses_both(self):
        shape = harvest_select.shape_of(USES_BOTH_ARGUMENTS)
        self.assertEqual(shape.unused_parameters, ())

    def test_the_two_share_a_skeleton_so_only_the_index_walk_separates_them(self):
        # If this ever stops being true the previous two tests stop testing the
        # de Bruijn walk and start testing the skeleton, silently.
        self.assertEqual(
            harvest_select.shape_of(IGNORES_FIRST_ARGUMENT).skeleton,
            harvest_select.shape_of(USES_BOTH_ARGUMENTS).skeleton,
        )

    def test_the_skeleton_erases_leaves_but_keeps_shape(self):
        self.assertEqual(
            harvest_select.shape_of(IGNORES_FIRST_ARGUMENT).skeleton,
            "lam(lam(let(var,var)))",
        )

    def test_two_constants_of_the_same_type_share_a_structural_class(self):
        self.assertEqual(
            harvest_select.shape_of(CONSTANT).structural_class,
            harvest_select.shape_of(CONSTANT_OTHER).structural_class,
        )

    def test_the_normalised_type_collapses_object_identities(self):
        normalised = harvest_select.shape_of(IGNORES_FIRST_ARGUMENT).normalised_type
        self.assertNotIn(LIST, normalised)
        self.assertIn(harvest_select.HASH_TOKEN, normalised)

    def test_a_surface_that_does_not_transcode_raises_rather_than_guessing(self):
        with self.assertRaises(harvest_select.SelectionError):
            harvest_select.shape_of("(def I64")


class BindingAgreementTest(unittest.TestCase):
    """The walk must agree with `scope.check_term` about what binds what.

    Not a paraphrase of the scope checker: it takes the terms the scope checker
    accepts and asserts the selector's own depth accounting reaches the same
    conclusion about which top-level parameters are live. A disagreement here is
    the failure mode with no symptom — G2 would quietly gate the wrong objects.
    """

    def test_let_bodies_shift_the_index(self):
        # `(var 1)` under one lam and one let names the lam's parameter; under
        # two lams and one let it names the *inner* lam's. Same integer, two
        # different answers, and only depth accounting tells them apart.
        one_lam = "(def (fn I64 () I64) (lam I64 (let I64 (lit i64 0) (var 1))))"
        self.assertEqual(harvest_select.shape_of(one_lam).unused_parameters, ())
        self.assertEqual(
            harvest_select.shape_of(IGNORES_FIRST_ARGUMENT).unused_parameters, (0,)
        )

    def test_match_arm_binders_shift_by_their_own_count(self):
        surface = (
            f"(def (fn (data 0x{LIST} (I64)) () I64) (lam (data 0x{LIST} (I64)) "
            "(match (var 0) ((0 0 (lit i64 0)) (1 2 (var 3))))))"
        )
        # The second arm binds two fields, so `(var 3)` names the lam parameter:
        # depth is 3 inside the arm (lam, field, field), and 3 - 1 - 3 would be
        # negative if the arm's binders were not counted.
        self.assertEqual(harvest_select.shape_of(surface).unused_parameters, ())

    def test_a_handle_without_an_arity_resolver_is_unanalysable_not_wrong(self):
        # A handle's operation body binds one variable per operation parameter
        # plus the continuation, and the count is in the ability declaration.
        # Guessing would produce a plausible wrong answer; refusing does not.
        selection = harvest_select.select(
            harvest_select.POLICY_DISTINCT_SHAPE,
            [candidate("h", "(def Unit (handle 0xdead (lit unit) () (var 0)))")],
        )
        self.assertEqual(selection.selected, [])
        self.assertIn(harvest_select.GATE_UNANALYSABLE, selection.counts())


class DefaultPolicyTest(unittest.TestCase):
    """`all` is the pre-selection harvest, and must stay that way."""

    def test_all_selects_every_candidate(self):
        pool = [candidate("a", CONSTANT), candidate("b", IGNORES_FIRST_ARGUMENT)]
        selection = harvest_select.select(harvest_select.POLICY_ALL, pool)
        self.assertEqual(selection.selected, ["a", "b"])
        self.assertEqual(selection.counts(), {})

    def test_all_still_honours_the_task_prefix_exclusion(self):
        pool = [
            candidate("a", CONSTANT),
            candidate("b", IDENTITY, task="heldout/list/reverseThen"),
        ]
        selection = harvest_select.select(
            harvest_select.POLICY_ALL, pool, exclude_task_prefixes=("heldout/",)
        )
        self.assertEqual(selection.selected, ["a"])
        self.assertEqual(selection.rejected["b"], harvest_select.GATE_EXCLUDED_TASK)

    def test_an_unknown_policy_is_refused_by_name(self):
        with self.assertRaises(harvest_select.SelectionError) as caught:
            harvest_select.select("diverse-ish", [])
        self.assertIn("diverse-ish", str(caught.exception))

    def test_size_match_needs_a_count(self):
        with self.assertRaises(harvest_select.SelectionError):
            harvest_select.parse_policy("size-match:lots")


class DistinctShapeTest(unittest.TestCase):
    """R4's three gates, applied to a pool."""

    def pool(self):
        return [
            candidate("c1", CONSTANT),
            candidate("c2", CONSTANT_OTHER),
            candidate("c3", CONSTANT_IF),
            candidate("ignores", IGNORES_FIRST_ARGUMENT),
            candidate("uses", USES_BOTH_ARGUMENTS),
            candidate("id", IDENTITY),
            candidate("not", NOT),
            candidate("apply", APPLY),
        ]

    def test_constants_are_rejected_by_g1(self):
        selection = harvest_select.select(
            harvest_select.POLICY_DISTINCT_SHAPE, self.pool()
        )
        for identity in ("c1", "c2", "c3"):
            self.assertEqual(selection.rejected[identity], harvest_select.GATE_CONSTANT)

    def test_the_turn_two_failure_shape_is_rejected_by_g2(self):
        # The regression guard for the finding: this exact term was harvested
        # into the loop's store, and the model then reproduced its skeleton for
        # a held-out task and scored 0.
        selection = harvest_select.select(
            harvest_select.POLICY_DISTINCT_SHAPE, self.pool()
        )
        self.assertEqual(
            selection.rejected["ignores"], harvest_select.GATE_UNUSED_PARAMETER
        )
        self.assertIn("uses", selection.selected)

    def test_a_second_member_of_a_class_is_rejected_by_g3(self):
        pool = [candidate("first", IDENTITY), candidate("second", IDENTITY)]
        selection = harvest_select.select(harvest_select.POLICY_DISTINCT_SHAPE, pool)
        self.assertEqual(selection.selected, ["first"])
        self.assertEqual(
            selection.rejected["second"], harvest_select.GATE_REDUNDANT_SHAPE
        )

    def test_a_class_the_curated_corpus_already_occupies_is_rejected(self):
        occupied = {
            harvest_select.shape_of(IDENTITY).structural_class: "corpus/nat/widenPos"
        }
        selection = harvest_select.select(
            harvest_select.POLICY_DISTINCT_SHAPE,
            [candidate("id", IDENTITY)],
            occupied=occupied,
        )
        self.assertEqual(selection.selected, [])
        self.assertEqual(selection.collided_with["id"], "corpus/nat/widenPos")

    def test_the_gates_partition_the_pool(self):
        # Every candidate is either selected or rejected by exactly one gate, so
        # the report's tallies add up and R5's count invariant can rely on them.
        selection = harvest_select.select(
            harvest_select.POLICY_DISTINCT_SHAPE, self.pool()
        )
        self.assertEqual(
            len(selection.selected) + len(selection.rejected), len(self.pool())
        )
        self.assertEqual(sum(selection.counts().values()), len(selection.rejected))

    def test_the_stages_are_monotone_and_end_at_the_selection(self):
        selection = harvest_select.select(
            harvest_select.POLICY_DISTINCT_SHAPE, self.pool()
        )
        surviving = [count for _, count in selection.stages]
        self.assertEqual(surviving, sorted(surviving, reverse=True))
        self.assertEqual(surviving[-1], len(selection.selected))


class SizeMatchTest(unittest.TestCase):
    """The control arm: same count, same pool, neutral draw."""

    def pool(self):
        return [
            candidate("d", CONSTANT),
            candidate("a", IDENTITY),
            candidate("c", NOT),
            candidate("b", APPLY),
        ]

    def test_it_takes_the_budget_in_ascending_identity_order(self):
        selection = harvest_select.select("size-match:2", self.pool())
        self.assertEqual(set(selection.selected), {"a", "b"})

    def test_it_emits_in_pool_order_not_hash_order(self):
        # `sequence` and therefore prompt order come from pool position. The
        # arms must differ in *which* objects they show, never in what order.
        selection = harvest_select.select("size-match:3", self.pool())
        self.assertEqual(selection.selected, ["a", "c", "b"])

    def test_it_does_not_apply_the_shape_gates(self):
        selection = harvest_select.select("size-match:4", self.pool())
        self.assertIn("d", selection.selected)
        self.assertEqual(selection.counts(), {})

    def test_a_budget_larger_than_the_pool_is_refused_rather_than_shrunk(self):
        # Silently landing fewer than the budget is the failure that makes the
        # control arm stop controlling anything.
        with self.assertRaises(harvest_select.SelectionError):
            harvest_select.select("size-match:99", self.pool())

    def test_a_candidate_the_store_already_holds_does_not_consume_budget(self):
        # It would dedupe into the existing object and add nothing, so counting
        # it against the budget lands a smaller arm than the one asked for —
        # observed for real: size-match:15 first landed 13 generated objects.
        selection = harvest_select.select(
            "size-match:2", self.pool(), already_held=frozenset({"a"})
        )
        self.assertEqual(selection.rejected["a"], harvest_select.GATE_ALREADY_HELD)
        self.assertEqual(set(selection.selected), {"b", "c"})


class ReproducibilityTest(unittest.TestCase):
    """Same pool, same answer — the completion criterion, as a test."""

    def pool(self):
        return [
            candidate("c1", CONSTANT),
            candidate("uses", USES_BOTH_ARGUMENTS),
            candidate("id", IDENTITY),
            candidate("apply", APPLY),
        ]

    def test_repeated_selection_is_identical(self):
        first = harvest_select.select(harvest_select.POLICY_DISTINCT_SHAPE, self.pool())
        again = harvest_select.select(harvest_select.POLICY_DISTINCT_SHAPE, self.pool())
        self.assertEqual(first.selected, again.selected)
        self.assertEqual(first.rejected, again.rejected)

    def test_size_match_is_independent_of_pool_order(self):
        forward = harvest_select.select("size-match:2", self.pool())
        backward = harvest_select.select("size-match:2", list(reversed(self.pool())))
        self.assertEqual(set(forward.selected), set(backward.selected))


if __name__ == "__main__":
    unittest.main()
