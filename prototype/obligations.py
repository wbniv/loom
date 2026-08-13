"""Obligation emission and verdict interpretation (SPEC.md §3.2.1, §3.3, §6.2).

The seam between typing and the oracle. §3.2.1 puts the solver *outside* the
typing loop: the typing layer emits an obligation — fixing its verification
condition, its canonical SMT-LIB script, and that script's SHA-256, which is
already the §6.4 memo-ledger payload key — and stops there. A separate oracle
pass discharges it and mints §6.1 evidence; admission (§5.3.2) consults the
evidence and never the solver. Nothing in this module calls a solver.

The second half of §3.2.1 this module implements is what a verdict *means*. A
solver answer is a fact about a script; the obligation's outcome is three-way,
derived from that fact plus the script's **exactness**. `unsat` proves;
a `sat` over an exact script refutes; everything else — a `sat` over a script
that abstracted something away, `unknown`, a timeout — leaves the obligation
undischarged, to be covered by weaker evidence (§6). The distinction exists
because a model of an abstracted script need not be a valuation of anything
real, and collapsing it into a rejection turns an expressiveness limit into a
refusal of correct code.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import refinements
import typecheck
from declarations import DeclarationRegistry
from refinements import FAITHFUL_SYMBOLS, ObligationTranslator, script_hash

#: §3.2.1 names exactly one v0.1 verification-condition producer: refinement
#: subtyping (§3.3). A condition it produced is *generator-faithful* — `H`
#: carries what the program establishes at that point.
PRODUCER_SUBTYPING = "subtype"

#: A condition whose hypotheses are asserted rather than derived — a hand-written
#: body summary, the only shape available until verification-condition generation
#: for function bodies exists. Emittable and translatable, but a model of it may
#: violate a premise the condition never stated, so it can never refute.
PRODUCER_AUTHORED = "authored"

PRODUCERS = (PRODUCER_SUBTYPING, PRODUCER_AUTHORED)

#: The producers §3.2.1 specifies. Generator faithfulness is membership here.
SPECIFIED_PRODUCERS = (PRODUCER_SUBTYPING,)

#: Raw solver answers. A term outside the fragment yields no script at all, so
#: it has no verdict — `translate` raises `SmtError` and nothing is emitted.
VERDICT_UNSAT = "unsat"
VERDICT_SAT = "sat"
VERDICT_UNKNOWN = "unknown"
VERDICT_TIMEOUT = "timeout"
VERDICTS = (VERDICT_UNSAT, VERDICT_SAT, VERDICT_UNKNOWN, VERDICT_TIMEOUT)

#: §3.2.1's three-way outcome.
OUTCOME_PROVED = "proved"
OUTCOME_REFUTED = "refuted"
OUTCOME_UNDISCHARGED = "undischarged"
OUTCOMES = (OUTCOME_PROVED, OUTCOME_REFUTED, OUTCOME_UNDISCHARGED)


@dataclass(frozen=True)
class Exactness:
    """Whether a model of the script reads back as a valuation of the obligation.

    Two independent parts, because two stages can each introduce an abstraction:
    the obligation-to-condition stage (who built `H`) and the condition-to-script
    stage (what the translator had to approximate).
    """

    generator_faithful: bool
    translation_faithful: bool
    reasons: tuple[str, ...] = ()

    @property
    def exact(self) -> bool:
        return self.generator_faithful and self.translation_faithful


def translation_faithfulness(abstractions: refinements.Abstractions) -> Exactness:
    """§3.2.1's five conditions, read off the translator's own record.

    Returned as an `Exactness` with `generator_faithful` unset (False) so the
    two halves are never confused; `exactness()` combines them.
    """
    reasons: list[str] = []
    if abstractions.uninterpreted:
        reasons.append(
            "uninterpreted references were declared, so the solver may invent a "
            f"function the definition does not compute: {', '.join(abstractions.uninterpreted)}")
    if abstractions.opaque_sorts:
        reasons.append(
            "opaque sorts were declared, and their cardinality and equality are "
            f"not those of the Loom type: {', '.join(abstractions.opaque_sorts)}")
    if abstractions.erased_refinement:
        reasons.append(
            "a refinement was erased in sort position, so a model may assign a "
            "value the predicate forbids")
    idealizing = abstractions.idealizing
    if idealizing:
        reasons.append(
            "SMT-LIB `Int` is unbounded where `I64` wraps, so a model may use an "
            f"intermediate no execution can produce: {', '.join(idealizing)}")
    if abstractions.unbounded_int_binder:
        reasons.append(
            "a `match` bound an `Int`-sorted field, which the I64 domain axiom "
            "does not reach")
    return Exactness(False, not reasons, tuple(reasons))


def exactness(producer: str, abstractions: refinements.Abstractions) -> Exactness:
    """Both halves of §3.2.1's exactness for one emitted script."""
    translation = translation_faithfulness(abstractions)
    faithful_generator = producer in SPECIFIED_PRODUCERS
    reasons = list(translation.reasons)
    if not faithful_generator:
        reasons.insert(0, (
            f"the condition's producer {producer!r} is not one §3.2.1 specifies, "
            "so its hypotheses are asserted rather than derived and a model may "
            "violate a premise they never stated"))
    return Exactness(faithful_generator, translation.translation_faithful, tuple(reasons))


