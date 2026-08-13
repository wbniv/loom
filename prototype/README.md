# Loom prototype — canonical S-expression surface + CBOR transcoder

This directory implements the canonical, prior-rich emission surface proposed
by `SPEC.md` §8.4 and the deterministic conversion between that surface and the
IR encoded as canonical CBOR.

**Status: working syntax/identity/scope and partial type-directed prototype, not
a store.** There is no complete typechecker, evidence lattice, or full oracle
here.

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
| `matches.py` | Bidirectional nominal/match and closed-row effect/handler checking for the first type-directed subset. |
| `refinements.py` | Translates one verification condition into one canonical SMT-LIB script and rejects everything outside the decidable fragment. |
| `policies.py` | Validates and canonically hashes namespace policy objects, checks evidence-satisfies-requirement (`E ⊒ R`) and policy domination. |
| `corpus_registry.py` | Bootstrap-corpus data declarations with reproducible nominal keys, the seed-set manifest, and the §8.4 few-shot pairs. |
| `loom.gbnf` | llama.cpp-style grammar for the same fixed-spacing generation surface. |
| `validate_gbnf.py` | Runs positive and negative conformance cases through llama.cpp's model-free validator. |
| `examples/*.loom.sexpr` | Five canonical definition fixtures. Descriptions live here rather than as comments in the machine-emission files. |
| `corpus/*.loom.sexpr` | Bootstrap-corpus seed definitions. Descriptions are manifest data in `corpus_registry.py`, not prose here. |
| `test_roundtrip.py` | Golden identity, exhaustive tag/literal coverage, inverse round trips, boundary checks, and malformed/noncanonical rejection tests. |
| `test_scope.py` | Exhaustive binder-depth, shadowing, handler-resolution, and out-of-scope rejection tests. |
| `test_references.py` | Declaration identity, registry integrity, missing/wrong-kind references, and bounds/arity tests. |
| `test_prelude.py` | Pins builtin ABI hashes and validates representative operations, handlers, rows, and capabilities. |
| `test_matches.py` | Parameter substitution, recursive self, binder ordering, exhaustiveness, and arm-type agreement tests. |
| `test_effects.py` | Function-row, operation-signature, capability, handler, and continuation typing tests. |
| `test_refinements.py` | Golden script bytes, sort mapping, datatype monomorphization, determinism, and fragment-refusal tests. |
| `test_policies.py` | Pinned default-policy hash, structural rejection cases, obligation decomposition, conjunctive selector matching, `E ⊒ R` satisfaction, and domination (including the deliberately incomplete rules test) and the §12 worked example's arithmetic. |
| `test_corpus.py` | Corpus declaration keys, fixture canonicity and pinned identity, declared validation tier, dependency order, and the recorded expressiveness limits (two of them re-pinned as lifted). |

The example fixtures are:

1. `01_id`: the §4.4 identity function.
2. `02_effect_row`: a nonempty effect row with `perform` and `let`.
3. `03_refinement`: a refinement predicate and constrained hole.
4. `04_match_con`: construction and matching for a fixture data type.
5. `05_clock_handler`: a locally handled builtin clock operation with typed
   continuations and an empty outer effect row.

The hashes in examples 2–4 are prototype fixtures rather than store content;
example 5 uses the pinned builtin clock declaration.

## The bootstrap corpus

