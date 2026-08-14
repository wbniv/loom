"""The reference evaluator: a definitional interpreter for SPEC.md §2's terms.

Every other layer in this directory decides whether a term is *well formed*.
This one says what it *means*. It covers all thirteen §2.1 term tags, implements
deep algebraic-effect handlers whose continuations are first-class and
invocable more than once (§3.1.2), honours two's-complement `I64` wrapping at
runtime (§3.2.1), and refuses a hole (§2.6).

Design decisions and the alternatives rejected for each are argued in
`docs/plans/2026-08-13-reference-evaluator.md`. The four that a reader of this
module needs up front:

**It assumes a checked term.** The precondition is that the input passed
`typecheck.validate_source`, and therefore parse, scope and reference validation
before it. Nothing here re-derives a type, re-checks exhaustiveness, re-checks an
arity, or re-checks §2.4's capability requirement — `perform` has no capability
operand to check, and §3.1.2 already enforces that statically. Where a checked
term could not have reached a state, the evaluator still refuses with a path
rather than guessing, so an upstream bug surfaces as a diagnosis instead of a
wrong answer.

**It is a machine, not a recursive function.** Control is an explicit
`(mode, control, environment, frame stack)` state stepped by one Python loop.
That is what makes a continuation a *tuple slice* — capturable, and pushable
twice — and it keeps Loom's control depth off CPython's stack, so a long fold
ends in a Loom-level `FuelExhausted` rather than a host `RecursionError`.

**It has no ambient authority.** §2.4 says a capability is "introduced only by
the runtime at a program entry point, never constructible in the language": only
`Interpreter.mint_capability` produces one. A `perform` with no dynamic handler
and no caller-supplied builtin behaviour is an error, never a default. The
module *offers* `scripted_clock` and `seeded_rand`; it never installs them.

**Its mutable surface is two write-once caches** — the recursive-`fix` cell and
the resolved-definition cache — and both are monotone. That is the invariant
multi-shot resumption rests on: replaying a captured frame tuple cannot observe a
different world the second time. (A *caller's* builtin behaviour is the caller's
business: a scripted stub that advances on each call is observably stateful if a
multi-shot continuation crosses it, which is a property of the stub, not of the
machine.)
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import cbor_canonical
import corpus_registry
import prelude
from declarations import DeclarationError, DeclarationRegistry
from scope import check_definition
from transcode import parse_source, transcode_source

#: Resolves a stored definition hash to that definition's *term*. The evaluator
#: has no store, so a body is injected exactly the way `scope.py` injects an
#: ability arity and `typecheck.py` injects a reference type (§3.1.5).
ReferenceTermResolver = Callable[[bytes], list]

#: One host primitive behind an extern hash (§5.1.3: an extern has no Loom body
#: and is "never evaluated by the Loom evaluator"). Called only when saturated.
ExternImplementation = Callable[[tuple, str], "Value"]

#: One builtin ability operation's behaviour, keyed by `(ability, operation)`.
#: Supplied by the caller; the evaluator ships none installed (§2.4).
BuiltinBehaviour = Callable[[tuple, str], "Value"]

#: Machine step budget for one run. Generous by default; every test that expects
#: divergence sets it low. §2.5 makes totality an oracle obligation, so the
#: evaluator must be able to run a term whose measure is wrong without hanging.
DEFAULT_FUEL = 1_000_000

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

#: §2.2 literal kinds, named so error messages and tests stop spelling integers.
KIND_UNIT, KIND_BOOL, KIND_I64, KIND_F64, KIND_TEXT, KIND_BYTES = range(6)

_LIST = corpus_registry.HASHES["List"]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationError(ValueError):
    """A runtime failure, with the path of the term that produced it."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class HoleRefused(EvaluationError):
    """§2.6: a hole inhabits its goal type by fiat, which has no operational
    content. A term containing one is confined to the draft region (§5.4) and
    an evaluator refuses it rather than inventing a value."""


class UnhandledOperation(EvaluationError):
    """A `perform` with no dynamic handler and no caller-supplied behaviour."""


class FuelExhausted(EvaluationError):
    """The step budget ran out — a `div`-carrying term, or a wrong measure."""


class UnresolvedReference(EvaluationError):
    """§3.1.5's refusal, at runtime: a `ref` whose target the resolver has not."""


class ReferenceCycle(EvaluationError):
    """A definition whose body transitively references itself through `ref`."""


def _fail(path: str, message: str) -> None:
    raise EvaluationError(path, message)


