"""Bootstrap-corpus data declarations and the seed-set manifest.

The corpus seeds §13 open problem 1 (prior starvation). Its definitions are
hand-transpiled from the Unison base library's structural eliminators; see
`docs/plans/2026-08-13-bootstrap-corpus.md` for the corpus choice, the mapping
losses, and the tranche list.

Nominal keys are derived reproducibly as `SHA-256("loom:v0.1:corpus:" || name)`,
mirroring the §5.1.1 rule the reference prelude uses for builtins. A corpus
declaration is not a builtin, so it uses its own derivation prefix and can never
collide with `prelude.py`.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import prelude
from declarations import DeclarationRegistry, declaration_hash

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

#: Validation depth a fixture is expected to reach today.
#:
#: ``checked``    — parse, scope, references, and the type-directed match layer.
#: ``structural`` — parse, scope, and references only, because the match layer
#:                  has no typing rule for a node the definition needs. The
#:                  reason is recorded per entry and is a documented obligation
#:                  (§2.6/§6.2), never a silent pass.
TIERS = ("checked", "structural")


def nominal_key(name: str) -> bytes:
    return hashlib.sha256(f"loom:v0.1:corpus:{name}".encode("ascii")).digest()


_TYVAR_0 = [5, 0]
_TYVAR_1 = [5, 1]

_DECLARATIONS = {
    # Maybe a = Nothing | Just a          (Unison `Optional a = None | Some a`)
    "Maybe": [4, nominal_key("Maybe"), 1, [[], [_TYVAR_0]]],
    # Either a b = Left a | Right b       (Unison `Either a b = Left a | Right b`)
    "Either": [4, nominal_key("Either"), 2, [[_TYVAR_0], [_TYVAR_1]]],
    # Pair a b = Pair a b                 (Unison's `(a, b)` tuple, un-nested)
    "Pair": [4, nominal_key("Pair"), 2, [[_TYVAR_0, _TYVAR_1]]],
    # List a = Nil | Cons a (List a)      (Unison's builtin `[a]` sequence)
    "List": [4, nominal_key("List"), 1, [[], [_TYVAR_0, [7, [_TYVAR_0]]]]],
}

CONSTRUCTOR_NAMES = MappingProxyType({
    "Maybe": ("Nothing", "Just"),
    "Either": ("Left", "Right"),
    "Pair": ("Pair",),
    "List": ("Nil", "Cons"),
})

HASHES = MappingProxyType({name: declaration_hash(obj) for name, obj in _DECLARATIONS.items()})
HASH_HEX = MappingProxyType({name: digest.hex() for name, digest in HASHES.items()})


def declaration(name: str) -> list:
    """Return an isolated copy of a canonical corpus data declaration."""
    try:
        return copy.deepcopy(_DECLARATIONS[name])
    except KeyError as exc:
        raise KeyError(f"unknown corpus data declaration {name!r}") from exc


#: The assumed base (layer 1 of the bootstrap corpus): the five §11 extern
#: definitions tranche 2 needs. They are host primitives, not a WASM component,
#: so their pinned artifact is the host adapter's published ABI identity, derived
#: reproducibly under the corpus prefix exactly like a nominal key. One artifact,
#: five ABI selectors.
#:
#: The `abi` text is not a display name — it is the byte string §2.4's `ffi.call`
#: resolves, and changing it changes what is called. The human names (`I64.add`,
#: `List.size`) are §5.2 metadata and never enter identity, which is why the keys
#: of this table and the selectors inside it are deliberately not the same
#: spellings.
HOST_ARTIFACT = hashlib.sha256(b"loom:v0.1:corpus:host").digest()

_I64 = [0, 2]
_BOOL = [0, 1]


def _binary(result):
    """`I64 -> I64 -{}> result`, fully curried with empty rows throughout."""
    return [2, _I64, [], [2, _I64, [], result]]


_EXTERNS = {
    # I64.add : I64 -> I64 -> I64        (§3.2.1 interpretation `+`)
    "I64.add": [7, _binary(_I64), HOST_ARTIFACT, "i64.add"],
    # I64.sub : I64 -> I64 -> I64        (§3.2.1 interpretation `-`)
    "I64.sub": [7, _binary(_I64), HOST_ARTIFACT, "i64.sub"],
    # I64.eq  : I64 -> I64 -> Bool       (§3.2.1 interpretation `=`)
    "I64.eq": [7, _binary(_BOOL), HOST_ARTIFACT, "i64.eq"],
    # I64.lt  : I64 -> I64 -> Bool       (§3.2.1 interpretation `<`)
    "I64.lt": [7, _binary(_BOOL), HOST_ARTIFACT, "i64.lt"],
    # List.size : List I64 -> I64        uninterpreted; the R4 measure primitive
    "List.size": [7, [2, [1, HASHES["List"], [_I64]], [], _I64], HOST_ARTIFACT, "list.size"],
}

EXTERN_HASHES = MappingProxyType({name: declaration_hash(obj) for name, obj in _EXTERNS.items()})
EXTERN_HASH_HEX = MappingProxyType({name: digest.hex() for name, digest in EXTERN_HASHES.items()})

#: Toolchain interpretation table (§3.2.1): extern hash to allowlisted SMT-LIB
#: symbol. Policy, never part of an object — supplied to the translator, so
#: identity is untouched. `List.size` is deliberately absent and stays
#: uninterpreted.
SMT_INTERPRETATION = MappingProxyType({
    EXTERN_HASHES["I64.add"]: "+",
    EXTERN_HASHES["I64.sub"]: "-",
    EXTERN_HASHES["I64.eq"]: "=",
    EXTERN_HASHES["I64.lt"]: "<",
})


def extern(name: str) -> list:
    """Return an isolated copy of a canonical assumed-base extern definition."""
    try:
        return copy.deepcopy(_EXTERNS[name])
    except KeyError as exc:
        raise KeyError(f"unknown corpus extern {name!r}") from exc


def registry() -> DeclarationRegistry:
    """Builtin abilities (§2.4), every corpus data declaration, and the assumed base."""
    result = prelude.registry()
    for name, digest in HASHES.items():
        result.add(_DECLARATIONS[name], expected_hash=digest)
    for name, digest in EXTERN_HASHES.items():
        result.add(_EXTERNS[name], expected_hash=digest)
    return result


@dataclass(frozen=True)
class CorpusEntry:
    """One seed definition: the §5.2 meta object, minus provenance.

    ``name_path`` and ``spec`` are exactly what a meta object carries, so the
    (spec-text, canonical-surface) pair a §8.4 few-shot prompt needs is read
    straight off this manifest rather than from a second, invented format.
    """

    fixture: str
    name_path: str
    spec: str
    source: str
    identity: str
    tier: str
    deferred: str = ""

    @property
    def path(self) -> Path:
        return CORPUS_DIR / self.fixture

    def source_text(self) -> str:
        return self.path.read_text(encoding="utf-8")


MANIFEST = (
    CorpusEntry(
        fixture="maybe_is_nothing_i64.loom.sexpr",
        name_path="corpus/maybe/isNothing",
        spec="True when the option carries no value.",
        source="Unison base Optional.isNone, instantiated at I64",
        identity="575ff2d3a57e5a4582a7640b6bcd5365d5e0898e27576e820b3a5fbdd39b01a3",
        tier="checked",
    ),
    CorpusEntry(
        fixture="maybe_get_or_else_i64.loom.sexpr",
        name_path="corpus/maybe/getOrElse",
        spec="The option's value, or the supplied default when it is empty.",
        source="Unison base Optional.getOrElse, instantiated at I64",
        identity="2dc64240af4f0bf328f1572c9cd09bca3bed789d5a150a3a8d0c0825b4ad2a2a",
        tier="checked",
    ),
    CorpusEntry(
        fixture="maybe_map_i64.loom.sexpr",
        name_path="corpus/maybe/map",
        spec="Apply a function to the option's value, leaving an empty option empty.",
        source="Unison base Optional.map, instantiated at I64 -> I64",
        identity="a4b7f01ca0cbe6e6fd3494feb556cb6b7c8c4453152e7797e201f1b5e5449cf4",
        tier="checked",
    ),
    CorpusEntry(
        fixture="list_uncons_i64.loom.sexpr",
        name_path="corpus/list/uncons",
        spec="Split a list into its head and tail, or nothing when it is empty.",
        source="Unison base List.uncons, instantiated at I64",
        identity="1aa47aec06e66f1f563d461eedcf951c9cdab11e7fa26d252536c97160798af5",
        tier="checked",
    ),
)


def few_shot_pairs():
    """(spec-text, canonical-surface) pairs for a §8.4 few-shot prompt.

    Emission order follows the manifest, which is dependency order: every
    declaration a definition names is registered before it, and no entry refers
    to a later one. The store has no forward references, and neither does this.
    """
    return tuple((entry.spec, entry.source_text().rstrip("\n")) for entry in MANIFEST)
