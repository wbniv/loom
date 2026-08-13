"""Tests for canonical namespace policy objects (SPEC.md §5.3.1-§5.3.2)."""

from __future__ import annotations

import unittest

import policies
from policies import (
    DEFAULT_POLICY,
    DEFAULT_POLICY_HASH,
    PolicyError,
    decompose_obligation_id,
    dominates,
    matching_rules,
    policy_hash,
    satisfies,
    validate_policy,
)

GEN_A = b"\xc1\xd0" + b"\x00" * 30
GEN_B = b"\xff" * 32

#: §5.3.1's worked example policy, verbatim in shape: every `ensures`
#: obligation reaches A1 at bound <= 1/2000, confidence >= 99%, under GEN_A;
#: an injected `no-panic` property must be proved outright; no assumptions.
EXAMPLE_POLICY = [
    6,
    {
        0: [
            [[0], [1, [1, 2000], [99, 100], GEN_A]],
            [[3, "no-panic"], [3]],
        ],
        1: [["no-panic", "Evaluation neither traps nor aborts on any reachable input."]],
        2: 0,
    },
]

#: §12's worked policy: `stats/POLICY`, bound <= 1/2000 @ >= 99% under GEN_A,
#: zero assumptions anywhere in the transitive closure.
STATS_POLICY = [6, {0: [[[0], [1, [1, 2000], [99, 100], GEN_A]]], 2: 0}]

#: §12's recorded `ensures.isMiddleOf` evidence: Clopper-Pearson bound for
#: 10_000 zero-failure draws at 99% confidence, rounded up to [461, 1000000].
MEDIAN_EVIDENCE = [1, [461, 1000000], [99, 100], GEN_A]


class DefaultPolicyTest(unittest.TestCase):
    def test_pinned_hash(self):
        self.assertEqual(
            policy_hash(DEFAULT_POLICY).hex(),
            "901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c",
        )
        self.assertEqual(policy_hash(DEFAULT_POLICY), DEFAULT_POLICY_HASH)

    def test_pinned_bytes(self):
        self.assertEqual(policies.policy_bytes(DEFAULT_POLICY), bytes.fromhex("8206a0"))

    def test_default_policy_dominates_itself(self):
        self.assertTrue(dominates(DEFAULT_POLICY, DEFAULT_POLICY))


