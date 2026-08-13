"""Tests for §3.3 refinement subsumption in `typecheck.py`.

`test_corpus.py` covers what the *manifest* claims about the three fixtures
this rule re-tiers (`corpus/math/abs`, `corpus/list/lengthNat`,
`corpus/nat/widenPos`) and how their checker-emitted conditions relate to the
pinned obligations. This file covers the rule itself, in isolation from the
corpus: the erasure-agreement test, the opt-in collector, the `φ = true`
encoding for a missing predicate on either side, and per-position emission
when one type comparison carries more than one differing refinement.

See `docs/plans/2026-08-13-refinement-subsumption.md`.
"""

from __future__ import annotations

import unittest

import corpus_registry
import obligations
from typecheck import TypingError, validate_source

I64 = [0, 2]
BOOL = [0, 1]

_LT_HEX = corpus_registry.EXTERN_HASH_HEX["I64.lt"]
_LT_HASH = corpus_registry.EXTERN_HASHES["I64.lt"]

#: The literal Bool `true` term (§3.2.1: "a bare T is {x:T|true}").
TRUE_TERM = [2, 1, True]


def _app(head, *arguments):
    for argument in arguments:
        head = [4, head, argument]
    return head


def _i64(value):
    return [2, 2, value]


def _lt_surface(bound: int) -> str:
    return f"(app (app (ref 0x{_LT_HEX}) (lit i64 {bound})) (var 0))"


#: `-1 < v` and `0 < v` over the refined value at index 0, as both IR (for
#: comparing an emitted `VerificationCondition`) and surface text (for a
#: `(def ...)` source string) — same predicates the corpus's `_NAT`/`_POS`
#: name, kept local so this file does not reach into `corpus_registry`'s
#: underscored module internals.
NAT_PRED = _app([1, _LT_HASH], _i64(-1), [0, 0])
POS_PRED = _app([1, _LT_HASH], _i64(0), [0, 0])
NAT_SURFACE = f"(refine I64 {_lt_surface(-1)})"
POS_SURFACE = f"(refine I64 {_lt_surface(0)})"


