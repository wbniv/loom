"""R2's two-layer mask: syntax feasibility plus an incremental type state.

The interface the plan asks for is one question, asked once per decoding step:
*given the tokens emitted so far, which next tokens keep this prefix extendable
to an accepted definition?* Two layers answer it.

**Syntax** — `gbnf.Grammar`, the incremental byte-level prefix oracle over
`loom.gbnf`. A token is syntactically feasible when feeding its bytes leaves the
automaton alive.

**Type state** — `TypeState`, a structural scanner over the same byte stream
that knows, at every byte, which grammar atom is being written (a hash, a
`var` index, a `tyvar` index, a head keyword, a literal payload), what the de
Bruijn binder depths are there, and — since B2 — what *goal type* the checker
will demand at that position. Pruners are pluggable checks over that state,
each individually toggleable and individually timed (R3).

The goal type, and why a left-to-right scanner can have one (B2)
----------------------------------------------------------------
`root ::= "(def " type " " term ")"`, so a definition's **declared type is
complete before its term begins**. That single structural fact is what makes
type-goal tracking possible from a byte prefix at all: at the moment the term
starts, `TypeState` has the declared type in hand, parses it once, peels its
prenex `forall`s exactly as `MatchChecker.check_definition` does, and carries
the result as the term's goal. From there the goal descends by the checker's own
*checking-mode* rules and by nothing else — `lam` splits a `fn` goal into domain
and codomain, `if` gives its condition `Bool` and its branches the goal, `match`
arms and `handle` clauses inherit it, `fix` forces its annotation to be it.
Where the checker switches to synthesis (`app`, `let`, a match scrutinee) the
goal is simply unknown and the layer abstains.

One of those abstentions has since been closed, on an **opt-in** layer:
`SpineGoalPruner` (`spine-goal`, not in `PRUNER_NAMES`). An `app` still
propagates no goal, but the frame chain says how many arguments a head is about
to be given, and `synth` tag 4 says the spine's type is the head's *k*-th
codomain — so a `ref` heading a *k*-ary spine can be filtered by codomain even
though the position itself has no goal. See `docs/plans/2026-08-25-mask-spine-
refs.md`.

Phase A's profile is why this is the first thing B2 built: `typecheck` killed
590 of 1,671 grammar-constrained draws — more than any other layer — and its
error localization is dominated by `definition.term` (×330), which is precisely
the position whose goal is known exactly.

**Canonical surfaces are what make a byte-equality veto a proof.**
`transcode.parse_source` refuses any surface that is not `def_to_surface(ir)`,
so an accepted definition's bytes *are* the canonical rendering of its IR. When
the checker forces a sub-type to equal a type we already know (a `lam`
annotation against the goal's domain; a `fix` annotation against the goal
itself), the bytes at that position are therefore determined, and every byte
that differs from the canonical rendering can be refused outright. That is the
single most aggressive prune in the stack: a whole type subtree collapses to one
string.

The soundness rule, which is the whole of R4
--------------------------------------------
A mask may **never** exclude a continuation that some accepted definition would
have used. Everything here is written to that rule:

* **A pruner may veto a byte only when it can prove that no completion of the
  current atom reaches an accepted definition.** That is stronger than "fires
  at atom boundaries" and is what actually makes mid-atom vetoes safe. Both
  shipped pruners have such a proof and it is monotone in the prefix:
  - `ReferenceHashPruner` — a hash atom whose hex prefix extends no known
    digest can never resolve, and `references`/`typecheck` reject an
    unresolvable hash, so no accepted definition contains it.
  - `DeBruijnPruner` — `uint ::= "0" | [1-9][0-9]*` only ever grows, so a
    partial index `v` has minimum completion `v`; once `v ≥ depth`, `scope`
    rejects every completion. The same proof at the *head* atom lets it veto
    the `v` of `var` (or the `t` of `tyvar`) when the depth there is already
    zero — which is also what keeps a mask from ever emptying itself into a
    dead end it created.
* **Where the state cannot prove anything, it abstains.** A `handle` operation
  body binds `parameter_count + 1` variables and the count needs ability
  resolution that is not available from the byte prefix, so the whole subtree
  is marked depth-unknown and the de Bruijn pruner says nothing there. Recorded,
  not forced — R2's "which checker operations cannot run per token" in code.
* **If the type layer would empty a non-empty syntax mask, the step falls back
  to syntax only** and the fallback is counted. Liveness beats aggression, and
  a mask with nothing in it is a dead end the masker created for itself.

Shape, and why it is affordable
-------------------------------
Because both layers are *byte* oracles they compose into one memoized
transition over the pair `(grammar state, type state)`, and a step is a single
depth-first walk of a trie over the token pieces. A byte the mask refuses cuts
that byte's entire subtree in one transition and charges it to the refusing
layer, so per-token cost tracks what survives rather than the size of the
vocabulary — which is what makes a 151k-token vocabulary tractable in Python at
all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

import sexpr
import transcode
from scope import forall_prefix
# `_erase_refinements` is §3.2.1's erasure and is the *only* place it is
# defined. The goal pruner compares types exactly where the checker does, so it
# imports that function rather than carrying a second copy that could drift out
# of step with a contract-versioned validator. Nothing here modifies it.
from typecheck import _erase_refinements

from .gbnf import Grammar, loom_grammar

# --------------------------------------------------------------------------
# Part kinds — what the scanner expects to see next at a given position
# --------------------------------------------------------------------------

P_DEFINITION = "definition"
P_TYPE = "type"
P_TERM = "term"
P_HASH = "hash"
P_ROW_ELEM = "row-elem"      # an ability hash, or `(tyvar N)`
P_VAR = "uint:var"
P_TYVAR = "uint:tyvar"
P_UINT = "uint:free"         # a uint with no de Bruijn meaning (tags, arities)
P_HEAD = "head"              # the keyword right after `(`
P_LIT_KIND = "lit-kind"
P_NONE = "none"
P_UNKNOWN = "unknown"

P_TYPE_LIST = "type-list"
P_TERM_LIST = "term-list"
P_ARM_LIST = "arm-list"
P_OP_LIST = "op-list"
P_ROW = "row"
P_ARM = "arm"
P_OP = "op"

#: Element kind of each list-shaped form.
LIST_ELEMENT = {
    P_TYPE_LIST: P_TYPE,
    P_TERM_LIST: P_TERM,
    P_ARM_LIST: P_ARM,
    P_OP_LIST: P_OP,
    P_ROW: P_ROW_ELEM,
}

#: A `(` in one of these positions opens a keyword-headed form.
HEADED = frozenset({P_DEFINITION, P_TYPE, P_TERM, P_ROW_ELEM})

#: Atom kinds a pruner can have an opinion about. Used only by the skip filter.
PRUNABLE = frozenset({P_HASH, P_ROW_ELEM, P_VAR, P_TYVAR, P_HEAD})

#: Atom kinds whose *content* some consumer actually reads — the pruners above,
#: plus `_next_part`'s head keyword, literal kind word and match-arm binder
#: count. Everywhere else the scanner keeps one byte (enough to answer "is this
#: atom empty?", which is the only other question asked of it) and drops the
#: rest.
#:
#: This is a correctness-neutral change that is the difference between the
#: masker running and the masker exhausting a 16 GB box. A text literal's
#: payload is `string`, which nothing reads; accumulating it made **every byte
#: of every string a distinct type state**, so the memoized transition shared
#: nothing, the mask cache never hit, and each token inside a literal cost a
#: full walk of the 333k-node vocabulary trie *and* left ~82,000 permanent
#: entries behind. Measured at 147,201 allowed tokens, 326,749 new transitions
#: and +131 MB for a single step; +2.38 GB over 64 characters. With the payload
#: dropped a whole literal collapses to two states (in-string, and in-string
#: after a backslash), so it is walked once and cached.
#:
#: `f64`, `bytes` and `i64` payloads are the same shape — unbounded atoms no
#: consumer reads — and are covered by the same rule.
ATOM_READ = frozenset({P_HEAD, P_LIT_KIND, P_UINT, P_VAR, P_TYVAR, P_HASH, P_ROW_ELEM})

#: Deltas that are not plain integers.
D_PRENEX = "prenex"     # the definition term runs at the type's prenex forall depth
D_ARM = "arm"           # a match arm's body binds the arm's own binder count
D_UNKNOWN = "unknown"   # a handler operation body: parameter_count + 1, unresolvable here

#: `head -> parts after the head`, each `(part kind, term delta, type delta)`.
#: Mirrors `scope.check_type` / `scope.check_term` exactly; the tests pin the
#: correspondence by walking every corpus fixture.
FORMS: dict[str, tuple] = {
    "def": ((P_TYPE, 0, 0), (P_TERM, 0, D_PRENEX)),
    # types
    "data": ((P_HASH, 0, 0), (P_TYPE_LIST, 0, 0)),
    "fn": ((P_TYPE, 0, 0), (P_ROW, 0, 0), (P_TYPE, 0, 0)),
    "refine": ((P_TYPE, 0, 0), (P_TERM, 1, 0)),
    "cap": ((P_HASH, 0, 0),),
    "tyvar": ((P_TYVAR, 0, 0),),
    "forall": ((P_TYPE, 0, 1),),
    # terms
    "var": ((P_VAR, 0, 0),),
    "ref": ((P_HASH, 0, 0),),
    "lit": ((P_LIT_KIND, 0, 0),),
    "lam": ((P_TYPE, 0, 0), (P_TERM, 1, 0)),
    "app": ((P_TERM, 0, 0), (P_TERM, 0, 0)),
    "let": ((P_TYPE, 0, 0), (P_TERM, 0, 0), (P_TERM, 1, 0)),
    "con": ((P_HASH, 0, 0), (P_UINT, 0, 0), (P_TERM_LIST, 0, 0)),
    "match": ((P_TERM, 0, 0), (P_ARM_LIST, 0, 0)),
    "perform": ((P_HASH, 0, 0), (P_UINT, 0, 0), (P_TERM_LIST, 0, 0)),
    "handle": ((P_HASH, 0, 0), (P_TERM, 0, 0), (P_OP_LIST, 0, 0), (P_TERM, 1, 0)),
    "fix": ((P_TYPE, 0, 0), (P_UINT, 0, 0), (P_TERM, 0, 0), (P_TERM, 1, 0)),
    "hole": ((P_TYPE, 0, 0), (P_TERM_LIST, 1, 0)),
    "if": ((P_TERM, 0, 0), (P_TERM, 0, 0), (P_TERM, 0, 0)),
}

#: `arm ::= "(" uint " " uint " " term ")"` — tag, binder count, body.
ARM_PARTS = ((P_UINT, 0, 0), (P_UINT, 0, 0), (P_TERM, D_ARM, 0))
#: `op ::= "(" uint " " term ")"` — the body's depth needs the ability's arity.
OP_PARTS = ((P_UINT, 0, 0), (P_TERM, D_UNKNOWN, 0))

#: `(lit <kind> <payload>)` — the payload's kind is the previous atom's value.
LIT_PAYLOAD = {
    "unit": P_NONE,
    "bool": P_NONE,        # `true`/`false`; nothing to prune
    "i64": P_NONE,
    "f64": P_NONE,         # `0x` + 16 hex — deliberately NOT a hash
    "bytes": P_NONE,       # `0x` + hex pairs — deliberately NOT a hash
    "text": "string",
}

#: The one term head that starts with `v`, and the one type head with `t`.
#: Both facts are asserted in the tests, because the head-level veto below is
#: only sound while they hold.
HEAD_VAR = b"var"
HEAD_TYVAR = b"tyvar"

_PENDING = "pending-head"
_ROOT = "root"

#: The goal an `if` condition carries, in both checking and synthesis mode
#: (`MatchChecker.check` tag 12 and `MatchChecker.synth` tag 12 both check it
#: against `BOOL`). Unconditional, so it is the one goal that needs no goal
#: above it — which is why `.body.condition` (×37 in Phase A) is prunable even
#: inside a term whose own goal is unknown.
BOOL_SURFACE = b"Bool"

#: `(lit <kind> …)` synthesizes `[0, LIT_KIND[kind]]`, and `base` codes agree
#: with literal-kind codes position for position (`transcode.LIT_KIND` /
#: `transcode.BASE_CODE`); `test_masker` pins that correspondence.
LIT_KIND_NAMES = (b"unit", b"bool", b"i64", b"f64", b"text", b"bytes")

#: Every term head, and the refinement-erased goal tag each one *requires*.
#: A head absent from the table can check against any goal, because it reaches
#: the goal through synthesis and synthesis can produce any type.
#:
#: * `lam` — `check` tag 3 takes the function branch only when the goal is a
#:   `fn`; otherwise the synthesized `[2, …]` must still erase to a `fn`.
#: * `fix` — `_check_fix` fails unless the annotation equals the goal *and* the
#:   annotation is a `fn`, so the goal must be one too.
#: * `lit` — synthesizes `[0, k]`, so the goal must erase to a base type.
#: * `con` — `check` tag 6 fails outright unless the goal is nominal.
TERM_HEADS = ("var", "ref", "lit", "lam", "app", "let", "con",
              "match", "perform", "handle", "fix", "hole", "if")
HEAD_REQUIRES_TAG = {"lam": 2, "fix": 2, "lit": 0, "con": 1}


# --------------------------------------------------------------------------
# Goal types, as canonical surface bytes
# --------------------------------------------------------------------------
#
# A goal travels through the state as the *canonical surface bytes* of a type,
# never as an IR list. Two reasons, both load-bearing:
#
# * `TypeState` is a frozen dataclass used as a dictionary key by the mask's
#   memoized transition, so every field it carries must be hashable. An IR node
#   is a list and is not.
# * The bytes are what the byte-equality veto compares against anyway, so the
#   representation the state carries is the representation the pruner uses.
#
# Everything derived from a goal — its tag, its erasure, its domain and
# codomain — is computed once per distinct goal and memoized here.


def _freeze(node):
    """A hashable, comparable image of a type IR. Never raises."""
    if isinstance(node, list):
        return tuple(_freeze(item) for item in node)
    return node


@dataclass(frozen=True)
class _TypeInfo:
    """What a pruner needs to know about one goal type."""

    tag: int                 # the goal's own tag — what the exact rules read
    erased_tag: int          # §3.2.1 erasure's tag — what head feasibility reads
    erased: tuple            # the whole erasure, for equality against a `ref`
    domain: bytes = b""      # `fn` domain, canonically rendered
    codomain: bytes = b""    # `fn` codomain, canonically rendered
    nominal: bytes = b""     # `data` digest as `0x…`, for a `con` head
    base_kind: int = -1      # base-type code, for a `lit` kind word


#: `goal surface -> _TypeInfo | None`. `None` records a goal this layer could
#: not make sense of, and every veto abstains on it.
_TYPE_INFO: dict[bytes, _TypeInfo | None] = {}


def type_info(goal: bytes) -> _TypeInfo | None:
    """Parse one goal surface, once. Returns `None` where anything went wrong.

    Failure is always an abstention, never a veto: a goal this layer cannot
    read is a goal it must have no opinion about.
    """
    if not goal:
        return None
    try:
        return _TYPE_INFO[goal]
    except KeyError:
        pass
    info: _TypeInfo | None
    try:
        ir = transcode.type_to_ir(sexpr.parse_all(goal.decode("utf-8"))[0])
        erased = _erase_refinements(ir)
        info = _TypeInfo(
            tag=ir[0],
            erased_tag=erased[0],
            erased=_freeze(erased),
            domain=(transcode.type_to_surface(ir[1]).encode("utf-8")
                    if ir[0] == 2 else b""),
            codomain=(transcode.type_to_surface(ir[3]).encode("utf-8")
                      if ir[0] == 2 else b""),
            nominal=(b"0x" + ir[1].hex().encode("ascii") if ir[0] == 1 else b""),
            base_kind=ir[1] if ir[0] == 0 else -1,
        )
    except Exception:       # noqa: BLE001 - any surface problem is an abstention
        info = None
    _TYPE_INFO[goal] = info
    return info


#: `declared type surface -> the term's goal surface`. The term of
#: `(def T t)` is checked against `T`'s quantified body, exactly as
#: `MatchChecker.check_definition` does it via `scope.forall_prefix`.
_DECLARED_GOAL: dict[bytes, bytes] = {}


def declared_goal(declared: bytes) -> bytes:
    """The goal `(def T …)`'s term carries, or `b""` when `T` is unreadable."""
    try:
        return _DECLARED_GOAL[declared]
    except KeyError:
        pass
    try:
        ir = transcode.type_to_ir(sexpr.parse_all(declared.decode("utf-8"))[0])
        _, quantified = forall_prefix(ir)
        goal = transcode.type_to_surface(quantified).encode("utf-8")
    except Exception:       # noqa: BLE001 - a rank-2 or malformed type abstains
        goal = b""
    _DECLARED_GOAL[declared] = goal
    return goal