#: Runtime paths are *bounded*. A path grows as the machine descends, and in a
#: tail-recursive loop it never shrinks — so an uncapped path would grow with the
#: step count, not with the term, and a long run would spend more memory on
#: diagnostics than on values. Past the cap the prefix is kept and an ellipsis
#: marks the truncation. `contracts.py` explicitly does not cover "the path
#: strings carried inside errors", so this costs no conformance claim.
_PATH_LIMIT = 240


def _extend(path: str, suffix: str) -> str:
    if len(path) + len(suffix) > _PATH_LIMIT:
        return path if path.endswith("…") else path + "…"
    return path + suffix


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Value:
    """A closed runtime value. Every subclass is immutable (§R14)."""


@dataclass(frozen=True)
class Literal(Value):
    """A §2.2 literal. `kind` is carried so `Literal(1, True)` (a `Bool`) can
    never be confused with `Literal(2, 1)` (an `I64`) the way Python's `bool`
    and `int` can. `f64` keeps its canonical eight big-endian bytes rather than
    becoming a Python float: nothing operates on `F64`, so decoding would only
    reopen §2.2's NaN-canonicalization question at the wrong layer."""

    kind: int
    value: object = None


@dataclass(frozen=True)
class Constructor(Value):
    """`con d i [args]` (§2.1 tag 6): nominal, fields in declaration order."""

    data: bytes
    index: int
    fields: tuple = ()


@dataclass(frozen=True)
class Closure(Value):
    """`lam` plus the environment it captured. Call-by-value, so the body is
    untouched until an argument arrives."""

    body: list
    env: tuple
    parameter_type: object = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class ExternValue(Value):
    """A `ref` that resolved to an extern (§5.1.3). Curried: `arity` comes off
    the declared type's `fn` spine, and the host implementation is called only
    once `applied` is saturated."""

    digest: bytes
    arity: int
    applied: tuple = ()


@dataclass(frozen=True)
class Capability(Value):
    """§2.4's `cap a`: unforgeable, minted only by the runtime at an entry
    point. No term evaluates to one."""

    ability: bytes
    label: str = ""


@dataclass(frozen=True)
class Continuation(Value):
    """A reified resumption: the frames between a `perform` and its handler,
    **with the handler frame re-installed** on top (deep handlers, §3.1.2).

    Invoking it splices `frames` onto the stack at the invocation site, so the
    resumption runs, passes through the handler's return clause and comes *back*
    — which is exactly the type §3.1.2 gives it, `fn operation-result
    ambient-row R`. The frames are an immutable tuple, so invoking the same
    continuation twice is pushing the same tuple twice; there is nothing to
    copy, which is what makes multi-shot resumption sound here."""

    frames: tuple
    ability: bytes
    operation: int


UNIT = Literal(KIND_UNIT, None)
TRUE = Literal(KIND_BOOL, True)
FALSE = Literal(KIND_BOOL, False)


class _RecursiveCell:
    """The write-once knot for `fix`. Placed in the environment before the body
    is evaluated and filled with the body's value; §2.3.1 puts the recursive
    value `k + 1` binders in, so a well-formed body is a `lam` and the cell is
    always filled before anything reads it."""

    __slots__ = ("value", "filled")

    def __init__(self) -> None:
        self.value: Value | None = None
        self.filled = False

    def fill(self, value: Value) -> None:
        self.value = value
        self.filled = True


def describe(value: Value) -> str:
    """A short human name for a value kind, for error messages."""
    if isinstance(value, Literal):
        return f"literal(kind {value.kind})"
    if isinstance(value, Constructor):
        return f"constructor {value.index} of {value.data.hex()[:8]}"
    if isinstance(value, Closure):
        return "function"
    if isinstance(value, ExternValue):
        return f"extern {value.digest.hex()[:8]}"
    if isinstance(value, Capability):
        return f"capability for {value.ability.hex()[:8]}"
    if isinstance(value, Continuation):
        return "continuation"
    return type(value).__name__


# --------------------------------------------------------------------------
# Frames — the defunctionalized continuation of the machine
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Frame:
    path: str


@dataclass(frozen=True)
class _EvalArgument(_Frame):
    """`app`: the function is done; evaluate the argument next."""

    argument: list = field(default_factory=list)
    env: tuple = ()


@dataclass(frozen=True)
class _ApplyFunction(_Frame):
    """`app`: both halves are done; apply."""

    function: Value = UNIT


@dataclass(frozen=True)
class _ApplyTo(_Frame):
    """Harness entry point: apply the arriving function to a ready value."""

    argument: Value = UNIT


@dataclass(frozen=True)
class _LetBody(_Frame):
    body: list = field(default_factory=list)
    env: tuple = ()


@dataclass(frozen=True)
class _ConstructorArguments(_Frame):
    data: bytes = b""
    index: int = 0
    done: tuple = ()
    rest: tuple = ()
    env: tuple = ()


