# Plan — The masked-generation experiment

**Date:** 2026-08-13
**Status:** Designed; substrate not yet built
**Decides:** §8.4's central hypothesis; sequencing of the store

## Objective

Test Loom's central unresolved hypothesis: whether an LLM generates useful
canonical Loom programs more reliably and efficiently under grammar and
type-directed constraints. Everything else in the design — canonical objects,
hashes, policies, bindings — operationalizes decisions already made; this is
the one bet the design cannot validate on paper.

**Sequencing verdict: experiment next; full store afterward.** The store is
built from the evidence this experiment produces — in particular, whether the
hot path needs a compact indexed type/reference service, which is likely to
shape the store more than the current document-oriented design suggests. Until
the core generation loop is shown to work, no namespaces, leases, policy
admission, persistence, or garbage collection are built.

No visible surface beyond experiment output tables, so this plan carries no
mockups; the results report will carry its own.

## Rules

### R1 — Build only the minimal experiment substrate

A disposable "store-shaped resolver," built only where the experiment requires
it:

- Immutable in-memory objects keyed by hash.
- Resolution of declaration and definition types (the existing
  `DeclarationRegistry` / `DefinitionTypeRegistry` / `corpus_registry`
  machinery, unified behind one lookup surface).
- Corpus retrieval and few-shot prompt construction
  (`corpus_registry.few_shot_pairs()` is the seed).
- An **incremental parser/type-state interface for masking**: the per-token
  question "which next tokens keep this prefix extendable to an accepted
  definition," layered as syntax (GBNF) and type state (§8.2). This is the
  substrate's genuinely new component and its design core.
- Explicitly out: namespaces, leases, policy admission, persistence, garbage
  collection.

### R2 — Three comparable generation conditions

1. Unconstrained generation.
2. GBNF syntax-constrained generation.
3. Syntax plus type-directed masking.

Comparable means: same model, same sampling parameters, same prompts, same
task set, same budget per definition.

### R3 — Measurements

- Canonical parse acceptance; scope correctness; reference resolution;
  type-check acceptance (the four contract layers as a funnel).
- Semantic task success — did it produce the *asked-for* definition, not just
  a valid one.
- Tokens and redraws per accepted definition.
- Generation latency, especially masking overhead (this feeds the
  masking-overhead Watch item and the language re-evaluation's trigger (d)
  profiling).
- Diversity and repeated-definition rate — masking must not collapse
  generation into repetitive local choices.
- Error localization and repair cost — when a draw fails, how far in, and how
  much of the prefix survives §8.3-style narrowing.

### R4 — Corpus regimes

- No examples.
- Small few-shot set.
- Full current corpus.
- Held-out tasks requiring composition rather than memorization.

### R5 — The comparison that matters

Not "does masking increase valid syntax" — GBNF should make syntax nearly
trivial. The question is whether **type-directed masking improves completed,
semantically correct programs** without making decoding prohibitively slow or
collapsing diversity.

### R6 — Roadmap questions this experiment resolves

- Whether Loom's canonical surface is model-friendly.
- Whether the corpus is large and representative enough.
- Which checker operations must execute per token.
- Whether Python performance is already material (language re-evaluation
  trigger (d) gets its number here).
- What API the eventual store must expose to the masker.
- Whether hashes and de Bruijn indices damage generation quality.
- Whether richer projections are needed during prompting.

## Work

- [ ] Substrate: unified hash-keyed resolver over the existing registries.
- [ ] Substrate: incremental syntax mask (GBNF prefix-feasibility) exposed as a
  per-token API.
- [ ] Substrate: incremental type-state layer over it (§8.2 subset — the
  checker operations that can run per token; record which cannot).
- [ ] Harness: prompt construction per corpus regime; task set including
  held-out compositional tasks; the three conditions runnable with one command.
- [ ] Model/hardware selection recorded before running (T5 — needs the
  operator: local GGUF under llama.cpp is the natural path since `loom.gbnf`
  is llama.cpp-format).
- [ ] Run; produce the results report against R3's metrics and R6's questions.
- [ ] Record the store-shaping conclusions explicitly for the store plan that
  follows.

## Verification

Not yet run, deliberately: this plan is the experiment's design of record and
nothing is implemented. The steps below run and get recorded when the substrate
TODO item completes; the triaged inbox deferral points here.

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

plus the experiment's own reproducibility requirement: fixed seeds, recorded
model identity and sampling parameters, and rerunnable conditions.

## Completion criteria

- The three conditions run end-to-end on the same task set with recorded,
  reproducible configurations.
- Every R3 metric is reported per condition × regime.
- Every R6 question has an evidenced answer or an explicit "not answerable
  yet, because…".
- The store-shaping evidence is written down where the store plan will start
  from it.
