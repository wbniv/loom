# Plan — The production implementation language

**Date:** 2026‑08‑14
**Status:** Decided — **Rust**, with migration **deferred** behind named triggers
**Decides:** `TODO.md`'s promoted production-language item (Watch trigger (a) met)
**Depends on:** [Versioned validation contracts](2026-08-13-validation-contracts.md) · [Masked-generation experiment](2026-08-13-masked-generation-experiment.md) · [Experiment Phase B](2026-08-13-experiment-phase-b.md)

This is a **decision record**. It authorizes no implementation and contains no
implementation code. Its output is a language choice, a migration order stated in
contract terms, and the conditions under which migration starts.

No visible surface, so this plan carries no mockups.

## Objective

Answer two questions that the promoted TODO item runs together, and keep them
apart because they have different answers:

1. **Which language**, if the Python validation engine is replaced?
2. **When** does replacement start?

The item was promoted on trigger (a) — *"two consecutive corpus tranches require
no canonical IR/tag changes **and** the parser, scope, reference, and type-checking
contracts are versioned."* Tranches 3 and 4 satisfied the first clause;
[`contracts.py`](../../prototype/contracts.py) at 1.0 across all seven layers
satisfied the second. Trigger (a) is a **stability** signal — it says the IR has
stopped moving, so a port would not be re-done. It is not a **performance** signal
and it is not a deadline. Trigger (d) is the performance signal, and §"Trigger (d),
computed" below shows it is not met by a wide margin.

The verdict is therefore split: **Rust is the answer to (1), recorded now while it
is cheap to record; the answer to (2) is "not yet", with four measurable triggers.**

## The Watch triggers, scored

The original Watch entry (recovered from `TODO.md` history) promotes on **any** of:

| | Trigger | Status |
|---|---|---|
| (a) | Two consecutive corpus tranches with no canonical IR/tag change **and** parser/scope/references/typecheck contracts versioned | **Met** — tranches 3 and 4; contracts 1.0 (typecheck 1.1) |
| (b) | Type-directed masking or validation integrated into an interactive generation loop | **Partially met** — B1 landed the per-token masker over real `libllama`; there is no interactive loop, and condition 4 has not run |
| (c) | The prototype must run as a persistent or security-sensitive service | **Not met** — the §5 store is unbuilt; the experiment resolver is deliberately in-memory and disposable |
| (d) | Profiling shows Python consumes ≥ 25 % of an agreed end-to-end latency budget | **Not met, by 25×** — see below |

Only (a) fired. It is the one trigger that says *decide*, not *migrate*.

**A caveat trigger (a) does not carry, which this study adds.** Trigger (a) reads
IR stability off the **corpus**. Phase A reads it off the **generator**, and the
two disagree: of 43 grammar-constrained draws, **25 died at `parse`** — the
dominant post-syntax failure layer, and the layer Phase B is gated to prune first.
The corpus stopped forcing surface changes; the model is still telling us the
surface is hard to emit. If the response to that is a surface change — a more
model-friendly canonical form — it is a `parser` **MAJOR** bump by
[`CONTRACTS.md`](../../prototype/CONTRACTS.md)'s table, and `parser` is precisely
the layer this plan sequences first. Porting the parser before Phase B has spoken
risks paying for it twice. This is recorded as deferral trigger **M3**.

## The workload, measured

### The masker is 0.03 % of decode

B1's live sanity run (`experiment/live_mask_sanity.py`, real `libllama`,
Qwen2.5‑Coder‑1.5B Q4_K_M, 151,936‑token vocabulary) measured, over a 16‑token
draw with the full mask stack active:

| quantity | value |
|---|---|
| `mask_seconds_per_token` (blended, warm) | **0.19 ms** |
| `mask_seconds_per_token_uncached` (cold) | **2.14 ms** |
| `mask_cache_hit_rate` | 0.9375 |
| `mask_fallbacks` | 0 |
| CPU decode, same box (i7‑1185G7, CPU‑only) | ~700 ms/token |
| **mask share of decode** | **0.027 %** |

The 0.19 ms figure is already the blended average at that hit rate, not the
best case.

**What this does to the "Python is too slow" assumption: it destroys it for the
single-stream masking path.** A 30× speedup from a compiled language, applied to
0.027 % of the critical path, returns 0.026 % of decode wall clock. The masker was
the presumed motivation for leaving Python and it is not one. Any honest reading of
this datum has to concede that the performance argument for migration, *as
currently measured*, does not exist.