#: Every term head as bytes — the set `_veto_head` needs to tell "this word is a
#: head I have an opinion about" from "this word is something else entirely".
ALL_HEAD_BYTES = frozenset(head.encode("ascii") for head in TERM_HEADS)

_FEASIBLE_HEADS: dict[tuple, frozenset] = {}
_HEAD_PREFIXES: dict[tuple, frozenset] = {}


def _feasible_heads(erased_tag: int | None, ref_ok: bool = True) -> frozenset:
    """The term heads that can check against a goal erasing to this tag.

    `ref_ok` is `False` when the resolver holds no digest whose type could meet
    this goal — then `(ref …)` cannot be written here at all, and refusing the
    head is what keeps the mask from walking into a hash position where it would
    have to refuse every digit and fall back for liveness instead.

    `erased_tag=None` means *no tag constraint at all*: the position's own type
    is unknown, so every head stays feasible and only `ref_ok` narrows the set.
    That is `SpineGoalPruner`'s case — a spine head has no goal of its own, and
    the only thing that layer can prove about it is whether some digest could
    stand there.
    """
    key = (erased_tag, ref_ok)
    try:
        return _FEASIBLE_HEADS[key]
    except KeyError:
        pass
    heads = frozenset(
        head.encode("ascii") for head in TERM_HEADS
        if (erased_tag is None or HEAD_REQUIRES_TAG.get(head, erased_tag) == erased_tag)
        and (ref_ok or head != "ref"))
    _FEASIBLE_HEADS[key] = heads
    return heads


