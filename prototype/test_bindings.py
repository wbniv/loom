"""Binding and lease admission (SPEC.md §5.3.2, §5.3.3).

These tests are about the *composition*: that `bindings.py` reaches §5.3.2's
verdicts by asking `policies.py`, and that every rule refuses for its own
stated reason rather than for a generic one. Where a test could pass by
accident — an admission that succeeds because nothing was checked — it asserts
the positive record too (which rules fired, which chain resolved).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import bindings
import policies
import store_admit

GEN_A = bytes([1]) * 32
GEN_B = bytes([2]) * 32
ALICE = bytes([0xA1]) * 32
BOB = bytes([0xB0]) * 32

A0 = [0]
A2 = [2]
A3 = [3]


def a1(bound, confidence, generator=GEN_A):
    return [1, list(bound), list(confidence), generator]


def policy(**keys):
    """`[6, policy-map]` from keyword names that read like §5.3.1's table."""
    names = {
        "rules": 0,
        "require": 1,
        "max_assumptions": 2,
        "by_ability": 3,
        "signers": 4,
        "writers": 5,
        "max_lease": 6,
        "max_redraws": 7,
        "relax": 8,
        "statement": 9,
    }
    return [6, {names[key]: value for key, value in keys.items()}]


def bound(namespace, obj):
    return bindings.PolicyBinding(
        namespace=namespace, hash=policies.policy_hash(obj), object=obj
    )


DEFAULT_HASH = policies.DEFAULT_POLICY_HASH


def candidate(name_path, *, policy_ref=DEFAULT_HASH, evidence=(), obj=None, def_hash=None, seq=1):
    return bindings.Candidate(
        name_path=name_path,
        def_hash=def_hash if def_hash is not None else bytes([0xDE]) * 32,
        evidence=list(evidence),
        policy_ref=policy_ref,
        seq=seq,
        object=obj,
    )


def policy_candidate(name_path, obj, *, policy_ref=DEFAULT_HASH, evidence=(), seq=1):
    return candidate(
        name_path,
        policy_ref=policy_ref,
        evidence=evidence,
        obj=obj,
        def_hash=policies.policy_hash(obj),
        seq=seq,
    )


class NamePathTest(unittest.TestCase):
    def test_the_namespace_is_everything_but_the_leaf_and_root_is_empty(self):
        self.assertEqual(bindings.split_name_path("stats/inner/median"), ("stats/inner", "median"))
        self.assertEqual(bindings.split_name_path("median"), ("", "median"))
        self.assertEqual(bindings.split_name_path("POLICY"), ("", "POLICY"))

    def test_an_empty_segment_or_non_nfc_text_is_not_a_name_path(self):
        for text in ["", "a//b", "/a", "a/"]:
            with self.assertRaises(ValueError):
                bindings.split_name_path(text)
        # NFC: "e" + combining acute is not the same spelling as "é".
        with self.assertRaises(ValueError):
            bindings.split_name_path("éclair")


class ResolutionTest(unittest.TestCase):
    def test_the_nearest_enclosing_policy_governs_and_the_chain_ends_at_default(self):
        near = policy(statement="near")
        far = policy(statement="far")
        chain = bindings.resolve(
            "a/b", False, [bound("a/b", near), bound("a", far), bound("", policy())]
        )
        self.assertEqual(policies.policy_hash(chain[0]), policies.policy_hash(near))
        self.assertEqual(len(chain), 4)
        self.assertEqual(policies.policy_hash(chain[-1]), DEFAULT_HASH)

    def test_a_policy_leaf_resolves_strictly_above_so_no_policy_governs_itself(self):
        own = policy(statement="stats")
        root = policy(statement="root")
        chain = bindings.resolve("stats", True, [bound("stats", own), bound("", root)])
        self.assertEqual(policies.policy_hash(chain[0]), policies.policy_hash(root))

    def test_with_no_policy_anywhere_the_default_governs_on_its_own(self):
        self.assertEqual(bindings.resolve("a/b", False, []), [policies.DEFAULT_POLICY])

    def test_a_sibling_namespaces_policy_never_governs(self):
        chain = bindings.resolve("a/b", False, [bound("a/c", policy(statement="sibling"))])
        self.assertEqual(chain, [policies.DEFAULT_POLICY])

    def test_the_default_policy_is_the_three_bytes_the_spec_prints(self):
        # SPEC §5.3.2: `printf '\x82\x06\xa0' | sha256sum`.
        self.assertEqual(policies.policy_bytes(policies.DEFAULT_POLICY), b"\x82\x06\xa0")
        self.assertEqual(
            hashlib.sha256(b"\x82\x06\xa0").hexdigest(),
            "901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c",
        )
        self.assertEqual(DEFAULT_HASH.hex(), hashlib.sha256(b"\x82\x06\xa0").hexdigest())


