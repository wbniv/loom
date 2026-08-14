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
``kind``             ``definition`` | ``data`` | ``ability`` | ``extern``
                     | ``policy``.
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
                     the admitter has none. A policy object carries its
                     §5.3.1 key 9 ``statement`` here, which is the only
                     prose a policy has.
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

The IR is JSON-shaped already except for two forms JSON has no spelling for:
byte strings become ``{"b16": "<hex>"}``, and CBOR maps — which only §5.3.1
policy objects use — become ``{"m": [[key, value]…]}`` in canonical key order,
because a JSON object cannot have integer keys. Encoding and decoding are
inverse, and both directions are checked against the canonical hash rather
than trusted — a mirror that silently disagreed with the CBOR encoder would be
the one defect this format could introduce, so it is never possible to land
one.

Commands
--------

``contracts``   print the contract-version map (one JSON line).
``corpus``      emit the whole pinned corpus — 8 abilities, 4 data
                declarations, 9 externs, 26 definitions — in seeding order.
``emit``        emit one definition source file, validated against a
                resolver export (``--resolver``) or, absent one, the pinned
                corpus registry.
``policy``      emit one §5.3.1 policy object, either ``--default`` (the
                empty policy, three bytes, the base case of §5.3.2's
                resolution) or from a JSON-mirrored policy map.
``bind``        run §5.3.2 admission over a binding request document (see
                `bindings.py`) and print the admission record, or refuse.

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

import bindings
import cbor_canonical
import contracts
import corpus_registry
import declarations
import policies
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
KIND_POLICY = "policy"

#: Object-kind tag (§4.1/§5.1, position 0 of every canonical object) to the
#: store's kind string. The store never reads the tag — it reads this string
#: out of the sidecar — but keeping the mapping in one place is what makes the
#: two agree.
KIND_BY_TAG = {
    0: KIND_DEFINITION,
    4: KIND_DATA,
    5: KIND_ABILITY,
    6: KIND_POLICY,
    7: KIND_EXTERN,
}

#: Which layers a definition passes through, in the order `run_funnel` runs
#: them. Recorded per object because a later store will admit objects that
#: reached different depths.
DEFINITION_LAYERS = ("parser", "scope", "references", "typecheck")
DECLARATION_LAYERS = ("declarations",)
POLICY_LAYERS = ("policies",)

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
    """Mirror an object IR into JSON.

    Byte strings become ``{"b16": hex}``; CBOR maps — which only §5.3.1 policy
    objects use — become ``{"m": [[key, value]…]}``, sorted by key, because a
    JSON object cannot carry the unsigned-integer keys §5.3.1 specifies.
    """
    if isinstance(node, bytes):
        return {"b16": node.hex()}
    if isinstance(node, bool) or isinstance(node, int) or isinstance(node, str):
        return node
    if isinstance(node, list):
        return [ir_to_json(item) for item in node]
    if isinstance(node, dict):
        return {"m": [[ir_to_json(key), ir_to_json(node[key])] for key in sorted(node)]}
    raise TypeError(f"cannot mirror {type(node).__name__} into the sidecar")


