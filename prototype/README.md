# Loom prototype — canonical S-expression surface + CBOR transcoder

This directory implements the canonical, prior-rich emission surface proposed
by `SPEC.md` §8.4 and the deterministic conversion between that surface and the
IR encoded as canonical CBOR.

**Status: working syntax/identity/scope prototype, not a store.** There is no
typechecker, evidence lattice, or full oracle here.

## Run it

```sh
cd prototype
python3 -m unittest test_roundtrip -v
python3 -m unittest test_roundtrip test_scope -v
python3 transcode.py examples/01_id.loom.sexpr
```

## Canonical-surface contract

The machine-emission surface has exactly one rendering for each supported IR:

- spacing is fixed and the definition occupies one line;
- one final newline is permitted for an ordinary text file;
- comments are not part of the surface;
- hashes are 32 bytes written as 64 lowercase hex digits;
- indices are canonical nonnegative decimal integers;
- `i64` values use canonical decimal spelling and are range-checked;
- `f64` values use their exact eight IEEE-754 bytes as 16 lowercase hex digits,
  with one permitted quiet-NaN representation;
- byte literals use an arbitrary even number of lowercase hex digits;
- text uses JSON string escapes and must already be NFC-normalized;
- effect hashes are unique and sorted bytewise, optionally followed by one
  `(tyvar n)` row variable.

`transcode.parse_source` rejects noncanonical aliases rather than silently
normalizing them. `transcode.def_to_surface` is the inverse renderer. Tests
exercise both `surface -> IR -> surface` and `IR -> surface -> IR`.

## Files

| File | Role |
|---|---|
| `cbor_canonical.py` | RFC 8949 deterministic encoder for the Python values used by Loom objects. |
| `sexpr.py` | Bounds-safe lexer and structural reader with source-offset errors. |
| `transcode.py` | Validates the surface, maps all term/type/literal tags to IR, renders IR back to its canonical surface, encodes definitions, and computes identity. |
| `scope.py` | Checks term/type de Bruijn indices with path-aware errors; handler checks use an injected ability-operation arity resolver. |
| `declarations.py` | Validates, hashes, and registers canonical data/ability declaration objects, including recursive data `self` types. |
| `references.py` | Resolves nominal data/ability hashes and checks explicit constructor/operation bounds and arities. |
| `prelude.py` | Canonical v0.1 builtin ability declarations, operation names, pinned hashes, and a preloaded registry. |
| `matches.py` | Bidirectional nominal constructor checking and exhaustive match validation for the first type-directed subset. |
| `loom.gbnf` | llama.cpp-style grammar for the same fixed-spacing generation surface. |
| `validate_gbnf.py` | Runs positive and negative conformance cases through llama.cpp's model-free validator. |
| `examples/*.loom.sexpr` | Four canonical definition fixtures. Descriptions live here rather than as comments in the machine-emission files. |
| `test_roundtrip.py` | Golden identity, exhaustive tag/literal coverage, inverse round trips, boundary checks, and malformed/noncanonical rejection tests. |
| `test_scope.py` | Exhaustive binder-depth, shadowing, handler-resolution, and out-of-scope rejection tests. |
| `test_references.py` | Declaration identity, registry integrity, missing/wrong-kind references, and bounds/arity tests. |
| `test_prelude.py` | Pins builtin ABI hashes and validates representative operations, handlers, rows, and capabilities. |
| `test_matches.py` | Parameter substitution, recursive self, binder ordering, exhaustiveness, and arm-type agreement tests. |

The example fixtures are:

1. `01_id`: the §4.4 identity function.
2. `02_effect_row`: a nonempty effect row with `perform` and `let`.
3. `03_refinement`: a refinement predicate and constrained hole.
4. `04_match_con`: construction and matching for a fixture data type.

The hashes in examples 2–4 are prototype fixtures rather than store content.

## Golden identity check

`examples/01_id.loom.sexpr` must encode to the exact 19 bytes and SHA-256
identity specified in `SPEC.md` §4.4:

```text
bytes = 83008402820002808200028303820002820000
hash  = #76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605
```

## Boundary of the result

The prototype demonstrates a canonical syntactic representation and preserves
identity through deterministic transcoding. The grammar constrains node shape;
the transcoder additionally enforces field domains and canonical spellings.

`scope.validate_source` establishes de Bruijn scope correctness using the binder
rules in `SPEC.md` §2.3.1. Handler clauses require a caller-provided resolver for
operation parameter counts; the checker refuses to guess when store information
is absent. `transcode.transcode_source` remains deliberately store-independent
and does not perform this stateful check.

`references.validate_source` checks nominal declaration existence, kind, and
explicit `con`/`perform`/`handle` bounds and arities. The prototype does not
establish match exhaustiveness, typing, termination, refinement validity, or
evidence. Match constructor and binder validation requires inference of the
scrutinee type and remains a typechecker responsibility. The remaining oracle
layers are described in `SPEC.md` §§3, 6, and 8.

`matches.validate_source` is the first deliberately partial type-directed layer.
It validates nominal constructors and matches over literals, variables, lambdas,
applications, lets, constructors, matches, and holes. Other nodes raise an
explicit path-aware error until their typing rules are implemented.

The repository does not vendor llama.cpp. To run production GBNF conformance,
point `LOOM_GBNF_VALIDATOR` at a built `test-gbnf-validator` binary and run:

```sh
LOOM_GBNF_VALIDATOR=/path/to/test-gbnf-validator task grammar:test
```

This is model-free. The harness checks canonical examples and additional surface
variants, then confirms that representative noncanonical forms are rejected.

## Spec clarification found during implementation

The unit literal has no payload. Its canonical node is the two-element array
`[2, 0]`, represented by `(lit unit)`, as now recorded in `SPEC.md` §2.2.
