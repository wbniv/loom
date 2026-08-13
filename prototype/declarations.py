"""Canonical data/ability declarations and content-addressed registry."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass

import cbor_canonical
from scope import ScopeError, check_term


class DeclarationError(ValueError):
    pass


def _error(path: str, message: str) -> None:
    raise DeclarationError(f"{path}: {message}")


def _array(value, path: str, arity: int | None = None) -> list:
    if not isinstance(value, list):
        _error(path, "expected an array")
    if arity is not None and len(value) != arity:
        _error(path, f"expected array length {arity}, got {len(value)}")
    return value


def _uint(value, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _error(path, "expected a nonnegative integer")
    return value


def _nominal_key(value, path: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        _error(path, "expected a 32-byte nominal key")
    return value


def check_declaration_type(ir, type_depth: int, self_arity: int | None, path: str) -> None:
    node = _array(ir, path)
    if not node:
        _error(path, "empty type node")
    tag = node[0]
    if tag == 0:
        _array(node, path, 2)
        if node[1] not in range(6):
            _error(path, f"invalid base code {node[1]!r}")
        return
    if tag == 1:
        _array(node, path, 3)
        if not isinstance(node[1], bytes) or len(node[1]) != 32:
            _error(path, "data reference must be a 32-byte hash")
        for index, argument in enumerate(_array(node[2], f"{path}.args")):
            check_declaration_type(argument, type_depth, self_arity, f"{path}.args[{index}]")
        return
    if tag == 2:
        _array(node, path, 4)
        check_declaration_type(node[1], type_depth, self_arity, f"{path}.domain")
        for index, effect in enumerate(_array(node[2], f"{path}.row")):
            if isinstance(effect, bytes) and len(effect) == 32:
                continue
            row_var = _array(effect, f"{path}.row[{index}]", 2)
            if row_var[0] != 5 or _uint(row_var[1], f"{path}.row[{index}]") >= type_depth:
                _error(f"{path}.row[{index}]", "row type variable is out of scope")
        check_declaration_type(node[3], type_depth, self_arity, f"{path}.codomain")
        return
    if tag == 3:
        _array(node, path, 3)
        check_declaration_type(node[1], type_depth, self_arity, f"{path}.base")
        try:
            check_term(node[2], term_depth=1, type_depth=type_depth, path=f"{path}.predicate")
        except ScopeError as exc:
            raise DeclarationError(str(exc)) from exc
        return
    if tag == 4:
        _array(node, path, 2)
        if not isinstance(node[1], bytes) or len(node[1]) != 32:
            _error(path, "capability reference must be a 32-byte hash")
        return
    if tag == 5:
        _array(node, path, 2)
        if _uint(node[1], path) >= type_depth:
            _error(path, f"type index {node[1]} is out of scope at depth {type_depth}")
        return
    if tag == 6:
        _array(node, path, 2)
        check_declaration_type(node[1], type_depth + 1, self_arity, f"{path}.body")
        return
    if tag == 7:
        _array(node, path, 2)
        if self_arity is None:
            _error(path, "self type is forbidden outside a data declaration")
        arguments = _array(node[1], f"{path}.args")
        if len(arguments) != self_arity:
            _error(path, f"self expects {self_arity} type arguments, got {len(arguments)}")
        for index, argument in enumerate(arguments):
            check_declaration_type(argument, type_depth, self_arity, f"{path}.args[{index}]")
        return
    _error(path, f"unknown declaration type tag {tag!r}")


def check_data_declaration(obj) -> None:
    node = _array(obj, "data", 4)
    if node[0] != 4:
        _error("data", "expected object-kind tag 4")
    _nominal_key(node[1], "data.nominal-key")
    parameter_count = _uint(node[2], "data.parameter-count")
    for ctor_index, constructor in enumerate(_array(node[3], "data.constructors")):
        for field_index, field_type in enumerate(_array(constructor, f"data.constructors[{ctor_index}]")):
            check_declaration_type(field_type, parameter_count, parameter_count, f"data.constructors[{ctor_index}].fields[{field_index}]")


def check_ability_declaration(obj) -> None:
    node = _array(obj, "ability", 3)
    if node[0] != 5:
        _error("ability", "expected object-kind tag 5")
    _nominal_key(node[1], "ability.nominal-key")
    for op_index, operation in enumerate(_array(node[2], "ability.operations")):
        op = _array(operation, f"ability.operations[{op_index}]", 2)
        for parameter_index, parameter_type in enumerate(_array(op[0], f"ability.operations[{op_index}].parameters")):
            check_declaration_type(parameter_type, 0, None, f"ability.operations[{op_index}].parameters[{parameter_index}]")
        check_declaration_type(op[1], 0, None, f"ability.operations[{op_index}].result")


def declaration_bytes(obj) -> bytes:
    node = _array(obj, "declaration")
    if not node:
        _error("declaration", "empty object")
    if node[0] == 4:
        check_data_declaration(node)
    elif node[0] == 5:
        check_ability_declaration(node)
    else:
        _error("declaration", f"expected object kind 4 or 5, got {node[0]!r}")
    return cbor_canonical.encode(node)


def declaration_hash(obj) -> bytes:
    return hashlib.sha256(declaration_bytes(obj)).digest()


@dataclass(frozen=True)
class DataInfo:
    parameter_count: int
    field_counts: tuple[int, ...]


@dataclass(frozen=True)
class AbilityInfo:
    parameter_counts: tuple[int, ...]


class DeclarationRegistry:
    def __init__(self, objects=()):
        self._objects: dict[bytes, list] = {}
        for obj in objects:
            self.add(obj)

    def add(self, obj, expected_hash: bytes | None = None) -> bytes:
        digest = declaration_hash(obj)
        if expected_hash is not None and expected_hash != digest:
            raise DeclarationError(f"registry: supplied hash {expected_hash.hex()} does not match canonical hash {digest.hex()}")
        self._objects[digest] = copy.deepcopy(obj)
        return digest

    def data(self, digest: bytes) -> DataInfo:
        obj = self._resolve(digest, 4, "data")
        return DataInfo(obj[2], tuple(len(fields) for fields in obj[3]))

    def ability(self, digest: bytes) -> AbilityInfo:
        obj = self._resolve(digest, 5, "ability")
        return AbilityInfo(tuple(len(operation[0]) for operation in obj[2]))

    def operation_arity(self, digest: bytes, operation: int) -> int:
        info = self.ability(digest)
        if not isinstance(operation, int) or isinstance(operation, bool) or operation < 0:
            raise LookupError(operation)
        try:
            return info.parameter_counts[operation]
        except IndexError as exc:
            raise LookupError(operation) from exc

    def _resolve(self, digest: bytes, kind: int, label: str) -> list:
        if digest not in self._objects:
            raise DeclarationError(f"registry: missing {label} declaration {digest.hex()}")
        obj = self._objects[digest]
        if obj[0] != kind:
            raise DeclarationError(f"registry: hash {digest.hex()} is object kind {obj[0]}, not {label}")
        return obj
