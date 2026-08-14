# Constrained generation, results

**Date:** 2026‑08‑14

Loom is a specification for an agent-native programming language: syntax,
type system, and a content-addressed store designed for an LLM to be the
only author, with human ergonomics given zero design weight. The design's
one unproven bet is whether that trade pays off — whether constraining a
model's decoding to Loom's grammar and type discipline actually makes it
write more, and more correct, Loom than letting it write freely and
checking the result afterward. This article reports the first experiment
built to answer that, end to end, on one open-weight model.

Everything below traces to two run reports and the plan that pre-registered
the predictions before either run happened:
[Phase A](../results/2026-08-14-phase-a-report.md) (2,335 draws, conditions
1–3), [the condition‑4 report](../results/2026-08-14-phase-b-condition4-report.md)
(773 draws, the masker), and
[the experiment plan](../plans/2026-08-13-masked-generation-experiment.md)
(design and the scored predictions). The masker's own design and its
five-launch path to a clean run are in
[the Phase B plan](../plans/2026-08-13-experiment-phase-b.md).

## Method

Four generation conditions, compared on the same model, same prompts, same
task set:

1. **Unconstrained** — the model samples freely; validity is checked after
   the fact.
2. **GBNF** — decoding is restricted to Loom's grammar, so malformed
   S‑expressions are unsampleable. Type and scope errors still happen; only
   syntax is guaranteed.
3. **GBNF + rejection sampling** — generate under the grammar, run the full
   checker (parse → scope → references → typecheck) on the completed
   definition, and redraw on rejection. This is the masker's real economic
   rival: if it matches condition 4 on accepted definitions per token, the
   more complex per-token masker buys nothing.
4. **GBNF + type-directed masking** — a per-token mask that prunes not just
   syntax but scope (de Bruijn binder depth), reference feasibility (which
   hashes could resolve here), and goal-type (what the declared type forces
   at this position), computed incrementally as each token is emitted.

Each condition ran under four corpus regimes — no examples, a small
few‑shot set, the full current corpus, and held‑out tasks that require
composing existing definitions rather than recalling one — and a single
budget rule held across all sixteen cells: a fixed 512‑token budget per
task (up to 32 draws to spend it), counting only accepted definitions. This
is load-bearing: masked decoding never fails at syntax, so its failures
land late and expensive, while unconstrained generation fails early and
cheap. A per-attempt budget would have made the conditions incomparable; a
per-task budget makes accepted-definitions-per-1,000-budget-tokens the one
number all four conditions can be judged on.

Six predictions were written down before any run — parse acceptance under
GBNF, which checker layer dominates post-syntax failures, whether de Bruijn
indices are the dominant scope-error source, whether masking beats
rejection sampling, whether masking overhead is material, and whether
masking collapses output diversity. All six are scored below.

**Hardware and model, once, for both phases:** Qwen2.5‑Coder‑7B‑Instruct
GGUF Q4_K_M, one L4 GPU (a g2‑standard‑4 instance, 24 GB), temperature 0.8,
seeds {1, 2, 3}. Conditions 1–3 served over `llama-server`; condition 4 ran
in-process over a ctypes shim on the same pinned llama.cpp build, because
`llama-server`'s HTTP API exposes no per-token logit callback. That
transport split means **wall-clock latency is not comparable between
condition 4 and conditions 1–3** — the comparable numbers are accepted
definitions per token (the shared budget rule) and per-token mask
overhead, both measured inside the masker itself regardless of transport.

**The scale limits, stated plainly.** This is one model, one size, one GPU.
7B is well below frontier scale, and nothing here says whether a larger
model would need the mask less (more prior mass on valid Loom already) or
more (more capacity to exploit what the mask permits). Every semantic
success recorded — all 19 of them, across both phases — was a
byte-identical match to a corpus fixture, i.e. memorization, not synthesis;
held-out compositional tasks scored zero acceptance in three of four
conditions and near-zero in the fourth. Whether constrained decoding helps
a model *compose* Loom it hasn't seen is not answered here — only that this
model, at this size, didn't do it under any condition tested.

## Results

