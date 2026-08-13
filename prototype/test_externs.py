"""Extern definition objects: SPEC.md §5.1.3 and §11.

Pins the five assumed-base externs tranche 2 of the bootstrap corpus needs,
and asserts the shape rules that keep an extern honest: a closed monomorphic
type, capability-honest effect rows, an ABI identification that is the sole
discriminator, and a body that does not exist.
"""

from __future__ import annotations

import hashlib
import unittest

import cbor_canonical
import corpus_registry
import policies
import prelude
import refinements
from declarations import (
    DeclarationError,
    DeclarationRegistry,
    check_extern_definition,
    declaration_bytes,
    declaration_hash,
)

I64 = [0, 2]
BOOL = [0, 1]
BYTES = [0, 5]

#: The corpus's pinned host-adapter artifact, shared by all five assumed-base externs.
ARTIFACT = corpus_registry.HOST_ARTIFACT


def binary(result):
    return [2, I64, [], [2, I64, [], result]]


class ExternIdentityTest(unittest.TestCase):
    #: The nine assumed-base externs, pinned: the five tranche-2 arithmetic
    #: externs plus the four boolean/comparison externs added alongside
    #: docs/plans/2026-08-13-boolean-base-externs.md. Changing a type, the
    #: artifact, or an ABI selector changes the hash; changing the human name
    #: does not, because the name is a §5.2 meta object and never enters
    #: identity.
    PINNED = {
        "I64.add": "23d1e0891aef622110302fe247b7148de5eb61a09f30138cfe7bd09d6cf7e6d7",
        "I64.sub": "d3914e25a045031ef17d33eb038ca837c40c55642ceeef902b2d046a322f00b5",
        "I64.eq": "4fb7cc71149d69f56fb423f341abd7be1fe28c6e5d92fbdb22485498d1dea41d",
        "I64.lt": "0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965",
        "List.size": "4bd80df0fc10754098795f5fe2bd676a20f933192622f10455b7f55dff5ad5ae",
        "I64.le": "52e63dfa16dffd7ea93f6a9b56a6da10e78c7745fe8a37c4b9e1ec0d859cb53e",
        "Bool.and": "4e303d5118babab70a13f230e374ac4f710b332213056839e9649d14fec5b9e0",
        "Bool.or": "3f146d1cf153175629d4e0c7577f4726854c5bb90328f77de7299c3a1c9989f0",
        "Bool.not": "86b89f7556d56a22c80d71c49651d32d127a5925c1e5b8efddc6297ae9cb52b6",
    }

    def test_the_assumed_base_hashes_are_pinned(self):
        for name in (
            "I64.add", "I64.sub", "I64.eq", "I64.lt", "List.size",
            "I64.le", "Bool.and", "Bool.or", "Bool.not",
        ):
            self.assertEqual(
                corpus_registry.EXTERN_HASH_HEX[name],
                self.PINNED[name],
                f"{name} identity moved",
            )

    def test_identity_is_sha256_of_the_canonical_encoding(self):
        for name, digest in corpus_registry.EXTERN_HASHES.items():
            obj = corpus_registry.extern(name)
            self.assertEqual(hashlib.sha256(cbor_canonical.encode(obj)).digest(), digest)
            self.assertEqual(declaration_hash(obj), digest)

    def test_the_nine_are_distinct_and_disjoint_from_declarations(self):
        externs = set(corpus_registry.EXTERN_HASHES.values())
        self.assertEqual(len(externs), 9)
        self.assertFalse(externs & set(corpus_registry.HASHES.values()))
        self.assertFalse(externs & set(prelude.HASHES.values()))

    def test_the_abi_is_the_only_discriminator_between_same_typed_externs(self):
        # I64.add and I64.sub have byte-identical types and the same artifact.
        add = corpus_registry.extern("I64.add")
        sub = corpus_registry.extern("I64.sub")
        self.assertEqual(add[1], sub[1])
        self.assertEqual(add[2], sub[2])
        self.assertNotEqual(add[3], sub[3])
        self.assertNotEqual(declaration_hash(add), declaration_hash(sub))

    def test_two_externs_agreeing_on_type_artifact_and_abi_are_one_object(self):
        # There is no nominal key, deliberately: an extern is identified by what
        # it calls, so restating the same extern shares one hash and one A0.
        again = [7, binary(I64), ARTIFACT, "i64.add"]
        self.assertEqual(declaration_hash(again), corpus_registry.EXTERN_HASHES["I64.add"])

    def test_the_artifact_is_reproducible_from_the_corpus_prefix(self):
        self.assertEqual(ARTIFACT, hashlib.sha256(b"loom:v0.1:corpus:host").digest())


