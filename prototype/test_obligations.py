"""Tests for the emission layer and SPEC.md §3.2.1's exactness rule.

`test_corpus.py` covers what the *manifest* claims about its six pinned
obligations. This file covers `obligations.py`'s own behaviour: the three-way
outcome table, each of the five translation-faithfulness conditions in
isolation, generator faithfulness, and the pipeline's ordering — typing first,
emission after, no solver anywhere.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import corpus_registry
import obligations
import refinements
from corpus_registry import MANIFEST, SMT_INTERPRETATION, SMT_SIGNATURES
from typecheck import TypingError

I64 = [0, 2]
F64 = [0, 3]
BOOL = [0, 1]

_LT = corpus_registry.EXTERN_HASHES["I64.lt"]
_SUB = corpus_registry.EXTERN_HASHES["I64.sub"]
_EQ = corpus_registry.EXTERN_HASHES["I64.eq"]
_SIZE = corpus_registry.EXTERN_HASHES["List.size"]


def _app(head, *arguments):
    for argument in arguments:
        head = [4, head, argument]
    return head


def _i64(value):
    return [2, 2, value]


#: `-1 < v` and `0 < v` over the refined value at index 0.
NAT = _app([1, _LT], _i64(-1), [0, 0])
POS = _app([1, _LT], _i64(0), [0, 0])


def _emit(condition, registry):
    return obligations.emit_condition("test.obligation", condition, registry,
                                      SMT_SIGNATURES, SMT_INTERPRETATION)


class OutcomeTableTest(unittest.TestCase):
    """§3.2.1's verdict table, which is the whole of decision (b)."""

    def test_unsat_proves_whether_or_not_the_script_is_exact(self):
        for exact in (True, False):
            with self.subTest(exact=exact):
                self.assertEqual(obligations.outcome("unsat", exact),
                                 obligations.OUTCOME_PROVED)

    def test_sat_refutes_only_over_an_exact_script(self):
        self.assertEqual(obligations.outcome("sat", True), obligations.OUTCOME_REFUTED)
        self.assertEqual(obligations.outcome("sat", False), obligations.OUTCOME_UNDISCHARGED)

    def test_unknown_and_timeout_are_undischarged_either_way(self):
        for verdict in ("unknown", "timeout"):
            for exact in (True, False):
                with self.subTest(verdict=verdict, exact=exact):
                    self.assertEqual(obligations.outcome(verdict, exact),
                                     obligations.OUTCOME_UNDISCHARGED)

    def test_an_unrecognized_verdict_is_refused_rather_than_bucketed(self):
        # A checker that does not recognize an answer rejects it, the way §6.1.1
        # rejects an unknown estimator tag rather than degrading it.
        with self.assertRaises(ValueError):
            obligations.outcome("sat-ish", True)


