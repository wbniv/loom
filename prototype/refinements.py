"""Refinement-to-SMT-LIB translation for the decidable fragment (SPEC.md §3.2.1)."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass

import cbor_canonical
from declarations import DeclarationError, DeclarationRegistry
from typecheck import TypingError, instantiate_type

SORT_BOOL = "Bool"
SORT_INT = "Int"
SORT_UNIT = "Loom.Unit"
SORT_F64 = "Loom.F64"
SORT_TEXT = "Loom.Text"
SORT_BYTES = "Loom.Bytes"

OPAQUE_SORTS = (SORT_BYTES, SORT_F64, SORT_TEXT)
BASE_SORT = {0: SORT_UNIT, 1: SORT_BOOL, 2: SORT_INT, 3: SORT_F64, 4: SORT_TEXT, 5: SORT_BYTES}
OPAQUE_PREFIX = {3: "loom.f64.", 4: "loom.text.", 5: "loom.bytes."}

DATA_SORT_PREFIX = "Loom.D"
UNIT_CONSTRUCTOR = "loom.unit"
CONTEXT_PREFIX = "loom.x"
BINDER_PREFIX = "loom.b"
REFERENCE_PREFIX = "loom.f"

I64_MIN = -(2**63)
I64_MAX = 2**63 - 1

#: SMT-LIB symbols a definition hash may be interpreted as. Everything else is
#: uninterpreted, so the allowlist is the whole of the trusted theory surface.
INTERPRETED_SYMBOLS = (
    "*", "+", "-", "<", "<=", "=", "=>", ">", ">=",
    "abs", "and", "distinct", "div", "ite", "mod", "not", "or",
)

#: The half of the allowlist whose SMT-LIB meaning *coincides* with the Loom
#: operation an interpretation-table entry maps onto it, so a model over these
#: symbols reads back as a real Loom valuation (SPEC.md §3.2.1, translation
#: faithfulness condition 4). Boolean structure and the order relations qualify.
FAITHFUL_SYMBOLS = ("<", "<=", "=", "=>", ">", ">=", "and", "distinct", "ite", "not", "or")

#: The other half: SMT-LIB `Int` is unbounded and Loom's `I64` wraps, so these
#: agree with the operation they interpret only while no intermediate value
#: leaves the I64 domain — which no syntactic check can establish. Their presence
#: makes a script inexact, and that is the countermodel side of the `Int`
#: fidelity limit §3.2.1 already states for proofs.
IDEALIZING_SYMBOLS = ("*", "+", "-", "abs", "div", "mod")

TERM_FRAGMENT_TAGS = (0, 1, 2, 4, 5, 6, 7, 12)


@dataclass(frozen=True)
class SmtError(ValueError):
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class Value:
    """A translated SMT-LIB term, its sort, and its integer numeral if it is one."""

    text: str
    sort: str
    numeral: int | None = None


@dataclass(frozen=True)
class Abstractions:
    """What the translator abstracted away while emitting one script.

    Facts, not policy: this module reports what it did and takes no position on
    what the report means. `obligations.py` holds SPEC.md §3.2.1's exactness
    rule, so the five conditions have exactly one place that decides them and
    exactly one walk that observes them — a second traversal recomputing these
    could silently disagree with the translation it is describing.
    """

    #: Reference symbols that became `declare-fun`. The solver invents a
    #: function for each; the real definition or extern computes something else.
    uninterpreted: tuple[str, ...] = ()
    #: Opaque sorts that became `declare-sort` — `F64`, `Text`, `Bytes`.
    opaque_sorts: tuple[str, ...] = ()
    #: A `refine` node reached sort position and its predicate was dropped.
    erased_refinement: bool = False
    #: Interpreted symbols this script actually used, sorted.
    interpreted: tuple[str, ...] = ()
    #: A `match` bound a field at sort `Int`, which no domain axiom bounds.
    unbounded_int_binder: bool = False

    @property
    def idealizing(self) -> tuple[str, ...]:
        """The used symbols whose `Int` meaning departs from `I64`'s."""
        return tuple(symbol for symbol in self.interpreted if symbol in IDEALIZING_SYMBOLS)