class EvidenceSetTest(unittest.TestCase):
    def test_a_set_has_one_spelling_so_it_is_sorted_and_duplicate_free(self):
        self.assertEqual(
            sorted(bindings.validate_evidence_set([["ensures.a", A3], ["terminates", A0]])),
            ["ensures.a", "terminates"],
        )
        with self.assertRaises(policies.PolicyError):
            bindings.validate_evidence_set([["terminates", A0], ["ensures.a", A3]])
        with self.assertRaises(policies.PolicyError):
            bindings.validate_evidence_set([["ensures.a", A3], ["ensures.a", A0]])

    def test_an_obligation_kind_outside_the_closed_registry_is_refused(self):
        with self.assertRaises(policies.PolicyError):
            bindings.validate_evidence_set([["wombat.x", A3]])


class AdmissionTest(unittest.TestCase):
    def test_the_empty_case_admits_and_says_what_it_checked(self):
        record = bindings.admit(candidate("stats/median"), [])
        self.assertTrue(record["admitted"])
        self.assertEqual(record["namespace"], "stats")
        self.assertEqual(record["governing_policy"], DEFAULT_HASH.hex())
        self.assertEqual(record["chain"], [DEFAULT_HASH.hex()])
        self.assertFalse(record["policy_leaf"])

    def test_rule_1_refuses_a_proposal_that_raced_a_policy_rebind(self):
        governing = policy(statement="in force")
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(candidate("stats/median"), [bound("stats", governing)])
        self.assertEqual(caught.exception.rule, 1)
        self.assertIn("is not the governing policy", str(caught.exception))
        # And carrying the new ref admits.
        self.assertTrue(
            bindings.admit(
                candidate("stats/median", policy_ref=policies.policy_hash(governing)),
                [bound("stats", governing)],
            )["admitted"]
        )

    def test_rule_1_refuses_a_policy_object_that_does_not_hash_to_its_binding(self):
        lie = bindings.PolicyBinding("stats", bytes([0xFF]) * 32, policy(statement="x"))
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(candidate("stats/median"), [lie])
        self.assertEqual(caught.exception.rule, 1)

    def test_rule_2_freezes_a_descendant_whose_ancestor_tightened_under_it(self):
        # `stats` permits 5 assumptions, root permits 1: `stats` no longer
        # dominates the policy governing it, so bindings under it freeze.
        loose = policy(statement="loose")
        strict = policy(max_lease=1000)
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(
                candidate("stats/median", policy_ref=policies.policy_hash(loose)),
                [bound("stats", loose), bound("", strict)],
            )
        self.assertEqual(caught.exception.rule, 2)
        self.assertIn("frozen", str(caught.exception))

    def test_rule_3_requires_an_entry_for_every_obligation_the_policy_injects(self):
        governing = policy(require=[["no-panic", "Evaluation never traps."]])
        reference = policies.policy_hash(governing)
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(
                candidate("stats/median", policy_ref=reference), [bound("stats", governing)]
            )
        self.assertEqual(caught.exception.rule, 3)
        self.assertIn("property.no-panic", str(caught.exception))
        # An A0 assumption is an entry, and §5.3.1 says that suffices when no
        # rule demands more.
        record = bindings.admit(
            candidate(
                "stats/median", policy_ref=reference, evidence=[["property.no-panic", A0]]
            ),
            [bound("stats", governing)],
        )
        self.assertEqual(record["injected"], ["no-panic"])

    def test_rule_3_applies_every_matching_rule_conjunctively(self):
        governing = policy(
            rules=[
                [[], [1, [1, 100], [9, 10], GEN_A]],
                [[0], [1, [1, 2000], [99, 100], GEN_A]],
            ]
        )
        reference = policies.policy_hash(governing)
        # Satisfies the broad rule but not the tighter `ensures` one.
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(
                candidate(
                    "stats/median",
                    policy_ref=reference,
                    evidence=[["ensures.sorted", a1((1, 500), (19, 20))]],
                ),
                [bound("stats", governing)],
            )
        self.assertEqual(caught.exception.rule, 3)
        # A3 is above every A1 point, so it satisfies both rules at once.
        record = bindings.admit(
            candidate(
                "stats/median", policy_ref=reference, evidence=[["ensures.sorted", A3]]
            ),
            [bound("stats", governing)],
        )
        self.assertEqual(record["rules_applied"], 2)

    def test_rule_4_refuses_rather_than_admitting_an_unenforceable_key(self):
        for key, keyword in [
            (2, {"max_assumptions": 0}),
            (3, {"by_ability": [[GEN_A, 1]]}),
            (4, {"signers": [ALICE]}),
        ]:
            governing = policy(**keyword)
            with self.assertRaises(bindings.BindingRefused) as caught:
                bindings.admit(
                    candidate("stats/median", policy_ref=policies.policy_hash(governing)),
                    [bound("stats", governing)],
                )
            self.assertEqual(caught.exception.rule, 4)
            self.assertIn(f"key {key}", str(caught.exception))
            self.assertIn("unenforced", str(caught.exception))

    def test_rule_5_refuses_a_weaker_bound_and_a_lower_confidence(self):
        for worse in [a1((1, 100), (99, 100)), a1((1, 2000), (9, 10))]:
            previous = bindings.Previous(
                def_hash=bytes([1]) * 32,
                evidence=[["ensures.sorted", a1((1, 2000), (99, 100))]],
                policy_ref=DEFAULT_HASH,
                seq=1,
            )
            with self.assertRaises(bindings.BindingRefused) as caught:
                bindings.admit(
                    candidate("stats/median", evidence=[["ensures.sorted", worse]]),
                    [],
                    previous,
                )
            self.assertEqual(caught.exception.rule, 5)
            self.assertIn("weaker", str(caught.exception))

    def test_rule_5_refuses_an_incomparable_generator_and_says_which_case_it_is(self):
        previous = bindings.Previous(
            def_hash=bytes([1]) * 32,
            evidence=[["ensures.sorted", a1((1, 2000), (99, 100), GEN_A)]],
            policy_ref=DEFAULT_HASH,
            seq=1,
        )
        # Numerically better, different generator: still not a statement about
        # the distribution the previous binding was cleared against.
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(
                candidate(
                    "stats/median",
                    evidence=[["ensures.sorted", a1((1, 9000), (999, 1000), GEN_B)]],
                ),
                [],
                previous,
            )
        self.assertEqual(caught.exception.rule, 5)
        self.assertIn("incomparable", str(caught.exception))

    def test_rule_5_admits_a_strictly_higher_level_and_leaves_new_obligations_free(self):
        previous = bindings.Previous(
            def_hash=bytes([1]) * 32,
            evidence=[["ensures.sorted", a1((1, 2000), (99, 100), GEN_A)]],
            policy_ref=DEFAULT_HASH,
            seq=1,
        )
        record = bindings.admit(
            candidate(
                "stats/median",
                evidence=[["ensures.sorted", A2], ["terminates", A0]],
                seq=2,
            ),
            [],
            previous,
        )
        self.assertTrue(record["monotone_checked"])
        self.assertEqual(record["obligations"], ["ensures.sorted", "terminates"])

    def test_rule_6_descent_refuses_a_policy_that_does_not_dominate_its_ancestors(self):
        root = policy(max_lease=1000)
        loose = policy(max_lease=9999)
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(
                policy_candidate("stats/POLICY", loose, policy_ref=policies.policy_hash(root)),
                [bound("", root)],
            )
        self.assertEqual(caught.exception.rule, 6)
        self.assertIn("descent", str(caught.exception))

    def test_rule_6_amendment_refuses_weakening_unless_the_predecessor_says_relax(self):
        strict = policy(max_lease=1000)
        weaker = policy(max_lease=5000)
        previous = bindings.Previous(
            def_hash=policies.policy_hash(strict),
            evidence=[],
            policy_ref=DEFAULT_HASH,
            seq=1,
            object=strict,
        )
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(policy_candidate("stats/POLICY", weaker, seq=2), [], previous)
        self.assertEqual(caught.exception.rule, 6)
        self.assertIn("amendment", str(caught.exception))

        relaxable = policy(max_lease=1000, relax=1)
        previous = bindings.Previous(
            def_hash=policies.policy_hash(relaxable),
            evidence=[],
            policy_ref=DEFAULT_HASH,
            seq=1,
            object=relaxable,
        )
        self.assertTrue(
            bindings.admit(policy_candidate("stats/POLICY", weaker, seq=2), [], previous)[
                "admitted"
            ]
        )

    def test_rule_6_refuses_a_policy_object_that_is_not_the_def_hash_bound(self):
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(
                candidate("stats/POLICY", obj=policy(statement="x"), def_hash=bytes([9]) * 32),
                [],
            )
        self.assertEqual(caught.exception.rule, 6)

    def test_a_policy_leaf_with_no_object_is_refused_rather_than_treated_as_a_definition(self):
        with self.assertRaises(bindings.BindingRefused) as caught:
            bindings.admit(candidate("stats/POLICY"), [])
        self.assertEqual(caught.exception.rule, 6)


