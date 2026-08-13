"""Partial bidirectional type checker for the implemented Loom subset."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass

from declarations import DeclarationError, DeclarationRegistry
from references import check_definition_references
from scope import check_definition, forall_prefix
from transcode import parse_source

#: Resolves a stored definition hash to the definition's Loom type. The match
#: layer has no store, so the type of a `ref` is supplied the way `scope.py`
#: supplies ability arities: injected, never guessed.
ReferenceTypeResolver = Callable[[bytes], list]

#: §2.5 measures map the *selected* argument to a number — the `fix` node's
#: position field says which. v0.1 has no natural base type, so the prototype
#: checks a measure against `fn D_k () I64`.
MEASURE_RESULT = [0, 2]

BOOL = [0, 1]


@dataclass(frozen=True)
class TypingError(ValueError):
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _fail(path: str, message: str) -> None:
    raise TypingError(path, message)


def _lookup_data(registry: DeclarationRegistry, digest: bytes, path: str) -> list:
    try:
        return registry.data_object(digest)
    except DeclarationError as exc:
        _fail(path, str(exc))


def instantiate_type(ir, arguments: list, self_hash: bytes, path: str = "type"):
    """Instantiate declaration tyvars and local self in a constructor field type."""
    tag = ir[0]
    if tag == 5:
        index = ir[1]
        if index >= len(arguments):
            _fail(path, f"declaration type index {index} exceeds {len(arguments)} arguments")
        return copy.deepcopy(arguments[index])
    if tag == 7:
        instantiated = [instantiate_type(arg, arguments, self_hash, f"{path}.self-args[{i}]") for i, arg in enumerate(ir[1])]
        return [1, self_hash, instantiated]
    if tag == 0 or tag == 4:
        return copy.deepcopy(ir)
    if tag == 1:
        return [1, ir[1], [instantiate_type(arg, arguments, self_hash, f"{path}.args[{i}]") for i, arg in enumerate(ir[2])]]
    if tag == 2:
        row = []
        for item in ir[2]:
            row.append(copy.deepcopy(item) if isinstance(item, bytes) else instantiate_type(item, arguments, self_hash, f"{path}.row"))
        return [2, instantiate_type(ir[1], arguments, self_hash, f"{path}.domain"), row, instantiate_type(ir[3], arguments, self_hash, f"{path}.codomain")]
    if tag == 3:
        # Predicate terms contain term variables, not declaration type nodes;
        # only the refined base participates in this first substitution layer.
        return [3, instantiate_type(ir[1], arguments, self_hash, f"{path}.base"), copy.deepcopy(ir[2])]
    if tag == 6:
        _fail(path, "constructor fields with nested forall are not supported by the nominal match prototype")
    _fail(path, f"unknown declaration type tag {tag!r}")


def constructor_fields(registry: DeclarationRegistry, data_type, constructor: int, path: str):
    if data_type[0] != 1:
        _fail(path, "expected a nominal data type")
    declaration = _lookup_data(registry, data_type[1], path)
    parameter_count, constructors = declaration[2], declaration[3]
    if len(data_type[2]) != parameter_count:
        _fail(path, f"data expects {parameter_count} type arguments, got {len(data_type[2])}")
    if constructor >= len(constructors):
        _fail(path, f"constructor index {constructor} is out of range for {len(constructors)} constructors")
    return [instantiate_type(field, data_type[2], data_type[1], f"{path}.fields[{i}]") for i, field in enumerate(constructors[constructor])]


class MatchChecker:
    def __init__(self, registry: DeclarationRegistry, reference_type: ReferenceTypeResolver | None = None):
        self.registry = registry
        self.reference_type = reference_type

    def check_definition(self, ir) -> None:
        check_definition(ir, self.registry.operation_arity)
        check_definition_references(ir, self.registry)
        # §3.1.3: a `forall^p` definition type is the type abstraction itself, so
        # the term is checked against the quantified body. Type variables stay
        # opaque atoms under structural type equality, which is parametricity.
        _, quantified = forall_prefix(ir[1])
        self.check(ir[2], quantified, [], (), "definition.term")

    def check(self, term, expected, environment: list, ambient: tuple[bytes, ...], path: str) -> None:
        tag = term[0]
        if tag == 3 and expected[0] == 2:
            if term[1] != expected[1]:
                _fail(path, "lambda parameter annotation differs from expected domain")
            row = self._closed_row(expected[2], f"{path}.effect-row")
            self.check(term[2], expected[3], [term[1], *environment], row, f"{path}.body")
            return
        if tag == 6:
            if expected[0] != 1 or term[1] != expected[1]:
                _fail(path, "constructor does not match the expected nominal data type")
            fields = constructor_fields(self.registry, expected, term[2], path)
            if len(term[3]) != len(fields):
                _fail(path, f"constructor {term[2]} expects {len(fields)} arguments, got {len(term[3])}")
            for index, (argument, field_type) in enumerate(zip(term[3], fields)):
                self.check(argument, field_type, environment, ambient, f"{path}.args[{index}]")
            return
        if tag == 7:
            self._check_match(term, environment, ambient, path, expected)
            return
        if tag == 9:
            self._check_handler(term, expected, environment, ambient, path)
            return
        if tag == 10:
            self._check_fix(term, expected, environment, ambient, path)
            return
        if tag == 12:
            self.check(term[1], BOOL, environment, ambient, f"{path}.condition")
            self.check(term[2], expected, environment, ambient, f"{path}.then")
            self.check(term[3], expected, environment, ambient, f"{path}.else")
            return
        actual = self.synth(term, environment, ambient, path)
        if actual == expected:
            return
        # §3.1.3: a term that synthesizes `forall^p T` — in practice a `ref`
        # whose resolved type is quantified — is instantiated by first-order
        # matching of `T` against the expected type, rather than failing the
        # plain structural comparison outright. Synthesis position (the
        # `synth` method) never reaches here and stays uninstantiated.
        if isinstance(actual, list) and actual and actual[0] == 6:
            self._instantiate(actual, expected, path)
            return
        _fail(path, f"type mismatch: expected {expected!r}, got {actual!r}")

    def synth(self, term, environment: list, ambient: tuple[bytes, ...], path: str):
        tag = term[0]
        if tag == 1:
            return self._resolve_reference(term[1], path)
        if tag == 0:
            try:
                return copy.deepcopy(environment[term[1]])
            except IndexError:
                _fail(path, f"variable index {term[1]} has no type in the environment")
        if tag == 2:
            kinds = {0: [0, 0], 1: [0, 1], 2: [0, 2], 3: [0, 3], 4: [0, 4], 5: [0, 5]}
            return kinds[term[1]]
        if tag == 3:
            # A synthesized lambda is pure: its type carries the empty row, so
            # its body must not lean on the ambient allowance at the synthesis
            # site — latent effects require checking against an annotated row.
            parameter_type = term[1]
            body_type = self.synth(term[2], [parameter_type, *environment], (), f"{path}.body")
            return [2, copy.deepcopy(parameter_type), [], body_type]
        if tag == 4:
            function_type = self.synth(term[1], environment, ambient, f"{path}.function")
            if function_type[0] != 2:
                _fail(path, "application function does not synthesize a function type")
            call_row = self._closed_row(function_type[2], f"{path}.function-row")
            self._require_allowed(call_row, ambient, path)
            self.check(term[2], function_type[1], environment, ambient, f"{path}.argument")
            return copy.deepcopy(function_type[3])
        if tag == 5:
            self.check(term[2], term[1], environment, ambient, f"{path}.bound")
            return self.synth(term[3], [term[1], *environment], ambient, f"{path}.body")
        if tag == 6:
            declaration = _lookup_data(self.registry, term[1], path)
            if declaration[2] != 0:
                _fail(path, "parameterized constructor needs an expected data type")
            result = [1, term[1], []]
            self.check(term, result, environment, ambient, path)
            return result
        if tag == 7:
            return self._check_match(term, environment, ambient, path, None)
        if tag == 8:
            try:
                parameters, result = self.registry.operation_signature(term[1], term[2])
            except (DeclarationError, LookupError) as exc:
                _fail(path, f"cannot resolve operation signature: {exc}")
            self._require_allowed((term[1],), ambient, path)
            self._require_capability(term[1], environment, path)
            if len(term[3]) != len(parameters):
                _fail(path, f"operation expects {len(parameters)} arguments, got {len(term[3])}")
            for index, (argument, parameter) in enumerate(zip(term[3], parameters)):
                self.check(argument, parameter, environment, ambient, f"{path}.args[{index}]")
            return result
        if tag == 9:
            _fail(path, "handler requires an expected result type")
        if tag == 10:
            return self._check_fix(term, None, environment, ambient, path)
        if tag == 11:
            return copy.deepcopy(term[1])
        if tag == 12:
            self.check(term[1], BOOL, environment, ambient, f"{path}.condition")
            consequent = self.synth(term[2], environment, ambient, f"{path}.then")
            alternative = self.synth(term[3], environment, ambient, f"{path}.else")
            if consequent != alternative:
                _fail(path, f"branch type {alternative!r} differs from {consequent!r}")
            return consequent
        _fail(path, f"type synthesis for term tag {tag} is not implemented in the partial type checker")

    def _check_match(self, term, environment, ambient, path, expected):
        scrutinee_type = self.synth(term[1], environment, ambient, f"{path}.scrutinee")
        if scrutinee_type[0] != 1:
            _fail(path, "match scrutinee does not synthesize a nominal data type")
        declaration = _lookup_data(self.registry, scrutinee_type[1], path)
        constructor_count = len(declaration[3])
        seen = set()
        result_type = None
        for arm_position, arm in enumerate(term[2]):
            arm_path = f"{path}.arms[{arm_position}]"
            constructor = arm[0]
            if constructor in seen:
                _fail(arm_path, f"duplicate constructor arm {constructor}")
            seen.add(constructor)
            fields = constructor_fields(self.registry, scrutinee_type, constructor, arm_path)
            if arm[1] != len(fields):
                _fail(arm_path, f"binder count {arm[1]} does not match constructor field count {len(fields)}")
            arm_environment = [*reversed(fields), *environment]
            if expected is not None:
                try:
                    self.check(arm[2], expected, arm_environment, ambient, f"{arm_path}.body")
                except TypingError as exc:
                    if exc.path == f"{arm_path}.body" and exc.message.startswith("type mismatch:"):
                        _fail(arm_path, f"arm result type differs from expected type: {exc.message}")
                    raise
            else:
                arm_type = self.synth(arm[2], arm_environment, ambient, f"{arm_path}.body")
                if result_type is None:
                    result_type = arm_type
                elif arm_type != result_type:
                    _fail(arm_path, f"arm result type {arm_type!r} differs from {result_type!r}")
        missing = sorted(set(range(constructor_count)) - seen)
        if missing:
            _fail(path, f"non-exhaustive match; missing constructors {missing}")
        if expected is not None:
            return copy.deepcopy(expected)
        if result_type is None:
            _fail(path, "match over an empty data declaration has no synthesizable result")
        return result_type

    def _resolve_reference(self, digest, path):
        if self.reference_type is None:
            _fail(path, f"reference {digest.hex()} is unresolved: the match layer has no reference-type resolver")
        try:
            resolved = self.reference_type(digest)
        except (KeyError, LookupError, DeclarationError):
            resolved = None
        if not isinstance(resolved, list) or not resolved:
            _fail(path, f"reference {digest.hex()} has no resolvable type")
        return copy.deepcopy(resolved)

    def _instantiate(self, quantified, expected, path):
        """§3.1.3: instantiate `forall^p T` against expected type `E` by
        first-order matching.

        Peels the leading `forall`s off `quantified`, matches the remaining
        body against `E` to find a binding for every one of the `p` type
        variables, then substitutes those bindings back into the body and
        checks the result equals `E` (matching succeeded elsewhere already
        guarantees this by construction; the check here is defense in depth,
        not a second source of truth).

        `E` may itself contain type variables — when the checking definition
        is itself polymorphic, its own `forall`-bound `tyvar` nodes appear
        inside `E` unsubstituted (§2.3.1: nothing in this layer ever
        substitutes a definition's *own* type variables, they stay opaque
        atoms). Those nodes are never inspected as binding sites here — only
        `quantified`'s own prefix variables are — so they bind like any other
        concrete subtree, which is exactly what makes them "concrete from the
        callee's perspective".
        """
        depth, body = 0, quantified
        while isinstance(body, list) and len(body) == 2 and body[0] == 6:
            depth += 1
            body = body[1]
        bindings: list = [None] * depth
        self._match_type(body, expected, bindings, depth, path)
        unbound = [index for index, binding in enumerate(bindings) if binding is None]
        if unbound:
            _fail(path, f"type variable(s) {unbound} were never matched against the expected type")
        instantiated = self._substitute_type(body, bindings, depth, path)
        if instantiated != expected:
            _fail(path, "instantiated type does not equal the expected type")
        return instantiated

    def _match_type(self, pattern, target, bindings: list, depth: int, path: str) -> None:
        """Walk `pattern` (a quantified body) against `target` (a concrete
        type), binding each `tyvar i` (i < depth) to the subtree of `target`
        it stands against. Every occurrence of the same `tyvar` must bind to
        the same subtree; anything else is a path-aware match failure.
        """
        if not isinstance(pattern, list) or not pattern:
            _fail(path, f"malformed type node {pattern!r}")
        if pattern[0] == 5 and pattern[1] < depth:
            index = pattern[1]
            if bindings[index] is None:
                bindings[index] = copy.deepcopy(target)
            elif bindings[index] != target:
                _fail(path, f"type variable {index} matched both {bindings[index]!r} and {target!r}")
            return
        if not isinstance(target, list) or not target or target[0] != pattern[0]:
            _fail(path, f"cannot match {pattern!r} against expected type {target!r}")
        tag = pattern[0]
        if tag == 0 or tag == 4:
            if pattern != target:
                _fail(path, f"{pattern!r} does not match expected type {target!r}")
            return
        if tag == 1:
            if pattern[1] != target[1] or len(pattern[2]) != len(target[2]):
                _fail(path, f"nominal type {pattern!r} does not match expected type {target!r}")
            for index, (pattern_arg, target_arg) in enumerate(zip(pattern[2], target[2])):
                self._match_type(pattern_arg, target_arg, bindings, depth, f"{path}.args[{index}]")
            return
        if tag == 2:
            self._match_type(pattern[1], target[1], bindings, depth, f"{path}.domain")
            # §3.1.3's rule substitutes types only; row variables are out of
            # scope, so a row on either side must already be closed.
            pattern_row = self._closed_row(pattern[2], f"{path}.pattern-row")
            target_row = self._closed_row(target[2], f"{path}.target-row")
            if pattern_row != target_row:
                _fail(path, f"effect row {pattern_row!r} does not match expected row {target_row!r}")
            self._match_type(pattern[3], target[3], bindings, depth, f"{path}.codomain")
            return
        if tag == 3:
            self._match_type(pattern[1], target[1], bindings, depth, f"{path}.base")
            # The predicate is a term, not a declaration-type node (§3.2); this
            # matching layer substitutes types only, so a refinement predicate
            # that differs cannot be reconciled here.
            if pattern[2] != target[2]:
                _fail(path, "refinement predicate differs and cannot be matched by first-order type instantiation")
            return
        if tag == 5:
            # A pattern tyvar with index >= depth is free with respect to this
            # instantiation (not one of `quantified`'s own p binders); scope
            # validation of the original definition already guarantees every
            # tyvar under a stored type's forall prefix is < depth, so this is
            # unreachable for a legitimately checked resolver result and is
            # handled only defensively.
            if pattern != target:
                _fail(path, f"free type variable {pattern!r} does not match expected type {target!r}")
            return
        if tag == 6:
            _fail(path, "a stored type with a forall nested past the prenex cannot be instantiated by first-order matching")
        _fail(path, f"unknown declaration type tag {tag!r} during instantiation")

    def _substitute_type(self, pattern, bindings: list, depth: int, path: str):
        """Rebuild `pattern` with each bound `tyvar i` (i < depth) replaced by
        its binding. Mirrors `instantiate_type`'s tag dispatch, but over
        term-level types (tags 0-6, §2.3) rather than declaration-field types
        (which additionally carry tag 7 self-reference, not applicable here).
        """
        tag = pattern[0]
        if tag == 5:
            if pattern[1] < depth:
                return copy.deepcopy(bindings[pattern[1]])
            return copy.deepcopy(pattern)
        if tag == 0 or tag == 4:
            return copy.deepcopy(pattern)
        if tag == 1:
            return [1, pattern[1], [self._substitute_type(arg, bindings, depth, f"{path}.args[{i}]") for i, arg in enumerate(pattern[2])]]
        if tag == 2:
            row = [copy.deepcopy(item) if isinstance(item, bytes) else self._substitute_type(item, bindings, depth, f"{path}.row") for item in pattern[2]]
            return [2, self._substitute_type(pattern[1], bindings, depth, f"{path}.domain"), row, self._substitute_type(pattern[3], bindings, depth, f"{path}.codomain")]
        if tag == 3:
            return [3, self._substitute_type(pattern[1], bindings, depth, f"{path}.base"), copy.deepcopy(pattern[2])]
        if tag == 6:
            _fail(path, "a stored type with a forall nested past the prenex cannot be instantiated by first-order matching")
        _fail(path, f"unknown declaration type tag {tag!r} during instantiation")

    def _check_fix(self, term, expected, environment, ambient, path):
        annotation = term[1]
        if expected is not None and annotation != expected:
            _fail(path, f"fix annotation differs from the expected type: expected {expected!r}, got {annotation!r}")
        if annotation[0] != 2:
            # §2.5's measure maps the *selected* argument to a number, so a
            # recursive value with no argument has nothing to measure.
            _fail(path, "fix at a non-function type is not implemented in the partial type checker")
        self._closed_row(annotation[2], f"{path}.effect-row")
        decreasing = self._measure_domain(annotation, term[2], path)
        # The measure is checked at the current environment (§2.3.1) as a pure
        # function from the selected argument to I64. Whether it *decreases* is
        # the oracle's `terminates` obligation (§2.5, §6.2); this layer types the
        # term and discharges nothing.
        measure_type = [2, decreasing, [], copy.deepcopy(MEASURE_RESULT)]
        self.check(term[3], measure_type, environment, ambient, f"{path}.measure")
        # Forming a recursive function value is itself pure, so the body checks
        # under the unchanged ambient allowance; because the annotation is a fn
        # type, a lam body immediately re-anchors that allowance to the
        # annotation's own row per §3.1.2.
        body_environment = [copy.deepcopy(annotation), *environment]
        self.check(term[4], annotation, body_environment, ambient, f"{path}.body")
        return copy.deepcopy(annotation)

    @staticmethod
    def _measure_domain(annotation, position, path):
        """`D_k`: the domain reached by walking `position` arrows of the spine.

        Rows walked past are deliberately not constrained — reaching argument
        `k` may perform effects, which changes nothing about how many times the
        recursion runs (§2.5). Only the measure's own row must be empty.
        """
        if not isinstance(position, int) or isinstance(position, bool) or position < 0:
            _fail(path, f"invalid measure position {position!r}")
        spine = annotation
        for step in range(position):
            spine = spine[3]
            if spine[0] != 2:
                _fail(path, f"measure position {position} exceeds the annotation's {step + 1}-argument curried spine")
        return copy.deepcopy(spine[1])

    def _check_handler(self, term, expected, environment, ambient, path):
        try:
            ability = self.registry.ability_object(term[1])
        except DeclarationError as exc:
            _fail(path, str(exc))
        if not ability[2]:
            _fail(path, "an ability with no operations is an effect marker and cannot be handled")
        handled_ambient = tuple(sorted(set([*ambient, term[1]])))
        handled_type = self.synth(term[2], environment, handled_ambient, f"{path}.handled")
        self.check(term[4], expected, [handled_type, *environment], ambient, f"{path}.return")
        seen = set()
        for position, operation in enumerate(term[3]):
            op_path = f"{path}.operations[{position}]"
            index = operation[0]
            if index in seen:
                _fail(op_path, f"duplicate operation clause {index}")
            seen.add(index)
            try:
                parameters, operation_result = self.registry.operation_signature(term[1], index)
            except LookupError:
                _fail(op_path, f"operation index {index} is out of range")
            continuation = [2, operation_result, list(ambient), copy.deepcopy(expected)]
            clause_environment = [continuation, *reversed(parameters), *environment]
            self.check(operation[1], expected, clause_environment, ambient, f"{op_path}.body")
        missing = sorted(set(range(len(ability[2]))) - seen)
        if missing:
            _fail(path, f"handler is missing operation clauses {missing}")

    @staticmethod
    def _closed_row(row, path):
        if any(not isinstance(item, bytes) for item in row):
            _fail(path, "row-polymorphic effect checking is not implemented")
        return tuple(row)

    @staticmethod
    def _require_allowed(required, ambient, path):
        for ability in required:
            if ability not in ambient:
                _fail(path, f"ability {ability.hex()} is not allowed by the ambient effect row")

    @staticmethod
    def _require_capability(ability, environment, path):
        if [4, ability] not in environment:
            _fail(path, f"ability {ability.hex()} has no capability value in scope")


def validate_source(source: str, registry: DeclarationRegistry, reference_type: ReferenceTypeResolver | None = None):
    ir = parse_source(source)
    MatchChecker(registry, reference_type).check_definition(ir)
    return ir