def _fail(path: str, message: str) -> None:
    raise SmtError(path, message)


def _contains_refinement(ir) -> bool:
    """Whether a type node carries a `refine` anywhere erasure would drop it."""
    if not isinstance(ir, list) or not ir:
        return False
    if ir[0] == 3:
        return True
    return any(_contains_refinement(item) for item in ir)


def _form(head: str, arguments) -> str:
    parts = list(arguments)
    if not parts:
        return head
    return "(" + " ".join([head, *parts]) + ")"


def erase_type(ir, path: str = "type"):
    """Erase refinements and reject every type outside the sort fragment."""
    if not isinstance(ir, list) or not ir:
        _fail(path, "expected a nonempty type node")
    tag = ir[0]
    if tag == 0:
        if ir[1] not in BASE_SORT:
            _fail(path, f"invalid base code {ir[1]!r}")
        return [0, ir[1]]
    if tag == 1:
        return [1, ir[1], [erase_type(argument, f"{path}.args[{index}]") for index, argument in enumerate(ir[2])]]
    if tag == 3:
        return erase_type(ir[1], f"{path}.base")
    names = {2: "function", 4: "capability", 5: "type variable", 6: "forall"}
    if tag in names:
        _fail(path, f"a {names[tag]} type has no SMT-LIB sort in the decidable refinement fragment")
    _fail(path, f"unknown type tag {tag!r}")


