# Loom prototype — canonical S-expression surface + CBOR transcoder

This directory implements the canonical, prior-rich emission surface proposed
by `SPEC.md` §8.4 and the deterministic conversion between that surface and the
IR encoded as canonical CBOR.

**Status: working syntax/identity/scope, a partial type-directed prototype, and
a reference evaluator that runs the corpus — not a store.** There is no complete
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

## Contract versions

Each validation layer's externally observable behaviour is a **versioned
contract**, so that a future non-Python implementation can claim conformance to
"scope contract 1.0" and be held to it by differential testing against this
reference. There are seven — `parser`, `scope`, `references`, `typecheck`,
`declarations`, `refinements`, `policies` — all seeded at 1.0, recorded in
[`contracts.py`](contracts.py) and narrated in [`CONTRACTS.md`](CONTRACTS.md).

A version covers the acceptance set, the fact of rejection and its declared error
class, canonical bytes and derived hashes, the injected-resolver call
conventions, and the public entry-point signatures. It deliberately does **not**
cover error message text or the path strings inside errors — diagnostics stay
free to improve at no version cost. Read [`CONTRACTS.md`](CONTRACTS.md) before
changing any layer's behaviour; it has the bump rules and the discipline for
applying them.

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
| `typecheck.py` | Partial bidirectional checker: nominal matches, effects/handlers, `if`, `fix`/`ref`, first-order instantiation, and opt-in §3.3 refinement subsumption. |
| `matches.py` | Compatibility import shim for the checker's former name. |
| `interp.py` | The reference evaluator: a definitional interpreter for all thirteen §2.1 term tags as a CEK-style machine, with deep handlers whose continuations are multi-shot values, two's-complement `I64` wrapping, the nine assumed-base extern implementations, a caller-set fuel guard, and no ambient authority of any kind. Assumes a checked term. See [Running Loom](#running-loom) below. |
| `definition_types.py` | Immutable, scope-validated definition-type snapshots used as a store-facing `ref` resolver in tests and the corpus. |
| `refinements.py` | Translates one verification condition into one canonical SMT-LIB script, rejects everything outside the decidable fragment, and records which abstractions the translation used. |
| `obligations.py` | The typing/oracle seam: verification conditions with their producer, obligation emission to `(id, script, script-hash)` triples, §3.2.1's exactness rule, and the three-way verdict outcome. Never calls a solver. |
| `policies.py` | Validates and canonically hashes namespace policy objects, checks evidence-satisfies-requirement (`E ⊒ R`) and policy domination. |
| `contracts.py` | The versioned validation contract for each layer: version, entry points, injected-resolver conventions, and pinned artifacts, with the coverage and bump rules in its module docstring. |
| `CONTRACTS.md` | The conformance narrative for those versions — what a version covers, what it does not, what bumps it, and the discipline that keeps the record honest. |
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
| `test_subsumption.py` | §3.3 refinement subsumption: with-collector success and the exact emitted condition, without-collector rejection unchanged, erased-shape disagreement rejecting regardless of a collector, both `φ = true` directions for a missing predicate, per-position emission within one type comparison, and the reflexive no-op case. |
| `test_refinements.py` | Golden script bytes, sort mapping, datatype monomorphization, determinism, and fragment-refusal tests. |
| `test_obligations.py` | The §3.2.1 outcome table, one test per exactness condition (uninterpreted reference, opaque sort, erased refinement, idealizing symbol, unbounded `Int` binder), generator faithfulness, and the emission pipeline's typecheck-before-emit ordering. |
| `test_policies.py` | Pinned default-policy hash, structural rejection cases, obligation decomposition, conjunctive selector matching, `E ⊒ R` satisfaction, and domination (including the deliberately incomplete rules test) and the §12 worked example's arithmetic. |
| `test_externs.py` | Pinned identities for the nine assumed-base externs, kind/arity/artifact/ABI rejection cases, polymorphism and capability-honesty refusals, registry resolution, the `extern` obligation kind, the §3.2.1 interpretation table over extern hashes, and a demonstration that a hypothesis conjoining two comparisons with `and` now translates deterministically. |
| `test_contracts.py` | Pins every contract version, and checks the record against the code: entry points resolve and are callable, resolver conventions and pinned artifacts exist, the four Watch-named layers are versioned, and `CONTRACTS.md` states each current version. |
| `test_interp.py` | The evaluator against the corpus: every fixture run to a value, the list eliminators over concrete lists with hand-computed results, `mapPoly` proven behaviourally identical to `map`, the clock/rand fixtures under deterministic stubs including the pinned evaluation order, the multi-shot `rand/resample` acceptance test, deep-vs-shallow and innermost-handler probes, the `abs`-at-`INT_MIN` wrap, extern-table completeness in both directions, and the refusals (hole, unhandled `perform`, fuel exhaustion, unresolved `ref`, reference cycle). |
| `test_corpus.py` | Corpus declaration keys, fixture canonicity and pinned identity, declared validation tier, declared effect-freedom (enforced in both directions) with closed builtin-only rows, dependency order, the §3.2.1 obligations with their pinned script hashes and expected verdicts (also both directions, plus an optional solver run), and the recorded expressiveness limits (two of them re-pinned as lifted). |
| `store_admit.py` | The store's admission oracle: runs an object through the existing validator layers and emits the sidecar the Rust store cannot produce for itself — kind, type surface, dependency edges, provenance, contract versions — as deterministic bytes. Consumes the layers; changes none of them, so no contract moves. See [the store plan](../docs/plans/2026-08-14-store-v0.md). |
| `test_store.py` | Admission-sidecar properties (determinism, declaration-mirror and surface round trips, dependency edges excluding identity slots, typed refusals) and the store's acceptance gate: `StoreResolver` proven behaviourally identical to `ExperimentResolver`, including byte-identical prompt assembly over every (task, regime) pair. |
| `experiment/` | The §8.4 masked-generation experiment's Phase A harness, which only ever *consumes* the layers above. See [the experiment section](#the-masked-generation-experiment-phase-a) below. |
| `experiment/resolver.py` | The plan's R1 "disposable store-shaped resolver": one hash-keyed lookup surface over the declaration registry, the definition-type snapshot, and the corpus fixture bytes. No namespaces, leases, policy admission, persistence, or garbage collection, by rule. |
| `experiment/store_resolver.py` | The same lookup surface as `experiment/resolver.py`, rebuilt from a `loom-store export-resolver` document instead of from the corpus tree. Re-derives types from the reconstructed registries rather than copying the store's precomputed column, so the equivalence proof against the corpus-built resolver is not vacuous. |
| `experiment/prompts.py` | The four corpus regimes (`none`, `few_shot`, `full_corpus`, `held_out`), the corpus-drawn task set, and eight held-out compositional tasks with expected types built from corpus hashes and rendered through the canonical transcoder. |
| `experiment/backends.py` | The pluggable model seam: one callable, prompt plus optional grammar to tokens. A llama.cpp server backend (exact token counts), a `llama-cli --grammar-file` backend (refuses to estimate a token count it cannot read), a deterministic no-model stub, and Phase B's optional second seam `generate_masked` — implemented by the in-process `llama-cpp` backend and by the stub's scripted-logits path. |
| `experiment/gbnf.py` | Phase B's syntax layer: a GBNF compiler and incremental byte-level prefix oracle over `loom.gbnf`, read at run time so the grammar file stays the single source of truth. Answers "which bytes keep this prefix extendable" and "may it end here". |
| `experiment/masker.py` | Phase B's two-layer mask: the incremental type state (atom kind, de Bruijn term/type depths, prenex `forall` count), the pluggable pruners (`ref-hash`, `de-bruijn`) with per-layer toggles and timings, the vocabulary trie, and the per-token `Masker` API with R3's instrumentation. |
| `experiment/llama_ffi.py` | The condition-4 transport: about fifteen `ctypes` declarations over the pinned `libllama.so`. Refuses on an ABI mismatch, and refuses any tokenizer whose detokenization is not concatenation of token pieces — the assumption a byte-level mask rests on. |
| `experiment/live_mask_sanity.py` | The by-hand live check: loads a GGUF in process, walks corpus fixtures through the mask under the *model's own* tokenizer, and runs one masked generation. Deliberately outside `task prototype:test`. |
| `experiment/phase_b.config.json` | The shipped condition-4 run config. `backend` is empty, so the entry point refuses until an operator fills in the model, exactly as Phase A's does. |
| `experiment/evaluate.py` | The funnel — parse, scope, references, typecheck classification by error class through each layer's published `validate_source` — plus the operationalized semantic-success rule and rejection sampling's narrowing note. |
| `experiment/runner.py` | Conditions 1–3 under the shared fixed-token-budget-per-task rule, the per-draw JSONL record, and the aggregate report including the failure-distribution-by-layer table that gates Phase B. |
| `experiment/phase_a.config.json` | The shipped run config. `backend` is empty, so the one-command entry point refuses with a message naming the model-selection item that blocks it. |
| `test_experiment.py` | The whole harness end to end on the stub backend: resolver agreement with `corpus_registry.reference_type`, regime and leave-one-out construction, every held-out expected type proven well-formed as a typed hole, one canned output per contract layer, budget accounting, run reproducibility, and report generation. |
| `test_masker.py` | Phase B's mask, with no model: the grammar prefix oracle, the type state against `scope.py`'s binder rules, each pruner's proof probed where it claims one and where it abstains, the **soundness suite** (all 26 corpus fixtures × four tokenizations, the fixture's own next token never masked), and condition 4 end to end on the stub including the pruner-toggle divergences. |

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
and `nat/select`, **all now `checked`**. The first three used to be
`structural` — `typecheck.py` implemented no §3.3 refinement subsumption, so a
term met a `refine` type only by structural equality, and a plain `I64`
inhabited neither `{n | 0 ≤ n}` nor `{n | 0 < n}`, nor did `{n | 0 < n}` flow
into `{n | 0 ≤ n}`. The
[refinement-subsumption plan](../docs/plans/2026-08-13-refinement-subsumption.md)
closes that: a checking-mode mismatch that survives refinement erasure — the
two types agree once every `refine` node is stripped — is admitted as
`{x:T|φ} <: {x:T|ψ}` and emits a subtyping obligation instead of being
rejected, opt-in via a caller-supplied `obligations` collector so every call
site that existed before that plan is unaffected. `corpus/nat/widenPos`'s
pinned obligation and what the checker now emits at its one subsumption site
are the same verification condition, byte for byte; `corpus/math/abs` and
`corpus/list/lengthNat` reach `checked` the same way, but the checker's
automatic obligation at their sites is a strictly weaker (and, on a live
solver, refuted) claim than the hand-authored one already pinned for each —
see that plan's R4 for why, and `test_corpus.py`'s
`test_math_abs_and_lengthnat_checker_emitted_obligations_differ_from_the_pin`
for where it is pinned rather than smoothed over.

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

