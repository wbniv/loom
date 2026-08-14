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

### R2 — Four comparable generation conditions

1. Unconstrained generation.
2. GBNF syntax-constrained generation.
3. GBNF plus definition-level rejection sampling: generate under the grammar,
   run the full (already-fast) checker on each completed definition, redraw on
   rejection with §8.3-style narrowing. **This is type-masking's real economic
   rival** — if it matches condition 4 on accepted definitions per token, the
   per-token masker does not pay regardless of its correctness gains.
4. Syntax plus type-directed masking.

Comparable means: same model, same sampling parameters, same prompts, same
task set, and one budget rule for all conditions: a **fixed total token budget
per task**, counting accepted definitions within it. This is load-bearing —
masked decoding never fails at syntax, so its failures land late and
expensive, while unconstrained fails early and cheap; per-attempt budgets
would make the conditions incomparable. Throughput falls out of the same rule.

### R2.1 — Two-phase execution

**Phase A** runs conditions 1–3 across all four regimes. It needs none of the
substrate's hard part (llama.cpp samples under GBNF natively; the resolver and
prompt work is assembly), answers five of R6's seven questions on its own, and
produces the input Phase B's design needs: the **failure distribution by
checker layer** for GBNF-valid generations. **Phase B** builds the incremental
type-state masker *against that profile* — pruning first whatever layer
actually kills most generations — then runs condition 4. Building the masker
before seeing the distribution risks building an expensive pruner for the
wrong layer.

### R3 — Measurements

- Canonical parse acceptance; scope correctness; reference resolution;
  type-check acceptance (the four contract layers as a funnel).
- Semantic task success — did it produce the *asked-for* definition, not just
  a valid one. **Operationalized now, not at analysis time**: for
  corpus-drawn tasks, identity match against the pinned fixture bytes; for
  held-out compositional tasks, the mechanical floor is checked-tier plus
  exact type match, supplemented by a hand-scored rubric on a fixed sample —
  this metric is partly human, stated here so it cannot be silently dropped
  mid-run.