class ExternShapeTest(unittest.TestCase):
    def test_kind_tag_and_arity_are_enforced(self):
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([0, binary(I64), ARTIFACT, "i64.add"])
        self.assertIn("expected object-kind tag 7", str(ctx.exception))
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, binary(I64), ARTIFACT])
        self.assertIn("expected array length 4", str(ctx.exception))

    def test_declaration_bytes_accepts_kind_7_and_names_the_admitted_kinds(self):
        self.assertEqual(
            declaration_bytes(corpus_registry.extern("I64.eq")),
            cbor_canonical.encode(corpus_registry.extern("I64.eq")),
        )
        with self.assertRaises(DeclarationError) as ctx:
            declaration_bytes([6, {}])
        self.assertIn("expected object kind 4, 5, or 7", str(ctx.exception))

    def test_artifact_must_be_a_32_byte_hash(self):
        for artifact in (b"\x00" * 31, "deadbeef", 0):
            with self.assertRaises(DeclarationError) as ctx:
                check_extern_definition([7, binary(I64), artifact, "i64.add"])
            self.assertIn("extern.artifact", str(ctx.exception))

    def test_abi_must_be_non_empty_nfc_text(self):
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, binary(I64), ARTIFACT, ""])
        self.assertIn("expected non-empty text", str(ctx.exception))
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, binary(I64), ARTIFACT, "i64.ádd"])
        self.assertIn("NFC", str(ctx.exception))
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, binary(I64), ARTIFACT, b"i64.add"])
        self.assertIn("extern.abi", str(ctx.exception))

    def test_polymorphic_externs_are_rejected(self):
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, [6, [2, [5, 0], [], [5, 0]]], ARTIFACT, "id"])
        self.assertIn("may not be polymorphic", str(ctx.exception))

    def test_free_type_variables_and_self_are_rejected(self):
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, [2, [5, 0], [], I64], ARTIFACT, "x"])
        self.assertIn("out of scope at depth 0", str(ctx.exception))
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, [2, [7, []], [], I64], ARTIFACT, "x"])
        self.assertIn("self type is forbidden", str(ctx.exception))

    def test_row_variables_are_rejected(self):
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, [2, I64, [[5, 0]], I64], ARTIFACT, "x"])
        self.assertIn("row type variable is out of scope", str(ctx.exception))

    def test_the_boolean_base_externs_pass_the_validator(self):
        for name in ("I64.le", "Bool.and", "Bool.or", "Bool.not"):
            obj = corpus_registry.extern(name)
            check_extern_definition(obj)
            self.assertEqual(len(declaration_hash(obj)), 32, name)


