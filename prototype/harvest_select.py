"""Which accepted draws are worth putting back into the loop.

`docs/plans/2026-08-23-diversity-harvest.md` R4 is this module's whole
specification. [`harvest.py`](harvest.py) knows how to re-admit a run's accepted
draws; this module knows which of them are worth admitting, and says why about
the ones it turns away.

The finding it exists for
-------------------------

Across every run this project has recorded, 62 distinct definitions were
accepted by the funnel and **42 of them contain no computation at all** — no
`app`, `ref`, `match`, `perform`, `handle` or `fix` anywhere in the term. 23 of
them *are* a literal. Harvest-everything put 19 such objects into the loop's
store, alongside a two-argument `append` that ignores its first argument — the
exact skeleton the model then reproduced for `heldout/list/reverseThen` and
which the R3 rubric hand-scored 0. Feeding those back is not neutral: it spends
context on worked examples of vacuity.

The three gates
---------------

Each is a total function of the definition's own IR plus the curated corpus.
None reads the task spec, the run's `semantic_success`, or anything held-out —
selection must not be able to launder a semantic judgement into the store, which
is the same line `provenance.observation` draws in the corpus-loop plan.

``G1`` **non-constant.** A body with no `var`, no `ref` and no `perform` has a
value fixed when it was written. It computes nothing and depends on nothing, so
it teaches nothing.

``G2`` **every parameter used.** A body that binds a top-level `lam` parameter
and never references it is a function that discards an input its own type
promised to consume. Checked with a real de Bruijn walk over the IR, mirroring
`scope.check_term`'s binding structure exactly, so this module cannot drift from
the validator's idea of what binds what.

``G3`` **novel structural class.** Two definitions with the same skeleton and
the same normalised type differ only in leaf constants. The second one costs
context and adds no shape, so only the first is admitted. The curated corpus
seeds the occupied classes: a generation structurally identical to a curated
definition is redundant with something already in every prompt.

Why exact classes and not a distance
------------------------------------

The textbook diversity selector is a farthest-point traversal over a structural
distance. It was rejected: a continuous metric needs a threshold or a budget,
and over a pool this size any value would be a parameter fitted to nothing.
Exact structural-class equality is the same idea at distance 0, is a decision
rather than a ranking, has nothing to tune, and lets a report name the class
each rejected candidate collided with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sexpr
import transcode

#: Term tags, by the name `transcode.TERM_TAG` gives them. Read from that table
#: rather than re-listed, so a tag renumbering cannot leave this file quietly
#: analysing the wrong node.
TAG = transcode.TERM_TAG
TAG_NAME = {value: key for key, value in TAG.items()}

#: The tags whose presence anywhere in a body means the body's value is not
#: fixed at write time: it reads a binder, names another object, or performs an
#: ability operation. `con`, `lam`, `let`, `if` and `lit` are all constructions
#: over whatever they contain, so they never make a term non-constant by
#: themselves — `(if (lit bool true) (lit i64 1) (lit i64 0))` is the constant 1.
NON_CONSTANT_TAGS = frozenset({TAG["var"], TAG["ref"], TAG["perform"]})

#: A 64-hex object identity, as it appears inside a type surface. Rewritten to
#: one token so that two definitions over the same data declaration compare
#: equal — the class is about shape, and a hash is a leaf.
_HASH = re.compile(r"[0-9a-f]{64}")
HASH_TOKEN = "#"

POLICY_ALL = "all"
POLICY_DISTINCT_SHAPE = "distinct-shape"
POLICY_SIZE_MATCH = "size-match"

#: Why a candidate was turned away. These strings are the report's vocabulary,
#: so they are named constants rather than literals at the point of rejection.
GATE_EXCLUDED_TASK = "excluded-task"
GATE_CONSTANT = "constant"
GATE_UNUSED_PARAMETER = "unused-parameter"
GATE_REDUNDANT_SHAPE = "redundant-shape"
GATE_OVER_BUDGET = "over-budget"
GATE_ALREADY_HELD = "already-held"
GATE_UNANALYSABLE = "unanalysable"

GATES = (
    GATE_EXCLUDED_TASK,
    GATE_CONSTANT,
    GATE_UNUSED_PARAMETER,
    GATE_REDUNDANT_SHAPE,
    GATE_OVER_BUDGET,
    GATE_ALREADY_HELD,
    GATE_UNANALYSABLE,
)


class SelectionError(ValueError):
    """A policy string that names nothing, or a term this module cannot walk."""


# ---------------------------------------------------------------------------
# Walking a term the way the scope checker does
# ---------------------------------------------------------------------------


def term_children(node, operation_arity=None):
    """`(child, binders_it_introduces)` for every *term* child of `node`.

    This is `scope.check_term`'s binding structure, transposed into data. It is
    written out per tag rather than derived, because the two places that need it
    — the free-variable walk and the skeleton — must agree with the validator
    about which positions are terms and how deep each one sits, and a clever
    generic traversal is exactly how that agreement is lost.

    `handle` is the one form whose binder count is not in the node: an operation
    body binds one variable per operation parameter plus the continuation, and
    the parameter count lives in the ability declaration. `operation_arity` is
    the resolver `harvest.AdmissionContext` already holds; without it a term
    containing a `handle` cannot be analysed, and the caller turns that into a
    named refusal rather than a wrong answer.
    """
    tag = node[0]
    if tag in (TAG["var"], TAG["ref"], TAG["lit"]):
        return []
    if tag == TAG["lam"]:
        return [(node[2], 1)]
    if tag == TAG["app"]:
        return [(node[1], 0), (node[2], 0)]
    if tag == TAG["let"]:
        return [(node[2], 0), (node[3], 1)]
    if tag in (TAG["con"], TAG["perform"]):
        return [(argument, 0) for argument in node[3]]
    if tag == TAG["match"]:
        return [(node[1], 0)] + [(arm[2], arm[1]) for arm in node[2]]
    if tag == TAG["handle"]:
        if operation_arity is None:
            raise SelectionError("a handle needs an ability operation-arity resolver")
        children = [(node[2], 0)]
        for operation in node[3]:
            try:
                parameters = operation_arity(node[1], operation[0])
            except (KeyError, IndexError, LookupError) as error:
                raise SelectionError(f"cannot resolve ability operation: {error}") from None
            children.append((operation[1], parameters + 1))
        children.append((node[4], 1))
        return children
    if tag == TAG["fix"]:
        return [(node[3], 0), (node[4], 1)]
    if tag == TAG["hole"]:
        return [(constraint, 1) for constraint in node[2]]
    if tag == TAG["if"]:
        return [(node[1], 0), (node[2], 0), (node[3], 0)]
    raise SelectionError(f"unknown term tag {tag!r}")


def _walk(node, depth, seen, tags, operation_arity):
    tags.add(node[0])
    if node[0] == TAG["var"]:
        # De Bruijn index `node[1]` at binder depth `depth` names the binder
        # `depth - 1 - index` counted from the outside in, which is the stable
        # identifier a top-level parameter can be tested against.
        seen.add(depth - 1 - node[1])
    for child, binders in term_children(node, operation_arity):
        _walk(child, depth + binders, seen, tags, operation_arity)


def _skeleton(node, operation_arity):
    """The term with every leaf payload erased, as a readable canonical string.

    `(lam (data …) (lam (data …) (let (data …) (var 0) (var 1))))` becomes
    `lam(lam(let(var,var)))`. Indices, hashes, literal values and type
    annotations are all gone; term tags, tree shape and `match` arm binder
    counts survive. Binder counts stay because an arm that binds two fields is a
    structurally different arm from one that binds none.
    """
    tag = node[0]
    name = TAG_NAME[tag]
    if tag in (TAG["var"], TAG["ref"], TAG["lit"]):
        return name
    if tag == TAG["match"]:
        arms = ",".join(
            f"{arm[1]}:{_skeleton(arm[2], operation_arity)}" for arm in node[2]
        )
        return f"match({_skeleton(node[1], operation_arity)};{arms})"
    children = ",".join(
        _skeleton(child, operation_arity) for child, _ in term_children(node, operation_arity)
    )
    return f"{name}({children})"


def normalise_type(type_ir) -> str:
    """The declared type's surface with every object identity collapsed."""
    return _HASH.sub(HASH_TOKEN, transcode.type_to_surface(type_ir))


