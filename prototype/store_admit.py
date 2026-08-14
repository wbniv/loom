"""The admission oracle: validate an object, emit its bytes and its sidecar.

`docs/plans/2026-08-14-store-v0.md` R3 draws the Python/Rust seam here. The
Rust store owns exactly one invariant — ``SHA-256(bytes) == name`` — and knows
nothing about what the bytes mean. Everything semantic (which kind of object
this is, its type surface, what it depends on, where it came from, which
contract versions accepted it) is produced *here*, by the layers that already
decide it, and travels to the store as a JSON sidecar.

This module therefore **consumes** the validator modules and changes none of
them: no contract in `CONTRACTS.md` moves because this file exists. It is a
projection of `experiment.evaluate.run_funnel`'s layer order onto a file
format, plus the pinned corpus's declaration set.

Two output artifacts per object, written into a caller-supplied directory:

``<stem>.bin``   the canonical object bytes (§4.1 CBOR for definitions,
                 §5.1 CBOR for declarations) — opaque to the store.
``<stem>.json``  the sidecar (schema below), written as deterministic bytes so
                 that re-seeding a store from the pinned corpus reproduces it
                 byte for byte. Nothing in it is a timestamp, deliberately.

Sidecar schema, version 1
-------------------------

===================  ======================================================
``schema``           ``1``.
``hash``             64 lowercase hex — SHA-256 of the object bytes. The
                     store re-derives this and refuses a mismatch.
``kind``             ``definition`` | ``data`` | ``ability`` | ``extern``.
``name``             §5.2 metadata name (``corpus/list/append``, ``List``,
                     ``clock``, ``I64.add``), or ``null`` when the admitter
                     has no name for the object.
``type_surface``     Canonical surface of the type a ``ref`` to this hash
                     has, or ``null`` for kinds that have none (data and
                     ability declarations are not referenceable as terms).
                     This is the column the decode-hot-path ``type`` lookup
                     reads; conclusion 3 is why it is precomputed.
``deps``             Sorted, deduplicated hashes this object references from
                     a *type or term* position. Identity slots (a data or
                     ability declaration's nominal key, an extern's pinned
                     artifact) are excluded: they are not store objects.
``surface``          Definitions only — the canonical S-expression text.
                     This is what a prompt shows, and the round trip
                     ``sha256(cbor(parse(surface))) == hash`` is checked on
                     the way in and on the way out.
``object``           Declarations only — the object IR in the JSON mirror
                     below, because §5.1 declarations have no surface
                     syntax. Round-tripped and hash-checked identically.
``spec``             Definitions only — the §5.2 spec text, ``null`` when
                     the admitter has none.
``sequence``         The admitter's presentation order. Not part of
                     identity; it exists so a store can reproduce the
                     dependency order the corpus manifest is written in.
``provenance``       ``origin`` (``transpiled`` | ``declared`` |
                     ``generated``), free-text ``source``, ``admitter``, and
                     for externs the pinned ``artifact`` and ``abi``.
``validation``       ``layers`` actually run, in order; ``contracts``, the
                     contract version of each at admission time (R3's "a
                     future MAJOR bump can find every object that predates
                     it" reads this field); and ``obligations``, how many
                     §3.3 subsumption verification conditions the checker
                     admitted on the way through.
===================  ======================================================

JSON mirror of an object IR
---------------------------

The IR is JSON-shaped already except for byte strings, which become
``{"b16": "<hex>"}``. Encoding and decoding are inverse, and both directions
are checked against the canonical hash rather than trusted — a mirror that
silently disagreed with the CBOR encoder would be the one defect this format
could introduce, so it is never possible to land one.

Commands
--------

``contracts``   print the contract-version map (one JSON line).
``corpus``      emit the whole pinned corpus — 8 abilities, 4 data
                declarations, 9 externs, 26 definitions — in seeding order.
``emit``        emit one definition source file, validated against a
                resolver export (``--resolver``) or, absent one, the pinned
                corpus registry.

Every command prints exactly one line of JSON on stdout. A refusal prints
``{"error": ...}`` and exits 5, so the store can pass the layer's own error
class straight through instead of inventing one.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

import cbor_canonical
import contracts
import corpus_registry
import declarations
import prelude
import references
import scope
import transcode
import typecheck

SCHEMA = 1

KIND_DEFINITION = "definition"
KIND_DATA = "data"
KIND_ABILITY = "ability"
KIND_EXTERN = "extern"

#: Object-kind tag (§4.1/§5.1, position 0 of every canonical object) to the
#: store's kind string. The store never reads the tag — it reads this string
#: out of the sidecar — but keeping the mapping in one place is what makes the
#: two agree.
KIND_BY_TAG = {0: KIND_DEFINITION, 4: KIND_DATA, 5: KIND_ABILITY, 7: KIND_EXTERN}

#: Which layers a definition passes through, in the order `run_funnel` runs
#: them. Recorded per object because a later store will admit objects that
#: reached different depths.
DEFINITION_LAYERS = ("parser", "scope", "references", "typecheck")
DECLARATION_LAYERS = ("declarations",)

ADMITTER = "prototype.store_admit/1"

#: Exit code for "the oracle refused this object". The store maps it to its
#: own `refused` class; see `store/src/error.rs`.
EXIT_REFUSED = 5


class AdmissionRefused(Exception):
    """A validator said no. Carries the layer and the layer's own error class."""

    def __init__(self, layer: str, error: Exception):
        super().__init__(str(error))
        self.layer = layer
        self.error_class = type(error).__name__
        self.message = str(error)


