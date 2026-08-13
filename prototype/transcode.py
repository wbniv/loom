"""Loom S-expression isomorph -> canonical CBOR bytes (SPEC.md SS8.4).

This is the deterministic transcoder SS8.4 requires: an agent under
constrained decoding emits the prior-rich S-expression surface defined by
loom.gbnf; this module maps that surface onto the exact node tag tables in
SPEC.md SS2 (terms, types, literals) and SS4.3 (def objects), then encodes
with cbor_canonical.encode. The mapping is total and deterministic, so
identity (SS4.3: sha256 of the def object's encoding) is unaffected by
which surface an agent used to emit the term.

No decoder exists for the *canonical bytes* (SPEC.md SS9: "no projection is
parseable") — but this reader is not a projection decoder, it is the one
tool explicitly licensed by SS8.4 to exist: the isomorph transcoder.
"""

from __future__ import annotations

import hashlib
import math
import struct

import cbor_canonical
import sexpr

# --- literal kinds (SPEC.md SS2.2) ------------------------------------------
LIT_KIND = {"unit": 0, "bool": 1, "i64": 2, "f64": 3, "text": 4, "bytes": 5}

# --- base type codes (SPEC.md SS2.2) ----------------------------------------
BASE_CODE = {"Unit": 0, "Bool": 1, "I64": 2, "F64": 3, "Text": 4, "Bytes": 5}

# --- term node tags (SPEC.md SS2.1) -----------------------------------------
TERM_TAG = {
    "var": 0, "ref": 1, "lit": 2, "lam": 3, "app": 4, "let": 5,
    "con": 6, "match": 7, "perform": 8, "handle": 9, "fix": 10, "hole": 11,
}

# --- type node tags (SPEC.md SS2.3) -----------------------------------------
TYPE_TAG = {
    "base": 0, "data": 1, "fn": 2, "refine": 3, "cap": 4, "tyvar": 5, "forall": 6,
}


def _hash_bytes(tok: str) -> bytes:
    if not (isinstance(tok, str) and tok.startswith("0x")):
        raise ValueError(f"expected 0x-prefixed hash/byte literal, got {tok!r}")
    return bytes.fromhex(tok[2:])


def _f64_bytes(x: float) -> bytes:
    if math.isnan(x):
        return struct.pack(">d", math.nan)  # canonical quiet NaN, 0x7ff8000000000000
    return struct.pack(">d", x)


def type_to_ir(form):
    if isinstance(form, str) and form in BASE_CODE:
        return [TYPE_TAG["base"], BASE_CODE[form]]
    head, *rest = form
    tag = TYPE_TAG[head]
    if head == "base":
        return [tag, BASE_CODE[rest[0]] if isinstance(rest[0], str) else int(rest[0])]
    if head == "data":
        h, args = rest
        return [tag, _hash_bytes(h), [type_to_ir(a) for a in args]]
    if head == "fn":
        dom, row, cod = rest
        row_hashes = sorted((_hash_bytes(h) for h in row))
        return [tag, type_to_ir(dom), row_hashes, type_to_ir(cod)]
    if head == "refine":
        t, phi = rest
        return [tag, type_to_ir(t), term_to_ir(phi)]
    if head == "cap":
        return [tag, _hash_bytes(rest[0])]
    if head == "tyvar":
        return [tag, int(rest[0])]
    if head == "forall":
        return [tag, type_to_ir(rest[0])]
    raise ValueError(f"unknown type form: {head}")


def term_to_ir(form):
    head, *rest = form
    tag = TERM_TAG[head]
    if head == "var":
        return [tag, int(rest[0])]
    if head == "ref":
        return [tag, _hash_bytes(rest[0])]
    if head == "lit":
        kind_name = rest[0]
        kind = LIT_KIND[kind_name]
        if kind_name == "unit":
            return [tag, kind]  # SS2.2 clarification: unit omits `v` (see prototype/README.md)
        v = rest[1]
        if kind_name == "bool":
            return [tag, kind, v == "true"]
        if kind_name == "i64":
            return [tag, kind, int(v)]
        if kind_name == "f64":
            return [tag, kind, _f64_bytes(float(v))]
        if kind_name == "text":
            assert isinstance(v, tuple) and v[0] == "str"
            return [tag, kind, v[1]]
        if kind_name == "bytes":
            return [tag, kind, _hash_bytes(v)]
        raise ValueError(f"unknown literal kind: {kind_name}")
    if head == "lam":
        t, body = rest
        return [tag, type_to_ir(t), term_to_ir(body)]
    if head == "app":
        f, a = rest
        return [tag, term_to_ir(f), term_to_ir(a)]
    if head == "let":
        t, bound, body = rest
        return [tag, type_to_ir(t), term_to_ir(bound), term_to_ir(body)]
    if head == "con":
        d, idx, args = rest
        return [tag, _hash_bytes(d), int(idx), [term_to_ir(a) for a in args]]
    if head == "match":
        scrut, arms = rest
        arm_irs = [[int(i), int(n), term_to_ir(b)] for i, n, b in arms]
        return [tag, term_to_ir(scrut), arm_irs]
    if head == "perform":
        a, idx, args = rest
        return [tag, _hash_bytes(a), int(idx), [term_to_ir(x) for x in args]]
    if head == "handle":
        a, t, ops, ret = rest
        op_irs = [[int(i), term_to_ir(b)] for i, b in ops]
        return [tag, _hash_bytes(a), term_to_ir(t), op_irs, term_to_ir(ret)]
    if head == "fix":
        t, measure, body = rest
        return [tag, type_to_ir(t), term_to_ir(measure), term_to_ir(body)]
    if head == "hole":
        t, constraints = rest
        return [tag, type_to_ir(t), [term_to_ir(c) for c in constraints]]
    raise ValueError(f"unknown term form: {head}")


def def_to_ir(form):
    """(def <type> <term>) -> [0, type_ir, term_ir]  (SS4.3, object kind 0)."""
    head, t, term = form
    assert head == "def"
    return [0, type_to_ir(t), term_to_ir(term)]


def def_object_bytes(form) -> bytes:
    return cbor_canonical.encode(def_to_ir(form))


def identity(form) -> str:
    """SS4.3: identity is sha256 over the def object's canonical encoding."""
    return hashlib.sha256(def_object_bytes(form)).hexdigest()


def transcode_source(src: str):
    """Parse one def form from `src` and return (ir, bytes, hash)."""
    forms = sexpr.parse_all(src)
    assert len(forms) == 1, "expected exactly one top-level (def ...) form"
    form = forms[0]
    ir = def_to_ir(form)
    b = cbor_canonical.encode(ir)
    return ir, b, hashlib.sha256(b).hexdigest()


if __name__ == "__main__":
    import sys

    path = sys.argv[1]
    with open(path) as f:
        src = f.read()
    ir, b, h = transcode_source(src)
    print(f"ir     = {ir}")
    print(f"bytes  = {b.hex()}  ({len(b)} bytes)")
    print(f"hash   = #{h}")