def _head_prefixes(erased_tag: int | None, ref_ok: bool = True) -> frozenset:
    """Every prefix of every term head that can check against this goal tag."""
    key = (erased_tag, ref_ok)
    try:
        return _HEAD_PREFIXES[key]
    except KeyError:
        pass
    prefixes = {b""}
    for head in _feasible_heads(erased_tag, ref_ok):
        for length in range(1, len(head) + 1):
            prefixes.add(head[:length])
    frozen = frozenset(prefixes)
    _HEAD_PREFIXES[key] = frozen
    return frozen


def part_goal(kind: str, goal_in: bytes, part: int) -> tuple:
    """`(goal, forced)` for part `part` of a `kind` form whose goal is `goal_in`.

    This function *is* the correspondence with `typecheck.MatchChecker`, and it
    only ever propagates a goal where the checker is in checking mode with that
    same expected type. `forced` is non-empty only where the checker demands
    byte-for-byte equality with a type already known.

    Deliberately silent — an abstention — everywhere the checker synthesizes:
    `app`'s function and argument, `let`'s bound term and body, a `match`
    scrutinee, `con`/`perform` field arguments, and `hole`'s annotation. Each is
    an entry in the plan's abstention list, not an omission.
    """
    if kind == "if":
        # Unconditional: both `check` and `synth` check the condition against
        # `BOOL`, so this fires even under an unknown goal.
        return (BOOL_SURFACE, b"") if part == 1 else (goal_in, b"")
    if not goal_in:
        return (b"", b"")
    if kind == "lam":
        info = type_info(goal_in)
        if info is not None and info.tag == 2:
            # `check` tag 3: `term[1] != expected[1]` fails outright, with no
            # subsumption or instantiation path behind it — so the annotation's
            # bytes are the goal domain's canonical bytes.
            if part == 1:
                return (info.domain, info.domain)
            if part == 2:
                return (info.codomain, b"")
        return (b"", b"")
    if kind == "fix":
        # `_check_fix`: `annotation != expected` fails outright, so the whole
        # annotation is forced; the body is then checked against it.
        if part == 1:
            return (goal_in, goal_in)
        if part == 4:
            return (goal_in, b"")
        return (b"", b"")
    if kind == "match":
        # `_check_match` with an expected type checks every arm body against it.
        return (goal_in, b"") if part == 2 else (b"", b"")
    if kind == "handle":
        # `_check_handler` checks the return term and every operation clause
        # body against the expected type. The binder *depths* in a clause are
        # still unknown — that abstention is the de Bruijn pruner's and is
        # independent of this one.
        return (goal_in, b"") if part in (3, 4) else (b"", b"")
    if kind in ("ref", "con", "lit") and part == 1:
        return (goal_in, b"")
    # `arm` and `op` are not in `FORMS`, so `_apply_part` indexes their spec by
    # `part` rather than `part - 1`: an arm's body is part 2 of `ARM_PARTS`
    # (tag, binder count, body) and an operation clause's body is part 1 of
    # `OP_PARTS` (index, body). `test_masker` walks both.
    if kind == P_ARM:
        return (goal_in, b"") if part == 2 else (b"", b"")
    if kind == P_OP:
        return (goal_in, b"") if part == 1 else (b"", b"")
    return (b"", b"")


def spine_context(stack: tuple, index: int) -> tuple:
    """`(k, goal)` for the term position that `stack[index]` fills.

    `k` is the arity of the application spine this position heads and `goal` is
    the type the *whole* spine is checked against — the two halves of §2.4's
    rule. Both come from the frame chain, which survives even where the goal
    does not: `_open` stamps every frame with the `goal_in` of the position it
    fills whether or not the checker is in checking mode there, and `app`'s own
    parts propagate no goal at all (which is exactly why `GoalTypePruner`
    abstains here).

    A `(app F A)` frame sits at `part == 1` while `F` is being written and at
    `part == 2` while `A` is. So walking up through consecutive `part == 1`
    ancestors counts the spine, and stops dead at an argument slot::

        (app (app (ref 0x…) a) b)   ->  k = 2, goal = the outer app's goal_in
        (app f (app (ref 0x…) a))   ->  k = 1, goal = b"" (the argument abstains)

    `k == 0` means this is not a spine head at all — `GoalTypePruner`'s veto 5
    already owns that position — and an empty goal means there is nothing to
    prune against. Both are abstentions for every caller.
    """
    k = 0
    goal = b""
    cursor = index - 1
    while cursor >= 0:
        frame = stack[cursor]
        if frame.kind != "app" or frame.part != 1:
            break
        k += 1
        goal = frame.goal_in
        cursor -= 1
    return k, goal


@dataclass(frozen=True)
class Frame:
    """One open parenthesised form, plus the depths in effect inside it."""

    kind: str
    part: int
    part_kind: str
    term_depth: int
    type_depth: int
    unknown: bool
    base_term: int
    base_type: int
    base_unknown: bool
    expected: str = P_UNKNOWN   # what the parent expected here (pending heads)
    prenex_ok: bool = False     # a `forall` opened in this part extends the prenex
    eligible: bool = False      # this frame itself sits in a prenex position
    binders: int = 0            # a match arm's binder count, once read
    lit_kind: str = ""
    goal: bytes = b""           # goal type of the part being written now
    goal_in: bytes = b""        # goal type of the position this frame fills


_ROOT_FRAME = Frame(
    kind=_ROOT, part=0, part_kind=P_DEFINITION,
    term_depth=0, type_depth=0, unknown=False,
    base_term=0, base_type=0, base_unknown=False,
)