# ---------------------------------------------------------------------------
# One definition's shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """Everything the gates need to know about one definition."""

    skeleton: str
    normalised_type: str
    is_constant: bool
    unused_parameters: tuple[int, ...]

    @property
    def structural_class(self) -> tuple[str, str]:
        return (self.skeleton, self.normalised_type)


def shape_of(surface: str, operation_arity=None) -> Shape:
    """Analyse one definition surface. Raises `SelectionError` if it cannot."""
    try:
        form = sexpr.parse_all(surface)[0]
        ir = transcode.def_to_ir(form)
    except (sexpr.ParseError, transcode.SurfaceError, IndexError, ValueError) as error:
        raise SelectionError(f"cannot transcode: {error}") from None
    declared_type, body = ir[1], ir[2]

    parameters: list[int] = []
    node = body
    while node[0] == TAG["lam"]:
        parameters.append(len(parameters))
        node = node[2]

    seen: set[int] = set()
    tags: set[int] = set()
    _walk(body, 0, seen, tags, operation_arity)

    return Shape(
        skeleton=_skeleton(body, operation_arity),
        normalised_type=normalise_type(declared_type),
        is_constant=not (tags & NON_CONSTANT_TAGS),
        unused_parameters=tuple(index for index in parameters if index not in seen),
    )


