"""R1's disposable store-shaped resolver: one hash-keyed lookup surface.

The plan is explicit that this is *not* the store. It is immutable in-memory
objects keyed by hash, built once at construction from the registries that
already exist, and thrown away with the experiment. Namespaces, leases, policy
admission, persistence and garbage collection are out by rule, and none of them
appear here.

What it unifies, and why the experiment needs each:

* **Definition types** — `DefinitionTypeRegistry` over the corpus manifest, so a
  generated `(ref 0x…)` into a corpus definition types instead of being refused.
* **Declaration types** — `DeclarationRegistry` over §2.4's builtin abilities,
  the corpus data declarations, and the nine assumed-base externs, so nominal
  hashes and extern references resolve.
* **Definition surfaces** — the canonical fixture bytes, which is what few-shot
  prompt construction reads and what R3's identity-match semantic rule for
  corpus-drawn tasks compares against.

`corpus_registry.reference_type()` already composes the first two, but rebuilds
the definition snapshot on every call and exposes nothing else. This class
builds it once and answers the three questions the harness actually asks —
*what type does this hash have*, *what is this hash*, and *what are its
canonical bytes* — behind one object. That single object is also the honest
answer to R6's "what API must the store expose to the masker": whatever this
class ends up needing is the lower bound.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from types import MappingProxyType

import corpus_registry
import prelude
from declarations import DeclarationRegistry
from definition_types import DefinitionTypeRegistry

#: The kinds a hash can resolve to. Deliberately not an enum: these strings go
#: straight into the JSONL run record and must stay stable and greppable.
KIND_DEFINITION = "definition"
KIND_DATA = "data"
KIND_ABILITY = "ability"
KIND_EXTERN = "extern"

KINDS = (KIND_DEFINITION, KIND_DATA, KIND_ABILITY, KIND_EXTERN)


@dataclass(frozen=True)
class Resolved:
    """One hash-keyed object, as much of it as the experiment can see.

    `type_ir` is an isolated copy for every kind that has a type; `surface` is
    populated only for definitions, because a declaration has no canonical
    definition surface to show a model.
    """

    digest: bytes
    kind: str
    name: str
    type_ir: list | None = None
    surface: str | None = None

    @property
    def hex(self) -> str:
        return self.digest.hex()


class ExperimentResolver:
    """Hash-keyed lookup over the corpus, the prelude, and the assumed base."""

    def __init__(self) -> None:
        self._declarations: DeclarationRegistry = corpus_registry.registry()
        self._definitions = DefinitionTypeRegistry(self._declarations.operation_arity)

        objects: dict[bytes, Resolved] = {}
        entries: dict[bytes, corpus_registry.CorpusEntry] = {}
        by_name: dict[str, bytes] = {}

        for name, digest in prelude.HASHES.items():
            objects[digest] = Resolved(digest=digest, kind=KIND_ABILITY, name=name)
            by_name[name] = digest
        for name, digest in corpus_registry.HASHES.items():
            objects[digest] = Resolved(digest=digest, kind=KIND_DATA, name=name)
            by_name[name] = digest
        for name, digest in corpus_registry.EXTERN_HASHES.items():
            objects[digest] = Resolved(
                digest=digest,
                kind=KIND_EXTERN,
                name=name,
                type_ir=self._declarations.reference_type(digest),
            )
            by_name[name] = digest

        # Manifest order is dependency order (no forward references), so adding
        # in order never asks the snapshot for a hash it does not yet hold.
        for entry in corpus_registry.MANIFEST:
            digest = bytes.fromhex(entry.identity)
            source = entry.source_text().rstrip("\n")
            recorded = self._definitions.add_source(source, expected_hash=digest)
            if recorded != digest:  # pragma: no cover - add_source already raises
                raise ValueError(f"corpus identity drift for {entry.name_path}")
            objects[digest] = Resolved(
                digest=digest,
                kind=KIND_DEFINITION,
                name=entry.name_path,
                type_ir=self._definitions.reference_type(digest),
                surface=source,
            )
            entries[digest] = entry
            by_name[entry.name_path] = digest

        self._objects = MappingProxyType(objects)
        self._entries = MappingProxyType(entries)
        self._by_name = MappingProxyType(by_name)

    # -- the registries, for the layers that take one directly ---------------

    @property
    def declarations(self) -> DeclarationRegistry:
        """The registry `references.validate_source` and the checker want."""
        return self._declarations

    @property
    def operation_arity(self):
        """The resolver `scope.validate_source` wants."""
        return self._declarations.operation_arity

    def reference_type(self, digest: bytes) -> list:
        """The §3.1.3 `ref`-type resolver, definitions first then declarations.

        Same contract as `corpus_registry.reference_type`'s closure — a hash in
        neither source raises rather than guessing — over a snapshot built once.
        """
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
        """The object behind a hash, or `LookupError` naming the hash."""
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
        """The hash of a named object (`corpus/list/append`, `List`, `clock`)."""
        try:
            return self._by_name[name]
        except KeyError:
            raise LookupError(f"unknown object name {name!r}") from None

    def entry(self, digest: bytes) -> corpus_registry.CorpusEntry:
        """The manifest entry behind a definition hash."""
        try:
            return self._entries[digest]
        except KeyError:
            raise LookupError(f"{digest.hex()} is not a corpus definition") from None

    def surface(self, digest: bytes) -> str:
        """The canonical fixture bytes for a definition hash."""
        found = self.resolve(digest)
        if found.surface is None:
            raise LookupError(f"{digest.hex()} has no definition surface")
        return found.surface

    def definitions(self) -> tuple[Resolved, ...]:
        """Every corpus definition, in manifest (dependency) order."""
        return tuple(
            self.resolve(bytes.fromhex(entry.identity))
            for entry in corpus_registry.MANIFEST
        )

    def digests(self) -> tuple[bytes, ...]:
        """Every hash this resolver can resolve, in no particular order.

        Phase B's reference-hash pruner is built from exactly this set: a hash
        outside it cannot appear in a definition this run would accept, so the
        set *is* the prefix universe the mask prunes against. R6 asks what API
        the store must expose to the masker; this method is one of the answers.
        """
        return tuple(self._objects)

    def counts(self) -> dict[str, int]:
        """How many objects of each kind the resolver holds — a report line."""
        return {kind: sum(1 for o in self._objects.values() if o.kind == kind) for kind in KINDS}
