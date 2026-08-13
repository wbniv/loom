# Plan — Experiment Phase B: the incremental type-state masker

**Date:** 2026-08-13
**Status:** Planned; B1 dispatched, B2 gated on Phase A's failure profile
**Parent:** [Masked-generation experiment](2026-08-13-masked-generation-experiment.md) (R2 condition 4, R2.1 Phase B)

## Objective

Build condition 4: per-token type-directed masking layered over GBNF syntax
constraint, and run it against conditions 1–3 under the shared budget rule.
This is §8.2's first implementation and the experiment's decisive comparison
(R5): whether per-token pruning beats definition-level rejection sampling on
accepted definitions per token, without collapsing diversity or blowing the
latency budget.

## The B1/B2 split

**B1 — profile-independent core (dispatchable now):** the per-token decode
loop with logit-level masking, the incremental syntax-feasibility layer, the
type-state skeleton with *pluggable* pruners, instrumentation, and the
condition-4 runner integration — everything except the decision of which
pruners matter most.

**B2 — profile-directed completion (gated):** pruner priority ordered by
Phase A's failure-distribution-by-layer table; the condition-4 run; the R5
comparison. Dispatch only after Phase A reports.

## Rules

### R1 — Transport: logit access is the constraint

`llama-server`'s HTTP API exposes no per-token logit callback, so condition 4
cannot run over the Phase A backend. The implementer settles the transport;
the plan names the candidates and the decision criteria (per-token overhead
measurable and low; exact token-id-level masking; same GGUF and sampling
parameters as Phase A for comparability):

1. **In-process `llama-cpp-python` with a logits processor** — direct masking,
   grammar sampling available in the same process; adds one dependency; the
   1.5B model loads in-process comfortably on this box. Likely winner.
2. Token-stepped `/completion` calls with a per-step restricted grammar —
   server-compatible but pays HTTP + grammar recompilation every token.
3. A thin native shim over the llama.cpp C API — most control, most work.

Whatever is chosen, Phase A's conditions are NOT re-run on the new transport;
condition 4's latency is compared via per-token *decode and mask* overhead
(R3), not end-to-end wall clock across transports, and the plan's results
section must state this comparability boundary.

### R2 — The mask API

A per-token interface: given the emitted token prefix, return the set (or a
token-id mask) of next tokens that keep the prefix extendable to an accepted
definition. Layered:

- **Syntax layer**: GBNF prefix-feasibility — reuse llama.cpp's grammar
  engine where the transport provides it in-process; otherwise an incremental
  automaton over `loom.gbnf`.
- **Type-state layer**: a skeleton consuming the partial parse as it grows,
  with pruners as pluggable checks, each individually toggleable and
  individually timed. Candidate pruners (priority decided in B2): reference
  hashes must be resolvable prefixes; de Bruijn indices bounded by current
  binder depth; effect-row entries sorted/unique and prelude-valid; goal-type
  tracking against the definition's declared type. Which checker operations
  cannot run per token gets *recorded*, not forced.

### R3 — Instrumentation

Per token: mask computation time, tokens pruned, layer that pruned them.
Per cell: total mask overhead vs decode time — the number the
masking-overhead Watch item and the language re-evaluation both consume.

### R4 — Testability without a model

Mirror Phase A's stub pattern: the mask API is exercised by tests that walk
known-good corpus surfaces token-by-token (every prefix of a valid definition
must keep that definition's next token unmasked — soundness of the mask), and
known-bad continuations must be masked where the layer claims to prune them.
Mask *soundness* (never excluding a valid continuation) is the critical
property: an unsound mask silently corrupts the experiment.

## Work

B1 (this dispatch):

- [ ] Transport decision recorded with the R1 criteria; dependency wired.
- [ ] Syntax-feasibility layer with prefix-soundness tests over all corpus
  fixtures.
- [ ] Type-state skeleton with at least two pruners implemented (reference
  and de Bruijn candidates) behind toggles, each timed.
- [ ] Condition-4 integration in the runner behind the existing config
  (condition name `gbnf+typemask`), stub-tested end-to-end.
- [ ] Instrumentation per R3 in the run records and report.

B2 (gated on Phase A's report):

- [ ] Pruner priority from the failure distribution; enable/extend
  accordingly.
- [ ] Run condition 4; complete the R5 comparison and the parent plan's
  prediction scoring.

## Verification

Not yet run, deliberately: B1's steps run and get recorded when the B1
dispatch completes; B2's when B2 does. The triaged inbox deferral points here.

```sh
task prototype:test
python3 -m py_compile prototype/*.py prototype/experiment/*.py
task todo:lint
git diff --check
```

plus the mask-soundness suite over every corpus fixture, and (B2) the live
condition-4 run recorded by the runner.

## Completion criteria

- B1: every corpus fixture's canonical surface walks token-by-token with the
  full mask stack active and is never pruned (soundness); condition 4 runs
  end-to-end against the stub backend; per-pruner timing appears in records.
- B2: condition 4 live results reported against conditions 1–3 under the
  shared budget rule; R5 answered with numbers; predictions scored.