class StructuralValidationTest(unittest.TestCase):
    def test_accepts_representative_full_policy(self):
        node = validate_policy(EXAMPLE_POLICY)
        self.assertEqual(node[0], 6)

    def test_accepts_stats_policy(self):
        validate_policy(STATS_POLICY)

    def test_rejects_unknown_key(self):
        with self.assertRaisesRegex(PolicyError, "unrecognized policy key"):
            validate_policy([6, {10: 1}])

    def test_rejects_wrong_object_kind(self):
        with self.assertRaisesRegex(PolicyError, "object-kind tag 6"):
            validate_policy([0, {}])

    def test_rejects_unsorted_rules_array(self):
        # The two entries of EXAMPLE_POLICY's rules are canonically ordered;
        # swapping them is a bytewise-unsorted array.
        rules = EXAMPLE_POLICY[1][0]
        bad = [6, {0: [rules[1], rules[0]]}]
        with self.assertRaisesRegex(PolicyError, "sorted bytewise"):
            validate_policy(bad)

    def test_rejects_duplicate_rule_entries(self):
        rule = [[0], [1, [1, 2000], [99, 100], GEN_A]]
        with self.assertRaisesRegex(PolicyError, "duplicate"):
            validate_policy([6, {0: [rule, rule]}])

    def test_rejects_empty_array_valued_key(self):
        with self.assertRaisesRegex(PolicyError, "non-empty"):
            validate_policy([6, {0: []}])

    def test_rejects_non_canonical_rational(self):
        with self.assertRaisesRegex(PolicyError, "lowest terms"):
            validate_policy([6, {0: [[[0], [1, [2, 4], [99, 100], GEN_A]]]}])

    def test_rejects_rational_denominator_zero(self):
        with self.assertRaisesRegex(PolicyError, "denominator"):
            validate_policy([6, {0: [[[0], [1, [0, 0], [99, 100], GEN_A]]]}])

    def test_rejects_bad_selector_length(self):
        with self.assertRaisesRegex(PolicyError, "length 0, 1, or 2"):
            validate_policy([6, {0: [[[0, "a", "b"], [3]]]}])

    def test_rejects_selector_unknown_kind_tag(self):
        with self.assertRaisesRegex(PolicyError, "unknown obligation kind tag"):
            validate_policy([6, {0: [[[9], [3]]]}])

    def test_rejects_unknown_requirement_level(self):
        with self.assertRaisesRegex(PolicyError, "invalid level"):
            validate_policy([6, {0: [[[0], [5]]]}])

    def test_rejects_requirement_level_1_without_triple(self):
        with self.assertRaisesRegex(PolicyError, "invalid level 1"):
            validate_policy([6, {0: [[[0], [1]]]}])

    def test_rejects_requirement_of_wrong_length(self):
        with self.assertRaisesRegex(PolicyError, "1-element level or 4-element"):
            validate_policy([6, {0: [[[0], [1, [1, 2]]]]}])

    def test_rejects_duplicate_require_detail(self):
        with self.assertRaisesRegex(PolicyError, "duplicate detail"):
            validate_policy([6, {1: [["no-panic", "a"], ["no-panic", "b"]]}])

    def test_rejects_relax_value_other_than_one(self):
        with self.assertRaisesRegex(PolicyError, "only admitted value is 1"):
            validate_policy([6, {8: 0}])

    def test_rejects_max_lease_millis_zero(self):
        with self.assertRaisesRegex(PolicyError, "at least 1"):
            validate_policy([6, {6: 0}])

    def test_rejects_duplicate_ability_hash(self):
        entry = [b"a" * 32, 1]
        with self.assertRaisesRegex(PolicyError, "duplicate ability hash"):
            validate_policy([6, {3: [[b"a" * 32, 1], [b"a" * 32, 2]]}])

    def test_empty_policy_validates(self):
        validate_policy([6, {}])


class ObligationDecompositionTest(unittest.TestCase):
    def test_kind_and_detail(self):
        self.assertEqual(decompose_obligation_id("ensures.isMiddleOf"), (0, "isMiddleOf"))

    def test_kind_with_dotted_detail(self):
        self.assertEqual(decompose_obligation_id("property.no-panic"), (3, "no-panic"))

    def test_kind_with_no_detail(self):
        self.assertEqual(decompose_obligation_id("terminates"), (1, None))
        self.assertEqual(decompose_obligation_id("exhaustive-match"), (2, None))

    def test_unknown_kind_rejected(self):
        with self.assertRaisesRegex(PolicyError, "unknown obligation kind"):
            decompose_obligation_id("bogus.detail")


class SelectorMatchingTest(unittest.TestCase):
    def test_matching_rules_is_conjunctive(self):
        policy_map = EXAMPLE_POLICY[1]
        matched = matching_rules(policy_map, "ensures.isMiddleOf")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0][0], [0])

    def test_broad_and_narrow_rule_both_match(self):
        policy_map = {
            0: [
                [[0], [1, [1, 100], [90, 100], GEN_A]],
                [[0, "isMiddleOf"], [2]],
            ]
        }
        matched = matching_rules(policy_map, "ensures.isMiddleOf")
        self.assertEqual(len(matched), 2)

    def test_property_rule_matches_injected_obligation(self):
        matched = matching_rules(EXAMPLE_POLICY[1], "property.no-panic")
        self.assertEqual(len(matched), 1)
        selector, requirement = matched[0]
        self.assertEqual(selector, [3, "no-panic"])
        self.assertEqual(requirement, [3])

    def test_no_matching_rule(self):
        self.assertEqual(matching_rules(EXAMPLE_POLICY[1], "terminates"), [])


