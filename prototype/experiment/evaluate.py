"""R3's funnel: which checker layer a generation dies at, and did it do the job.

The four contract layers (`prototype/contracts.py`) are run in order through
their own published `validate_source` entry points. Nothing is re-implemented
here — the point of the funnel is to measure the layers the prototype actually
ships, and a second copy of any of them would measure the copy instead.

The layers are cumulative by construction (`references.validate_source` re-runs
scope, and every entry point re-parses), so running all four in order costs a
few redundant traversals on a checker that is already fast. Classification is by
*error class*, not by position, which is what makes it robust to that
cumulativeness: a `ScopeError` is a scope failure whichever entry point surfaced
it.

The distribution this produces over grammar-constrained draws is Phase A's
deliverable for Phase B (R2.1): the masker gets built against whichever layer
turns out to kill most generations, rather than against a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import declarations
import references
import scope
import typecheck
from sexpr import ParseError
from transcode import SurfaceError, def_to_surface, transcode_source, type_to_surface

from .prompts import KIND_CORPUS, Task
from .resolver import ExperimentResolver

#: The funnel's stages, in order. A generation's outcome is either `accepted` or
#: the name of the first stage that rejected it.
LAYERS = ("parse", "scope", "references", "typecheck")
ACCEPTED = "accepted"
OUTCOMES = (*LAYERS, ACCEPTED)

_ERROR_LAYER = (
    (ParseError, "parse"),
    (SurfaceError, "parse"),
    (scope.ScopeError, "scope"),
    (references.ReferenceError, "references"),
    (typecheck.TypingError, "typecheck"),
)

#: Layer errors are formatted `path: message`. The path is what R3's error
#: localization wants, and it is explicitly *not* covered by any contract
#: version, so it is recorded as an observation and never asserted on.
_PATH = re.compile(r"^([A-Za-z0-9_.\[\]-]+):\s")

#: Prediction 3 asks whether de Bruijn index errors dominate scope failures.
#: Scope errors that are about an index say so in their path (`…var`, `…tyvar`)
#: or their message. This is a reported heuristic, labelled as one in the report.
_DE_BRUIJN = re.compile(r"\b(index|de bruijn|var|tyvar|binder|depth)\b", re.IGNORECASE)

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n?|\n?\s*```\s*$")


def extract_definition(text: str) -> str:
    """The single normalization applied to every condition's raw output.

    Three steps, all of them generous to unconstrained generation and all of
    them no-ops under the grammar (which emits exactly one canonical form):
    strip a markdown code fence, strip surrounding whitespace, and truncate to
    the first balanced parenthesized form. Without the third step condition 1
    would lose most of its draws to trailing chatter rather than to the
    canonical surface, and R3's parse-acceptance number would be measuring
    politeness. Applied identically to all conditions, so it cannot flatter one.
    """
    stripped = _FENCE.sub("", text).strip()
    depth = 0
    for index, character in enumerate(stripped):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return stripped[: index + 1]
            if depth < 0:
                return stripped[: index + 1]
    return stripped


@dataclass(frozen=True)
class FunnelResult:
    """Where a generation reached, and what it looked like when it got there."""

    outcome: str
    layers_passed: int
    error_class: str = ""
    error_path: str = ""
    error_message: str = ""
    identity: str = ""
    type_surface: str = ""
    canonical_surface: str = ""

    @property
    def accepted(self) -> bool:
        return self.outcome == ACCEPTED

    @property
    def de_bruijn_suspected(self) -> bool:
        if self.outcome != "scope":
            return False
        return bool(_DE_BRUIJN.search(f"{self.error_path} {self.error_message}"))


def _classify(error: Exception) -> str:
    for kind, layer in _ERROR_LAYER:
        if isinstance(error, kind):
            return layer
    return ""


def run_funnel(source: str, resolver: ExperimentResolver) -> FunnelResult:
    """Run one generated surface through parse, scope, references, typecheck."""
    identity = ""
    type_surface = ""
    canonical = ""
    layers_passed = 0
    try:
        # One call for the parse layer: it parses, enforces canonicity, and
        # returns the identity R3's corpus-drawn rule compares against.
        ir, _, identity = transcode_source(source)
        canonical = def_to_surface(ir)
        type_surface = type_to_surface(ir[1])
        layers_passed = 1
        scope.validate_source(source, resolver.operation_arity)
        layers_passed = 2
        references.validate_source(source, resolver.declarations)
        layers_passed = 3
        typecheck.validate_source(source, resolver.declarations, resolver.reference_type)
        layers_passed = 4
    except Exception as error:  # noqa: BLE001 - the layer classes are the taxonomy
        layer = _classify(error)
        if not layer and isinstance(error, (declarations.DeclarationError, LookupError)):
            # A resolver refusal (e.g. a generated definition naming a
            # hallucinated ability/data hash) is that stage's rejection per
            # §2.3.1's report-don't-guess rule — never a harness crash. Found
            # live: the first GPU run died on ability 0x00…01 invented by the
            # model, 552 records in.
            layer = {1: "scope", 2: "references", 3: "typecheck"}.get(layers_passed, "")
        if not layer:
            raise
        message = str(error)
        match = _PATH.match(message)
        return FunnelResult(
            outcome=layer,
            layers_passed=layers_passed,
            error_class=type(error).__name__,
            error_path=match.group(1) if match else "",
            error_message=message,
            identity=identity,
            type_surface=type_surface,
            canonical_surface=canonical,
        )
    return FunnelResult(
        outcome=ACCEPTED,
        layers_passed=4,
        identity=identity,
        type_surface=type_surface,
        canonical_surface=canonical,
    )


@dataclass(frozen=True)
class SemanticResult:
    """R3's semantic-task-success verdict, operationalized before the run.

    `rubric_pending` is not decoration. R3 says the held-out floor is
    "checked-tier plus exact type match, supplemented by a hand-scored rubric on
    a fixed sample — this metric is partly human, stated here so it cannot be
    silently dropped mid-run". The flag rides in every held-out record and is
    counted in the report, so the human half stays visible as an outstanding
    obligation rather than being quietly replaced by the mechanical floor.
    """

    success: bool
    rule: str
    detail: str = ""
    rubric_pending: bool = False


#: `hole`'s term-IR tag (SPEC §2.1 row 11) — the node §5.4 confines to the
#: draft region and forbids as a binding target.
_HOLE_TAG = 11


def _term_has_hole(node) -> bool:
    """True if the term-IR node `node` is a hole, or has one anywhere in its
    subterms.

    Walks exactly the child positions `transcode.term_to_surface` recurses
    into, tag by tag, so it can never wander into a type-IR position (a
    disjoint tag namespace) by accident. A single hit anywhere is enough —
    §5.4 confines a hole-bearing definition to `draft/` regardless of what
    else the term contains or how deep the hole sits.
    """
    tag = node[0]
    if tag == _HOLE_TAG:
        return True
    if tag == 3:  # lam: body
        return _term_has_hole(node[2])
    if tag == 4:  # app: function, argument
        return _term_has_hole(node[1]) or _term_has_hole(node[2])
    if tag == 5:  # let: bound value, body
        return _term_has_hole(node[2]) or _term_has_hole(node[3])
    if tag in (6, 8):  # con, perform: field/argument terms
        return any(_term_has_hole(field) for field in node[3])
    if tag == 7:  # match: scrutinee, each arm's body
        if _term_has_hole(node[1]):
            return True
        return any(_term_has_hole(body) for _, _, body in node[2])
    if tag == 9:  # handle: handled term, each op's body, continuation
        if _term_has_hole(node[2]) or _term_has_hole(node[4]):
            return True
        return any(_term_has_hole(body) for _, body in node[3])
    if tag == 10:  # fix: body, continuation
        return _term_has_hole(node[3]) or _term_has_hole(node[4])
    if tag == 12:  # if: condition, then, else
        return any(_term_has_hole(node[i]) for i in (1, 2, 3))
    return False  # var, ref, lit carry no subterms


def score_semantic(task: Task, funnel: FunnelResult, source: str) -> SemanticResult:
    """Did the generation produce the *asked-for* definition, not just a valid one."""
    if task.kind == KIND_CORPUS:
        matched = bool(task.expected_identity) and funnel.identity == task.expected_identity
        detail = ""
        if not matched:
            detail = f"identity {funnel.identity or '<unparsed>'} != {task.expected_identity}"
        elif source != task.expected_surface:
            # Identity is over canonical bytes; a byte difference at equal
            # identity would mean the parser accepted a non-canonical surface,
            # which is a parser bug and is worth surfacing loudly rather than
            # scoring as a pass.
            detail = "identity matched but surface bytes differ"
            matched = False
        return SemanticResult(success=matched, rule="identity-match", detail=detail)

    if not funnel.accepted:
        return SemanticResult(
            success=False,
            rule="checked+type-exact",
            detail=f"funnel stopped at {funnel.outcome}",
            rubric_pending=False,
        )
    # §5.4: a term containing a hole lives in `draft/` and can never be the
    # target of a binding — so it can never be this floor's success case,
    # whatever its type. Checked before type-exactness because a hole makes
    # the type comparison moot: an eta-skeleton (all lambdas, one bare
    # `(hole GOAL ())`) is accepted and type-exact by construction for any
    # task, so without this clause the floor is met by a definition with no
    # term at all.
    term_ir, _, _ = transcode_source(source)
    if _term_has_hole(term_ir[2]):
        return SemanticResult(
            success=False,
            rule="checked+type-exact",
            detail="term contains a hole (§5.4: draft/ only, never a binding target)",
            rubric_pending=False,
        )
    if funnel.type_surface != task.expected_type_surface:
        return SemanticResult(
            success=False,
            rule="checked+type-exact",
            detail="type mismatch",
            rubric_pending=False,
        )
    return SemanticResult(
        success=True,
        rule="checked+type-exact",
        detail="mechanical floor met; hand-scored rubric outstanding",
        rubric_pending=True,
    )


def narrowing_note(funnel: FunnelResult) -> str:
    """Condition 3's §8.3-style feedback for the next draw.

    Phase A's narrowing is definition-level, which is the whole point of
    condition 3: the previous draw's rejecting layer and its error are handed
    back so the redraw is informed rather than blind. Per-token narrowing is
    Phase B and is deliberately absent.
    """
    if funnel.accepted:
        return ""
    where = f" at {funnel.error_path}" if funnel.error_path else ""
    return (
        f"The previous answer was rejected by the {funnel.outcome} layer{where}: "
        f"{funnel.error_message}\nWrite a different definition that avoids this."
    )


@dataclass
class FunnelTally:
    """Counts by outcome, which is the failure-distribution-by-layer table."""

    counts: dict = field(default_factory=lambda: {outcome: 0 for outcome in OUTCOMES})

    def add(self, outcome: str) -> None:
        self.counts[outcome] = self.counts.get(outcome, 0) + 1

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def share(self, outcome: str) -> float:
        return self.counts.get(outcome, 0) / self.total if self.total else 0.0