def json_to_ir(node):
    """The inverse of `ir_to_json`, strict about the two dict shapes it knows."""
    if isinstance(node, dict):
        if set(node) == {"b16"}:
            return bytes.fromhex(node["b16"])
        if set(node) == {"m"}:
            entries = node["m"]
            if not isinstance(entries, list):
                raise ValueError("sidecar object: a mirrored map must be an array of pairs")
            decoded = {}
            for entry in entries:
                if not isinstance(entry, list) or len(entry) != 2:
                    raise ValueError("sidecar object: a mirrored map entry must be [key, value]")
                key = json_to_ir(entry[0])
                if key in decoded:
                    raise ValueError(f"sidecar object: duplicate map key {key!r}")
                decoded[key] = json_to_ir(entry[1])
            return decoded
        raise ValueError(f"sidecar object: unknown mirrored form {sorted(node)}")
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

    A **policy object has no dependency edges at all**, and that is the same
    rule rather than an exception. Its 32-byte values are A1 generators (key
    0), ability hashes (key 3) and principal-ids (keys 4 and 5); the last two
    are not store objects, and a generator is not *referenced* by the policy in
    a type or term position — the policy states a constraint on evidence *about*
    it, and a policy that names a generator no object in this store was ever
    measured against is a perfectly well-formed policy.
    """
    tag = obj[0]
    if tag == 0:  # definition: [0, type, term]
        roots = obj[1:3]
    elif tag == 4:  # data: [4, nominal_key, parameters, constructor field types]
        roots = [obj[3]]
    elif tag == 5:  # ability: [5, nominal_key, operation signatures]
        roots = [obj[2]]
    elif tag == 6:  # policy: [6, policy-map] — see the docstring
        return []
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


def policy_sidecar(policy_ir, *, sequence: int = 0, name: str | None = None) -> tuple[bytes, dict]:
    """Validate one §5.3.1 policy object and build its object bytes + sidecar.

    `policies.policy_bytes` *is* the validation — it refuses before it
    encodes — so, exactly as for declarations, there is no separate check to
    run and no way to store an object the `policies` contract would reject.

    A policy has no nominal key and no name of its own: two policies stating
    the same constraints are the same policy and share one hash (§5.3.1). The
    sidecar's `name` is therefore the *admitter's* label for it, and nothing
    resolves by it.
    """
    try:
        obj = policies.policy_bytes(policy_ir)
    except Exception as error:  # noqa: BLE001 - the layer class is the taxonomy
        raise AdmissionRefused("policies", error) from None
    digest = hashlib.sha256(obj).hexdigest()
    policy_map = policy_ir[1]

    sidecar = {
        "schema": SCHEMA,
        "hash": digest,
        "kind": KIND_POLICY,
        "name": name,
        "type_surface": None,
        "deps": dependency_edges(policy_ir),
        "surface": None,
        "object": ir_to_json(policy_ir),
        "spec": policy_map.get(9),
        "sequence": sequence,
        "provenance": {
            "origin": "declared",
            "source": "SPEC.md §5.3.1 namespace policy object",
            "admitter": ADMITTER,
        },
        "validation": {
            "layers": list(POLICY_LAYERS),
            "contracts": _contract_versions(POLICY_LAYERS),
            "obligations": 0,
        },
    }
    mirrored = policies.policy_hash(json_to_ir(sidecar["object"])).hex()
    if mirrored != digest:
        raise ValueError(f"sidecar mirror round trip changed {digest} into {mirrored}")
    return obj, sidecar


def default_policy_pair() -> tuple[bytes, dict]:
    """The base case of §5.3.2's resolution — the empty policy, three bytes,
    preloaded in every store like the §2.4 prelude."""
    obj, sidecar = policy_sidecar(policies.DEFAULT_POLICY, sequence=0, name="POLICY/default")
    if sidecar["hash"] != policies.DEFAULT_POLICY_HASH.hex():
        raise ValueError(f"the default policy hashed to {sidecar['hash']}, not the SPEC's value")
    return obj, sidecar


# ---------------------------------------------------------------------------
# The binding request wire format (`bind`)
# ---------------------------------------------------------------------------

#: Wire-format version of the request document `bind` reads. Bumped when the
#: Rust store and this oracle must change together.
BIND_SCHEMA = 1


def _hash_field(value, path: str) -> bytes:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{path}: expected 64 lowercase hex digits")
    return bytes.fromhex(value)


def point_from_json(value, path: str) -> list:
    """A lattice point off the wire: A1's generator arrives as hex text and
    becomes the 32 bytes `policies.validate_point` requires."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path}: expected a lattice point")
    if value[0] == 1 and len(value) == 4:
        return [1, value[1], value[2], _hash_field(value[3], f"{path}.generator")]
    return list(value)


def point_to_json(point) -> list:
    if point[0] == 1 and len(point) == 4:
        return [1, point[1], point[2], point[3].hex()]
    return list(point)