class ObligationTranslator:
    """Translates one verification condition into one canonical SMT-LIB script."""

    def __init__(self, registry: DeclarationRegistry, signatures=None, interpretations=None):
        self.registry = registry
        self.signatures = dict(signatures or {})
        self.interpretations = dict(interpretations or {})
        for digest, symbol in self.interpretations.items():
            if symbol not in INTERPRETED_SYMBOLS:
                _fail("interpretations", f"{symbol!r} is not an admitted interpreted SMT-LIB symbol")
        self._reset()

    def _reset(self) -> None:
        self._opaque: set[str] = set()
        self._unit = False
        self._datatypes: dict[str, list | None] = {}
        self._constants: dict[str, str] = {}
        self._context: list[tuple[str, str]] = []
        self._functions: dict[str, tuple[list[str], str]] = {}
        self._binder = 0
        self._erased_refinement = False
        self._used_symbols: set[str] = set()
        self._unbounded_int_binder = False

    def abstractions(self) -> Abstractions:
        """What this translator abstracted away on its most recent script."""
        return Abstractions(
            uninterpreted=tuple(sorted(self._functions)),
            opaque_sorts=tuple(sorted(self._opaque)),
            erased_refinement=self._erased_refinement,
            interpreted=tuple(sorted(self._used_symbols)),
            unbounded_int_binder=self._unbounded_int_binder,
        )

    # ---------------------------------------------------------------- sorts

    def sort(self, ir, path: str) -> str:
        # Every path into erasure runs through here, so this is the one place a
        # dropped predicate can be observed (SPEC.md §3.2.1, condition 3).
        if _contains_refinement(ir):
            self._erased_refinement = True
        return self._sort(erase_type(ir, path), path)

    def _sort(self, ir, path: str) -> str:
        if ir[0] == 0:
            sort = BASE_SORT[ir[1]]
            if sort == SORT_UNIT:
                self._unit = True
            elif sort in OPAQUE_SORTS:
                self._opaque.add(sort)
            return sort
        return self._declare_data(ir, path)

    def _declare_data(self, ir, path: str) -> str:
        name = DATA_SORT_PREFIX + hashlib.sha256(cbor_canonical.encode(ir)).hexdigest()
        if name in self._datatypes:
            return name
        try:
            declaration = self.registry.data_object(ir[1])
        except DeclarationError as exc:
            _fail(path, str(exc))
        if declaration[2] != len(ir[2]):
            _fail(path, f"data expects {declaration[2]} type arguments, got {len(ir[2])}")
        self._datatypes[name] = None
        constructors = []
        for index, fields in enumerate(declaration[3]):
            field_sorts = []
            for position, field in enumerate(fields):
                field_path = f"{path}.constructors[{index}].fields[{position}]"
                try:
                    instantiated = instantiate_type(field, ir[2], ir[1], field_path)
                except TypingError as exc:
                    _fail(exc.path, exc.message)
                field_sorts.append(self.sort(instantiated, field_path))
            constructors.append(field_sorts)
        self._datatypes[name] = constructors
        return name

    # ---------------------------------------------------------------- terms

    def term(self, ir, environment: list[tuple[str, str]], path: str) -> Value:
        if not isinstance(ir, list) or not ir:
            _fail(path, "expected a nonempty term node")
        tag = ir[0]
        if tag == 0:
            index = ir[1]
            if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(environment):
                _fail(path, f"term index {index!r} has no sort in the obligation environment")
            symbol, sort = environment[index]
            return Value(symbol, sort)
        if tag == 1:
            return self._apply(ir[1], [], environment, path)
        if tag == 2:
            return self._literal(ir, path)
        if tag == 4:
            head, arguments = ir, []
            while isinstance(head, list) and head and head[0] == 4:
                arguments.append(head[2])
                head = head[1]
            arguments.reverse()
            if not isinstance(head, list) or not head or head[0] != 1:
                _fail(path, "only a saturated application of a stored reference is inside the refinement fragment")
            return self._apply(head[1], arguments, environment, path)
        if tag == 5:
            return self._let(ir, environment, path)
        if tag == 6:
            return self._constructor(ir, environment, path)
        if tag == 7:
            return self._match(ir, environment, path)
        if tag == 12:
            return self._if(ir, environment, path)
        names = {3: "lam", 8: "perform", 9: "handle", 10: "fix", 11: "hole"}
        if tag in names:
            _fail(path, f"`{names[tag]}` is outside the decidable refinement fragment")
        _fail(path, f"unknown term tag {tag!r}")

    def _literal(self, ir, path: str) -> Value:
        kind = ir[1]
        if kind == 0:
            self._unit = True
            return Value(UNIT_CONSTRUCTOR, SORT_UNIT)
        if kind == 1:
            return Value("true" if ir[2] is True else "false", SORT_BOOL)
        if kind == 2:
            value = ir[2]
            text = str(value) if value >= 0 else f"(- {-value})"
            return Value(text, SORT_INT, value)
        if kind in OPAQUE_PREFIX:
            payload = ir[2].encode("utf-8") if kind == 4 else ir[2]
            sort = BASE_SORT[kind]
            symbol = OPAQUE_PREFIX[kind] + hashlib.sha256(payload).hexdigest()
            self._opaque.add(sort)
            self._constants[symbol] = sort
            return Value(symbol, sort)
        _fail(path, f"unknown literal kind {kind!r}")

    def _signature(self, digest: bytes, path: str):
        if digest not in self.signatures:
            _fail(path, f"reference {digest.hex()} has no signature; the translator does not guess one")
        current = copy.deepcopy(self.signatures[digest])
        parameters = []
        while isinstance(current, list) and current and current[0] == 3:
            current = current[1]
        while isinstance(current, list) and current and current[0] == 2:
            if current[2]:
                _fail(path, f"reference {digest.hex()} is effectful and cannot occur in a refinement predicate")
            parameters.append(current[1])
            current = current[3]
            while isinstance(current, list) and current and current[0] == 3:
                current = current[1]
        return parameters, current

    def _apply(self, digest: bytes, argument_irs, environment, path: str) -> Value:
        if not isinstance(digest, bytes) or len(digest) != 32:
            _fail(path, "reference must be a 32-byte hash")
        parameters, result = self._signature(digest, path)
        if len(parameters) != len(argument_irs):
            _fail(path, f"reference {digest.hex()} takes {len(parameters)} arguments, got {len(argument_irs)}; partial application is out of fragment")
        parameter_sorts = [self.sort(parameter, f"{path}.parameters[{index}]") for index, parameter in enumerate(parameters)]
        result_sort = self.sort(result, f"{path}.result")
        values = []
        for index, argument in enumerate(argument_irs):
            argument_path = f"{path}.args[{index}]"
            value = self.term(argument, environment, argument_path)
            if value.sort != parameter_sorts[index]:
                _fail(argument_path, f"expected sort {parameter_sorts[index]}, got {value.sort}")
            values.append(value)
        symbol = self.interpretations.get(digest)
        if symbol is not None:
            return self._interpreted(symbol, values, result_sort, path)
        name = REFERENCE_PREFIX + digest.hex()
        self._functions[name] = (parameter_sorts, result_sort)
        return Value(_form(name, [value.text for value in values]), result_sort)

    def _interpreted(self, symbol: str, values: list[Value], result_sort: str, path: str) -> Value:
        arity = len(values)
        sorts = [value.sort for value in values]

        def require(condition, message):
            if not condition:
                _fail(path, f"interpreted `{symbol}`: {message}")

        def expect(sort):
            require(result_sort == sort, f"declared result sort {result_sort} should be {sort}")

        if symbol in ("not",):
            require(arity == 1 and sorts == [SORT_BOOL], "expects one Bool argument")
            expect(SORT_BOOL)
        elif symbol in ("and", "or"):
            require(arity >= 2 and set(sorts) == {SORT_BOOL}, "expects at least two Bool arguments")
            expect(SORT_BOOL)
        elif symbol == "=>":
            require(arity == 2 and sorts == [SORT_BOOL, SORT_BOOL], "expects two Bool arguments")
            expect(SORT_BOOL)
        elif symbol in ("=", "distinct"):
            require(arity >= 2 and len(set(sorts)) == 1, "expects at least two arguments of one common sort")
            expect(SORT_BOOL)
        elif symbol == "ite":
            require(arity == 3 and sorts[0] == SORT_BOOL and sorts[1] == sorts[2], "expects Bool plus two arguments of one common sort")
            expect(sorts[1])
        elif symbol in ("+", "-"):
            require(arity >= (1 if symbol == "-" else 2) and set(sorts) == {SORT_INT}, "expects Int arguments")
            expect(SORT_INT)
        elif symbol == "*":
            require(arity >= 2 and set(sorts) == {SORT_INT}, "expects at least two Int arguments")
            require(sum(1 for value in values if value.numeral is None) <= 1, "is nonlinear; at most one factor may be a variable term")
            expect(SORT_INT)
        elif symbol in ("div", "mod"):
            require(arity == 2 and sorts == [SORT_INT, SORT_INT], "expects two Int arguments")
            require(values[1].numeral not in (None, 0), "requires a nonzero integer literal divisor")
            expect(SORT_INT)
        elif symbol == "abs":
            require(arity == 1 and sorts == [SORT_INT], "expects one Int argument")
            expect(SORT_INT)
        elif symbol in ("<", "<=", ">", ">="):
            require(arity == 2 and sorts == [SORT_INT, SORT_INT], "expects two Int arguments")
            expect(SORT_BOOL)
        else:  # pragma: no cover - constructor rejects unknown symbols
            _fail(path, f"{symbol!r} is not an admitted interpreted SMT-LIB symbol")
        numeral = None
        if symbol == "-" and arity == 1 and values[0].numeral is not None:
            numeral = -values[0].numeral
        self._used_symbols.add(symbol)
        return Value(_form(symbol, [value.text for value in values]), result_sort, numeral)

    def _fresh(self) -> str:
        symbol = f"{BINDER_PREFIX}{self._binder}"
        self._binder += 1
        return symbol

    def _let(self, ir, environment, path: str) -> Value:
        sort = self.sort(ir[1], f"{path}.binding-type")
        bound = self.term(ir[2], environment, f"{path}.bound")
        if bound.sort != sort:
            _fail(f"{path}.bound", f"expected sort {sort}, got {bound.sort}")
        symbol = self._fresh()
        body = self.term(ir[3], [(symbol, sort), *environment], f"{path}.body")
        return Value(f"(let (({symbol} {bound.text})) {body.text})", body.sort)

    def _if(self, ir, environment, path: str) -> Value:
        condition = self.term(ir[1], environment, f"{path}.condition")
        if condition.sort != SORT_BOOL:
            _fail(f"{path}.condition", f"expected sort {SORT_BOOL}, got {condition.sort}")
        consequent = self.term(ir[2], environment, f"{path}.then")
        alternative = self.term(ir[3], environment, f"{path}.else")
        if consequent.sort != alternative.sort:
            _fail(f"{path}.else", f"expected sort {consequent.sort}, got {alternative.sort}")
        # §3.2.1: `if` costs the trusted theory surface nothing because `ite` is
        # already admitted — so it is recorded like any other use of it.
        self._used_symbols.add("ite")
        return Value(_form("ite", [condition.text, consequent.text, alternative.text]), consequent.sort)

    def _constructor(self, ir, environment, path: str) -> Value:
        try:
            declaration = self.registry.data_object(ir[1])
        except DeclarationError as exc:
            _fail(path, str(exc))
        if declaration[2] != 0:
            _fail(path, "a parameterized constructor has no synthesizable sort in the refinement fragment")
        sort = self._declare_data([1, ir[1], []], path)
        constructors = self._datatypes[sort]
        index = ir[2]
        if index >= len(constructors):
            _fail(path, f"constructor index {index} is out of range for {len(constructors)} constructors")
        field_sorts = constructors[index]
        if len(ir[3]) != len(field_sorts):
            _fail(path, f"constructor {index} expects {len(field_sorts)} arguments, got {len(ir[3])}")
        texts = []
        for position, argument in enumerate(ir[3]):
            argument_path = f"{path}.args[{position}]"
            value = self.term(argument, environment, argument_path)
            if value.sort != field_sorts[position]:
                _fail(argument_path, f"expected sort {field_sorts[position]}, got {value.sort}")
            texts.append(value.text)
        return Value(_form(f"{sort}.c{index}", texts), sort)

    def _match(self, ir, environment, path: str) -> Value:
        scrutinee = self.term(ir[1], environment, f"{path}.scrutinee")
        if not scrutinee.sort.startswith(DATA_SORT_PREFIX):
            _fail(path, "match scrutinee does not have a datatype sort")
        constructors = self._datatypes[scrutinee.sort]
        arms: dict[int, tuple[int, list]] = {}
        for position, arm in enumerate(ir[2]):
            arm_path = f"{path}.arms[{position}]"
            index = arm[0]
            if index >= len(constructors):
                _fail(arm_path, f"constructor index {index} is out of range for {len(constructors)} constructors")
            if index in arms:
                _fail(arm_path, f"duplicate constructor arm {index}")
            arms[index] = (position, arm)
        missing = sorted(set(range(len(constructors))) - set(arms))
        if missing:
            _fail(path, f"non-exhaustive match; missing constructors {missing}")
        if not constructors:
            _fail(path, "match over an empty data declaration has no SMT-LIB sort")
        cases = []
        result_sort = None
        for index in sorted(arms):
            position, arm = arms[index]
            arm_path = f"{path}.arms[{position}]"
            field_sorts = constructors[index]
            if arm[1] != len(field_sorts):
                _fail(arm_path, f"binder count {arm[1]} does not match constructor field count {len(field_sorts)}")
            binders = [self._fresh() for _ in field_sorts]
            # The I64 domain axiom is emitted for context variables only, so an
            # `Int`-sorted field binder ranges over all of `Int` (§3.2.1,
            # condition 5).
            if SORT_INT in field_sorts:
                self._unbounded_int_binder = True
            arm_environment = [*reversed(list(zip(binders, field_sorts))), *environment]
            body = self.term(arm[2], arm_environment, f"{arm_path}.body")
            if result_sort is None:
                result_sort = body.sort
            elif body.sort != result_sort:
                _fail(arm_path, f"arm sort {body.sort} differs from {result_sort}")
            pattern = _form(f"{scrutinee.sort}.c{index}", binders)
            cases.append(f"({pattern} {body.text})")
        return Value(f"(match {scrutinee.text} ({' '.join(cases)}))", result_sort)

    # --------------------------------------------------------------- script

    def script(self, context_types, hypotheses, goal, path: str = "obligation") -> str:
        """Return the canonical refutation script for `hypotheses ⊨ goal`."""
        self._reset()
        environment = []
        for index, ir in enumerate(context_types):
            environment.append((f"{CONTEXT_PREFIX}{index}", self.sort(ir, f"{path}.context[{index}]")))
        self._context = list(environment)
        assertions = []
        for index, hypothesis in enumerate(hypotheses):
            hypothesis_path = f"{path}.hypotheses[{index}]"
            value = self.term(hypothesis, environment, hypothesis_path)
            if value.sort != SORT_BOOL:
                _fail(hypothesis_path, f"a hypothesis must translate to Bool, got {value.sort}")
            assertions.append(value.text)
        conclusion = self.term(goal, environment, f"{path}.goal")
        if conclusion.sort != SORT_BOOL:
            _fail(f"{path}.goal", f"a goal must translate to Bool, got {conclusion.sort}")
        return self._render(assertions, conclusion.text)

    def _render(self, assertions: list[str], goal: str) -> str:
        lines = ["(set-logic ALL)"]
        for sort in sorted(self._opaque):
            lines.append(f"(declare-sort {sort} 0)")
        names = sorted([*self._datatypes, *([SORT_UNIT] if self._unit else [])])
        if names:
            header = " ".join(f"({name} 0)" for name in names)
            bodies = []
            for name in names:
                if name == SORT_UNIT:
                    bodies.append(f"(({UNIT_CONSTRUCTOR}))")
                    continue
                forms = []
                for index, field_sorts in enumerate(self._datatypes[name]):
                    fields = [f"({name}.c{index}.f{position} {sort})" for position, sort in enumerate(field_sorts)]
                    forms.append(_form(f"{name}.c{index}", fields))
                bodies.append("(" + " ".join(forms) + ")")
            lines.append(f"(declare-datatypes ({header}) ({' '.join(bodies)}))")
        for symbol, sort in self._context:
            lines.append(f"(declare-const {symbol} {sort})")
        for symbol in sorted(self._constants):
            lines.append(f"(declare-const {symbol} {self._constants[symbol]})")
        for symbol in sorted(self._functions):
            arguments, result = self._functions[symbol]
            lines.append(f"(declare-fun {symbol} ({' '.join(arguments)}) {result})")
        by_sort: dict[str, list[str]] = {}
        for symbol, sort in self._constants.items():
            by_sort.setdefault(sort, []).append(symbol)
        for sort in sorted(by_sort):
            members = sorted(by_sort[sort])
            if len(members) > 1:
                lines.append(f"(assert (distinct {' '.join(members)}))")
        for symbol, sort in self._context:
            if sort == SORT_INT:
                lines.append(f"(assert (and (<= (- {-I64_MIN}) {symbol}) (<= {symbol} {I64_MAX})))")
        for assertion in assertions:
            lines.append(f"(assert {assertion})")
        lines.append(f"(assert (not {goal}))")
        lines.append("(check-sat)")
        lines.append("(exit)")
        return "\n".join(lines) + "\n"


def obligation_script(context_types, hypotheses, goal, registry, signatures=None, interpretations=None) -> str:
    """Canonical script for a verification condition over an explicit context."""
    return ObligationTranslator(registry, signatures, interpretations).script(list(context_types), list(hypotheses), goal)


def subtype_script(base_type, weaker, stronger, registry, signatures=None, interpretations=None, outer_context=()) -> str:
    """Canonical script for `{x:T|weaker} <: {x:T|stronger}` (SPEC.md §3.3)."""
    return obligation_script([base_type, *outer_context], [weaker], stronger, registry, signatures, interpretations)


def check_translatable(refinement_type, registry, signatures=None, interpretations=None, path: str = "type") -> None:
    """Raise `SmtError` unless a `[3, T, φ]` node lies inside the decidable fragment."""
    if not isinstance(refinement_type, list) or len(refinement_type) != 3 or refinement_type[0] != 3:
        _fail(path, "expected a refinement type node")
    ObligationTranslator(registry, signatures, interpretations).script([refinement_type[1]], [], refinement_type[2], path)


def script_hash(script: str) -> str:
    """Memo-ledger payload hash of a canonical script (SPEC.md §6.4)."""
    return hashlib.sha256(script.encode("utf-8")).hexdigest()