class SubsumptionTest(unittest.TestCase):
    def setUp(self):
        self.registry = corpus_registry.registry()
        self.resolver = corpus_registry.reference_type(self.registry)

    @staticmethod
    def definition(type_surface: str, term_surface: str) -> str:
        return f"(def {type_surface} {term_surface})"

    def test_subsumption_with_a_sink_succeeds_and_emits_the_expected_condition(self):
        # `{x|0<x} <: {x|-1<x}`: the identity function's whole body, `(var
        # 0)`, is the site — its synthesized `pos` disagrees with the
        # declared `nat` codomain by exactly a refinement predicate.
        source = self.definition(f"(fn {POS_SURFACE} () {NAT_SURFACE})", f"(lam {POS_SURFACE} (var 0))")
        sink: list = []
        validate_source(source, self.registry, self.resolver, obligations=sink)
        self.assertEqual(len(sink), 1)
        obligation_id, condition = sink[0]
        self.assertEqual(obligation_id, "subsumption@definition.term.body")
        self.assertEqual(condition, obligations.subtyping_condition(I64, POS_PRED, NAT_PRED))

    def test_subsumption_without_a_sink_still_rejects(self):
        # No collector — explicit `None` and the omitted default both — means
        # subsumption never fires, so this is exactly today's rejection.
        source = self.definition(f"(fn {POS_SURFACE} () {NAT_SURFACE})", f"(lam {POS_SURFACE} (var 0))")
        for call in (
            lambda: validate_source(source, self.registry, self.resolver),
            lambda: validate_source(source, self.registry, self.resolver, obligations=None),
        ):
            with self.assertRaises(TypingError) as caught:
                call()
            self.assertIn("type mismatch", str(caught.exception))

    def test_erased_shape_disagreement_still_rejects_even_with_a_sink(self):
        # `Bool` and `I64` erase to different sorts; no refinement predicate
        # can explain a mismatch here, so a collector changes nothing.
        domain = "(refine Bool (lit bool true))"
        codomain = f"(refine I64 {_lt_surface(-1)})"
        source = self.definition(f"(fn {domain} () {codomain})", f"(lam {domain} (var 0))")
        with self.assertRaises(TypingError) as caught:
            validate_source(source, self.registry, self.resolver, obligations=[])
        self.assertIn("type mismatch", str(caught.exception))

    def test_bare_actual_against_refined_expected_uses_true_as_the_missing_predicate(self):
        # `corpus/math/abs`'s and `corpus/list/lengthNat`'s shape: the body
        # synthesizes a plain `I64`, checked against a refined codomain.
        source = self.definition(f"(fn I64 () {NAT_SURFACE})", "(lam I64 (var 0))")
        sink: list = []
        validate_source(source, self.registry, self.resolver, obligations=sink)
        self.assertEqual(len(sink), 1)
        _, condition = sink[0]
        self.assertEqual(condition.hypotheses, (TRUE_TERM,))
        self.assertEqual(condition.goal, NAT_PRED)

    def test_refined_actual_against_bare_expected_uses_true_as_the_missing_predicate(self):
        # The mirror image — `{x:T|φ} <: T` from SPEC.md §3.3's own statement
        # of the rule — is `ψ = true` on the *expected* side.
        source = self.definition(f"(fn {NAT_SURFACE} () I64)", f"(lam {NAT_SURFACE} (var 0))")
        sink: list = []
        validate_source(source, self.registry, self.resolver, obligations=sink)
        self.assertEqual(len(sink), 1)
        _, condition = sink[0]
        self.assertEqual(condition.hypotheses, (NAT_PRED,))
        self.assertEqual(condition.goal, TRUE_TERM)

    def test_multi_position_emission_within_one_type_comparison(self):
        # `Pair(pos, pos)` checked against `Pair(nat, nat)`: one comparison,
        # two independently differing refinement positions, so §3.2.1's
        # per-position translation unit means two obligations, not one VC
        # covering the whole pair.
        pair = corpus_registry.HASH_HEX["Pair"]
        pos_pair = f"(data 0x{pair} ({POS_SURFACE} {POS_SURFACE}))"
        nat_pair = f"(data 0x{pair} ({NAT_SURFACE} {NAT_SURFACE}))"
        source = self.definition(f"(fn {pos_pair} () {nat_pair})", f"(lam {pos_pair} (var 0))")
        sink: list = []
        validate_source(source, self.registry, self.resolver, obligations=sink)
        self.assertEqual(len(sink), 2)
        obligation_ids = sorted(obligation_id for obligation_id, _ in sink)
        self.assertEqual(obligation_ids, [
            "subsumption@definition.term.body.args[0]",
            "subsumption@definition.term.body.args[1]",
        ])
        for _, condition in sink:
            self.assertEqual(condition.producer, obligations.PRODUCER_SUBTYPING)
            self.assertEqual(condition.context, (I64,))
            self.assertEqual(condition.hypotheses, (POS_PRED,))
            self.assertEqual(condition.goal, NAT_PRED)

    def test_a_matching_type_needs_no_subsumption_and_ignores_the_sink(self):
        # Reflexive case: `nat <: nat` is already structurally equal, so no
        # obligation is emitted even though a collector is present.
        source = self.definition(f"(fn {NAT_SURFACE} () {NAT_SURFACE})", f"(lam {NAT_SURFACE} (var 0))")
        sink: list = []
        validate_source(source, self.registry, self.resolver, obligations=sink)
        self.assertEqual(sink, [])

    def test_emitted_condition_translates_to_a_script(self):
        # The obligation `typecheck.py` emits is a plain
        # `obligations.VerificationCondition` — translating it end to end via
        # `obligations.emit_condition` is the caller's job, not typecheck's
        # (SPEC.md §3.2.1 R1: typing never touches the translator or a
        # solver), but it must still be a well-formed input to that pipeline.
        source = self.definition(f"(fn {POS_SURFACE} () {NAT_SURFACE})", f"(lam {POS_SURFACE} (var 0))")
        sink: list = []
        validate_source(source, self.registry, self.resolver, obligations=sink)
        obligation_id, condition = sink[0]
        emitted = obligations.emit_condition(
            obligation_id, condition, self.registry,
            corpus_registry.SMT_SIGNATURES, corpus_registry.SMT_INTERPRETATION)
        self.assertTrue(emitted.exactness.exact)
        self.assertTrue(emitted.script.startswith("(set-logic ALL)\n"))


if __name__ == "__main__":
    unittest.main()
