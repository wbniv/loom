"""Which entry points are captured, and what each one's record carries.

The list below is `contracts.py`'s `entry_points` minus the things that cannot
be a differential case: the two classes that are constructed rather than called
(`MatchChecker`, `DeclarationRegistry` — `DeclarationRegistry.add` is captured
instead, because *that* is where a declaration is accepted or refused).

Three per-entry-point knobs, and no others:

``env``    the parameter holding a `DeclarationRegistry`. It is lifted out of
           the input into a shared environment document, because a registry is
           large, is shared by thousands of cases, and is the same object for
           all of them.
``trace``  parameters holding an injected resolver. The resolver is wrapped and
           every call it receives during the case is recorded, so a consumer can
           replay the case against a table instead of needing the closure —
           `CONTRACTS.md` makes the resolver convention, *including* its `None`
           and raising cases, part of the contract, so the trace is contract
           surface and belongs in the input key.
``drop``   parameters that are diagnostics only. `path` is explicitly listed by
           `CONTRACTS.md` as not covered by any version, so it must not enter a
           case key or two spellings of the same input would become two cases.

`EMIT` says what a layer's gate compares beyond the accept/reject bit. A missing
entry means the gate is the verdict and the error class alone — which is exactly
what the migration table says for `scope`, `references`, and `typecheck`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntryPoint:
    layer: str
    module: str
    attribute: str
    env: str | None = None
    trace: tuple[str, ...] = ()
    drop: tuple[str, ...] = ("path",)
    #: Name of the record's `extra.result` field, when the return value is part
    #: of the gate (the policy predicates, `forall_prefix`, `erase_type`).
    result: str | None = None

    @property
    def name(self) -> str:
        return f"{self.module}.{self.attribute}"


ENTRY_POINTS: tuple[EntryPoint, ...] = (
    # ── 1. parser ───────────────────────────────────────────────────────
    # `parse_source` is the whole gate: every other parser entry point is
    # either reached through it or is a pure function of its result, and the
    # recorder derives the canonical bytes, the identity, and the rendered
    # surface from the accepted IR rather than needing a separate case.
    EntryPoint("parser", "transcode", "parse_source"),
    EntryPoint("parser", "transcode", "def_to_ir", result="ir"),
    EntryPoint("parser", "transcode", "type_to_ir", result="ir"),
    EntryPoint("parser", "transcode", "term_to_ir", result="ir"),
    EntryPoint("parser", "transcode", "def_to_surface", result="surface"),
    EntryPoint("parser", "transcode", "type_to_surface", result="surface"),
    EntryPoint("parser", "transcode", "term_to_surface", result="surface"),
    EntryPoint("parser", "transcode", "def_object_bytes"),
    EntryPoint("parser", "transcode", "identity"),
    EntryPoint("parser", "transcode", "transcode_source"),
    # ── 2. declarations ─────────────────────────────────────────────────
    EntryPoint("declarations", "declarations", "check_declaration_type"),
    EntryPoint("declarations", "declarations", "check_data_declaration"),
    EntryPoint("declarations", "declarations", "check_ability_declaration"),
    EntryPoint("declarations", "declarations", "check_extern_type"),
    EntryPoint("declarations", "declarations", "check_extern_definition"),
    EntryPoint("declarations", "declarations", "declaration_bytes"),
    EntryPoint("declarations", "declarations", "declaration_hash"),
    # ── 3. scope ────────────────────────────────────────────────────────
    EntryPoint("scope", "scope", "check_type", trace=("ability_arity",)),
    EntryPoint("scope", "scope", "check_term", trace=("ability_arity",)),
    EntryPoint("scope", "scope", "check_definition", trace=("ability_arity",)),
    EntryPoint("scope", "scope", "forall_prefix", result="prefix"),
    EntryPoint("scope", "scope", "validate_source", trace=("ability_arity",)),
    # ── 4. references ───────────────────────────────────────────────────
    EntryPoint("references", "references", "check_type_references", env="registry"),
    EntryPoint("references", "references", "check_term_references", env="registry"),
    EntryPoint("references", "references", "check_definition_references", env="registry"),
    EntryPoint("references", "references", "validate_source", env="registry"),
    # ── 5. typecheck ────────────────────────────────────────────────────
    EntryPoint("typecheck", "typecheck", "instantiate_type", result="type"),
    EntryPoint("typecheck", "typecheck", "constructor_fields", env="registry", result="fields"),
    EntryPoint("typecheck", "typecheck", "validate_source", env="registry", trace=("reference_type",)),
    # ── 6. refinements ──────────────────────────────────────────────────
    EntryPoint("refinements", "refinements", "erase_type", result="sort"),
    EntryPoint("refinements", "refinements", "obligation_script", env="registry"),
    EntryPoint("refinements", "refinements", "subtype_script", env="registry"),
    EntryPoint("refinements", "refinements", "check_translatable", env="registry"),
    # ── 7. policies ─────────────────────────────────────────────────────
    EntryPoint("policies", "policies", "decompose_obligation_id", result="decomposition"),
    EntryPoint("policies", "policies", "validate_point", result="point"),
    EntryPoint("policies", "policies", "at_least", result="at_least"),
    EntryPoint("policies", "policies", "satisfies", result="satisfies"),
    EntryPoint("policies", "policies", "validate_selector", result="selector"),
    EntryPoint("policies", "policies", "selector_matches", result="matches"),
    EntryPoint("policies", "policies", "matching_rules", result="rules"),
    EntryPoint("policies", "policies", "validate_policy", result="policy"),
    EntryPoint("policies", "policies", "policy_bytes"),
    EntryPoint("policies", "policies", "policy_hash"),
    EntryPoint("policies", "policies", "dominates", result="dominates"),
)

#: `DeclarationRegistry.add` is a method, so it is patched on the class rather
#: than on the module. It is the point at which a declaration object is accepted
#: into a registry or refused, which is the `declarations` gate in practice.
METHOD_ENTRY_POINTS: tuple[tuple[EntryPoint, str], ...] = (
    (EntryPoint("declarations", "declarations", "DeclarationRegistry.add", result="digest"), "DeclarationRegistry"),
)

#: Which layer owns which error classes. Used only to sanity-check the export:
#: a rejection carrying a class no contract declares is a harness bug or a leak
#: from a layer into another layer's gate, and either is worth seeing.
DECLARED_ERRORS = {
    "parser": ("SurfaceError", "ParseError"),
    "declarations": ("DeclarationError",),
    "scope": ("ScopeError",),
    "references": ("ReferenceError",),
    "typecheck": ("TypingError",),
    "refinements": ("SmtError",),
    "policies": ("PolicyError",),
}


def by_layer() -> dict[str, list[EntryPoint]]:
    result: dict[str, list[EntryPoint]] = {}
    for entry in ENTRY_POINTS:
        result.setdefault(entry.layer, []).append(entry)
    for entry, _ in METHOD_ENTRY_POINTS:
        result.setdefault(entry.layer, []).append(entry)
    return result