Combined, the two phases produced 3,108 draws, 302 checker-accepted
definitions, and 19 byte-identical semantic successes, with zero
mask-soundness violations recorded across every fixture and tokenization
tested.

### The comparison that matters: accepted definitions per 1,000 budget tokens

| regime | gbnf (c2) | gbnf+rejection (c3) | **gbnf+typemask (c4)** | c4 vs c3 |
|---|---|---|---|---|
| none | 0.326 | 0.501 | **0.851** | **+70 %** |
| few_shot | 0.376 | 0.326 | **0.476** | **+46 %** |
| full_corpus | **1.452** | 1.377 | 1.377 | ±0 |
| held_out | 0.000 | 0.081 | 0.081 | ±0 |

(from [the condition‑4 report's R5 section](../results/2026-08-14-phase-b-condition4-report.md))

Masking wins by the largest margin exactly where the model has the least
to go on — no examples in context — and is indistinguishable from plain
grammar sampling once the full corpus is available. Semantic (not just
checker-accepted) successes follow the same shape: condition 4 scored 5 in
full_corpus (against 4 for gbnf, 3 for gbnf+rejection) and 1 in few_shot
(against 0 and 3); held_out scored 0 under every condition. Repeat rate in
full_corpus — how often the model reproduces the same definition rather
than a distinct one — was 0.836 under masking against 0.879 under plain
grammar sampling, so masking did not collapse diversity to buy its gains.

### Where the failures moved

The four-layer funnel is parse (does it parse as canonical Loom) → scope
(are de Bruijn indices in range) → references (do hashes resolve) →
typecheck (does it type). Comparing Phase A's grammar-constrained
conditions (2 and 3 combined, 1,671 draws) against condition 4's own funnel
(773 draws — the draw counts differ, so these are before/after distributions,
not a controlled A/B on identical inputs):

- **Scope failures: 268 → 17.** This is the de Bruijn pruner's kill — the
  single largest funnel movement in the experiment, and the mechanism the
  goal-type and de Bruijn layers were built to prune first, per Phase A's
  own failure-distribution gate.
- **Reference failures: 115 → 75.**
- **Typecheck failures: 590 → 316** — which is 41 % of condition 4's 773
  draws, making typecheck the dominant *surviving* failure layer once
  scope is largely closed. This is the layer the per-token masker's proof
  discipline explicitly abstains on in several positions (an `app`'s
  argument goal, a `let`'s bound term, a `match` scrutinee — see the Phase
  B plan's abstention list) rather than prune unsoundly.
- **Parse/truncation: roughly unchanged, ~33 %** of draws either way — the
  512‑token budget, not the grammar, is the wall here. Every grammar-side
  parse failure Phase A traced was a truncation, none a rejected-but-balanced
  program.

### Mask cost

Across the 773 masked draws (132,096 mask steps, 152,064‑token
vocabulary): mask computation totaled 416.48 s, or **3.15 ms/token warm**
(6.69 ms/token cold, before the transition cache fills) — **10.4 %** of
masked-draw latency, with the rest spent in model decode. That is material
enough to measure, and small enough that it does not approach the
language-plan's 25 % trigger for reconsidering the implementation
substrate.

Almost all of that mask time is spent in one place: the syntax layer's
trie walk costs 413.47 of the 416.48 total seconds (over 99 %); the three
type-directed pruners together — de Bruijn, goal-type, reference-hash —
add well under one second combined, despite doing the pruning that moves
the acceptance numbers above. The syntax layer runs a depth-first walk
over every surviving token piece at every step; the type layers only veto
within what that walk already narrowed.

### The corpus is the largest lever measured, not the sampling strategy

Plain grammar sampling's acceptance rate roughly quadruples going from no
examples to the full corpus (gbnf: 0.326 → 1.452, +345 %); the same move
helps the other two conditions less dramatically because they start from a
higher no-example floor (gbnf+rejection: 0.501 → 1.377, +175 %;
gbnf+typemask: 0.851 → 1.377, +62 %) — but every condition's largest single
jump across the whole experiment is this one, from no examples to the full
corpus. Phase A's own reject-rate table
tells the same story from the failure side: grammar-constrained draws are
rejected 95.8 % of the time with no examples in context, versus 71.5 %
with the full corpus. No sampling strategy tested closes a gap that size;
what closes it is what the model has seen.

### Held-out composition ≈ 0, everywhere

Across all four conditions, held-out compositional tasks produced zero
semantic successes, and checker-acceptance in that regime never exceeded
0.081 accepted per 1,000 budget tokens — a single accepted (not
necessarily correct) definition under rejection sampling and under
masking, none at all under plain grammar or unconstrained generation. The
corpus buys recall of what the model has already seen; nothing measured
here buys synthesis of what it hasn't.

## The verdict

Stated exactly, from the condition‑4 report: **masking weakly dominates
rejection sampling — never loses, wins large without examples — but does
not beat plain grammar sampling in the corpus-rich regime.** Masking is the
right default when a task set can't guarantee rich in-context examples; it
is not a free win once the corpus does that job on its own, and its added
complexity (a per-token type-state layer, five proof rules, an abstention
list) is not repaid in the regime where the corpus is doing the work
anyway.

## What the predictions got wrong

Two of the six pre-registered predictions were not fully right — which is
the point of pre-registering them.

- **Prediction 1 (partial).** GBNF was predicted to take parse acceptance
  to ~100 %. It did not: 31 % of grammar-constrained draws still failed at
  parse, and every one of them was a truncation — the 512‑token budget
  running out mid-definition, not a grammar defect. The unconstrained
  prediction half held (0 % parse acceptance with no examples, well under
  the ~30 % bar).
- **Prediction 2 (false).** Reference resolution was predicted to be the
  dominant post-syntax failure layer in low-example regimes, with scope
  taking over once examples supply hashes. Neither held: typecheck
  dominates overall (590 of 1,671 grammar-constrained draws, against 115
  for references), and scope is only the leading failure in the
  no-example regime specifically.

The other four scored true or confirmed: de Bruijn indices are 97.8 % of
scope failures (prediction 3); masking beats rejection sampling without
beating plain grammar in the corpus-rich regime, exactly as scored above
(prediction 4); mask overhead is measurable but decode-dominated at 10.4 %
(prediction 5); and masking did not collapse diversity, with the
full-corpus regime's higher repeat rate (0.88–0.93) explained by
memorization pressure rather than the mask (prediction 6).

## Getting a clean condition‑4 run took five tries

Worth one honest paragraph, not more: the live condition‑4 matrix needed
five launches on rented GPU capacity before one completed — a decode that
silently ran on CPU with the GPU idle, an out-of-memory crash traced to an
unbounded type-state memo for text-literal bytes nothing was reading, a
zone-wide capacity stockout, and a batch-size assertion on the first
11.9k‑token full-corpus prompt. Each was diagnosed, fixed, and pinned with
a regression test before the next attempt; the full account, including the
root-cause analysis for each, is in
[the Phase B plan's run log](../plans/2026-08-13-experiment-phase-b.md#condition-4-run-log).

## Reproducing this

The experiment substrate lives under `prototype/experiment/`:
`runner.py` drives all four conditions; `masker.py` and `gbnf.py` implement
the mask; `llama_ffi.py` is the ctypes transport for condition 4;
`phase_a.config.json` / `phase_b.config.json` are the run configurations.
Corpus fixtures are under `prototype/corpus/`. The mask-soundness suite —
every corpus fixture walked token-by-token under four tokenizations, with
the fixture's own next token asserted never masked — runs with the rest of
the prototype's tests:

```sh
task prototype:test
```

The full reports carry every number in this article plus per-layer error
localization, transition-cache behavior, and the config used for each run:
[Phase A](../results/2026-08-14-phase-a-report.md),
[condition 4](../results/2026-08-14-phase-b-condition4-report.md). The
design document that pre-registered the predictions and scored them is
[docs/plans/2026-08-13-masked-generation-experiment.md](../plans/2026-08-13-masked-generation-experiment.md);
the masker's design and build history is
[docs/plans/2026-08-13-experiment-phase-b.md](../plans/2026-08-13-experiment-phase-b.md).
Framing in the spec itself: [SPEC.md §8.4](../../SPEC.md) (feasibility on
2026 decoders) and [§13, open problem 3](../../SPEC.md) (masking depth,
now measured).
