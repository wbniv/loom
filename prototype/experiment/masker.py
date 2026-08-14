"""R2's two-layer mask: syntax feasibility plus an incremental type state.

The interface the plan asks for is one question, asked once per decoding step:
*given the tokens emitted so far, which next tokens keep this prefix extendable
to an accepted definition?* Two layers answer it.

**Syntax** — `gbnf.Grammar`, the incremental byte-level prefix oracle over
`loom.gbnf`. A token is syntactically feasible when feeding its bytes leaves the
automaton alive.

**Type state** — `TypeState`, a structural scanner over the same byte stream
that knows, at every byte, which grammar atom is being written (a hash, a
`var` index, a `tyvar` index, a head keyword, a literal payload) and what the de
Bruijn binder depths are there. Pruners are pluggable checks over that state,
each individually toggleable and individually timed (R3).

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

    # -- transitions -----------------------------------------------------

    def advance(self, byte: int) -> "TypeState":
        # Hot path: most bytes are atom content, and this runs once per uncached
        # byte of every candidate token, so it builds the successor directly
        # rather than going through `dataclasses.replace`.
        if self.in_string:
            return self._advance_string(byte)
        if byte == 0x28:      # (
            return self._open()
        if byte == 0x29:      # )
            return self._close()
        if byte == 0x20:      # space
            return self._next_part()
        if not self.atom and byte == 0x22 and self.stack[-1].part_kind == "string":
            return TypeState(self.stack, b'"', self.prenex, True, False)
        return TypeState(
            self.stack, self.atom + bytes((byte,)), self.prenex, False, False)

    def _advance_string(self, byte: int) -> "TypeState":
        atom = self.atom + bytes((byte,))
        if self.escaped:
            return TypeState(self.stack, atom, self.prenex, True, False)
        if byte == 0x5C:      # backslash
            return TypeState(self.stack, atom, self.prenex, True, True)
        if byte == 0x22:      # closing quote
            return TypeState(self.stack, atom, self.prenex, False, False)
        return TypeState(self.stack, atom, self.prenex, True, False)

    def _open(self) -> "TypeState":
        top = self.stack[-1]
        expected = top.part_kind
        common = {
            "base_term": top.term_depth,
            "base_type": top.type_depth,
            "base_unknown": top.unknown,
            "expected": expected,
            "eligible": top.prenex_ok,
        }
        if expected in HEADED:
            child = Frame(
                kind=_PENDING, part=0, part_kind=P_HEAD,
                term_depth=top.term_depth, type_depth=top.type_depth,
                unknown=top.unknown, **common)
        elif expected in LIST_ELEMENT:
            child = Frame(
                kind=expected, part=0, part_kind=LIST_ELEMENT[expected],
                term_depth=top.term_depth, type_depth=top.type_depth,
                unknown=top.unknown, **common)
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
        return replace(self, stack=self.stack + (child,), atom=b"")

    def _close(self) -> "TypeState":
        if len(self.stack) <= 1:
            # Only reachable on input the grammar layer has already refused.
            return replace(self, atom=b"")
        return replace(self, stack=self.stack[:-1], atom=b"")

    def _next_part(self) -> "TypeState":
        top = self.stack[-1]
        atom, prenex = self.atom, self.prenex

        if top.kind == _PENDING:
            head = atom.decode("utf-8", "replace")
            spec = FORMS.get(head)
            if spec is None:
                resolved = replace(top, kind=P_UNKNOWN, part=1, part_kind=P_UNKNOWN,
                                   unknown=True)
                return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"")
            if head == "forall" and top.eligible:
                prenex += 1
            resolved = replace(top, kind=head, binders=0)
            resolved = self._apply_part(resolved, spec, 1, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"", prenex=prenex)

        if top.kind == "lit" and top.part == 1:
            kind = atom.decode("utf-8", "replace")
            payload = LIT_PAYLOAD.get(kind, P_UNKNOWN)
            resolved = replace(top, part=2, part_kind=payload, lit_kind=kind)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"")

        if top.kind == P_ARM and top.part == 1:
            try:
                binders = int(atom)
            except ValueError:  # pragma: no cover - grammar guarantees digits
                binders = 0
                top = replace(top, unknown=True)
            resolved = replace(top, binders=binders)
            resolved = self._apply_part(resolved, ARM_PARTS, 2, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"")

        if top.kind in FORMS:
            spec = FORMS[top.kind]
            resolved = self._apply_part(top, spec, top.part + 1, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"")
        if top.kind == P_ARM:
            resolved = self._apply_part(top, ARM_PARTS, top.part + 1, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"")
        if top.kind == P_OP:
            resolved = self._apply_part(top, OP_PARTS, top.part + 1, prenex)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"")
        if top.kind in LIST_ELEMENT:
            resolved = replace(top, part=top.part + 1)
            return replace(self, stack=self.stack[:-1] + (resolved,), atom=b"")
        return replace(self, atom=b"")

    @staticmethod
    def _apply_part(frame: Frame, spec: tuple, part: int, prenex: int) -> Frame:
        """Set `frame`'s current part to `part`, with that part's depths."""
        index = part - 1 if frame.kind in FORMS else part
        if index < 0 or index >= len(spec):
            return replace(frame, part=part, part_kind=P_NONE)
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
        return replace(
            frame, part=part, part_kind=kind, term_depth=term_depth,
            type_depth=type_depth, unknown=unknown, prenex_ok=prenex_ok)

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

    def __init__(self, vocabulary: StaticVocabulary, pruners=(), grammar: Grammar | None = None,
                 mask_cache_size: int = 32_768) -> None:
        self.vocabulary = vocabulary
        self.grammar = grammar or loom_grammar()
        self.pruners = [p if isinstance(p, _Timed) else _Timed(p) for p in pruners]
        self._transitions: dict = {}
        self._mask_cache: dict = {}
        self._mask_cache_size = mask_cache_size
        self._cached_ids = 0
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
        if (len(self._mask_cache) < self._mask_cache_size
                and self._cached_ids < self.MASK_CACHE_IDS):
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

#: The B1 pruner set, in the order the plan names them.
PRUNER_NAMES = ("ref-hash", "de-bruijn")


def build_pruners(resolver, names=PRUNER_NAMES) -> list:
    """The named pruners, wired to the experiment resolver's hash universe."""
    digests = tuple(resolver.digests()) if hasattr(resolver, "digests") else tuple(resolver)
    built = []
    for name in names:
        if name == "ref-hash":
            built.append(ReferenceHashPruner(digests))
        elif name == "de-bruijn":
            built.append(DeBruijnPruner())
        else:
            raise KeyError(f"unknown pruner {name!r}; known pruners: {', '.join(PRUNER_NAMES)}")
    return built


def build_masker(vocabulary, resolver, names=PRUNER_NAMES, grammar=None) -> Masker:
    return Masker(vocabulary, pruners=build_pruners(resolver, names), grammar=grammar)