class LeaseTest(unittest.TestCase):
    def test_a_policy_stating_neither_key_leases_freely(self):
        cleared = bindings.check_lease("stats", ALICE, 60_000, [])
        self.assertEqual(cleared["policy_ref"], DEFAULT_HASH.hex())
        self.assertFalse(cleared["writers_stated"])
        self.assertIsNone(cleared["max_lease_millis"])

    def test_key_5_refuses_a_principal_outside_the_writers_set(self):
        governing = policy(writers=[ALICE])
        with self.assertRaises(bindings.LeaseRefused) as caught:
            bindings.check_lease("stats", BOB, 1000, [bound("stats", governing)])
        self.assertEqual(caught.exception.reason, "writer")
        self.assertTrue(bindings.check_lease("stats", ALICE, 1000, [bound("stats", governing)]))

    def test_key_6_refuses_an_over_bound_ttl_rather_than_clamping_it(self):
        governing = policy(max_lease=1000)
        with self.assertRaises(bindings.LeaseRefused) as caught:
            bindings.check_lease("stats", ALICE, 1001, [bound("stats", governing)])
        self.assertEqual(caught.exception.reason, "bound")
        self.assertIn("refused rather than clamped", str(caught.exception))
        cleared = bindings.check_lease("stats", ALICE, 1000, [bound("stats", governing)])
        self.assertEqual(cleared["ttl_millis"], 1000)

    def test_the_lease_of_a_namespace_is_governed_by_that_namespaces_own_policy(self):
        # §5.3.3: the lease on `stats/` covers `stats/POLICY` too, so `stats`'s
        # own policy governs it — unlike a `POLICY` *binding*, which resolves
        # strictly above.
        governing = policy(writers=[ALICE])
        cleared = bindings.check_lease("stats", ALICE, 1000, [bound("stats", governing)])
        self.assertEqual(cleared["policy_ref"], policies.policy_hash(governing).hex())


