# Loom — Language Specification, v0.1

**Status:** Design fiction made precise. Nothing here is implemented; every
rule is written as if it were normative so that the design can be attacked
concretely. Derived from the six design pressures in
[the design sketch](../docs/investigations/2026-08-12-loom-agent-native-language-sketch.md)
(P1–P6 are referenced throughout).
**Date:** 2026‑08‑12

---

## 1. Model and terminology

- **Store** — the only persistence layer. An append-only, content-addressed
  set of *objects*. There are no files and no builds.
- **Definition** — a typed, closed term. Identified by the hash of its
  canonical encoding (§4). Immutable.
- **Binding** — a mutable name-path ↦ definition-hash mapping, carrying
  evidence (§6). The only mutable thing in the system.
- **Projection** — a rendering of store content for a reader (human or
  model). One-way: no parser for any projection exists (§9).
- **Agent** — a stochastic author. Emits canonical encodings under a
  decoding mask (§8). Never edits text.
- **Oracle** — the deterministic toolchain: typechecker, SMT solver,
  evidence runner. The only source of ground truth in the loop (P5).
- **Principal** — a human or service accountable for a namespace's policy.

Hashes are SHA‑256 in v0.1 (ubiquitous, verifiable anywhere; a faster hash
is a v0.2 question, not a semantic one). A hash is written `#` + first
8 hex chars in projections, full 32 bytes in encodings.

## 2. Core calculus

A pure, total-by-default functional core with algebraic data, algebraic
effects and handlers, refinement types, and capability values. The node set
is deliberately small and closed — the decoding mask (§8) is a table over
these tags, and every tag added is mask complexity paid forever.

### 2.1 Terms

Every term is encoded as a CBOR array `[tag, …fields]`.

| Tag | Node | Shape | Notes |
|---|---|---|---|
| 0 | `var` | `[0, i]` | de Bruijn index — bound names do not exist in canonical form |
| 1 | `ref` | `[1, h]` | reference to a store definition by 32‑byte hash |
| 2 | `lit` | `[2, k, v]` | literal; kinds in §2.2 |
| 3 | `lam` | `[3, T, body]` | fully annotated — canonical form is the *elaborated* term |
| 4 | `app` | `[4, f, a]` | |
| 5 | `let` | `[5, T, bound, body]` | monomorphic let; polymorphic reuse goes through the store |
| 6 | `con` | `[6, d, i, [args]]` | constructor `i` of data type `d` |
| 7 | `match` | `[7, scrut, [arms]]` | arm = `[ctor-index, binder-count, body]`; must be exhaustive |
| 8 | `perform` | `[8, a, i, [args]]` | operation `i` of ability `a` |
| 9 | `handle` | `[9, a, term, [ops], ret]` | handler discharges ability `a` from the row |
| 10 | `fix` | `[10, T, measure, body]` | recursion **only** with a termination measure; see §2.5 |
| 11 | `hole` | `[11, T, [constraints]]` | typed hole; storable only in the draft region (§5.4) |

There is no `anno` node and no syntax for comments: hashing operates on
elaborated terms, and prose lives in metadata (§5.2), never in the term.

### 2.2 Literals and base types

Literal kinds: `0` unit, `1` bool, `2` i64, `3` f64 (8 raw bytes,
IEEE‑754 big-endian byte string — NaNs canonicalized to a single quiet NaN),
`4` text (Unicode NFC), `5` bytes. `unit` has no payload: its node is the
2-element array `[2, 0]` — `v` is omitted, not null-padded — since kind 0 is
the only one with nothing to carry.

### 2.3 Types

| Tag | Node | Shape | Notes |
|---|---|---|---|
| 0 | `base` | `[0, c]` | `c`: 0 Unit, 1 Bool, 2 I64, 3 F64, 4 Text, 5 Bytes |
| 1 | `data` | `[1, h, [T…]]` | applied data type by hash |
| 2 | `fn` | `[2, dom, row, cod]` | effect row on every arrow |
| 3 | `refine` | `[3, T, φ]` | `{x : T \| φ}`; φ is a term of type Bool over the SMT fragment (§3.2) |
| 4 | `cap` | `[4, a]` | capability for ability `a` — a nominal, unforgeable value type |
| 5 | `tyvar` | `[5, i]` | de Bruijn at the type level |
| 6 | `forall` | `[6, T]` | rank‑1 polymorphism only |

