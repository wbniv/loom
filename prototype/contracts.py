"""Versioned validation contracts for the prototype's layers.

A *contract* is the externally observable behaviour of one validation layer:
which inputs it accepts, which it rejects, and — where the layer produces them —
the canonical bytes and hashes it emits. The version number exists so that a
future non-Python implementation can claim conformance to, say, "scope contract
1.0" and be held to it by differential testing against this Python reference,
rather than against a moving target with no name.

Granularity is one contract per layer, not one for the toolchain, because a
re-implementation lands layer by layer and a single number would make the
intermediate states unnameable and the conformance claim all-or-nothing. The
four layers named by `TODO.md`'s production-language Watch trigger are recorded
in `WATCH_TRIGGER_LAYERS`; the other three are here because they have the same
two properties — a public accept/reject decision and pinned canonical output.

Versions are `MAJOR.MINOR`; there is no patch level, because a patch could only
ever record a change this contract does not cover.

Covered by a version (see `COVERED`): the acceptance set, the fact of rejection
and the declared error class, canonical byte outputs and derived hashes, the
injected-resolver call conventions, and the public entry-point signatures.

Not covered (see `NOT_COVERED`): error message text and the path strings inside
errors. Diagnostics must stay free to improve without a version cost, and a
conforming implementation is not required to reproduce them byte for byte.

Bump rules — decided by asking what happens to an implementation that conformed
to the previous version:

  MAJOR  an input the previous version accepted is now rejected; canonical
         bytes, an identity, or a pinned hash moved for any previously accepted
         input; a resolver convention or entry-point signature changed
         incompatibly. A MAJOR bump resets MINOR to 0. A silent mis-acceptance
         that is now correctly rejected is MAJOR too — the old behaviour was in
         the acceptance set whether or not it was intended.
  MINOR  an input the previous version rejected *loudly* (with that layer's
         declared error class) is now accepted, with nothing previously accepted
         changed; or a new public entry point, or a new optional parameter whose
         default preserves behaviour.
  none   error text, error paths, refactors, performance, tests, docs, and new
         fixtures that need no layer change.

Every contract is seeded at 1.0 as of the commit that introduced this module.
Historical versions are deliberately *not* reconstructed: the rules did not
exist while that history happened, so a reconstructed number would be a
fabrication dressed as a record.

`prototype/CONTRACTS.md` is the narrative form of all of the above, and
`test_contracts.py` pins every version and checks this module against the code
it describes. Changing a version here requires editing that test, which is the
point at which the change gets checked against the bump rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

COVERED = (
    "the acceptance set of the listed entry points",
    "the fact of rejection, and the declared error class it is reported as",
    "canonical byte outputs and the hashes derived from them",
    "the injected-resolver call conventions",
    "the public entry-point names and signatures",
)

NOT_COVERED = (
    "error message text",
    "the path strings carried inside errors",
    "module-private structure, traversal order, performance, and memory",
    "test organisation and documentation",
    "fixtures and corpus entries that need no layer change",
)

#: The four layers `TODO.md`'s production-language Watch trigger (a) names.
WATCH_TRIGGER_LAYERS = ("parser", "scope", "references", "typecheck")


@dataclass(frozen=True)
class Contract:
    """One validation layer's versioned external behaviour."""

    name: str
    version: tuple[int, int]
    module: str
    summary: str
    entry_points: tuple[str, ...]
    resolvers: tuple[str, ...] = ()
    pinned: tuple[str, ...] = field(default=())

    @property
    def major(self) -> int:
        return self.version[0]

    @property
    def minor(self) -> int:
        return self.version[1]

    @property
    def version_string(self) -> str:
        return f"{self.version[0]}.{self.version[1]}"

    def __str__(self) -> str:
        return f"{self.name} contract {self.version_string}"