class TranslationFaithfulnessTest(unittest.TestCase):
    """One test per §3.2.1 condition, each isolating a single abstraction."""

    def setUp(self):
        self.registry = corpus_registry.registry()

    def test_a_pure_subtyping_pair_is_exact_and_its_sat_would_refute(self):
        # The reference exact script: one Int context variable the domain axiom
        # bounds, one comparison symbol, nothing erased, nothing uninterpreted.
        emitted = _emit(obligations.subtyping_condition(I64, POS, NAT), self.registry)
        self.assertEqual(emitted.exactness.reasons, ())
        self.assertTrue(emitted.exactness.exact)
        self.assertEqual(emitted.outcome("sat"), obligations.OUTCOME_REFUTED)
        self.assertEqual(emitted.outcome("unsat"), obligations.OUTCOME_PROVED)

    def test_an_uninterpreted_reference_makes_the_script_inexact(self):
        # `List.size` is absent from the interpretation table, so the solver
        # invents a function; a model of it says nothing about the real extern.
        condition = obligations.subtyping_condition(
            I64, _app([1, _EQ], [0, 0], _app([1, _SIZE], [0, 1])), NAT,
            outer_context=(corpus_registry._LIST_I64,))
        emitted = _emit(condition, self.registry)
        self.assertTrue(emitted.abstractions.uninterpreted)
        self.assertFalse(emitted.exactness.translation_faithful)
        self.assertEqual(emitted.outcome("sat"), obligations.OUTCOME_UNDISCHARGED)

    def test_an_opaque_sort_makes_the_script_inexact(self):
        # F64 is a declared sort whose equality is bitwise, not IEEE-754, so a
        # model over it is not a valuation of the Loom type.
        condition = obligations.subtyping_condition(
            I64, POS, NAT, outer_context=(F64,))
        emitted = _emit(condition, self.registry)
        self.assertEqual(emitted.abstractions.opaque_sorts, (refinements.SORT_F64,))
        self.assertFalse(emitted.exactness.translation_faithful)
        self.assertEqual(emitted.outcome("sat"), obligations.OUTCOME_UNDISCHARGED)

    def test_an_erased_refinement_makes_the_script_inexact(self):
        # A refinement in a context type is dropped in sort position, so a model
        # may assign a value the predicate forbids.
        condition = obligations.subtyping_condition(
            I64, POS, NAT, outer_context=([3, I64, NAT],))
        emitted = _emit(condition, self.registry)
        self.assertTrue(emitted.abstractions.erased_refinement)
        self.assertFalse(emitted.exactness.translation_faithful)
        self.assertEqual(emitted.outcome("sat"), obligations.OUTCOME_UNDISCHARGED)

    def test_an_idealizing_symbol_makes_the_script_inexact(self):
        # `I64.sub` interprets as `-`, and SMT-LIB `Int` does not wrap, so a
        # model may use an intermediate no execution can produce.
        condition = obligations.subtyping_condition(
            I64, _app([1, _EQ], [0, 0], _app([1, _SUB], _i64(0), [0, 1])), NAT,
            outer_context=(I64,))
        emitted = _emit(condition, self.registry)
        self.assertEqual(emitted.abstractions.idealizing, ("-",))
        self.assertFalse(emitted.exactness.translation_faithful)
        self.assertEqual(emitted.outcome("sat"), obligations.OUTCOME_UNDISCHARGED)

    def test_an_int_sorted_match_binder_makes_the_script_inexact(self):
        # The domain axiom is emitted for context variables only, so a datatype
        # field read out by `match` ranges over all of `Int`.
        goal = [7, [0, 1], [[0, 0, [2, 1, True]],
                            [1, 2, _app([1, _LT], _i64(-1), [0, 1])]]]
        condition = obligations.subtyping_condition(
            I64, POS, goal, outer_context=(corpus_registry._LIST_I64,))
        emitted = _emit(condition, self.registry)
        self.assertTrue(emitted.abstractions.unbounded_int_binder)
        self.assertFalse(emitted.exactness.translation_faithful)
        self.assertEqual(emitted.outcome("sat"), obligations.OUTCOME_UNDISCHARGED)

    def test_every_inexactness_carries_a_stated_reason(self):
        condition = obligations.subtyping_condition(
            I64, _app([1, _EQ], [0, 0], _app([1, _SIZE], [0, 1])), NAT,
            outer_context=(corpus_registry._LIST_I64,))
        emitted = _emit(condition, self.registry)
        self.assertTrue(emitted.exactness.reasons)
        self.assertTrue(all(reason for reason in emitted.exactness.reasons))

    def test_the_faithful_and_idealizing_halves_partition_the_allowlist(self):
        # The exactness rule may not quietly acquire or lose a symbol: every
        # admitted interpreted symbol is classified exactly once.
        faithful = set(refinements.FAITHFUL_SYMBOLS)
        idealizing = set(refinements.IDEALIZING_SYMBOLS)
        self.assertEqual(faithful & idealizing, set())
        self.assertEqual(faithful | idealizing, set(refinements.INTERPRETED_SYMBOLS))