Three of the six obligations are pinned at `sat`, and each records which fact the
verification condition could not carry: refinement erasure inside data type
arguments makes `List {n | 0 ≤ n}` and `List I64` one sort, `List.size` stays
uninterpreted so nothing bounds it below, and `H` holds exactly one hypothesis so
a claim needing two premises cannot state them. All three claims are *true*, so
under the [obligation-pipeline plan](../docs/plans/2026-08-13-obligation-pipeline.md)
all three land as `undischarged` rather than `refuted` — see below. Those are
the honest boundary of "exercising §3.2.1 end to end" today; the tranche-4 plan
scopes them against the body-VC generation §3.2.1 lists as future work.

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

## Running Loom

Every layer above decides whether a term is *well formed*. `interp.py` says what
it *means* — it is the first thing here that can run a Loom program. The design
of record is
[`docs/plans/2026-08-13-reference-evaluator.md`](../docs/plans/2026-08-13-reference-evaluator.md).

```python
import corpus_registry, prelude
from interp import (corpus_digest, corpus_interpreter, i64, i64_list,
                    scripted_clock, seeded_rand)

SUB = corpus_registry.EXTERN_HASHES["I64.sub"]
I64 = [0, 2]

machine = corpus_interpreter()
fold = machine.value_of(corpus_digest("corpus/list/foldRight"))
minus = machine.evaluate([3, I64, [3, I64, [4, [4, [1, SUB], [0, 1]], [0, 0]]]])

machine.apply(fold, minus, i64(0), i64_list([1, 2, 3]))   # Literal(kind=2, value=2)
```

