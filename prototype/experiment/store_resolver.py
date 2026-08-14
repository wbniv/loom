"""`ExperimentResolver`, rebuilt from a store instead of from the corpus tree.

R4 of [the store plan](../../docs/plans/2026-08-14-store-v0.md) asks for one
thing from the Python side: a resolver that consumes `loom-store
export-resolver` and is *behaviourally identical* to the corpus-built resolver,
proven by running the resolver-dependent tests against both. That is the v0
acceptance gate, and it is deliberately a strong one — byte-identical prompt
assembly over all 26 definitions × 4 regimes, not "looks the same".

Why identical rather than merely equivalent, and why that is achievable:

* **Definitions travel as their canonical surface.** The store holds opaque
  CBOR, but the sidecar carries the surface text, and the parser contract makes
  surface and bytes an inverse pair. So this class re-parses the surface and
  requires the identity to come back out — the store's claim is checked, never
  taken.
* **Declarations travel as a JSON mirror of their IR**, because §5.1
  declarations have no surface syntax to travel as. `DeclarationRegistry.add`
  is handed the reconstructed object *with* its expected hash, so a mirror that
  round-tripped wrong fails at load with the declaration layer's own error.
* **Types are re-derived, not copied.** `type_ir` comes from the same two
  registries `ExperimentResolver` builds it from, and the store's precomputed
  `type_surface` column is then checked against the reconstruction. Copying the
  column instead would make the two resolvers agree by construction, which is
  the one way to make this equivalence proof vacuous.

Everything the harness asks a resolver for is here, with the same names and the
same refusal behaviour — a hash in neither source raises `LookupError` rather
than guessing, exactly as §2.3.1 requires and as the live GPU run's invented
ability hash demonstrated the hard way.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import cbor_canonical
import transcode
from declarations import DeclarationRegistry
from definition_types import DefinitionTypeRegistry
from store_admit import json_to_ir

from .resolver import KIND_ABILITY, KIND_DATA, KIND_DEFINITION, KIND_EXTERN, KINDS, Resolved


@dataclass(frozen=True)
class StoreEntry:
    """The §5.2 metadata a stored definition carries.

    `corpus_registry.CorpusEntry` is a *manifest* row that reads its source off
    the filesystem; this is the same information as the store holds it, with
    `source_text()` served from the sidecar rather than from `prototype/corpus/`.
    Prompt assembly asks an entry for `spec` and nothing else, so the two are
    interchangeable where the harness actually uses them.
    """

    name_path: str
    spec: str
    source: str
    identity: str
    surface: str
    sequence: int

    def source_text(self) -> str:
        return self.surface + "\n"


class StoreExportError(ValueError):
    """The export document is not one this resolver can be built from."""


class StoreResolver:
    """Hash-keyed lookup over the objects a store holds."""

    def __init__(self, document: dict):
        schema = document.get("schema")
        if schema != 1:
            raise StoreExportError(f"export schema {schema!r} is not 1")
        objects = document.get("objects")
        if not isinstance(objects, list):
            raise StoreExportError("export has no `objects` array")

        self._declarations = DeclarationRegistry()
        resolved: dict[bytes, Resolved] = {}
        entries: dict[bytes, StoreEntry] = {}
        by_name: dict[str, bytes] = {}
        definition_sidecars = []

        # Declarations first: a definition cannot be scope-checked without the
        # ability arities, and the export is ordered so this is also just
        # "in the order the store was written".
        for sidecar in objects:
            kind = sidecar["kind"]
            digest = bytes.fromhex(sidecar["hash"])
            name = sidecar.get("name")
            if kind == KIND_DEFINITION:
                definition_sidecars.append(sidecar)
                continue
            if sidecar.get("object") is None:
                raise StoreExportError(f"{sidecar['hash']}: a {kind} sidecar carries no object")
            self._declarations.add(json_to_ir(sidecar["object"]), expected_hash=digest)
            type_ir = self._declarations.reference_type(digest) if kind == KIND_EXTERN else None
            self._check_type_surface(sidecar, type_ir)
            resolved[digest] = Resolved(digest=digest, kind=kind, name=name, type_ir=type_ir)
            if name is not None:
                by_name[name] = digest

        self._definitions = DefinitionTypeRegistry(self._declarations.operation_arity)
        for sidecar in definition_sidecars:
            digest = bytes.fromhex(sidecar["hash"])
            surface = sidecar.get("surface")
            if surface is None:
                raise StoreExportError(f"{sidecar['hash']}: a definition sidecar carries no surface")
            self._check_identity(sidecar, surface, digest)
            self._definitions.add_source(surface, expected_hash=digest)
            type_ir = self._definitions.reference_type(digest)
            self._check_type_surface(sidecar, type_ir)
            name = sidecar.get("name")
            resolved[digest] = Resolved(
                digest=digest,
                kind=KIND_DEFINITION,
                name=name,
                type_ir=type_ir,
                surface=surface,
            )
            if name is not None:
                by_name[name] = digest
                entries[digest] = StoreEntry(
                    name_path=name,
                    spec=sidecar.get("spec") or "",
                    source=(sidecar.get("provenance") or {}).get("source", ""),
                    identity=sidecar["hash"],
                    surface=surface,
                    sequence=int(sidecar.get("sequence", 0)),
                )

        self._objects = MappingProxyType(resolved)
        self._entries = MappingProxyType(entries)
        self._by_name = MappingProxyType(by_name)
        self._definition_order = tuple(
            bytes.fromhex(sidecar["hash"]) for sidecar in definition_sidecars
        )
        self._contracts = MappingProxyType(dict(document.get("store", {}).get("contracts", {})))

    # -- construction --------------------------------------------------------

    @classmethod
    def from_path(cls, path) -> StoreResolver:
        """Build from a `loom-store export-resolver --out PATH` document."""
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- verification --------------------------------------------------------

    @staticmethod
    def _check_identity(sidecar: dict, surface: str, digest: bytes) -> None:
        """The surface must hash back to the name the store filed it under."""
        ir = transcode.parse_source(surface)
        actual = hashlib.sha256(cbor_canonical.encode(ir)).digest()
        if actual != digest:
            raise StoreExportError(
                f"{sidecar['hash']}: the stored surface hashes to {actual.hex()}"
            )

    @staticmethod
    def _check_type_surface(sidecar: dict, type_ir) -> None:
        """The store's precomputed type column must agree with the reconstruction.

        The column is what the decode hot path reads (conclusion 3), so it is
        the one derived value in the store that a wrong answer would be *fast*
        about. Checking it here is the cheapest place the check exists.
        """
        claimed = sidecar.get("type_surface")
        expected = None if type_ir is None else transcode.type_to_surface(type_ir)
        if claimed != expected:
            raise StoreExportError(
                f"{sidecar['hash']}: index type surface {claimed!r} is not {expected!r}"
            )

    # -- the registries, for the layers that take one directly ---------------

    @property
    def declarations(self) -> DeclarationRegistry:
        return self._declarations

    @property
    def operation_arity(self):
        return self._declarations.operation_arity

    @property
    def contracts(self):
        """The contract versions the store was initialized under."""
        return self._contracts

    def reference_type(self, digest: bytes) -> list:
        try:
            return self._definitions.reference_type(digest)
        except LookupError:
            return self._declarations.reference_type(digest)

    # -- the hash-keyed surface ----------------------------------------------

    def __len__(self) -> int:
        return len(self._objects)

    def __contains__(self, digest: object) -> bool:
        return digest in self._objects

    def resolve(self, digest: bytes) -> Resolved:
        try:
            found = self._objects[digest]
        except KeyError:
            raise LookupError(f"unresolved hash {digest.hex()}") from None
        return Resolved(
            digest=found.digest,
            kind=found.kind,
            name=found.name,
            type_ir=copy.deepcopy(found.type_ir),
            surface=found.surface,
        )

    def resolve_hex(self, digest_hex: str) -> Resolved:
        return self.resolve(bytes.fromhex(digest_hex))

    def digest_for(self, name: str) -> bytes:
        try:
            return self._by_name[name]
        except KeyError:
            raise LookupError(f"unknown object name {name!r}") from None

    def entry(self, digest: bytes) -> StoreEntry:
        try:
            return self._entries[digest]
        except KeyError:
            raise LookupError(f"{digest.hex()} is not a corpus definition") from None

    def surface(self, digest: bytes) -> str:
        found = self.resolve(digest)
        if found.surface is None:
            raise LookupError(f"{digest.hex()} has no definition surface")
        return found.surface

    def definitions(self) -> tuple[Resolved, ...]:
        """Every stored definition, in the order the store was written.

        The store keeps the admitter's presentation order in each sidecar's
        `sequence`, which for the pinned corpus *is* the manifest's dependency
        order. That is why `sequence` is in the schema at all: without it a
        content-addressed store has no way to reproduce an order it did not
        invent, and `ExperimentResolver.definitions()` promises one.
        """
        return tuple(self.resolve(digest) for digest in self._definition_order)

    def digests(self) -> tuple[bytes, ...]:
        return tuple(self._objects)

    def counts(self) -> dict[str, int]:
        return {kind: sum(1 for o in self._objects.values() if o.kind == kind) for kind in KINDS}


__all__ = [
    "KIND_ABILITY",
    "KIND_DATA",
    "KIND_DEFINITION",
    "KIND_EXTERN",
    "StoreEntry",
    "StoreExportError",
    "StoreResolver",
]
