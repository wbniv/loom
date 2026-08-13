# Plan — Canonical parser and transcoder hardening

**Date:** 2026-08-12
**Status:** Implemented and verified locally
**Baseline:** `7474944` (`Prototype Loom S-expression transcoder`)
**Review:** [Parser prototype review](../reviews/2026-08-12-parser-prototype-review.md)

## Objective

Turn the initial S-expression feasibility spike into a defensible canonical
generation surface for Loom: one rendered spelling per supported IR value, a
safe and validating parser, an inverse renderer, agreement between fixtures and
the GBNF artifact, and tests that substantiate the isomorphism and identity
claims.

This remains a syntax and identity prototype. Scope checking, type checking,
constructor and operation lookup, exhaustiveness, termination, refinements, and
evidence remain outside this plan and belong to the stateful decoder and oracle.

## Decisions

### Use a strict canonical surface

Choose a bijective canonical subset rather than a permissive, many-to-one
authoring language. The parser may structurally recognize an input before
validation, but `parse_source` accepts it only when the inverse renderer produces
the same source, apart from one optional terminal newline.

Canonical rules:

- fixed single-space layout on one line;
- no comments;
- lowercase, exactly 32-byte hashes;
- canonical nonnegative decimal indices;
- signed-64-bit decimal literals without leading zeroes or negative zero;
- exact eight-byte hexadecimal `f64` literals, with one canonical NaN payload;
- arbitrary-length, even-digit lowercase hexadecimal byte literals;
- JSON string escapes, valid Unicode scalar values, and NFC text;
- unique effect hashes in bytewise order, followed optionally by one row
  variable.

### Keep syntax validation independent of masking

The transcoder must reject malformed and noncanonical input even when callers do
not use the GBNF mask. Constrained generation is a producer-side guarantee, not
a substitute for validation at the identity boundary.

### Make the inverse executable

Implement `type_to_surface`, `term_to_surface`, and `def_to_surface`. The word
"isomorphism" is justified only when both directions exist and both round trips
are tested.

## Work plan

### Phase 1 — lexer and error model

- [x] Replace regex plus line-based comment stripping with a state-aware lexer.
- [x] Preserve token offsets for deliberate parse diagnostics.
- [x] Handle strings without treating embedded semicolons as comments.
- [x] Detect unclosed lists, stray closing delimiters, unterminated strings,
  invalid escapes, and multiple top-level forms without incidental exceptions.
- [x] Reject comments because they are not part of the machine-emission surface.

### Phase 2 — validated canonical transcoding

- [x] Replace input-validation assertions with explicit `SurfaceError` failures.
- [x] Validate node arity and keyword choice at every term and type node.
- [x] Validate nonnegative indices and signed-64-bit literal bounds.
- [x] Require exactly 32 bytes for references, abilities, and data hashes.
- [x] Separate arbitrary byte literals from fixed-length hashes.
- [x] Represent `f64` values with exact IEEE-754 bytes and reject alternate NaNs.
- [x] Require NFC text and reject Unicode surrogate code points.
- [x] Support an effect-row type variable in final position.
- [x] Require effect hashes to be unique and sorted bytewise.

### Phase 3 — inverse renderer and canonicality gate

- [x] Render every term tag, type tag, and literal kind from IR.
- [x] Render lists, rows, arms, and handler operations with fixed spacing.
- [x] Permit only the rendered normal form, plus an optional final newline.
- [x] Preserve the §4.4 definition's exact canonical CBOR bytes and identity.

### Phase 4 — grammar and fixture alignment

- [x] Remove comments and free whitespace from example emission files.
- [x] Change `loom.gbnf` to the fixed-spacing canonical surface.
- [x] Restrict hashes, integers, floats, and bytes to their canonical lexical
  forms in the grammar.
- [x] Add the optional final row variable to the grammar.
- [x] Preserve fixture descriptions in `prototype/README.md` rather than inside
  machine-emission files.
- [x] Execute `loom.gbnf` through llama.cpp's model-free GBNF validator and add
  a repeatable positive/negative conformance harness.

### Phase 5 — conformance tests

- [x] Retain the independent golden bytes and SHA-256 identity test.
- [x] Test `surface -> IR -> surface` and `IR -> surface -> IR`.
- [x] Cover all 12 term tags.
- [x] Cover all 7 type tags, all base types, and a row variable.
- [x] Cover all 6 literal kinds, including empty bytes, signed boundaries,
  negative zero as an `f64`, infinity, canonical NaN, escapes, and Unicode.
- [x] Reject aliases: alternate base syntax, leading zeroes, negative indices,
  invalid booleans, alternate NaNs, decomposed text, bad hash case/length,
  unsorted or duplicate effects, extra whitespace, and comments.
- [x] Test malformed delimiters, strings, arity, keywords, empty input, and
  multiple definitions.
- [x] Correct and pin RFC 8949 length-first map-key ordering in the CBOR encoder.

## Verification procedure

Run from the repository root unless a different directory is shown.

### Unit and conformance suite

```sh
cd prototype
python3 -m unittest test_roundtrip -v
```

Recorded result on 2026-08-12:

```text
Ran 10 tests in 0.010s

OK
```

The ten test groups cover the golden identity, examples, every term/type/literal
variant, both inverse round trips, integer boundaries, malformed forms,
noncanonical aliases, terminal-newline handling, and CBOR map-key ordering.

### Syntax compilation

```sh
cd prototype
python3 -m py_compile sexpr.py transcode.py cbor_canonical.py test_roundtrip.py
```

Recorded result: exit status 0.

### Golden CLI check

```sh
cd prototype
python3 transcode.py examples/01_id.loom.sexpr
```

Recorded result:

```text
bytes  = 83008402820002808200028303820002820000  (19 bytes)
hash   = #76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605
```

### Repository checks

```sh
task todo:lint
git diff --check
```

Recorded results:

```text
TODO.md: clean
```

`git diff --check` exited successfully with no output.

### Production GBNF validation

The grammar was verified with llama.cpp `test-gbnf-validator` built from
revision `1f368f354d9edcfea9fd6a1e0989b3e7335a050f`:

```sh
LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator \
  task grammar:test
```

The validator initially rejected `loom.gbnf`, exposing invalid ungrouped
multiline alternatives. After correcting those productions, the recorded result
was:

```text
GBNF PASS: 11 valid cases accepted; 11 invalid cases rejected
```

## Completion criteria

The local parser-hardening work is complete when:

- every normative term, type, and literal representation has a canonical
  surface form;
- the inverse renderer reproduces that form exactly;
- malformed, invalid, and noncanonical inputs fail intentionally;
- fixtures conform to the canonical surface;
- all positive, boundary, rejection, and golden identity tests pass;
- documentation describes the implemented behavior and its semantic boundary.

Those criteria are satisfied by the current working tree. The repository does
not vendor llama.cpp; callers provide the validator path through
`LOOM_GBNF_VALIDATOR`. CI should build or install the pinned upstream validator
before invoking `task grammar:test` when a CI workflow is introduced.