@dataclass(frozen=True)
class TypeState:
    """The incremental type state after some prefix of a definition's bytes.

    Immutable by design: `advance` returns a new state, so a candidate token can
    be simulated by advancing a local copy and thrown away for free.
    """

    stack: tuple = (_ROOT_FRAME,)
    atom: bytes = b""
    prenex: int = 0
    in_string: bool = False
    escaped: bool = False
    #: The canonical bytes still owed at a position whose type the checker has
    #: already fixed (a `lam` annotation, a `fix` annotation). Empty everywhere
    #: else. Consumed one byte at a time; a mismatch empties it, so a state
    #: reached by a byte the pruner would have refused simply stops having an
    #: opinion rather than going wrong.
    forced: bytes = b""
    #: The declared type's bytes while `(def T …)`'s `T` is being written.
    #: Cleared the moment `T` closes and becomes the term's goal, so it costs
    #: state distinctness only inside the declared type.
    captured: bytes = b""

    # -- what a pruner reads ---------------------------------------------

    @property
    def top(self) -> Frame:
        return self.stack[-1]

    @property
    def atom_kind(self) -> str:
        return self.stack[-1].part_kind if self.stack else P_UNKNOWN

    @property
    def term_depth(self) -> int:
        return self.stack[-1].term_depth

    @property
    def type_depth(self) -> int:
        return self.stack[-1].type_depth

    @property
    def depth_unknown(self) -> bool:
        return self.stack[-1].unknown

    @property
    def capturing(self) -> bool:
        """True while the bytes being written are `(def T …)`'s declared type."""
        return (len(self.stack) >= 2 and self.stack[1].kind == "def"
                and self.stack[1].part == 1)

    # -- transitions -----------------------------------------------------

    def advance(self, byte: int) -> "TypeState":
        # Hot path: most bytes are atom content, and this runs once per uncached
        # byte of every candidate token, so it builds the successor directly
        # rather than going through `dataclasses.replace`.
        forced = self.forced
        if forced:
            forced = forced[1:] if byte == forced[0] else b""
        if self.in_string:
            return self._advance_string(byte, forced)
        if byte == 0x28:      # (
            return self._open(forced)
        if byte == 0x29:      # )
            return self._close(forced)
        if byte == 0x20:      # space
            return self._next_part(forced)
        captured = self.captured + bytes((byte,)) if self.capturing else self.captured
        if not self.atom and byte == 0x22 and self.stack[-1].part_kind == "string":
            return TypeState(self.stack, b'"', self.prenex, True, False, forced, captured)
        return TypeState(
            self.stack, self._extend(byte), self.prenex, False, False,
            forced, captured)

    def _extend(self, byte: int) -> bytes:
        """The atom after `byte`, keeping only what some consumer will read.

        For an atom kind nobody reads, this keeps the first byte and discards
        the rest: emptiness is the only property still asked of it, and holding
        the content makes every position in a literal a distinct state. See
        `ATOM_READ`.
        """
        if self.stack[-1].part_kind in ATOM_READ:
            return self.atom + bytes((byte,))
        return self.atom or bytes((byte,))

    def _advance_string(self, byte: int, forced: bytes) -> "TypeState":
        # A string payload is never read, so the atom stays at the opening quote
        # and the whole literal is two states rather than one per character.
        atom = self._extend(byte)
        captured = self.captured + bytes((byte,)) if self.capturing else self.captured
        if self.escaped:
            return TypeState(self.stack, atom, self.prenex, True, False, forced, captured)
        if byte == 0x5C:      # backslash
            return TypeState(self.stack, atom, self.prenex, True, True, forced, captured)
        if byte == 0x22:      # closing quote
            return TypeState(self.stack, atom, self.prenex, False, False, forced, captured)
        return TypeState(self.stack, atom, self.prenex, True, False, forced, captured)

    def _open(self, forced: bytes = b"") -> "TypeState":
        top = self.stack[-1]
        expected = top.part_kind
        common = {
            "base_term": top.term_depth,
            "base_type": top.type_depth,
            "base_unknown": top.unknown,
            "expected": expected,
            "eligible": top.prenex_ok,
            "goal_in": top.goal,
        }
        if expected in HEADED:
            child = Frame(
                kind=_PENDING, part=0, part_kind=P_HEAD,
                term_depth=top.term_depth, type_depth=top.type_depth,
                unknown=top.unknown, **common)
        elif expected in LIST_ELEMENT:
            # An arm list and an operation list hand every element the goal the
            # list itself carries; a term list (`con`/`perform` arguments) and a
            # type list do not, because those element types come from a
            # declaration this layer does not consult.
            element_goal = top.goal if expected in (P_ARM_LIST, P_OP_LIST) else b""
            child = Frame(
                kind=expected, part=0, part_kind=LIST_ELEMENT[expected],
                term_depth=top.term_depth, type_depth=top.type_depth,
                unknown=top.unknown, goal=element_goal, **common)
        elif expected in (P_ARM, P_OP):
            parts = ARM_PARTS if expected == P_ARM else OP_PARTS
            child = Frame(
                kind=expected, part=0, part_kind=parts[0][0],
                term_depth=top.term_depth, type_depth=top.type_depth,
                unknown=top.unknown, **common)
        else:
            child = Frame(
                kind=P_UNKNOWN, part=0, part_kind=P_UNKNOWN,
                term_depth=top.term_depth, type_depth=top.type_depth,
                unknown=True, **common)
        captured = self.captured + b"(" if self.capturing else self.captured
        return replace(self, stack=self.stack + (child,), atom=b"",
                       forced=forced, captured=captured)

    def _close(self, forced: bytes = b"") -> "TypeState":
        captured = self.captured + b")" if self.capturing else self.captured
        if len(self.stack) <= 1:
            # Only reachable on input the grammar layer has already refused.
            return replace(self, atom=b"", forced=forced, captured=captured)
        return replace(self, stack=self.stack[:-1], atom=b"", forced=forced,
                       captured=captured)

    def _next_part(self, forced: bytes = b"") -> "TypeState":
        top = self.stack[-1]
        atom, prenex = self.atom, self.prenex
        captured = self.captured + b" " if self.capturing else self.captured

        if top.kind == _PENDING:
            head = atom.decode("utf-8", "replace")
            spec = FORMS.get(head)
            if spec is None:
                resolved = replace(top, kind=P_UNKNOWN, part=1, part_kind=P_UNKNOWN,
                                   unknown=True, goal=b"")
                return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"",
                               forced=forced, captured=captured)
            if head == "forall" and top.eligible:
                prenex += 1
            resolved = replace(top, kind=head, binders=0)
            resolved, opened = self._apply_part(resolved, spec, 1, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"",
                           prenex=prenex, forced=opened or forced, captured=captured)

        if top.kind == "lit" and top.part == 1:
            kind = atom.decode("utf-8", "replace")
            payload = LIT_PAYLOAD.get(kind, P_UNKNOWN)
            resolved = replace(top, part=2, part_kind=payload, lit_kind=kind, goal=b"")
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"",
                           forced=forced, captured=captured)

        if top.kind == P_ARM and top.part == 1:
            try:
                binders = int(atom)
            except ValueError:  # pragma: no cover - grammar guarantees digits
                binders = 0
                top = replace(top, unknown=True)
            resolved = replace(top, binders=binders)
            resolved, opened = self._apply_part(resolved, ARM_PARTS, 2, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"",
                           forced=opened or forced, captured=captured)

        if top.kind in FORMS:
            spec = FORMS[top.kind]
            # `(def T t)`: `T` has just closed, so the term's goal is knowable
            # exactly here and nowhere earlier. The captured bytes are dropped
            # in the same step, so they cost state distinctness only inside `T`.
            declared = b""
            if top.kind == "def" and top.part == 1:
                declared = declared_goal(self.captured)
                captured = b""
            resolved, opened = self._apply_part(
                top, spec, top.part + 1, prenex, declared)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"",
                           forced=opened or forced, captured=captured)
        if top.kind == P_ARM:
            resolved, opened = self._apply_part(top, ARM_PARTS, top.part + 1, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"",
                           forced=opened or forced, captured=captured)
        if top.kind == P_OP:
            resolved, opened = self._apply_part(top, OP_PARTS, top.part + 1, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"",
                           forced=opened or forced, captured=captured)
        if top.kind in LIST_ELEMENT:
            resolved = replace(top, part=top.part + 1)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"",
                           forced=forced, captured=captured)
        return replace(self, atom=b"", forced=forced, captured=captured)

    @staticmethod
    def _apply_part(frame: Frame, spec: tuple, part: int, prenex: int,
                    declared: bytes = b"") -> tuple:
        """`(frame at part `part`, bytes that part is forced to)`.

        `declared` is `(def T …)`'s quantified `T`, supplied only on the step
        that opens the definition's term.
        """
        index = part - 1 if frame.kind in FORMS else part
        if index < 0 or index >= len(spec):
            return replace(frame, part=part, part_kind=P_NONE, goal=b""), b""
        kind, term_delta, type_delta = spec[index]
        unknown = frame.base_unknown
        term_depth = frame.base_term
        if term_delta == D_ARM:
            term_depth += frame.binders
        elif term_delta == D_UNKNOWN:
            unknown = True
        else:
            term_depth += term_delta
        type_depth = frame.base_type
        if type_delta == D_PRENEX:
            type_depth += prenex
        else:
            type_depth += type_delta
        prenex_ok = (frame.kind == "def" and part == 1) or (
            frame.kind == "forall" and part == 1 and frame.eligible)
        if declared:
            goal, forced = declared, b""
        else:
            goal, forced = part_goal(frame.kind, frame.goal_in, part)
        return replace(
            frame, part=part, part_kind=kind, term_depth=term_depth,
            type_depth=type_depth, unknown=unknown, prenex_ok=prenex_ok,
            goal=goal), forced

    def feed(self, data: bytes) -> "TypeState":
        state = self
        for byte in data:
            state = state.advance(byte)
        return state


# --------------------------------------------------------------------------
# Pruners
# --------------------------------------------------------------------------


class Pruner:
    """A pluggable type-state check. `veto` may only refuse under proof."""

    name = "pruner"

    def veto(self, state: TypeState, byte: int) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


def digest_trie(digests, admit) -> tuple:
    """`(prefix set, complete set)` over the digests `admit` keeps.

    The one shape every hash veto in this module uses: a hex atom is refused
    when extending it leaves the prefix set, and a *finished* hex atom is
    refused when it is not in the complete set. `b"0"` seeds the prefix set so
    the leading `0` of `0x…` survives even when nothing is admitted, which
    keeps the veto to "this digest", never "no hash may start here" — the head
    layer is what refuses the position itself.
    """
    prefixes: set[bytes] = {b"", b"0"}
    complete: set[bytes] = set()
    for digest in digests:
        if not admit(digest):
            continue
        text = b"0x" + digest.hex().encode("ascii")
        complete.add(text)
        for length in range(1, len(text) + 1):
            prefixes.add(text[:length])
    return frozenset(prefixes), frozenset(complete)


class ReferenceHashPruner(Pruner):
    """Hash atoms must stay prefixes of a hash the resolver can resolve.

    Every hash in an accepted definition resolves — `references` refuses an
    unknown nominal hash and `typecheck` refuses an unknown `ref` through the
    injected resolver — so a hex prefix that extends no known digest cannot
    appear in any accepted definition. The trie is the union over every kind the
    resolver holds (definitions, data, abilities, externs): a union is a
    superset of the per-position set, and a superset is the safe side.
    Kind-specialising it is a B2 lever, not a B1 one.
    """

    name = "ref-hash"

    name = "ref-hash"

    #: Bytes that end the current atom rather than extending it. A hash atom is
    #: only ever followed by one of these, and the empty row `()` reaches the
    #: pruner with an empty atom — the case that makes "veto anything that is
    #: not a hash prefix" unsound, and the reason the terminator branch exists.
    TERMINATORS = frozenset({0x28, 0x29, 0x20})

    def __init__(self, digests) -> None:
        prefixes: set[bytes] = {b"", b"0"}
        complete: set[bytes] = set()
        for digest in digests:
            text = b"0x" + digest.hex().encode("ascii")
            complete.add(text)
            for length in range(1, len(text) + 1):
                prefixes.add(text[:length])
        self._prefixes = frozenset(prefixes)
        self._complete = frozenset(complete)
        self._max = 66
        self.digests = frozenset(digests)

    def veto(self, state: TypeState, byte: int) -> bool:
        if state.atom_kind not in (P_HASH, P_ROW_ELEM):
            return False
        atom = state.atom
        if byte in self.TERMINATORS:
            # The atom is finished. An empty atom is an empty row or a row
            # variable, neither of which is a hash; a finished hash must be one
            # the resolver holds.
            return bool(atom) and atom not in self._complete
        if len(atom) >= self._max:
            return False
        return atom + bytes((byte,)) not in self._prefixes