@dataclass(frozen=True)
class _MatchArms(_Frame):
    arms: tuple = ()
    env: tuple = ()


@dataclass(frozen=True)
class _PerformArguments(_Frame):
    ability: bytes = b""
    operation: int = 0
    done: tuple = ()
    rest: tuple = ()
    env: tuple = ()


@dataclass(frozen=True)
class _IfBranches(_Frame):
    then_term: list = field(default_factory=list)
    else_term: list = field(default_factory=list)
    env: tuple = ()


@dataclass(frozen=True)
class _Handle(_Frame):
    """An installed handler. A value arriving here runs the return clause; a
    `perform` searching the stack stops at the innermost matching one."""

    ability: bytes = b""
    operations: tuple = ()
    return_clause: list = field(default_factory=list)
    env: tuple = ()


@dataclass(frozen=True)
class _FixBind(_Frame):
    cell: _RecursiveCell = None  # type: ignore[assignment]


@dataclass(frozen=True)
class _CacheDefinition(_Frame):
    digest: bytes = b""


_EVAL = "eval"
_APPLY = "apply"


# --------------------------------------------------------------------------
# The assumed base: nine extern implementations (§R6, §R7)
# --------------------------------------------------------------------------


def wrap_i64(value: int) -> int:
    """§3.2.1 names the gap from the solver's side — "`Int` does not wrap, so a
    proof that depends on 64-bit overflow is unsound". This is the other side of
    that sentence: the runtime wraps, two's complement, always."""
    return ((value + 2**63) % 2**64) - 2**63


def i64(value: int) -> Literal:
    return Literal(KIND_I64, wrap_i64(value))


def boolean(value: bool) -> Literal:
    return Literal(KIND_BOOL, bool(value))


def text(value: str) -> Literal:
    return Literal(KIND_TEXT, value)


def byte_string(value: bytes) -> Literal:
    return Literal(KIND_BYTES, value)


def _literal_argument(arguments: tuple, position: int, kind: int, path: str, label: str):
    try:
        value = arguments[position]
    except IndexError:
        _fail(path, f"{label} expects an argument at position {position}")
    if not isinstance(value, Literal) or value.kind != kind:
        _fail(path, f"{label} argument {position}: expected literal kind {kind}, got {describe(value)}")
    return value.value


def _i64_binary(label, combine, wrap):
    def implementation(arguments: tuple, path: str) -> Value:
        left = _literal_argument(arguments, 0, KIND_I64, path, label)
        right = _literal_argument(arguments, 1, KIND_I64, path, label)
        result = combine(left, right)
        return i64(result) if wrap else boolean(result)

    implementation.__name__ = label.replace(".", "_")
    return implementation


def _bool_binary(label, combine):
    def implementation(arguments: tuple, path: str) -> Value:
        left = _literal_argument(arguments, 0, KIND_BOOL, path, label)
        right = _literal_argument(arguments, 1, KIND_BOOL, path, label)
        return boolean(combine(left, right))

    implementation.__name__ = label.replace(".", "_")
    return implementation


def _bool_not(arguments: tuple, path: str) -> Value:
    return boolean(not _literal_argument(arguments, 0, KIND_BOOL, path, "Bool.not"))


def _list_size(arguments: tuple, path: str) -> Value:
    """`List.size` — uninterpreted for SMT (§3.2.1) and perfectly ordinary here:
    walk the `Cons` spine. The `List` identity is checked, so a mis-typed
    argument is a path-aware refusal rather than a wrong number."""
    try:
        cursor = arguments[0]
    except IndexError:
        _fail(path, "List.size expects one argument")
    size = 0
    while True:
        if not isinstance(cursor, Constructor) or cursor.data != _LIST:
            _fail(path, f"List.size: expected a List value, got {describe(cursor)}")
        if cursor.index == 0:
            return i64(size)
        if cursor.index != 1 or len(cursor.fields) != 2:
            _fail(path, f"List.size: malformed List constructor {cursor.index}")
        size += 1
        cursor = cursor.fields[1]