### Trigger (d), computed

The threshold is 25 % of the end-to-end latency budget. Decode is the budget.

| decode configuration | decode ms/token/seq | mask share, warm (0.19 ms) | mask share, cold (2.14 ms) |
|---|---|---|---|
| CPU‑only, batch 1 — **measured** | 700 | **0.03 %** | 0.31 % |
| GPU L4, batch 1 — brief's figure | 20 | 0.96 % | 10.7 % |
| GPU L4, batch 1 — brief's figure | 15 | **1.28 %** | 14.2 % |
| GPU L4, batch 1, bandwidth-optimal (~1.0 GB weights / 300 GB/s) | ~4 | 4.8 % | 53 % |
| GPU L4, batch 32, step 42 ms | 1.31 | 15 % | — |
| GPU L4, batch 32, step 23 ms | 0.72 | **26 %** | — |

**Moving decode to the GPU raises the mask from 0.03 % to ~1 %** — a 40× relative
increase that still lands 25× below the trigger. Trigger (d) is not close to met
in any single-stream configuration.

### The only configuration that reaches 25 % is batch serving, and it is unmeasured

Per-sequence decode amortizes with batch size; **per-sequence masking does not**.
At batch `B` with GPU step time `T_step(B)`, effective decode per sequence is
`T_step(B)/B` while mask cost stays 0.19 ms per sequence per token. The trigger
fires when `0.19·B / T_step(B) ≥ 0.25`.

The answer depends entirely on how `T_step` scales, which this study cannot
measure:

- **Compute-bound model** (`T_step ≈ 20 + 0.1·B` ms — ~3 GFLOP/token at ~30 TFLOPS
  effective): trigger fires at **B ≈ 30**.
- **Bandwidth-dominated model** (`T_step ≈ 20 + 0.7·B` ms): trigger fires at
  **B ≈ 333**, i.e. never in practice.

An order of magnitude apart on an assumption neither this plan nor Phase A
measured. **That measurement is B2's, and it is deferral trigger M1.** Recording
the range rather than picking one is the point: the honest statement is *"trigger
(d) does not fire at batch 1, and whether it fires at realistic batch sizes turns
on a slope we have not measured."*

**The mechanism, if it does fire, is the GIL, not interpreter speed.** At batch 32
the masker consumes 32 × 0.19 ms = **6.1 ms** of CPU per decode step, and under
CPython that work is serialized onto one core no matter how many are idle. A
compiled implementation spreads it across cores; so, notably, would free-threaded
CPython. That alternative is priced in "Rejected alternatives" below, because a
build flag is a much cheaper answer than a rewrite and deserves to be beaten
honestly rather than ignored.

### Where Python's real cost actually is — and it is not speed

The `ctypes` shim (`experiment/llama_ffi.py`, 402 lines) hand-mirrors
`llama_model_params`, `llama_context_params`, and `llama_batch` field by field
against a pinned `libllama` header. That is an **unchecked raw-pointer surface
with no compile-time verification**, and it has already produced one real defect:
`_check_abi` pinned `n_gpu_layers` to `0` where the pinned build returns `-1`,
yielding a false negative that cost a debugging cycle. Every field added upstream
silently corrupts the struct layout until something crashes.

This is the strongest *non-performance* argument against Python in the hot path,
and it is a **correctness** argument. It is also the criterion on which the
candidate ranking is least intuitive — see FFI scoring below.

### The size of the thing being replaced

| bucket | LOC | migrates? |
|---|---|---|
| Core validation engine (`transcode`, `sexpr`, `cbor_canonical`, `scope`, `references`, `typecheck`, `declarations`, `refinements`, `policies`, `obligations`, `definition_types`, `matches`, `prelude`, `contracts`) | **3,363** | yes, layer by layer |
| `corpus_registry.py` (mostly pinned data) | 856 | as data, not code |
| `interp.py` (reference evaluator) | 997 | not until execution is served |
| Experiment harness (`runner`, `backends`, `prompts`, `evaluate`, `resolver`, `gbnf`, `llama_ffi`, `live_mask_sanity`, `masker`) | 4,178 | only `masker.py` (887), only if M1 fires |
| Tests | 5,718 | become the differential fixture corpus, stay Python |

**3,363 lines with zero third-party dependencies.** Every import in the core is
stdlib or local; canonical CBOR is 65 hand-written lines. That cuts both ways and
both matter:

- The port is genuinely tractable — this is not a compiler with an LLVM dependency.
- **There is no library leverage to lose by leaving Python, and none to gain by
  arriving anywhere.** Ecosystem breadth, normally a dominant criterion, is nearly
  irrelevant here; ecosystem *stability* is not.

## Rules

### R1 — Two decisions, kept separate

*Which language* is decided now. *When to migrate* is decided by triggers, not by
this document's date. Conflating them is how a language decision becomes a
schedule commitment nobody costed.

### R2 — The criteria, weighted by discriminating power

The TODO names eight criteria. They do not carry equal weight for **this**
codebase, and pretending they do produces a matrix that flatters the prior. Weights
are justified per row; two criteria turn out to be near-inert and are recorded as
such rather than padded.

| # | Criterion | Weight | Why that weight |
|---|---|---|---|
| 1 | Deterministic performance | 2 | Measured non-critical (0.03 %/~1 %). Matters only in the batched case, and there it separates *compiled from interpreted*, not Rust from Zig from Go |
| 2 | Memory safety | 3 | The §5 store is append-only, network-facing, and parses untrusted content-addressed bytes. Trigger (c) territory |
| 3 | Closed IR types | **5** | The IR *is* a closed tagged union (8 object kinds, numbered term tags). `CONTRACTS.md` prices a silent mis-acceptance as a **MAJOR** bump — the exact defect class an exhaustive-match compiler eliminates. This is the project's central correctness risk |
| 4 | CBOR byte-exactness | 1 | **Near non-discriminating.** Canonical bytes must not be delegated to a library's reading of "canonical"; the encoder is hand-rolled in every candidate (65 Python lines → 150–250 anywhere) |
| 5 | WASM, both directions | **4** | §5.1.3 and §11 make externs WASM components pinned by hash — **the host must embed a WASM runtime**. Separately, in-browser corpus/playground validation wants the validator *compiled to* WASM. Two different requirements; few languages are strong at both |
| 6 | FFI (llama.cpp) | 2 | Per-token path today, and the site of the one shipped ABI defect |
| 7 | SMT integration | **0** | **Non-discriminating, recorded not padded.** `obligations.py:8` — *"Nothing in this module calls a solver."* Script emission is string building; invocation is subprocess. Identical in every candidate including Python |
| 8 | Deployment | 2 | Single static binary is the target; several candidates achieve it |
| 9 | Ecosystem risk | **4** | The project's thesis is byte-stable identity and versioned conformance over years. A substrate with its own breaking-change cadence is a *structural* mismatch, not an inconvenience |
| 10 | Implementation cost | 3 | 3,363 LOC + a differential harness. Real, but bounded |

### R3 — Candidates evaluated in full: Rust, Zig, Go. OCaml screened.

Three profiles chosen because they differ on the axes that matter, not because
they are popular: **Rust** (compile-time safety, no GC, rich types), **Zig**
(manual memory, C-grade FFI, maximal byte control, pre‑1.0), **Go** (GC safety,
maximal stability, minimum implementation cost, minimal type expressiveness).
**OCaml** is screened as the ML-family representative because its type-system fit
to a checker is the best in the field and that deserves to be stated before it
exits.

#### Rust

- **Closed IR types (5):** `enum` + exhaustive `match`. The single best argument
  for Rust here: the IR's 8 object kinds and numbered term tags become a sum type
  the compiler refuses to let you handle incompletely. Adding term tag 12 (`if`)
  would have produced a compile error at every site that must learn about it —
  which is exactly the review the Python version does by hand.
- **Memory safety (5):** compile-time, including temporal safety. Alone in the
  field on that.
- **WASM (5):** the only candidate strong in *both* directions — `wasmtime` is a
  first-class Rust crate for embedding extern artifacts, and
  `wasm32-unknown-unknown` + `wasm-bindgen` is the best-supported browser target
  of any systems language. Given criterion 5's weight, this is where Rust pulls
  clear.
- **Deterministic performance (5):** no GC, no runtime.
- **CBOR (4):** hand-rolled regardless; `ciborium`/`minicbor` are live if wanted
  (`serde_cbor` is unmaintained — an ecosystem-churn data point, and irrelevant
  once the encoder is ours).
- **FFI (4):** `bindgen` at build time, or `llama-cpp-2`. Better than hand-mirrored
  `ctypes`, worse than Zig. `unsafe` blocks make the raw-pointer surface *visible
  and greppable*, which is the property the `_check_abi` defect wanted.