class DeBruijnPruner(Pruner):
    """`(var N)` and `(tyvar N)` indices bounded by the binder depth in force.

    Two vetoes, both proofs:

    * mid-index — `uint` only grows, so a partial index `v` extended by digit
      `d` has minimum completion `10·v + d`; once that reaches the depth, every
      completion is out of scope and `scope` rejects it.
    * at the head — when the depth in force is already zero, no `(var …)` (or
      `(tyvar …)`) is in scope at all, so the `v` that would start `var` is
      itself refused. Besides pruning earlier, this is what stops the masker
      from walking into a position whose only continuations it must then veto.

    Abstains wherever the depth is unknown — inside a `handle` operation body,
    whose binder count is `parameter_count + 1` and needs the ability
    declaration, which a byte prefix does not carry.
    """

    name = "de-bruijn"

    @staticmethod
    def _bounded(atom: bytes, byte: int, depth: int) -> bool:
        if not (0x30 <= byte <= 0x39):
            return False
        digit = byte - 0x30
        value = int(atom) if atom else 0
        return value * 10 + digit >= depth

    def veto(self, state: TypeState, byte: int) -> bool:
        if state.depth_unknown:
            return False
        kind = state.atom_kind
        if kind == P_VAR:
            return self._bounded(state.atom, byte, state.term_depth)
        if kind == P_TYVAR:
            return self._bounded(state.atom, byte, state.type_depth)
        if kind == P_HEAD:
            frame = state.top
            if frame.base_unknown:
                return False
            candidate = state.atom + bytes((byte,))
            if frame.expected == P_TERM and HEAD_VAR.startswith(candidate):
                return frame.base_term == 0
            if frame.expected in (P_TYPE, P_ROW_ELEM) and HEAD_TYVAR.startswith(candidate):
                return frame.base_type == 0
        return False


class GoalTypePruner(Pruner):
    """B2's first pruner: the checker's goal type, tracked per byte.

    Phase A's gate put `typecheck` at the top of the failure distribution (590
    of 1,671 grammar-constrained draws, against parse 523, scope 268 and
    references 115), localized overwhelmingly at `definition.term` — the term
    checked against the definition's own declared type. `TypeState` knows that
    type exactly, because `root ::= "(def " type " " term ")"` finishes it before
    the term starts, so this pruner is the direct answer to that row.

    Five vetoes, each with its proof. In every one of them the *goal* is a type
    the checker will demand at that position, computed by `part_goal` from the
    checker's own checking-mode rules.

    1. **A forced type.** `check` tag 3 fails on `term[1] != expected[1]` and
       `_check_fix` fails on `annotation != expected`, both immediately and with
       no subsumption or instantiation path behind them. So a `lam` annotation
       under a `fn` goal, and a `fix` annotation under any goal, must equal a
       type already in hand. `transcode.parse_source` refuses a non-canonical
       surface, so an accepted definition's bytes are the canonical rendering of
       its IR — which makes those bytes *determined*, and every other byte
       refusable. This is the aggressive one: a whole type subtree collapses to
       one string.
    2. **Head feasibility.** `lam` and `fix` need a `fn` goal, `lit` a base goal,
       `con` a nominal one (`HEAD_REQUIRES_TAG`). A byte that no feasible head
       can continue is refused. Every other head reaches its goal through
       synthesis, which can produce any type, so it is always feasible.
    3. **A literal's kind word.** `(lit k …)` synthesizes `[0, k]`, so under a
       base goal the kind word is the goal's own.
    4. **A constructor's data hash.** `check` tag 6 fails unless
       `term[1] == expected[1]`, so under a nominal goal the digest is the
       goal's own.
    5. **A `ref`'s digest, filtered by goal.** A `ref` synthesizes its resolved
       type; the checker then needs equality, first-order instantiation of a
       `forall`, or subsumption — and subsumption's own precondition is that the
       two types agree once refinements are erased. So a digest whose resolved
       type is not quantified *and* erases differently from the goal cannot
       appear here. This is the kind-specialisation B1 left on the table, done
       by type rather than by kind.

    Comparisons are on §3.2.1 **erasure** wherever a refinement could stand
    between the two types, which is what keeps every proof above independent of
    whether a caller supplies `MatchChecker`'s obligation collector.
    `experiment.evaluate.run_funnel` does not supply one — so subsumption never
    actually fires in this experiment — but the vetoes do not rely on that, and
    `test_masker` pins the coupling so a future collector cannot silently
    invalidate them.

    Abstains — recorded, not forced — wherever the checker synthesizes: `app`'s
    function and argument, `let`'s bound term and body, a `match` scrutinee,
    `con`/`perform` field arguments, `hole`'s annotation, and the type of a
    `var`, which needs a binder-type environment this layer does not carry.
    """

    name = "goal-type"

    TERMINATORS = frozenset({0x28, 0x29, 0x20})

    def __init__(self, digests=(), reference_type=None) -> None:
        self._digests = tuple(digests)
        self._reference_type = reference_type
        #: `goal surface -> (prefix set, complete set)`, built on first use at
        #: each distinct goal. A run sees very few distinct goals, so this is a
        #: handful of tries over a few dozen digests, not a per-step cost.
        self._ref_cache: dict[bytes, tuple | None] = {}

    # -- veto ------------------------------------------------------------

    def veto(self, state: TypeState, byte: int) -> bool:
        if state.forced:
            return byte != state.forced[0]
        kind = state.atom_kind
        if kind == P_HEAD:
            return self._veto_head(state, byte)
        if kind == P_LIT_KIND:
            return self._veto_lit_kind(state, byte)
        if kind == P_HASH:
            return self._veto_hash(state, byte)
        return False

    def _veto_head(self, state: TypeState, byte: int) -> bool:
        frame = state.top
        if frame.expected != P_TERM:
            return False
        info = type_info(frame.goal_in)
        if info is None:
            return False
        atom = state.atom
        ref_ok = self._ref_possible(frame.goal_in)
        if byte in self.TERMINATORS:
            # The head atom is finished. Judge the head itself, and only when it
            # is a head at all — a word this layer does not recognise is the
            # grammar's problem, not a proof of anything here.
            return (atom in ALL_HEAD_BYTES
                    and atom not in _feasible_heads(info.erased_tag, ref_ok))
        return atom + bytes((byte,)) not in _head_prefixes(info.erased_tag, ref_ok)

    def _ref_possible(self, goal: bytes) -> bool:
        """Is there any digest a `(ref …)` at this goal could name?"""
        sets = self._ref_sets(goal)
        return sets is None or bool(sets[1])

    def _veto_lit_kind(self, state: TypeState, byte: int) -> bool:
        info = type_info(state.top.goal)
        if info is None or info.erased_tag != 0:
            # A non-base goal already refused the `lit` head; anything else is
            # an unknown goal, and an unknown goal is an abstention.
            return False
        if not 0 <= info.base_kind < len(LIT_KIND_NAMES):
            return False
        return self._veto_against(state.atom, byte, LIT_KIND_NAMES[info.base_kind])

    def _veto_hash(self, state: TypeState, byte: int) -> bool:
        frame = state.top
        if frame.kind == "con":
            info = type_info(frame.goal)
            # `check` tag 6 compares `expected[0] != 1` before anything else, so
            # only a goal that is *literally* nominal fixes the digest.
            if info is None or info.tag != 1 or not info.nominal:
                return False
            return self._veto_against(state.atom, byte, info.nominal)
        if frame.kind == "ref":
            sets = self._ref_sets(frame.goal)
            if sets is None:
                return False
            prefixes, complete = sets
            atom = state.atom
            if byte in self.TERMINATORS:
                return bool(atom) and atom not in complete
            return atom + bytes((byte,)) not in prefixes
        return False

    @staticmethod
    def _veto_against(atom: bytes, byte: int, required: bytes) -> bool:
        """Refuse any byte that walks off `required`, terminators included."""
        if byte in GoalTypePruner.TERMINATORS:
            return bool(atom) and atom != required
        return not required.startswith(atom + bytes((byte,)))

    # -- the goal-filtered digest universe --------------------------------

    def _ref_sets(self, goal: bytes):
        try:
            return self._ref_cache[goal]
        except KeyError:
            pass
        built = self._build_ref_sets(goal)
        self._ref_cache[goal] = built
        return built

    def _build_ref_sets(self, goal: bytes):
        info = type_info(goal)
        if info is None or self._reference_type is None:
            return None
        return digest_trie(
            self._digests, lambda digest: self._compatible(digest, info.erased))

    def _compatible(self, digest: bytes, erased_goal: tuple) -> bool:
        """Could a `ref` to `digest` check against a goal erasing to this?

        Anything the layer cannot decide comes back `True`, because keeping a
        digest is the safe side of R4 and dropping one is not.
        """
        try:
            resolved = self._reference_type(digest)
        except Exception:       # noqa: BLE001 - an unresolvable ref dies anyway
            return False
        if not isinstance(resolved, list) or not resolved:
            return False
        if resolved[0] == 6:
            # §3.1.3 instantiates a quantified type against whatever is
            # expected; deciding that here would be re-implementing
            # `_instantiate`, so every polymorphic definition stays in.
            return True
        try:
            return _freeze(_erase_refinements(resolved)) == erased_goal
        except Exception:       # noqa: BLE001 - an unreadable type stays in
            return True