class ExternCapabilityHonestyTest(unittest.TestCase):
    FFI = prelude.HASHES["ffi"]
    NET = prelude.HASHES["net"]
    CLOCK = prelude.HASHES["clock"]

    def test_an_effectful_extern_must_take_a_matching_cap_parameter(self):
        # `Bytes -{ffi}> Bytes` with no cap: rejected, because §2.4's blast-radius
        # bound would otherwise be escapable through the FFI boundary.
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition([7, [2, BYTES, [self.FFI], BYTES], ARTIFACT, "call"])
        self.assertIn("before taking a matching direct cap parameter", str(ctx.exception))
        self.assertIn(self.FFI.hex(), str(ctx.exception))

    def test_an_effectful_extern_with_its_cap_is_accepted(self):
        obj = [7, [2, [4, self.FFI], [], [2, BYTES, [self.FFI], BYTES]], ARTIFACT, "call"]
        check_extern_definition(obj)
        self.assertEqual(len(declaration_hash(obj)), 32)

    def test_the_cap_must_match_the_ability_in_the_row(self):
        obj = [7, [2, [4, self.NET], [], [2, BYTES, [self.FFI], BYTES]], ARTIFACT, "call"]
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition(obj)
        self.assertIn(self.FFI.hex(), str(ctx.exception))

    def test_a_cap_in_the_result_does_not_discharge_the_row(self):
        # Returning a capability is not receiving one.
        obj = [7, [2, BYTES, [self.FFI], [4, self.FFI]], ARTIFACT, "call"]
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition(obj)
        self.assertIn("before taking a matching direct cap parameter", str(ctx.exception))

    def test_a_capability_buried_in_a_callback_is_not_available(self):
        callback = [2, [4, self.FFI], [], [0, 0]]
        obj = [7, [2, callback, [self.FFI], [0, 0]], ARTIFACT, "call"]
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition(obj)
        self.assertIn("matching direct cap parameter", str(ctx.exception))

    def test_a_later_curried_capability_cannot_authorize_an_earlier_effect(self):
        obj = [7, [2, BYTES, [self.FFI], [2, [4, self.FFI], [], BYTES]], ARTIFACT, "call"]
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition(obj)
        self.assertIn("matching direct cap parameter", str(ctx.exception))

    def test_direct_capabilities_authorize_the_current_and_later_arrows(self):
        obj = [7, [2, [4, self.FFI], [self.FFI], [2, BYTES, [self.FFI], BYTES]], ARTIFACT, "call"]
        check_extern_definition(obj)

    def test_a_callback_only_extern_is_unwritable(self):
        # `fn (fn (cap clock) () Unit) {clock} Unit` (§5.1.3): the extern
        # invokes an effectful callback, so `clock` occurs in the extern's own
        # row, but the only `cap clock` in sight is buried in the callback's
        # domain rather than taken directly — rejected, same as any other
        # buried cap.
        callback = [2, [4, self.CLOCK], [], [0, 0]]
        obj = [7, [2, callback, [self.CLOCK], [0, 0]], ARTIFACT, "call"]
        with self.assertRaises(DeclarationError) as ctx:
            check_extern_definition(obj)
        self.assertIn("matching direct cap parameter", str(ctx.exception))

    def test_a_callback_extern_with_its_own_direct_cap_is_accepted(self):
        # Same callback and the same row, but the extern also takes `cap
        # clock` directly, earlier in the spine — it now holds the authority
        # it exercises when it invokes the callback.
        callback = [2, [4, self.CLOCK], [], [0, 0]]
        obj = [7, [2, [4, self.CLOCK], [], [2, callback, [self.CLOCK], [0, 0]]], ARTIFACT, "call"]
        check_extern_definition(obj)

    def test_the_nine_assumed_base_externs_are_pure_typed(self):
        # Every arrow carries the empty row, which is what §3.2.1 requires of a
        # `ref` in a predicate — and is itself the A0 assumption being signed.
        expected = {
            "I64.add": binary(I64),
            "I64.sub": binary(I64),
            "I64.eq": binary(BOOL),
            "I64.lt": binary(BOOL),
            "List.size": [2, [1, corpus_registry.HASHES["List"], [I64]], [], I64],
            "I64.le": binary(BOOL),
            "Bool.and": [2, BOOL, [], [2, BOOL, [], BOOL]],
            "Bool.or": [2, BOOL, [], [2, BOOL, [], BOOL]],
            "Bool.not": [2, BOOL, [], BOOL],
        }
        for name, type_ir in expected.items():
            self.assertEqual(corpus_registry.extern(name)[1], type_ir, name)


class ExternRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = corpus_registry.registry()

    def test_externs_resolve_by_hash_with_type_artifact_and_abi(self):
        info = self.registry.extern(corpus_registry.EXTERN_HASHES["List.size"])
        self.assertEqual(info.type, [2, [1, corpus_registry.HASHES["List"], [I64]], [], I64])
        self.assertEqual(info.artifact, ARTIFACT)
        self.assertEqual(info.abi, "list.size")

    def test_reference_type_is_what_a_ref_to_an_extern_has(self):
        digest = corpus_registry.EXTERN_HASHES["I64.lt"]
        self.assertEqual(self.registry.reference_type(digest), binary(BOOL))

    def test_the_boolean_base_externs_resolve_by_hash(self):
        for name, expected_type, abi in (
            ("Bool.and", [2, BOOL, [], [2, BOOL, [], BOOL]], "bool.and"),
            ("Bool.or", [2, BOOL, [], [2, BOOL, [], BOOL]], "bool.or"),
            ("Bool.not", [2, BOOL, [], BOOL], "bool.not"),
            ("I64.le", binary(BOOL), "i64.le"),
        ):
            digest = corpus_registry.EXTERN_HASHES[name]
            info = self.registry.extern(digest)
            self.assertEqual(info.type, expected_type, name)
            self.assertEqual(info.artifact, ARTIFACT, name)
            self.assertEqual(info.abi, abi, name)
            self.assertEqual(self.registry.reference_type(digest), expected_type, name)

    def test_a_resolved_extern_object_is_isolated_from_the_registry(self):
        digest = corpus_registry.EXTERN_HASHES["I64.add"]
        obj = self.registry.extern_object(digest)
        obj[3] = "mutated"
        self.assertEqual(self.registry.extern(digest).abi, "i64.add")

    def test_wrong_kind_and_missing_lookups_are_path_aware(self):
        with self.assertRaises(DeclarationError) as ctx:
            self.registry.extern(corpus_registry.HASHES["List"])
        self.assertIn("is object kind 4, not extern", str(ctx.exception))
        with self.assertRaises(DeclarationError) as ctx:
            self.registry.extern(b"\x11" * 32)
        self.assertIn("missing extern declaration", str(ctx.exception))
        with self.assertRaises(DeclarationError) as ctx:
            self.registry.data(corpus_registry.EXTERN_HASHES["I64.add"])
        self.assertIn("is object kind 7, not data", str(ctx.exception))

    def test_registering_under_a_wrong_expected_hash_is_refused(self):
        registry = DeclarationRegistry()
        with self.assertRaises(DeclarationError) as ctx:
            registry.add(corpus_registry.extern("I64.add"), expected_hash=b"\x00" * 32)
        self.assertIn("does not match canonical hash", str(ctx.exception))


class ExternObligationTest(unittest.TestCase):
    """§5.1.3/§5.3.1: `extern` is kind tag 4 in the closed obligation registry,
    and A0 is the only level it can ever reach."""

    def test_extern_is_in_the_closed_obligation_kind_registry(self):
        self.assertEqual(policies.OBLIGATION_KINDS[4], "extern")
        self.assertEqual(policies.decompose_obligation_id("extern"), (4, None))

    def test_a_policy_may_select_the_extern_kind(self):
        policies.validate_policy([6, {0: [[[4], [0]]]}])
        tag, detail = policies.decompose_obligation_id("extern")
        self.assertTrue(policies.selector_matches([4], tag, detail))
        self.assertTrue(policies.selector_matches([], tag, detail))
        self.assertFalse(policies.selector_matches([0], tag, detail))

    def test_requiring_a1_on_externs_forbids_them(self):
        # An A0 assumption cannot satisfy a requirement above A0, so a namespace
        # stating this rule admits no binding that reaches an extern.
        requirement = [3]
        self.assertFalse(policies.satisfies([0], requirement))
        self.assertTrue(policies.satisfies([0], [0]))


class ExternSmtInterpretationTest(unittest.TestCase):
    """§3.2.1: an extern `ref` is uninterpreted by default, and the toolchain
    interpretation table is what makes tranche-2 arithmetic provable."""

    def setUp(self):
        self.registry = corpus_registry.registry()
        self.add = corpus_registry.EXTERN_HASHES["I64.add"]
        self.eq = corpus_registry.EXTERN_HASHES["I64.eq"]
        # The signature table is read straight off the extern objects: the
        # translator never guesses a reference's type, and an extern is where a
        # bodyless reference's type comes from.
        self.signatures = {
            digest: self.registry.reference_type(digest)
            for digest in corpus_registry.EXTERN_HASHES.values()
        }

    def _goal(self):
        """`I64.eq (I64.add x0 0) x0`, a saturated spine of two extern refs."""
        add_call = [4, [4, [1, self.add], [0, 0]], [2, 2, 0]]
        return [4, [4, [1, self.eq], add_call], [0, 0]]

    def test_an_uninterpreted_extern_ref_becomes_a_declare_fun(self):
        script = refinements.subtype_script(
            I64, [2, 1, True], self._goal(), self.registry, signatures=self.signatures
        )
        self.assertIn(f"(declare-fun loom.f{self.add.hex()} (Int Int) Int)", script)
        self.assertIn(f"(declare-fun loom.f{self.eq.hex()} (Int Int) Bool)", script)

    def test_the_interpretation_table_maps_an_extern_hash_onto_the_allowlist(self):
        script = refinements.subtype_script(
            I64,
            [2, 1, True],
            self._goal(),
            self.registry,
            signatures=self.signatures,
            interpretations=dict(corpus_registry.SMT_INTERPRETATION),
        )
        self.assertNotIn("declare-fun", script)
        self.assertIn("(= (+ loom.x0 0) loom.x0)", script)

    def test_list_size_is_deliberately_left_uninterpreted(self):
        self.assertNotIn(
            corpus_registry.EXTERN_HASHES["List.size"],
            corpus_registry.SMT_INTERPRETATION,
        )