def outcome(verdict: str, exact: bool) -> str:
    """§3.2.1's verdict table: a raw solver answer plus exactness is an outcome."""
    if verdict not in VERDICTS:
        raise ValueError(f"{verdict!r} is not a solver verdict; expected one of {VERDICTS}")
    if verdict == VERDICT_UNSAT:
        return OUTCOME_PROVED
    if verdict == VERDICT_SAT and exact:
        return OUTCOME_REFUTED
    return OUTCOME_UNDISCHARGED


@dataclass(frozen=True)
class VerificationCondition:
    """§3.2.1's `(Γ, H, g)`, with the producer that built it recorded on it.

    The producer is not decoration: it is half of exactness, and the emission
    layer is the only thing that mints a condition, so it is the only thing that
    can stamp one honestly. A condition arriving from anywhere else — a manifest,
    a future body-VC generator this spec version does not name — declares itself
    `authored` and can never ground a refutation.
    """

    producer: str
    context: tuple
    hypotheses: tuple
    goal: list

    def __post_init__(self):
        if self.producer not in PRODUCERS:
            raise ValueError(f"unknown verification-condition producer {self.producer!r}")


def subtyping_condition(base, weaker, stronger, outer_context=()) -> VerificationCondition:
    """`{x:T|weaker} <: {x:T|stronger}` — §3.2.1's one specified producer.

    `Γ = [T]` with any surrounding term context appended after the refined value,
    `H = [weaker]`, `g = stronger`.
    """
    return VerificationCondition(
        PRODUCER_SUBTYPING,
        (copy.deepcopy(base), *copy.deepcopy(tuple(outer_context))),
        (copy.deepcopy(weaker),),
        copy.deepcopy(stronger),
    )


def authored_condition(context, hypotheses, goal) -> VerificationCondition:
    """A condition whose hypotheses are asserted rather than derived."""
    return VerificationCondition(
        PRODUCER_AUTHORED,
        tuple(copy.deepcopy(tuple(context))),
        tuple(copy.deepcopy(tuple(hypotheses))),
        copy.deepcopy(goal),
    )


@dataclass(frozen=True)
class EmittedObligation:
    """One obligation as the oracle pass receives it.

    Everything here is fixed before any solver runs, which is the point: the
    script hash is the §6.4 ledger key, so the pass is a cache lookup first.
    """

    obligation_id: str
    condition: VerificationCondition
    script: str
    script_hash: str
    abstractions: refinements.Abstractions
    exactness: Exactness

    @property
    def triple(self) -> tuple[str, str, str]:
        """`(obligation-id, script, script-hash)` — the emission layer's output."""
        return (self.obligation_id, self.script, self.script_hash)

    def outcome(self, verdict: str) -> str:
        """The §3.2.1 outcome this obligation reaches on a given raw verdict."""
        return outcome(verdict, self.exactness.exact)


def emit_condition(obligation_id: str, condition: VerificationCondition,
                   registry: DeclarationRegistry, signatures=None,
                   interpretations=None) -> EmittedObligation:
    """Translate one verification condition and record what it abstracted away."""
    translator = ObligationTranslator(registry, signatures, interpretations)
    script = translator.script(
        [copy.deepcopy(item) for item in condition.context],
        [copy.deepcopy(item) for item in condition.hypotheses],
        copy.deepcopy(condition.goal),
        obligation_id or "obligation",
    )
    abstractions = translator.abstractions()
    return EmittedObligation(
        obligation_id=obligation_id,
        condition=condition,
        script=script,
        script_hash=script_hash(script),
        abstractions=abstractions,
        exactness=exactness(condition.producer, abstractions),
    )


def emit(named_conditions, registry: DeclarationRegistry, signatures=None,
         interpretations=None) -> tuple[EmittedObligation, ...]:
    """Emit `(obligation-id, VerificationCondition)` pairs, in input order."""
    return tuple(
        emit_condition(obligation_id, condition, registry, signatures, interpretations)
        for obligation_id, condition in named_conditions
    )


def emit_definition(source: str, named_conditions, registry: DeclarationRegistry,
                    reference_type=None, signatures=None,
                    interpretations=None) -> tuple[EmittedObligation, ...]:
    """Typecheck a definition, then emit its obligations.

    The ordering is the pipeline, not a convenience: obligation emission is a
    *consequence* of typing (§3.2.1), so a definition that does not typecheck
    emits nothing and the `TypingError` propagates. Typing itself stays
    solver-free — nothing below this line runs during `validate_source`.
    """
    typecheck.validate_source(source, registry, reference_type)
    return emit(named_conditions, registry, signatures, interpretations)