#: What peeling `k` arrows off a resolved type concluded. `_ABSTAIN` is the
#: only value that must never become a veto.
_PEELED = "peeled"        # the k-th codomain, in hand
_ABSTAIN = "abstain"      # instantiation, or a shape this layer will not judge
_NOT_A_FUNCTION = "not-a-function"   # ran out of arrows before k


def peel_codomain(resolved, k: int) -> tuple:
    """`(verdict, k-th codomain)` for `resolved` applied to `k` arguments.

    Mirrors `MatchChecker.synth` tag 4, which is the whole proof: an
    application synthesizes `copy.deepcopy(function_type[3])` after refusing
    anything whose tag is not 2, and the innermost `synth` of a `(ref …)` is
    `_resolve_reference` **verbatim** — synthesis position never instantiates.
    So the type a `k`-ary spine synthesizes *is* the `k`-th codomain here.

    Stops at `_ABSTAIN` on a `forall`: §3.1.3 instantiation is the one shape
    the language gives a second life to, and deciding it here would mean
    re-implementing `_instantiate`. (`synth` tag 4 in fact rejects a `forall`
    head outright, before instantiation is ever considered — so this
    abstention leaves precision on the table on purpose.)

    Everything else that is not a `fn` — a base type, a nominal, a `cap`, a
    `tyvar`, **and a `refine`** — cannot be applied at all: `synth` tag 4's
    `function_type[0] != 2` is unconditional, and *function* position never
    consults subsumption, which is the only rule that ever looks through a
    refinement. `_NOT_A_FUNCTION` is therefore a proof, and it is a
    load-bearing one: three of the corpus's function types return a `refine`
    (`list/lengthNat`, `math/abs`, `nat/widenPos`), so abstaining on that tag
    would keep every one of them admissible at every over-long spine and cost
    roughly a third of the filter. `test_masker` pins the coupling
    behaviourally — an over-applied `refine`-returning definition is put
    through the real funnel and has to be rejected.
    """
    node = resolved
    for _ in range(k):
        if not isinstance(node, list) or not node:
            return _ABSTAIN, None
        tag = node[0]
        if tag == 2:
            node = node[3]
            continue
        if tag == 6:
            return _ABSTAIN, None
        return _NOT_A_FUNCTION, None
    if not isinstance(node, list) or not node:
        return _ABSTAIN, None
    if node[0] == 6:
        # The spine's result is itself quantified, so `check`'s instantiation
        # branch is live and no erased comparison decides anything.
        return _ABSTAIN, None
    return _PEELED, node


def _contains_tyvar(node) -> bool:
    """Defensive: a free `tyvar` outside a `forall` this layer already saw."""
    if not isinstance(node, list) or not node:
        return False
    if node[0] == 5:
        return True
    return any(_contains_tyvar(child) for child in node[1:]
               if isinstance(child, list))


class SpineGoalPruner(Pruner):
    """§2.4: a `ref` heading a *k*-ary application spine, filtered by codomain.

    `GoalTypePruner`'s veto 5 filters a `ref`'s digest by the goal *at that
    position* — and abstains wherever the checker synthesizes, which includes
    `app`'s function slot, which is where every held-out composition lives.
    This layer is that hole, closed at the only place it can be closed
    soundly: at decode time, where the open `(app` parentheses have already
    fixed *k*, and the checker's own per-position goals do the instantiation
    that a selection-time filter provably cannot (Amendment A1).

    **The proof.** `MatchChecker.check` does not special-case tag 4, so
    `check(spine, G)` is `synth(spine)` and then exactly one of: structural
    equality; `_instantiate`, live only when the synthesized type is a
    `forall`; or `_subsume`, whose own precondition is that the two types are
    equal once §3.2.1 refinements are erased. `synth` of a *k*-ary spine is the
    *k*-th codomain of the head's resolved type (`peel_codomain`). So a digest
    whose *k*-th codomain is not quantified **and** erases differently from `G`
    cannot appear at this position in any accepted definition. Same one-sided
    shape as veto 5, one position further in.

    **Effects do not enter it.** `synth` tag 4 returns the codomain whatever
    the call row is; the row feeds `_require_allowed`, which can make an
    application *fail* and never makes it succeed at a different type. So
    `corpus/clock/now : (fn (cap C) (C) I64)` is admitted precisely and
    soundly at `k = 1, G = I64`. The effectful positions Amendment A1 flagged
    (`stampedBytes`) abstain here for an unrelated reason — they are `con`
    field arguments, which carry no goal at all.

    **Abstains** at `k = 0` (veto 5's position), wherever the spine's goal is
    unknown (an argument slot, a `let` bound term, a `match` scrutinee, a `con`
    field), on a `forall`-typed head, on a `forall` or `refine` met while
    peeling, on a quantified result, and on any resolved type carrying a free
    `tyvar`. A `forall`-typed head is in fact rejected outright by the checker
    (`synth` tag 4 fails on `function_type[0] != 2` before instantiation is
    ever considered), so abstaining there leaves precision on the table
    deliberately: soundness beats precision wherever they meet.

    Two vetoes. The digest is the point; the head veto exists for liveness —
    with an empty admissible set and no head veto the mask walks into a hash
    position, refuses every digit, empties, and takes R4's syntax-only
    fallback, which throws the whole step's pruning away. Only `ref` is
    refused there; every other head reaches its goal through synthesis and
    stays feasible.
    """

    name = "spine-goal"

    TERMINATORS = frozenset({0x28, 0x29, 0x20})

    def __init__(self, digests=(), reference_type=None) -> None:
        self._digests = tuple(digests)
        self._reference_type = reference_type
        #: `(k, goal surface) -> (prefix set, complete set) | None`. A run sees
        #: a handful of distinct spine positions, so this is a few tries over a
        #: few dozen digests, not a per-step cost.
        self._sets: dict[tuple, tuple | None] = {}
        #: `digest -> resolved type | None`, so a peel never re-resolves.
        self._resolved: dict[bytes, list | None] = {}

    # -- veto ------------------------------------------------------------

    def veto(self, state: TypeState, byte: int) -> bool:
        if state.forced:
            # A position whose bytes the checker has already fixed is
            # `GoalTypePruner`'s, and it is not a spine head.
            return False
        kind = state.atom_kind
        if kind == P_HASH:
            return self._veto_hash(state, byte)
        if kind == P_HEAD:
            return self._veto_head(state, byte)
        return False

    def _veto_hash(self, state: TypeState, byte: int) -> bool:
        frame = state.top
        if frame.kind != "ref" or frame.goal:
            # A goal of its own means the position is veto 5's, not this one's.
            return False
        sets = self._sets_for(state)
        if sets is None:
            return False
        prefixes, complete = sets
        atom = state.atom
        if byte in self.TERMINATORS:
            return bool(atom) and atom not in complete
        return atom + bytes((byte,)) not in prefixes

    def _veto_head(self, state: TypeState, byte: int) -> bool:
        frame = state.top
        if frame.expected != P_TERM or frame.goal_in:
            return False
        sets = self._sets_for(state)
        if sets is None or sets[1]:
            return False
        # Nothing the resolver holds can head this spine, so `(ref …)` cannot
        # be written here — and only `(ref …)`.
        atom = state.atom
        if byte in self.TERMINATORS:
            return (atom in ALL_HEAD_BYTES
                    and atom not in _feasible_heads(None, ref_ok=False))
        return atom + bytes((byte,)) not in _head_prefixes(None, ref_ok=False)

    # -- the spine-filtered digest universe --------------------------------

    def _sets_for(self, state: TypeState):
        """The admissible digest trie at this position, or `None` to abstain."""
        k, goal = spine_context(state.stack, len(state.stack) - 1)
        if k == 0 or not goal or self._reference_type is None:
            return None
        key = (k, goal)
        try:
            return self._sets[key]
        except KeyError:
            pass
        info = type_info(goal)
        built = None if info is None else digest_trie(
            self._digests, lambda digest: self._admits(digest, k, info.erased))
        self._sets[key] = built
        return built

    def _resolve(self, digest: bytes):
        try:
            return self._resolved[digest]
        except KeyError:
            pass
        try:
            resolved = self._reference_type(digest)
        except Exception:       # noqa: BLE001 - an unresolvable ref dies anyway
            resolved = None
        if not isinstance(resolved, list) or not resolved:
            resolved = None
        self._resolved[digest] = resolved
        return resolved

    def _admits(self, digest: bytes, k: int, erased_goal: tuple) -> bool:
        """Could `(ref digest)` head a `k`-ary spine checked against this goal?

        Anything undecidable comes back `True`: keeping a digest is the safe
        side of R4 and dropping one is not.
        """
        resolved = self._resolve(digest)
        if resolved is None:
            # `_resolve_reference` fails, so no accepted definition names it.
            return False
        if resolved[0] == 6 or _contains_tyvar(resolved):
            return True
        verdict, codomain = peel_codomain(resolved, k)
        if verdict is _ABSTAIN:
            return True
        if verdict is _NOT_A_FUNCTION:
            return False
        try:
            return _freeze(_erase_refinements(codomain)) == erased_goal
        except Exception:       # noqa: BLE001 - an unreadable type stays in
            return True


