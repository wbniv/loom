"""Bootstrap-corpus data declarations and the seed-set manifest.

The corpus seeds §13 open problem 1 (prior starvation). Its definitions are
hand-transpiled from the base library of the MIT-licensed unisonweb/unison
repository — structural eliminators (tranche 1), their recursive companions
(tranche 2), and ability code against §2.4's builtins (tranche 3) — plus, in
tranche 4, refinement-carrying definitions from the Apache-2.0 FStarLang/FStar
standard library, transpiled type-first; see
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

import obligations
import prelude
import refinements
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
#: definitions tranche 2 needs, plus the four boolean/comparison externs that
#: give §3.2.1's `and or not <=` interpreted symbols something to interpret
#: (docs/plans/2026-08-13-boolean-base-externs.md). They are host primitives,
#: not a WASM component, so their pinned artifact is the host adapter's
#: published ABI identity, derived reproducibly under the corpus prefix exactly
#: like a nominal key. One artifact, nine ABI selectors.
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


def _binary_bool(result):
    """`Bool -> Bool -{}> result`, fully curried with empty rows throughout."""
    return [2, _BOOL, [], [2, _BOOL, [], result]]


def _unary_bool(result):
    """`Bool -{}> result`, curried with an empty row."""
    return [2, _BOOL, [], result]


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
    # I64.le  : I64 -> I64 -> Bool       (§3.2.1 interpretation `<=`)
    "I64.le": [7, _binary(_BOOL), HOST_ARTIFACT, "i64.le"],
    # Bool.and : Bool -> Bool -> Bool    (§3.2.1 interpretation `and`)
    "Bool.and": [7, _binary_bool(_BOOL), HOST_ARTIFACT, "bool.and"],
    # Bool.or  : Bool -> Bool -> Bool    (§3.2.1 interpretation `or`)
    "Bool.or": [7, _binary_bool(_BOOL), HOST_ARTIFACT, "bool.or"],
    # Bool.not : Bool -> Bool            (§3.2.1 interpretation `not`)
    "Bool.not": [7, _unary_bool(_BOOL), HOST_ARTIFACT, "bool.not"],
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
    EXTERN_HASHES["I64.le"]: "<=",
    EXTERN_HASHES["Bool.and"]: "and",
    EXTERN_HASHES["Bool.or"]: "or",
    EXTERN_HASHES["Bool.not"]: "not",
})

#: Reference signatures the §3.2.1 translator needs to uncurry a `ref` occurring
#: inside a refinement predicate. Policy like `SMT_INTERPRETATION`, never part of
#: an object. Only the assumed base appears: a tranche-4 predicate may name an
#: extern and nothing else, because a corpus *definition* has a body a later
#: version could unfold and v0.1 deliberately never unfolds one.
SMT_SIGNATURES = MappingProxyType({digest: _EXTERNS[name][1] for name, digest in EXTERN_HASHES.items()})


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


#: A pinned obligation's raw solver answer on its canonical script. This is an
#: observation and stays one: the optional solver run reproduces it, and no
#: interpretation of it is allowed to overwrite it.
#:
#: ``unsat`` — the refutation fails, so the goal is valid under the hypothesis.
#: ``sat``   — the refutation succeeds: the script has a model. Whether that
#:             model *refutes the obligation* is a separate question §3.2.1
#:             answers with exactness, and `outcome` below records the answer.
VERDICTS = ("unsat", "sat")

#: The §3.2.1 three-way result an obligation reaches, derived from `verdict` and
#: the emitted script's exactness by `obligations.outcome`. Pinned as manifest
#: data and checked against a fresh derivation, the way `tier` and `effect_free`
#: are — so the manifest can neither invent an outcome the rule does not produce
#: nor silence one it does.
OUTCOMES = obligations.OUTCOMES


@dataclass(frozen=True)
class Obligation:
    """One §3.2.1 verification condition: `{x:T|weaker} <: {x:T|stronger}`.

    §3.2.1 names exactly one v0.1 producer of verification conditions —
    refinement subtyping — so this is the whole obligation vocabulary the corpus
    can pin today. `base` is the refined type `T` (index 0, the refined value);
    `outer_context` is §3.2.1's "any surrounding term context appended to `Γ`
    after the refined value", which is how an `ensures` claim reaches the
    definition's own arguments without a dependent arrow (§2.3.1).

    `weaker` is the predicate the corpus records as *established* at that point
    and `stronger` is the one the definition's type *claims*. Deriving `weaker`
    from a function body is §3.2.1's stated future work; until it exists the
    manifest authors it by hand and says so — that is the honest boundary of
    this tranche, not a gap papered over.

    `script_hash` pins the SHA-256 of the canonical script, which is the memo
    ledger's payload key (§6.4). `verdict` pins the raw answer a solver returns
    for it and `outcome` pins what §3.2.1 makes of that answer.

    `producer` says which verification-condition producer built this triple.
    Only `subtype` is one §3.2.1 specifies; `authored` marks the hand-written
    body summaries above, and it is what stops a `sat` over one of them from
    refuting a definition that is in fact correct. The field is not taken on
    trust — `test_corpus` derives it from the fixture's own declared type.
    """

    name: str
    base: list
    weaker: list
    stronger: list
    script_hash: str
    verdict: str
    outcome: str
    producer: str
    note: str = ""
    outer_context: tuple = ()

    def condition(self) -> obligations.VerificationCondition:
        """This obligation as a §3.2.1 `(Γ, H, g)` carrying its producer."""
        if self.producer == obligations.PRODUCER_SUBTYPING:
            return obligations.subtyping_condition(
                self.base, self.weaker, self.stronger, self.outer_context)
        return obligations.authored_condition(
            [self.base, *self.outer_context], [self.weaker], self.stronger)

    def emit(self, declarations: DeclarationRegistry | None = None) -> obligations.EmittedObligation:
        """Run this obligation through the emission layer (§3.2.1, §6.2)."""
        return obligations.emit_condition(
            self.name,
            self.condition(),
            declarations if declarations is not None else registry(),
            SMT_SIGNATURES,
            SMT_INTERPRETATION,
        )

    def script(self, declarations: DeclarationRegistry | None = None) -> str:
        """The canonical SMT-LIB script for this verification condition."""
        return refinements.subtype_script(
            copy.deepcopy(self.base),
            copy.deepcopy(self.weaker),
            copy.deepcopy(self.stronger),
            declarations if declarations is not None else registry(),
            SMT_SIGNATURES,
            SMT_INTERPRETATION,
            copy.deepcopy(self.outer_context),
        )


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

    ``obligations`` is the entry's declared position on §3.2/§6.2: the §3.2.1
    verification conditions its `ensures`-style claims produce, each with its
    canonical script's SHA-256 pinned. Tranche 4 is the first tranche to set it.
    Like ``tier`` and ``effect_free`` it is enforced in both directions — an
    entry whose *type* contains a `refine` node must carry at least one
    obligation, and an entry carrying one must have a `refine` in its type — so
    a refinement can never enter the corpus without its obligation coming with
    it, and an obligation can never be attached to a fixture that does not claim
    one.
    """

    fixture: str
    name_path: str
    spec: str
    source: str
    identity: str
    tier: str
    deferred: str = ""
    effect_free: bool = True
    obligations: tuple = ()

    @property
    def path(self) -> Path:
        return CORPUS_DIR / self.fixture

    def source_text(self) -> str:
        return self.path.read_text(encoding="utf-8")