def _evidence_from_json(value, path: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected an array of [obligation-id, point]")
    out = []
    for index, entry in enumerate(value):
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError(f"{path}[{index}]: expected [obligation-id, point]")
        out.append([entry[0], point_from_json(entry[1], f"{path}[{index}].point")])
    return out


def bind_request(document: dict):
    """Decode a binding request into the plain values `bindings.admit` takes.

    This function is the whole wire format. `bindings.py` never sees JSON, and
    the store never sees IR — which is what keeps the semantics testable
    without a filesystem and the store free of object interpretation.
    """
    schema = document.get("schema")
    if schema != BIND_SCHEMA:
        raise ValueError(f"bind request schema {schema!r} is not {BIND_SCHEMA}")
    body = document["binding"]
    candidate = bindings.Candidate(
        name_path=body["name_path"],
        def_hash=_hash_field(body["def_hash"], "binding.def_hash"),
        evidence=_evidence_from_json(body.get("evidence"), "binding.evidence"),
        policy_ref=_hash_field(body["policy_ref"], "binding.policy_ref"),
        seq=int(body.get("seq", 0)),
        object=json_to_ir(body["object"]) if body.get("object") is not None else None,
    )
    chain = [
        bindings.PolicyBinding(
            namespace=entry["namespace"],
            hash=_hash_field(entry["hash"], "policy_bindings[].hash"),
            object=json_to_ir(entry["object"]),
        )
        for entry in document.get("policy_bindings") or []
    ]
    return candidate, chain, _previous_from_json(document.get("previous"))


def lease_request(document: dict):
    """Decode a lease-check request: the namespace, the claimed principal-id,
    the requested TTL, and the enclosing namespaces' current `POLICY` bindings.

    The principal-id is **claimed, not proved** (§5.3.3, L6). The store records
    it unverified — the same stance §5.3.1 already takes for A0 signers — and
    this decoder is the seam a proof argument slots into when the A0 payload
    format lands.
    """
    schema = document.get("schema")
    if schema != BIND_SCHEMA:
        raise ValueError(f"lease request schema {schema!r} is not {BIND_SCHEMA}")
    chain = [
        bindings.PolicyBinding(
            namespace=entry["namespace"],
            hash=_hash_field(entry["hash"], "policy_bindings[].hash"),
            object=json_to_ir(entry["object"]),
        )
        for entry in document.get("policy_bindings") or []
    ]
    return (
        document["namespace"],
        _hash_field(document["principal"], "principal"),
        int(document["ttl_millis"]),
        chain,
    )


def _previous_from_json(previous):
    if previous is not None:
        previous = bindings.Previous(
            def_hash=_hash_field(previous["def_hash"], "previous.def_hash"),
            evidence=_evidence_from_json(previous.get("evidence"), "previous.evidence"),
            policy_ref=_hash_field(previous["policy_ref"], "previous.policy_ref"),
            seq=int(previous.get("seq", 0)),
            object=json_to_ir(previous["object"]) if previous.get("object") is not None else None,
        )
    return previous


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

    policy = sub.add_parser("policy", help="emit one §5.3.1 policy object")
    policy.add_argument("--out", required=True, type=Path)
    policy.add_argument(
        "--default",
        action="store_true",
        dest="use_default",
        help="the empty policy — §5.3.2's base case, preloaded in every store",
    )
    policy.add_argument("--name", default=None)
    policy.add_argument("--sequence", type=int, default=0)
    policy.add_argument("source", nargs="?", type=Path, help="a JSON-mirrored policy object")

    bind = sub.add_parser("bind", help="run §5.3.2 admission over a binding request")
    bind.add_argument("request", type=Path)

    lease = sub.add_parser("lease", help="apply §5.3.1 keys 5 and 6 to a lease request")
    lease.add_argument("request", type=Path)

    args = parser.parse_args(argv)

    if args.command == "contracts":
        _emit_line(dict(contracts.VERSIONS))
        return 0

    if args.command in ("bind", "lease"):
        document = json.loads(args.request.read_text(encoding="utf-8"))
        try:
            if args.command == "bind":
                candidate, chain, previous = bind_request(document)
                _emit_line(bindings.admit(candidate, chain, previous))
            else:
                _emit_line(bindings.check_lease(*lease_request(document)))
            return 0
        except (
            bindings.BindingRefused,
            bindings.LeaseRefused,
            policies.PolicyError,
            ValueError,
            KeyError,
        ) as error:
            _emit_line(
                {
                    "error": "refused",
                    "layer": "bindings" if args.command == "bind" else "leases",
                    "error_class": type(error).__name__,
                    "message": str(error),
                    "rule": getattr(error, "rule", None),
                    "reason": getattr(error, "reason", None),
                }
            )
            return EXIT_REFUSED

    args.out.mkdir(parents=True, exist_ok=True)

    try:
        if args.command == "policy":
            if args.use_default == (args.source is not None):
                raise AdmissionRefused(
                    "policies",
                    ValueError("policy needs exactly one of --default or a source file"),
                )
            if args.use_default:
                obj, sidecar = default_policy_pair()
            else:
                mirrored = json.loads(args.source.read_text(encoding="utf-8"))
                obj, sidecar = policy_sidecar(
                    json_to_ir(mirrored), sequence=args.sequence, name=args.name
                )
            entry = _write_pair(args.out, "policy", obj, sidecar)
            _emit_line({"count": 1, "objects": [entry]})
            return 0

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