@dataclass
class _Timed:
    """One pruner plus R3's per-layer counters. Toggling clears nothing."""

    pruner: Pruner
    enabled: bool = True
    calls: int = 0
    vetoes: int = 0
    seconds: float = 0.0

    @property
    def name(self) -> str:
        return self.pruner.name

    def veto(self, state: TypeState, byte: int) -> bool:
        started = time.perf_counter()
        verdict = self.pruner.veto(state, byte)
        self.seconds += time.perf_counter() - started
        self.calls += 1
        if verdict:
            self.vetoes += 1
        return verdict


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------


class StaticVocabulary:
    """Token id to bytes, indexed as a byte trie over the token pieces.

    The trie is what makes the mask affordable. Scoring a vocabulary token by
    token costs `len(vocab) × len(piece)` automaton steps per position; walking
    the trie instead costs one step per *live edge*, and a byte the mask refuses
    prunes that byte's whole subtree in a single step — which is the common
    case, because at almost every Loom position the set of legal next bytes is
    tiny. `subtree_size` carries the number of tokens under each node, so the
    per-layer pruned counts R3 asks for fall out of the cut rather than needing
    a second pass.
    """

    def __init__(self, pieces, eos_ids=()) -> None:
        self.pieces = tuple(pieces)
        self.eos_ids = frozenset(eos_ids)
        self._index = {piece: token_id for token_id, piece in enumerate(self.pieces)}
        children: list[dict] = [{}]
        token_at: list[int | None] = [None]
        subtree: list[int] = [0]
        for token_id, piece in enumerate(self.pieces):
            if token_id in self.eos_ids or not piece:
                continue
            node = 0
            subtree[0] += 1
            for byte in piece:
                nxt = children[node].get(byte)
                if nxt is None:
                    nxt = len(children)
                    children[node][byte] = nxt
                    children.append({})
                    token_at.append(None)
                    subtree.append(0)
                node = nxt
                subtree[node] += 1
            token_at[node] = token_id
        self.children = children
        self.token_at = token_at
        self.subtree_size = subtree

    def __len__(self) -> int:
        return len(self.pieces)

    def piece(self, token_id: int) -> bytes:
        return self.pieces[token_id]

    def lookup(self, piece: bytes):
        """The id of an exact piece, or `None`. Used by tests and the stub."""
        return self._index.get(piece)

    @property
    def trie_nodes(self) -> int:
        return len(self.children)


# --------------------------------------------------------------------------
# The masker
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MaskStep:
    """One decoding step's mask, with R3's per-token instrumentation."""

    allowed: tuple
    pruned: dict = field(default_factory=dict)
    seconds: float = 0.0
    seconds_by_layer: dict = field(default_factory=dict)
    can_end: bool = False
    fallback: bool = False

    @property
    def size(self) -> int:
        return len(self.allowed)

    def __contains__(self, token_id: int) -> bool:
        return token_id in self.allowed


