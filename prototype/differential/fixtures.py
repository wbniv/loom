"""The fixture pass: the 26 corpus entries and the 5 examples, every layer.

Track P's L0 names these 31 inputs explicitly, so they are driven directly
rather than being left to whichever test happens to reach them. Each source is
put through the parser, scope, references, and typecheck gates; the corpus's
declarations and externs through the declaration gate; the corpus's pinned
verification conditions through the refinement gate; and the pinned policies
through the policy gate.

Every call is made under `_attempt`, which lets a rejection *be a record*. A
fixture that the type layer refuses today is not a harness failure — the corpus
manifest declares which entries reach `checked` and which stop at `structural`,
and both are cases a Rust port must reproduce.

This module must not be imported before `instrument.install`, because importing
`corpus_registry` builds its hash tables eagerly and those calls are themselves
declaration cases worth capturing.
"""

from __future__ import annotations

from pathlib import Path

PROTOTYPE_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = PROTOTYPE_DIR / "examples"


def _attempt(function, *args, **kwargs):
    """Call and swallow. The wrapper has already recorded whichever happened."""
    try:
        return function(*args, **kwargs)
    except Exception:
        return None


def sources() -> list[tuple[str, str]]:
    """`(fixture name, source text)` for the 26 corpus entries and 5 examples."""
    import corpus_registry

    entries = [
        (f"corpus/{entry.fixture}", entry.source_text())
        for entry in corpus_registry.MANIFEST
    ]
    entries += [
        (f"examples/{path.name}", path.read_text(encoding="utf-8"))
        for path in sorted(EXAMPLES_DIR.glob("*.loom.sexpr"))
    ]
    return sorted(entries)


def run(recorder) -> None:
    import corpus_registry
    import declarations
    import policies
    import prelude
    import references
    import scope
    import transcode
    import typecheck

    registry = corpus_registry.registry()
    reference_type = corpus_registry.reference_type(registry)
    ability_arity = registry.operation_arity

    # ── the 31 named inputs, through the first five layers ──────────────
    for name, source in sources():
        recorder.provenance = ("fixture", name, "")
        _attempt(transcode.parse_source, source)
        _attempt(transcode.transcode_source, source)
        # `None` is a contract-relevant resolver configuration in its own
        # right: CONTRACTS.md makes the absent-resolver behaviour part of the
        # scope contract, and the gate table repeats it.
        _attempt(scope.validate_source, source, None)
        _attempt(scope.validate_source, source, ability_arity)
        _attempt(references.validate_source, source, registry)
        _attempt(typecheck.validate_source, source, registry, None)
        _attempt(typecheck.validate_source, source, registry, reference_type)
        _attempt(typecheck.validate_source, source, registry, reference_type, obligations=[])

    # ── declarations: the builtin prelude, the corpus, the assumed base ──
    for kind, table, load in (
        ("prelude", prelude.HASHES, prelude.declaration),
        ("corpus", corpus_registry.HASHES, corpus_registry.declaration),
        ("extern", corpus_registry.EXTERN_HASHES, corpus_registry.extern),
    ):
        for name in sorted(table):
            recorder.provenance = ("fixture", f"declaration/{kind}/{name}", "")
            obj = load(name)
            _attempt(declarations.declaration_bytes, obj)
            _attempt(declarations.declaration_hash, obj)
            _attempt(declarations.DeclarationRegistry().add, obj, table[name])

    # ── refinements: every pinned corpus verification condition ─────────
    for entry in corpus_registry.MANIFEST:
        for obligation in entry.obligations:
            recorder.provenance = ("fixture", f"corpus/{entry.fixture}#{obligation.name}", "")
            _attempt(obligation.script, registry)
            _attempt(obligation.emit, registry)

    # ── policies: the pinned default and its own domination ─────────────
    recorder.provenance = ("fixture", "policy/default", "")
    _attempt(policies.validate_policy, policies.DEFAULT_POLICY)
    _attempt(policies.policy_bytes, policies.DEFAULT_POLICY)
    _attempt(policies.policy_hash, policies.DEFAULT_POLICY)
    _attempt(policies.dominates, policies.DEFAULT_POLICY, policies.DEFAULT_POLICY)
    for tag in sorted(policies.OBLIGATION_KINDS):
        recorder.provenance = ("fixture", f"policy/obligation-kind/{tag}", "")
        _attempt(policies.decompose_obligation_id, [tag])

    recorder.provenance = None