- **Deployment (5):** static musl binary.
- **Ecosystem risk (4):** editions plus a real stability promise. Crate churn is
  genuine, and this codebase's ~zero dependency surface makes it nearly moot.
- **Implementation cost (2):** the weakest score. Steepest curve of the three; the
  registry's hash→object graph will cost borrow-checker design work (arena +
  indices, or `Arc`, decided at port time). Estimate 5,000–6,000 Rust LOC for
  3,363 Python LOC.
- **SMT (5).**

#### Zig — the serious runner-up

Argued at full strength before it loses, because it wins outright on two criteria
Rust does not:

- **FFI (5) — best in field, and it deletes a real defect.** `@cImport("llama.h")`
  consumes the header directly: no hand-mirrored structs, no `bindgen` build step,
  no `_check_abi` plausibility heuristic. The 402‑line `ctypes` shim becomes an
  import line. Nothing else scores this.
- **Deterministic performance (5) and CBOR (5):** explicit allocators make
  **arena-per-validation** natural — allocate one arena per definition check, free
  in O(1), zero fragmentation, no GC, no refcount traffic. That maps onto this
  workload better than any other memory model here, and byte-level control for
  canonical CBOR is Zig's home ground.
- **Closed IR types (4):** tagged unions with exhaustive `switch`. Genuinely close
  to Rust; loses only on the absence of borrow-checked sharing and
  `#[non_exhaustive]`-style evolution control.
- **Deployment (5):** static binaries, and `zig cc` is an excellent cross-compiler
  in its own right.
- **WASM (3):** *splits*. The browser target is superb — small binaries, no
  `wasm-bindgen` ceremony. Host-side embedding means consuming **wasmtime's C API**
  through `@cImport` rather than a native API: workable, second-class, and it
  reintroduces exactly the hand-managed-C-boundary character that Zig's FFI score
  was earned for eliminating.
- **Memory safety (2) — the first disqualifier.** ReleaseSafe covers bounds and
  overflow; **it does not cover use-after-free or aliasing**. For the §5 store —
  persistent, network-facing, parsing untrusted bytes into content-addressed
  objects — that is a live risk class, not a theoretical one. Arena-only allocation
  mitigates temporal safety substantially (nothing is individually freed) but does
  not eliminate aliasing errors, and the store is the component where the
  consequence is worst.
- **Ecosystem risk (1) — the decisive disqualifier.** Zig is pre‑1.0 and breaks
  across minor releases: stdlib reorganizations, build-system rewrites, and async
  removed and still being redesigned. A project whose entire proposition is
  *stable canonical bytes and versioned conformance claims held for years* would
  be pinning that claim to a substrate that has not promised stability to anyone.
  This is a structural mismatch with the thesis, not a complaint about maturity —
  and it is why Zig loses despite winning FFI outright.
- **Implementation cost (3):** the language is simpler to learn than Rust, but you
  write more yourself and pay a re-port tax on each Zig release.
- **SMT (5).**

#### Go — the other serious runner-up, losing on different criteria

- **Ecosystem risk (5) — best in field.** The Go 1 compatibility promise is the
  strongest stability guarantee of any candidate and matches the versioned-contract
  ethos precisely. Code written today compiles in a decade.
- **Implementation cost (5) — best in field.** Fastest to write, easiest to
  maintain, boring in the way infrastructure should be.
- **CBOR (5):** `fxamacker/cbor` has explicit deterministic/canonical encoding
  modes — the best library story here. (Still hand-rolled, per criterion 4.)
- **Memory safety (4):** GC, no use-after-free. Data races are possible and
  unchecked at compile time.
- **Deterministic performance (3) — and the usual objection is overstated.** Go's
  GC is sub-millisecond p99 on a heap this small (a few MB of interned objects); a
  100 µs pause against a 15 ms GPU step is nothing, and *"GC pauses in a hot path"*
  is not, on these numbers, a real argument. The honest cost is different:
  interface dispatch allocates and escape analysis is opaque, so the 0.19 ms
  masking budget is harder to *reason* about than to hit.
- **WASM (2) — also splits, the other way from Zig.** `wazero` is an excellent
  pure-Go WASM runtime, so host-side embedding of extern artifacts is arguably
  *better* than Zig's C-API route. But the browser target is poor:
  `GOOS=js/wasm` ships the runtime in multi-megabyte binaries, and TinyGo is a
  different compiler with stdlib gaps that would fork the build.