- Tokens and redraws per accepted definition (under R2's shared budget rule).
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

## Predictions (pre-registered)

Written before any run, so surprises are visible as surprises:

1. GBNF takes canonical parse acceptance to ~100%; unconstrained parse
   acceptance stays under ~30% in the no-example regime.
2. The dominant post-syntax failure layer for GBNF-valid generations is
   **reference resolution** in low-example regimes (64-hex hashes cannot be
   guessed) and **scope** (de Bruijn indices) once examples supply the hashes.
3. De Bruijn index errors are the single largest scope-error source, bearing
   on R6's hashes-and-indices question.
4. Condition 3 (rejection sampling) is competitive with condition 4 at
   current definition sizes — the honest prediction that threatens the
   per-token masker; masking must beat it on accepted-per-token to justify
   §8.2's complexity.
5. Python-side masking overhead is material relative to local decode speed
   (trigger (d)'s number lands above the threshold) but is dominated by model
   latency, not checker latency, in Phase A.
6. Masking reduces diversity mildly but does not collapse it; the
   repeated-definition rate rises most in the full-corpus regime
   (memorization pressure), not from masking.

## Work

Phase A:

- [ ] Substrate: unified hash-keyed resolver over the existing registries.
- [ ] Harness: prompt construction per corpus regime; task set including
  held-out compositional tasks; conditions 1–3 runnable with one command
  under the shared token-budget rule.
- [x] Model/hardware selection recorded before running. **Recorded
  2026‑08‑13, operator-approved; amended same day after two findings.**
  Final selection: `Qwen2.5-Coder-3B-Instruct GGUF Q4_K_M` (falling back to
  the 1.5B variant if measured eval throughput is under ~8 tok/s), served by
  `llama-server` (`-c 16384 --parallel 1 -ctk q8_0 -ctv q8_0`) built from
  [`ggml-org/llama.cpp@1f368f3`](https://github.com/ggml-org/llama.cpp/commit/1f368f354d9edcfea9fd6a1e0989b3e7335a050f)
  at `~/loom-tools/llama.cpp`; hardware Intel i7‑1185G7 (4c/8t, AVX‑512),
  32 GB RAM, CPU-only; token budget 512 per task, temperature 0.8, seeds
  {1,2,3}. Machine-local paths live in the untracked
  `experiment/phase_a.local.json`; a 21-cell smoke slice
  (`phase_a.smoke.json`) runs before the full 774-cell matrix.

  **Measurement deviation (recorded before the run):** `cache_prompt` is
  enabled (`backend_extra`) for CPU feasibility — uncached full-corpus prompts
  cost ~4 min each at the measured 42 tok/s prompt-eval rate. Latency metrics
  therefore measure *cached* serving; the masking-overhead comparison (R3) is
  per-token decode overhead and is unaffected. KV-cache quantization
  (`-ctk/-ctv q8_0`) is NOT used: it cut prompt eval to ~12 tok/s on this CPU.

  **GPU-run restoration (2026‑08‑13):** with the run moved to a rented
  g6.xlarge (L4 24 GB) per the GPU-experiment-infra plan, the CPU concessions
  are reversed: the run uses the *originally approved*
  `Qwen2.5-Coder-7B-Instruct Q4_K_M` (the 1.5B fallback was hardware-driven
  and is so recorded) and the full seed set {1, 2, 3}; the smoke's
  512-token draw cap stands. Recorded before launch.

  **Smoke-run amendment (2026‑08‑13):** the 21-cell smoke produced 57 draws,
  0 acceptances, and a decisive artifact diagnosis: all 25 grammar-constrained
  "parse" failures are truncations (2–8 unclosed parens each; zero
  balanced-but-rejected, so the GBNF is sound against the canonical parser
  in-sample). The 256-token per-draw cap starves definitions — 64-hex hashes
  cost ~25–35 tokens each, an early R6 answer: hashes hurt as budget damage.
  Config amended for the full run: `max_tokens_per_draw` 512 (= the full task
  budget in one draw), seeds {1} for the first full pass (smoke wall-time
  extrapolates 3 seeds to ~46 h on this CPU; one seed ≈ 15 h). The dominant
  *checker* layer among completed drafts is typecheck, then scope
  (de Bruijn share 1.0) — the Phase B gate signal to carry into B2, along
  with a new pruner candidate the truncation data suggests:
  completion-pressure (prune openings that cannot close within the remaining
  budget).

  **GPU run-attempt log (2026‑08‑14):**
  - *Attempt 2* (spot L4, us-central1): built and ran at 97 % GPU utilization,
    then crashed 552 records in — the model invented ability hash `0x00…01`
    and the evaluation funnel raised an uncaught `DeclarationError` through
    the scope layer's arity resolver. Fixed: resolver refusals now classify
    as the consulting layer's rejection per §2.3.1 (regression tests pin both
    handle shapes); partial data archived as `runs/phase-a-full-attempt1/`.
  - *Attempt 3* (spot): **preempted** by GCP 30 minutes in, mid-build
    (`compute.instances.preempted`, 07:34 UTC); the exit trap never ran, so
    no artifacts. Also surfaced a build-cache key mismatch (short vs full
    revision hash), corrected.
  - *Attempt 4* (running): **on-demand** — with trial credits the 2.4× price
    is still $0 out of pocket and preemption is eliminated; launched with
    the seeded build cache and hardened funnel.

  **Amendment record (history kept, not erased):**
  - The first selection, `Qwen2.5-Coder-7B-Instruct Q4_K_M` (byte-verified
    against HF: sha256 `509287f7…`), is not viable on this hardware: the
    server's default 131k-context/4-slot KV allocation was OOM-killed by the
    kernel (10.5 GB anon-rss), and the measured eval rate under memory
    pressure was 0.10 tok/s — mmap thrash, not compute. The 7B GGUF is kept
    on disk for a future GPU host. This build's `llama-cli` also exits
    silently without generating (`-no-cnv` path), so the backend is
    `llama-server` regardless of model.
  - Kimi K3 (2.8T MoE, open weights 2026‑07‑27) was evaluated at the
    operator's request: hosted APIs expose JSON-schema constraints only — no
    GBNF — so conditions 2–3 cannot run hosted, and self-serving needs
    multi-node H100/B200 under vLLM+XGrammar. Operator decision: drop K3 for
    this experiment, keep the original single-local-model design. A future
    frontier-scale arm (vLLM+XGrammar, which could even host Phase B's masker
    via custom logits processors) is noted as an option the store/language
    decisions do not depend on.
- [ ] Run Phase A; report R3 metrics per condition × regime; produce the
  failure distribution by checker layer.

Phase B (gated on Phase A's failure profile):

- [ ] Substrate: incremental syntax mask (GBNF prefix-feasibility) exposed as
  a per-token API.
- [ ] Substrate: incremental type-state layer over it (§8.2 subset,
  prioritized by Phase A's profile — the checker operations that can run per
  token; record which cannot).
- [ ] Run condition 4; complete the R3 report and the R5 comparison against
  condition 3.
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

- All four conditions run end-to-end on the same task set with recorded,
  reproducible configurations, under the shared budget rule.
- Each pre-registered prediction is scored true/false/partial in the results
  report.
- Every R3 metric is reported per condition × regime.
- Every R6 question has an evidenced answer or an explicit "not answerable
  yet, because…".
- The store-shaping evidence is written down where the store plan will start
  from it.