class SatisfactionTest(unittest.TestCase):
    def test_a1_satisfies_a1_same_generator_stronger(self):
        requirement = [1, [1, 2000], [99, 100], GEN_A]
        self.assertTrue(satisfies(MEDIAN_EVIDENCE, requirement))

    def test_a1_does_not_satisfy_a1_different_generator(self):
        requirement = [1, [1, 2000], [99, 100], GEN_B]
        self.assertFalse(satisfies(MEDIAN_EVIDENCE, requirement))

    def test_a1_weaker_bound_refused(self):
        weaker = [1, [1, 500], [99, 100], GEN_A]  # 1/500 > 1/2000
        requirement = [1, [1, 2000], [99, 100], GEN_A]
        self.assertFalse(satisfies(weaker, requirement))

    def test_a1_lower_confidence_refused(self):
        weaker = [1, [1, 2000], [9, 10], GEN_A]
        requirement = [1, [1, 2000], [99, 100], GEN_A]
        self.assertFalse(satisfies(weaker, requirement))

    def test_a2_and_a3_satisfy_any_a1_requirement(self):
        requirement = [1, [1, 2000], [99, 100], GEN_A]
        self.assertTrue(satisfies([2], requirement))
        self.assertTrue(satisfies([3], requirement))

    def test_a0_requirement_met_by_anything(self):
        requirement = [0]
        self.assertTrue(satisfies([0], requirement))
        self.assertTrue(satisfies(MEDIAN_EVIDENCE, requirement))
        self.assertTrue(satisfies([2], requirement))
        self.assertTrue(satisfies([3], requirement))

    def test_a1_does_not_satisfy_a2_requirement(self):
        requirement = [2]
        self.assertFalse(satisfies(MEDIAN_EVIDENCE, requirement))

    def test_a2_does_not_satisfy_a3_requirement(self):
        self.assertFalse(satisfies([2], [3]))
        self.assertTrue(satisfies([3], [3]))

    def test_a0_does_not_satisfy_a1_requirement(self):
        requirement = [1, [1, 2000], [99, 100], GEN_A]
        self.assertFalse(satisfies([0], requirement))