# ---------------------------------------------------------------------------
# The JSON mirror of an object IR
# ---------------------------------------------------------------------------


def ir_to_json(node):
    """Mirror an object IR into JSON. Byte strings become ``{"b16": hex}``."""
    if isinstance(node, bytes):
        return {"b16": node.hex()}
    if isinstance(node, bool) or isinstance(node, int) or isinstance(node, str):
        return node
    if isinstance(node, list):
        return [ir_to_json(item) for item in node]
    raise TypeError(f"cannot mirror {type(node).__name__} into the sidecar")


def json_to_ir(node):
    """The inverse of `ir_to_json`, strict about the one dict shape it knows."""
    if isinstance(node, dict):
        if set(node) != {"b16"}:
            raise ValueError(f"sidecar object: unknown mirrored form {sorted(node)}")
        return bytes.fromhex(node["b16"])
    if isinstance(node, list):
        return [json_to_ir(item) for item in node]
    if isinstance(node, bool) or isinstance(node, int) or isinstance(node, str):
        return node
    raise TypeError(f"sidecar object: cannot decode {type(node).__name__}")


def _hashes_in(node, found: set) -> set:
    """Every 32-byte string reachable from `node`, which is every hash edge."""
    if isinstance(node, bytes):
        if len(node) == 32:
            found.add(node)
    elif isinstance(node, list):
        for item in node:
            _hashes_in(item, found)
    return found


def dependency_edges(obj) -> list:
    """Sorted hex hashes this object references from a type or term position.

    Identity slots are deliberately excluded — a data or ability declaration's
    nominal key (§5.1.1) and an extern's pinned artifact (§5.1.3) are 32-byte
    values that name something *other* than a store object, and reporting them
    as dependencies would invent edges to hashes the store can never hold.
    """
    tag = obj[0]
    if tag == 0:  # definition: [0, type, term]
        roots = obj[1:3]
    elif tag == 4:  # data: [4, nominal_key, parameters, constructor field types]
        roots = [obj[3]]
    elif tag == 5:  # ability: [5, nominal_key, operation signatures]
        roots = [obj[2]]
    elif tag == 7:  # extern: [7, type, artifact, abi]
        roots = [obj[1]]
    else:
        raise ValueError(f"unknown object kind tag {tag!r}")
    found: set = set()
    for root in roots:
        _hashes_in(root, found)
    return sorted(digest.hex() for digest in found)


# ---------------------------------------------------------------------------
# Sidecar construction
# ---------------------------------------------------------------------------


def _contract_versions(layers) -> dict:
    return {layer: contracts.version(layer) for layer in layers}