_CONTRACTS = (
    Contract(
        name="parser",
        version=(1, 0),
        module="transcode",
        summary=(
            "Canonical S-expression surface acceptance, the surface/IR inverse pair, "
            "the canonical CBOR definition object, and definition identity."
        ),
        entry_points=(
            "transcode.parse_source",
            "transcode.def_to_ir",
            "transcode.def_to_surface",
            "transcode.type_to_ir",
            "transcode.type_to_surface",
            "transcode.term_to_ir",
            "transcode.term_to_surface",
            "transcode.def_object_bytes",
            "transcode.identity",
            "transcode.transcode_source",
        ),
        pinned=(
            "transcode.TERM_TAG",
            "transcode.TYPE_TAG",
            "transcode.LIT_KIND",
            "transcode.BASE_CODE",
            "examples/01_id.loom.sexpr",
            "loom.gbnf",
        ),
    ),
    Contract(
        name="scope",
        version=(1, 0),
        module="scope",
        summary=(
            "Term and type de Bruijn index validity, binder depth, handler operation "
            "resolution, and the `forall` prefix of a definition type."
        ),
        entry_points=(
            "scope.check_type",
            "scope.check_term",
            "scope.check_definition",
            "scope.forall_prefix",
            "scope.validate_source",
        ),
        resolvers=("scope.AbilityArityResolver",),
        pinned=("scope.ScopeError",),
    ),
    Contract(
        name="references",
        version=(1, 0),
        module="references",
        summary=(
            "Resolution of nominal data and ability hashes against a registry, plus "
            "explicit constructor and operation bounds and arities."
        ),
        entry_points=(
            "references.check_type_references",
            "references.check_term_references",
            "references.check_definition_references",
            "references.validate_source",
        ),
        pinned=("prelude.HASHES", "corpus_registry.EXTERN_HASHES"),
    ),
    Contract(
        name="typecheck",
        version=(1, 0),
        module="typecheck",
        summary=(
            "The partial bidirectional checker: nominal matches, effects and handlers, "
            "`if`, `fix`/`ref`, and first-order `forall` instantiation."
        ),
        entry_points=(
            "typecheck.MatchChecker",
            "typecheck.instantiate_type",
            "typecheck.constructor_fields",
            "typecheck.validate_source",
        ),
        resolvers=("typecheck.ReferenceTypeResolver",),
        pinned=("corpus_registry.MANIFEST",),
    ),
    Contract(
        name="declarations",
        version=(1, 0),
        module="declarations",
        summary=(
            "Validation, canonical encoding, and hashing of data/ability declaration "
            "and extern definition objects, and the registry that holds them."
        ),
        entry_points=(
            "declarations.check_declaration_type",
            "declarations.check_data_declaration",
            "declarations.check_ability_declaration",
            "declarations.check_extern_type",
            "declarations.check_extern_definition",
            "declarations.declaration_bytes",
            "declarations.declaration_hash",
            "declarations.DeclarationRegistry",
        ),
        pinned=("prelude.HASHES", "corpus_registry.EXTERN_HASHES"),
    ),
    Contract(
        name="refinements",
        version=(1, 0),
        module="refinements",
        summary=(
            "Translation of one SPEC.md §3.2.1 verification condition into one "
            "canonical SMT-LIB script, and refusal of everything outside the "
            "decidable fragment."
        ),
        entry_points=(
            "refinements.erase_type",
            "refinements.obligation_script",
            "refinements.subtype_script",
            "refinements.check_translatable",
            "refinements.script_hash",
        ),
        resolvers=(
            "refinements.obligation_script(signatures=)",
            "refinements.obligation_script(interpretations=)",
        ),
        pinned=(
            "refinements.BASE_SORT",
            "refinements.INTERPRETED_SYMBOLS",
            "refinements.TERM_FRAGMENT_TAGS",
            "corpus_registry.MANIFEST",
        ),
    ),
    Contract(
        name="policies",
        version=(1, 0),
        module="policies",
        summary=(
            "Namespace policy object validation and canonical hashing, obligation-id "
            "decomposition, evidence satisfaction (E ⊒ R), and policy domination."
        ),
        entry_points=(
            "policies.decompose_obligation_id",
            "policies.validate_point",
            "policies.at_least",
            "policies.satisfies",
            "policies.validate_selector",
            "policies.selector_matches",
            "policies.matching_rules",
            "policies.validate_policy",
            "policies.policy_bytes",
            "policies.policy_hash",
            "policies.dominates",
        ),
        pinned=(
            "policies.OBLIGATION_KINDS",
            "policies.POLICY_KEYS",
            "policies.DEFAULT_POLICY_HASH",
        ),
    ),
)

CONTRACTS = MappingProxyType({item.name: item for item in _CONTRACTS})

VERSIONS = MappingProxyType({name: item.version_string for name, item in CONTRACTS.items()})


def contract(name: str) -> Contract:
    """Return the named contract, or raise `KeyError` with the known names."""
    try:
        return CONTRACTS[name]
    except KeyError:
        known = ", ".join(sorted(CONTRACTS))
        raise KeyError(f"unknown contract {name!r}; known contracts: {known}") from None


def version(name: str) -> str:
    """Return the named contract's version as `MAJOR.MINOR`."""
    return contract(name).version_string


def summary_lines() -> tuple[str, ...]:
    """One `name contract MAJOR.MINOR` line per contract, in declaration order."""
    return tuple(str(item) for item in _CONTRACTS)


if __name__ == "__main__":
    for line in summary_lines():
        print(line)