- **FFI (2):** cgo works, but it forfeits the pure-Go static-binary advantage the
  moment it is used, adds per-call overhead, and complicates cross-compilation.
- **Closed IR types (1) — the disqualifier.** Go has no sum types. The IR would be
  an `interface` plus `switch v := x.(type)` with **no exhaustiveness check** —
  which is *the same failure mode as Python's integer tags and dict dispatch*,
  reproduced at higher implementation cost. Migrating 3,363 lines to buy back
  nothing on the project's highest-weighted criterion is the argument against Go,
  and it is sufficient on its own.
- **Deployment (4), SMT (5).**

#### OCaml — screened, exits on the non-core criteria

Recorded because its exit is instructive, not because it was never in contention.

- **Closed IR types (5) — the best fit in the entire field, better than Rust's.**
  Variants, exhaustive matching, and GADTs are what ML was designed for; a
  bidirectional typechecker is idiomatic OCaml at a fraction of the code. If this
  decision were scored on criterion 3 alone, OCaml wins it.
- **Memory safety (4), deterministic performance (3)** (GC; OCaml 5 multicore is
  young).
- **FFI (1):** `Ctypes` or hand-written C stubs, plus the runtime lock, plus care
  with a **moving GC** around foreign pointers. The per-token `libllama` path is
  precisely OCaml's worst FFI case.
- **WASM (1):** `wasm_of_ocaml` is real but young, and there is no host-embedding
  story worth scoring against criterion 5's requirement to *run* extern artifacts.
- **Deployment (3), ecosystem risk (3)** — small but stable; thin maintenance
  surface.
- **Verdict:** exits on FFI, WASM, and deployment — never on type-system fit. The
  lesson carried forward is that criterion 3's win condition is *exhaustive sum
  types*, and Rust is the candidate that has them **and** clears the other seven.

### R4 — The matrix

Scores 0–5 per criterion; weighted total out of a 130 maximum. Python is scored
alongside as the calibration baseline, because "how much does migrating actually
buy?" is unanswerable without it.

| Criterion | W | Rust | Zig | Go | OCaml | Python (status quo) |
|---|---|---|---|---|---|---|
| Deterministic performance | 2 | 5 | 5 | 3 | 3 | 1 |
| Memory safety | 3 | 5 | 2 | 4 | 4 | 4 |
| Closed IR types | 5 | 5 | 4 | 1 | 5 | 1 |
| CBOR byte-exactness | 1 | 4 | 5 | 5 | 3 | 5 |
| WASM (embed + browser) | 4 | 5 | 3 | 2 | 1 | 1 |
| FFI (llama.cpp) | 2 | 4 | 5 | 2 | 1 | 2 |
| SMT integration | 0 | 5 | 5 | 5 | 5 | 5 |
| Deployment | 2 | 5 | 5 | 4 | 3 | 2 |
| Ecosystem risk | 4 | 4 | 1 | 5 | 3 | 5 |
| Implementation cost | 3 | 2 | 3 | 5 | 3 | 5 |
| **Weighted total / 130** | | **114** | **86** | **83** | **79** | **71** |

**Batch 2** — Standard ML, Haskell, Clojure, Perl and Ruby scored against this same matrix
at these same weights in
[the batch‑2 investigation](../investigations/2026-08-14-language-eval-batch-2.md); best
total 90 (Haskell and Standard ML, tied), so Rust's 114 and this decision stand unchanged.

**Sensitivity — the result is not an artifact of the weights.** Three adversarial
re-weightings, each chosen to attack the winner:

| Re-weighting | Rust | Zig | Go | Python |
|---|---|---|---|---|
| Baseline | 114 | 86 | 83 | 71 |
| WASM demoted 4 → 1 (assume no browser target, no extern execution) | 99 | 77 | 77 | 68 |
| Closed IR types demoted 5 → 2 (assume the type argument is overrated) | 99 | 74 | 80 | 68 |
| Implementation cost promoted 3 → 5 (assume schedule pressure dominates) | 118 | 92 | 93 | 81 |

Rust wins every one, and its **28‑point margin** over the nearest rival is not
close. The matrix is doing work here rather than confirming a prior — which is
what it was asked to do.

**The calibration reading matters as much as the winner.** Go scores 83 against
Python's 71: rewriting 3,363 lines in Go buys **12 points**. Rust buys **43**. That
ratio, not Rust's absolute score, is what makes the migration worth its cost —
and it is also why "migrate to something, anything, off Python" would have been
the wrong instinct.

### R5 — Decision

