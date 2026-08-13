"""Bootstrap-corpus data declarations and the seed-set manifest.

The corpus seeds §13 open problem 1 (prior starvation). Its definitions are
hand-transpiled from the base library of the MIT-licensed unisonweb/unison
repository — structural eliminators (tranche 1), their recursive companions
(tranche 2), and ability code against §2.4's builtins (tranche 3); see
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
from definition_types import DefinitionTypeRegistry

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

#: Validation depth a fixture is expected to reach today.
#:
#: ``checked``    — parse, scope, references, and the type-directed match layer,
#:                  the last one given `reference_type()` so a `ref` into the
#:                  assumed base resolves instead of being refused.
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


def reference_type(source: DeclarationRegistry | None = None):
    """The `ref`-type resolver the match layer needs (§3.1.3).

    The prototype has no live store, so a validated immutable definition-type
    snapshot stands in for it. Extern types continue to resolve through the
    declaration registry. A hash absent from both sources still raises, and the
    typing layer refuses rather than guessing.
    """
    declarations = source if source is not None else registry()
    definitions = DefinitionTypeRegistry(declarations.operation_arity)
    for entry in MANIFEST:
        definitions.add_source(entry.source_text(), bytes.fromhex(entry.identity))

    def resolve(digest: bytes) -> list:
        try:
            return definitions.reference_type(digest)
        except LookupError:
            return declarations.reference_type(digest)

    return resolve


@dataclass(frozen=True)
class CorpusEntry:
    """One seed definition: the §5.2 meta object, minus provenance.

    ``name_path`` and ``spec`` are exactly what a meta object carries, so the
    (spec-text, canonical-surface) pair a §8.4 few-shot prompt needs is read
    straight off this manifest rather than from a second, invented format.

    ``effect_free`` is the entry's declared position on §2.4: ``True`` means the
    definition's type mentions no ability row and no capability, so it cannot
    perform anything (a capability is unforgeable and enters a closed definition
    only through its type). Tranche 3 is the first tranche to set it ``False``.
    Like ``tier``, it is enforced in both directions — an ``effect_free`` entry
    must be pure and an effectful entry must actually carry effects — so the flag
    can never be used to quietly exempt a fixture from the purity test.
    """

    fixture: str
    name_path: str
    spec: str
    source: str
    identity: str
    tier: str
    deferred: str = ""
    effect_free: bool = True

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
        source="Unison (unisonweb/unison, MIT) Optional.isNone, instantiated at I64",
        identity="575ff2d3a57e5a4582a7640b6bcd5365d5e0898e27576e820b3a5fbdd39b01a3",
        tier="checked",
    ),
    CorpusEntry(
        fixture="maybe_get_or_else_i64.loom.sexpr",
        name_path="corpus/maybe/getOrElse",
        spec="The option's value, or the supplied default when it is empty.",
        source="Unison (unisonweb/unison, MIT) Optional.getOrElse, instantiated at I64",
        identity="2dc64240af4f0bf328f1572c9cd09bca3bed789d5a150a3a8d0c0825b4ad2a2a",
        tier="checked",
    ),
    CorpusEntry(
        fixture="maybe_map_i64.loom.sexpr",
        name_path="corpus/maybe/map",
        spec="Apply a function to the option's value, leaving an empty option empty.",
        source="Unison (unisonweb/unison, MIT) Optional.map, instantiated at I64 -> I64",
        identity="a4b7f01ca0cbe6e6fd3494feb556cb6b7c8c4453152e7797e201f1b5e5449cf4",
        tier="checked",
    ),
    CorpusEntry(
        fixture="maybe_map_poly.loom.sexpr",
        name_path="corpus/maybe/mapPoly",
        spec="Apply a function to the option's value, for any element types.",
        source="Unison (unisonweb/unison, MIT) Optional.map, kept generic (SPEC.md §3.1.3)",
        identity="0dba3946f35c4e5746427da984d883b8067eea3e5149e7a2a4da26c0d1d6f24a",
        tier="checked",
    ),
    CorpusEntry(
        fixture="bool_not.loom.sexpr",
        name_path="corpus/bool/not",
        spec="The opposite of the given boolean.",
        source="Unison (unisonweb/unison, MIT) Boolean.not",
        identity="162f818f22a2d041cb823d9a4e98c98d6102eee7de83519211452c348bb1be45",
        tier="checked",
    ),
    CorpusEntry(
        fixture="list_uncons_i64.loom.sexpr",
        name_path="corpus/list/uncons",
        spec="Split a list into its head and tail, or nothing when it is empty.",
        source="Unison (unisonweb/unison, MIT) List.uncons, instantiated at I64",
        identity="1aa47aec06e66f1f563d461eedcf951c9cdab11e7fa26d252536c97160798af5",
        tier="checked",
    ),
    CorpusEntry(
        fixture="list_fold_right_i64.loom.sexpr",
        name_path="corpus/list/foldRight",
        spec="Collapse a list from the right with a combining function and an initial value.",
        source="Unison (unisonweb/unison, MIT) List.foldRight, instantiated at I64",
        identity="2509a18eb5e81726042a2cef5cd5444955a71c9dce18221ff8a49d0f93c82893",
        tier="checked",
    ),
    # --- Tranche 2, continued: the remaining recursive list definitions. Every
    # fix below measures `(ref #List.size)` (the R4 assumed base) and takes no
    # `div`; `list/concat` and `list/flatMap` additionally `ref` `list/append`,
    # the corpus's first cross-definition dependency chain (docs/plans/
    # 2026-08-13-corpus-tranche-2.md).
    CorpusEntry(
        fixture="list_append_i64.loom.sexpr",
        name_path="corpus/list/append",
        spec="Concatenate two lists, the second following the first.",
        source="Unison (unisonweb/unison, MIT) List.++, instantiated at I64",
        identity="32f5d833f0b7c42ea8252e7ec8810657e9e9d132d395d30a7259e683bc31f791",
        tier="checked",
    ),
    CorpusEntry(
        fixture="list_reverse_i64.loom.sexpr",
        name_path="corpus/list/reverse",
        spec="Reverse a list's element order.",
        source="Unison (unisonweb/unison, MIT) List.reverse, instantiated at I64",
        identity="9d677953e4471fb4b1c80accfd4f2cb48d59b08073a9e431f74bd1f0020e249b",
        tier="checked",
    ),
    CorpusEntry(
        fixture="list_map_i64.loom.sexpr",
        name_path="corpus/list/map",
        spec="Apply a function to every element of a list, preserving its order.",
        source="Unison (unisonweb/unison, MIT) List.map, instantiated at I64 -> I64",
        identity="617903dc2f185adc90f658f482357c9961001882d693cab0c4701ae518e21ade",
        tier="checked",
    ),
    CorpusEntry(
        fixture="list_fold_left_i64.loom.sexpr",
        name_path="corpus/list/foldLeft",
        spec="Collapse a list from the left with a combining function and an initial accumulator.",
        source="Unison (unisonweb/unison, MIT) List.foldLeft, instantiated at I64",
        identity="7c880749df1f488a834cc9b2352d0d064dba904e2c7cfd83af762cee2d3b665f",
        tier="checked",
    ),
    CorpusEntry(
        fixture="list_concat_i64.loom.sexpr",
        name_path="corpus/list/concat",
        spec="Concatenate two lists by delegating to `append`.",
        source=(
            "Unison (unisonweb/unison, MIT) List.++, instantiated at I64 "
            "(second instantiation, composed via `ref` into corpus/list/append "
            "to exercise the manifest's first cross-definition reference)"
        ),
        identity="9bdf05836448d24d7c66f987cbf6de55e7a7bfa303c4636db9b259958c9d93a1",
        tier="checked",
    ),
    CorpusEntry(
        fixture="list_flat_map_i64.loom.sexpr",
        name_path="corpus/list/flatMap",
        spec="Apply a list-producing function to every element and concatenate the results.",
        source=(
            "Unison (unisonweb/unison, MIT) List.flatMap, instantiated at I64 "
            "-> I64, composed via `ref` into corpus/list/append for its Cons step"
        ),
        identity="72fe5503bbf99fd187a83b5fd5cca4f6df2c5747fcd0d934457e7c96f6f4e6ed",
        tier="checked",
    ),
    # --- Tranche 3: the effectful slice. Closed rows only (R2 drops Unison's
    # row polymorphism), §2.4 builtin abilities only, and every capability
    # arrives as a parameter because §2.4 makes `cap a` unforgeable in the
    # language. `clock/nowPair` is the only entry with a `ref`, into
    # `corpus/clock/now` above it (docs/plans/2026-08-13-corpus-tranche-3.md).
    CorpusEntry(
        fixture="clock_now.loom.sexpr",
        name_path="corpus/clock/now",
        spec="The current wall-clock time in Unix-epoch milliseconds.",
        source=(
            "Unison (unisonweb/unison, MIT) IO.systemTime, narrowed from the "
            "broad `{IO}` ability to §2.4's `clock` and taking the explicit "
            "`cap clock` parameter Unison has no counterpart for"
        ),
        identity="1d76cfea633059e7e0523b04b2a25f1bd7681266c2ad9c107fe63ed94b96aabe",
        tier="checked",
        effect_free=False,
    ),
    CorpusEntry(
        fixture="rand_bytes.loom.sexpr",
        name_path="corpus/rand/bytes",
        spec="Draw the requested number of random bytes.",
        source=(
            "Unison (unisonweb/unison, MIT) `Random` ability draw; no base "
            "definition returns a requested count of bytes, so the ability-draw "
            "shape rather than a named original is what is transpiled"
        ),
        identity="f403bb626c6758e31f4d6ffe69b657f210dd40ad1b972249788bfb4c6e4d6181",
        tier="checked",
        effect_free=False,
    ),
    CorpusEntry(
        fixture="clock_stamped.loom.sexpr",
        name_path="corpus/clock/stamped",
        spec="Run a clock-reading action and pair the time it started with its result.",
        source=(
            "Unison (unisonweb/unison, MIT) IO.systemTime used as a timing "
            "wrapper's prefix; the elapsed-time subtraction has no Loom "
            "arithmetic term (R2), so the start time is paired with the result"
        ),
        identity="1b34eac0d6170e358d640f3361f66fdf85f10605542755b4560bc527f6dc5fce",
        tier="checked",
        effect_free=False,
    ),
    CorpusEntry(
        fixture="rand_with_stub.loom.sexpr",
        name_path="corpus/rand/withStub",
        spec="Draw four random bytes under a local handler answering with a fixed stub.",
        source=(
            "Unison (unisonweb/unison, MIT) ability-handler idiom for `Random` "
            "(a handler supplying deterministic answers in place of the "
            "runtime's); no single base definition is the original, and "
            "generator state is dropped because Loom v0.1 has no arithmetic (R2)"
        ),
        identity="f0f11f45a58849efad599470a01968334bd98c8c9338bd463ceba51933204dc7",
        tier="checked",
        effect_free=False,
    ),
    CorpusEntry(
        fixture="clock_now_pair.loom.sexpr",
        name_path="corpus/clock/nowPair",
        spec="Read the wall clock twice, pairing the two readings.",
        source=(
            "Unison (unisonweb/unison, MIT) IO.systemTime called twice in one "
            "`{IO}` block; the ambient ability becomes an explicit `cap clock` "
            "threaded by hand into each call of corpus/clock/now"
        ),
        identity="39256387522338400d5fd3181c328882c76356d9c50ca40465be88b219c0d642",
        tier="checked",
        effect_free=False,
    ),
    CorpusEntry(
        fixture="sample_now_and_bytes.loom.sexpr",
        name_path="corpus/sample/nowAndBytes",
        spec="Pair the current wall-clock time with eight random bytes.",
        source=(
            "Unison (unisonweb/unison, MIT) `{IO}` code reading the clock and "
            "the random source in one block; §2.4 splits that single Unison "
            "ability in two, so the row is the closed two-ability row rand+clock"
        ),
        identity="8671c61e79cc536d0a4e00ecad9c838547797cdfa5342a876e00285159717105",
        tier="checked",
        effect_free=False,
    ),
    CorpusEntry(
        fixture="rand_resample.loom.sexpr",
        name_path="corpus/rand/resample",
        spec="Draw random bytes under a handler that resumes twice and recombines both outcomes.",
        source=(
            "Unison (unisonweb/unison, MIT) nondeterminism-handler idiom (a "
            "handler invoking its continuation more than once); no base "
            "definition is the original, so the multi-shot shape rather than a "
            "named function is what is transpiled"
        ),
        identity="13926e2d25d36dc321a19973fc64a11255751426863707efa2ed164e9a794db0",
        tier="checked",
        effect_free=False,
    ),
)


def few_shot_pairs():
    """(spec-text, canonical-surface) pairs for a §8.4 few-shot prompt.

    Emission order follows the manifest, which is dependency order: every
    declaration a definition names is registered before it, and no entry refers
    to a later one. The store has no forward references, and neither does this.
    """
    return tuple((entry.spec, entry.source_text().rstrip("\n")) for entry in MANIFEST)