class WireFormatTest(unittest.TestCase):
    """The JSON the Rust store speaks, decoded by `store_admit`."""

    def test_a_policy_object_mirrors_through_json_without_moving_its_hash(self):
        original = policy(rules=[[[0], [1, [1, 2000], [99, 100], GEN_A]]], statement="x")
        mirrored = store_admit.ir_to_json(original)
        self.assertEqual(
            policies.policy_hash(store_admit.json_to_ir(mirrored)),
            policies.policy_hash(original),
        )

    def test_a_mirrored_map_with_a_duplicate_key_is_refused(self):
        with self.assertRaises(ValueError):
            store_admit.json_to_ir({"m": [[0, 1], [0, 2]]})

    def test_an_a1_point_round_trips_its_generator_through_hex(self):
        point = a1((1, 2000), (99, 100))
        self.assertEqual(
            store_admit.point_from_json(store_admit.point_to_json(point), "p"), point
        )

    def test_a_bind_request_decodes_into_the_values_admission_takes(self):
        governing = policy(statement="stats")
        document = {
            "schema": 1,
            "binding": {
                "name_path": "stats/median",
                "def_hash": "de" * 32,
                "evidence": [["ensures.sorted", [3]]],
                "policy_ref": policies.policy_hash(governing).hex(),
                "seq": 4,
                "object": None,
            },
            "policy_bindings": [
                {
                    "namespace": "stats",
                    "hash": policies.policy_hash(governing).hex(),
                    "object": store_admit.ir_to_json(governing),
                }
            ],
            "previous": None,
        }
        record = bindings.admit(*store_admit.bind_request(document))
        self.assertEqual(record["seq"], 4)
        self.assertEqual(record["governing_policy"], policies.policy_hash(governing).hex())

    def test_a_wrong_schema_is_refused_rather_than_read_optimistically(self):
        with self.assertRaises(ValueError):
            store_admit.bind_request({"schema": 99, "binding": {}})


