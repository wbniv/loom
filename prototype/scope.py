"""Stateful de Bruijn scope validation for canonical Loom IR."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from transcode import parse_source

AbilityArityResolver = Callable[[bytes, int], int]


@dataclass(frozen=True)
class ScopeError(ValueError):
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _fail(path: str, message: str) -> None:
    raise ScopeError(path, message)


def _node(value, path: str, arity: int | None = None) -> list:
    if not isinstance(value, list) or not value:
        _fail(path, "expected a nonempty IR node")
    if arity is not None and len(value) != arity:
        _fail(path, f"expected node arity {arity}, got {len(value)}")
    return value


def check_type(
    ir,
    term_depth: int = 0,
    type_depth: int = 0,
    ability_arity: AbilityArityResolver | None = None,
    path: str = "type",
) -> None:
    node = _node(ir, path)
    tag = node[0]
    if tag == 0:
        _node(node, path, 2)
        return
    if tag == 1:
        _node(node, path, 3)
        for index, argument in enumerate(node[2]):
            check_type(argument, term_depth, type_depth, ability_arity, f"{path}.args[{index}]")
        return
    if tag == 2:
        _node(node, path, 4)
        check_type(node[1], term_depth, type_depth, ability_arity, f"{path}.domain")
        for index, effect in enumerate(node[2]):
            if isinstance(effect, bytes):
                continue
            effect_node = _node(effect, f"{path}.row[{index}]", 2)
            if effect_node[0] != 5:
                _fail(f"{path}.row[{index}]", "expected an ability hash or row type variable")
            _check_type_index(effect_node[1], type_depth, f"{path}.row[{index}]")
        check_type(node[3], term_depth, type_depth, ability_arity, f"{path}.codomain")
        return
    if tag == 3:
        _node(node, path, 3)
        check_type(node[1], term_depth, type_depth, ability_arity, f"{path}.base")
        check_term(node[2], term_depth + 1, type_depth, ability_arity, f"{path}.predicate")
        return
    if tag == 4:
        _node(node, path, 2)
        return
    if tag == 5:
        _node(node, path, 2)
        _check_type_index(node[1], type_depth, path)
        return
    if tag == 6:
        _node(node, path, 2)
        check_type(node[1], term_depth, type_depth + 1, ability_arity, f"{path}.body")
        return
    _fail(path, f"unknown type tag {tag!r}")


def _check_term_index(index, depth: int, path: str) -> None:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        _fail(path, f"invalid term index {index!r}")
    if index >= depth:
        _fail(path, f"term index {index} is out of scope at depth {depth}")


def _check_type_index(index, depth: int, path: str) -> None:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        _fail(path, f"invalid type index {index!r}")
    if index >= depth:
        _fail(path, f"type index {index} is out of scope at depth {depth}")


def check_term(
    ir,
    term_depth: int = 0,
    type_depth: int = 0,
    ability_arity: AbilityArityResolver | None = None,
    path: str = "term",
) -> None:
    node = _node(ir, path)
    tag = node[0]
    if tag == 0:
        _node(node, path, 2)
        _check_term_index(node[1], term_depth, path)
        return
    if tag in (1, 2):
        return
    if tag == 3:
        _node(node, path, 3)
        check_type(node[1], term_depth, type_depth, ability_arity, f"{path}.parameter-type")
        check_term(node[2], term_depth + 1, type_depth, ability_arity, f"{path}.body")
        return
    if tag == 4:
        _node(node, path, 3)
        check_term(node[1], term_depth, type_depth, ability_arity, f"{path}.function")
        check_term(node[2], term_depth, type_depth, ability_arity, f"{path}.argument")
        return
    if tag == 5:
        _node(node, path, 4)
        check_type(node[1], term_depth, type_depth, ability_arity, f"{path}.binding-type")
        check_term(node[2], term_depth, type_depth, ability_arity, f"{path}.bound")
        check_term(node[3], term_depth + 1, type_depth, ability_arity, f"{path}.body")
        return
    if tag in (6, 8):
        _node(node, path, 4)
        for index, argument in enumerate(node[3]):
            check_term(argument, term_depth, type_depth, ability_arity, f"{path}.args[{index}]")
        return
    if tag == 7:
        _node(node, path, 3)
        check_term(node[1], term_depth, type_depth, ability_arity, f"{path}.scrutinee")
        for index, arm in enumerate(node[2]):
            arm_path = f"{path}.arms[{index}]"
            arm_node = _node(arm, arm_path, 3)
            binder_count = arm_node[1]
            if not isinstance(binder_count, int) or isinstance(binder_count, bool) or binder_count < 0:
                _fail(arm_path, f"invalid binder count {binder_count!r}")
            check_term(arm_node[2], term_depth + binder_count, type_depth, ability_arity, f"{arm_path}.body")
        return
    if tag == 9:
        _node(node, path, 5)
        check_term(node[2], term_depth, type_depth, ability_arity, f"{path}.handled")
        if ability_arity is None:
            _fail(path, "handler scope requires an ability operation-arity resolver")
        for index, operation in enumerate(node[3]):
            op_path = f"{path}.operations[{index}]"
            op_node = _node(operation, op_path, 2)
            try:
                parameter_count = ability_arity(node[1], op_node[0])
            except (KeyError, IndexError, LookupError) as exc:
                _fail(op_path, f"cannot resolve ability operation {op_node[0]}")
            if not isinstance(parameter_count, int) or isinstance(parameter_count, bool) or parameter_count < 0:
                _fail(op_path, f"resolver returned invalid parameter count {parameter_count!r}")
            check_term(op_node[1], term_depth + parameter_count + 1, type_depth, ability_arity, f"{op_path}.body")
        check_term(node[4], term_depth + 1, type_depth, ability_arity, f"{path}.return")
        return
    if tag == 10:
        _node(node, path, 5)
        check_type(node[1], term_depth, type_depth, ability_arity, f"{path}.type")
        # The measure position selects a domain of the annotation (§2.5); this
        # layer checks only its shape, exactly as it checks a match arm's binder
        # count and leaves the field-count comparison to the typing layer.
        position = node[2]
        if not isinstance(position, int) or isinstance(position, bool) or position < 0:
            _fail(path, f"invalid measure position {position!r}")
        check_term(node[3], term_depth, type_depth, ability_arity, f"{path}.measure")
        check_term(node[4], term_depth + 1, type_depth, ability_arity, f"{path}.body")
        return
    if tag == 11:
        _node(node, path, 3)
        check_type(node[1], term_depth, type_depth, ability_arity, f"{path}.goal-type")
        for index, constraint in enumerate(node[2]):
            check_term(constraint, term_depth + 1, type_depth, ability_arity, f"{path}.constraints[{index}]")
        return
    if tag == 12:
        _node(node, path, 4)
        check_term(node[1], term_depth, type_depth, ability_arity, f"{path}.condition")
        check_term(node[2], term_depth, type_depth, ability_arity, f"{path}.then")
        check_term(node[3], term_depth, type_depth, ability_arity, f"{path}.else")
        return
    _fail(path, f"unknown term tag {tag!r}")


def _contains_forall(ir) -> bool:
    if not isinstance(ir, list) or not ir:
        return False
    if ir[0] == 6:
        return True
    return any(_contains_forall(child) for child in ir[1:] if isinstance(child, list))


def forall_prefix(ir, path: str = "definition.type") -> tuple[int, list]:
    """Split a definition type into its prenex `forall` count and quantified body.

    §2.3.1: a definition's term is checked at the type's leading `forall` depth,
    so that depth must be well defined — a `forall` surviving inside the body is
    rank-2 and is refused here rather than silently ignored.
    """
    depth, body = 0, ir
    while isinstance(body, list) and len(body) == 2 and body[0] == 6:
        depth += 1
        body = body[1]
    if _contains_forall(body):
        _fail(path, "a definition type's quantifiers must be prenex; rank-1 polymorphism only")
    return depth, body


def check_definition(ir, ability_arity: AbilityArityResolver | None = None) -> None:
    node = _node(ir, "definition", 3)
    if node[0] != 0:
        _fail("definition", f"expected object-kind tag 0, got {node[0]!r}")
    check_type(node[1], 0, 0, ability_arity, "definition.type")
    type_depth, _ = forall_prefix(node[1])
    check_term(node[2], 0, type_depth, ability_arity, "definition.term")


def validate_source(source: str, ability_arity: AbilityArityResolver | None = None):
    """Parse canonical source, validate scope, and return its IR."""
    ir = parse_source(source)
    check_definition(ir, ability_arity)
    return ir