def sidecar_bytes(sidecar: dict) -> bytes:
    """Deterministic sidecar bytes: sorted keys, two-space indent, one newline.

    Determinism is a requirement, not a nicety — the plan's completion
    criterion is that a store deleted and re-seeded from the pinned corpus is
    byte-identical, and the store's `fsck` digests these bytes.
    """
    text = json.dumps(sidecar, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def definition_sidecar(
    source: str,
    *,
    resolver,
    sequence: int,
    name: str | None = None,
    spec: str | None = None,
    origin: str = "generated",
    provenance_source: str = "",
) -> tuple[bytes, dict]:
    """Validate one definition surface and build its object bytes + sidecar.

    The layer order is `experiment.evaluate.run_funnel`'s, and the refusal is
    that layer's own exception class — conclusion 2's shape, at admission time
    rather than at lookup time.
    """
    try:
        ir = transcode.parse_source(source)
    except Exception as error:  # noqa: BLE001 - the layer class is the taxonomy
        raise AdmissionRefused("parser", error) from None
    obj = cbor_canonical.encode(ir)
    digest = hashlib.sha256(obj).hexdigest()

    # §3.3 refinement subsumption is opt-in, and a `refine`-carrying definition
    # cannot reach the `checked` tier without it — `test_corpus` threads the
    # same collector for exactly that reason. Admission runs the *deepest*
    # validation available, which is a deliberate difference from
    # `evaluate.run_funnel`, whose job is to score what a model produced under
    # the default rules rather than to decide what may enter the store.
    admitted_obligations: list = []
    for layer, run in (
        ("scope", lambda: scope.validate_source(source, resolver.operation_arity)),
        ("references", lambda: references.validate_source(source, resolver.declarations)),
        (
            "typecheck",
            lambda: typecheck.validate_source(
                source,
                resolver.declarations,
                resolver.reference_type,
                obligations=admitted_obligations,
            ),
        ),
    ):
        try:
            run()
        except Exception as error:  # noqa: BLE001 - the layer class is the taxonomy
            raise AdmissionRefused(layer, error) from None

    sidecar = {
        "schema": SCHEMA,
        "hash": digest,
        "kind": KIND_DEFINITION,
        "name": name,
        "type_surface": transcode.type_to_surface(ir[1]),
        "deps": dependency_edges(ir),
        "surface": source,
        "object": None,
        "spec": spec,
        "sequence": sequence,
        "provenance": {
            "origin": origin,
            "source": provenance_source,
            "admitter": ADMITTER,
        },
        "validation": {
            "layers": list(DEFINITION_LAYERS),
            "contracts": _contract_versions(DEFINITION_LAYERS),
            "obligations": len(admitted_obligations),
        },
    }
    return obj, sidecar


def declaration_sidecar(
    obj_ir,
    *,
    sequence: int,
    name: str,
    origin: str = "declared",
    provenance_source: str = "",
) -> tuple[bytes, dict]:
    """Validate one §5.1 declaration and build its object bytes + sidecar.

    `declarations.declaration_bytes` *is* the validation — it refuses before it
    encodes — so there is no separate check to run and no way to store an
    object the declaration contract would reject.
    """
    try:
        obj = declarations.declaration_bytes(obj_ir)
    except Exception as error:  # noqa: BLE001 - the layer class is the taxonomy
        raise AdmissionRefused("declarations", error) from None
    digest = hashlib.sha256(obj).hexdigest()
    tag = obj_ir[0]
    kind = KIND_BY_TAG[tag]

    provenance = {"origin": origin, "source": provenance_source, "admitter": ADMITTER}
    type_surface = None
    if kind == KIND_EXTERN:
        type_surface = transcode.type_to_surface(obj_ir[1])
        provenance["artifact"] = obj_ir[2].hex()
        provenance["abi"] = obj_ir[3]
    else:
        provenance["nominal_key"] = obj_ir[1].hex()

    sidecar = {
        "schema": SCHEMA,
        "hash": digest,
        "kind": kind,
        "name": name,
        "type_surface": type_surface,
        "deps": dependency_edges(obj_ir),
        "surface": None,
        "object": ir_to_json(obj_ir),
        "spec": None,
        "sequence": sequence,
        "provenance": provenance,
        "validation": {
            "layers": list(DECLARATION_LAYERS),
            "contracts": _contract_versions(DECLARATION_LAYERS),
            "obligations": 0,
        },
    }
    # The mirror is never trusted: decode it back and require the canonical
    # hash to survive the round trip. A mirror that disagreed with the CBOR
    # encoder is the one defect this format could introduce, and this line is
    # why it cannot be introduced silently.
    mirrored = declarations.declaration_hash(json_to_ir(sidecar["object"])).hex()
    if mirrored != digest:
        raise ValueError(f"sidecar mirror round trip changed {digest} into {mirrored}")
    return obj, sidecar


# ---------------------------------------------------------------------------
# The pinned corpus, in seeding order
# ---------------------------------------------------------------------------


def corpus_objects():
    """Every pinned object, in the order a fresh store admits them.

    Declarations first because a definition cannot be typechecked before the
    declarations its types name exist, then definitions in manifest order,
    which is dependency order (`corpus_registry.MANIFEST`'s own invariant).
    """
    resolver_declarations = corpus_registry.registry()
    definitions = corpus_registry.reference_type(resolver_declarations)

    class _Resolver:
        """The three attributes `definition_sidecar` asks a resolver for."""

        declarations = resolver_declarations
        operation_arity = staticmethod(resolver_declarations.operation_arity)
        reference_type = staticmethod(definitions)

    sequence = 0
    for name in prelude.HASHES:
        obj, sidecar = declaration_sidecar(
            prelude.declaration(name),
            sequence=sequence,
            name=name,
            provenance_source="SPEC.md §2.4 builtin ability prelude",
        )
        yield obj, sidecar
        sequence += 1
    for name in corpus_registry.HASHES:
        obj, sidecar = declaration_sidecar(
            corpus_registry.declaration(name),
            sequence=sequence,
            name=name,
            provenance_source="bootstrap corpus data declaration",
        )
        yield obj, sidecar
        sequence += 1
    for name in corpus_registry.EXTERN_HASHES:
        obj, sidecar = declaration_sidecar(
            corpus_registry.extern(name),
            sequence=sequence,
            name=name,
            provenance_source="bootstrap corpus assumed base (host adapter)",
        )
        yield obj, sidecar
        sequence += 1
    for entry in corpus_registry.MANIFEST:
        obj, sidecar = definition_sidecar(
            entry.source_text().rstrip("\n"),
            resolver=_Resolver,
            sequence=sequence,
            name=entry.name_path,
            spec=entry.spec,
            origin="transpiled",
            provenance_source=entry.source,
        )
        yield obj, sidecar
        sequence += 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_pair(out: Path, stem: str, obj: bytes, sidecar: dict) -> dict:
    (out / f"{stem}.bin").write_bytes(obj)
    (out / f"{stem}.json").write_bytes(sidecar_bytes(sidecar))
    return {
        "hash": sidecar["hash"],
        "kind": sidecar["kind"],
        "name": sidecar["name"],
        "sequence": sidecar["sequence"],
        "object": f"{stem}.bin",
        "sidecar": f"{stem}.json",
    }


def _emit_line(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def _load_resolver(path: str | None):
    if path is None:
        registry = corpus_registry.registry()
        resolve = corpus_registry.reference_type(registry)

        class _Pinned:
            declarations = registry
            operation_arity = staticmethod(registry.operation_arity)
            reference_type = staticmethod(resolve)

        return _Pinned
    from experiment.store_resolver import StoreResolver

    return StoreResolver.from_path(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="store_admit", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("contracts", help="print the contract-version map")

    corpus = sub.add_parser("corpus", help="emit the whole pinned corpus in seeding order")
    corpus.add_argument("--out", required=True, type=Path)

    emit = sub.add_parser("emit", help="emit one definition source file")
    emit.add_argument("--out", required=True, type=Path)
    emit.add_argument("--resolver", default=None, help="an export-resolver document")
    emit.add_argument("--sequence", type=int, default=0)
    emit.add_argument("--name", default=None)
    emit.add_argument("--spec", default=None)
    emit.add_argument("--origin", default="generated")
    emit.add_argument("source", type=Path)

    args = parser.parse_args(argv)

    if args.command == "contracts":
        _emit_line(dict(contracts.VERSIONS))
        return 0

    args.out.mkdir(parents=True, exist_ok=True)

    try:
        if args.command == "corpus":
            entries = [
                _write_pair(args.out, f"{index:04d}", obj, sidecar)
                for index, (obj, sidecar) in enumerate(corpus_objects())
            ]
            _emit_line({"count": len(entries), "objects": entries})
            return 0

        source = args.source.read_text(encoding="utf-8").rstrip("\n")
        obj, sidecar = definition_sidecar(
            source,
            resolver=_load_resolver(args.resolver),
            sequence=args.sequence,
            name=args.name,
            spec=args.spec,
            origin=args.origin,
            provenance_source=str(args.source),
        )
        _emit_line({"count": 1, "objects": [_write_pair(args.out, "object", obj, sidecar)]})
        return 0
    except AdmissionRefused as refused:
        _emit_line(
            {
                "error": "refused",
                "layer": refused.layer,
                "error_class": refused.error_class,
                "message": refused.message,
            }
        )
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