`foldRight (-) 0 [1,2,3]` is `1-(2-(3-0))`, which is `2`; the same arguments to
`corpus/list/foldLeft` give `-6`. Nothing but running them tells the two apart.

Four things about that snippet are load-bearing.

**The evaluator assumes a checked term.** Its precondition is that the input
passed `typecheck.validate_source`. It never re-derives a type and never
re-checks an arity — but where a checked term could not have reached a state it
still refuses with a path, so an upstream bug surfaces as a diagnosis rather than
a wrong answer.

**It has no ambient authority.** `corpus_interpreter()` supplies no clock and no
entropy. A `perform` with no dynamic handler and no caller-supplied behaviour is
an error naming the ability, the operation and the path. §2.4's capabilities are
minted only by `Interpreter.mint_capability` — no term evaluates to one — and
deterministic `scripted_clock` / `seeded_rand` stubs are *offered*, never
installed:

```python
machine = corpus_interpreter(builtins={**scripted_clock([1000, 2000]), **seeded_rand(7)})
clock = machine.mint_capability(prelude.HASHES["clock"])
machine.apply(machine.value_of(corpus_digest("corpus/clock/nowPair")), clock)
# Pair 1000 2000
```

**Handlers are deep and their continuations are multi-shot.** A `perform` splits
the frame stack at the innermost matching handler; the operation clause runs
*outside* the handler (which is what discharges the ability from the row) and the
continuation captures the frames in between **with the handler frame put back**,
so the resumption is handled again. The continuation is an immutable tuple, so
invoking it twice is pushing the same tuple twice. `corpus/rand/resample` invokes
one continuation with `0x00` and then with `0xff` and pairs the first result's
first field with the second result's second field:

```python
machine.apply(machine.value_of(corpus_digest("corpus/rand/resample")),
              machine.mint_capability(prelude.HASHES["rand"]))
# Pair 0x00 0xff
```

That mixed pair is unreachable for a one-shot continuation and unreachable for an
implementation that re-executes from the start. §13's residue recorded this
fixture as operationally meaningless in the prototype; it is not, any more.

**`I64` wraps, and the corpus proves it hurts.** §3.2.1 states the fidelity limit
from the solver's side — "`Int` does not wrap, so a proof that depends on 64-bit
overflow is unsound", with `-` among the symbols "whose `Int` meaning departs
from `I64`'s wrapping meaning". The runtime is the other side of that sentence:

```python
machine.apply(machine.value_of(corpus_digest("corpus/math/abs")), i64(-2**63))
# Literal(kind=2, value=-9223372036854775808)   ← negative
```

`corpus/math/abs` declares `I64 -> {v : I64 | -1 < v}`, and at `INT_MIN` it
returns a negative number: a definition that is provable over SMT-LIB `Int` and
false on hardware. That is exactly the case the obligation pipeline's **reserved**
countermodel-validation rule exists to catch — "substitute the model into the
original Loom terms and evaluate under the real semantics" (§3.2.1), which needed
an evaluator. This is the evaluator. Enabling the rule is a separate change;
`obligations.py` is untouched.

Divergence never hangs the suite: `fix` runs directly (§2.5 makes totality an
oracle obligation, not an evaluation-time one, and neither `k` nor `measure` is
consulted at run time), and a caller-set **fuel** budget ends any run that
outlives it with an explicit `FuelExhausted` carrying a path. Because the machine
is a loop rather than a recursive function, Loom's control depth never touches
CPython's stack, so the fuel guard is the *only* thing that stops a long run.

`interp.py` is deliberately **not** in `contracts.py`: a validation contract
versions an accept/reject decision and pinned canonical bytes, and the evaluator
has neither — its acceptance set is whatever `typecheck` accepted, and it emits
values.

## The masked-generation experiment (Phase A)

`experiment/` is the harness for §8.4's central hypothesis — whether an LLM
generates useful canonical Loom programs more reliably under grammar and
type-directed constraints. The design of record is
[`docs/plans/2026-08-13-masked-generation-experiment.md`](../docs/plans/2026-08-13-masked-generation-experiment.md);
what was built and why is
[`docs/plans/2026-08-13-experiment-phase-a.md`](../docs/plans/2026-08-13-experiment-phase-a.md).

