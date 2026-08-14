"""Canonical, lossless JSON encoding for harness records.

Two properties matter and nothing else does:

*Deterministic* — the same Python value always produces the same bytes, on any
interpreter run, so two exports of the same tree are byte-identical. Object keys
are sorted, dictionaries with non-string keys are emitted as sorted pair lists,
and no float ever reaches the JSON encoder as a float.

*Lossless* — the prototype's IR is nested lists of `int`, `bool`, `str`, and
`bytes`. JSON has no `bytes`, and conflates `bool` with `int` only in Python's
direction, so `bytes` and `float` are carried in tagged objects a consumer can
decode unambiguously. Anything the harness cannot represent becomes an explicit
`$opaque` marker rather than a silently lossy string, because a case whose input
is only partly recorded is a case a consumer cannot replay.
"""

from __future__ import annotations

import collections.abc
import hashlib
import json
import struct

#: Tag keys. A tagged object always has exactly one key, and that key always
#: starts with `$`, which no Loom IR or policy map key ever does.
BYTES_TAG = "$bytes"
FLOAT_TAG = "$f64"
MAP_TAG = "$map"
OPAQUE_TAG = "$opaque"


def encode(value):
    """Return a JSON-representable, losslessly tagged form of `value`."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return {FLOAT_TAG: struct.pack(">d", value).hex()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {BYTES_TAG: bytes(value).hex()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((encode(item) for item in value), key=canonical)
    # `Mapping`, not `dict`: the corpus ships its SMT signature and
    # interpretation tables as `MappingProxyType`, and a resolver table that
    # silently became `$opaque` would be a case no consumer could replay.
    if isinstance(value, collections.abc.Mapping):
        pairs = [[encode(key), encode(item)] for key, item in value.items()]
        pairs.sort(key=canonical)
        return {MAP_TAG: pairs}
    return {OPAQUE_TAG: type(value).__name__}


def canonical(value) -> str:
    """Canonical JSON text of an already-`encode`d value.

    Sorted keys, no insignificant whitespace, ASCII-escaped — so the text is
    independent of locale, of dict insertion order, and of the terminal it is
    written to.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def digest(value) -> str:
    """SHA-256 of the canonical JSON text of an already-`encode`d value."""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def contains_opaque(value) -> bool:
    """True when any part of an encoded value was not representable."""
    if isinstance(value, dict):
        if OPAQUE_TAG in value:
            return True
        return any(contains_opaque(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_opaque(item) for item in value)
    return False