An **effect row** is a CBOR array of ability hashes sorted bytewise
(deterministic by construction), optionally ending in a row variable
`[5, i]`. The empty row `[]` means pure.

### 2.4 Abilities and capabilities

Abilities (effect interfaces, in the sense of
[Unison's abilities](https://www.unison-lang.org/docs/fundamentals/abilities/))
are store definitions: an ability declares a list of operation signatures.
Builtin abilities ship as well-known hashes: `clock`, `rand`, `fsRead`,
`fsWrite`, `net`, `spawn`, `div` (§2.5), `ffi` (§11).

A **capability** is a runtime value of type `cap a`, introduced only by the
runtime at a program entry point, never constructible in the language.
Performing an operation of ability `a` requires both `a` in the effect row
*and* a `cap a` value in scope. The row is the static audit surface; the
capability is the dynamic blast-radius bound: a definition whose type
mentions no `cap net` cannot exfiltrate regardless of how badly it was
generated.

### 2.5 Totality

Loom is total by default. `fix` requires a `measure`: a term mapping the
recursive argument to a natural number that the oracle proves strictly
decreasing (obligation `terminates`, §6.2). If no measure is provable, the
definition must instead take the `div` ability in its row — divergence is an
effect, visible in every caller's type, all the way up.

### 2.6 Holes

`hole` carries its goal type and a constraint list (equalities and
membership facts the fill must satisfy). A term containing holes typechecks
— the hole inhabits its goal type by fiat — but is confined to the draft
region of the store and can never be the target of a binding (§5.4). Holes
are the unit of the generation loop's narrowing step (§8.3).

## 3. Static semantics (highlights)

Full formal rules are out of scope for v0.1; the load-bearing choices:

### 3.1 Elaboration before identity

The hashed form is the *elaborated* term: all types explicit, all instances
resolved, all implicit machinery discharged. Two agents whose inference
engines differ in power still agree on the identity of any term they can
both elaborate — identity never depends on inference strength.

### 3.2 Refinements and obligations

Refinement predicates live in a decidable fragment: quantifier-free linear
integer/real arithmetic plus datatypes and uninterpreted functions (roughly
what [SMT-LIB](https://smt-lib.org/) `QF_UFLIRA` + datatypes gives). Each
`ensures`-style refinement on a binding generates a **named obligation**;
obligations the solver discharges get `proof`-level evidence automatically;
the rest must be covered by weaker evidence explicitly (§6). Nothing is ever
silently unverified — every obligation has an evidence entry, even if that
entry is `assumption`.

### 3.3 No subtyping surprises

Refinement subtyping (`{x:T|φ} <: T`, and `{x:T|φ} <: {x:T|ψ}` when
`φ ⇒ ψ` is solver-valid) is the only subtyping in the language. No
inheritance, no variance annotations, no coercions.

### 3.4 Crisp by design — where uncertainty lives

It may seem perverse that a language built for a *stochastic* author has no
fuzzy or probabilistic judgments anywhere — no graded truth in refinements,
no confidence-weighted typechecks, no fuzzy numerics in the base types. The
omission is the design's central bet applied consistently: **all gradation
in Loom is epistemic, never semantic.** The system grades how well a crisp
proposition is known (the evidence lattice, §6.1); it never grades the
proposition itself.

Three reasons, in decreasing order of importance:

1. **The referee must not leak a gradient.** The generating agent optimizes
   against the oracle's signal. A graded acceptance — "this checks to
   degree 0.94" — is a reward surface, and reward surfaces get climbed:
   specification gaming would be rediscovered inside the toolchain. A
   two-valued gate with monotone thresholds (§6.3) is the only acceptance
   shape that gives the optimizer nothing to climb at the margin. The
   crispness is not inherited from human-era languages; it is load-bearing
   *because* the author is a sampler — human languages could afford fuzzier
   tooling precisely because the human was the referee.
2. **Content addressing needs crisp equality.** Identity, the memo ledger,
   and replication all hang off byte equality (§4). Fuzzy *values* encode
   fine; fuzzy *equality of terms* has no canonical answer — at what
   similarity do two definitions share evidence? — and every possible
   answer destroys the cached-forever economics of §6.4.
3. **Degrees of truth don't compose canonically.** Fuzzy conjunction is a
   choice among t-norms with no privileged option, so monotone assurance
   across a dependency graph would need a theory the field doesn't agree
   on. Epistemic grading composes by weakest-link, which §6 already does.

Where uncertainty *does* live, deliberately — three sanctioned homes:

- **In the author:** generation is sampling, type-directed masking is soft
  pruning (§8.2), and holes are declared uncertainty (§2.6).
- **In the data:**
  [fuzzy numbers](https://en.wikipedia.org/wiki/Fuzzy_number), intervals,
  and probability distributions are ordinary library ADTs (§2.3) — a crisp
  host carries fuzzy mathematics as *values*, the same way a pure language
  carries effects as data. A measurement pipeline in Loom should absolutely
  compute with `Fuzzy F64`; the *typechecking of that pipeline* stays
  two-valued.
- **In the evidence:** A1 `property` evidence is already a statistical
  claim, and v0.1 flattens it to a run count — the one place this spec is
  *less* fuzzy than it ought to be. See open problem 6 (§13).

## 4. Canonical form and identity

### 4.1 Normalization

Before encoding: bound variables are de Bruijn (α-equivalent terms are
byte-identical); metadata is absent by construction (names and prose never
appear in terms); the term is elaborated (§3.1); floats are canonicalized
(§2.2). No β/η normalization — identity is *intensional*: two extensionally
equal implementations are different definitions, because evidence attaches
per implementation.

### 4.2 Deterministic encoding

The encoding is CBOR restricted to the deterministic core of
[RFC 8949 §4.2.1](https://www.rfc-editor.org/rfc/rfc8949.html#section-4.2.1):
definite lengths only, minimal-length integers, map keys sorted bytewise
(maps appear only in store objects, not terms), no tags, no indefinite
forms. One term, one byte sequence.

### 4.3 Identity

A **def object** is `[0, type, term]` (leading `0` is the object-kind tag;
kinds: 0 def, 1 meta, 2 binding, 3 evidence — the tag makes cross-kind hash
collisions impossible by construction). The definition's identity is
SHA‑256 over the def object's encoding.

### 4.4 Worked example (verifiable by hand)

The identity function at `I64` — projection `id : I64 -> I64 = λx. x`:

```
type  = [2, [0,2], [], [0,2]]        ; fn(I64) —{}→ I64
term  = [3, [0,2], [0,0]]            ; lam(I64, var 0)
def   = [0, type, term]

bytes = 83 00                        ; array(3), kind 0
        84 02 82 00 02 80 82 00 02   ; the fn type
        83 03 82 00 02 82 00 00      ; the lam term
```

19 bytes total. `sha256(bytes)` =
`76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605`, so this
definition is `#76c62727` in any projection, in every store, forever.
(Reproduce: `printf '\x83\x00\x84\x02\x82\x00\x02\x80\x82\x00\x02\x83\x03\x82\x00\x02\x82\x00\x00' | sha256sum`.)

## 5. The store

### 5.1 Objects

Append-only. Four kinds (§4.3). Nothing is ever deleted or garbage
collected in v0.1 — history is the feature (P4), and definitions are small.

### 5.2 Meta objects

`[1, def-hash, name-path, spec-text, prov]` — names and prose attach here,
outside identity. This is the D7 concession made structural: the
prior-carrying surface exists, is versioned, and is queryable, but can never
change what a term *is*.

### 5.3 Bindings and namespaces

A binding is `[2, name-path, def-hash, evidence-set, policy-ref, seq]`.
Name-paths live in **namespaces**, each owned by a single writer at a time
(a lease held by one agent or principal) — the store itself needs no
consensus because objects are content-addressed and commutative; only
binding sequences are serialized, per namespace (P6). Rebinding is the
entire edit model: "changing" a function means appending a new definition
and a new binding record with a higher `seq`. Every previous state of every
namespace remains addressable.

### 5.4 The draft region

Definitions containing holes live under the reserved namespace `draft/`.
Bindings outside `draft/` may not reference any definition that transitively
contains a hole. Drafts are where the generation loop iterates (§8.3);
promotion out of draft is atomic with obligation checking.

## 6. Evidence

### 6.1 Kinds and the assurance lattice

An evidence object is `[3, obligation-id, kind, payload, result]`. Kinds:

| Level | Kind | Payload | Meaning |
|---|---|---|---|
| A3 | `proof` | checked derivation (solver certificate or proof term) | holds for all inputs |
| A2 | `exhaustive` | domain descriptor + enumeration digest | holds on the entire (finite) stated domain |
| A1 | `property` | generator hash, seed, run count | held on `n` sampled inputs |
| A0 | `assumption` | principal signature + justification text | trusted, unverified |

Order: `A0 ⊑ A1(n) ⊑ A1(m) ⊑ A2 ⊑ A3` for `n ≤ m`. Every obligation on a
binding carries exactly one evidence entry; `A0` is legal but loud (every
projection renders assumptions in front of everything else). The lattice
grades *knowledge of* a crisp proposition, never the proposition itself —
this is the only kind of gradation the system permits (§3.4).

### 6.2 Obligations

Generated per binding: one per refinement clause (§3.2), one `terminates`
per `fix` (§2.5), one `exhaustive-match` per `match` (discharged by the
typechecker, always A3), plus any policy-required properties (e.g., a
namespace policy may demand a `no-panic` property on everything it binds).

### 6.3 Monotone assurance

A rebind of name-path `p` is **refused** unless, for every obligation name
shared with the previous binding, the new evidence level ⊒ the old. New
obligations may enter at any level the policy allows; assurance on what
already existed never silently decreases. This is the store-level guarantee
that regeneration churn cannot erode verification over time.

### 6.4 The memo ledger

Evidence is keyed by `(def-hash, obligation-id, payload-hash)`. A result,
once recorded, is valid forever — content addressing makes cache
invalidation a non-problem, and in a regenerate-heavy workflow (P4) the
ledger converts verification cost from per-change to per-novel-definition.

## 7. Provenance

The `prov` field of a meta object: requesting principal, generating model
identifier, prompt hash, parent-definition hash (what this regeneration
replaced), timestamp. `why #9c31…` resolves intent without archaeology;
`lineage p` walks a name's rebind history with the spec text of each step.
Provenance is metadata: it can be wrong without making the term wrong, and
its trust level is exactly the signing principal's.

## 8. Generation protocol

### 8.1 Emission order

An agent emits a definition as the pre-order traversal of its canonical
encoding — i.e., it streams the CBOR bytes tag by tag. There is no textual
intermediate at any point. (§8.4 relaxes the *byte* part for current
models: the stored form is normative, the emission form is not.)

### 8.2 The mask

At each emission step the toolchain computes the set of admissible next
tokens and masks the rest of the vocabulary:

- **Syntactic masking (guaranteed):** only tags/values that can extend a
  well-formed encoding are admissible. Malformed CBOR and unknown tags are
  unsampleable. The class "syntax error" does not exist (P1).
- **Type-directed pruning (best effort):** the current goal type further
  prunes tags — a goal of function type admits `lam`/`ref`/`var`/`app`…;
  a `ref` position admits only hashes whose definitions inhabit the goal;
  a literal position admits only the goal's literal kind. This is pruning,
  not a guarantee: full type-directed masking is undecidable with
  refinements, so refinement failures surface at check time, not decode
  time. The spec is honest about which side of the line each check is on.

### 8.3 The narrowing loop

The intended authoring cycle: **draft → check → narrow.** The agent emits a
draft, placing `hole` nodes wherever its uncertainty is high; the oracle
typechecks and returns, for the first failure, the *smallest unsatisfiable
constraint* localized to a subtree; the agent regenerates only that subtree
(a new draft def sharing every other node by hash). Redraw budget is a
policy knob. Promotion out of `draft/` runs the full obligation set (§6.2)
and is atomic.

### 8.4 Feasibility on 2026 decoders

Could an agent write valid Loom under constrained decoding *today*?
Mostly yes — each mechanism maps to a demonstrated technique — with one
honest amendment to §8.1.

- **Grammar masking is commodity.** The term/type grammar (§2) is a small
  pushdown grammar, the same class as the JSON-schema and CFG constraints
  that [llama.cpp GBNF](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md),
  [Outlines](https://github.com/dottxt-ai/outlines), and
  [XGrammar](https://github.com/mlc-ai/xgrammar) enforce token-by-token in
  production, and that hosted APIs expose as structured outputs. The
  "syntax errors are unsampleable" guarantee is buildable now.
- **Scope and arity need a stateful mask.** "`var` index < binder depth"
  is context-sensitive — beyond off-the-shelf CFG engines, but a small
  custom logit processor on any open-weight serving stack: the masker
  tracks the traversal stack and binder depth. Hosted APIs that expose
  only declarative grammars cannot express this today; open-weight
  serving can.
- **Type-directed pruning has research precedent at exactly this tier.**
  [Synchromesh](https://arxiv.org/abs/2201.11227) enforced semantic
  constraints incrementally during decoding, and
  [type-constrained decoding](https://arxiv.org/abs/2504.09246)
  (Mündler et al.) enforces well-typedness on generated TypeScript via
  prefix automata plus a search over inhabitable types, halving
  compilation errors on models past 30 B parameters. Loom's §8.2 pruning
  tier is this technique pointed at a smaller, closed grammar — easier,
  not harder. Refinement-aware masking at token cadence remains out of
  reach, as §8.2 already concedes.
- **`ref` selection is trie-constrained retrieval.** A 32‑byte hash spans
  many tokens; the mask restricts to a precomputed typed candidate set
  and forces the chosen hash's remaining bytes through a prefix trie —
  the [GENRE](https://arxiv.org/abs/2010.00904) technique for constrained
  entity decoding, with the store index as the entity catalogue.
- **The amendment: emission form ≠ stored form.** Raw CBOR bytes are the
  wrong surface for byte-fallback BPE models — a model emitting `83 03…`
  has near-zero priors over every choice, and priors are the performance
  budget (P3, D7). The relaxation: the agent emits any *deterministic
  isomorph* of the canonical encoding — in practice a canonical
  S-expression surface whose tokens are the prior-rich names and keywords
  of §9's projections — and the toolchain transcodes to canonical bytes.
  Every guarantee survives, because the transcoding is total and
  deterministic and the isomorph is itself mask-generated with zero
  stylistic freedom; no free-form text ever exists, and hashing and
  identity are untouched. The isomorph is not an engineering compromise;
  it is the prior-delivery mechanism D7 predicted the design would need.
- **What masking cannot buy: competence.** Constraint guarantees validity
  while measurably distorting output quality when the format is alien to
  the model ([format-constraint effects](https://arxiv.org/abs/2408.02442)),
  so a masked model with no Loom corpus produces well-formed, well-scoped,
  type-plausible junk. Validity today; fluency only after the bootstrap
  problem (§13.1) is paid down.

## 9. Projection

Projections render store content for a reader; the projection grammar used
in this spec's examples (and the sketch's `median`) is normative for
*rendering only*. Rules:

- Names come from meta objects; a def with no meta renders as its hash.
- `var` indices render as generated names scoped to the definition.
- Effect rows render as `{a, b}` after the arrow; empty row renders as
  nothing (purity is the unmarked case).
- Evidence renders as one line per obligation, level first, `A0` first of
  all — assumptions are never below the fold.
- **No projection is parseable.** There is no grammar for authoring Loom as
  text, by anyone. Humans participate by reading projections, writing
  policy (§6.2), signing assumptions (§6.1), and approving promotions —
  the review surface, not the authoring surface.

The same projection machinery serves generating models their context: the
interface-only view (types + contracts + specs of candidate `ref` targets,
bodies withheld — sketch D3) is a projection with a visibility rule. The
model's working view and the human's reading view are one mechanism (D7).

## 10. Multi-agent operation

Objects replicate freely (content-addressed, commutative — the store is a
grow-only set and needs no coordination). Binding writes serialize per
namespace via the lease (§5.3). Two agents wanting the same namespace is a
scheduling problem, not a merge problem; there are no merge conflicts
because there is no text. Cross-namespace atomicity (bind `p` and `q`
together or not at all) is provided by a binding-group record and is the
only transactional primitive.

## 11. The boundary (FFI)

An `extern` definition wraps a foreign artifact (a WASM component in v0.1,
pinned by its own content hash) with a Loom type, a required capability set,
and mandatory `A0 assumption` evidence signed by a principal — the language
does not pretend to verify what it didn't check. Policy can quarantine:
namespaces may forbid transitive `assumption` evidence above a count, which
makes "how much of this system is faith?" a query with a number for an
answer. Compilation of Loom itself targets
[WASM](https://webassembly.org/) through a pipeline that is, aspirationally,
verified — the bottom layer of the essay's stack, reached without ever
passing through unverifiable text.

## 12. Worked example — `median`, end to end

Projection of the bound state after promotion (definition `#9c31…` under
name `stats/median`, policy `stats/POLICY` requiring ⊒ A1(10⁴) on ensures):

```
stats/median : (xs : List F64) -> {x : F64 | isMiddleOf x (sort xs)}
  spec  "Median of the sample; mean of the two middle values for even n."
  prov  principal wbnorris · model claude-fable-5 · prompt #e4a2… · replaces #77d1…
  obligations
    exhaustive-match   A3 proof        (typechecker)          memo #b02f…
    terminates         A3 proof        (measure: len xs)      memo #40aa…
    ensures.isMiddleOf A1 property     10_000 runs, seed 0x2f41  memo #77b0…
= let s = sort xs in
  match odd (len s)
    true  -> s ! (len s / 2)
    false -> (s ! (len s / 2 - 1) + s ! (len s / 2)) / 2
```

What the store actually holds: one def object (term + type, hashed), one
meta object (name, spec, prov), one binding under `stats/` with three
evidence entries, three memo-ledger rows. A later agent that regenerates
`median` must beat or match A1(10⁴) on `ensures.isMiddleOf` or its rebind
is refused (§6.3). A human reviewing this sees every assumption the system
is making about it — here, none.

## 13. Non-goals and open problems

**Non-goals (v0.1):** human text authoring (permanently); macros/staging;
performance model and codegen quality; a standard library beyond builtins;
IDE affordances.

**Open problems, inherited from the sketch and not solved by rigor:**

1. **Prior starvation.** The mask guarantees well-formedness, not
   competence; until a corpus exists, models will inhabit these types
   poorly. Bootstrap plan (transpile verified existing code, keep D7's
   natural-language surface rich) is a plan, not a result.
2. **Oracle regress.** Refinements and properties must be authored;
   a wrong contract verifies a wrong program at level A3. Loom shrinks the
   trusted surface to contracts + policy and makes it enumerable
   (`assumption` counting, §11) — smaller and visible, never zero.
3. **Type-directed masking depth** (§8.2) — how much pruning is
   affordable per token is an empirical systems question.
4. **Lease granularity** (§5.3) under high agent counts.
5. **Intensional identity** (§4.1) means semantically identical
   definitions duplicate evidence effort; an extensional-equality memo
   layer is future work.
6. **Confidence-quantified evidence.** Run-count ordering on A1 is a crude
   proxy — 10⁶ draws from a narrow generator can warrant less than
   10³ from an adversarial one. Evidence should carry an explicit
   statistical bound (failure probability at a stated confidence, relative
   to a stated generator), making policy thresholds numeric rather than
   positional. This tightens §3.4's epistemic dial without ever making a
   judgment fuzzy: the *bound* is graded, the *accept/refuse decision*
   against policy stays two-valued.

---

*Companions:
[design sketch](../docs/investigations/2026-08-12-loom-agent-native-language-sketch.md) ·
[essay analysis](../docs/investigations/2026-08-12-english-as-source-code-analysis.md)*
