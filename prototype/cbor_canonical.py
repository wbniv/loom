"""Canonical CBOR encoder — the deterministic subset SPEC.md SS4.2 requires.

Implements only RFC 8949 SS4.2.1's deterministic core: definite lengths,
minimal-length integers, no tags, no indefinite forms, map keys sorted
bytewise. No decoder is provided — Loom identity is a write-only hash over
an encoder's output, so only the encoder direction needs to be canonical.

Python-type mapping (unambiguous, no wrapper types needed):
    int   -> CBOR unsigned/negative integer (major type 0 / 1)
    bytes -> CBOR byte string               (major type 2)
    str   -> CBOR text string, NFC-normalized (major type 3)
    list  -> CBOR array, definite length      (major type 4)
    dict  -> CBOR map, definite length, keys sorted bytewise (major type 5)
    bool  -> CBOR simple value true/false     (major type 7)

`dict` support exists for meta/binding/evidence objects (SPEC.md SS5) even
though the term/type grammar itself (SS2) never nests a map.
"""

from __future__ import annotations

import unicodedata


def _encode_head(major: int, n: int) -> bytes:
    """Major type + argument, minimal-length per RFC 8949 SS3.1."""
    if n < 24:
        return bytes([(major << 5) | n])
    if n < 256:
        return bytes([(major << 5) | 24, n])
    if n < 65536:
        return bytes([(major << 5) | 25]) + n.to_bytes(2, "big")
    if n < 2**32:
        return bytes([(major << 5) | 26]) + n.to_bytes(4, "big")
    if n < 2**64:
        return bytes([(major << 5) | 27]) + n.to_bytes(8, "big")
    raise ValueError(f"argument {n} exceeds CBOR 64-bit range")


def encode(value) -> bytes:
    if isinstance(value, bool):  # bool is an int subclass — check first
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        if value >= 0:
            return _encode_head(0, value)
        return _encode_head(1, -value - 1)
    if isinstance(value, bytes):
        return _encode_head(2, len(value)) + value
    if isinstance(value, str):
        b = unicodedata.normalize("NFC", value).encode("utf-8")
        return _encode_head(3, len(b)) + b
    if isinstance(value, (list, tuple)):
        out = _encode_head(4, len(value))
        for item in value:
            out += encode(item)
        return out
    if isinstance(value, dict):
        # RFC 8949 core deterministic order: shorter encoded keys first,
        # then bytewise lexical order among keys of equal encoded length.
        keys_sorted = sorted(value.keys(), key=lambda k: (len(encode(k)), encode(k)))
        out = _encode_head(5, len(value))
        for k in keys_sorted:
            out += encode(k) + encode(value[k])
        return out
    raise TypeError(f"no canonical CBOR encoding for {type(value)}")