class GeneratorFaithfulnessTest(unittest.TestCase):
    """The half of exactness the translator cannot see."""

    def setUp(self):
        self.registry = corpus_registry.registry()

    def test_an_authored_condition_never_refutes_even_when_exactly_translated(self):
        # Same Γ, H, and g as the subtyping pair above, hence the same script
        # bytes — and a different outcome, because the hypotheses were asserted
        # rather than derived and may not be everything the program establishes.
        derived = _emit(obligations.subtyping_condition(I64, POS, NAT), self.registry)
        authored = _emit(obligations.authored_condition([I64], [POS], NAT), self.registry)
        self.assertEqual(authored.script, derived.script)
        self.assertTrue(authored.exactness.translation_faithful)
        self.assertFalse(authored.exactness.generator_faithful)
        self.assertEqual(authored.outcome("sat"), obligations.OUTCOME_UNDISCHARGED)
        self.assertEqual(derived.outcome("sat"), obligations.OUTCOME_REFUTED)

    def test_an_authored_condition_still_proves_on_unsat(self):
        # The asymmetry is deliberate and narrow: exactness governs the
        # *refutation* direction only, because that is where an abstraction
        # invents a witness out of nothing. An `unsat` under an asserted premise
        # is still a proof — of a claim conditional on that premise, which is an
        # A0 assumption and is accounted for as one (§5.1.3, §5.3.1), not a
        # second job for this rule.
        authored = _emit(obligations.authored_condition([I64], [POS], NAT), self.registry)
        self.assertEqual(authored.outcome("unsat"), obligations.OUTCOME_PROVED)

    def test_an_unknown_producer_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            obligations.VerificationCondition("body-vc", (I64,), (POS,), NAT)


class EmissionPipelineTest(unittest.TestCase):
    """Decision (a): typing emits, a later pass discharges, nothing calls a solver."""

    def setUp(self):
        self.registry = corpus_registry.registry()
        self.reference_type = corpus_registry.reference_type(self.registry)

    def _entry(self, name_path):
        return next(entry for entry in MANIFEST if entry.name_path == name_path)

    def test_emission_yields_id_script_and_hash_triples(self):
        entry = self._entry("corpus/nat/select")
        emitted = obligations.emit_definition(
            entry.source_text(),
            [(o.name, o.condition()) for o in entry.obligations],
            self.registry, self.reference_type, SMT_SIGNATURES, SMT_INTERPRETATION)
        self.assertEqual(len(emitted), len(entry.obligations))
        for produced, declared in zip(emitted, entry.obligations):
            obligation_id, script, digest = produced.triple
            self.assertEqual(obligation_id, declared.name)
            self.assertEqual(digest, declared.script_hash)
            self.assertEqual(refinements.script_hash(script), declared.script_hash)

    def test_a_definition_that_does_not_typecheck_emits_nothing(self):
        # The ordering is the pipeline: obligation emission is a consequence of
        # typing, so an ill-typed definition never reaches the oracle at all.
        # corpus/nat/widenPos is `structural` precisely because §3.3 subsumption
        # is unimplemented, which makes it the case in hand.
        entry = self._entry("corpus/nat/widenPos")
        with self.assertRaises(TypingError):
            obligations.emit_definition(
                entry.source_text(),
                [(o.name, o.condition()) for o in entry.obligations],
                self.registry, self.reference_type, SMT_SIGNATURES, SMT_INTERPRETATION)

    def test_emission_is_deterministic_and_order_preserving(self):
        named = [(o.name, o.condition()) for entry in MANIFEST for o in entry.obligations]
        first = obligations.emit(named, self.registry, SMT_SIGNATURES, SMT_INTERPRETATION)
        second = obligations.emit(named, self.registry, SMT_SIGNATURES, SMT_INTERPRETATION)
        self.assertEqual([e.triple for e in first], [e.triple for e in second])
        self.assertEqual([e.obligation_id for e in first], [name for name, _ in named])

    def test_the_shared_verification_condition_emits_one_ledger_key(self):
        # §6.4's payload key is fixed at emission, before any solver runs, which
        # is what makes the oracle pass a cache lookup first. The two
        # differently named obligations over one VC therefore key one row.
        named = [(o.name, o.condition()) for entry in MANIFEST for o in entry.obligations
                 if entry.name_path in ("corpus/nat/widenPos", "corpus/nat/applyPos")]
        emitted = obligations.emit(named, self.registry, SMT_SIGNATURES, SMT_INTERPRETATION)
        self.assertEqual(len({e.obligation_id for e in emitted}), 2)
        self.assertEqual(len({e.script_hash for e in emitted}), 1)

    def test_the_module_never_shells_out(self):
        # Decision (a) as a property of the source, not a promise in a docstring.
        source = (Path(__file__).parent / "obligations.py").read_text()
        for forbidden in ("subprocess", "shutil.which", "z3", "os.system"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