class ExternConjunctionDemonstrationTest(unittest.TestCase):
    """docs/plans/2026-08-13-boolean-base-externs.md: the predicate tranche 4's
    `nat/select` obligation says it cannot state — two `nat`-style comparisons
    conjoined into one hypothesis — is now expressible, because `Bool.and` gives
    `and` a definition to interpret. `nat` stays spelled `-1 < i` (§3.2.1's
    interpreted `<` extern, unchanged); what is new is joining two of them with
    one `and` rather than needing two separate hypotheses.

    This does not touch `corpus_registry.MANIFEST` or `test_corpus.py` — the
    corpus fixtures are a concurrent tranche-4 agent's — it only demonstrates
    the translation is now reachable, and that it is deterministic.
    """

    def setUp(self):
        self.registry = corpus_registry.registry()
        self.and_ = corpus_registry.EXTERN_HASHES["Bool.and"]
        self.lt = corpus_registry.EXTERN_HASHES["I64.lt"]
        self.signatures = {
            digest: self.registry.reference_type(digest)
            for digest in corpus_registry.EXTERN_HASHES.values()
        }
        self.interpretations = dict(corpus_registry.SMT_INTERPRETATION)

    def _nat(self, var_index):
        """`-1 < (var var_index)`, the corpus's existing `nat` spelling."""
        return [4, [4, [1, self.lt], [2, 2, -1]], [0, var_index]]

    def _hypothesis(self):
        """`(-1 < a) and (-1 < b)`, two branch values' `nat` conditions
        conjoined in one hypothesis — exactly what `nat/select`'s obligation
        note says the assumed base could not previously state."""
        return [4, [4, [1, self.and_], self._nat(1)], self._nat(2)]

    def _script(self):
        # base = I64 (the refined value, index 0, unused by this demonstration);
        # outer_context = (I64 a, I64 b) at indices 1 and 2. Proving the goal
        # `-1 < a` from the conjoined hypothesis is the smallest instance of the
        # shape nat/select needs: recovering one erased branch fact from a
        # multi-part hypothesis, rather than the single hypothesis §3.2.1's VC
        # shape carries without `and`.
        return refinements.subtype_script(
            I64,
            self._hypothesis(),
            self._nat(1),
            self.registry,
            signatures=self.signatures,
            interpretations=self.interpretations,
            outer_context=(I64, I64),
        )

    def test_the_conjoined_hypothesis_translates_using_the_new_extern_hashes(self):
        script = self._script()
        # No `declare-fun` at all: both `Bool.and` and `I64.lt` are interpreted,
        # so the conjoined hypothesis is pure Core/Ints vocabulary, not two
        # uninterpreted references the solver could only relate by congruence.
        self.assertNotIn("declare-fun", script)
        self.assertIn("(assert (and (< (- 1) loom.x1) (< (- 1) loom.x2)))", script)
        self.assertIn("(assert (not (< (- 1) loom.x1)))", script)

    def test_the_script_is_deterministic(self):
        first = self._script()
        second = self._script()
        self.assertEqual(first, second)
        self.assertEqual(refinements.script_hash(first), refinements.script_hash(second))


if __name__ == "__main__":
    unittest.main()