#: The nine §11 assumed-base externs, keyed off `corpus_registry.EXTERN_HASHES`
#: rather than a hand-copied hash list — copying pinned hashes creates a second
#: source of truth that drifts silently on a re-pin. Semantics agree with
#: `corpus_registry.SMT_INTERPRETATION`'s claims (`+ - = < <=` and `and or not`)
#: with R6's wrap on the two arithmetic entries; the wrap is exactly where the
#: agreement with SMT-LIB `Int` ends, and §3.2.1's exactness rule says so.
DEFAULT_EXTERNS: Mapping[bytes, ExternImplementation] = MappingProxyType({
    corpus_registry.EXTERN_HASHES["I64.add"]: _i64_binary("I64.add", lambda a, b: a + b, True),
    corpus_registry.EXTERN_HASHES["I64.sub"]: _i64_binary("I64.sub", lambda a, b: a - b, True),
    corpus_registry.EXTERN_HASHES["I64.eq"]: _i64_binary("I64.eq", lambda a, b: a == b, False),
    corpus_registry.EXTERN_HASHES["I64.lt"]: _i64_binary("I64.lt", lambda a, b: a < b, False),
    corpus_registry.EXTERN_HASHES["I64.le"]: _i64_binary("I64.le", lambda a, b: a <= b, False),
    corpus_registry.EXTERN_HASHES["Bool.and"]: _bool_binary("Bool.and", lambda a, b: a and b),
    corpus_registry.EXTERN_HASHES["Bool.or"]: _bool_binary("Bool.or", lambda a, b: a or b),
    corpus_registry.EXTERN_HASHES["Bool.not"]: _bool_not,
    corpus_registry.EXTERN_HASHES["List.size"]: _list_size,
})


# --------------------------------------------------------------------------
# §2.4 builtin-ability behaviours the caller may opt into
# --------------------------------------------------------------------------


def abi_success(payload: bytes) -> Literal:
    """§2.4's canonical runtime ABI envelope, success: `[0, payload-bytes]`."""
    return byte_string(cbor_canonical.encode([0, payload]))


def abi_failure(diagnostic: str) -> Literal:
    """§2.4's canonical runtime ABI envelope, failure: `[1, diagnostic-text]`."""
    return byte_string(cbor_canonical.encode([1, diagnostic]))


def scripted_clock(millis) -> dict:
    """A deterministic `clock` (§2.4): `wallMillis` answers from a fixed script,
    `sleepMillis` returns immediately. Offered, never installed — the caller
    must pass it to `Interpreter(builtins=...)` for a program to see a clock."""
    remaining = list(millis)

    def wall_millis(arguments: tuple, path: str) -> Value:
        if not remaining:
            _fail(path, "scripted clock exhausted: no further wallMillis answers")
        return i64(remaining.pop(0))

    def sleep_millis(arguments: tuple, path: str) -> Value:
        _literal_argument(arguments, 0, KIND_I64, path, "clock.sleepMillis")
        return UNIT

    return {
        (prelude.HASHES["clock"], 0): wall_millis,
        (prelude.HASHES["clock"], 1): sleep_millis,
    }


def seeded_rand(seed: int = 0) -> dict:
    """A deterministic `rand` (§2.4): a SHA-256 counter stream. `bytes n`
    returns exactly `max(n, 0)` bytes, as §2.4 requires. Offered, never
    installed."""
    counter = [0]

    def stream(count: int) -> bytes:
        out = b""
        while len(out) < count:
            out += hashlib.sha256(
                seed.to_bytes(8, "big", signed=True) + counter[0].to_bytes(8, "big")
            ).digest()
            counter[0] += 1
        return out[:count]

    def rand_bytes(arguments: tuple, path: str) -> Value:
        requested = _literal_argument(arguments, 0, KIND_I64, path, "rand.bytes")
        return byte_string(stream(max(requested, 0)))

    def rand_i64(arguments: tuple, path: str) -> Value:
        return i64(int.from_bytes(stream(8), "big", signed=True))

    return {
        (prelude.HASHES["rand"], 0): rand_bytes,
        (prelude.HASHES["rand"], 1): rand_i64,
    }


# --------------------------------------------------------------------------
# Definition bodies: the injected resolver (§R10)
# --------------------------------------------------------------------------


class DefinitionTermRegistry:
    """Validated, immutable definition-*term* snapshots for injected `ref`
    evaluation — the body-level twin of `definition_types.DefinitionTypeRegistry`.

    A small store-facing test adapter, not a Loom object registry. Only
    scope-validated definitions enter, and returned terms are isolated copies so
    an evaluator cannot mutate the stored snapshot.
    """

    def __init__(self, ability_arity=None):
        self._ability_arity = ability_arity
        self._terms: dict[bytes, list] = {}

    def add_source(self, source: str, expected_hash: bytes | None = None) -> bytes:
        ir, _, digest_hex = transcode_source(source)
        digest = bytes.fromhex(digest_hex)
        if expected_hash is not None and digest != expected_hash:
            raise ValueError(
                f"definition term registry: supplied hash {expected_hash.hex()} "
                f"does not match canonical hash {digest.hex()}"
            )
        check_definition(ir, self._ability_arity)
        self._terms[digest] = copy.deepcopy(ir[2])
        return digest

    def reference_term(self, digest: bytes) -> list:
        try:
            return copy.deepcopy(self._terms[digest])
        except KeyError as exc:
            raise LookupError(digest) from exc

    def __contains__(self, digest: object) -> bool:
        return digest in self._terms

    def __len__(self) -> int:
        return len(self._terms)


