"""First type-directed layer: nominal constructor and match validation."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from declarations import DeclarationError, DeclarationRegistry
from references import check_definition_references
from scope import check_definition
from transcode import parse_source


@dataclass(frozen=True)
class TypeDirectionError(ValueError):
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _fail(path: str, message: str) -> None:
    raise TypeDirectionError(path, message)


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
    def __init__(self, registry: DeclarationRegistry):
        self.registry = registry

    def check_definition(self, ir) -> None:
        check_definition(ir, self.registry.operation_arity)
        check_definition_references(ir, self.registry)
        self.check(ir[2], ir[1], [], "definition.term")

    def check(self, term, expected, environment: list, path: str) -> None:
        tag = term[0]
        if tag == 6:
            if expected[0] != 1 or term[1] != expected[1]:
                _fail(path, "constructor does not match the expected nominal data type")
            fields = constructor_fields(self.registry, expected, term[2], path)
            if len(term[3]) != len(fields):
                _fail(path, f"constructor {term[2]} expects {len(fields)} arguments, got {len(term[3])}")
            for index, (argument, field_type) in enumerate(zip(term[3], fields)):
                self.check(argument, field_type, environment, f"{path}.args[{index}]")
            return
        actual = self.synth(term, environment, path)
        if actual != expected:
            _fail(path, f"type mismatch: expected {expected!r}, got {actual!r}")

    def synth(self, term, environment: list, path: str):
        tag = term[0]
        if tag == 0:
            try:
                return copy.deepcopy(environment[term[1]])
            except IndexError:
                _fail(path, f"variable index {term[1]} has no type in the environment")
        if tag == 2:
            kinds = {0: [0, 0], 1: [0, 1], 2: [0, 2], 3: [0, 3], 4: [0, 4], 5: [0, 5]}
            return kinds[term[1]]
        if tag == 3:
            parameter_type = term[1]
            body_type = self.synth(term[2], [parameter_type, *environment], f"{path}.body")
            return [2, copy.deepcopy(parameter_type), [], body_type]
        if tag == 4:
            function_type = self.synth(term[1], environment, f"{path}.function")
            if function_type[0] != 2:
                _fail(path, "application function does not synthesize a function type")
            self.check(term[2], function_type[1], environment, f"{path}.argument")
            return copy.deepcopy(function_type[3])
        if tag == 5:
            self.check(term[2], term[1], environment, f"{path}.bound")
            return self.synth(term[3], [term[1], *environment], f"{path}.body")
        if tag == 6:
            declaration = _lookup_data(self.registry, term[1], path)
            if declaration[2] != 0:
                _fail(path, "parameterized constructor needs an expected data type")
            result = [1, term[1], []]
            self.check(term, result, environment, path)
            return result
        if tag == 7:
            scrutinee_type = self.synth(term[1], environment, f"{path}.scrutinee")
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
                arm_type = self.synth(arm[2], arm_environment, f"{arm_path}.body")
                if result_type is None:
                    result_type = arm_type
                elif arm_type != result_type:
                    _fail(arm_path, f"arm result type {arm_type!r} differs from {result_type!r}")
            missing = sorted(set(range(constructor_count)) - seen)
            if missing:
                _fail(path, f"non-exhaustive match; missing constructors {missing}")
            if result_type is None:
                _fail(path, "match over an empty data declaration has no synthesizable result")
            return result_type
        if tag == 11:
            return copy.deepcopy(term[1])
        _fail(path, f"type synthesis for term tag {tag} is not implemented in the nominal match layer")


def validate_source(source: str, registry: DeclarationRegistry):
    ir = parse_source(source)
    MatchChecker(registry).check_definition(ir)
    return ir
