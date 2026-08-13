# Design sketch — Loom, a language for agents as sole authors

**Date:** 2026‑08‑12
**Context:** Companion to
[the essay analysis](2026-08-12-english-as-source-code-analysis.md), which
argued that an agent-optimal language would be *more* formal and largely
legible, not an opaque token soup. This document tests that claim by actually
doing the design: derive a language from the mechanics of LLM agents —
sampling, scarce context, prior-driven competence — with zero weight given to
human authorship comfort, and see where the optimizer lands.
**Type:** Design sketch / thought experiment. Nothing here is implemented.
**Now specified:** the full v0.1 specification lives in
[SPEC.md](../../SPEC.md) — node tables, deterministic encoding,
store/evidence semantics, generation protocol.
**Name:** *Loom*, after the
[Jacquard loom](https://en.wikipedia.org/wiki/Jacquard_machine) — the first
machine programmed in a notation (punched cards) that no human read fluently
and no human missed.

---

## Conclusion

An AI-only language is designable, and several of its features would be
genuinely alien to human programmers: a canonical binary AST as the *only*
stored form, zero stylistic degrees of freedom, identity by content hash
rather than by name, and verification evidence memoized per definition
forever. Humans would hate authoring it.

But the design refuses to become illegible. Two forces push it back toward
legibility at every decision point:

1. **LLM competence is borrowed from natural language.** Strip the names,
   the specs, and the prose anchors, and you strip the model's own priors —
   the generator gets *worse*, not better. The token soup version is
   anti-optimal for the AI itself.
2. **A stochastic author needs a deterministic checker,** so every definition
   grows contracts, effects, and evidence — and a contract-saturated notation
   is largely human-readable as a side effect, because analysability and
   legibility come from the same properties (explicitness, locality,
   compositionality).

The result is an AI-*first* language whose stored form no human reads and
whose projected form almost any engineer can. That is the essay's speculation
half-confirmed and half-refuted: yes, agents would choose their own
representation; no, it does not free anyone from the notion of "good code" —
it *mechanizes* that notion per definition.

## Design pressures

Everything below is derived from six facts about how LLM agents actually
operate. A language designed for agents is a language designed around these.

| # | Fact about the author | Design consequence |
|---|---|---|
| P1 | Generation is token sampling — every output is a draw, and syntax errors are wasted draws | Make invalid programs *unrepresentable at decode time*: grammar co-designed with a decoding mask |
| P2 | Context is the scarce resource | Maximize local reasoning: full contract at every interface, no action at a distance, high semantic density per token |
| P3 | Competence is priors — `sort` and an English spec carry enormous predictive signal | Natural-language anchors are performance-critical inputs, not decoration; keep them |
| P4 | Agents regenerate units rather than patch lines | Small content-addressed definitions; identity by hash; edits are rebinds, not diffs |
| P5 | The only ground truth in the loop is a deterministic oracle | Push maximal checking into the toolchain: types, effects, refinements, evidence — and memoize all of it |
| P6 | Many agents, no shared memory, no hallway conversations | Intent and provenance must travel *inside* the artifact |

## The design

### D1. No concrete syntax — a canonical AST is the program

The stored artifact is a normalized, deterministically serialized AST
(CBOR-style). There is exactly one byte sequence per program: no whitespace,
no formatting choices, no naming-convention entropy. Diffs are semantic by
construction. The grammar is designed jointly with a *decoding mask* so that
during generation, tokens that cannot extend a well-formed program are simply
unsampleable — the class "syntax error" does not exist (P1). Humans never see
this form; see D7.

### D2. Content-addressed store, not files (after [Unison](https://www.unison-lang.org/))

A definition's identity is the hash of its normalized AST. There are no
files, no builds, no version ranges, no dependency conflicts — a definition
refers to the exact hashes of the definitions it uses. "Editing" means adding
a new definition and rebinding a name to it; the old one remains, so every
past state of the system is trivially addressable (P4). The killer economy:
**verification results are memoized by hash, forever.** A test or proof run
once for `#9c31…` never runs again, no matter how many agents regenerate
code around it. In a regenerate-heavy workflow this converts verification
from a per-change tax into an append-only ledger.

### D3. Saturated interfaces — the callee's body is invisible

Every definition carries, inseparably: a type, refinement pre/postconditions,
an algebraic effect row, and the object-capabilities it consumes. The
projection served to a generating agent shows callees' *interfaces only* —
bodies are withheld by default. This is P2 turned into an enforcement
mechanism: an agent physically cannot depend on implementation details it was
never shown, so all reasoning is local and every dependency is
contract-mediated. Capabilities double as the blast-radius bound for a wrong
generation: a function without the `net` capability cannot exfiltrate,
however badly it was generated.

### D4. Evidence-carrying definitions

Each definition ships its own `evidence` block: a machine-checked proof term
where feasible, an exhaustive check where the domain is small and finite,
recorded property-test runs (generator, seed, count) otherwise. The store
enforces **monotone assurance**: a rebind whose evidence is weaker than the
binding it replaces is refused. "Does it work?" stops being a hope about the
whole system and becomes a queryable, per-definition, cached fact (P5) —
with its weakest form (sampled properties) explicitly labeled as such.

### D5. Provenance is a field, not a commit message

The requesting principal, the spec prose, and the generating model + prompt
hashes are fields *of the definition* (P6). `why #9c31…` is a query, not an
archaeology project. When behaviour surprises someone — human or agent — the
comparison target (what was asked) is attached to the artifact itself, which
is the essay-analysis "spec recovery" problem given a mechanical answer.

### D6. Typed holes

A partial program is a valid program: `?h : T requires P` typechecks, and
the toolchain either synthesizes the hole from smaller verified parts or
reports the smallest unsatisfiable constraint. Agents iterate by narrowing
holes rather than by regenerating whole units and re-diagnosing from raw
compiler errors.

### D7. Names and specs are metadata — and they stay (the load-bearing concession)

Identity is the hash, so names are not needed for linking. They are kept
anyway, as attached metadata, because of P3: `median` plus one English
sentence is worth more to a generating model than any amount of structural
context. This is the decision that kills the essay's opaque version from the
inside — the illegible language is *worse for the AI*, not just for us. And
since the store already holds names, specs, and contracts, rendering a
human-readable projection costs nothing. The projection humans read and the
prior-rich view the model performs best on are substantially the same view.

### D8. Crisp judgments, graded knowledge (why no fuzzy anything)

Every judgment in the system — typechecks, hash equality, obligation
acceptance — is two-valued, and that is a decision, not classical inertia.
A graded acceptance ("checks to degree 0.94") is a reward surface the
generating agent would learn to climb, and content addressing needs crisp
equality or the memoized-evidence economics (D2, D4) collapse. Uncertainty
gets exactly three sanctioned homes: the sampling author (holes, soft
masking), the *data* (fuzzy numbers, intervals, and distributions as
ordinary ADTs in a crisp host), and the evidence lattice — which grades how
well a crisp proposition is known, never how true it is. The one dial the
design keeps analog is epistemic. Counterintuitively, a language for a
probabilistic author ends up *more* classical than languages for humans:
humans could afford fuzzy tooling because the human was the referee, and
when the author is a sampler, the referee is the one thing that must not be.

## What a definition looks like (human projection)

```
median : (xs : List F64) -> F64
  requires  nonEmpty xs
  ensures   isMiddleOf result (sort xs)
  effects   ∅                            -- pure: no capabilities consumed
  spec      "Median of the sample; mean of the two middle values for even n."
  evidence  perm-invariance  : property, 10_000 runs, seed 0x2f41 ✓   memo #77b0…
            small-exhaustive : all xs with len ≤ 6 over value grid ✓  memo #a91c…
  prov      principal wbnorris · model claude-fable-5 · prompt #e4a2…
= let s = sort xs in
  if odd (len s) then s ! (len s / 2)
  else (s ! (len s / 2 - 1) + s ! (len s / 2)) / 2
```

This text is a *projection* — one of several possible renderings of stored
hash `#9c31…`. The agent that authored it emitted canonical AST bytes under
a decoding mask; no human-syntax parser exists because none is needed.

## What is genuinely AI-only here

Four features that would be miserable for human authors and are exactly right
for agents — the defensible core of the essay's speculation:

- **The wire form.** Nobody hand-writes canonical CBOR ASTs; nobody has to.
- **Zero style freedom.** Humans experience formatting choice as expression;
  for a sampler it is pure entropy that burns draws and pollutes diffs.
- **Hash-identity ergonomics.** Humans need stable names to navigate;
  an agent needs only the store and the query interface.
- **The evidence economy.** Memoized-forever verification is designed for a
  workflow that regenerates constantly — human workflows never needed it
  this badly.

## Honest failure modes

- **Prior starvation / bootstrap paradox.** Until a large Loom corpus
  exists, models write it worse than Python — the essay's "fluency from spec
  alone, no training data" is assumed, not established, and it is the single
  assumption this whole design leans on hardest. Mitigation is D7 (keep the
  natural-language surface) plus transpilation of existing verified code,
  but the cold start is real.
- **Oracle regress.** Contracts must come from somewhere. Loom moves the
  trust boundary from ten thousand lines of code to ten lines of
  `requires`/`ensures` — a smaller, reviewable surface, but a wrong contract
  verifies a wrong program beautifully. The specification problem is
  *relocated and shrunk*, never solved.
- **Edge unverifiability.** FFI to the legacy ecosystem (P3's cousin: all
  the value lives in existing libraries) reintroduces unverified edges, and
  every capability granted at the boundary is a hole in the blast-radius
  story.

## Verdict, relative to the essay

The essay asked: *why wouldn't agents create a language that meets their
needs perfectly?* Designing one shows they plausibly would — and that its
needs are canonical form, content addressing, saturated contracts, attached
evidence, and preserved natural-language anchors. Every one of those makes
the artifact **more** inspectable than today's Python, not less. The
projection layer that keeps humans able to read it isn't charity, and it
isn't backwards compatibility — it is the same machinery that feeds the
model its own best working representation. "AI-only" turns out to mean
*AI-first, human-auditable*, and the essay's endpoint — code nobody can or
need read, judged only by "does it work" — is the one point in the design
space the design pressures themselves rule out.