class OracleCommandTest(unittest.TestCase):
    """The two new subcommands, over a real process boundary — the exact seam
    the Rust store uses."""

    def run_oracle(self, *arguments):
        completed = subprocess.run(
            [sys.executable, "-m", "store_admit", *arguments],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode, completed.stdout.strip().splitlines()[-1]

    def test_the_default_policy_command_emits_the_specs_three_bytes(self):
        with tempfile.TemporaryDirectory() as out:
            code, line = self.run_oracle("policy", "--default", "--out", out)
            self.assertEqual(code, 0, line)
            self.assertEqual((Path(out) / "policy.bin").read_bytes(), b"\x82\x06\xa0")
            self.assertIn(DEFAULT_HASH.hex(), line)

    def test_a_refusal_exits_five_and_names_the_rule_it_refused_under(self):
        governing = policy(statement="in force")
        document = {
            "schema": 1,
            "binding": {
                "name_path": "stats/median",
                "def_hash": "de" * 32,
                "evidence": [],
                "policy_ref": DEFAULT_HASH.hex(),
                "seq": 1,
            },
            "policy_bindings": [
                {
                    "namespace": "stats",
                    "hash": policies.policy_hash(governing).hex(),
                    "object": store_admit.ir_to_json(governing),
                }
            ],
        }
        import json

        with tempfile.TemporaryDirectory() as out:
            request = Path(out) / "request.json"
            request.write_text(json.dumps(document), encoding="utf-8")
            code, line = self.run_oracle("bind", str(request))
        self.assertEqual(code, store_admit.EXIT_REFUSED)
        body = json.loads(line)
        self.assertEqual(body["error"], "refused")
        self.assertEqual(body["layer"], "bindings")
        self.assertEqual(body["rule"], 1)

    def test_a_lease_refusal_carries_the_5_3_3_reason_the_store_branches_on(self):
        import json

        governing = policy(max_lease=1000)
        document = {
            "schema": 1,
            "namespace": "stats",
            "principal": ALICE.hex(),
            "ttl_millis": 60_000,
            "policy_bindings": [
                {
                    "namespace": "stats",
                    "hash": policies.policy_hash(governing).hex(),
                    "object": store_admit.ir_to_json(governing),
                }
            ],
        }
        with tempfile.TemporaryDirectory() as out:
            request = Path(out) / "request.json"
            request.write_text(json.dumps(document), encoding="utf-8")
            code, line = self.run_oracle("lease", str(request))
        self.assertEqual(code, store_admit.EXIT_REFUSED)
        body = json.loads(line)
        self.assertEqual(body["layer"], "leases")
        self.assertEqual(body["reason"], "bound")


class ContractCompositionTest(unittest.TestCase):
    def test_admission_records_the_policies_contract_it_composed(self):
        import contracts

        record = bindings.admit(candidate("stats/median"), [])
        self.assertEqual(record["contracts"]["policies"], contracts.version("policies"))

    def test_this_module_reimplements_none_of_the_policies_contract(self):
        """The composition rule, made mechanical: every comparison `bindings`
        makes about policies is a call into `policies`, so the module's source
        must contain no independent domination or lattice arithmetic."""
        source = Path(__file__).with_name("bindings.py").read_text(encoding="utf-8")
        for forbidden in ["def dominates", "def at_least", "def satisfies", "def validate_policy"]:
            self.assertNotIn(forbidden, source)
        for required in [
            "policies.dominates",
            "policies.satisfies",
            "policies.matching_rules",
            "policies.validate_policy",
            "policies.policy_hash",
            "policies.DEFAULT_POLICY",
        ]:
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
