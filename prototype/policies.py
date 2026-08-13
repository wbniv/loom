"""Canonical namespace policy objects: validation, satisfaction, and
domination (SPEC.md §5.3.1-§5.3.2).

This module validates policy objects and compares them structurally. It does
not resolve `policy-ref` over a live store, does not perform binding
admission, and knows nothing about leases or amendment descent — there is no
store here, only the object shape and the two comparisons §5.3.1/§5.3.2
define on it: does an evidence entry satisfy a requirement (`E ⊒ R`, reused
from §6.1.2), and does one policy dominate another.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata

import cbor_canonical


class PolicyError(ValueError):
    pass


def _error(path: str, message: str) -> None:
    raise PolicyError(f"{path}: {message}")


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


def _bytes32(value, path: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        _error(path, "expected a 32-byte hash")
    return value


def _nfc_text(value, path: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        _error(path, "expected non-empty text" if not allow_empty else "expected text")
    if value != unicodedata.normalize("NFC", value):
        _error(path, "text must be NFC-normalized")
    return value


def _rational(value, path: str) -> list:
    """A canonical rational `[num, den]`: `den >= 1`, `0 <= num <= den`, `gcd(num, den) = 1`."""
    num, den = _array(value, path, 2)
    _uint(num, f"{path}[0]")
    _uint(den, f"{path}[1]")
    if den < 1:
        _error(path, "denominator must be at least 1")
    if not (0 <= num <= den):
        _error(path, "numerator must satisfy 0 <= num <= den")
    if math.gcd(num, den) != 1:
        _error(path, "not in lowest terms (gcd(num, den) != 1)")
    return [num, den]


def _rational_le(a: list, b: list) -> bool:
    """`a <= b` for canonical rationals, by exact cross-multiplication (SPEC.md §6.1.2)."""
    a_num, a_den = a
    b_num, b_den = b
    return a_num * b_den <= b_num * a_den


def _check_sorted_unique(items: list, path: str) -> None:
    if not items:
        _error(path, "must be non-empty when present")
    encoded = [cbor_canonical.encode(item) for item in items]
    if encoded != sorted(encoded):
        _error(path, "must be sorted bytewise by element encoding")
    if len(set(encoded)) != len(encoded):
        _error(path, "must not contain duplicate elements")


# --------------------------------------------------------------- obligations

#: The closed obligation-kind registry (SPEC.md §5.3.1). A kind outside it,
#: on either side — an obligation id or a policy selector/requirement — is
#: rejected rather than admitted at a degraded level (§6.1.1's discipline).
OBLIGATION_KINDS = {0: "ensures", 1: "terminates", 2: "exhaustive-match", 3: "property", 4: "extern"}
_KIND_TAG_BY_NAME = {name: tag for tag, name in OBLIGATION_KINDS.items()}


def decompose_obligation_id(obligation_id, path: str = "obligation-id") -> tuple[int, str | None]:
    """Split an obligation id into `(kind-tag, detail-or-None)` at its first `.`."""
    _nfc_text(obligation_id, path)
    head, sep, rest = obligation_id.partition(".")
    if head not in _KIND_TAG_BY_NAME:
        _error(path, f"unknown obligation kind {head!r}")
    return _KIND_TAG_BY_NAME[head], (rest if sep else None)


# ------------------------------------------------------------- lattice points

def validate_point(value, path: str) -> list:
    """A requirement or evidence-entry point in the assurance lattice: `[level]`
    for A0/A2/A3, or `[1, bound, confidence, generator]` for A1 (SPEC.md §5.3.1)."""
    arr = _array(value, path)
    if len(arr) == 1:
        level = _uint(arr[0], f"{path}[0]")
        if level not in (0, 2, 3):
            _error(f"{path}[0]", f"invalid level {level!r}; a bare level must be 0, 2, or 3")
        return arr
    if len(arr) == 4:
        if arr[0] != 1:
            _error(f"{path}[0]", "a four-element requirement must have level 1 (A1)")
        _rational(arr[1], f"{path}.bound")
        _rational(arr[2], f"{path}.confidence")
        _bytes32(arr[3], f"{path}.generator")
        return arr
    _error(path, f"expected a 1-element level or 4-element A1 point, got length {len(arr)}")


def at_least(evidence: list, requirement: list) -> bool:
    """`E ⊒ R` for two already-validated lattice points, under the order of
    SPEC.md §6.1.2 extended across levels: `A0 ⊏ A1 ⊏ A2 ⊑ A3`. A2/A3 evidence
    satisfies any A1 requirement; an A0 requirement is met by anything; two A1
    points compare by exact same-generator bound/confidence."""
    e_level, r_level = evidence[0], requirement[0]
    if e_level == 1 and r_level == 1:
        return _a1_at_least(evidence, requirement)
    return e_level >= r_level


def _a1_at_least(evidence: list, requirement: list) -> bool:
    _, e_bound, e_confidence, e_generator = evidence
    _, r_bound, r_confidence, r_generator = requirement
    if e_generator != r_generator:
        return False
    return _rational_le(e_bound, r_bound) and _rational_le(r_confidence, e_confidence)


def satisfies(evidence, requirement) -> bool:
    """Whether evidence entry `E` satisfies requirement `R`: `E ⊒ R` (SPEC.md §5.3.1,
    reusing §6.1.2's order). Validates both points before comparing."""
    validate_point(evidence, "evidence")
    validate_point(requirement, "requirement")
    return at_least(evidence, requirement)


# ---------------------------------------------------------------- selectors

def validate_selector(value, path: str) -> list:
    """A selector is `[]`, `[kind-tag]`, or `[kind-tag, detail]` — a prefix of
    an obligation id's `(kind, detail)` decomposition (SPEC.md §5.3.1)."""
    arr = _array(value, path)
    if len(arr) == 0:
        return arr
    tag = _uint(arr[0], f"{path}[0]")
    if tag not in OBLIGATION_KINDS:
        _error(f"{path}[0]", f"unknown obligation kind tag {tag!r}")
    if len(arr) == 1:
        return arr
    if len(arr) == 2:
        _nfc_text(arr[1], f"{path}[1]")
        return arr
    _error(path, f"selector must have length 0, 1, or 2, got {len(arr)}")


def selector_matches(selector: list, tag: int, detail: str | None) -> bool:
    if len(selector) == 0:
        return True
    if len(selector) == 1:
        return selector[0] == tag
    return selector[0] == tag and selector[1] == detail


def matching_rules(policy_map: dict, obligation_id) -> list:
    """Every rule of `policy-map`'s key 0 whose selector matches `obligation_id`,
    in canonical order. Matching is conjunctive — all matches apply, there is
    no precedence (SPEC.md §5.3.1)."""
    tag, detail = decompose_obligation_id(obligation_id)
    return [
        (selector, requirement)
        for selector, requirement in policy_map.get(0, [])
        if selector_matches(selector, tag, detail)
    ]


# ---------------------------------------------------------- structural checks

def _validate_rules(value, path: str) -> None:
    arr = _array(value, path)
    _check_sorted_unique(arr, path)
    for index, entry in enumerate(arr):
        selector, requirement = _array(entry, f"{path}[{index}]", 2)
        validate_selector(selector, f"{path}[{index}].selector")
        validate_point(requirement, f"{path}[{index}].requirement")


def _validate_require(value, path: str) -> None:
    arr = _array(value, path)
    _check_sorted_unique(arr, path)
    seen: set[str] = set()
    for index, entry in enumerate(arr):
        detail, statement = _array(entry, f"{path}[{index}]", 2)
        _nfc_text(detail, f"{path}[{index}][0]")
        _nfc_text(statement, f"{path}[{index}][1]")
        if detail in seen:
            _error(f"{path}[{index}]", f"duplicate detail {detail!r}")
        seen.add(detail)


def _validate_ability_caps(value, path: str) -> None:
    arr = _array(value, path)
    _check_sorted_unique(arr, path)
    seen: set[bytes] = set()
    for index, entry in enumerate(arr):
        ability, maximum = _array(entry, f"{path}[{index}]", 2)
        _bytes32(ability, f"{path}[{index}][0]")
        _uint(maximum, f"{path}[{index}][1]")
        if ability in seen:
            _error(f"{path}[{index}]", "duplicate ability hash")
        seen.add(ability)


def _validate_principal_set(value, path: str) -> None:
    arr = _array(value, path)
    _check_sorted_unique(arr, path)
    for index, principal in enumerate(arr):
        _bytes32(principal, f"{path}[{index}]")


#: Keys 0-9 of a policy-map (SPEC.md §5.3.1). A checker that does not
#: recognize a key rejects the policy object rather than admitting it with
#: that key ignored.
POLICY_KEYS = frozenset(range(10))


def validate_policy(obj, path: str = "policy") -> list:
    """Structurally validate a policy object `[6, policy-map]` and return it.

    Raises `PolicyError` on: a wrong object-kind tag, an unrecognized map key,
    an unsorted or duplicate-containing array-valued key, a non-canonical
    rational, a malformed selector or requirement, or an unrecognized
    obligation kind or assurance level. Absence of a key states no
    constraint, except key 8 `relax` (SPEC.md §5.3.1)."""
    node = _array(obj, path, 2)
    if node[0] != 6:
        _error(path, f"expected object-kind tag 6, got {node[0]!r}")
    policy_map = node[1]
    if not isinstance(policy_map, dict):
        _error(f"{path}.map", "expected a CBOR map")
    for key in policy_map:
        if not isinstance(key, int) or isinstance(key, bool) or key not in POLICY_KEYS:
            _error(f"{path}.map", f"unrecognized policy key {key!r}")
    if 0 in policy_map:
        _validate_rules(policy_map[0], f"{path}.rules")
    if 1 in policy_map:
        _validate_require(policy_map[1], f"{path}.require")
    if 2 in policy_map:
        _uint(policy_map[2], f"{path}.max-assumptions")
    if 3 in policy_map:
        _validate_ability_caps(policy_map[3], f"{path}.max-assumptions-by-ability")
    if 4 in policy_map:
        _validate_principal_set(policy_map[4], f"{path}.signers")
    if 5 in policy_map:
        _validate_principal_set(policy_map[5], f"{path}.writers")
    if 6 in policy_map:
        if _uint(policy_map[6], f"{path}.max-lease-millis") < 1:
            _error(f"{path}.max-lease-millis", "must be at least 1")
    if 7 in policy_map:
        _uint(policy_map[7], f"{path}.max-redraws")
    if 8 in policy_map:
        if policy_map[8] != 1:
            _error(f"{path}.relax", "the only admitted value is 1")
    if 9 in policy_map:
        _nfc_text(policy_map[9], f"{path}.statement", allow_empty=True)
    return node


def policy_bytes(obj) -> bytes:
    """Canonical CBOR encoding of a policy object, after structural validation."""
    return cbor_canonical.encode(validate_policy(obj))


def policy_hash(obj) -> bytes:
    return hashlib.sha256(policy_bytes(obj)).digest()


#: The base case of resolution (SPEC.md §5.3.2): the empty policy, three
#: bytes, preloaded in every store like the §2.4 prelude.
DEFAULT_POLICY = [6, {}]
DEFAULT_POLICY_HASH = bytes.fromhex("901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c")


# ---------------------------------------------------------------- domination

def _is_prefix(prefix: list, full: list) -> bool:
    return full[: len(prefix)] == prefix


def _dominates_rules(q: dict, p: dict) -> bool:
    q_rules = q.get(0, [])
    for selector, requirement in p.get(0, []):
        if not any(
            _is_prefix(q_selector, selector) and at_least(q_requirement, requirement)
            for q_selector, q_requirement in q_rules
        ):
            return False
    return True


def _dominates_require(q: dict, p: dict) -> bool:
    q_details = {detail for detail, _ in q.get(1, [])}
    p_details = {detail for detail, _ in p.get(1, [])}
    return p_details <= q_details


def _dominates_max(q: dict, p: dict, key: int) -> bool:
    """Wherever `P` states a maximum at `key`, `Q` states one no larger."""
    if key not in p:
        return True
    return key in q and q[key] <= p[key]


def _dominates_ability_caps(q: dict, p: dict) -> bool:
    q_caps = dict(q.get(3, []))
    for ability, maximum in p.get(3, []):
        if ability not in q_caps or q_caps[ability] > maximum:
            return False
    return True


def _dominates_principal_subset(q: dict, p: dict, key: int) -> bool:
    """Wherever `P` states a principal set at `key`, `Q` states a subset of it."""
    if key not in p:
        return True
    return key in q and set(q[key]) <= set(p[key])


def _dominates_relax(q: dict, p: dict) -> bool:
    """`Q` omits `relax` whenever `P` does — the one key whose absent value is
    the restrictive one."""
    if 8 not in p:
        return 8 not in q
    return True


def dominates(successor_obj, predecessor_obj) -> bool:
    """Whether policy `Q` (successor) dominates policy `P` (predecessor): at
    least as strict on every key (SPEC.md §5.3.2's table). Key 9 `statement`
    always dominates — prose is never load-bearing.

    The `rules` test is **sound but incomplete by design**: each of `P`'s
    rules must be dominated by a *single* rule of `Q` whose selector is a
    prefix of it. A `Q` that is at least as strict only through a conjunction
    of several of its rules is refused — an exact test would need a meet
    inside A1 across generators that §6.1.2 deliberately does not define, and
    the incompleteness refuses in the safe direction."""
    _, q = validate_policy(successor_obj, "successor")
    _, p = validate_policy(predecessor_obj, "predecessor")
    return (
        _dominates_rules(q, p)
        and _dominates_require(q, p)
        and _dominates_max(q, p, 2)
        and _dominates_ability_caps(q, p)
        and _dominates_principal_subset(q, p, 4)
        and _dominates_principal_subset(q, p, 5)
        and _dominates_max(q, p, 6)
        and _dominates_max(q, p, 7)
        and _dominates_relax(q, p)
    )