def _arrow_arity(type_ir) -> int:
    """How many arguments an extern takes, off its curried `fn` spine (§2.3)."""
    count = 0
    cursor = type_ir
    while isinstance(cursor, list) and cursor and cursor[0] == 2:
        count += 1
        cursor = cursor[3]
    return count


# --------------------------------------------------------------------------
# The machine
# --------------------------------------------------------------------------


class Interpreter:
    """A definitional interpreter for SPEC.md §2's term language.

    Call-by-value, left to right in CBOR field order (§R1). Deep handlers with
    multi-shot continuations (§R5). Wrapping `I64` (§R6). No ambient authority
    (§R8). Assumes a checked term (§R12).
    """

    def __init__(
        self,
        declarations: DeclarationRegistry,
        reference_term: ReferenceTermResolver | None = None,
        externs: Mapping[bytes, ExternImplementation] | None = None,
        builtins: Mapping[tuple, BuiltinBehaviour] | None = None,
        fuel: int = DEFAULT_FUEL,
    ):
        self._declarations = declarations
        self._reference_term = reference_term
        self._externs = dict(DEFAULT_EXTERNS if externs is None else externs)
        self._builtins = dict(builtins or {})
        self._fuel = fuel
        self._definition_values: dict[bytes, Value] = {}
        self._resolving: set[bytes] = set()
        self._depth = 0

    @property
    def builtins(self):
        """The §2.4 builtin-ability behaviours this interpreter was given. Empty
        unless the caller supplied some — the evaluator installs none."""
        return MappingProxyType(self._builtins)

    @property
    def externs(self):
        """The extern implementations behind §5.1.3's bodiless definitions."""
        return MappingProxyType(self._externs)

    # -- entry points --------------------------------------------------------

    def evaluate(self, term, env: tuple = (), path: str = "term", fuel: int | None = None) -> Value:
        """Evaluate a term to a value. `env` supplies de Bruijn index 0 first."""
        return self._run(_EVAL, term, tuple(env), (), path, fuel)

    def evaluate_definition(self, ir, path: str = "definition.term", fuel: int | None = None) -> Value:
        """Evaluate a `[0, type, term]` definition object's term (§4.3).

        §3.1.3: a definition typed `forall^p T` *is* its type abstraction and no
        term node abstracts or applies a type, so instantiation is erased at
        runtime with nothing to erase — the value of a quantified definition is
        simply its body's value.
        """
        if not isinstance(ir, list) or len(ir) != 3 or ir[0] != 0:
            _fail(path, "expected a definition object [0, type, term]")
        return self.evaluate(ir[2], (), path, fuel)

    def evaluate_source(self, source: str, path: str = "definition.term", fuel: int | None = None) -> Value:
        """Parse a canonical definition surface and evaluate its term."""
        return self.evaluate_definition(parse_source(source), path, fuel)

    def value_of(self, digest: bytes, path: str = "ref", fuel: int | None = None) -> Value:
        """The value behind a stored definition or extern hash — a bare `ref`."""
        return self.evaluate([1, digest], (), path, fuel)

    def apply(self, function: Value, *arguments: Value, path: str = "apply", fuel: int | None = None) -> Value:
        """Apply a value to already-evaluated arguments, left to right."""
        stack = tuple(_ApplyTo(path, argument) for argument in arguments)
        return self._run(_APPLY, function, (), stack, path, fuel)

    def mint_capability(self, ability: bytes, label: str = "") -> Capability:
        """§2.4: capabilities are "introduced only by the runtime at a program
        entry point, never constructible in the language". This method is that
        entry point, and it is the only one. The ability must be one the
        declaration registry knows, so a capability cannot name a fiction."""
        try:
            self._declarations.ability(ability)
        except DeclarationError as exc:
            raise EvaluationError("capability", str(exc)) from None
        return Capability(ability, label)

    # -- the loop ------------------------------------------------------------

    def _run(self, mode, control, env: tuple, stack: tuple, path: str, fuel: int | None) -> Value:
        # Reference resolution begins and ends inside one run, so anything left
        # in `_resolving` at the outermost entry is debris from a run that
        # raised; clearing it stops a retry mistaking that debris for a cycle.
        # A *nested* entry must not clear it: §5.1.3's callback externs mean a
        # host implementation can legitimately call back into the machine, and
        # that inner run is inside the outer one's resolution. A nested run gets
        # its own fuel budget, which is the honest reading — the host, not Loom,
        # decided to start a second computation.
        if self._depth == 0:
            self._resolving.clear()
        self._depth += 1
        budget = self._fuel if fuel is None else fuel
        remaining = budget
        try:
            while True:
                remaining -= 1
                if remaining < 0:
                    raise FuelExhausted(path, f"step budget exhausted after {budget} steps")
                if mode == _EVAL:
                    mode, control, env, stack, path = self._step_eval(control, env, stack, path)
                else:
                    if not stack:
                        return control
                    mode, control, env, stack, path = self._step_apply(control, stack, path)
        finally:
            self._depth -= 1

    # -- eval: a term is in control -----------------------------------------

    def _step_eval(self, term, env: tuple, stack: tuple, path: str):
        if not isinstance(term, list) or not term:
            _fail(path, "expected a nonempty term node")
        tag = term[0]

        if tag == 0:  # var
            return _APPLY, self._lookup(term[1], env, path), env, stack, path

        if tag == 1:  # ref
            return self._eval_reference(term[1], env, stack, path)

        if tag == 2:  # lit
            value = Literal(term[1], term[2] if len(term) > 2 else None)
            return _APPLY, value, env, stack, path

        if tag == 3:  # lam
            return _APPLY, Closure(term[2], env, term[1]), env, stack, path

        if tag == 4:  # app — [4, f, a]: function first, then argument (§R1)
            frame = _EvalArgument(path, term[2], env)
            return _EVAL, term[1], env, (frame,) + stack, _extend(path, ".function")

        if tag == 5:  # let
            frame = _LetBody(path, term[3], env)
            return _EVAL, term[2], env, (frame,) + stack, _extend(path, ".bound")

        if tag == 6:  # con
            arguments = tuple(term[3])
            if not arguments:
                return _APPLY, Constructor(term[1], term[2], ()), env, stack, path
            frame = _ConstructorArguments(path, term[1], term[2], (), arguments[1:], env)
            return _EVAL, arguments[0], env, (frame,) + stack, _extend(path, ".args[0]")

        if tag == 7:  # match
            frame = _MatchArms(path, tuple(term[2]), env)
            return _EVAL, term[1], env, (frame,) + stack, _extend(path, ".scrutinee")

        if tag == 8:  # perform
            arguments = tuple(term[3])
            if not arguments:
                return self._perform(term[1], term[2], (), stack, path)
            frame = _PerformArguments(path, term[1], term[2], (), arguments[1:], env)
            return _EVAL, arguments[0], env, (frame,) + stack, _extend(path, ".args[0]")

        if tag == 9:  # handle
            frame = _Handle(path, term[1], tuple(term[3]), term[4], env)
            return _EVAL, term[2], env, (frame,) + stack, _extend(path, ".handled")

        if tag == 10:  # fix — the measure is never evaluated (§2.5, §R9)
            cell = _RecursiveCell()
            frame = _FixBind(path, cell)
            return _EVAL, term[4], (cell,) + env, (frame,) + stack, _extend(path, ".body")

        if tag == 11:  # hole
            raise HoleRefused(path, "a hole has no value; §2.6 confines it to the draft region")

        if tag == 12:  # if
            frame = _IfBranches(path, term[2], term[3], env)
            return _EVAL, term[1], env, (frame,) + stack, _extend(path, ".condition")

        _fail(path, f"unknown term tag {tag!r}")

    def _lookup(self, index, env: tuple, path: str) -> Value:
        if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(env):
            _fail(path, f"de Bruijn index {index!r} is out of range for depth {len(env)}")
        slot = env[index]
        if isinstance(slot, _RecursiveCell):
            if not slot.filled:
                _fail(path, "recursive value used before it is bound; a `fix` body must be a value form")
            return slot.value
        return slot

    def _eval_reference(self, digest, env: tuple, stack: tuple, path: str):
        try:
            info = self._declarations.extern(digest)
        except DeclarationError:
            info = None
        if info is not None:
            arity = _arrow_arity(info.type)
            if arity == 0:
                _fail(path, f"extern {digest.hex()} has no arguments; §5.1.3 gives it no body to evaluate")
            if digest not in self._externs:
                _fail(path, f"no implementation supplied for extern {digest.hex()}")
            return _APPLY, ExternValue(digest, arity), env, stack, path

        if digest in self._definition_values:
            return _APPLY, self._definition_values[digest], env, stack, path

        if self._reference_term is None:
            raise UnresolvedReference(path, f"no definition-term resolver supplied for {digest.hex()}")
        if digest in self._resolving:
            raise ReferenceCycle(path, f"definition {digest.hex()} references itself through `ref`")
        try:
            body = self._reference_term(digest)
        except (LookupError, DeclarationError):
            raise UnresolvedReference(path, f"unresolved reference {digest.hex()}") from None

        self._resolving.add(digest)
        frame = _CacheDefinition(path, digest)
        return _EVAL, body, (), (frame,) + stack, _extend(path, f".ref[{digest.hex()[:8]}]")

    # -- apply: a value is in control, and a frame is waiting for it ---------

    def _step_apply(self, value: Value, stack: tuple, path: str):
        frame, rest = stack[0], stack[1:]

        if isinstance(frame, _EvalArgument):
            return _EVAL, frame.argument, frame.env, (_ApplyFunction(frame.path, value),) + rest, _extend(frame.path, ".argument")

        if isinstance(frame, _ApplyFunction):
            return self._apply_value(frame.function, value, rest, frame.path)

        if isinstance(frame, _ApplyTo):
            return self._apply_value(value, frame.argument, rest, frame.path)

        if isinstance(frame, _LetBody):
            return _EVAL, frame.body, (value,) + frame.env, rest, _extend(frame.path, ".body")

        if isinstance(frame, _ConstructorArguments):
            done = frame.done + (value,)
            if frame.rest:
                nxt = _ConstructorArguments(frame.path, frame.data, frame.index, done, frame.rest[1:], frame.env)
                return _EVAL, frame.rest[0], frame.env, (nxt,) + rest, _extend(frame.path, f".args[{len(done)}]")
            return _APPLY, Constructor(frame.data, frame.index, done), (), rest, frame.path

        if isinstance(frame, _MatchArms):
            return self._select_arm(value, frame, rest)

        if isinstance(frame, _PerformArguments):
            done = frame.done + (value,)
            if frame.rest:
                nxt = _PerformArguments(frame.path, frame.ability, frame.operation, done, frame.rest[1:], frame.env)
                return _EVAL, frame.rest[0], frame.env, (nxt,) + rest, _extend(frame.path, f".args[{len(done)}]")
            return self._perform(frame.ability, frame.operation, done, rest, frame.path)

        if isinstance(frame, _IfBranches):
            if not isinstance(value, Literal) or value.kind != KIND_BOOL:
                _fail(frame.path, f"`if` condition must be a Bool literal, got {describe(value)}")
            branch, label = (frame.then_term, "then") if value.value else (frame.else_term, "else")
            return _EVAL, branch, frame.env, rest, _extend(frame.path, "." + label)

        if isinstance(frame, _Handle):
            # §2.3.1: the return clause binds the handled result at index 0.
            return _EVAL, frame.return_clause, (value,) + frame.env, rest, _extend(frame.path, ".return")

        if isinstance(frame, _FixBind):
            frame.cell.fill(value)
            return _APPLY, value, (), rest, frame.path

        if isinstance(frame, _CacheDefinition):
            self._definition_values[frame.digest] = value
            self._resolving.discard(frame.digest)
            return _APPLY, value, (), rest, frame.path

        _fail(path, f"unknown machine frame {type(frame).__name__}")

    def _apply_value(self, function: Value, argument: Value, stack: tuple, path: str):
        if isinstance(function, Closure):
            return _EVAL, function.body, (argument,) + function.env, stack, _extend(path, ".body")

        if isinstance(function, ExternValue):
            applied = function.applied + (argument,)
            if len(applied) < function.arity:
                return _APPLY, ExternValue(function.digest, function.arity, applied), (), stack, path
            implementation = self._externs.get(function.digest)
            if implementation is None:
                _fail(path, f"no implementation supplied for extern {function.digest.hex()}")
            return _APPLY, implementation(applied, path), (), stack, path

        if isinstance(function, Continuation):
            # Deep handlers: `frames` already ends in the handler frame, so the
            # resumption runs, passes the return clause, and comes back here.
            return _APPLY, argument, (), function.frames + stack, path

        _fail(path, f"cannot apply {describe(function)} as a function")

    def _select_arm(self, value: Value, frame: _MatchArms, stack: tuple):
        if not isinstance(value, Constructor):
            _fail(frame.path, f"`match` scrutinee must be a constructor value, got {describe(value)}")
        for position, arm in enumerate(frame.arms):
            if arm[0] != value.index:
                continue
            if arm[1] != len(value.fields):
                _fail(
                    f"{frame.path}.arms[{position}]",
                    f"arm declares {arm[1]} binders but constructor {value.index} carries {len(value.fields)} fields",
                )
            # §2.3.1: fields enter in declaration order, last field at index 0.
            env = tuple(reversed(value.fields)) + frame.env
            return _EVAL, arm[2], env, stack, _extend(frame.path, f".arms[{position}].body")
        _fail(frame.path, f"no arm for constructor index {value.index}")

    def _perform(self, ability: bytes, operation: int, arguments: tuple, stack: tuple, path: str):
        for position, frame in enumerate(stack):
            if isinstance(frame, _Handle) and frame.ability == ability:
                return self._handle_operation(frame, position, operation, arguments, stack, path)

        behaviour = self._builtins.get((ability, operation))
        if behaviour is None:
            raise UnhandledOperation(
                path,
                f"no handler and no builtin behaviour for operation {operation} "
                f"of ability {ability.hex()}",
            )
        return _APPLY, behaviour(arguments, path), (), stack, path

    def _handle_operation(self, frame: _Handle, position: int, operation: int, arguments: tuple, stack: tuple, path: str):
        body = None
        clause_index = None
        for index, clause in enumerate(frame.operations):
            if clause[0] == operation:
                body, clause_index = clause[1], index
                break
        if body is None:
            _fail(frame.path, f"handler for {frame.ability.hex()} has no clause for operation {operation}")

        # The captured resumption includes the handler frame itself, so a
        # `perform` inside the resumption is caught by the same handler again —
        # deep handlers (§3.1.2). The slice is immutable, so invoking the
        # continuation twice is pushing the same tuple twice.
        continuation = Continuation(stack[: position + 1], frame.ability, operation)

        # §2.3.1: parameters in signature order, then the continuation at index
        # 0 — so the last parameter is index 1.
        env = (continuation,) + tuple(reversed(arguments)) + frame.env

        # The clause body runs *outside* the handler: that is what discharges
        # the ability from the row (§3.1.2).
        return _EVAL, body, env, stack[position + 1:], _extend(frame.path, f".operations[{clause_index}]")


