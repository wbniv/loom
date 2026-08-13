"""Canonical Loom S-expression <-> IR and canonical-CBOR transcoder."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import unicodedata

import cbor_canonical
import sexpr

LIT_KIND = {"unit": 0, "bool": 1, "i64": 2, "f64": 3, "text": 4, "bytes": 5}
BASE_CODE = {"Unit": 0, "Bool": 1, "I64": 2, "F64": 3, "Text": 4, "Bytes": 5}
BASE_NAME = {value: key for key, value in BASE_CODE.items()}
TERM_TAG = {
    "var": 0, "ref": 1, "lit": 2, "lam": 3, "app": 4, "let": 5,
    "con": 6, "match": 7, "perform": 8, "handle": 9, "fix": 10, "hole": 11,
    "if": 12,
}
TYPE_TAG = {"base": 0, "data": 1, "fn": 2, "refine": 3, "cap": 4, "tyvar": 5, "forall": 6}


class SurfaceError(ValueError):
    pass


def _list(form, context: str, arity: int | None = None) -> list:
    if not isinstance(form, list):
        raise SurfaceError(f"{context}: expected a list, got {form!r}")
    if arity is not None and len(form) != arity:
        raise SurfaceError(f"{context}: expected {arity} fields, got {len(form)}")
    return form


def _head(form, context: str, arity: int | None = None) -> tuple[str, list]:
    values = _list(form, context, arity)
    if not values or not isinstance(values[0], str):
        raise SurfaceError(f"{context}: expected a keyword")
    return values[0], values[1:]


def _canonical_uint(tok, context: str) -> int:
    if not isinstance(tok, str) or not (tok == "0" or (tok[0] in "123456789" and tok.isascii() and tok.isdigit())):
        raise SurfaceError(f"{context}: expected a canonical nonnegative integer")
    return int(tok)


def _canonical_i64(tok) -> int:
    if not isinstance(tok, str):
        raise SurfaceError("i64: expected an integer atom")
    digits = tok[1:] if tok.startswith("-") else tok
    if not (digits == "0" or (digits and digits[0] in "123456789" and digits.isascii() and digits.isdigit())):
        raise SurfaceError("i64: noncanonical integer spelling")
    if tok == "-0":
        raise SurfaceError("i64: negative zero is not canonical")
    value = int(tok)
    if not -(2**63) <= value < 2**63:
        raise SurfaceError("i64: value outside signed 64-bit range")
    return value


def _hash_bytes(tok) -> bytes:
    if not isinstance(tok, str) or len(tok) != 66 or not tok.startswith("0x"):
        raise SurfaceError("hash: expected 0x followed by exactly 64 lowercase hex digits")
    digits = tok[2:]
    if any(ch not in "0123456789abcdef" for ch in digits):
        raise SurfaceError("hash: expected lowercase hexadecimal")
    return bytes.fromhex(digits)


def _bytes_literal(tok) -> bytes:
    if not isinstance(tok, str) or not tok.startswith("0x"):
        raise SurfaceError("bytes: expected a 0x-prefixed lowercase hex atom")
    digits = tok[2:]
    if len(digits) % 2 or any(ch not in "0123456789abcdef" for ch in digits):
        raise SurfaceError("bytes: expected an even number of lowercase hex digits")
    return bytes.fromhex(digits)


def _f64_literal(tok) -> bytes:
    if not isinstance(tok, str) or len(tok) != 18 or not tok.startswith("0x"):
        raise SurfaceError("f64: expected exactly 8 bytes as 0x plus 16 lowercase hex digits")
    raw = _bytes_literal(tok)
    value = struct.unpack(">d", raw)[0]
    if math.isnan(value) and raw != bytes.fromhex("7ff8000000000000"):
        raise SurfaceError("f64: noncanonical NaN payload")
    return raw


def type_to_ir(form):
    if isinstance(form, str) and form in BASE_CODE:
        return [TYPE_TAG["base"], BASE_CODE[form]]
    head, rest = _head(form, "type")
    if head == "data":
        if len(rest) != 2:
            raise SurfaceError("data: expected hash and type list")
        args = _list(rest[1], "data arguments")
        return [1, _hash_bytes(rest[0]), [type_to_ir(arg) for arg in args]]
    if head == "fn":
        if len(rest) != 3:
            raise SurfaceError("fn: expected domain, row, and codomain")
        row = _list(rest[1], "effect row")
        hashes: list[bytes] = []
        row_var = None
        for pos, item in enumerate(row):
            if isinstance(item, list):
                if pos != len(row) - 1:
                    raise SurfaceError("effect row: row variable must be last")
                h, r = _head(item, "row variable", 2)
                if h != "tyvar":
                    raise SurfaceError("effect row: expected ability hash or tyvar")
                row_var = [5, _canonical_uint(r[0], "row variable")]
            else:
                hashes.append(_hash_bytes(item))
        if hashes != sorted(hashes) or len(set(hashes)) != len(hashes):
            raise SurfaceError("effect row: hashes must be unique and sorted bytewise")
        ir_row = list(hashes)
        if row_var is not None:
            ir_row.append(row_var)
        return [2, type_to_ir(rest[0]), ir_row, type_to_ir(rest[2])]
    if head == "refine" and len(rest) == 2:
        return [3, type_to_ir(rest[0]), term_to_ir(rest[1])]
    if head == "cap" and len(rest) == 1:
        return [4, _hash_bytes(rest[0])]
    if head == "tyvar" and len(rest) == 1:
        return [5, _canonical_uint(rest[0], "type variable")]
    if head == "forall" and len(rest) == 1:
        return [6, type_to_ir(rest[0])]
    raise SurfaceError(f"unknown or malformed type form: {head}")


def term_to_ir(form):
    head, rest = _head(form, "term")
    if head not in TERM_TAG:
        raise SurfaceError(f"unknown term form: {head}")
    tag = TERM_TAG[head]
    if head == "var" and len(rest) == 1:
        return [tag, _canonical_uint(rest[0], "variable")]
    if head == "ref" and len(rest) == 1:
        return [tag, _hash_bytes(rest[0])]
    if head == "lit":
        if not rest or rest[0] not in LIT_KIND:
            raise SurfaceError("lit: unknown literal kind")
        kind_name = rest[0]
        kind = LIT_KIND[kind_name]
        if kind_name == "unit" and len(rest) == 1:
            return [tag, kind]
        if len(rest) != 2:
            raise SurfaceError(f"lit {kind_name}: wrong arity")
        value = rest[1]
        if kind_name == "bool":
            if value not in ("true", "false"):
                raise SurfaceError("bool: expected true or false")
            return [tag, kind, value == "true"]
        if kind_name == "i64":
            return [tag, kind, _canonical_i64(value)]
        if kind_name == "f64":
            return [tag, kind, _f64_literal(value)]
        if kind_name == "text":
            if not (isinstance(value, tuple) and len(value) == 2 and value[0] == "str"):
                raise SurfaceError("text: expected a JSON string")
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value[1]):
                raise SurfaceError("text: Unicode surrogate code points are not valid scalar values")
            if value[1] != unicodedata.normalize("NFC", value[1]):
                raise SurfaceError("text: value must be NFC-normalized")
            return [tag, kind, value[1]]
        if kind_name == "bytes":
            return [tag, kind, _bytes_literal(value)]
    if head == "lam" and len(rest) == 2:
        return [tag, type_to_ir(rest[0]), term_to_ir(rest[1])]
    if head == "app" and len(rest) == 2:
        return [tag, term_to_ir(rest[0]), term_to_ir(rest[1])]
    if head == "let" and len(rest) == 3:
        return [tag, type_to_ir(rest[0]), term_to_ir(rest[1]), term_to_ir(rest[2])]
    if head in ("con", "perform") and len(rest) == 3:
        args = _list(rest[2], f"{head} arguments")
        return [tag, _hash_bytes(rest[0]), _canonical_uint(rest[1], f"{head} index"), [term_to_ir(a) for a in args]]
    if head == "match" and len(rest) == 2:
        arms = _list(rest[1], "match arms")
        arm_irs = []
        for arm in arms:
            values = _list(arm, "match arm", 3)
            arm_irs.append([_canonical_uint(values[0], "constructor index"), _canonical_uint(values[1], "binder count"), term_to_ir(values[2])])
        return [tag, term_to_ir(rest[0]), arm_irs]
    if head == "handle" and len(rest) == 4:
        ops = _list(rest[2], "handler operations")
        op_irs = []
        for op in ops:
            values = _list(op, "handler operation", 2)
            op_irs.append([_canonical_uint(values[0], "operation index"), term_to_ir(values[1])])
        return [tag, _hash_bytes(rest[0]), term_to_ir(rest[1]), op_irs, term_to_ir(rest[3])]
    if head == "fix" and len(rest) == 4:
        # The measure position precedes the measure: §8.1 emits a definition in
        # pre-order, so the field that fixes the measure's goal type has to be
        # decoded before the measure for §8.2's pruning to use it.
        return [tag, type_to_ir(rest[0]), _canonical_uint(rest[1], "fix measure position"), term_to_ir(rest[2]), term_to_ir(rest[3])]
    if head == "hole" and len(rest) == 2:
        constraints = _list(rest[1], "hole constraints")
        return [tag, type_to_ir(rest[0]), [term_to_ir(c) for c in constraints]]
    if head == "if" and len(rest) == 3:
        return [tag, term_to_ir(rest[0]), term_to_ir(rest[1]), term_to_ir(rest[2])]
    raise SurfaceError(f"malformed {head} term")


def def_to_ir(form):
    head, rest = _head(form, "definition")
    if head != "def" or len(rest) != 2:
        raise SurfaceError("definition: expected (def <type> <term>)")
    return [0, type_to_ir(rest[0]), term_to_ir(rest[1])]


def _hash_surface(value: bytes) -> str:
    if not isinstance(value, bytes) or len(value) != 32:
        raise SurfaceError("IR hash must contain exactly 32 bytes")
    return "0x" + value.hex()


def _join(head: str, fields: list[str]) -> str:
    return "(" + " ".join([head, *fields]) + ")"


def type_to_surface(ir) -> str:
    values = _list(ir, "type IR")
    if not values:
        raise SurfaceError("type IR: empty node")
    tag = values[0]
    if tag == 0 and len(values) == 2 and values[1] in BASE_NAME:
        return BASE_NAME[values[1]]
    if tag == 1 and len(values) == 3:
        return _join("data", [_hash_surface(values[1]), _join_list(type_to_surface(x) for x in values[2])])
    if tag == 2 and len(values) == 4:
        row_fields = []
        for pos, item in enumerate(values[2]):
            if isinstance(item, bytes):
                row_fields.append(_hash_surface(item))
            elif pos == len(values[2]) - 1 and item[0] == 5:
                row_fields.append(_join("tyvar", [str(item[1])]))
            else:
                raise SurfaceError("type IR: malformed effect row")
        return _join("fn", [type_to_surface(values[1]), _join_list(row_fields), type_to_surface(values[3])])
    if tag == 3 and len(values) == 3:
        return _join("refine", [type_to_surface(values[1]), term_to_surface(values[2])])
    if tag == 4 and len(values) == 2:
        return _join("cap", [_hash_surface(values[1])])
    if tag == 5 and len(values) == 2:
        return _join("tyvar", [str(values[1])])
    if tag == 6 and len(values) == 2:
        return _join("forall", [type_to_surface(values[1])])
    raise SurfaceError(f"unknown or malformed type IR tag: {tag!r}")


def _join_list(values) -> str:
    return "(" + " ".join(values) + ")"


def term_to_surface(ir) -> str:
    values = _list(ir, "term IR")
    if not values:
        raise SurfaceError("term IR: empty node")
    tag = values[0]
    if tag == 0 and len(values) == 2:
        return _join("var", [str(values[1])])
    if tag == 1 and len(values) == 2:
        return _join("ref", [_hash_surface(values[1])])
    if tag == 2:
        kinds = {value: key for key, value in LIT_KIND.items()}
        if len(values) == 2 and values[1] == 0:
            return "(lit unit)"
        if len(values) != 3 or values[1] not in kinds:
            raise SurfaceError("term IR: malformed literal")
        kind, value = kinds[values[1]], values[2]
        if kind == "bool": rendered = "true" if value is True else "false" if value is False else None
        elif kind == "i64": rendered = str(value)
        elif kind == "f64": rendered = "0x" + value.hex()
        elif kind == "text": rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        elif kind == "bytes": rendered = "0x" + value.hex()
        else: rendered = None
        if rendered is None:
            raise SurfaceError("term IR: malformed literal value")
        return _join("lit", [kind, rendered])
    if tag == 3 and len(values) == 3:
        return _join("lam", [type_to_surface(values[1]), term_to_surface(values[2])])
    if tag == 4 and len(values) == 3:
        return _join("app", [term_to_surface(values[1]), term_to_surface(values[2])])
    if tag == 5 and len(values) == 4:
        return _join("let", [type_to_surface(values[1]), term_to_surface(values[2]), term_to_surface(values[3])])
    if tag in (6, 8) and len(values) == 4:
        head = "con" if tag == 6 else "perform"
        return _join(head, [_hash_surface(values[1]), str(values[2]), _join_list(term_to_surface(x) for x in values[3])])
    if tag == 7 and len(values) == 3:
        arms = _join_list(_join_list([str(i), str(n), term_to_surface(body)]) for i, n, body in values[2])
        return _join("match", [term_to_surface(values[1]), arms])
    if tag == 9 and len(values) == 5:
        ops = _join_list(_join_list([str(i), term_to_surface(body)]) for i, body in values[3])
        return _join("handle", [_hash_surface(values[1]), term_to_surface(values[2]), ops, term_to_surface(values[4])])
    if tag == 10 and len(values) == 5:
        if not isinstance(values[2], int) or isinstance(values[2], bool) or values[2] < 0:
            raise SurfaceError("term IR: fix measure position must be a nonnegative integer")
        return _join("fix", [type_to_surface(values[1]), str(values[2]), term_to_surface(values[3]), term_to_surface(values[4])])
    if tag == 11 and len(values) == 3:
        return _join("hole", [type_to_surface(values[1]), _join_list(term_to_surface(x) for x in values[2])])
    if tag == 12 and len(values) == 4:
        return _join("if", [term_to_surface(values[1]), term_to_surface(values[2]), term_to_surface(values[3])])
    raise SurfaceError(f"unknown or malformed term IR tag: {tag!r}")


def def_to_surface(ir) -> str:
    values = _list(ir, "definition IR", 3)
    if values[0] != 0:
        raise SurfaceError("definition IR: expected object-kind tag 0")
    return _join("def", [type_to_surface(values[1]), term_to_surface(values[2])])


def parse_source(src: str):
    forms = sexpr.parse_all(src)
    if len(forms) != 1:
        raise SurfaceError(f"expected exactly one top-level definition, got {len(forms)}")
    ir = def_to_ir(forms[0])
    canonical = def_to_surface(ir)
    if src not in (canonical, canonical + "\n"):
        raise SurfaceError(f"noncanonical surface; expected: {canonical}")
    return ir


def def_object_bytes(form) -> bytes:
    return cbor_canonical.encode(def_to_ir(form))


def identity(form) -> str:
    return hashlib.sha256(def_object_bytes(form)).hexdigest()


def transcode_source(src: str):
    ir = parse_source(src)
    encoded = cbor_canonical.encode(ir)
    return ir, encoded, hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: transcode.py PATH")
    with open(sys.argv[1], encoding="utf-8") as source_file:
        source = source_file.read()
    parsed_ir, encoded_bytes, definition_hash = transcode_source(source)
    print(f"ir     = {parsed_ir}")
    print(f"bytes  = {encoded_bytes.hex()}  ({len(encoded_bytes)} bytes)")
    print(f"hash   = #{definition_hash}")