def _app(head, *arguments):
    """A saturated `app` spine over a stored reference (§3.2.1's term fragment)."""
    for argument in arguments:
        head = [4, head, argument]
    return head


def _i64(value):
    return [2, 2, value]


_LT = EXTERN_HASHES["I64.lt"]
_SUB = EXTERN_HASHES["I64.sub"]
_EQ = EXTERN_HASHES["I64.eq"]
_SIZE = EXTERN_HASHES["List.size"]

#: `Prims.nat = i:int{i >= 0}` and `Prims.pos = i:int{i > 0}` (F* `ulib/Prims.fst`),
#: over `I64` and written with `<` because the assumed base supplies no `<=`
#: (R5's five externs interpret `+ - = <` and nothing else). `-1 < v` and `0 <= v`
#: are the same predicate over SMT-LIB `Int`, which is the sort §3.2.1 gives I64.
_NAT = _app([1, _LT], _i64(-1), [0, 0])
_POS = _app([1, _LT], _i64(0), [0, 0])
_R_NAT = [3, _I64, _NAT]
_R_POS = [3, _I64, _POS]
_LIST_I64 = [1, HASHES["List"], [_I64]]
_LIST_NAT = [1, HASHES["List"], [_R_NAT]]

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
    # --- Tranche 4: the refinement slice. Sourced from the Apache-2.0
    # FStarLang/FStar standard library and transpiled *type*-first: the
    # refinement is what is being imported, so where the Loom encoding cannot
    # keep an F* type whole, the manifest records which axis was weakened
    # (docs/plans/2026-08-13-corpus-tranche-4.md). Refinement predicates are
    # non-dependent — a codomain refinement may name only the refined value,
    # because naming the argument is a dependent arrow and §2.3.1 has none — so
    # every F* postcondition relating a result to an input is weakened here.
    # All six carry `refine` types. The first three used to be `structural`:
    # typecheck.py implemented no §3.3 refinement subtyping, so a term only
    # ever checked against a `refine` type by structural equality, and each
    # one's body synthesizes a type that differs from its declared codomain
    # by exactly a refinement predicate. The
    # [refinement-subsumption plan](../docs/plans/2026-08-13-refinement-subsumption.md)
    # closes that: `typecheck.validate_source(..., obligations=sink)` now
    # admits the mismatch and emits a subtyping obligation for it instead of
    # rejecting, so all six reach `checked` — opt-in, since a caller with no
    # sink still gets exactly today's structural-equality rejection.
    # `test_corpus.CorpusFixtureTest` supplies the sink unconditionally for
    # `checked` entries, which is harmless for the three that needed no
    # subsumption to begin with.
    CorpusEntry(
        fixture="math_abs_nat.loom.sexpr",
        name_path="corpus/math/abs",
        spec="The absolute value of an integer, which is never negative.",
        source=(
            "F* (FStarLang/FStar, Apache-2.0) FStar.Math.Lib.abs, weakened: F*'s "
            "codomain `y:int{(x >= 0 ==> y = x) /\\ (x < 0 ==> y = -x)}` names the "
            "argument `x` and is therefore a dependent arrow (§2.3.1 has none), so "
            "only the nonnegativity half survives; `int` monomorphizes to I64"
        ),
        identity="722a6900553dbe78a5fea5116255d5519deab85db50049222cfbb9f38c79b093",
        tier="checked",
        obligations=(
            Obligation(
                name="ensures.nonnegative",
                base=_I64,
                outer_context=(_I64,),
                weaker=_app([1, _EQ], [0, 0],
                            [12, _app([1, _LT], [0, 1], _i64(0)),
                             _app([1, _SUB], _i64(0), [0, 1]), [0, 1]]),
                stronger=_NAT,
                script_hash="3f2827e45b57868083f5281a54e7527086fce2ed7fd1e2b562fb61c602c6b883",
                verdict="unsat",
                outcome="proved",
                producer="authored",
                note=(
                    "Valid in the encoding, and a live instance of §3.2.1's stated "
                    "`Int` fidelity limit: at x = -2^63 the real `I64.sub 0 x` wraps "
                    "back to a negative value, but the domain axiom on the result "
                    "makes that model infeasible rather than modelling the wrap. The "
                    "A3 this earns is A3 relative to `I64.sub`'s A0 extern assumption "
                    "(§5.1.3), and that assumption is where the overflow hides. The "
                    "script is inexact for exactly that reason (it uses `-`), which "
                    "changes nothing on the `unsat` side but records the A0-relativity "
                    "as a derived fact rather than a comment. This remains the *only* "
                    "sound argument for the definition: the checker's own automatic "
                    "subsumption at each `if` branch (`definition.term.body.then` and "
                    "`.else`) is admitted at typing time regardless, but its emitted "
                    "condition uses `weaker = true` (§3.2.1: a bare `I64` is "
                    "`{v|true}`) because neither branch's *synthesized* type carries "
                    "the `if`'s own condition as a hypothesis — that condition is "
                    "translation-exact and a live solver refutes it. Typing is "
                    "unaffected (§3.2.1's R1: typing never consults the verdict), but "
                    "it is why this fixture still needs the hand-authored obligation "
                    "above to reach A3 rather than the checker-emitted one."
                ),
            ),
        ),
    ),
    CorpusEntry(
        fixture="list_length_nat.loom.sexpr",
        name_path="corpus/list/lengthNat",
        spec="A list's length, which is never negative.",
        source=(
            "F* (FStarLang/FStar, Apache-2.0) FStar.List.Tot.Base.length : "
            "list 'a -> Tot nat, monomorphized at 'a = int and delegating to the "
            "assumed-base `List.size` extern rather than recursing, because R4's "
            "measure primitive is the only list length the corpus has"
        ),
        identity="7ebd41f6467f08bc3876f6a4d137198115b6dd954ba68523440f3f9445cbd636",
        tier="checked",
        obligations=(
            Obligation(
                name="ensures.nonnegative",
                base=_I64,
                outer_context=(_LIST_I64,),
                weaker=_app([1, _EQ], [0, 0], _app([1, _SIZE], [0, 1])),
                stronger=_NAT,
                script_hash="253432acedceb5a09769bb82edff1c73f0f8100a213b7a940107493b1cfbe4c5",
                verdict="sat",
                outcome="undischarged",
                producer="authored",
                note=(
                    "`List.size` is deliberately absent from SMT_INTERPRETATION, so it "
                    "translates to an uninterpreted function about which the solver "
                    "learns congruence and nothing else — no lower bound. F* proves "
                    "`length` nonnegative by induction over the list; the v0.1 "
                    "fragment is quantifier-free and has no induction, so the routes "
                    "are an A0 range assumption on the extern or body-VC generation. "
                    "The `declare-fun` is also what makes the script inexact, so the "
                    "model is an artifact and the outcome is `undischarged`, not a "
                    "refutation of a true claim. As with corpus/math/abs, the "
                    "checker's own automatic subsumption at `definition.term.body` "
                    "admits the definition regardless (weaker = true), but that "
                    "checker-emitted condition is a different, weaker claim than the "
                    "one pinned here — this hand-authored obligation is still the "
                    "argument that carries the actual A3 evidence."
                ),
            ),
        ),
    ),
    CorpusEntry(
        fixture="nat_widen_pos.loom.sexpr",
        name_path="corpus/nat/widenPos",
        spec="A positive integer viewed as a nonnegative one.",
        source=(
            "F* (FStarLang/FStar, Apache-2.0) Prims.pos and Prims.nat "
            "(`ulib/Prims.fst`): F* discharges `pos <: nat` implicitly at every use "
            "site, and this fixture is that coercion written out as a definition"
        ),
        identity="d9de68ecf5f6203a5b510e60183904138f5d4b71f60b636616cba82417e3b46d",
        tier="checked",
        obligations=(
            Obligation(
                name="subtype.pos-nat",
                base=_I64,
                weaker=_POS,
                stronger=_NAT,
                script_hash="0aee355cf7a5bdffb9ae32b9c859203e96140431c978d21b0572d3f1a9cf00c1",
                verdict="unsat",
                outcome="proved",
                producer="subtype",
                note=(
                    "The tranche's flagship: the one obligation whose discharge turns "
                    "its own fixture from `structural` into `checked`. It is also the "
                    "corpus's only *exact* verification condition (the one it shares "
                    "with corpus/nat/applyPos) — generated by §3.2.1's one specified "
                    "producer and translated with no uninterpreted symbol, no opaque "
                    "sort, no erasure, and no arithmetic — so a `sat` here would have "
                    "been a real refutation. This pin was hand-authored before the "
                    "refinement-subsumption plan; it is now also exactly what "
                    "`typecheck.py` emits at its one subsumption site "
                    "(`definition.term.body`, the fixture's whole body being `(var 0)` "
                    "checked at `pos` against the declared `nat` codomain) — same "
                    "base, same weaker/stronger predicates, same script, same hash. "
                    "The pin moved from authored to derived without moving a byte."
                ),
            ),
        ),
    ),
    CorpusEntry(
        fixture="list_cons_nat.loom.sexpr",
        name_path="corpus/list/consNat",
        spec="Prepend a nonnegative integer to a list of nonnegative integers.",
        source=(
            "F* (FStarLang/FStar, Apache-2.0) FStar.List.Tot.Base.list_refb — its "
            "`Cons` step `hd :: list_refb #a #p tl`, which is where `list (x:a{p x})` "
            "appears in the F* standard library — monomorphized at a = int and "
            "p = (fun x -> x >= 0); the recursion and the `for_all p l` precondition "
            "are dropped, the recursion because the assumed-base measure "
            "`List.size : List I64 -> I64` does not apply to `List {n | -1 < n}`"
        ),
        identity="77c735fb26b542c3288ecb6dda4bca9f337c20bab57aa02aa057895d132e0c9f",
        tier="checked",
        obligations=(
            Obligation(
                name="ensures.head-nonnegative",
                base=_LIST_NAT,
                weaker=[2, 1, True],
                stronger=[7, [0, 0], [[0, 0, [2, 1, True]],
                                      [1, 2, _app([1, _LT], _i64(-1), [0, 1])]]],
                script_hash="067345e1c37280e8047dfb020e7f5086a7bcd19bbda18406ba4a7b2f92ff30db",
                verdict="sat",
                outcome="undischarged",
                producer="authored",
                note=(
                    "The element refinement is erased: §3.2.1 refinement-erases a type "
                    "in sort position 'recursively, including inside data type "
                    "arguments', so `List {n | -1 < n}` and `List I64` are the *same* "
                    "SMT-LIB sort and the element predicate contributes no hypothesis. "
                    "Nothing inside the fragment recovers it — and stating the "
                    "invariant for a whole list would need a quantifier the fragment "
                    "does not have. That erasure is one of §3.2.1's exactness "
                    "conditions, and the `match` additionally binds an `Int`-sorted "
                    "field the domain axiom does not reach, so the model is doubly an "
                    "artifact and the outcome is `undischarged`."
                ),
            ),
        ),
    ),
    CorpusEntry(
        fixture="nat_apply_pos.loom.sexpr",
        name_path="corpus/nat/applyPos",
        spec="Apply a nonnegative-to-positive function to a nonnegative integer.",
        source=(
            "F* (FStarLang/FStar, Apache-2.0) FStar.List.Tot.Base.map : "
            "('a -> Tot 'b) -> list 'a -> Tot (list 'b), instantiated at 'a = nat and "
            "'b = pos and reduced to its element-application step; the list recursion "
            "is dropped for the same reason as corpus/list/consNat"
        ),
        identity="48e49ab0d1ae05af9f075a14f5af944cc267fa88095f0e8fbdb07bbaedd92ff8",
        tier="checked",
        obligations=(
            Obligation(
                name="subtype.argument-pos-nat",
                base=_I64,
                weaker=_POS,
                stronger=_NAT,
                script_hash="0aee355cf7a5bdffb9ae32b9c859203e96140431c978d21b0572d3f1a9cf00c1",
                verdict="unsat",
                outcome="proved",
                producer="subtype",
                note=(
                    "Deliberately the same verification condition as "
                    "corpus/nat/widenPos, arrived at from the other side — there it is "
                    "a codomain widening, here it is the contravariant check a caller "
                    "passing a `pos` into this definition's `nat` domain owes. §3.2.1: "
                    "'the obligation's name never enters the script, so two "
                    "differently named obligations with the same verification "
                    "condition share one memo-ledger row (§6.4)'. Same pinned hash."
                ),
            ),
        ),
    ),
    CorpusEntry(
        fixture="nat_select.loom.sexpr",
        name_path="corpus/nat/select",
        spec="Choose between two nonnegative integers on a boolean.",
        source=(
            "F* (FStarLang/FStar, Apache-2.0) FStar.Math.Lib.max, weakened twice: its "
            "value-pinning codomain is dependent (§2.3.1) and only nonnegativity "
            "survives, and its own `x >= y` test is lifted to a Bool parameter "
            "because comparing two `nat`s needs `{x:T|φ} <: T` to reach `I64.lt`"
        ),
        identity="4300a5090d354a1ad4dac0ce1a3ff1e96af401c3fca2a6d5c0e685bc5dfdaca4",
        tier="checked",
        obligations=(
            Obligation(
                name="ensures.nonnegative",
                base=_I64,
                outer_context=(_BOOL, _I64, _I64),
                weaker=_app([1, _EQ], [0, 0], [12, [0, 1], [0, 2], [0, 3]]),
                stronger=_NAT,
                script_hash="952812314f7eb1da073261e40ec289e7a0a8b8d3a6afef61073e596eb4bbaa08",
                verdict="sat",
                outcome="undischarged",
                producer="authored",
                note=(
                    "The one obligation in the corpus whose script is *translation*-"
                    "exact and still does not refute. It uses only `=`, `ite`, and `<` "
                    "over `Int` context variables the domain axiom bounds: no "
                    "uninterpreted function, no opaque sort, no datatype, and — read "
                    "the Γ above — nothing for the translator to erase, because "
                    "`outer_context` already spells the two branch arguments `I64`. "
                    "The definition's declared type spells them "
                    "`{n | -1 < n}`. The premises were therefore dropped when this "
                    "verification condition was *authored*, one stage before §3.2.1's "
                    "erasure would have acted, so the countermodel (b true, "
                    "x2 = x0 = -5) is a real valuation of the VC and not of the "
                    "definition. That is what `producer='authored'` is for. Carrying "
                    "the premises needs a multi-hypothesis VC: `and` in the assumed "
                    "base is one half, body-VC generation the other."
                ),
            ),
        ),
    ),
)


def few_shot_pairs():
    """(spec-text, canonical-surface) pairs for a §8.4 few-shot prompt.

    Emission order follows the manifest, which is dependency order: every
    declaration a definition names is registered before it, and no entry refers
    to a later one. The store has no forward references, and neither does this.
    """
    return tuple((entry.spec, entry.source_text().rstrip("\n")) for entry in MANIFEST)
