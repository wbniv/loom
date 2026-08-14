# Investigation — Production language, batch 2: Standard ML, Haskell, Clojure, Perl, Ruby

**Date:** 2026‑08‑14
**Type:** Investigation. Scores five further candidates against the fixed rubric of the
batch‑1 decision record. **It decides nothing.**
**Contract:** [The production implementation language](../plans/2026-08-14-production-language-decision.md)
— its R2 criteria and weights, its R3 evidence bar, and its R4 calibration column are
taken as given and are not re‑derived here.
**Verdict in one line:** nothing in batch 2 beats Rust's **114**. The best batch‑2 score is
**90, a tie between Haskell and Standard ML**, and the batch‑1 DECISION stands unchanged.

**Two amendments, same day.** Both were challenges to scores this document flagged as weak,
and both are folded in below.

- **A1 — Haskell WASM, 3 → 2** (Haskell 94 → **90**). Flagged on first pass as the
  least‑certain call and re‑researched against five specific questions. The evidence moved
  it **down**, on two findings the first pass missed: the live pandoc‑wasm playground serves
  a **50.4 MiB** module, and **Hackage has no Wasmtime binding at all**. Two claims in the
  original write‑up were also *wrong in Haskell's favour* and are corrected.
- **A2 — SML FFI, 2 → 3** (SML 88 → **90**), after the whole FFI row was re‑audited under a
  lens the first pass missed: **struct layouts can be generated from the pinned header at
  build time in any language with a build step**. See
  [The layout‑generation lens](#the-layout-generation-lens).

Net effect: **Haskell and SML are now tied at 90**, and SML is never behind Haskell under
any of the four weightings. Rust's 114 is untouched by both amendments, and no batch‑1
number changed.

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

### Haskell — joint best in batch 2, and the one whose score moved most

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

**WASM — 2 (revised from 3).** This was the least‑certain call on first pass and was
re‑researched against five specific questions. The evidence moved it **down**, and it moved
on the *embedding* half — the half I under‑researched initially. Findings, in order:

**(1) Bindist trajectory: static, but not stalled — the backend is actively developed and
has no promotion roadmap.** The phrase *"still a tech preview and not included in the
official bindists yet"* appears unchanged in the 9.6 (2023‑03), 9.8, 9.10, 9.12, 9.14 and
[9.15 (2026‑03)](https://ghc.gitlab.haskell.org/ghc/doc/users_guide/wasm.html) user's
guides — **three and a half years of an identical sentence.** Searching GHC's issue tracker
for a promotion/bindist milestone turns up nothing open: the one directly on point,
[#22628 "Build fully_static linux bindists for the wasm backend"](https://gitlab.haskell.org/ghc/ghc/-/issues/22628),
was **closed in January 2023**. Meanwhile the backend is emphatically *alive* — 25+ open
`wasm` issues, several updated within days of writing, and
[ghc‑wasm‑meta](https://github.com/haskell-wasm/ghc-wasm-meta) pushed the same day. The
honest characterisation is neither "abandoned" nor "arriving": **permanently in preview,
actively worked, with nobody committing to a stabilisation date.** For a criterion about
depending on something for years, that is worse than either extreme would be.

**(2) Real artefacts compiled to WASM — they exist, and now there is a number.**
[haskell‑wasm/pandoc‑wasm](https://github.com/haskell-wasm/pandoc-wasm) (168 stars, last
pushed 2025‑10‑11) compiles **pandoc** — a genuinely large real Haskell program, not a demo
— to a standalone `wasm32-wasi` module that runs in browsers and under `wasmtime`.
[Miso](https://github.com/dmjio/miso) (2,400+ stars, pushed today) now recommends the wasm
backend as its *default*. So the compile‑to direction is real for non‑trivial programs, and
that is genuinely more than OCaml or SML can show.
**The size figure I could not find on first pass, measured directly:** the live
[pandoc‑wasm playground](https://haskell-wasm.github.io/pandoc-wasm/) serves
`pandoc.wasm` as `content-type: application/wasm` with `content-length: 52892061` —
**50.4 MiB**, uncompressed. Batch 1 scored Go's browser target 2 for *"multi‑megabyte
binaries"*; Ruby's ~10–20 MB CRuby module also scored 2. GHC's is an order of magnitude past
Go's. That size is a known, unsolved, actively‑tracked problem —
[#27338 "Make wasm modules smaller"](https://gitlab.haskell.org/ghc/ghc/-/issues/27338)
(opened 2026‑06‑06) is an open **meta‑issue** for exactly this. *Caveat stated honestly:*
pandoc pulls in a large dependency tree, so 50.4 MiB is not pure GHC overhead — but Go's and
Ruby's figures were measured on comparably real programs, so the comparison is fair, and it
is the only measured datum available.

**(3) The embedding half is weaker than I credited, and it decides the score.**
Criterion 5's *first* requirement is embedding a runtime to execute hash‑pinned externs.
Hard facts: **a Hackage search for `wasmtime` returns an empty list — zero packages.** There
is no wasmtime‑hs and no successor. The two real options are the
[Extism Haskell host SDK](https://github.com/extism/haskell-sdk) — **last commit
2024‑12‑03**, i.e. ~20 months stale, 11 stars, `extism` 1.3.0.0 on Hackage — and
[byteally/wasmedge](https://github.com/byteally/wasmedge), which *is* actively maintained
(last commit 2026‑03‑27) but is an 11‑star binding to a *different* engine, over its C API.
**Against batch 1's bar this is decisive:** Zig scored WASM 3 with a host story batch 1
explicitly penalised as a "hand‑managed C boundary" — and Zig at least consumed **wasmtime's
own C API**. Haskell has no binding to the reference engine at all. Haskell's embedding half
is therefore *below* the one that earned Zig a 3, while its browser half is *also* below
Zig's ("small binaries, no `wasm-bindgen` ceremony" versus 50.4 MiB and a preview label).
Below Zig on both halves cannot be scored at Zig's 3.

**(4) Single‑threaded RTS and Template Haskell — I was wrong, and this favours Haskell.**
Both restrictions I cited are weaker than I stated. Template Haskell **and GHCi** have been
supported since 9.10/9.12 per
[Tweag's write‑up](https://www.tweag.io/blog/2024-11-21-ghc-wasm-th-ghci/) (Nov 2024); what
remains is that TH splices cannot spawn subprocesses and the ghci debugger doesn't work.
And the single‑threaded RTS still supports `forkIO`, `MVar` and `threadDelay` — *concurrency
works; only parallelism is absent.* **For Loom's actual use case this does not bite at all:**
criterion 5's second half is a browser validator, which is CPU‑bound, single‑shot, and
single‑threaded by nature. Neither restriction costs Loom anything, and the original
write‑up should not have counted them. Similarly, pandoc‑wasm's three stated limitations —
no sockets, no Lua, and a custom fork patching dependencies — **all miss Loom**, whose core
is 3,363 lines with *zero third‑party dependencies* (R3) and which needs no network in the
browser. Had the score turned on these, it would have gone up.

**(5) JSFFI is still churning, and one bug lands on criterion 2.** Open, all within ~10
weeks of writing:
[#27334](https://gitlab.haskell.org/ghc/ghc/-/issues/27334) (async JSFFI uncaught promise
rejection when a thunk is forced too late),
[#27546](https://gitlab.haskell.org/ghc/ghc/-/issues/27546) (LLVM and wasm backends segfault
at `-O2`), [#25935](https://gitlab.haskell.org/ghc/ghc/-/issues/25935) (compiler plugins
unsupported), and — the one that matters most here —
[#27659](https://gitlab.haskell.org/ghc/ghc/-/issues/27659), *"wasm: unsupported
`ByteArray#` JSFFI imports compile **silently** to memory‑unsafe code"*, opened 2026‑08‑09
and labelled `wasm`/`FFI`/`T::bug`. A silently‑memory‑unsafe compilation path is precisely
the defect class this whole migration exists to eliminate, in the exact subsystem a browser
validator would use to hand bytes across the boundary. *Cited with its caveat:* the issue
carries an `llm-derived::reproducer` label and `P::low`, so it is a real filed bug of
modest priority, not a five‑alarm fire. It is evidence of an interface still settling, which
is what question 5 asked.

**Settled at 2.** Not from discomfort — from the embedding half being materially worse than
Zig's 3 and there being no binding to the reference engine, compounded by a 50.4 MiB
measured artefact. It stays **above OCaml's and SML's 1**, because pandoc‑wasm is a working
large program and weak bindings still beat no bindings.

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

**What would change this (updated, and now with the thresholds named):**

- **WASM 2 → 4** needs *both* halves fixed: a maintained binding to a reference engine on
  Hackage (any Wasmtime binding at all would do — there are currently zero), **and** either
  bindist promotion or an order‑of‑magnitude size reduction under #27338. That is +8 →
  **98**.
- **WASM 2 → 5** (Rust parity) additionally needs the tech‑preview label to actually come
  off: +12 → **102**.
- **Ecosystem risk 3 → 4** if the LTS cadence holds for two cycles: +4. Combined with the
  above, **106**.

Even the generous ceiling leaves Haskell **8 points short of Rust**, and the realistic
revision leaves it 16 short. Stated plainly: Haskell's gap to Rust is not one contingent
fact away from closing, and this round of research widened it rather than narrowing it.

**What remains genuinely unresolved:** (i) whether 50.4 MiB is representative of a
*dependency‑free* 3,363‑line validator — pandoc is the only measured Haskell wasm artefact
I could find, and Loom's core would be far smaller, but nobody has published a
minimal‑program baseline, so the gap between "pandoc is 50 MiB" and "Loom would be N MiB"
is unmeasured; (ii) whether anyone intends to write a Wasmtime binding — the absence is a
fact, the intent is unknowable from outside; (iii) whether the tech‑preview label reflects
a real stabilisation blocker or merely nobody having filed the paperwork. A one‑day spike
compiling a 200‑line Haskell CBOR round‑tripper to wasm and measuring the module would
settle (i) outright, and is the cheapest evidence available against this score.

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
ML‑family score or an OCaml score. It was mostly an OCaml score: SML lands at **90**, eleven
points higher, on three +1s and one +2 — and, importantly, on **none** of the three criteria
that actually exited OCaml. (The +2 is FFI, revised upward by amendment A2; the first pass
had it at +1 and SML at 88.)

| Criterion | OCaml | SML | Why it changed, or didn't |
|---|---|---|---|
| Closed IR types | 5 | **5** | *Unchanged — but for a different reason.* OCaml's 5 was argued on variants + exhaustive matching + GADTs. SML has no GADTs. It compensates with something batch 1 did not have available to score: **MLton's `nonexhaustiveMatch {warn\|error\|ignore}` ML Basis annotation** ([MLBasisAnnotations](https://github.com/MLton/mlton/blob/master/doc/guide/src/MLBasisAnnotations.adoc)) turns a non‑exhaustive `case`/`fn`/`fun` into a **hard compile error**, giving SML *Rust's* property rather than the ML tradition's warning. Since the IR is a first‑order closed union with no type‑indexing requirement, the GADT loss does not bite. Net: still 5 |
| Deterministic performance | 3 | **3** | *Unchanged, and the reasoning matters.* MLton's whole‑program monomorphisation and strict evaluation generate genuinely C‑class code — better than OCaml's on this workload. But **MLton has no parallelism**: the one live scenario for criterion 1 is batch serving, where the mechanism batch 1 identified is *GIL‑style serialisation of 32 × 0.19 ms onto one core*, and a single‑threaded MLton runtime reproduces that shape exactly. The ~30× constant factor rescues the arithmetic; the structure is unchanged. MPL fixes it and is a research fork. The two cancel at 3 |
| Memory safety | 4 | **4** | Unchanged. GC'd, no unsafe by default |
| CBOR byte‑exactness | 3 | **4** | **+1.** The SML Basis Library standardises `Word8Vector`, the `PackWord*`/`PackReal*` byte‑packing structures, **and `IntInf` arbitrary‑precision integers**. OCaml needs Zarith — an external C library — for CBOR bignums. For a criterion about byte exactness, having the whole toolkit inside the frozen standard is worth the point |
| WASM | 1 | **1** | **Unchanged, and it is the disqualifier.** MLton 20241230 adds *"preliminary support for `wasm32-wasi`"* ([releases](https://github.com/MLton/mlton/releases)) — real, and directly host‑runtime consumable, which `wasm_of_ocaml`'s WasmGC output is not. But criterion 5's *first* requirement is embedding a runtime to execute hash‑pinned extern components, and SML has **no host‑embedding story whatsoever**. That is the same 1 OCaml took, for the same reason |
| FFI | 1 | **3** | **+2 — revised from +1 by amendment A2.** MLton's `_import`/`_export` compiles to a direct call with **no runtime lock** (there is no runtime to lock) and no wrapper overhead — the per‑token `libllama` path is not SML's worst case the way it is OCaml's, and that half of OCaml's 1 does not transfer. The original write‑up then deducted for MLton having "no struct‑layout facility at all", posing a false choice between hand‑computed offsets and a hand‑written C shim. **There is a third route** — generate the layout from the pinned header at build time — which makes drift a build failure and is available to any language with a build step; see [The layout‑generation lens](#the-layout-generation-lens). With the drift class eliminated, SML's remaining deductions against Rust's 4 are that cheap generator output is untyped `MLton.Pointer` peek/poke at the use site, and that the project owns the generator. Net 3 |
| Deployment | 3 | **4** | **+1.** Whole‑program compilation yields one statically linkable native executable with no separate runtime and no dynamic loader, and community musl builds exist. Cross‑compilation is poor. This is the SML score I would defend second‑least |
| Ecosystem risk | 3 | **4** | **+1, and it is the interesting one.** The **language standard has not changed in 29 years**. Measured on the criterion as R2 actually writes it — *"a substrate with its own breaking‑change cadence is a structural mismatch"* — SML has no cadence to mismatch, and R3's *"there is no library leverage to lose"* removes the usual objection. Against a 5: the four‑year release gap, a maintainer pool countable on one hand, and — the concrete one — **no maintained TLS/networking stack that could receive a CVE patch**, which is a live concern for a network‑facing §5 store. Net 4. **This is my single most‑torn call in the document** |
| Implementation cost | 3 | **3** | Unchanged, from two effects that cancel: the *core* is cheaper than anywhere else in either batch (SML is a smaller, stricter language than Haskell and the validator is textbook SML), while the *scaffolding* is dearer than anywhere else — you write SHA‑256 for the identity hashes yourself, and the editor/formatter/package tooling barely exists |
| SMT | 5 | **5** | Unchanged and weightless |

**Verdict:** SML is the best pure *language* fit for the validator core in either batch and
it still loses by 24 points, because criterion 5 is weighted 4 and SML scores 1 on it, and
because the store's non‑core needs (networking, TLS) fall outside what a frozen 1997
standard and a two‑release‑per‑decade compiler supply. Note that after amendment A2 the
list of things falling outside **no longer includes FFI struct layouts** — that was a
tooling gap I mis‑scored as a language property.

**What would change this:** if MLton's `wasm32-wasi` support matured out of "preliminary"
*and* someone wrote a Wasmtime C‑API binding, WASM 1 → 3 (+8 → **98**). Still 16 short.
Note the Wasmtime C‑API binding is itself cheaper than it looks under amendment A2's lens —
the same generator that derives `llama.h` layouts derives `wasm.h`'s — so the *reason* SML
scores 1 on criterion 5 is the absence of anyone having done it, not a language barrier.

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

## The layout‑generation lens

**Amendment A2.** The first pass scored criterion 6 partly on whether a language *ships* a
struct‑layout facility, and posed SML's options as a dichotomy: hand‑computed offset
arithmetic, or a hand‑written C shim. **That dichotomy was false, and the error generalises
across the whole row.**

**The third route: generate the layout from one machine‑readable source.** A build‑time C
program `#include`s the *pinned* `llama.h`, prints `offsetof`/`sizeof`/type per field, and
emits (a) constants or accessors in the target language and (b) C‑side `static_assert`s. Any
field added or reordered upstream then fails the **build**, loudly, instead of silently
corrupting a struct — which is exactly the `_check_abi` defect class the migration exists to
eliminate. This is precisely the technique I credited `hsc2hs` for when scoring Haskell 4,
**and nothing about it is Haskell‑specific.** It needs only a build step, which every
candidate in either batch has. Crediting it to one language and penalising others for
lacking the tool — rather than for the cost of writing ~200–400 lines of it — was the
mistake.

**Prior art, and it is not novel.** The operator's own
`~/WorldFoundry-wbniv` is a decades‑old shipped‑game‑engine instance of the same pattern:
`wfsource/source/oas/*.oas` text layout descriptions sharing `.inc` fragments, compiled by
`oas2oad-rs` into binary `.oad` files, with `oaddump` as the inspector. One description, every
consumer generated from it, so the sides *cannot* drift. The generalisation is that
byte‑layout agreement between two languages is a **code‑generation problem with a settled
solution**, not a language capability to be scored.

**What dissolves.** "No struct‑layout facility" as a hard penalty — for every candidate.
SML, Ruby, Perl, Clojure and Python can all derive layouts from the real header at build
time. The layout‑drift defect class is available to be eliminated everywhere.

**What survives as genuinely language‑differentiating**, and is what the row now scores:

| Residual discriminator | Why generation can't fix it |
|---|---|
| **Runtime‑lock and callback semantics** | A GIL/GVL, OCaml's runtime lock, a moving GC around foreign pointers, or JVM safepoints are properties of the runtime on the per‑token path. No generator touches them. This is why **OCaml's batch‑1 score of 1 survives the lens intact** — batch 1 argued it on exactly this, not on layouts |
| **End‑to‑end typedness of the result** | A real spectrum, not a binary: `bindgen`/`@cImport` yield *typed structs in the language*; a generator can yield *typed accessors* if you write more generator; the cheap version yields *untyped `peek`/`poke` at machine‑derived offsets* — drift‑safe but not type‑safe at the use site |
| **Call overhead** | Compiled direct call (SML `_import`, Haskell `unsafe ccall`) vs FFM downcall across a JVM boundary vs interpreted marshalling through `Fiddle`/`ctypes`. Unchanged by generation |
| **Who owns the generator** | Off‑the‑shelf and maintained by someone else (`bindgen`, `@cImport`, `hsc2hs`, `jextract`) vs a bespoke build tool this project owns forever. That is a real **criterion‑10** cost, and a second piece of bespoke infrastructure after L0 |

**Re‑audit of the batch‑2 FFI row under the lens:**

| | Was | Now | Reasoning |
|---|---|---|---|
| **SML** | 2 | **3** | The one score the lens moves. `_import` is a compiled direct call with **no runtime lock** (there is no runtime to lock) and no wrapper overhead — the best call semantics in batch 2. With generated layouts the drift class is gone. Held below Rust's 4 because the cheap generator output is untyped `MLton.Pointer` peek/poke at the use site, and because the project owns the generator rather than using `bindgen` |
| **Haskell** | 4 | 4 | Unchanged, and now better justified: `hsc2hs` ships *with GHC*, so Haskell gets the technique off‑the‑shelf and pays no generator‑ownership cost, and `#peek`/`#poke` are typed through `Storable` |
| **Clojure** | 3 | 3 | Unchanged. `jextract` was already the off‑the‑shelf header‑derived generator and its output is typed. Held at 3 by the JVM boundary, boxing, and `--enable-native-access` friction, none of which the lens touches |
| **Ruby** | 2 | 2 | Unchanged. The layout half improves, but criterion 6 is about the *per‑token path*, and Ruby's remains a GVL plus interpreted `Fiddle` marshalling — the worst call semantics in batch 2 alongside Perl. The lens raises the floor it was never scored on |
| **Perl** | 2 | 2 | Unchanged, same reasoning; `FFI::Platypus` call overhead is the binding constraint, not layout declaration |

**Only one score moves**, and saying so plainly is the point — a lens that moved everything
would be re‑weighting by stealth rather than correcting an error.

**Batch‑1 under the same lens — recorded, not applied.** Batch 1's numbers are published and
frozen, but the lens would have touched two of them:

- **Python 2 → 3** (total 71 → 73). This is the uncomfortable one, and it deserves to be
  stated rather than buried: batch 1's *strongest non‑performance argument against Python*
  was the `ctypes` shim as an *"unchecked raw‑pointer surface with no compile‑time
  verification"* that had already shipped the `_check_abi` defect. **A generated‑offsets
  `ctypes` shim supplies that verification without leaving Python.** The lens therefore
  weakens one plank of the migration case. It does not move the decision — criteria 3 and 5,
  which carry 9 of the 26 weight and are where Rust's 43‑point margin actually comes from,
  are untouched — but "the ABI surface is unverifiable in Python" should be retired as an
  argument, because it is a tooling gap, not a language property.
- **OCaml 1 → 2** (total 79 → 81). Layout was a minor part of OCaml's 1; the moving GC and
  runtime lock were the argument, and those survive.
- **Zig's 5 and Rust's 4 are unchallenged.** `@cImport` is native header import at compile
  time with no generator to own and full typing; `bindgen` is the off‑the‑shelf version of
  the same. Both remain ahead of anything the generator route reaches.

Neither remark changes any ordering in either batch.

## R4′ — The matrix

Scores 0–5 per criterion; weighted total out of 130. **Rust and Python columns are batch 1's,
unchanged**, and are present so the two batches read as one table.

| Criterion | W | Rust | Haskell | SML | Clojure | Ruby | Perl | Python (status quo) |
|---|---|---|---|---|---|---|---|---|
| Deterministic performance | 2 | 5 | 3 | 3 | 2 | 2 | 1 | 1 |
| Memory safety | 3 | 5 | 4 | 4 | 4 | 4 | 4 | 4 |
| Closed IR types | 5 | 5 | 5 | 5 | 1 | 2 | 1 | 1 |
| CBOR byte‑exactness | 1 | 4 | 4 | 4 | 3 | 4 | 3 | 5 |
| WASM (embed + browser) | 4 | 5 | **2** | 1 | 2 | 2 | 1 | 1 |
| FFI (llama.cpp) | 2 | 4 | 4 | **3** | 3 | 2 | 2 | 2 |
| SMT integration | 0 | 5 | 5 | 5 | 5 | 5 | 5 | 5 |
| Deployment | 2 | 5 | 3 | 4 | 3 | 2 | 2 | 2 |
| Ecosystem risk | 4 | 4 | 3 | 4 | 5 | 3 | 4 | 5 |
| Implementation cost | 3 | 2 | 3 | 3 | 4 | 5 | 4 | 5 |
| **Weighted total / 130** | | **114** | **90** | **90** | **76** | **73** | **62** | **71** |

Two cells were revised after publication and are bolded: **Haskell WASM 3 → 2** (amendment
A1, total 94 → 90) and **SML FFI 2 → 3** (amendment A2, total 88 → 90). Every other cell is
as first scored, and no batch‑1 cell moved.

### Sensitivity — the same three adversarial re‑weightings batch 1 used

Identical attacks, so the columns are comparable across batches. Rust's and Python's rows
reproduce batch 1's published numbers exactly, which is the arithmetic check that the
weights really are unchanged.

| Re‑weighting | Rust | Haskell | SML | Clojure | Ruby | Perl | Python |
|---|---|---|---|---|---|---|---|
| Baseline | **114** | 90 | 90 | 76 | 73 | 62 | 71 |
| WASM demoted 4 → 1 (no browser target, no extern execution) | **99** | 84 | **87** | 70 | 67 | 59 | 68 |
| Closed IR types demoted 5 → 2 (the type argument is overrated) | **99** | 75 | 75 | 73 | 67 | 59 | 68 |
| Implementation cost promoted 3 → 5 (schedule pressure dominates) | **118** | 96 | 96 | 84 | 83 | 70 | 81 |

Three readings the table earns:

- **Rust wins every re‑weighting in batch 2 as it did in batch 1**, with a baseline margin
  of 24 and a worst‑case margin of 12, under the WASM attack — which is the attack aimed
  squarely at Rust's own best criterion.
- **The WASM attack is the one that helps batch 2 most** — it closes the gap from 24 to 12,
  and it is the only weighting that separates Haskell from SML at all, in **SML's** favour
  (87 vs 84).
- **Haskell and SML tie on three of the four weightings and SML wins the fourth.** SML is
  therefore *weakly dominant* over Haskell across this whole sensitivity analysis: never
  behind, ahead once. See below.
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
| Haskell | 90 | **+19** | Real, but under half of Rust's gain — and the residual 24 is concentrated in WASM and deployment, which is where the whole migration's stated purpose (§11 externs, browser validation) lives |
| SML | 90 | **+19** | Identical to Haskell, by a different route: the best core‑language fit in either batch, with no browser or embedding story at all |
| Zig *(batch 1)* | 86 | +15 | |
| Go *(batch 1)* | 83 | +12 | |
| OCaml *(batch 1)* | 79 | +8 | |
| Clojure | 76 | **+5** | 3,363 lines rewritten for 5 points, none of them on criterion 3 |
| Ruby | 73 | **+2** | The cheapest port available buys the least. This is the pair that makes the point |
| Perl | 62 | **−9** | Actively worse than staying |

**The batch‑2 finding, stated once:** a port is worth its cost only if it moves criterion 3
*and* criterion 5 together. Haskell and SML move criterion 3 all the way to Rust's level
and are still 24 points behind, because they don't move criterion 5. Clojure, Ruby and
Perl move neither, and their totals cluster within ±5 of the status quo — which is the
matrix saying, correctly, *don't bother.*

---

## Combined leaderboard, both batches

| Rank | Language | Batch | Total / 130 | Loses on |
|---|---|---|---|---|
| 1 | **Rust** | 1 | **114** | — (no criterion in the bottom half) |
| 2= | Haskell | 2 | 90 | WASM (2) — 50.4 MiB artefact, no reference‑engine binding; deployment (3); ecosystem cadence (3) |
| 2= | Standard ML | 2 | 90 | WASM (1) — no embedding story at all; performance (3) — no parallelism |
| 4 | Zig | 1 | 86 | Ecosystem risk (1), memory safety (2) |
| 5 | Go | 1 | 83 | Closed IR types (1), browser WASM |
| 6 | OCaml | 1 | 79 | FFI (1), WASM (1), deployment |
| 7 | Clojure | 2 | 76 | Closed IR types (1) — Go's disqualifier, in a dynamic language |
| 8 | Ruby | 2 | 73 | Closed IR types (2), browser artefact size, deployment |
| 9 | *Python (status quo)* | 1 | *71* | *Closed IR types (1), WASM (1)* |
| 10 | Perl | 2 | 62 | WASM (1) — both directions — and closed IR types (1) |

### Second place is a tie, and SML weakly dominates it

Both amendments moved the #2/#3 question, in opposite directions, and they have landed it on
an **exact tie at 90**. That is not a coincidence worth hiding behind a tiebreak — it is the
result:

| Weighting | SML | Haskell | Winner |
|---|---|---|---|
| Baseline | 90 | 90 | tie |
| WASM demoted 4 → 1 | **87** | 84 | **SML** |
| Closed IR types demoted 5 → 2 | 75 | 75 | tie |
| Implementation cost promoted 3 → 5 | 96 | 96 | tie |

**SML is never behind Haskell under any weighting this document applies, and is ahead under
one.** In decision‑analysis terms it weakly dominates. If forced to name a single runner‑up
to Rust, the evidence says **Standard ML**, not Haskell — which reverses the first pass's
ordering, and reverses it for a reason worth stating: the first pass under‑credited SML's
FFI on a false dichotomy (A2) and over‑credited Haskell's WASM on unmeasured optimism (A1).

The tie is also fragile in both directions, which is why neither should be reported as a
finding on its own:

| Change (each a ±1 on a score already flagged as arguable) | SML | vs Haskell 90 |
|---|---|---|
| As scored | 90 | tie |
| SML WASM 1 → 2 (crediting MLton's `wasm32-wasi` as a browser story) | **94** | SML by 4 |
| SML deployment 4 → 3 (equal to OCaml's) | 88 | Haskell by 2 |
| SML ecosystem risk 4 → 3 (equal to OCaml's) | 86 | Haskell by 4 |

**The honest statement is that batch 2 has one clear result — neither candidate is close to
Rust — and a second place that is a tie with a mild lean to SML.** Anyone reading this for
"the best alternative to Rust" should read "Haskell and SML, indistinguishable, both 24
points short". The two lose for opposite reasons, which is the more useful thing to carry
forward: Haskell has a real browser story that weighs 50 MiB and no embedding story; SML has
neither story, but a better‑fitting core, better call semantics, and a frozen substrate.

**Nothing beats or approaches 114.** The nearest batch‑2 candidate is 24 points back, and
its two most plausible favourable revisions together close only 16 of those. Rust's margin
over the whole field, both batches, is unchanged in character: it remains **the only
candidate with no criterion in the bottom half**, and batch 2 adds nine more rows without
producing a second one.

Two structural observations the combined table makes visible that neither batch made alone:

1. **The typed‑functional family now occupies both of the joint‑second slots**, above Zig
   and Go. Batch 1's
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
3. **Criterion 6 (FFI) conflates two different questions**, and amendment A2 sharpened this
   from a suspicion into a demonstrated defect. The questions are *is the binding derived
   from the real header?* and *what does the runtime do on the per‑token path?* Batch 1's
   own scores answer different ones: Zig's 5 is about the first, OCaml's 1 about the second.
   **The first question turns out not to be a language property at all** — it is a build‑step
   property available to every candidate — which is what made me mis‑score SML on first pass.
   Were the criterion split, the header half would collapse to near‑uniform (only the cost of
   owning the generator would separate anyone) and the runtime half would do all the
   discriminating. At weight 2 it is not worth re‑opening the contract, but the
   generation‑is‑universal finding is the durable part and is recorded in
   [The layout‑generation lens](#the-layout-generation-lens).
4. **The lens weakens one plank of batch 1's own case against Python**, as recorded in that
   section: "the ABI surface is unverifiable in Python" is a tooling gap, not a language
   property, and a generated‑offsets `ctypes` shim closes it without leaving Python. Batch 1's
   Python 71 is unchanged here; the argument behind one of its cells should be retired.
5. **No weight change I can construct produces a batch‑2 winner.** Haskell and SML each need
   +24. The only single‑criterion lever big enough is criterion 5, and moving it *helps*
   Rust, which scores 5 there. That is the strongest statement available that this result is
   not an artefact of the weights — and it survived both amendments, which between them moved
   two cells and changed the runner‑up but not the winner.

---

## Scores I would defend least

Stated explicitly, ranked by how much of the result rests on them.

*Haskell WASM has been removed from this list — it was #1 on first pass, was re‑researched
on request, and is now settled at 2 on measured evidence (50.4 MiB artefact; zero Wasmtime
packages on Hackage). The residual uncertainty in it is stated in Haskell's "what would
change this" note instead.* The list below is re‑ordered accordingly, and the top two now
matter more than they did, because they are what decides the #2/#3 ordering.

1. **SML deployment = 4** against OCaml's 3. The whole‑program/no‑runtime/static‑binary
   argument is real but the gap to OCaml's native binaries is narrow, and I could not name
   a discriminator I fully believe. Worth 2 points — and since Haskell and SML are now
   **tied at 90**, this single cell is what would break the tie in Haskell's favour. That is
   more weight than it can bear. **What would confirm it:** building the same trivial
   program under MLton and OCaml and comparing `ldd` output and artefact size.
2. **SML ecosystem risk = 4.** A 29‑year‑frozen standard argues for 5; a four‑year gap
   between MLton releases, a maintainer pool of a handful, and no patchable TLS stack
   argue for 3. I split it. The criterion's own wording favours 5; the §5 store's
   network‑facing reality favours 3. **What would confirm it:** MLton's release cadence
   over the next 18 months, and whether any maintained SML TLS binding exists (I did not
   find one).
3. **SML WASM = 1**, equal to OCaml's. MLton 20241230 does ship preliminary `wasm32-wasi`
   support in the mainline compiler, which is arguably worth a 2 — and a 2 would put SML at
   92, **ahead of Haskell**. I held it at 1 because criterion 5's first‑named requirement,
   embedding a runtime, is entirely absent in SML. Anyone who weights the compile‑to half
   more heavily should reverse ranks 2 and 3.
4. **SML FFI = 3** (amendment A2). The generator route is sound and has decades of prior art,
   but I am scoring a binding **nobody has written** — unlike Haskell's `hsc2hs`, Clojure's
   `jextract` or Rust's `bindgen`, which exist and are maintained by others. Scoring a
   language for what a competent team *could* build is a different standard from scoring it
   for what ships, and I have applied the first here and the second elsewhere. A 2 (as
   originally scored) is still defensible on that inconsistency alone; it would put SML back
   at 88 and restore Haskell to a clear second. **What would confirm it:** writing the
   generator — it is a day's work, and it is the cheapest experiment in this document.
5. **Ruby closed IR types = 2.** Everything rests on Sorbet's `sealed!` + `T.absurd` being
   a real static exhaustiveness check rather than a runtime one. It is — but it is opt‑in,
   sigil‑scoped, and has open exhaustiveness bugs. A 1 (matching Go and Python) is
   defensible and costs 5 points; it would not change Ruby's position relative to anything.

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