> **Rust**, when migration happens. Migration does not start now.

Rust is chosen because it is the **only candidate with no criterion in the bottom
half**, and because the two criteria it wins outright — WASM in both directions,
and exhaustive closed types *together with* memory safety — are the two the
specification is actually built on (§11's WASM extern boundary; §4.1's closed IR
identity, whose failure mode `CONTRACTS.md` prices as a MAJOR bump).

Zig would have been chosen on FFI and byte control alone. It loses on temporal
memory safety for the store and on pre‑1.0 substrate churn against a decade-scale
byte-identity commitment.

Go would have been chosen on stability and cost alone. It loses on the absence of
sum types, which reproduces the exact Python defect class the migration exists to
eliminate.

### R6 — Rejected alternatives, with reasons

| Rejected | Reason |
|---|---|
| **Zig** | Ecosystem risk (pre‑1.0, breaking minors) against a byte-identity promise; no temporal memory safety in the §5 store. Wins FFI outright and would win a masker-only port |
| **Go** | No sum types — the IR's central shape is inexpressible with exhaustiveness, reproducing Python's defect class. Poor browser WASM target. Wins stability and cost |
| **OCaml** | Best type-system fit in the field; exits on FFI (moving GC + runtime lock on the per-token path), WASM (no host embedding), deployment |
| **C++** | Not evaluated in full: strictly dominated by Rust on memory safety and by Zig on build simplicity, with no criterion it wins. Recorded so its absence is a decision, not an oversight |
| **Stay on Python permanently** | Adequate today (this study's central datum) and scores 71 — but concedes criterion 3 permanently, has no WASM story in either direction (Pyodide is 6+ MB and slow; `wasmtime-py` binds a C API through `ctypes` again), and leaves the raw-pointer ABI surface unchecked. Adequate is not the same as *terminal* |
| **Free-threaded CPython (3.13t+) instead of migrating** | **The cheapest answer to trigger (d) and it must be beaten honestly, not ignored.** If M1 fires, the mechanism is GIL serialization of 32 × 0.19 ms per decode step — and removing the GIL addresses that mechanism directly, for the price of a build flag. It is therefore the **correct first response to M1**, and this plan says so: try it before porting `masker.py`. It is not an answer to criteria 3, 5, or 6, so it defers migration rather than cancelling it |
| **Rewrite everything at once** | Forfeits differential testing. `CONTRACTS.md` exists precisely so a replacement lands layer by layer against a live oracle; a big-bang port has no gate to pass |
| **Port `masker.py` first** (the hot path) | Intuitive and wrong. It is 0.03 % of decode, it belongs to no contract, and it has no byte output — so it is the layer with the *weakest* differential gate and the *least* payoff. Parser first is the opposite on all three counts |

### R7 — Migration sequencing, in contract terms

Two tracks. They are independent and only one of them is a migration.

**Track G — greenfield (no contract, no oracle, no port).** The §5 store is
unbuilt. When it is built, it is built in **Rust from the first line**. This costs
zero differential-testing debt, produces the first production Rust in the project,
and buys the team's Rust competence *before* the port track needs it. It is
sequenced first not because it is urgent but because it is the only Rust work with
no migration cost at all. Trigger **M2** is what starts it.

**Track P — the port, in contract order.** Prerequisite, belonging to no contract:

- **L0 — the differential harness.** A JSON-lines export from the Python
  reference: `{input, verdict, error_class, canonical_bytes_hex, identity_hash}`
  over the 26 corpus fixtures, the 5 examples, and **every rejection case in the
  5,718 lines of tests**. Built in Python (it is a Python-side export), consumed by
  Rust. This is the *only* new infrastructure the migration requires, and it must
  exist before any layer is ported.

Then, in order, with the gate each layer must pass:

| # | Contract | Ver | Gate to become authoritative |
|---|---|---|---|
| 1 | `parser` | 1.0 | Same accept/reject on every harness input; same `SurfaceError` class; **byte-identical canonical CBOR and identical 32‑byte identity** for every accepted input; byte-identical rendered surface on the inverse direction |
| 2 | `declarations` | 1.0 | Byte-identical declaration bytes and hashes; `DeclarationError` on the same set. **Jumps ahead of `references`** — `references` resolves *against* declaration hashes, so it cannot be gated before this exists |
| 3 | `scope` | 1.0 | Same accept/reject; `ScopeError`; plus the `AbilityArityResolver` injection convention reproduced, **including the `None` and raising cases**, which `CONTRACTS.md` makes part of the contract |
| 4 | `references` | 1.0 | Same accept/reject; `ReferenceError`; against a registry loaded from the same pinned declaration bytes |
| 5 | `typecheck` | 1.1 | The largest layer (605 LOC). Same accept/reject; `TypingError`; `ReferenceTypeResolver` injected identically. §3.3 refinement subsumption is opt-in and gated separately |
| 6 | `refinements` | 1.0 | **Byte-identical SMT‑LIB script text and identical SHA‑256**; identical refusal set outside the decidable fragment (`SmtError`). A strong and cheap gate — the output is text |
| 7 | `policies` | 1.0 | Canonical policy bytes and hashes; obligation-id decomposition; identical `E ⊒ R` and domination verdicts |

**Why `parser` first** is the reason `CONTRACTS.md` already states: it is the only
layer whose output is *bytes*, so it is differentially testable with zero
scaffolding beyond L0, and byte-equality is the strongest gate available. Every
later layer's gate is an accept/reject bit plus an error class — weaker evidence,
and worth reaching only after the byte layer is trusted.

**Authority handover rule.** A layer becomes authoritative only when (i) it passes
its gate on the full fixture set, **and** (ii) Python has run in shadow beside it
for one complete corpus tranche with zero divergences. Until both hold, **Python's
verdict wins on conflict.** A contract version is not re-derived by the Rust
implementation — it is *claimed against* the Python reference, which is what
`CONTRACTS.md` means by "claim scope contract 1.0".

**Version discipline during the port.** A port that changes no behaviour bumps
nothing (`CONTRACTS.md`: refactors and performance are "none"). If the Rust
implementation is found to reject something Python silently mis-accepted, that is
a **MAJOR** bump on both, not a bug-fix exemption — and finding such cases is a
*benefit* of the port, so it must be budgeted as version churn rather than
discovered as a surprise.

### R8 — What stays Python, permanently

- **The differential oracle.** Python *is* the specification of record until every
  contract is at parity, and it remains the cross-check afterwards. Deleting it
  deletes the ability to detect a Rust-side regression against 1.0. This is not a
  transitional stance.
- **The experiment harness — 4,178 lines** (`runner`, `backends`, `prompts`,
  `evaluate`, `resolver`, `gbnf`, `llama_ffi`, `live_mask_sanity`). Research code,
  throwaway-shaped, cost dominated by model inference. Rewriting it would cost more
  than it can ever save. Only `masker.py` (887 lines) is a migration candidate, and
  only if M1 fires *and* free-threaded CPython does not resolve it.
- **`contracts.py` / `test_contracts.py`** as the version registry — it is data,
  readable by both implementations.
- **`interp.py`** (997 lines, the reference evaluator), unless and until execution
  becomes a served operation.
- **Terraform, scripts, and experiment infrastructure.**

### R9 — Deferral triggers: what starts the migration

Migration starts when **any** fires. Each is measurable; none is a date.

- **M1 — mask overhead ≥ 25 % of decode in the deployed configuration**, measured
  by B2's instrumentation at the batch size actually served (not modelled — §"The
  only configuration that reaches 25 %" shows the modelled answer spans B ≈ 30 to
  B ≈ 333). **First response is free-threaded CPython, not a port**; escalate to
  porting `masker.py` only if that fails to clear the threshold. Restates trigger
  (d) with the denominator specified.
  *Measured (2026‑08‑14, the complete 773-draw condition-4 run): mask share
  of masked-draw latency is **10.4 %** (3.15 ms/token warm, 6.69 cold, on an
  L4 at single-stream decode) — **M1 does not fire.** The deferral holds
  with a 2.4× margin in the deployed single-stream configuration; the
  B ≫ 1 served-batch case remains the only path to M1, tracked as a
  narrowed TODO Watch item.* (Historical caveat kept for provenance: the
  12–17 ms/token readings in launch 2's salvaged partial were symptoms of
  the since-fixed type-state memo defect, not a measurement.)