It is a consumer of this prototype and never a part of it. Every checker layer
is reached through its published `validate_source` entry point, so the funnel
measures the layers that actually ship rather than a copy of them, and nothing
in `experiment/` is on the road to the store.

Phase A runs three of the plan's four conditions:

1. `unconstrained` — no grammar.
2. `gbnf` — sampled under `loom.gbnf`, so syntax cannot fail.
3. `gbnf+rejection` — sampled under the grammar, the full checker run on each
   completed definition, and a rejected draw redrawn with the rejecting layer's
   error handed back. This is per-token masking's real economic rival.

Condition 4 (`gbnf+typemask`) is Phase B's and is described in [its own
section](#phase-b-the-type-state-masker-condition-4) below. Nothing in
conditions 1-3 changed when it arrived: a Phase A run's records, summary and
report are byte-for-byte what they were.

All conditions are compared under one rule — a **fixed total token budget per
task**, spent across as many draws as it takes, with accepted definitions
counted inside it. The runner cannot express a per-attempt budget, because that
would make masked decoding's late-and-expensive failures incomparable with
unconstrained generation's early-and-cheap ones.

```sh
task experiment:phase-a -- --dry-run     # shape and upper-bound token cost, no model
task experiment:phase-a                  # refuses until a model backend is configured
LOOM_EXPERIMENT_CONFIG=my-run.json task experiment:phase-a
```

The shipped config has no backend, so the second command exits 2 with a message
naming the model-selection item that blocks it. A live run needs three things
from the operator: a backend (`llama-server` with a `server_url`, or
`llama-cli` with a `binary` and a GGUF `model_path`), a recorded
`model_identity` — refused if empty, because the plan requires the model to be
recorded *before* the run rather than reconstructed after it — and `hardware`.

Output lands in `output_dir` (git-ignored by default): `records.jsonl` with one
record per draw, `summary.json`, and `report.md`. The report's load-bearing
table is the **failure distribution by checker layer** over grammar-constrained
draws, which is the input Phase B's masker design is gated on.

`task prototype:test` runs the whole harness against a deterministic stub
backend that emits one valid corpus surface and one output broken at each of the
four contract layers, so the funnel, the budget accounting and the report are
all tested without a model.

## Phase B: the type-state masker (condition 4)

Condition 4 does not hand the model a grammar at all. It masks logits at every
decoding step, so syntax errors and the pruned classes of type error become
*unreachable* rather than rejected after the fact. The plan of record is
[`docs/plans/2026-08-13-experiment-phase-b.md`](../docs/plans/2026-08-13-experiment-phase-b.md);
B1 (the profile-independent core) is built, B2 (pruner priority from Phase A's
failure distribution, and the live matrix) is gated on Phase A reporting.

Two layers, both byte oracles, composed into one memoized transition and walked
once per step over a trie of the token pieces:

1. **Syntax** — `gbnf.py`, an incremental prefix automaton over `loom.gbnf`.
   Ours rather than llama.cpp's, so the soundness suite runs with no model on
   every `task prototype:test` and the grammar file stays the single source of
   truth.
2. **Type state** — `masker.py` tracks which grammar atom is being written and
   the de Bruijn depths in force, and pruners veto bytes. Two ship, each
   toggleable and individually timed: `ref-hash` (a hash atom must stay a prefix
   of a digest the resolver can resolve) and `de-bruijn` (a `var`/`tyvar` index
   must stay below the binder depth — including refusing the `v` of `var`
   outright where nothing is in scope).

**Soundness is the property everything else is subordinate to.** A pruner may
veto a byte only where it can *prove* no completion of the current atom reaches
an accepted definition; where it cannot prove — a `handle` operation body, whose
binder count needs ability resolution a byte prefix does not carry — it
abstains and the fact is recorded. `test_masker.py` walks all 26 corpus fixtures
under four tokenizations and asserts the fixture's own next token is never
masked, which is the tokenizer-boundary case that matters: the mask works on
*model tokens* while the grammar works on *bytes*, so a token that ends
mid-hash has to be handled rather than assumed away.

The transport is `experiment/llama_ffi.py` — `ctypes` over the pinned llama.cpp
build's `libllama.so`, the same engine `llama-server` runs for Phase A. No PyPI
dependency is added; `llama-cpp-python` was rejected because it ships
source-only and would mean building a second, differently pinned copy of
llama.cpp, which is the engine identity the comparability criterion asks us to
hold fixed. Wall clock is therefore **not** comparable across the Phase A /
Phase B line; the report says so, and the comparable numbers are accepted
definitions per token and the per-token mask overhead.

```sh
LOOM_EXPERIMENT_CONFIG=experiment/phase_b.config.json task experiment:phase-a
task experiment:mask-sanity -- --fixtures 0    # live: real tokenizer, real logits
```

A live condition-4 run needs `backend: "llama-cpp"`, a GGUF `model_path`, a
recorded `model_identity`, and optionally `llama_lib` (or `LOOM_LLAMA_LIB`) when
the pinned build is not at its default path.

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

A structural mismatch that survives one more test is SPEC.md §3.3's
subsumption rather than a type error: erase every `refine` node from both the
synthesized and expected type (recursively, including inside `data` type
arguments and `fn` domains/codomains, exactly as §3.2.1's own erasure works)
and compare what remains. Erasure disagreement is a genuine mismatch, reported
exactly as before. Erasure agreement means the two types differ only by their
refinement predicates, at one or more positions — walked in parallel, one
subtype obligation per position, a missing predicate on either side standing
for `true` (§3.2.1: "a bare `T` is `{x:T|true}`"). This never calls a solver
(SPEC.md §3.2.1's R1, [obligation-pipeline plan](../docs/plans/2026-08-13-obligation-pipeline.md));
it only fires when the caller supplies `MatchChecker`/`validate_source` an
`obligations` collector list, into which every admitted site's
`obligations.VerificationCondition` is appended. With no collector — every
call site that predates the
[refinement-subsumption plan](../docs/plans/2026-08-13-refinement-subsumption.md)
— subsumption never fires and a mismatch is rejected exactly as it always
was, which is what makes the change a MINOR contract bump (`typecheck`
1.0 → 1.1) rather than a MAJOR one.

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
by a human running the script, not by this prototype. Alongside the script it
now records what it had to abstract away — uninterpreted references, opaque
sorts, dropped refinements, which interpreted symbols it used, and whether a
`match` bound an `Int`-sorted field — as facts, taking no position on what they
mean.

`obligations.py` is the seam between typing and the oracle, and it is where
those facts become a decision. It implements `SPEC.md` §3.2.1's pipeline —
typing emits obligations, a later pass discharges them, admission consults the
resulting evidence — as `emit_definition`, which typechecks a definition and
*then* yields one `(obligation-id, script, script-hash)` triple per obligation,
so an ill-typed definition emits nothing. It also implements the verdict rule: a
solver answer is a raw fact, and the obligation's outcome is `proved`,
`refuted`, or `undischarged` depending on that answer plus the script's
**exactness**. A script is exact when it was built by a producer §3.2.1
specifies (v0.1: refinement subtyping only — a hand-authored body summary is
not) and when the translation abstracted nothing away: no `declare-fun`, no
`declare-sort`, no erased refinement, no `+ - * div mod abs` (SMT-LIB `Int` does
not wrap where `I64` does), and no `Int`-sorted `match` binder outside the reach
of the domain axiom. Only a `sat` over an exact script refutes; every other
`sat` is `undischarged`. Nothing in the module calls a solver, and a test
asserts that from the source.

Across the six pinned corpus obligations that rule leaves the three `unsat`
cases `proved` and all three `sat` cases `undischarged`, so no correct
definition is rejected. One result is worth reading twice:
`corpus/nat/select`'s script *is* translation-exact — it uses only `=`, `ite`,
and `<` over domain-bounded `Int` variables — and what stops its countermodel
from being a refutation is the other half of the rule. Its verification
condition's `outer_context` spells the two branch arguments `I64` while the
definition's type spells them `{n | -1 < n}`, so the premises were dropped when
the condition was *authored*, one stage before §3.2.1's erasure would have
acted. `test_corpus` pins that finding so it cannot be smoothed away by a later
edit.

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
