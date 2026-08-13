"""Registry-backed nominal reference and explicit arity validation."""

from __future__ import annotations

from dataclasses import dataclass

from declarations import DeclarationError, DeclarationRegistry
from scope import check_definition
from transcode import parse_source


@dataclass(frozen=True)
class ReferenceError(ValueError):
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _fail(path: str, message: str) -> None:
    raise ReferenceError(path, message)


def _lookup(path: str, operation):
    try:
        return operation()
    except DeclarationError as exc:
        _fail(path, str(exc))


def check_type_references(ir, registry: DeclarationRegistry, path: str = "type") -> None:
    tag = ir[0]
    if tag == 0:
        return
    if tag == 1:
        info = _lookup(path, lambda: registry.data(ir[1]))
        if len(ir[2]) != info.parameter_count:
            _fail(path, f"data expects {info.parameter_count} type arguments, got {len(ir[2])}")
        for index, argument in enumerate(ir[2]):
            check_type_references(argument, registry, f"{path}.args[{index}]")
        return
    if tag == 2:
        check_type_references(ir[1], registry, f"{path}.domain")
        for index, effect in enumerate(ir[2]):
            if isinstance(effect, bytes):
                _lookup(f"{path}.row[{index}]", lambda effect=effect: registry.ability(effect))
        check_type_references(ir[3], registry, f"{path}.codomain")
        return
    if tag == 3:
        check_type_references(ir[1], registry, f"{path}.base")
        check_term_references(ir[2], registry, f"{path}.predicate")
        return
    if tag == 4:
        _lookup(path, lambda: registry.ability(ir[1]))
        return
    if tag == 5:
        return
    if tag == 6:
        check_type_references(ir[1], registry, f"{path}.body")
        return
    _fail(path, f"unknown type tag {tag!r}")


def check_term_references(ir, registry: DeclarationRegistry, path: str = "term") -> None:
    tag = ir[0]
    if tag in (0, 1, 2):
        return
    if tag == 3:
        check_type_references(ir[1], registry, f"{path}.parameter-type")
        check_term_references(ir[2], registry, f"{path}.body")
        return
    if tag == 4:
        check_term_references(ir[1], registry, f"{path}.function")
        check_term_references(ir[2], registry, f"{path}.argument")
        return
    if tag == 5:
        check_type_references(ir[1], registry, f"{path}.binding-type")
        check_term_references(ir[2], registry, f"{path}.bound")
        check_term_references(ir[3], registry, f"{path}.body")
        return
    if tag == 6:
        info = _lookup(path, lambda: registry.data(ir[1]))
        index = ir[2]
        if index >= len(info.field_counts):
            _fail(path, f"constructor index {index} is out of range for {len(info.field_counts)} constructors")
        expected = info.field_counts[index]
        if len(ir[3]) != expected:
            _fail(path, f"constructor {index} expects {expected} arguments, got {len(ir[3])}")
        for arg_index, argument in enumerate(ir[3]):
            check_term_references(argument, registry, f"{path}.args[{arg_index}]")
        return
    if tag == 7:
        check_term_references(ir[1], registry, f"{path}.scrutinee")
        for index, arm in enumerate(ir[2]):
            check_term_references(arm[2], registry, f"{path}.arms[{index}].body")
        return
    if tag == 8:
        info = _lookup(path, lambda: registry.ability(ir[1]))
        index = ir[2]
        if index >= len(info.parameter_counts):
            _fail(path, f"operation index {index} is out of range for {len(info.parameter_counts)} operations")
        expected = info.parameter_counts[index]
        if len(ir[3]) != expected:
            _fail(path, f"operation {index} expects {expected} arguments, got {len(ir[3])}")
        for arg_index, argument in enumerate(ir[3]):
            check_term_references(argument, registry, f"{path}.args[{arg_index}]")
        return
    if tag == 9:
        info = _lookup(path, lambda: registry.ability(ir[1]))
        check_term_references(ir[2], registry, f"{path}.handled")
        for index, operation in enumerate(ir[3]):
            operation_index = operation[0]
            if operation_index >= len(info.parameter_counts):
                _fail(f"{path}.operations[{index}]", f"operation index {operation_index} is out of range for {len(info.parameter_counts)} operations")
            check_term_references(operation[1], registry, f"{path}.operations[{index}].body")
        check_term_references(ir[4], registry, f"{path}.return")
        return
    if tag == 10:
        check_type_references(ir[1], registry, f"{path}.type")
        check_term_references(ir[3], registry, f"{path}.measure")
        check_term_references(ir[4], registry, f"{path}.body")
        return
    if tag == 11:
        check_type_references(ir[1], registry, f"{path}.goal-type")
        for index, constraint in enumerate(ir[2]):
            check_term_references(constraint, registry, f"{path}.constraints[{index}]")
        return
    _fail(path, f"unknown term tag {tag!r}")


def check_definition_references(ir, registry: DeclarationRegistry) -> None:
    check_type_references(ir[1], registry, "definition.type")
    check_term_references(ir[2], registry, "definition.term")


def validate_source(source: str, registry: DeclarationRegistry):
    """Parse canonical source, check scope and nominal references, return IR."""
    ir = parse_source(source)
    check_definition(ir, registry.operation_arity)
    check_definition_references(ir, registry)
    return ir
