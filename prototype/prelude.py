"""Canonical Loom v0.1 builtin ability reference prelude."""

from __future__ import annotations

import copy
import hashlib
from types import MappingProxyType

from declarations import DeclarationRegistry, declaration_hash

_UNIT = [0, 0]
_I64 = [0, 2]
_TEXT = [0, 4]
_BYTES = [0, 5]

def _key(name: str) -> bytes:
    return hashlib.sha256(f"loom:v0.1:builtin:{name}".encode("ascii")).digest()


_DECLARATIONS = {
    "clock": [5, _key("clock"), [[[], _I64], [[_I64], _UNIT]]],
    "rand": [5, _key("rand"), [[[_I64], _BYTES], [[], _I64]]],
    "fsRead": [5, _key("fsRead"), [[[_TEXT], _BYTES]]],
    "fsWrite": [5, _key("fsWrite"), [[[_TEXT, _BYTES], _BYTES]]],
    "net": [5, _key("net"), [[[_BYTES], _BYTES]]],
    "spawn": [5, _key("spawn"), [[[_TEXT, _BYTES], _BYTES]]],
    "div": [5, _key("div"), []],
    "ffi": [5, _key("ffi"), [[[_TEXT, _BYTES], _BYTES]]],
}

OPERATION_NAMES = MappingProxyType({
    "clock": ("wallMillis", "sleepMillis"),
    "rand": ("bytes", "i64"),
    "fsRead": ("read",),
    "fsWrite": ("write",),
    "net": ("request",),
    "spawn": ("run",),
    "div": (),
    "ffi": ("call",),
})

HASHES = MappingProxyType({name: declaration_hash(obj) for name, obj in _DECLARATIONS.items()})
HASH_HEX = MappingProxyType({name: digest.hex() for name, digest in HASHES.items()})


def declaration(name: str) -> list:
    """Return an isolated copy of a canonical builtin declaration."""
    try:
        return copy.deepcopy(_DECLARATIONS[name])
    except KeyError as exc:
        raise KeyError(f"unknown builtin ability {name!r}") from exc


def registry() -> DeclarationRegistry:
    """Return a registry containing all canonical builtin declarations."""
    result = DeclarationRegistry()
    for name, digest in HASHES.items():
        result.add(_DECLARATIONS[name], expected_hash=digest)
    return result
