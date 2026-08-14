# Plan — Experiment Phase B: the incremental type-state masker

**Date:** 2026-08-13
**Status:** B1 implemented and verified; B2 gated on Phase A's failure profile
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

#### Decision (B1, 2026‑08‑13): candidate 3 — a ctypes shim over the pinned `libllama.so`

**Chosen:** [`prototype/experiment/llama_ffi.py`](../../prototype/experiment/llama_ffi.py),
about fifteen `ctypes` declarations over
`~/loom-tools/llama.cpp/build/bin/libllama.so` — the *same build* Phase A
serves with, [`ggml-org/llama.cpp@1f368f3`](https://github.com/ggml-org/llama.cpp/commit/1f368f354d9edcfea9fd6a1e0989b3e7335a050f).
Backend name `llama-cpp`; it implements `generate_masked` only and refuses
`generate` by name, so no Phase A condition can drift onto it.

**Why the expected winner lost.** `llama-cpp-python` publishes **source
distributions only** — checked against PyPI for 0.3.27 through 0.3.34, no
wheels of any kind — so "adds one dependency" is really *builds a second,
differently pinned copy of llama.cpp from source*. That is exactly the engine
identity R1's comparability criterion asks us to hold fixed, and it costs a
CMake build and roughly a gigabyte of artefacts on a box the parent plan
already records as memory-constrained (~9 GB free, CPU-only). Binding the
build that already exists keeps the engine bit-identical to Phase A's and adds
no dependency at all.

**Why "most work" turned out not to be.** The premise that candidate 3 is
expensive assumed the mask would reuse llama.cpp's grammar engine and so need
the sampler ABI. It does not: R4 requires the syntax layer to be testable with
no model on every `task prototype:test`, so the syntax layer is our own
incremental automaton over `loom.gbnf`
([`experiment/gbnf.py`](../../prototype/experiment/gbnf.py)). With grammar
sampling out of the picture the transport only has to load, tokenize, decode one
token, read logits and detokenize.

**Rejected, candidate 2** (token-stepped `/completion`): pays an HTTP round trip
*and* a grammar recompilation per token, and it would also mean pointing the
run at the shared `llama-server` that Phase A's live run needs.

**Criteria, scored.** Exact token-id masking: yes — the mask returns token ids
and `select_token` samples over that subset, so a 151k-wide softmax never runs.
Measurable per-token overhead: yes — R3's instrumentation lives in the masker,
not the transport, so the number is transport-independent. Same GGUF and
sampling parameters: yes, and the same engine binary as well.

**Dependency provisioning.** There is no PyPI dependency to provision, which is
the point. What a live condition-4 run needs is: the pinned llama.cpp build's
`libllama.so` (already on the box; overridable per run via the config's
`llama_lib` or the `LOOM_LLAMA_LIB` environment variable) and a GGUF via
`model_path`. `experiment/phase_b.config.json` ships with an empty `backend`
so the entry point refuses until an operator fills those in, exactly as Phase
A's config does.

**Escalation condition, checked and clear.** A byte-level mask over token
pieces is only sound if the model's detokenization *is* concatenation of those
pieces. `LlamaModel` asserts that at load and refuses to construct otherwise,
because a tokenizer where it failed would make the mask unsound at the token
boundary — a Phase-B-reshaping finding, not a bug to patch. Qwen2.5-Coder is
byte-level BPE and passes.

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

#### As built (B1)

Both layers are **byte oracles**, which is the shape decision that made the
rest fall out. `gbnf.Grammar` answers "which bytes keep this prefix alive";
`masker.TypeState` answers "what atom am I in and at what binder depth", and a
pruner answers "may this byte follow". They compose into a single memoized
transition over the pair, and the mask is one depth-first walk of a trie over
the token pieces — a byte the mask refuses cuts that byte's whole subtree in
one step, which is why per-token cost is proportional to what survives rather
than to the vocabulary.

**The soundness rule, stated in code and here.** A pruner may veto a byte only
when it can *prove* no completion of the current atom reaches an accepted
definition. That is stronger than "only fire at atom boundaries", and it is
what makes mid-atom vetoes safe — both shipped pruners have a monotone proof
(trie membership; `uint` only grows, so a partial index's minimum completion is
itself). Where no proof exists the layer abstains: a `handle` operation body
binds `parameter_count + 1` variables and the count needs ability resolution
that a byte prefix does not carry, so that subtree is marked depth-unknown and
the de Bruijn pruner says nothing inside it. **That is R2's "record, don't
force" in code** — and it is the first entry in the answer to R6's *which
checker operations must execute per token*.

Two design consequences worth naming because they cost aggression to buy
correctness:

- The reference pruner's trie is the **union** over every kind the resolver
  holds (definitions, data, abilities, externs) rather than a per-position
  trie. A union is a superset of the right set at every position, and a
  superset is the safe side of R4. Kind-specialising it is a B2 lever.
- If the type layer would empty a *non-empty* syntax mask, the step falls back
  to syntax alone and the fallback is **counted** in the records. Liveness
  beats aggression, and a silent dead end would be worse than a recorded
  retreat. The corpus soundness walk records zero fallbacks.

The de Bruijn pruner also vetoes at the **head** atom: with no binder in scope,
the `v` that would start `var` is refused outright. That prunes earlier, and it
is also what stops the masker from walking into a position whose only
continuations it would then have to veto.

### R3 — Instrumentation

Per token: mask computation time, tokens pruned, layer that pruned them.
Per cell: total mask overhead vs decode time — the number the
masking-overhead Watch item and the language re-evaluation both consume.

#### As built (B1)

`MaskStep` carries the step's `seconds` and `seconds_by_layer` and its
`pruned` counts by layer; `Masker.stats()` rolls those into the per-draw
record; `runner._mask_metrics` rolls the records into a `masking` block per
cell and per run, including `mask_share_of_draw_latency`.

Three numbers are reported separately because they are not the same number, and
conflating them would flatter the masker:

| field | means |
|---|---|
| `mask_pruned_by_layer` | tokens the mask removed, per layer. **Cache-stable** — a step answered from the mask cache pruned exactly what the step that filled it pruned. |
| `mask_calls_by_layer` / `mask_vetoes_by_layer` | byte evaluations actually performed. The caches suppress these, so they fall as a run warms. |
| `mask_seconds_by_layer` | the same uncached time — a pruner's *marginal* cost, not a re-charge per cache hit. |

`mask_seconds_per_token` is the warm number; `mask_seconds_per_token_uncached`
is the cold one. Prediction 5 should be scored against both, and the report
says which is which on the page.

### R4 — Testability without a model

Mirror Phase A's stub pattern: the mask API is exercised by tests that walk
known-good corpus surfaces token-by-token (every prefix of a valid definition
must keep that definition's next token unmasked — soundness of the mask), and
known-bad continuations must be masked where the layer claims to prune them.
Mask *soundness* (never excluding a valid continuation) is the critical
property: an unsound mask silently corrupts the experiment.

#### As built (B1)

`prototype/test_masker.py`, wired into `task prototype:test`.

**Soundness (`MaskSoundnessTest`).** All 26 corpus fixtures × four
tokenizations — one token per byte, fixed 3-byte chunks, longest-match, and the
pruner-subset walk — with the full stack active: the fixture's own next token is
asserted present in the mask at every step, and the walk must finish on a state
the grammar may end in. The tokenizations are the point: **the mask operates on
model tokens while the grammar and type state operate on bytes**, so a token
that ends mid-hash or straddles `) (` is the case that breaks a naive
implementation, and the byte-chunk schemes manufacture those boundaries
deliberately. Zero liveness fallbacks are asserted too.

**Unsoundness probes (`PrunerTest`).** Every corpus hash is walked digit by
digit through the reference trie; indices are probed at, below and above the
depth in force; the head-level `var`/`tyvar` veto, the `handle`-body
abstention, the free-`uint` non-opinion, and the `f64`/`bytes` literals that
must **not** be read as hashes each have a case. The empty row `()` has its own
test, because vetoing its `)` as a truncated hash was a real unsoundness this
suite caught — it killed every `(fn T () U)` in the corpus.

**End to end with no model (`ConditionFourTest`).** `StubBackend.generate_masked`
decodes against the real mask with scripted logits that score *decoys above the
target's own next token*, so the intended token can only win if the mask removed
them. The decoys are one per layer: bytes no Loom surface contains (syntax), an
out-of-scope `(var 9)` (de Bruijn), and hex extending no known digest
(reference). Switching a pruner off makes the run visibly diverge into exactly
the failure that pruner prevents — a `scope` rejection and an unresolvable
`0xdead…` respectively — which is what makes the passing run evidence about the
mask rather than about the script.

Real-tokenizer soundness is checked by `experiment/live_mask_sanity.py` rather
than by the suite, because a test that dlopens a shared library and mmaps a
gigabyte of weights fails for reasons unrelated to the code under test.

## Work

B1 (this dispatch):

- [x] Transport decision recorded with the R1 criteria; dependency wired.
  Candidate 3 (ctypes over the pinned `libllama.so`), rationale and rejected
  alternatives in R1 above; `experiment/llama_ffi.py`, backend `llama-cpp`,
  `experiment/phase_b.config.json`. No PyPI dependency is added.
- [x] Syntax-feasibility layer with prefix-soundness tests over all corpus
  fixtures. `experiment/gbnf.py`; `test_masker.MaskSoundnessTest` walks all 26
  fixtures under four tokenizations.
- [x] Type-state skeleton with at least two pruners implemented (reference
  and de Bruijn candidates) behind toggles, each timed. `experiment/masker.py`
  — `ReferenceHashPruner`, `DeBruijnPruner`, `Masker.enable(name, on)`,
  per-layer seconds and counts on every step and in `Masker.stats()`.
- [x] Condition-4 integration in the runner behind the existing config
  (condition name `gbnf+typemask`), stub-tested end-to-end.
  `runner.CONDITION_TYPEMASK`, `runner.make_masker`,
  `StubBackend.generate_masked`; `test_masker.ConditionFourTest`.
- [x] Instrumentation per R3 in the run records and report. `mask_*` fields on
  every condition-4 record, a `masking` block per cell and per run, and a
  "Masking overhead" report section that appears **only** when condition 4 ran
  — a Phase A run's records, summary and report are unchanged.

B2 (gated on Phase A's report):

- [ ] Pruner priority from the failure distribution; enable/extend
  accordingly.
- [ ] Run condition 4; complete the R5 comparison and the parent plan's
  prediction scoring.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py prototype/experiment/*.py
task todo:lint
git diff --check
```

plus the mask-soundness suite over every corpus fixture, and (B2) the live
condition-4 run recorded by the runner.

### Recorded — B1, 2026‑08‑13

**1. `task prototype:test`**

```
Ran 408 tests in 47.095s

OK (skipped=1)
```

PASS. 408 tests, up from 344: `test_masker.py` adds 64.

**2. `python3 -m py_compile prototype/*.py prototype/experiment/*.py`**

```
py_compile exit=0
```

PASS.

**3. `task todo:lint`**

```
TODO.md: clean
todo:lint exit=0
```

PASS.

**4. `git diff --check`**

```
diff --check exit=0
```

PASS.

**5. The mask-soundness suite over every corpus fixture (R4)** — called out
separately because it is the property the phase rests on.
`python3 -m unittest test_masker.MaskSoundnessTest test_masker.PrunerTest -v`:

```
test_every_fixture_byte_by_byte ... ok
test_every_fixture_in_atom_straddling_chunks ... ok
test_every_fixture_under_longest_match_tokenization ... ok
test_no_fixture_walk_needed_a_liveness_fallback ... ok
test_soundness_holds_for_every_pruner_subset ... ok
test_the_mask_shrinks_hard_and_still_offers_something ... ok
test_a_complete_unknown_hash_is_refused_at_its_terminator ... ok
test_a_float_or_byte_literal_is_never_treated_as_a_hash ... ok
test_a_free_uint_is_never_bounded ... ok
test_a_hex_prefix_that_extends_no_known_digest_is_pruned ... ok
test_a_partial_index_is_pruned_on_its_minimum_completion ... ok
test_a_row_variable_is_bounded_by_the_type_depth ... ok
test_an_empty_row_is_not_a_truncated_hash ... ok
test_an_index_at_or_past_the_depth_is_pruned ... ok
test_every_corpus_hash_survives_the_trie_digit_by_digit ... ok
test_no_binder_in_scope_prunes_the_var_head_itself ... ok
test_no_type_binder_in_scope_prunes_the_tyvar_head ... ok
test_the_pruner_abstains_where_the_depth_is_unknown ... ok
test_var_and_tyvar_are_the_only_heads_their_first_letter_can_reach ... ok

----------------------------------------------------------------------
Ran 19 tests in 33.086s

OK
```

PASS. All 26 corpus fixtures walk under four tokenizations (one token per byte,
3-byte chunks, longest-match, and the four pruner subsets) with the fixture's
own next token never masked, and zero liveness fallbacks.

**6. Live sanity — the in-process transport, on this box.**
`task experiment:mask-sanity -- --fixtures 0 --max-tokens 16`:

```
model            : /home/will/loom-tools/models/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf
vocabulary       : 151936 tokens, 333028 trie nodes, loaded in 8.3 s
tokenizer        : detokenize == concat(pieces)  [checked at load]
soundness        : 26/26 fixtures, 11341 mask steps, 0 violations, 33.2 s
masked draw      : 16 tokens in 11.3 s, stop=length
  text           : '(def (fn Bool () Bool) (lam Bool (if (var '
  stats          : {"mask_cache_hit_rate": 0.9375, "mask_fallbacks": 0,
                    "mask_pruned_by_layer": {"de-bruijn": 893, "ref-hash": 0,
                                             "syntax": 2425181},
                    "mask_seconds": 0.003065, "mask_seconds_per_token": 0.000191574,
                    "mask_seconds_per_token_uncached": 0.002137135,
                    "mask_steps": 16, "mask_vocab_size": 151936}
```

PASS, and it carries the three things the stub cannot:

- The **tokenizer-boundary** assumption holds on the real model — Qwen2.5-Coder
  detokenizes by concatenating token pieces, so a byte-level mask over pieces is
  sound here. `LlamaModel` refuses to construct if it ever stops holding, which
  is the escalation this dispatch was told to watch for. It did not fire.
- **R4 under the model's own tokenization**: all 26 fixtures, 11341 mask steps,
  zero violations, over a 151,936-token vocabulary.
- A first read on **prediction 5**. Mask overhead is ~0.19 ms per token warm and
  ~2.1 ms cold, against roughly 700 ms per token of CPU decode for the 1.5B
  model here: the mask is on the order of **0.03 % of decode**, so the honest
  early reading is that Python-side masking overhead is *not* material relative
  to local decode speed on this hardware. That is the opposite of prediction 5's
  first clause and the same as its second. It is one 16-token draw at
  temperature 0, so it is a signal to test in B2, not a score.

One ABI note recorded because it cost a false negative: the first
`_check_abi` pinned `llama_model_default_params().n_gpu_layers` to `0` and the
pinned build returns `-1` ("all layers, falling back where there is no
device"). The check is now a plausibility check over pointer and count fields,
which is what a misaligned struct actually corrupts.

**Not run:** the condition-4 matrix. That is B2's, and it is gated on Phase A's
failure distribution by rule (R2.1) — B1 deliberately claims no pruner-priority
conclusion from data it does not have.

## Completion criteria

- B1: every corpus fixture's canonical surface walks token-by-token with the
  full mask stack active and is never pruned (soundness); condition 4 runs
  end-to-end against the stub backend; per-pruner timing appears in records.
  **Met** — see Recorded verification steps 5 and 6, and
  `test_masker.ConditionFourTest`.
- B2: condition 4 live results reported against conditions 1–3 under the
  shared budget rule; R5 answered with numbers; predictions scored.

## What B1 hands B2

- **Pruner priority is the only decision left in the type layer.** Adding one
  is a class with a `veto(state, byte)` and a name in `PRUNER_NAMES`; the
  toggles, timing, instrumentation and soundness harness already exist, and
  `test_masker.MaskSoundnessTest` will walk a new pruner over every fixture
  without being told to.
- **The abstention list is the start of R6's "which checker operations must
  execute per token" answer.** So far it holds one entry: a `handle` operation
  body's binder count needs ability resolution, so de Bruijn checking cannot run
  inside one. Effect-row and goal-type pruners will add their own entries; the
  discipline is to record them, not to force them.
- **Two aggression levers deliberately left on the table**, both traded for
  soundness margin in B1: the reference trie is a union over all hash kinds
  rather than per-position, and the mask cache means per-layer *timings* are
  marginal-cost numbers rather than per-step ones.
- **Prediction 5 needs re-reading against real numbers** — see verification
  step 6. On this hardware the mask looks negligible against decode, which if it
  holds across the matrix flips the prediction's first clause.
