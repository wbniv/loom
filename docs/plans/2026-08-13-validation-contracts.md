# Plan — Versioned validation contracts

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Bootstrap corpus tranche 4: the refinement slice](2026-08-13-corpus-tranche-4.md)

## Objective

Give each prototype validation layer a **version number with a stated meaning**, so
that a future non-Python implementation can claim "scope contract 1.0" and be held
to it by differential testing against the Python reference.

This is the remaining gate on `TODO.md`'s production-language Watch entry. Trigger
(a) reads: *two consecutive corpus tranches require no canonical IR/tag changes
**and** the parser, scope, reference, and type-checking contracts are versioned.*
Tranches 3 and 4 satisfied the first clause. This plan satisfies the second.

Scope is deliberately narrow. This is **toolchain policy, not language semantics**:
`SPEC.md` is not touched, no layer's behaviour changes, and no version is
retroactively reconstructed.

## Rules

### R1 — Granularity: one contract per layer, seven of them

`parser`, `scope`, `references`, `typecheck`, `refinements`, `declarations`,
`policies`. Not one toolchain version.

Three reasons, in order of weight:

1. **A re-implementation lands layer by layer.** The realistic path for a Rust
   port is: parser + canonical bytes first (it is the only layer whose output is
   *bytes*, so it is the only one that can be differentially tested with no
   scaffolding), then scope, then references, then typecheck. A single toolchain
   version forces an all-or-nothing conformance claim and makes the intermediate
   states unnameable.
2. **A single version is a useless differential-test scope.** Under one number,
   any change anywhere bumps it, so "conforms to toolchain 4.0" tells a
   re-implementer nothing about *which* fixtures to re-run. Per-layer, a bump
   names exactly the entry points and pinned artifacts whose oracle comparison
   must be redone.
3. **The Watch entry names four layers separately**, which is already the
   per-layer shape. The three extra contracts (`refinements`, `declarations`,
   `policies`) are included because each has the same two properties the four
   named ones have — a public entry point with an accept/reject decision, and
   pinned canonical bytes or hashes — so excluding them would be arbitrary.
   `contracts.WATCH_TRIGGER_LAYERS` records which four the trigger names.

Layers with no independent acceptance decision get no contract of their own:
`cbor_canonical.py` and `sexpr.py` are covered by `parser` (they have no public
surface a re-implementation would target separately), `matches.py` is an import
shim, `prelude.py`/`corpus_registry.py`/`definition_types.py` are *data* that
appears in other contracts' pinned-artifact lists.

### R2 — Version scheme: `MAJOR.MINOR`, no patch level

A patch level could only ever record a change the contract explicitly does not
cover (error wording, refactor, performance). Numbering those would make the
version move without any conformance consequence, which is exactly the failure
that makes a version number ignorable.

### R3 — What a version covers

For each layer, the version covers:

- **The acceptance set.** Which inputs the layer's public entry points accept and
  which they reject. This is the whole point: a conforming implementation must
  agree with the Python reference on the accept/reject bit for every input.
- **The rejection *decision*, and the declared error class** (`SurfaceError`,
  `ScopeError`, `ReferenceError`, `TypingError`, `DeclarationError`, `SmtError`,
  `PolicyError`) — a conforming implementation must reject, and must reject in
  the category the reference does.
- **Canonical byte outputs and derived hashes**, where the layer produces them:
  the rendered surface, the CBOR definition object, the definition identity,
  declaration bytes and hashes, SMT-LIB script text and its SHA‑256, policy bytes
  and hashes.
- **The injected-resolver call conventions** — `scope.AbilityArityResolver`,
  `typecheck.ReferenceTypeResolver`, and `refinements`' `signatures` /
  `interpretations` mappings. Argument order, argument meaning, return shape, and
  what the layer does when the resolver is absent (`None`) or raises are all
  contract; a re-implementation has to be injectable the same way or it cannot be
  driven by the same differential harness.
- **The public entry-point names and signatures** listed in `Contract.entry_points`.

### R4 — What a version explicitly does **not** cover

- **Error message text.** Wording is free to improve at any time, with no bump.
  A better diagnostic is a strict improvement and must never be discouraged by a
  version-number cost.
- **Path strings in errors** (`definition.term.arg.1` and friends). These are
  diagnostic quality, not contract. They are extremely useful and should stay
  path-aware — but a conforming implementation is not required to reproduce them
  byte for byte, and re-labelling one here is not a bump.
- Internal structure, module-private helpers, performance, memory, traversal
  order, test organisation, and documentation.
- Fixtures and corpus entries *per se*. Adding `corpus/list/map` exercises the
  contracts; it does not change them. (If adding a fixture requires a layer
  change to make it validate, the *layer change* is what bumps.)

### R5 — What bumps a version

Exactly three outcomes, decided by asking what happens to an implementation that
conformed to the previous version:

| Change | Bump |
|---|---|
| An input the previous version **accepted** is now rejected | **MAJOR** |
| Canonical bytes, an identity, or a pinned hash change for any input the previous version accepted | **MAJOR** |
| An injected-resolver convention or a public entry-point signature changes incompatibly | **MAJOR** |
| An input the previous version **rejected loudly** is now accepted, with no change to anything previously accepted | **MINOR** |
| A new public entry point, or a new optional parameter whose default preserves behaviour | **MINOR** |
| Error text, error path strings, refactor, performance, tests, docs, new fixtures | **none** |

Two clarifications the rule needs to be crisp:

- **"Rejected loudly"** means the previous version raised that layer's declared
  error class. A layer that silently mis-accepted something and now rejects it is
  a MAJOR bump, not a bug-fix exemption — the old behaviour was in the acceptance
  set whether or not it was intended. This is the rule's teeth: it prices
  soundness fixes honestly rather than letting them slip through unnumbered.
- A **MAJOR bump resets MINOR to 0**.

### R6 — The rule tested against actual history

The rule is only worth anything if it decides real past changes unambiguously.
It is stated forward-looking (R7), but it must *reproduce* the intent of what
already happened:

| Past change | Under R5 |
|---|---|
| `if` / term tag 12 added (Bool elimination) | `parser` MINOR (a surface that previously failed to parse now parses; no existing bytes moved) + `typecheck` MINOR |
| `fix` gained the decreasing-argument position field | `parser` **MAJOR** — every previously-accepted `fix` surface without the field is now rejected, and existing `fix` definitions' canonical bytes and identities moved |
| First-order `forall` instantiation | `typecheck` MINOR (previously a `TypingError`, now checks) |
| Effect-consistency follow-ups: error rewording | **none** |
| Corpus tranches 3 and 4 | **none** on any layer — zero IR/tag changes, and no layer's acceptance set or bytes moved. This is precisely the evidence Watch trigger (a) asks for, and under R5 it is visible as "no version moved across two tranches" rather than as prose. |

### R7 — Seed honestly at 1.0

Every contract starts at **1.0 as of this commit**. Historical versions are *not*
reconstructed — the bump rules did not exist while that history happened, so any
reconstructed number would be a fabrication dressed as a record. 1.0 means "the
behaviour at commit *this one*", and the rules apply from here forward.

### R8 — Where it is recorded

- **`prototype/contracts.py`** — the machine-readable record. One frozen
  `Contract` dataclass per layer carrying name, `(major, minor)`, owning module,
  entry points, injected-resolver conventions, and the pinned artifacts that are
  the contract's executable form. Importable, so a differential harness can
  enumerate what to compare instead of hardcoding it; testable, so the record
  cannot drift from the code it describes.
- **`prototype/CONTRACTS.md`** — the narrative: what a version means, the bump
  table, and the per-layer detail. Kept **out of** `prototype/README.md` because
  that file is a tour of the directory for someone working *in* the prototype,
  whereas this is a conformance document read by someone *replacing* it. It needs
  to be linkable on its own. `README.md` gets a pointer and a files-table row.
- **`prototype/test_contracts.py`** — pins the current version of every contract
  as a literal, and asserts the module's own invariants (see R9).

No version constant is added to any layer module. One place, importable, or the
numbers drift.

### R9 — The comment discipline and what the test enforces

The pinning test is what makes the discipline real: **you cannot change a
contract's version without editing `test_contracts.py`**, and that edit is the
moment to check the change against R5. The test additionally asserts:

- every declared entry point resolves in its module and is callable;
- every declared pinned artifact resolves — a dotted module attribute, or a path
  that exists under `prototype/`;
- names are unique, versions are `(int, int)` at ≥ 1.0, `MAJOR ≥ 1`;
- the four `WATCH_TRIGGER_LAYERS` are all present in `CONTRACTS`;
- every module owning a contract is distinct, and every declared entry point is
  prefixed with its own contract's module;
- `CONTRACTS.md` names every contract and states its current version — a
  doc-drift guard, so a bump that misses the narrative fails the suite;
- the covered/not-covered lists are non-empty and disjoint.

## Deliberate boundary

- This plan **versions**; it does not build the differential harness. Comparing a
  second implementation against the reference is future work and belongs with
  whatever the Watch entry's language decision produces.
- It changes no layer behaviour, no fixture, and no pinned hash. Every existing
  test must pass unchanged, and any diff to an existing golden would itself be a
  defect of this change.
- `TODO.md` is not edited here: promoting the Watch entry is a ranking decision.

## Work

- [x] Settle granularity, coverage, bump rules, and seeding (R1–R7).
- [x] Add `prototype/contracts.py` with seven contracts seeded at 1.0.
- [x] Add `prototype/CONTRACTS.md` narrating the rules.
- [x] Add `prototype/test_contracts.py` pinning versions and asserting invariants.
- [x] Wire `test_contracts` into `Taskfile.yml`'s `prototype:test`.
- [x] Add rows to `docs/plans/README.md` and `prototype/README.md`'s files table.
- [x] Preserve every existing parser, scope, reference, typecheck, refinement,
      policy, extern, and corpus result.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

## Completion criteria

- Each of the seven layers has a version whose meaning is written down.
- The bump rule decides the historical cases in R6 without appeal to judgment.
- The record is importable and cannot silently drift from the code or the doc.
- All four Watch-named contracts (`parser`, `scope`, `references`, `typecheck`)
  are versioned, making trigger (a)'s second clause true.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

### 1. `task prototype:test`

```text
Ran 267 tests in 0.699s

OK (skipped=1)
```

PASS — 267 tests, up from 249 (18 new in `test_contracts`), no existing test
changed or removed. The one skip is `test_corpus`'s optional solver run, which is
skipped when no `LOOM_SMT_SOLVER` or `z3` is available; it was skipped before this
change too.

### 2. `python3 -m py_compile prototype/*.py`

```text
(no output)
```

PASS — exit status 0.

### 3. `task todo:lint`

```text
TODO.md: clean
```

PASS.

### 4. `git diff --check`

```text
(no output)
```

PASS — no whitespace errors.