class DominationTest(unittest.TestCase):
    def test_default_policy_is_dominated_by_stats_policy(self):
        self.assertTrue(dominates(STATS_POLICY, DEFAULT_POLICY))

    def test_weaker_bound_does_not_dominate(self):
        weaker = [6, {0: [[[0], [1, [1, 500], [99, 100], GEN_A]]]}]
        self.assertFalse(dominates(weaker, STATS_POLICY))

    def test_strictly_stronger_single_rule_dominates(self):
        predecessor = [6, {0: [[[0], [1, [1, 100], [19, 20], GEN_A]]]}]
        stronger = [6, {0: [[[0], [1, [1, 1000], [99, 100], GEN_A]]]}]
        self.assertTrue(dominates(stronger, predecessor))

    def test_rules_test_refuses_semantically_stronger_conjunction(self):
        # The predecessor states one broad rule over selector [0]. The
        # successor's two rules, over selectors [0,'a'] and [0,'b'], are each
        # individually stronger and would (if 'a' and 'b' were the only
        # `ensures` obligations) conjunctively cover the same ground at least
        # as strictly — but neither successor selector is a *prefix* of [0],
        # so no single successor rule dominates the predecessor's rule. This
        # pins SPEC.md §5.3.2's "sound but incomplete" domination test: it
        # refuses in the safe direction rather than reasoning about rule
        # conjunctions.
        predecessor = [6, {0: [[[0], [1, [1, 100], [19, 20], GEN_A]]]}]
        successor = [
            6,
            {
                0: [
                    [[0, "a"], [1, [1, 1000], [99, 100], GEN_A]],
                    [[0, "b"], [1, [1, 1000], [99, 100], GEN_A]],
                ]
            },
        ]
        self.assertFalse(dominates(successor, predecessor))

    def test_require_superset_dominates(self):
        predecessor = [6, {1: [["a", "statement a"]]}]
        superset = [6, {1: [["a", "statement a"], ["b", "statement b"]]}]
        self.assertTrue(dominates(superset, predecessor))
        self.assertFalse(dominates(predecessor, superset))

    def test_max_assumptions_no_larger_dominates(self):
        predecessor = [6, {2: 5}]
        self.assertTrue(dominates([6, {2: 5}], predecessor))
        self.assertTrue(dominates([6, {2: 3}], predecessor))
        self.assertFalse(dominates([6, {2: 6}], predecessor))
        self.assertFalse(dominates([6, {}], predecessor))

    def test_per_ability_caps_dominate(self):
        ability = b"a" * 32
        predecessor = [6, {3: [[ability, 5]]}]
        self.assertTrue(dominates([6, {3: [[ability, 3]]}], predecessor))
        self.assertFalse(dominates([6, {3: [[ability, 6]]}], predecessor))
        self.assertFalse(dominates([6, {}], predecessor))

    def test_signers_subset_dominates(self):
        principals = [b"p" * 32, b"q" * 32]
        predecessor = [6, {4: sorted(principals)}]
        subset = [6, {4: [b"p" * 32]}]
        self.assertTrue(dominates(subset, predecessor))
        other = [6, {4: [b"r" * 32]}]
        self.assertFalse(dominates(other, predecessor))
        self.assertFalse(dominates([6, {}], predecessor))

    def test_key8_relax_dominance_is_the_ratchet_direction(self):
        strict_predecessor = [6, {0: [[[0], [3]]]}]  # relax absent
        relaxed_successor = [6, {0: [[[0], [3]]], 8: 1}]
        # A successor that introduces relax where the predecessor had none
        # does not dominate: presence of relax is the weaker state.
        self.assertFalse(dominates(relaxed_successor, strict_predecessor))
        self.assertTrue(dominates(strict_predecessor, strict_predecessor))
        relaxed_predecessor = [6, {0: [[[0], [3]]], 8: 1}]
        # Once the predecessor already states relax, the successor may
        # state it too and still dominate.
        self.assertTrue(dominates(relaxed_predecessor, relaxed_predecessor))

    def test_statement_never_affects_domination(self):
        predecessor = [6, {9: "predecessor prose"}]
        successor = [6, {9: "unrelated prose"}]
        self.assertTrue(dominates(successor, predecessor))


class WorkedExampleArithmeticTest(unittest.TestCase):
    """Pins §12's `stats/median` example: bound <= 5e-4 @ >= 99% under #c1d0…."""

    def test_recorded_evidence_satisfies_stats_policy_rule(self):
        matched = matching_rules(STATS_POLICY[1], "ensures.isMiddleOf")
        self.assertEqual(len(matched), 1)
        _, requirement = matched[0]
        self.assertTrue(satisfies(MEDIAN_EVIDENCE, requirement))

    def test_recorded_bound_is_within_the_stated_threshold(self):
        # 461/1000000 = 4.61e-4 <= 1/2000 = 5e-4.
        bound_value = 461 / 1_000_000
        self.assertLessEqual(bound_value, 5e-4)
        self.assertTrue(policies._rational_le([461, 1_000_000], [1, 2000]))

    def test_recorded_evidence_under_a_different_generator_is_refused(self):
        requirement = [1, [1, 2000], [99, 100], GEN_A]
        regenerated = [1, [461, 1_000_000], [99, 100], GEN_B]
        self.assertFalse(satisfies(regenerated, requirement))

    def test_stats_policy_forbids_all_assumptions(self):
        self.assertEqual(STATS_POLICY[1][2], 0)

    def test_stats_policy_hash_is_stable(self):
        self.assertEqual(policy_hash(STATS_POLICY), policy_hash(STATS_POLICY))
        self.assertNotEqual(policy_hash(STATS_POLICY), DEFAULT_POLICY_HASH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