- **M2 — the §5 store leaves memory.** The first persistence or network work starts
  Track G, in Rust, immediately. Restates trigger (c). This is the most likely
  trigger to fire first, and it is the cheapest, because it is greenfield.
- **M3 — the surface stops moving.** `parser` holds at its current version across
  two further corpus tranches **and** Phase B's condition‑4 run completes without
  forcing a surface change. Until then, porting the parser risks paying a `parser`
  MAJOR twice. This is the trigger trigger (a) should have carried.
- **M4 — in-browser validation is scheduled.** A playground or corpus-serving
  surface requiring client-side validation is a WASM target Python cannot serve;
  it starts Track P at `parser`, which is also the layer a browser needs first.

If none has fired within two further corpus tranches, this record is re-opened and
re-scored rather than allowed to decay into an assumption.

## Deliberate boundary

- **No implementation.** No Rust crate, no `Cargo.toml`, no skeleton. The TODO item
  says *record the decision before any implementation*, and a skeleton is
  implementation.
- **`SPEC.md` is untouched.** This is toolchain policy, not language semantics.
- **`prototype/` is untouched** — read-only for this study.
- **No trigger-(d) verdict is claimed from Phase A.** Phase A runs conditions 1–3;
  the masker runs only in condition 4. The smoke report says so itself: *"Predictions
  4 and 5 … cannot be scored from Phase A alone: both compare against condition 4."*