# ---------------------------------------------------------------------------
# The policies
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One distinct accepted identity, at the record that first produced it."""

    identity: str
    task: str
    surface: str


@dataclass
class Selection:
    """What a policy chose, and an audit trail for everything it did not."""

    policy: str
    pool: int = 0
    selected: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    collided_with: dict[str, str] = field(default_factory=dict)
    stages: list[tuple[str, int]] = field(default_factory=list)

    @property
    def identities(self) -> frozenset[str]:
        return frozenset(self.selected)

    def counts(self) -> dict[str, int]:
        tally = {gate: 0 for gate in GATES}
        for gate in self.rejected.values():
            tally[gate] = tally.get(gate, 0) + 1
        return {gate: count for gate, count in tally.items() if count}

    def report(self) -> dict:
        """The `selection` block R5 puts on the harvest's one JSON line."""
        return {
            "policy": self.policy,
            "pool": self.pool,
            "selected": len(self.selected),
            "rejected_by_gate": self.counts(),
            "stages": [{"stage": name, "surviving": n} for name, n in self.stages],
        }


def parse_policy(policy: str) -> tuple[str, int | None]:
    """`"size-match:15"` → `("size-match", 15)`; everything else → `(policy, None)`."""
    if policy in (POLICY_ALL, POLICY_DISTINCT_SHAPE):
        return policy, None
    if policy.startswith(POLICY_SIZE_MATCH + ":"):
        budget = policy.split(":", 1)[1]
        if not budget.isdigit():
            raise SelectionError(f"size-match needs a count, got {budget!r}")
        return POLICY_SIZE_MATCH, int(budget)
    raise SelectionError(
        f"unknown selection policy {policy!r}; expected {POLICY_ALL}, "
        f"{POLICY_DISTINCT_SHAPE}, or {POLICY_SIZE_MATCH}:<n>"
    )


def curated_classes(document: dict, operation_arity=None) -> dict[tuple[str, str], str]:
    """The structural classes the store's *non-generated* definitions occupy.

    Generated objects already in the store are deliberately not counted. If they
    were, a re-harvest of the same pool into the same store would reject every
    candidate as redundant with itself and report `not_selected` where it should
    report `exists` — the idempotence the corpus-loop plan's completion criteria
    require. Content addressing is what keeps the re-harvest free; G3 is about
    what the *curated* corpus already shows.
    """
    occupied: dict[tuple[str, str], str] = {}
    for sidecar in document.get("objects", []):
        if sidecar.get("kind") != "definition":
            continue
        provenance = sidecar.get("provenance") or {}
        if provenance.get("origin") == "generated":
            continue
        try:
            shape = shape_of(sidecar["surface"], operation_arity)
        except SelectionError:
            # A curated object this module cannot walk occupies no class. It
            # cannot: the class is what a candidate is compared against, and an
            # unknown class excludes nothing. Never a crash — the curated corpus
            # is not this module's to validate.
            continue
        occupied.setdefault(shape.structural_class, sidecar.get("name") or sidecar["hash"])
    return occupied


