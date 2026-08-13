# Loom prototype — versioned validation contracts

This is the conformance document. It exists for someone **replacing** this
prototype, not for someone working inside it: a future non-Python implementation
should be able to claim "scope contract 1.0", and this file plus
[`contracts.py`](contracts.py) is what that claim means and how it is checked.

`contracts.py` is the machine-readable form; this file is the narrative. They are
kept in step by [`test_contracts.py`](test_contracts.py), which fails if a version
moves in one and not the other.

Design and rationale: [Versioned validation contracts](../docs/plans/2026-08-13-validation-contracts.md).

## Current versions

| Contract | Version | Module | What it covers |
|---|---|---|---|
| `parser` | 1.0 | `transcode.py` | Canonical S-expression surface acceptance, the surface/IR inverse pair, the canonical CBOR definition object, and definition identity. |
| `scope` | 1.0 | `scope.py` | Term and type de Bruijn index validity, binder depth, handler operation resolution, and the `forall` prefix of a definition type. |
| `references` | 1.0 | `references.py` | Resolution of nominal data and ability hashes against a registry, plus explicit constructor and operation bounds and arities. |
| `typecheck` | 1.0 | `typecheck.py` | The partial bidirectional checker: nominal matches, effects and handlers, `if`, `fix`/`ref`, and first-order `forall` instantiation. |
| `declarations` | 1.0 | `declarations.py` | Validation, canonical encoding, and hashing of data/ability declaration and extern definition objects, and the registry that holds them. |
| `refinements` | 1.0 | `refinements.py` | Translation of one §3.2.1 verification condition into one canonical SMT-LIB script, and refusal of everything outside the decidable fragment. |
| `policies` | 1.0 | `policies.py` | Namespace policy object validation and canonical hashing, obligation-id decomposition, evidence satisfaction (`E ⊒ R`), and policy domination. |

The first four are the ones `TODO.md`'s production-language Watch trigger (a)
names; `contracts.WATCH_TRIGGER_LAYERS` records that.

All seven are seeded at **1.0 as of the commit that added this file**. Historical
versions are deliberately not reconstructed — the bump rules did not exist while
that history happened, so any earlier number would be a fabrication dressed as a
record. The rules below apply forward from 1.0.

## Why per layer, not one toolchain version

A re-implementation lands layer by layer: parser and canonical bytes first
(the only layer whose output is *bytes*, so the only one differentially testable
with no scaffolding), then scope, then references, then typecheck. One number
would make those intermediate states unnameable and force an all-or-nothing
conformance claim. It would also be a useless test scope — under one version any
change anywhere bumps it, so the number stops telling a re-implementer which
fixtures to re-run.

Layers with no independent acceptance decision get no contract: `cbor_canonical.py`
and `sexpr.py` are covered by `parser`, `matches.py` is an import shim, and
`prelude.py` / `corpus_registry.py` / `definition_types.py` are *data* that
appears in other contracts' pinned-artifact lists.

## Versions are `MAJOR.MINOR`

There is no patch level. A patch could only ever record a change that this
contract explicitly does not cover, which would move the number with no
conformance consequence — exactly the habit that makes a version ignorable.

## What a version covers

- **The acceptance set.** Which inputs the layer's listed entry points accept and
  which they reject. A conforming implementation must agree with the Python
  reference on the accept/reject bit for every input.
- **The rejection decision and its declared error class** — `SurfaceError`,
  `ScopeError`, `ReferenceError`, `TypingError`, `DeclarationError`, `SmtError`,
  `PolicyError`. It must reject, and reject in the same category.
- **Canonical byte outputs and derived hashes**, where the layer produces them:
  the rendered surface, the CBOR definition object and its identity, declaration
  bytes and hashes, SMT-LIB script text and its SHA‑256, policy bytes and hashes.
- **The injected-resolver call conventions** — `scope.AbilityArityResolver`,
  `typecheck.ReferenceTypeResolver`, and `refinements`' `signatures` /
  `interpretations` mappings. Argument order and meaning, return shape, and the
  behaviour when the resolver is absent (`None`) or raises. A re-implementation
  must be injectable the same way or the same differential harness cannot drive it.
- **The public entry-point names and signatures** listed in each contract's
  `entry_points`.

## What a version does **not** cover

- **Error message text.** Wording is free to improve at any time at no version
  cost. A better diagnostic is a strict improvement and must never be priced.
- **The path strings inside errors** (`definition.term.arg.1` and friends). They
  are diagnostic quality, not contract: they should stay path-aware, but a
  conforming implementation is not required to reproduce them byte for byte, and
  re-labelling one here is not a bump.
- Module-private structure, traversal order, performance, memory, test
  organisation, and documentation.
- Fixtures and corpus entries as such. Adding `corpus/list/map` *exercises* the
  contracts; it does not change them. If a new fixture needs a layer change to
  validate, the layer change is what bumps.

## What bumps a version

Decide by asking what happens to an implementation that conformed to the
previous version.

| Change | Bump |
|---|---|
| An input the previous version **accepted** is now rejected | **MAJOR** |
| Canonical bytes, an identity, or a pinned hash change for any input the previous version accepted | **MAJOR** |
| An injected-resolver convention or a public entry-point signature changes incompatibly | **MAJOR** |
| An input the previous version **rejected loudly** is now accepted, with nothing previously accepted changed | **MINOR** |
| A new public entry point, or a new optional parameter whose default preserves behaviour | **MINOR** |
| Error text, error path strings, refactor, performance, tests, docs, new fixtures | **none** |

Two clarifications that make the rule decidable rather than a judgment call:

- **"Rejected loudly"** means the previous version raised that layer's declared
  error class. A layer that *silently mis-accepted* something and now rejects it
  is a **MAJOR** bump, not a bug-fix exemption — the old behaviour was in the
  acceptance set whether or not anyone intended it. This is the rule's teeth: it
  prices soundness fixes honestly instead of letting them slip through unnumbered.
- A **MAJOR bump resets MINOR to 0.**

## The rule against this repository's own history

Stated forward-looking, but it has to reproduce the intent of what already
happened, or it is not a rule:

| Past change | Under the table above |
|---|---|
| `if` / term tag 12 added (Bool elimination) | `parser` MINOR — a surface that previously failed to parse now parses, and no existing bytes moved — plus `typecheck` MINOR |
| `fix` gained the decreasing-argument position field | `parser` **MAJOR** — every previously-accepted `fix` surface lacking the field is now rejected, and existing `fix` definitions' canonical bytes and identities moved |
| First-order `forall` instantiation | `typecheck` MINOR — previously a `TypingError`, now checked |
| Effect-consistency review follow-ups (error rewording) | **none** |
| Corpus tranches 3 and 4 | **none** on any layer — zero IR/tag changes, and no acceptance set or byte output moved. This is exactly the evidence Watch trigger (a) asks for, now visible as "no version moved across two tranches" rather than as prose. |

## The discipline

Versions live in `contracts.py` only — never as a constant inside a layer module,
or they drift.

`test_contracts.py` pins every current version as a literal. You therefore
**cannot change a version without editing that test**, and that edit is the moment
to check the change against the table above. The same test also asserts the
record against the code: every entry point resolves and is callable, every pinned
artifact resolves as a module attribute or an existing file, every declared
resolver keyword actually exists on its function, the four Watch-named contracts
are present, and this file names every contract with its current version.

When you bump, change three things in the same commit: the `Contract` in
`contracts.py`, the pinned literal in `test_contracts.py`, and the current-versions
table above.