- **`T_step(B)` is modelled, not measured.** Two models an order of magnitude apart
  are recorded rather than one being chosen. M1 is the measurement.

## Trigger (d) — the Phase A full run

**Status at the time of writing: not landed.** `prototype/runs/phase-a-full/`
does not exist. `phase-a-full-attempt1` **FAILED** at `2026‑08‑14T06:57:33Z` with

```
declarations.DeclarationError: registry: missing ability declaration
0000000000000000000000000000000000000000000000000000000000000001
```

— a resolver-seeding defect in the remote run, not a language-relevant fact.

**Provisional numbers are recorded above** from the Phase A **smoke** report
(`2026‑08‑14T00:15:23Z`, 57 draws in 4,562.5 s, conditions 1–3, four regimes) and
the **B1 live sanity** run, and they are marked as such:

- Numerator — **measured, and it is the number that matters**: 0.19 ms/token warm,
  2.14 ms/token cold, cache hit rate 0.9375, zero fallbacks, over the real
  151,936‑token vocabulary.
- Denominator — decode latency, which the full run refreshes.

**The conclusion is denominator-insensitive across the whole plausible range**, and
that is why this record is not blocked on the run. Mask share is 0.03 % at 700 ms
CPU decode, ~1 % at 15–20 ms GPU decode, and ~4.8 % even at a bandwidth-optimal
~4 ms. Trigger (d)'s 25 % threshold is not approached in **any** single-stream
configuration; only batch serving reaches it, and Phase A measures no batch case
because conditions 1–3 run at batch 1 and do not invoke the masker at all.

**One paragraph slots in when the run lands**, replacing the smoke figures with the
full run's `mean lat s` column as the denominator and restating the ratio. It
cannot change the verdict — it would take a **28×** reduction in single-stream
decode latency below the brief's GPU figure to reach 25 %, which is below the
model's memory-bandwidth floor and therefore physically unavailable. **Trigger (d)
remains not met, provisionally on the denominator and definitively on the ratio's
robustness.** The definitive number is a **B2** deliverable, not a Phase A one.

## Work

1. This decision record. — done
2. Row in [`docs/plans/README.md`](README.md). — done
3. No code, no `prototype/` change, no `SPEC.md` change, no `TODO.md` change.

## Verification

This plan produces a document. Its verification is correspondingly narrow.

1. `task todo:lint`
2. `git diff --check`

## Completion criteria

- A language is named, with the runner-up named and its loss argued on stated
  criteria rather than dismissed. **Met** — Rust; Zig, with two criteria it wins
  outright.
- At least three candidates scored in full against the same matrix, plus an
  ML-family screen. **Met** — Rust, Zig, Go in full; OCaml screened; C++ and
  status-quo Python recorded.
- The matrix's result shown to be robust to adversarial re-weighting. **Met** —
  three re-weightings, Rust wins all.
- Migration sequenced in contract terms with a per-layer differential gate.
  **Met** — L0 plus seven contracts, `declarations` promoted ahead of `references`
  with the dependency stated.
- What stays Python forever, stated. **Met** — R8.
- Trigger (d) computed against its actual 25 % threshold, with the GPU case worked
  and the batched case bounded. **Met, provisionally on the denominator** — see the
  trigger‑(d) section.

## Recorded verification

### 1. `task todo:lint`

```
TODO.md: clean
```

PASS — `TODO.md` is untouched by this plan and remains conformant.

### 2. `git diff --check`

```
(no output; exit 0)
```

PASS — no whitespace errors in the staged change.