def select(
    policy: str,
    candidates: list[Candidate],
    *,
    occupied: dict[tuple[str, str], str] | None = None,
    already_held: frozenset[str] = frozenset(),
    exclude_task_prefixes: tuple[str, ...] = (),
    operation_arity=None,
) -> Selection:
    """Apply a policy to a pool of candidates, in the pool's canonical order.

    `candidates` arrives in the harvest's canonical records order (R2), which is
    what makes `distinct-shape`'s first-of-a-class rule reproducible. The
    `size-match` policy re-orders by identity — a content hash, so ascending
    order is a sample unbiased with respect to structure — because its job is to
    be a *neutral* draw of the same size, and taking a records-order prefix
    would instead sample the earliest runs.
    """
    name, budget = parse_policy(policy)
    occupied = dict(occupied or {})
    selection = Selection(policy=policy, pool=len(candidates))

    surviving = []
    for candidate in candidates:
        if any(candidate.task.startswith(prefix) for prefix in exclude_task_prefixes):
            selection.rejected[candidate.identity] = GATE_EXCLUDED_TASK
            continue
        surviving.append(candidate)
    selection.stages.append(("pool", len(candidates)))
    if exclude_task_prefixes:
        selection.stages.append(("task-filter", len(surviving)))

    if name == POLICY_ALL:
        selection.selected = [candidate.identity for candidate in surviving]
        selection.stages.append(("selected", len(selection.selected)))
        return selection

    if name == POLICY_SIZE_MATCH:
        # A candidate byte-identical to an object the store already holds does
        # not enter it: content addressing dedupes it into the curated object,
        # which keeps its own origin and name. Such a candidate must therefore
        # not consume budget, or the control arm silently lands fewer generated
        # definitions than the arm it is supposed to size-match — which is
        # exactly what a first attempt at 15 did, landing 13.
        fresh = []
        for candidate in surviving:
            if candidate.identity in already_held:
                selection.rejected[candidate.identity] = GATE_ALREADY_HELD
            else:
                fresh.append(candidate)
        if len(fresh) < budget:
            raise SelectionError(
                f"size-match:{budget} but only {len(fresh)} candidates would "
                "enter the store; the control arm cannot reach its size"
            )
        selection.stages.append(("not-already-held", len(fresh)))
        ordered = sorted(fresh, key=lambda candidate: candidate.identity)
        for position, candidate in enumerate(ordered):
            if position >= budget:
                selection.rejected[candidate.identity] = GATE_OVER_BUDGET
        chosen = {candidate.identity for candidate in ordered[:budget]}
        # Emitted in pool order, not hash order, so `sequence` and prompt order
        # stay the harvest's own — the arms must differ in *which* objects, not
        # in what order they are shown.
        selection.selected = [c.identity for c in surviving if c.identity in chosen]
        selection.stages.append(("selected", len(selection.selected)))
        return selection

    # distinct-shape: G1, then G2, then G3, in that order so the report's
    # per-gate tallies are a partition rather than overlapping populations.
    after_g1 = []
    for candidate in surviving:
        try:
            shape = shape_of(candidate.surface, operation_arity)
        except SelectionError:
            selection.rejected[candidate.identity] = GATE_UNANALYSABLE
            continue
        if shape.is_constant:
            selection.rejected[candidate.identity] = GATE_CONSTANT
            continue
        after_g1.append((candidate, shape))
    selection.stages.append(("g1-non-constant", len(after_g1)))

    after_g2 = []
    for candidate, shape in after_g1:
        if shape.unused_parameters:
            selection.rejected[candidate.identity] = GATE_UNUSED_PARAMETER
            continue
        after_g2.append((candidate, shape))
    selection.stages.append(("g2-parameters-used", len(after_g2)))

    for candidate, shape in after_g2:
        collision = occupied.get(shape.structural_class)
        if collision is not None:
            selection.rejected[candidate.identity] = GATE_REDUNDANT_SHAPE
            selection.collided_with[candidate.identity] = collision
            continue
        occupied[shape.structural_class] = candidate.identity
        selection.selected.append(candidate.identity)
    selection.stages.append(("g3-novel-shape", len(selection.selected)))
    return selection
