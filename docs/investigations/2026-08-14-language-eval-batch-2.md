# Investigation — Production language, batch 2: Standard ML, Haskell, Clojure, Perl, Ruby

**Date:** 2026‑08‑14
**Type:** Investigation. Scores five further candidates against the fixed rubric of the
batch‑1 decision record. **It decides nothing.**
**Contract:** [The production implementation language](../plans/2026-08-14-production-language-decision.md)
— its R2 criteria and weights, its R3 evidence bar, and its R4 calibration column are
taken as given and are not re‑derived here.
**Verdict in one line:** nothing in batch 2 beats Rust's **114**. The best batch‑2 score
is **Haskell at 94**, and the batch‑1 DECISION stands unchanged.

No visible surface, so this investigation carries no mockups.

---

## What this is, and what it deliberately is not

Batch 1 scored Rust, Zig and Go in full, screened OCaml, and decided **Rust** with
migration deferred behind four named triggers. This document scores five more candidates
— **Standard ML, Haskell, Clojure, Perl, Ruby** — against the *same* ten criteria at the
*same* weights, so that the two batches sit in one leaderboard rather than two
incomparable ones.

Three constraints follow from that, and they are absolute:

1. **The weights are frozen.** R2's `5/4/4/3/3/2/2/2/1/0` allocation is not re‑opened. A
   re‑weighting invented to accommodate a batch‑2 candidate would retroactively invalidate
   batch 1's totals, which is the one thing a second batch must not do. Where I think a
   weight is wrong, it is recorded in [Remarks on the rubric](#remarks-on-the-rubric-not-applied-to-the-matrix)
   and applied nowhere.
2. **Batch 1's scores are the calibration, not a starting point for renegotiation.**
   Rust's `5,5,5,4,5,4,5,5,4,2` and Python's `1,4,1,5,1,2,5,2,5,5` carry over verbatim as
   the comparison columns. Where a batch‑1 score looks wrong to me — and two do — that is
   a remark, not an edit.
3. **This document does not re‑decide.** Had a batch‑2 total exceeded 114, the correct
   output would have been a loud flag and a stop. It did not, so the flag is the absence
   of one. Re‑deciding is the operator's call in either direction.

**The evidence bar, restated from batch 1's precedents**, because consistency with them is
what makes the numbers mean anything:

- **Go scored 1 on closed IR types** for having interfaces plus `switch v := x.(type)`
  with no exhaustiveness check — *"the same failure mode as Python's integer tags and dict
  dispatch"*. Any candidate whose union handling is unchecked at build time inherits that 1.
- **Zig scored 1 on ecosystem risk** for a pre‑1.0 breaking cadence against a decade‑scale
  byte‑identity promise. The criterion is about *cadence of breakage*, not about library
  count — R3 says explicitly that *"ecosystem breadth… is nearly irrelevant here;
  ecosystem stability is not."*
- **Criterion 5 requires BOTH directions.** §5.1.3 and §11 make externs WASM components
  pinned by hash, so **the host must embed a WASM runtime**; separately, in‑browser
  corpus/playground validation wants the validator **compiled to** WASM. Zig scored 3 for
  winning one direction and limping in the other; Go scored 2 for the mirror‑image split;
  OCaml scored 1 for having a young browser story and *no host‑embedding story at all*.
- **Criterion 4 (CBOR) discriminates almost nothing** — the encoder is hand‑rolled in
  every candidate — and **criterion 7 (SMT) discriminates nothing at all** and is weighted
  0 for exactly that reason. Both are scored honestly and neither is padded.

---

## R3′ — Candidate profiles

Ordered as scored. Each profile leads with the load‑bearing facts, then the scores those
facts produce.

### Haskell — the batch‑2 leader, and the one that gets closest

**What it is.** A lazy, purely functional, statically typed language with the most
expressive practical type system in either batch. GHC 9.14.1 shipped
[2025‑12‑19](https://www.haskell.org/ghc/blog/20251219-ghc-9.14.1-released.html), and
9.14 is notable for being the **first formal LTS release** under a policy
[announced 2025‑07‑02](https://www.haskell.org/ghc/blog/20250702-ghc-release-schedules.html);
non‑LTS majors continue on a ~6‑month cadence.

**Closed IR types — 5.** This is why Haskell is here. The IR's 8 object kinds and numbered
term tags become a `data` declaration; `-Wincomplete-patterns` (in `-Wall`, and promotable
to a hard error with `-Werror`) makes adding term tag 12 (`if`) a build failure at every
site that must learn about it. GADTs, `DataKinds` and type families are available if the
typechecker's own judgements want to be indexed by their own type language — which is a
genuine option here that no other batch‑2 candidate offers. This ties OCaml's best‑in‑field 5.

**FFI — 4, and this is the surprise.** Batch 1's OCaml screen exited partly on FFI ("moving
GC + runtime lock on the per‑token path"), and it is tempting to assume every ML‑family
language inherits that. Haskell does not. `foreign import ccall unsafe` is a *language
feature* compiling to a direct call with no marshalling wrapper; `safe` calls do not block
other Haskell threads; and — the fact that actually matters for the `_check_abi` defect —
**`hsc2hs` and `c2hs` derive struct field offsets from the real `llama.h` at build time**,
which is the same header‑derived guarantee that earned Rust's `bindgen` a 4. The 402‑line
hand‑mirrored `ctypes` shim's failure mode does not survive that. Deducted one for the
`safe`/`unsafe` footgun and for pinned‑vs‑movable memory discipline around foreign
pointers.

**WASM — 3, and this is the score I am least sure of in the whole document.** It splits,
like Zig's and Go's, but with a different fault line.
*Compiled to WASM:* the GHC WebAssembly backend targets `wasm32-wasi` and is real, with a
JSFFI that treats `JSVal` as first‑class garbage‑collected Haskell values, async imports
that don't block the runtime, and browser‑mode GHCi live coding. But the
[9.15 user's guide](https://ghc.gitlab.haskell.org/ghc/doc/users_guide/wasm.html) still
says it is *"still a tech preview and not included in the official bindists yet"* — the
same sentence the 9.8 guide carried in 2023 — and it ships a single‑threaded RTS with
Template Haskell restrictions in browser mode.
*Embedding a runtime:* no native `wasmtime` binding. The routes are the
[Extism Haskell host SDK](https://github.com/extism/haskell-sdk) and
[byteally/wasmedge](https://github.com/byteally/wasmedge), both of which are Haskell FFI
over a C API — workable, second‑class, and precisely the "hand‑managed C boundary"
character batch 1 penalised in Zig's WASM score.
Three years of an unchanged "tech preview" label against a criterion weighted 4 is the
uncomfortable part. **A 2 is defensible; I went 3** because both directions demonstrably
work today, which is more than OCaml's 1 and more than SML's.

**Ecosystem risk — 3.** Two majors a year, `base` API churn managed by a
[Core Libraries Committee](https://github.com/haskell/core-libraries-committee) whose
standing policy is only that code compile against *the latest three releases* without CPP
— a three‑release window is a churn budget, not a stability promise, and it is weaker than
Rust's editions. The [first LTS](https://blog.haskell.org/ghc-lts-releases/) is a real
improvement and is the single thing most likely to move this score.

**Deterministic performance — 3.** Compiled and fast, but a generational copying GC plus
*laziness* — thunk build‑up makes latency and residency harder to reason about than in any
strict compiled candidate. Same band as Go and OCaml, for a different reason.

**Memory safety — 4.** GC'd, no temporal errors, purity plus STM removes most of the
data‑race surface; not compile‑time‑enforced, so not Rust's 5.

**CBOR — 4.** `ByteString` builders give exact byte control and `Integer` is arbitrary
precision in the Prelude; `cborg`/`serialise` exist as a cross‑check oracle. Hand‑rolled
regardless, per criterion 4.

**Deployment — 3.** Native binaries, but dynamically linked against `libgmp`/`libffi` by
default, fully static musl builds are a known‑fiddly exercise, artefacts run tens of MB,
and the toolchain is multi‑GB. Below Go's 4, at OCaml's 3.

**Implementation cost — 3.** A bidirectional typechecker is close to the canonical Haskell
program and 3,363 Python lines would land well under that in Haskell. Held at OCaml's 3
rather than 4 — see [Remarks](#remarks-on-the-rubric-not-applied-to-the-matrix), where I
argue *both* are a point low and show it changes nothing.

**SMT — 5.**

**What would change this:** GHC's wasm backend leaving tech‑preview status *and* a
maintained native Wasmtime binding on Hackage would take WASM 3 → 5 (+8 → **102**); the
LTS cadence holding for two cycles would take ecosystem risk 3 → 4 (+4 → **106**). Even
both together, granted generously, leave Haskell **8 points short of Rust**. That is worth
stating plainly: Haskell's gap to Rust is not one contingent fact away from closing.

### Standard ML — the new ML‑family entrant, and what changes vs OCaml's 79

**What it is.** A language whose definition has been *frozen since 1997*. The production
implementation is [MLton](http://mlton.org/), a whole‑program, monomorphising, optimising
compiler whose stable release is **20241230** — the first since **20210107**, a four‑year
gap. [SML/NJ](https://www.smlnj.org/) runs two tracks (development at 2026.1; legacy at
110.99.9) and is the research/interactive implementation, not the deployment one.
[MPL/MaPLe](https://github.com/MPLLang/mpl) is a CMU fork of MLton adding provably
efficient nested parallelism, tutorialised at
[POPL 2025](https://popl25.sigplan.org/details/POPL-2025-tutorials/6/MPL-Provably-Efficient-Parallel-Programming).

**The scoring question this entrant exists to answer** is whether OCaml's 79 was an
ML‑family score or an OCaml score. It was mostly an OCaml score: SML lands at **88**, nine
points higher, on four separate +1s — and, importantly, on **none** of the three criteria
that actually exited OCaml.

| Criterion | OCaml | SML | Why it changed, or didn't |
|---|---|---|---|
| Closed IR types | 5 | **5** | *Unchanged — but for a different reason.* OCaml's 5 was argued on variants + exhaustive matching + GADTs. SML has no GADTs. It compensates with something batch 1 did not have available to score: **MLton's `nonexhaustiveMatch {warn\|error\|ignore}` ML Basis annotation** ([MLBasisAnnotations](https://github.com/MLton/mlton/blob/master/doc/guide/src/MLBasisAnnotations.adoc)) turns a non‑exhaustive `case`/`fn`/`fun` into a **hard compile error**, giving SML *Rust's* property rather than the ML tradition's warning. Since the IR is a first‑order closed union with no type‑indexing requirement, the GADT loss does not bite. Net: still 5 |
| Deterministic performance | 3 | **3** | *Unchanged, and the reasoning matters.* MLton's whole‑program monomorphisation and strict evaluation generate genuinely C‑class code — better than OCaml's on this workload. But **MLton has no parallelism**: the one live scenario for criterion 1 is batch serving, where the mechanism batch 1 identified is *GIL‑style serialisation of 32 × 0.19 ms onto one core*, and a single‑threaded MLton runtime reproduces that shape exactly. The ~30× constant factor rescues the arithmetic; the structure is unchanged. MPL fixes it and is a research fork. The two cancel at 3 |
| Memory safety | 4 | **4** | Unchanged. GC'd, no unsafe by default |
| CBOR byte‑exactness | 3 | **4** | **+1.** The SML Basis Library standardises `Word8Vector`, the `PackWord*`/`PackReal*` byte‑packing structures, **and `IntInf` arbitrary‑precision integers**. OCaml needs Zarith — an external C library — for CBOR bignums. For a criterion about byte exactness, having the whole toolkit inside the frozen standard is worth the point |
| WASM | 1 | **1** | **Unchanged, and it is the disqualifier.** MLton 20241230 adds *"preliminary support for `wasm32-wasi`"* ([releases](https://github.com/MLton/mlton/releases)) — real, and directly host‑runtime consumable, which `wasm_of_ocaml`'s WasmGC output is not. But criterion 5's *first* requirement is embedding a runtime to execute hash‑pinned extern components, and SML has **no host‑embedding story whatsoever**. That is the same 1 OCaml took, for the same reason |
| FFI | 1 | **2** | **+1.** MLton's `_import`/`_export` compiles to a direct call with **no runtime lock** (there is no runtime to lock) and no wrapper overhead — the per‑token `libllama` path is not SML's worst case the way it is OCaml's. Against: MLton has **no struct‑layout facility at all**, so `llama_batch` is either hand‑computed offset arithmetic (strictly worse than `ctypes`) or a hand‑written C shim linked into the program. 2 is generous and rests entirely on the shim route being clean |
| Deployment | 3 | **4** | **+1.** Whole‑program compilation yields one statically linkable native executable with no separate runtime and no dynamic loader, and community musl builds exist. Cross‑compilation is poor. This is the SML score I would defend second‑least |
| Ecosystem risk | 3 | **4** | **+1, and it is the interesting one.** The **language standard has not changed in 29 years**. Measured on the criterion as R2 actually writes it — *"a substrate with its own breaking‑change cadence is a structural mismatch"* — SML has no cadence to mismatch, and R3's *"there is no library leverage to lose"* removes the usual objection. Against a 5: the four‑year release gap, a maintainer pool countable on one hand, and — the concrete one — **no maintained TLS/networking stack that could receive a CVE patch**, which is a live concern for a network‑facing §5 store. Net 4. **This is my single most‑torn call in the document** |
| Implementation cost | 3 | **3** | Unchanged, from two effects that cancel: the *core* is cheaper than anywhere else in either batch (SML is a smaller, stricter language than Haskell and the validator is textbook SML), while the *scaffolding* is dearer than anywhere else — you write SHA‑256 for the identity hashes yourself, and the editor/formatter/package tooling barely exists |
| SMT | 5 | **5** | Unchanged and weightless |

**Verdict:** SML is the best pure *language* fit for the validator core in either batch and
it still loses by 26 points, because criterion 5 is weighted 4 and SML scores 1 on it, and
because the store's non‑core needs (networking, TLS, FFI structs) fall outside what a
frozen 1997 standard and a two‑release‑per‑decade compiler supply.

**What would change this:** if MLton's `wasm32-wasi` support matured out of "preliminary"
*and* someone wrote a Wasmtime C‑API binding, WASM 1 → 3 (+8 → **96**). Still 18 short.

### Clojure — wins ecosystem risk outright, loses on the same criterion Go did

**What it is.** A dynamically typed Lisp on the JVM, built around immutable persistent data
structures. [Clojure 1.12.0](https://clojure.org/news/2024/09/05/clojure-1-12-0) shipped
2024‑09‑05; there is no 1.13.

**Ecosystem risk — 5, best in field, tied with Go and Python.** Clojure's non‑breakage
posture is a design commitment, not a slogan: deprecated constructs from early Clojure
still run on current releases, and Hickey's
[Spec‑ulation](https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/Spec_ulation.md)
argument is explicitly that you rename rather than break. It sits on the JVM, whose
backward compatibility record is the strongest in industry. For a project whose thesis is
byte‑stable identity held over years, this is a genuine structural match — and it is the
one criterion where Clojure beats Rust.

**Closed IR types — 1, and it is decisive, exactly as it was for Go.** There are no sum
types and no static types. The IR would be tagged maps dispatched by multimethod or
`case`, with **no exhaustiveness check** — which is R3's stated Go disqualifier verbatim,
and which is *the same failure mode as Python's integer tags and dict dispatch*.
`clojure.spec` and Malli validate at runtime, which is what the Python implementation
already does. [lambdaisland/uniontypes](https://github.com/lambdaisland/uniontypes)
provides a `case-of` macro that checks coverage of an `or` spec at macroexpansion time —
real, but a small unmaintained library, opt‑in per call site, and not a property of the
type. Migrating 3,363 lines to buy back nothing on the highest‑weighted criterion is
sufficient on its own, per batch 1's Go finding.

**WASM — 2. Go's split, mirrored precisely.**
*Embedding:* [Chicory](https://github.com/dylibso/chicory) is a pure‑JVM WebAssembly
runtime that reached [1.0.0](https://chicory.dev/blog/chicory-1.0.0/) in December 2024 —
zero native dependencies, no JNI, an AOT compiler mode. This is arguably the cleanest
host‑embedding story in either batch after Rust's `wasmtime`, and it is exactly the role
`wazero` played for Go.
*Compiled to:* essentially absent. ClojureScript targets JavaScript, not WASM. GraalVM's
[Web Image](https://www.graalvm.org/latest/reference-manual/web-image/) backend
(`--tool:svm-wasm`, Oracle GraalVM 25.1+) is explicitly experimental with no networking,
and it inherits Native Image's closed‑world assumption — which collides directly with
Clojure's runtime code generation, `eval`, and reflection. Babashka proves Clojure can be
Native Image'd with sustained effort; nobody has shown the validator surviving that *and*
the Wasm backend.

**FFI — 3.** JDK 22 finalised the [FFM API](https://dev.java/learn/ffm/jextract/), and
`jextract` generates bindings **by parsing the real `llama.h`** — the same header‑derived
property that earns Rust's `bindgen` a 4. Two deductions: the generated artefact is Java
that Clojure then interops with, and the Clojure‑idiomatic alternative,
[coffi](https://github.com/IGJoshua/coffi), uses hand‑declared struct descriptions —
i.e. it reproduces the `ctypes` defect class exactly. Best FFI of the three dynamic
candidates.

**Deterministic performance — 2.** JIT warmup, JVM GC, boxing, and persistent‑structure
allocation churn against a 0.19 ms per‑token budget. Better than an interpreter; worse
than every compiled candidate.
**Memory safety — 4.** GC'd; immutability by default removes most of the data‑race surface
Go was docked for, but transients and raw Java interop remain.
**CBOR — 3.** `byte[]`/`ByteBuffer` work, but the JVM's signed `byte` and boxing friction
make byte‑exact assembly noisier than in any other candidate here.
**Deployment — 3.** An uberjar needs a JVM; Native Image works (babashka) but costs
reflection configuration and forfeits `eval`.
**Implementation cost — 4.** Concise and REPL‑driven; the port itself is cheap.
**SMT — 5.**

**What would change this:** nothing plausible. The 1 on criterion 3 is a property of the
language having no static types, and criterion 3 is weighted 5.

### Ruby — the cheapest port in either batch, and it buys 2 points

**What it is.** A dynamically typed object‑oriented language.
[Ruby 4.0.0 shipped 2025‑12‑25](https://www.honeybadger.io/blog/ruby-4/) — the version was
bumped past 3.5 to mark the 30th anniversary and the arrival of ZJIT and Ruby::Box.

**Closed IR types — 2, and this is the one place a dynamic language beats Go's 1.**
[Sorbet](https://sorbet.org/docs/exhaustiveness) supports `sealed!` modules behaving as
union types plus `T.absurd` in the `else` branch, and *"sealed classes effectively make
exhaustiveness a property of the definition, not the usage site"* — checked **statically**
by `srb tc`, with a runtime raise as backstop. That is a real closed‑union‑with‑exhaustiveness
mechanism, and it is strictly more than Go's type switch or Python's integer tags offer,
so scoring it 1 would be dishonest. It is capped at 2 because it is an opt‑in gradual
layer over a dynamic language: it holds only where `typed:` sigils are strict, escape
hatches (`T.unsafe`, `T.untyped`) are everywhere, it requires a separate checker in CI,
and its exhaustiveness has
[known interactions with generics](https://github.com/sorbet/sorbet/issues/3242).

**WASM — 2. Both directions officially exist; the browser artefact is the problem.**
*Embedding:* [wasmtime‑rb](https://github.com/bytecodealliance/wasmtime-rb) is the
**official** Wasmtime embedding, maintained under the Bytecode Alliance, sponsored by
Shopify, shipped as precompiled gems, and running untrusted code in production. On the
host‑embedding half alone this is arguably the best non‑Rust story in either batch — better
than `wazero`, which is a reimplementation rather than the reference engine.
*Compiled to:* [ruby.wasm](https://github.com/ruby/ruby.wasm) is officially maintained by
Ruby core with WASI support since Ruby 3.2 and browser‑ready npm packages. But you ship
**the whole CRuby VM**: the `minimal` profile *"shaves around 10 MB"* off the module
(while dropping `json`, `yaml`, `stringio`), and a packed Rails application weighs
[76.2 MB](https://evilmartians.com/chronicles/ruby-on-rails-on-webassembly-a-guide-to-full-stack-in-browser-action).
Go took a 2 for *"multi‑megabyte binaries"*; Ruby's are an order of magnitude past that.
Excellent half plus worse‑than‑Go half → 2.

**Ecosystem risk — 3.** Annual releases with real removals. Ruby 4.0 dropped `--rjit` and
pipe‑based `Kernel#open`; ZJIT is
[not recommended for production until 4.1](https://www.honeybadger.io/blog/ruby-4/); and
Rails‑driven gem churn is the highest‑velocity dependency environment of any candidate.
Below Python's 5 on demonstrated behaviour, not on reputation.

**Deterministic performance — 2.** YJIT is a genuine production JIT, which is more than
CPython has, and ZJIT is arriving; still an interpreter with a GC. One point above Python.
**Memory safety — 4.** GC'd; equivalent to Python's.
**FFI — 2.** `Fiddle` and the `ffi` gem are hand‑declared struct layouts — the `ctypes`
failure mode, identically. A C extension including the real `llama.h` is available, but
that is writing C, not deriving a binding, and it is equally available to Python. Same 2.
**CBOR — 4.** `String#pack`, binary strings, native bignums.
**Deployment — 2.** Interpreter plus gems, as Python.
**Implementation cost — 5, best in field.** Python → Ruby is close to a transliteration of
3,363 lines. Nothing else in either batch is this cheap.
**SMT — 5.**

**What would change this:** repo‑wide `typed: strict` Sorbet with the whole IR as `sealed!`
modules would justify 3 on criterion 3 (+5 → **78**). That is the ceiling, and it is 36
points short.

### Perl — the only candidate in either batch that scores below the status quo

**What it is.** A dynamically typed language with the strongest empirical backward‑compat
record of anything here. [Perl 5.42.0 shipped July 2025](https://www.phoronix.com/news/Perl-5.42-Released).
[Perl 7 was announced and then shelved](https://www.perl.com/article/announcing-perl-7/)
precisely to avoid breaking scripts that rely on older defaults; feature‑bundle removal,
scheduled for 5.42, was **indefinitely postponed** after discussion. Perl breaks
compatibility less often than Go does.

**WASM — 1, and it is fatal.** Both directions are dead ends.
*Embedding:* the [Perl Wasm project](https://perlwasm.github.io/) states that as of
**August 2025, work on `Wasm` and `Wasm::Wasmtime` has stalled.**
*Compiled to:* WebPerl is an Emscripten build from 2019 and is not a live target.
This is the only 1 in batch 2 where *neither* half of the criterion exists, and against a
weight of 4 it costs 16 of the 20 available points.

**Closed IR types — 1.** Nothing. No static types, no checker comparable to Sorbet, no
exhaustiveness anywhere. The `class` feature added in 5.38 is objects, not sums.

**Ecosystem risk — 4.** The compat record genuinely earns Rust's number:
[perlpolicy](https://perldoc.perl.org/perlpolicy) commits to it, `use v5.xx` bundles gate
new behaviour, and 5.42 even *rolled back* a 5.40 behaviour change that caused leaks.
Held off 5 for trajectory: a shrinking contributor base, CPAN abandonment, and a Perl 7
question that has been reopened and closed twice.

**Deterministic performance — 1.** No JIT. Same band as CPython.
**Memory safety — 4.** Refcounted and memory‑safe in the C sense.
**CBOR — 3.** `pack`/`unpack` is Perl's home ground, but the SV numeric model (IV/NV/UV,
bignums only via `Math::BigInt`) and the **UTF‑8 flag on scalars** are a real hazard for
byte‑exact output — a string that is byte‑identical can serialise differently depending on
an invisible flag, which is exactly the defect class canonical CBOR exists to prevent.
**FFI — 2.** [FFI::Platypus](https://metacpan.org/pod/FFI::Platypus) is better engineered
than `ctypes` but has the identical failure mode: struct layouts are declared by hand
against a header nobody checks. XS gives real header access at the cost of writing C, as
everywhere.
**Deployment — 2.** Interpreter plus CPAN; system perl is ubiquitous, `PAR::Packer` exists.
**Implementation cost — 4.** Near‑mechanical from Python, one below Ruby because sigils and
reference syntax make a deeply nested IR noisier to transcribe.
**SMT — 5.**

**Verdict:** 62 against Python's 71. Porting the validator to Perl would make the project
measurably worse on its own stated criteria — it trades Python's mature WASM‑adjacent
tooling and CBOR clarity for a marginally better compatibility guarantee. It is recorded
in full rather than dismissed, because a candidate scoring *below the incumbent* is a
useful calibration that the matrix is not simply rewarding novelty.

---

## R4′ — The matrix

Scores 0–5 per criterion; weighted total out of 130. **Rust and Python columns are batch 1's,
unchanged**, and are present so the two batches read as one table.

| Criterion | W | Rust | Haskell | SML | Clojure | Ruby | Perl | Python (status quo) |
|---|---|---|---|---|---|---|---|---|
| Deterministic performance | 2 | 5 | 3 | 3 | 2 | 2 | 1 | 1 |
| Memory safety | 3 | 5 | 4 | 4 | 4 | 4 | 4 | 4 |
| Closed IR types | 5 | 5 | 5 | 5 | 1 | 2 | 1 | 1 |
| CBOR byte‑exactness | 1 | 4 | 4 | 4 | 3 | 4 | 3 | 5 |
| WASM (embed + browser) | 4 | 5 | 3 | 1 | 2 | 2 | 1 | 1 |
| FFI (llama.cpp) | 2 | 4 | 4 | 2 | 3 | 2 | 2 | 2 |
| SMT integration | 0 | 5 | 5 | 5 | 5 | 5 | 5 | 5 |
| Deployment | 2 | 5 | 3 | 4 | 3 | 2 | 2 | 2 |
| Ecosystem risk | 4 | 4 | 3 | 4 | 5 | 3 | 4 | 5 |
| Implementation cost | 3 | 2 | 3 | 3 | 4 | 5 | 4 | 5 |
| **Weighted total / 130** | | **114** | **94** | **88** | **76** | **73** | **62** | **71** |

### Sensitivity — the same three adversarial re‑weightings batch 1 used

Identical attacks, so the columns are comparable across batches. Rust's and Python's rows
reproduce batch 1's published numbers exactly, which is the arithmetic check that the
weights really are unchanged.

| Re‑weighting | Rust | Haskell | SML | Clojure | Ruby | Perl | Python |
|---|---|---|---|---|---|---|---|
| Baseline | **114** | 94 | 88 | 76 | 73 | 62 | 71 |
| WASM demoted 4 → 1 (no browser target, no extern execution) | **99** | 85 | 85 | 70 | 67 | 59 | 68 |
| Closed IR types demoted 5 → 2 (the type argument is overrated) | **99** | 79 | 73 | 73 | 67 | 59 | 68 |
| Implementation cost promoted 3 → 5 (schedule pressure dominates) | **118** | 100 | 94 | 84 | 83 | 70 | 81 |

Three readings the table earns:

- **Rust wins every re‑weighting in batch 2 as it did in batch 1**, with a baseline margin
  of 20 over Haskell and a worst‑case margin of 14, under the WASM attack — which is the
  attack aimed squarely at Rust's own best criterion.
- **The WASM attack is the one that helps batch 2 most** — it closes Haskell's gap from 20
  to 14 and lifts SML level with Haskell. That is the honest statement of where the
  ML‑family candidates lose: not on types, on WASM.
- **The closed‑IR attack collapses batch 2's dynamic candidates into the status quo.**
  Clojure ties SML at 73; Ruby (67) and Perl (59) fall *below* Python's 68. Strip out the
  type argument and there is no case for any dynamic port at all — which is a
  self‑consistency check on batch 1's Go finding rather than a new result.

### The calibration reading — what does each candidate buy over Python's 71?

Batch 1's most useful sentence was *"rewriting 3,363 lines in Go buys 12 points; Rust buys 43."*
The same arithmetic, extended:

| Candidate | Total | Buys over Python | Reading |
|---|---|---|---|
| Rust | 114 | **+43** | The batch‑1 decision |
| Haskell | 94 | **+23** | Real, and more than half of Rust's gain — but the residual 20 is concentrated in WASM and deployment, which is where the whole migration's stated purpose (§11 externs, browser validation) lives |
| SML | 88 | **+17** | Buys the best core‑language fit in either batch and nothing else |
| Zig *(batch 1)* | 86 | +15 | |
| Go *(batch 1)* | 83 | +12 | |
| OCaml *(batch 1)* | 79 | +8 | |
| Clojure | 76 | **+5** | 3,363 lines rewritten for 5 points, none of them on criterion 3 |
| Ruby | 73 | **+2** | The cheapest port available buys the least. This is the pair that makes the point |
| Perl | 62 | **−9** | Actively worse than staying |

**The batch‑2 finding, stated once:** a port is worth its cost only if it moves criterion 3
*and* criterion 5 together. Haskell and SML move criterion 3 all the way to Rust's level
and are still 20–26 points behind, because they don't move criterion 5. Clojure, Ruby and
Perl move neither, and their totals cluster within ±5 of the status quo — which is the
matrix saying, correctly, *don't bother.*

---

## Combined leaderboard, both batches

| Rank | Language | Batch | Total / 130 | Loses on |
|---|---|---|---|---|
| 1 | **Rust** | 1 | **114** | — (no criterion in the bottom half) |
| 2 | Haskell | 2 | 94 | WASM maturity (3), deployment (3), ecosystem cadence (3) |
| 3 | Standard ML | 2 | 88 | WASM (1), FFI structs (2) |
| 4 | Zig | 1 | 86 | Ecosystem risk (1), memory safety (2) |
| 5 | Go | 1 | 83 | Closed IR types (1), browser WASM |
| 6 | OCaml | 1 | 79 | FFI (1), WASM (1), deployment |
| 7 | Clojure | 2 | 76 | Closed IR types (1) — Go's disqualifier, in a dynamic language |
| 8 | Ruby | 2 | 73 | Closed IR types (2), browser artefact size, deployment |
| 9 | *Python (status quo)* | 1 | *71* | *Closed IR types (1), WASM (1)* |
| 10 | Perl | 2 | 62 | WASM (1) — both directions — and closed IR types (1) |

**Nothing beats or approaches 114.** The nearest batch‑2 candidate is 20 points back, and
its two most plausible favourable revisions together close only 12 of those. Rust's margin
over the whole field, both batches, is unchanged in character: it remains **the only
candidate with no criterion in the bottom half**, and batch 2 adds nine more rows without
producing a second one.

Two structural observations the combined table makes visible that neither batch made alone:

1. **The typed‑functional family now occupies ranks 2 and 3**, above Zig and Go. Batch 1's
   OCaml screen concluded *"criterion 3's win condition is exhaustive sum types, and Rust is
   the candidate that has them and clears the other seven"* — batch 2 confirms the first
   half harder (three languages now tie Rust at 5 on criterion 3) and the second half
   exactly (none of them clears the other seven).
2. **Dynamic languages cluster at 62–76, a 14‑point band straddling the status quo.** Five
   dynamic candidates across both batches, and the spread between the best and the incumbent
   is 5 points. The rubric is not distinguishing meaningfully among them, because
   criterion 3 floors them all — which is the intended behaviour of a weight of 5.

---

## Remarks on the rubric — not applied to the matrix

Recorded because the contract asks for disagreements to be visible rather than smuggled
into scores. **None of the following is applied above.**

1. **Criterion 2 (memory safety, weight 3) is fully non‑discriminating in batch 2.** All
   five candidates score 4 — GC'd, memory‑safe, no compile‑time temporal guarantee. It
   contributes a constant 12 to every batch‑2 row and separates nobody. Across both
   batches it separates exactly two candidates (Rust's 5, Zig's 2) out of nine. R2 flagged
   criteria 4 and 7 as near‑inert and priced them at 1 and 0; on batch‑2 evidence,
   criterion 2 belongs closer to that group than to weight 3. Applying it (say 3 → 2)
   would subtract 4 from every batch‑2 candidate and 5 from Rust, changing no ordering.
2. **Criterion 10 (implementation cost) looks a point low for the functional candidates.**
   Go's 5 is *"fastest to write, boring in the way infrastructure should be"*. For 3,363
   lines of pure tree‑walking validation with zero dependencies, Haskell and OCaml are not
   two points harder than Go; they are arguably easier, since the program is
   pattern‑matching over a closed union and nothing else. I held Haskell at OCaml's 3
   rather than assert Haskell is easier than OCaml, which I do not believe. Lifting both
   to 4 gives Haskell 97 and OCaml 82 — ordering unchanged, gap to Rust still 17.
3. **Criterion 6 (FFI) conflates two different questions** — *is the binding derived from
   the real header?* and *what does the runtime do to a foreign pointer?* Batch 1's own
   scores show the strain: Zig's 5 and OCaml's 1 answer the first and second question
   respectively. Splitting it would move Haskell (strong on the first, mixed on the
   second) and SML (weak on the first, strong on the second) in opposite directions. At
   weight 2 it is not worth re‑opening the contract for.
4. **No weight change I can construct produces a batch‑2 winner.** Haskell needs +20. The
   only single‑criterion lever big enough is criterion 5, and moving it *helps* Rust,
   which scores 5 there. That is the strongest statement available that this result is not
   an artefact of the weights.

---

## Scores I would defend least

Stated explicitly, ranked by how much of the result rests on them.

1. **Haskell WASM = 3** (weight 4, so ±1 is ±4 points). The GHC backend has carried the
   phrase *"still a tech preview and not included in the official bindists yet"* through
   at least the 9.8, 9.10, 9.12, 9.14 and 9.15 user's guides — 2023 to 2026 — and the
   host‑embedding half is C‑API bindings, which batch 1 penalised Zig for. A 2 is
   defensible and would put Haskell at 90, narrowing its lead over SML from 6 points to 2
   and making the batch‑2 ranking a coin‑toss rather than a result. **What would
   confirm it:** whether the backend ships in an official bindist in the 9.16 cycle, and
   whether anyone has run a non‑trivial Haskell program in a browser at a tolerable
   artefact size. I did not find a credible published binary‑size figure for a real GHC
   wasm program, and that gap is the specific weakness in this score.
2. **SML ecosystem risk = 4.** A 29‑year‑frozen standard argues for 5; a four‑year gap
   between MLton releases, a maintainer pool of a handful, and no patchable TLS stack
   argue for 3. I split it. The criterion's own wording favours 5; the §5 store's
   network‑facing reality favours 3. **What would confirm it:** MLton's release cadence
   over the next 18 months, and whether any maintained SML TLS binding exists (I did not
   find one).
3. **Ruby closed IR types = 2.** Everything rests on Sorbet's `sealed!` + `T.absurd` being
   a real static exhaustiveness check rather than a runtime one. It is — but it is opt‑in,
   sigil‑scoped, and has open exhaustiveness bugs. A 1 (matching Go and Python) is
   defensible and costs 5 points; it would not change Ruby's position relative to anything.
4. **SML deployment = 4** against OCaml's 3. The whole‑program/no‑runtime argument is real
   but the gap to OCaml's native binaries is narrow. Worth 2 points.

---

## Deliberate boundary

- **No decision.** The batch‑1 record stands. This document names no winner and starts no
  migration.
- **No re‑weighting**, and no edit to any batch‑1 score, including the two I think are
  wrong.
- **`SPEC.md`, `prototype/` and `TODO.md` are untouched.** The only edit outside this file
  is a one‑line Batch 2 pointer beside batch 1's matrix.
- **Scored on published evidence, not on hands‑on trial.** No candidate was prototyped
  against the corpus. Every score is a reading of documentation, release notes and
  maintainer statements as of 2026‑08‑14, cited inline. A 3,363‑line spike in Haskell would
  be better evidence than this document is, and would cost more than the decision is worth
  while all four deferral triggers remain unfired.
- **The deferral triggers M1–M4 are unaffected.** Nothing in batch 2 bears on *when*
  migration starts; batch 2 is entirely about *which language*, and it does not change the
  answer.

## Verification

1. `task todo:lint`
2. `git diff --check`

### Recorded verification

#### 1. `task todo:lint`

```
TODO.md: clean
```

PASS — `TODO.md` is untouched by this investigation and remains conformant.

#### 2. `git diff --check`

```
(no output; exit 0)
```

PASS — no whitespace errors in the staged change.