class Masker:
    """The per-token mask API of R2, over one in-flight generation.

    Both layers are byte oracles, so they compose into a single memoized
    transition over the pair `(grammar state, type state)`. That is what makes
    the mask affordable: a candidate token costs one dictionary lookup per byte,
    and the *byte* prefilter — allowed bytes of the syntax layer minus the bytes
    the pruners veto — usually collapses a whole vocabulary to the handful of
    tokens that start with a live byte. Mid-hash, where the reference pruner
    leaves one or two hex digits alive, that is the difference between scoring
    the vocabulary and scoring a few hundred tokens.

    The memo is per-masker and is cleared whenever a pruner is toggled, since a
    toggle changes the transition relation.
    """

    #: Cap on the total number of token ids held in the mask cache. A hex
    #: position in a 151k-token vocabulary allows tens of thousands of tokens,
    #: so an unbounded cache is a gigabyte; an entry cap alone would not bound it.
    MASK_CACHE_IDS = 4_000_000

    #: Cap on the memoized byte transition, which is the other half of the
    #: masker's memory and was the half with no bound at all until a live run
    #: found out. Measured at 313-428 bytes per entry (key tuple, plus the
    #: `TypeState` and grammar state each entry retains), so this is ~200 MB
    #: worst case.
    #:
    #: Eviction is a wholesale clear rather than an LRU on purpose. `_transition`
    #: is the hottest path in the masker — it runs once per live trie edge per
    #: step — and per-hit recency bookkeeping there would cost more than the
    #: cache saves. Clearing is O(1) amortized and gives a hard bound; with the
    #: `ATOM_READ` fix above it is rare, and `mask_transition_clears` reports it
    #: so a run that thrashes says so rather than quietly slowing down.
    TRANSITION_CACHE_SIZE = 500_000

    def __init__(self, vocabulary: StaticVocabulary, pruners=(), grammar: Grammar | None = None,
                 mask_cache_size: int = 32_768, transition_cache_size: int | None = None) -> None:
        self.vocabulary = vocabulary
        self.grammar = grammar or loom_grammar()
        self.pruners = [p if isinstance(p, _Timed) else _Timed(p) for p in pruners]
        self._transitions: dict = {}
        self._transition_cache_size = (
            self.TRANSITION_CACHE_SIZE if transition_cache_size is None
            else transition_cache_size)
        self.transition_clears = 0
        self._mask_cache: dict = {}
        self._mask_cache_size = mask_cache_size
        self._cached_ids = 0
        self.mask_cache_clears = 0
        self.steps = 0
        self.mask_seconds = 0.0
        self.uncached_steps = 0
        self.uncached_seconds = 0.0
        self.cache_hits = 0
        #: Tokens pruned per layer. Counted from the per-step mask, not from the
        #: pruners' own counters, so it is *cache-stable*: a step answered from
        #: the mask cache pruned exactly as many tokens as the step that filled
        #: it, and a per-draw record must say so. The pruners' evaluation and
        #: veto counters live separately and are uncached work by construction.
        self.pruned_totals: dict[str, int] = {}
        self.fallbacks = 0
        self.reset()

    # -- toggles ---------------------------------------------------------

    def enable(self, name: str, enabled: bool = True) -> None:
        for timed in self.pruners:
            if timed.name == name:
                if timed.enabled != enabled:
                    timed.enabled = enabled
                    self._transitions.clear()
                    self._mask_cache.clear()
                    self._cached_ids = 0
                return
        raise KeyError(f"no pruner named {name!r}; have {[p.name for p in self.pruners]}")

    @property
    def enabled_pruners(self) -> tuple:
        return tuple(p.name for p in self.pruners if p.enabled)

    # -- the in-flight generation ---------------------------------------

    def reset(self) -> None:
        self.gstate = self.grammar.initial
        self.tstate = TypeState()
        self.tokens: list[int] = []
        self.emitted = bytearray()

    @property
    def text(self) -> str:
        return self.emitted.decode("utf-8", "replace")

    @property
    def can_end(self) -> bool:
        return self.grammar.can_end(self.gstate)

    @property
    def dead(self) -> bool:
        return not self.gstate

    def accept_token(self, token_id: int) -> None:
        if token_id in self.vocabulary.eos_ids:
            self.tokens.append(token_id)
            return
        piece = self.vocabulary.piece(token_id)
        self.accept_bytes(piece)
        self.tokens.append(token_id)

    def accept_bytes(self, data: bytes) -> None:
        for byte in data:
            self.gstate = self.grammar.step(self.gstate, byte)
            self.tstate = self.tstate.advance(byte)
        self.emitted.extend(data)

    # -- the combined byte oracle ----------------------------------------

    _DEAD = (None, "")

    def _veto_layer(self, tstate: TypeState, byte: int) -> str:
        for timed in self.pruners:
            if timed.enabled and timed.veto(tstate, byte):
                return timed.name
        return ""

    def _transition(self, state, byte: int):
        """`(next state, killing layer)`; the state is `None` when the byte dies."""
        key = (state, byte)
        cached = self._transitions.get(key)
        if cached is not None:
            return cached
        gstate, tstate = state
        advanced = self.grammar.step(gstate, byte)
        if not advanced:
            result = (None, "syntax")
        else:
            layer = self._veto_layer(tstate, byte)
            result = (None, layer) if layer else ((advanced, tstate.advance(byte)), "")
        if len(self._transitions) >= self._transition_cache_size:
            # In-place, so the `memo` alias `_mask_for` holds stays valid; a walk
            # in flight just recomputes rather than reading a stale entry.
            self._transitions.clear()
            self.transition_clears += 1
        self._transitions[key] = result
        return result

    def _mask_for(self, state):
        """`(allowed ids, pruned-by-layer)` at `state`. Deterministic, so cached.

        One depth-first walk of the vocabulary trie against the combined
        automaton. A dead edge charges its entire subtree to the layer that
        killed it and is not descended into, so the cost is proportional to what
        stays alive rather than to the vocabulary.
        """
        cached = self._mask_cache.get(state)
        if cached is not None:
            self.cache_hits += 1
            return cached
        vocabulary = self.vocabulary
        children = vocabulary.children
        token_at = vocabulary.token_at
        subtree = vocabulary.subtree_size
        transition = self._transition
        memo = self._transitions
        allowed: list[int] = []
        pruned: dict[str, int] = {"syntax": 0}
        work = [(0, state)]
        while work:
            node, here = work.pop()
            for byte, child in children[node].items():
                found = memo.get((here, byte))
                nxt, layer = found if found is not None else transition(here, byte)
                if nxt is None:
                    pruned[layer] = pruned.get(layer, 0) + subtree[child]
                    continue
                token_id = token_at[child]
                if token_id is not None:
                    allowed.append(token_id)
                if children[child]:
                    work.append((child, nxt))
        allowed.sort()
        result = (tuple(allowed), pruned)
        # Full means *evict*, not freeze. Refusing new entries at the cap sounds
        # conservative but leaves the cache frozen on whatever it happened to
        # learn first: launch 4 reached the 32,768-entry cap during `none` and
        # `few_shot`, so `full_corpus` — the regime carrying R5's bar — would
        # have run with a cache that could no longer learn anything about it.
        # Same wholesale clear as the transition memo, same reasoning.
        if (len(self._mask_cache) >= self._mask_cache_size
                or self._cached_ids >= self.MASK_CACHE_IDS):
            self._mask_cache.clear()
            self._cached_ids = 0
            self.mask_cache_clears += 1
        self._mask_cache[state] = result
        self._cached_ids += len(allowed)
        return result

    def step(self) -> MaskStep:
        started = time.perf_counter()
        state = (self.gstate, self.tstate)
        hits_before = self.cache_hits
        before = {timed.name: timed.seconds for timed in self.pruners}
        allowed, pruned = self._mask_for(state)
        can_end = self.grammar.can_end(self.gstate)
        eos = tuple(sorted(self.vocabulary.eos_ids)) if can_end else ()

        fallback = False
        if not allowed and any(timed.enabled for timed in self.pruners):
            # R4 over aggression: the type layer must never be the reason a step
            # has nothing to emit. Fall back to syntax alone and record it.
            syntax_only, _ = self._syntax_only(state)
            if syntax_only:
                allowed = syntax_only
                pruned = {"syntax": pruned.get("syntax", 0)}
                fallback = True
                self.fallbacks += 1

        elapsed = time.perf_counter() - started
        self.steps += 1
        self.mask_seconds += elapsed
        if self.cache_hits == hits_before:
            self.uncached_steps += 1
            self.uncached_seconds += elapsed
        for layer, count in pruned.items():
            self.pruned_totals[layer] = self.pruned_totals.get(layer, 0) + count
        seconds_by_layer = {
            "syntax": round(elapsed - sum(t.seconds - before[t.name] for t in self.pruners), 9)}
        for timed in self.pruners:
            seconds_by_layer[timed.name] = round(timed.seconds - before[timed.name], 9)
        return MaskStep(
            allowed=allowed + eos,
            pruned=pruned,
            seconds=elapsed,
            seconds_by_layer=seconds_by_layer,
            can_end=can_end,
            fallback=fallback,
        )

    def _syntax_only(self, state):
        """The mask with every pruner off — the liveness fallback's input."""
        saved = [timed.enabled for timed in self.pruners]
        for timed in self.pruners:
            timed.enabled = False
        transitions, mask_cache, cached_ids = self._transitions, self._mask_cache, self._cached_ids
        self._transitions, self._mask_cache, self._cached_ids = {}, {}, 0
        try:
            return self._mask_for(state)
        finally:
            self._transitions, self._mask_cache = transitions, mask_cache
            self._cached_ids = cached_ids
            for timed, was in zip(self.pruners, saved):
                timed.enabled = was

    # -- R3 instrumentation ---------------------------------------------

    def stats(self) -> dict:
        """R3's per-cell numbers.

        Three honest caveats, stated here because the report repeats them:
        `mask_pruned_by_layer` counts *tokens the mask removed* and is
        cache-stable; `mask_vetoes_by_layer` and `mask_calls_by_layer` count
        *byte evaluations actually performed*, which the caches suppress and
        which therefore fall as a run warms up; and `*_seconds` for a pruner is
        that same uncached time — the marginal cost of the check, not a
        re-charge for every cache hit. Compare
        `mask_seconds_per_token_uncached` against decode time for a cold run.
        """
        pruner_seconds = sum(timed.seconds for timed in self.pruners)
        by_layer = {"syntax": self.pruned_totals.get("syntax", 0)}
        seconds = {"syntax": round(max(0.0, self.mask_seconds - pruner_seconds), 6)}
        calls = {"syntax": self.steps}
        vetoes = {"syntax": self.steps}
        for timed in self.pruners:
            by_layer[timed.name] = self.pruned_totals.get(timed.name, 0)
            seconds[timed.name] = round(timed.seconds, 6)
            calls[timed.name] = timed.calls
            vetoes[timed.name] = timed.vetoes
        return {
            "mask_vetoes_by_layer": vetoes,
            "mask_steps": self.steps,
            "mask_seconds": round(self.mask_seconds, 6),
            "mask_seconds_per_token": round(self.mask_seconds / self.steps, 9) if self.steps else 0.0,
            "mask_seconds_per_token_uncached": (
                round(self.uncached_seconds / self.uncached_steps, 9) if self.uncached_steps else 0.0),
            "mask_cache_hits": self.cache_hits,
            "mask_cache_hit_rate": round(self.cache_hits / self.steps, 4) if self.steps else 0.0,
            "mask_pruned_by_layer": by_layer,
            "mask_seconds_by_layer": seconds,
            "mask_calls_by_layer": calls,
            "mask_fallbacks": self.fallbacks,
            "mask_pruners_enabled": list(self.enabled_pruners),
            "mask_vocab_size": len(self.vocabulary),
            # The two bounded caches, reported so a run that is thrashing them
            # says so on the page rather than only getting slower.
            "mask_transition_entries": len(self._transitions),
            "mask_transition_clears": self.transition_clears,
            "mask_cache_entries": len(self._mask_cache),
            "mask_cache_clears": self.mask_cache_clears,
            "mask_cached_ids": self._cached_ids,
        }

    def reset_stats(self) -> None:
        self.steps = 0
        self.mask_seconds = 0.0
        self.uncached_steps = 0
        self.uncached_seconds = 0.0
        self.cache_hits = 0
        self.pruned_totals = {}
        self.fallbacks = 0
        for timed in self.pruners:
            timed.calls = timed.vetoes = 0
            timed.seconds = 0.0


# --------------------------------------------------------------------------
# Construction helpers
# --------------------------------------------------------------------------

#: The pruner set, **in Phase A's failure-distribution order** — which is what
#: B2's gate asked for. Over the 1,671 grammar-constrained draws of conditions 2
#: and 3: typecheck 590, parse 523, scope 268 (de Bruijn share 0.978),
#: references 115. So `goal-type` runs first, `de-bruijn` second, `ref-hash`
#: third. Parse has no pruner and cannot have one — see the plan's B2 decision
#: on completion pressure.
#:
#: The order is not cosmetic. `Masker._veto_layer` credits the *first* layer
#: that refuses a byte, so running them in profile order makes
#: `mask_pruned_by_layer` read as "what the dominant checker layer removed",
#: which is the number R5 wants. It changes attribution between layers, never
#: the mask itself: a byte any enabled pruner refuses is refused.
PRUNER_NAMES = ("goal-type", "de-bruijn", "ref-hash")

#: Every pruner `build_pruners` knows how to build, default set **plus** the
#: opt-in ones. `spine-goal` is deliberately not in `PRUNER_NAMES`: adding it
#: there would silently change every config that takes the default, and the
#: whole point of an opt-in layer is that the configs already on record run
#: byte-identically without it. A config opts in by naming it::
#:
#:     "pruners": ["goal-type", "spine-goal", "de-bruijn", "ref-hash"],
#:
#: after `goal-type`, so `mask_pruned_by_layer` attribution keeps reading in
#: Phase A's failure-distribution order.
KNOWN_PRUNER_NAMES = PRUNER_NAMES + ("spine-goal",)


def build_pruners(resolver, names=PRUNER_NAMES) -> list:
    """The named pruners, wired to the experiment resolver's hash universe."""
    digests = tuple(resolver.digests()) if hasattr(resolver, "digests") else tuple(resolver)
    # A bare digest iterable is accepted for the tests and probes that have no
    # resolver; the goal pruner's `ref` filter then abstains rather than
    # guessing at types it cannot look up.
    reference_type = getattr(resolver, "reference_type", None)
    built = []
    for name in names:
        if name == "ref-hash":
            built.append(ReferenceHashPruner(digests))
        elif name == "de-bruijn":
            built.append(DeBruijnPruner())
        elif name == "goal-type":
            built.append(GoalTypePruner(digests, reference_type))
        elif name == "spine-goal":
            built.append(SpineGoalPruner(digests, reference_type))
        else:
            raise KeyError(
                f"unknown pruner {name!r}; known pruners: {', '.join(KNOWN_PRUNER_NAMES)}")
    return built


def build_masker(vocabulary, resolver, names=PRUNER_NAMES, grammar=None) -> Masker:
    return Masker(vocabulary, pruners=build_pruners(resolver, names), grammar=grammar)