`corpus/` is a separate, growing set with different provenance from `examples/`:
these are definitions hand-transpiled from the Unison base library to seed
`SPEC.md` §13 open problem 1, per the
[bootstrap-corpus plan](../docs/plans/2026-08-13-bootstrap-corpus.md). Each entry
in `corpus_registry.MANIFEST` carries a name path, spec text, source attribution,
a pinned identity, and the validation **tier** it is expected to reach — `checked`
(parse, scope, references, and the type-directed match layer) or `structural`
(the first three, with the deferred layer's reason recorded). `test_corpus.py`
enforces the tier in both directions, so a `structural` entry that starts passing
the match layer fails the suite rather than keeping a stale deferral.

Transpiling the seed set established three limits of v0.1 by construction, each
pinned by a test in `test_corpus.ExpressivenessLimitTest`. Two have since been
lifted by the
[polymorphism and Bool-elimination plan](../docs/plans/2026-08-13-polymorphism-and-bool-elimination.md)
and are re-pinned as the new behaviour: a definition's term is checked at its
type's `forall` depth, so `corpus/maybe/mapPoly` is a genuinely generic
definition (what remains is that v0.1 cannot *instantiate* a polymorphic
reference, so the `I64` instances stay); and `if` (term tag 12) eliminates
`Bool`, so `corpus/bool/not` — the definition that found the limit — is now a
fixture. The third limit stands: `fix` and `ref` have no typing rule in the match
layer yet, so the recursive tranche is still ahead.

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
rules in `SPEC.md` §2.3.1, including the definition-level rule that a term is
checked at its type's leading `forall` depth and that the depth is well defined
because a definition type's quantifiers must be prenex (`scope.forall_prefix`).
Handler clauses require a caller-provided resolver for
operation parameter counts; the checker refuses to guess when store information
is absent. `transcode.transcode_source` remains deliberately store-independent
and does not perform this stateful check.

`references.validate_source` checks nominal declaration existence, kind, and
explicit `con`/`perform`/`handle` bounds and arities. It does not establish
typing, termination, refinement validity, or evidence. The remaining oracle
layers are described in `SPEC.md` §§3, 6, and 8.

`matches.validate_source` is a deliberately partial type-directed layer. It
validates nominal constructors and exhaustive matches, `if` against `Bool` with
both branches at the goal type, closed function effect
rows, operation signatures and capabilities, and handlers with typed return,
operation, and continuation clauses. A definition typed `forall^p` is checked
against its quantified body, with type variables treated as opaque atoms under
structural type equality. Synthesized lambdas are pure — latent
effects require checking against an annotated row — and operation-less
abilities such as `div` cannot be handled. Row polymorphism and other
unsupported nodes raise an explicit path-aware error until their typing rules
are implemented.

`refinements.py` implements the `SPEC.md` §3.2.1 translation rules. It takes a
verification condition — a de Bruijn context, Bool hypotheses, and a Bool goal,
with the refined value at term index 0 — and emits exactly one canonical
SMT-LIB refutation script per input, with `subtype_script` covering the one
verification-condition producer §3.3 defines. Base types map to `Int`, `Bool`,
and three uninterpreted sorts; applied data types are monomorphized to
`Loom.D<sha256>` datatypes keyed by the canonical CBOR of the refinement-erased
type; stored references become uninterpreted functions unless a caller-supplied
interpretation table maps them onto a closed allowlist of Core and Ints symbols,
with linearity checked at each call site. Everything else — `lam`, `perform`,
`handle`, `fix`, `hole`, partial application, effectful references, function and
capability sorts, polymorphic constructors — raises a path-aware `SmtError`
rather than being approximated. The module emits and structurally validates
text; it neither links nor shells out to a solver, so `unsat` is still asserted
by a human running the script, not by this prototype.

`policies.py` implements `SPEC.md` §5.3.1's policy-object grammar and §5.3.2's
domination table. It canonically validates a policy object (key range,
array sortedness/uniqueness, canonical rationals, the closed obligation-kind
registry, selector and requirement shapes), hashes it via `cbor_canonical`
(reproducing the pinned default-policy hash `#901f33bd…` from `[6, {}]`), and
implements two comparisons: `satisfies(evidence, requirement)` — `E ⊒ R` under
§6.1.2's order, extended across A0–A3 — and `dominates(successor,
predecessor)` per §5.3.2's per-key table, including the `rules` key's
deliberately sound-but-incomplete single-rule test. There is no store here:
the module does not resolve `policy-ref` over live bindings, perform
admission, or touch leases or amendment descent — it only validates policy
objects and compares two of them at a time.

The repository does not vendor llama.cpp. To run production GBNF conformance,
point `LOOM_GBNF_VALIDATOR` at a built `test-gbnf-validator` binary and run:

```sh
LOOM_GBNF_VALIDATOR=/path/to/test-gbnf-validator task grammar:test
```

This is model-free. The harness checks canonical examples and additional surface
variants, then confirms that representative noncanonical forms are rejected.

### Building the validator

The binary is not distributed; earlier verification runs recorded
`LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator`, an
ephemeral local build. That checkout is pinned at
[`ggml-org/llama.cpp@1f368f3`](https://github.com/ggml-org/llama.cpp/commit/1f368f354d9edcfea9fd6a1e0989b3e7335a050f)
(`ggml : fix arm builds, unused var (#26991)`, 2026-08-13). Reproduce it with:

```sh
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /tmp/loom-llama-cpp
git -C /tmp/loom-llama-cpp fetch --depth 1 origin 1f368f354d9edcfea9fd6a1e0989b3e7335a050f
git -C /tmp/loom-llama-cpp checkout 1f368f354d9edcfea9fd6a1e0989b3e7335a050f
cmake -B /tmp/loom-llama-cpp/build -S /tmp/loom-llama-cpp -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/loom-llama-cpp/build --target test-gbnf-validator -j"$(nproc)"
```

No non-default CMake options are required — the recorded build used a plain
`Release` configuration. Any later `ggml-org/llama.cpp` revision that still
builds `test-gbnf-validator` should work equally well; the pin above is only
for reproducing the exact binary earlier verification runs used.

## Spec clarification found during implementation

The unit literal has no payload. Its canonical node is the two-element array
`[2, 0]`, represented by `(lit unit)`, as now recorded in `SPEC.md` §2.2.