# --------------------------------------------------------------------------
# Corpus wiring, and the Loom/Python value bridge tests and callers want
# --------------------------------------------------------------------------


def corpus_definition_terms() -> DefinitionTermRegistry:
    """Every bootstrap-corpus definition's term, pinned to its own identity.

    Manifest order is dependency order, so adding in order never asks for a hash
    the snapshot does not yet hold — the same property `experiment/resolver.py`
    relies on.
    """
    declarations = corpus_registry.registry()
    terms = DefinitionTermRegistry(declarations.operation_arity)
    for entry in corpus_registry.MANIFEST:
        terms.add_source(entry.source_text().rstrip("\n"), bytes.fromhex(entry.identity))
    return terms


def corpus_interpreter(builtins=None, fuel: int = DEFAULT_FUEL) -> Interpreter:
    """An interpreter over the bootstrap corpus: the §2.4 builtin abilities, the
    corpus data declarations, the nine assumed-base externs with their
    implementations, and every corpus definition's body.

    `builtins` is still empty by default: wiring the corpus in supplies no clock
    and no entropy (§2.4, §R8).
    """
    declarations = corpus_registry.registry()
    terms = corpus_definition_terms()
    return Interpreter(
        declarations,
        reference_term=terms.reference_term,
        externs=DEFAULT_EXTERNS,
        builtins=builtins,
        fuel=fuel,
    )


