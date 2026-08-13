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
| `declarations.py` | Validates, hashes, and registers canonical data/ability declaration and extern definition objects, including recursive data `self` types. |
| `references.py` | Resolves nominal data/ability hashes and checks explicit constructor/operation bounds and arities. |
| `prelude.py` | Canonical v0.1 builtin ability declarations, operation names, pinned hashes, and a preloaded registry. |
| `typecheck.py` | Partial bidirectional checker: nominal matches, effects/handlers, `if`, `fix`/`ref`, and first-order instantiation. |
| `matches.py` | Compatibility import shim for the checker's former name. |
| `definition_types.py` | Immutable, scope-validated definition-type snapshots used as a store-facing `ref` resolver in tests and the corpus. |
| `refinements.py` | Translates one verification condition into one canonical SMT-LIB script and rejects everything outside the decidable fragment. |
| `policies.py` | Validates and canonically hashes namespace policy objects, checks evidence-satisfies-requirement (`E ⊒ R`) and policy domination. |
| `corpus_registry.py` | Bootstrap-corpus data declarations with reproducible nominal keys, the nine assumed-base §11 externs (five arithmetic, four boolean/comparison) with their pinned identities and interpretation table, the registry-backed `ref`-type resolver, the seed-set manifest with its §3.2.1 obligations and pinned script hashes, and the §8.4 few-shot pairs. |
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
| `test_fix_ref.py` | Recursive-binder, measure-shape and measure-position, annotation-row, and resolver-backed `ref` resolution/refusal tests. |
| `test_instantiation.py` | First-order `forall` instantiation: monomorphic and polymorphic-caller instantiation via a typed `let`, the `corpus/maybe/mapPoly`-at-`I64` proof definition, and inconsistent-binding/unbound-`tyvar`/structural-mismatch/row-variable rejection tests. |
| `test_refinements.py` | Golden script bytes, sort mapping, datatype monomorphization, determinism, and fragment-refusal tests. |
| `test_policies.py` | Pinned default-policy hash, structural rejection cases, obligation decomposition, conjunctive selector matching, `E ⊒ R` satisfaction, and domination (including the deliberately incomplete rules test) and the §12 worked example's arithmetic. |
| `test_externs.py` | Pinned identities for the nine assumed-base externs, kind/arity/artifact/ABI rejection cases, polymorphism and capability-honesty refusals, registry resolution, the `extern` obligation kind, the §3.2.1 interpretation table over extern hashes, and a demonstration that a hypothesis conjoining two comparisons with `and` now translates deterministically. |
| `test_corpus.py` | Corpus declaration keys, fixture canonicity and pinned identity, declared validation tier, declared effect-freedom (enforced in both directions) with closed builtin-only rows, dependency order, the §3.2.1 obligations with their pinned script hashes and expected verdicts (also both directions, plus an optional solver run), and the recorded expressiveness limits (two of them re-pinned as lifted). |

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
these are definitions hand-transpiled from the Unison base library — and, in
tranche 4, from the F\* standard library — to seed `SPEC.md` §13 open problem 1,
per the
[bootstrap-corpus plan](../docs/plans/2026-08-13-bootstrap-corpus.md). Each entry
in `corpus_registry.MANIFEST` carries a name path, spec text, source attribution,
a pinned identity, and the validation **tier** it is expected to reach — `checked`
(parse, scope, references, and the type-directed match layer) or `structural`
(the first three, with the deferred layer's reason recorded). `test_corpus.py`
enforces the tier in both directions, so a `structural` entry that starts passing
the match layer fails the suite rather than keeping a stale deferral.

Transpiling the seed set established three limits of v0.1 by construction, each
pinned by a test in `test_corpus.ExpressivenessLimitTest`. All three have since
been lifted and re-pinned as the new behaviour. Two by the
[polymorphism and Bool-elimination plan](../docs/plans/2026-08-13-polymorphism-and-bool-elimination.md):
a definition's term is checked at its type's `forall` depth, so
`corpus/maybe/mapPoly` is a genuinely generic definition; and `if` (term tag
12) eliminates `Bool`, so `corpus/bool/not` — the definition that found the
limit — is now a fixture. The third by the
[measure-selection plan](../docs/plans/2026-08-13-measure-selection.md): `fix`
carries the position of its decreasing argument (`SPEC.md` §2.5), and
`corpus_registry.reference_type()` gives the match layer the assumed base as
its `ref` resolver, so a recursive definition reaches `checked` with a stored
measure stated directly — `list/foldRight` descends on its *third* argument and
measures it with `(ref #List.size)`. What remains pinned is the narrower limit
the new rule leaves in place: a measure reads one argument, so a recursion
descending on two at once, where neither decreases alone, still has to take
`div`.

Tranche 2 (the recursive slice) is now built out: `list/append`, `list/reverse`,
`list/map`, `list/foldLeft`, `list/concat`, and `list/flatMap` join
`list/foldRight`, all reaching `checked` with the measure `(ref #List.size)`
and no `div`, per the
[tranche-2 plan](../docs/plans/2026-08-13-corpus-tranche-2.md). `list/size`
itself stays assumed base (`corpus_registry.EXTERN_HASHES`), never a fixture.
`list/concat` and `list/flatMap` are the manifest's first cross-definition
`ref`s — each `ref`s `list/append` rather than re-deriving structural
recursion, and `corpus_registry.reference_type()` resolves the reference
through `definition_types.DefinitionTypeRegistry` exactly as it already did
for the assumed base, just against a manifest entry's validated type instead
of an extern's. The tranche stays monomorphic at `I64`: a genuine
`List (List I64)`-flattening `concat`, or any generic recursion over a
`forall`-bound element type, would need a second `List.size`-shaped measure
instantiated at the nested type, which is out of scope here and recorded as
residue in the tranche-2 plan.

Tranche 3 (the effectful slice) is built on top of it: `clock/now`,
`rand/bytes`, `clock/stamped`, `rand/withStub`, `clock/nowPair`,
`sample/nowAndBytes`, and `rand/resample`, all at `checked`, per the
[tranche-3 plan](../docs/plans/2026-08-13-corpus-tranche-3.md). These are the
first fixtures whose types carry a nonempty effect row or a `cap`, and they
exercise §2.4/§3.1.2 as a set rather than singly: `perform` with and without
arguments, a two-ability closed row (`rand`+`clock`, sorted bytewise), an
effectful function argument applied under the ambient allowance, a capability
threaded as an ordinary value into a `ref` whose own type carries a row, a
handler that discharges its ability and leaves the definition pure to callers,
and a handler that invokes its continuation twice. Every capability arrives as
a parameter, because §2.4 makes `cap a` unforgeable in the language; rows are
closed throughout, since `typecheck._closed_row` refuses a row variable and
the corpus plan's R2 drops Unison's ability polymorphism outright. The purity
test that used to assert every fixture was ability-free is now split in two
and keyed on the manifest's `effect_free` flag — pure entries must be pure,
entries declaring themselves effectful must actually name an ability — so the
flag is a claim checked in both directions rather than an exemption.

Tranche 4 (the refinement slice) is the first drawn from a second source — the
Apache-2.0 [FStarLang/FStar](https://github.com/FStarLang/FStar) standard
library — and the first to carry `refine` types and §6.2 obligations, per the
[tranche-4 plan](../docs/plans/2026-08-13-corpus-tranche-4.md). Six entries:
`math/abs`, `list/lengthNat`, `nat/widenPos`, `list/consNat`, `nat/applyPos`,
and `nat/select`, of which the first three are `structural`. They are
`structural` for one reason worth stating plainly: `typecheck.py` implements no
§3.3 refinement subsumption, so a term meets a `refine` type only by structural
equality — a plain `I64` inhabits neither `{n | 0 ≤ n}` nor `{n | 0 < n}`, and
`{n | 0 < n}` does not flow into `{n | 0 ≤ n}`. What *does* work is a refinement
flowing through unchanged, including inside a `(data …)` type argument, which is
what keeps the other three at `checked`.

`CorpusEntry.obligations` is the tranche's new manifest field, enforced in both
directions like `tier` and `effect_free`: a `refine` in an entry's type may not
enter the corpus without an obligation, and an obligation may not be attached to
an entry that claims none. Each `corpus_registry.Obligation` is one §3.2.1
verification condition — refinement subtyping, v0.1's only producer — with its
canonical SMT-LIB script's SHA-256 pinned (the §6.4 memo-ledger payload key) and
the solver verdict it expects. Two of the six deliberately share a script hash,
because §3.2.1 says the obligation's name never enters the script; a test
asserts they agree byte for byte. `test_corpus.CorpusObligationTest` regenerates
every script from `refinements.py` and re-hashes it, and additionally runs a
solver over each one when `LOOM_SMT_SOLVER` is set or `z3` is on `PATH` —
never a hard dependency.

Three of the six obligations are pinned at `sat`, i.e. §3.2.1 *refutes* the
verification condition as v0.1 builds it, and each records which fact the VC
shape could not carry: refinement erasure inside data type arguments makes
`List {n | 0 ≤ n}` and `List I64` one sort, `List.size` stays uninterpreted so
nothing bounds it below, and `H` holds exactly one hypothesis so a claim needing
two premises cannot state them. Those are the honest boundary of "exercising
§3.2.1 end to end" today; the tranche-4 plan scopes them against the body-VC
generation §3.2.1 lists as future work.

The instantiation gap that remained after the first lift — v0.1 could write a
polymorphic definition but not *call* one at a concrete type — is itself now
closed by the
[forall-instantiation plan](../docs/plans/2026-08-13-forall-instantiation.md):
a quantified `ref`, checked against a concrete expected type, is instantiated by
first-order matching (SPEC.md §3.1.3). `corpus/maybe/mapPoly` called at `I64`
through a typed `let` is the proof definition in
`test_instantiation.InstantiationTest`. Synthesis position is unaffected — a
quantified reference used as, say, an application's function still synthesizes
its quantified type verbatim, so a generic definition still needs a
monomorphic wrapper or a typed `let` at each use site; only the *elimination*
rule for checking position was missing.

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

`declarations.py` also validates `SPEC.md` §5.1.3 extern definition objects
`[7, type, artifact, abi]` — the FFI boundary's store form. An extern's type must
be closed and monomorphic (`forall`, `tyvar`, row variables, and `self` are all
refused), its artifact a 32-byte pin, its ABI selector non-empty NFC text, and
every ability its rows name must be matched by a `cap` parameter so §2.4's
blast-radius bound survives the boundary. There is no nominal key: `(artifact,
abi)` is the discriminator, so two externs stating the same call are one object.
`DeclarationRegistry.extern` resolves one to a type with no body, which is what a
`ref` to an extern has. The nine assumed-base externs — the five the bootstrap
corpus's tranche 2 needs plus `Bool.and`/`Bool.or`/`Bool.not`/`I64.le`, which give
§3.2.1's `and or not <=` interpreted symbols something to interpret — are pinned
in `corpus_registry.EXTERN_HASHES`; see the
[extern-object plan](../docs/plans/2026-08-13-extern-object-encoding.md) and the
[boolean-base-externs plan](../docs/plans/2026-08-13-boolean-base-externs.md).

`references.validate_source` checks nominal declaration existence, kind, and
explicit `con`/`perform`/`handle` bounds and arities. It does not establish
typing, termination, refinement validity, or evidence. The remaining oracle
layers are described in `SPEC.md` §§3, 6, and 8.

`typecheck.validate_source` is a deliberately partial type-directed layer. It
validates nominal constructors and exhaustive matches, `if` against `Bool` with
both branches at the goal type, closed function effect
rows, operation signatures and capabilities, and handlers with typed return,
operation, and continuation clauses. A definition typed `forall^p` is checked
against its quantified body, with type variables treated as opaque atoms under
structural type equality. Synthesized lambdas are pure — latent
effects require checking against an annotated row — and operation-less
abilities such as `div` cannot be handled. A term that is *checked* against a
concrete expected type and synthesizes `forall^p T` — in practice a `ref` whose
resolved type is quantified — is instantiated by first-order matching of `T`
against the expected type (SPEC.md §3.1.3); synthesis position is untouched, so
a quantified reference in application position still synthesizes its
quantified type verbatim. Row polymorphism and other unsupported nodes raise an
explicit path-aware error until their typing rules are implemented.

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