def corpus_digest(name_path: str) -> bytes:
    """The identity of a corpus definition, by its meta-object name path."""
    for entry in corpus_registry.MANIFEST:
        if entry.name_path == name_path:
            return bytes.fromhex(entry.identity)
    raise LookupError(f"unknown corpus definition {name_path!r}")


def loom_list(values, data: bytes = _LIST) -> Constructor:
    """Build a `List` value from Python values, `Nil`-terminated."""
    result = Constructor(data, 0, ())
    for item in reversed(list(values)):
        result = Constructor(data, 1, (item, result))
    return result


def python_list(value: Value, path: str = "value") -> list:
    """Read a `List` value back out, as a Python list of `Value`s."""
    items: list[Value] = []
    cursor = value
    while True:
        if not isinstance(cursor, Constructor) or cursor.data != _LIST:
            _fail(path, f"expected a List value, got {describe(cursor)}")
        if cursor.index == 0:
            return items
        items.append(cursor.fields[0])
        cursor = cursor.fields[1]


def i64_list(values) -> Constructor:
    """`loom_list` over Python ints, wrapped into `I64` literals."""
    return loom_list([i64(value) for value in values])


def python_i64_list(value: Value, path: str = "value") -> list[int]:
    """`python_list` back to Python ints, refusing a non-`I64` element."""
    result = []
    for position, item in enumerate(python_list(value, path)):
        if not isinstance(item, Literal) or item.kind != KIND_I64:
            _fail(f"{path}[{position}]", f"expected an I64 element, got {describe(item)}")
        result.append(item.value)
    return result
