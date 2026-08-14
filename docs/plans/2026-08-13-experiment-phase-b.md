# Plan — Experiment Phase B: the incremental type-state masker

**Date:** 2026-08-13
**Status:** B1 implemented and verified. B2 implemented and verified locally.
The live condition-4 matrix has been attempted four times and is not yet
complete; every failure is diagnosed, fixed and guarded by a test, and launch 4
reached two full regimes with the memory fix confirmed working live. See the
[condition-4 run log](#condition-4-run-log). Awaiting an operator relaunch.
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

- [x] Pruner priority from the failure distribution; enable/extend
  accordingly. `goal-type` built and placed first, ahead of `de-bruijn` and
  `ref-hash`; completion pressure ruled out with reasons. See
  [the B2 decisions](#the-b2-decisions) below.
- [x] Machinery for the R5 comparison and the parent plan's prediction
  scoring, producible from the run report. `runner.r5_comparison`,
  `Config.baseline_summary`, the report's **R5** section and the masking
  section's **Prediction 5** block.
- [x] A remote condition-4 configuration, ready for an operator to launch.
  `experiment/phase_b.config.json`, plus the transport seam the GCP runner
  needed to serve it — see [the remote path](#the-remote-path-for-condition-4).
- [ ] **Run condition 4.** Four launches so far, none complete: an OOM, a
  capacity stockout, and a batch-size abort, each diagnosed and fixed — see
  [the run log](#condition-4-run-log). Launch 4 got two full regimes in with the
  memory fix confirmed working live. Awaiting an operator relaunch; not run from
  this dispatch by rule.

## The B2 decisions

Recorded 2026‑08‑14, from Phase A's failure distribution by layer.

Phase A's gate, over the 1,671 grammar-constrained draws of conditions 2–3:
**typecheck 590, parse 523, scope 268** (de Bruijn share 0.978),
**references 115**, accepted 175. `typecheck`'s error localization is
dominated by `definition.term` (×330), then `.body.condition` (×37), then
match arms and nested bodies.

### Priority: type-goal tracking first

`PRUNER_NAMES = ("goal-type", "de-bruijn", "ref-hash")` — the profile's own
order. It is not cosmetic: `Masker._veto_layer` credits the **first** layer that
refuses a byte, so profile order makes `mask_pruned_by_layer` read as "what the
dominant checker layer removed", which is the number R5 wants. It changes
attribution between layers, never the mask itself.

**What made a goal pruner possible at all** is one structural fact:
`root ::= "(def " type " " term ")"`, so a definition's declared type is
**complete before its term begins**. At the moment the term starts, the state
has that type in hand; it parses it once, peels the prenex `forall`s exactly as
`MatchChecker.check_definition` does, and carries the result as the term's goal.
That is precisely the position the ×330 localization points at.

**And what makes a byte-level veto a proof** is that `transcode.parse_source`
refuses any surface that is not `def_to_surface(ir)`. An accepted definition's
bytes therefore *are* the canonical rendering of its IR, so wherever the checker
forces a sub-type to equal a type already known, the bytes at that position are
determined and every other byte is refusable. This is the single hardest prune
in the stack — a whole type subtree collapses to one string — and it exists only
because the surface is canonical.

Five vetoes, each with its rule in `typecheck.py`:

| veto | proof |
|---|---|
| a `lam` annotation under a `fn` goal, and a `fix` annotation under any goal, are **forced** to canonical bytes | `check` tag 3 fails on `term[1] != expected[1]` and `_check_fix` on `annotation != expected`, both immediately, with no subsumption or instantiation path behind them |
| head feasibility: `lam`/`fix` need a `fn` goal, `lit` a base goal, `con` a nominal one | `check` tag 6 fails outright on a non-nominal goal; the others synthesize a type whose erasure cannot meet the goal's |
| a literal's kind word is fixed by a base goal | `synth` tag 2 returns `[0, k]`, and literal-kind codes are base-type codes |
| a `con`'s data hash is fixed by a nominal goal | `check` tag 6 fails unless `term[1] == expected[1]` |
| a `ref`'s digest is filtered to those whose resolved type meets the goal | a `ref` synthesizes its resolved type; equality, first-order instantiation of a `forall`, and subsumption all fail when a non-quantified type erases differently |

The last one is B1's "kind-specialising the reference trie is a B2 lever",
taken — specialised by *type* rather than by kind, which is strictly narrower.

Every comparison is on §3.2.1 **refinement erasure**, which is subsumption's own
precondition. That keeps all five proofs independent of whether a caller
supplies `MatchChecker`'s obligation collector. `evaluate.run_funnel` does not
supply one, so subsumption never fires in this experiment — but nothing above
leans on that, and `test_masker` pins the coupling so a future collector cannot
silently widen what the checker accepts under a mask built for the narrower
rule.

One consequence worth naming: the goal layer can prove `(ref …)` impossible at a
goal no digest could meet, and refuses the **head** rather than walking into a
hash position where it would have to refuse every digit until the mask emptied
and fell back for liveness. On *this* corpus that veto is inert — one corpus
definition is polymorphic, and §3.1.3 instantiates a `forall` against any goal,
so exactly one digest survives every goal. The test says so rather than hiding
it, and drives the mechanism against a resolver holding only an ill-fitting
type, which is what a larger monomorphic corpus produces.

### Completion pressure: **out of B2 scope**, and why

Parse deaths are second (523) and are essentially all budget truncation at 512
tokens. A masker cannot extend a budget, so the only pruner shaped like an
answer is one that vetoes branches that cannot close within the remaining
tokens. It is not built, for four reasons, in order of weight:

1. **The only sound bound is too weak to steer.** Minimum *bytes* to close is
   computable from the grammar; minimum *tokens* is not, because tokenization is
   the model's. The sound lower bound is `min_bytes / max_piece_len`, and
   `max_piece_len` is ~24 on this vocabulary. With 400 tokens left that permits
   ~9,600 bytes — so the veto cannot fire at the point where steering would
   change the program. The version that *would* steer needs an expected
   bytes-per-token estimate, and an estimate is a heuristic, which R4's
   proof-or-abstain rule forbids outright.
2. **It would break the memoization the design's affordability rests on.** The
   mask is a memoized transition over `(grammar state, type state)`. Remaining
   budget is a per-step quantity, so admitting it into the veto puts it in the
   cache key and every step becomes a cache miss. B1's whole tractability
   argument is that per-token cost tracks what survives rather than the
   vocabulary; this would trade the dominant layer's prune for a cache.
3. **Closing early converts a failure, it does not create an acceptance.** A
   draw steered to close inside budget yields a complete definition that then
   meets the checkers — a truncation relabelled as a typecheck failure.
   Accepted-per-1k-tokens, the R5 measure, does not move.
4. It does not touch the dominant layer.

Recorded as an abstention rather than an omission. What would change the answer:
a per-position bytes-per-token bound that is a *bound* and not an estimate, or a
budget large enough that truncation stops being the second-largest killer — the
latter being the honest reading of Phase A's parse row anyway.

### Abstentions added (R6: which checker operations cannot run per token)

B1 left one entry. B2 adds these, all recorded in `part_goal` and pinned by
`test_masker.GoalTypePrunerTest.test_the_synthesis_positions_are_abstentions_not_omissions`:

| position | why the goal is unknown |
|---|---|
| `app`'s function and argument | `synth` tag 4 synthesizes the function, and the argument's goal is that function's domain — not available from a byte prefix unless the function is already resolved |
| `let`'s bound term and body | `synth` tag 5 checks the bound term against the `let`'s *written* type and then **synthesizes** the body; neither is a goal the declared type supplies |
| a `match` scrutinee | synthesized, and it is what determines the arms' constructor set |
| `con` and `perform` field arguments | field types come from `constructor_fields` / `operation_signature`, i.e. a declaration lookup keyed on a tag that follows in the byte stream |
| `hole`'s annotation | `synth` tag 11 returns the annotation, which may itself be a `forall` and reach the goal by instantiation, so it is not forced |
| the type of a `(var N)` | needs a binder-*type* environment; the state carries binder depths, not types |
| minimum tokens to close a form | see the completion-pressure decision above |
| an operation clause's binder count (B1) | still open: `parameter_count + 1` needs ability resolution. Note the two abstentions are **independent** — a handler clause's *goal* is known (`_check_handler` checks every clause body against the expected type) even though its depth is not, and B2 propagates the goal there |

### `mask_fallbacks` means something new

B1's liveness fallback fired when the type layer would empty a non-empty syntax
mask, and read as "the type layer over-pruned". With a goal layer it can also
mean **the prefix is provably dead** — every continuation fails the checker, and
the mask has no way to say so. Both are still counted the same way and are still
honest instrumentation; the interpretation of a non-zero count in a live run is
now "the model painted itself into a corner", not necessarily "a pruner is too
aggressive". The corpus walk records zero either way.

## The remote path for condition 4

The condition-4 config alone could not have run. The GCP runner's
[startup script](../../infrastructure/gcp/modules/experiment-runner/startup-script.sh.tftpl)
hardcoded `backend = "llama-server"` and dropped `model_path`, and
`llama-server` exposes no `mask_vocabulary`, so
`make_masker` would have refused by name after the instance was already paid
for. The startup script now reads the transport out of the operator's own
config: `gbnf+typemask` present means the in-process `llama-cpp` backend with
`model_path` and `llama_lib` filled in and no `llama-server` started (a second
full offload would contend for the same VRAM); anything else is Phase A's served
path, unchanged. A config **mixing** condition 4 with a Phase A condition is
refused before anything is built, because `llama-cpp` implements
`generate_masked` only and would otherwise die partway through a GPU-hour
matrix. `libllama.so` is now named as a build target and required of a build
cache hit, so a cache seeded before condition 4 existed fails the hit test rather
than failing the run.

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

### Recorded — B2, 2026‑08‑14

**1. `task prototype:test`**

```
Ran 541 tests in 19.569s

OK (skipped=1)
```

PASS. 541 tests. `test_masker.py` goes from 64 to 92: `GoalTypePrunerTest`'s 23
probes, four R5/config-readiness cases in `ConditionFourTest`, and one added to
`MaskerApiTest`.

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

**5. The mask-soundness suite over every corpus fixture (R4)** — the property
the phase rests on, now with a third pruner in the stack.
`python3 -m unittest test_masker.MaskSoundnessTest test_masker.GoalTypePrunerTest`:

```
Ran 29 tests in 14.888s

OK
```

PASS. All 26 corpus fixtures walk under four tokenizations with `goal-type`
active, the fixture's own next token never masked, and **zero liveness
fallbacks** — which is the load-bearing number, because the goal layer is by far
the most aggressive of the three and a fallback is how over-aggression would
show up.

Two unsoundnesses the suite caught during development, both recorded because
they are the shape of mistake this layer invites:

- **A terminator is not an extension.** The first head veto tested
  `atom + byte` against the feasible-head prefixes, so the space ending `lam`
  was read as the head `lam ` and refused — killing every `lam` in the corpus.
  Terminators now judge the finished atom instead, and
  `test_a_finished_head_is_judged_at_its_terminator_not_extended` pins it.
- **`arm` and `op` are not in `FORMS`,** so `_apply_part` indexes their spec by
  `part` rather than `part - 1`. Propagating the goal to "part 3" of an arm
  silently propagated it nowhere.
  `test_match_arms_and_handler_clauses_inherit_the_goal` pins the real indices.

**6. Live sanity — the real tokenizer, on this box.**
`task experiment:mask-sanity -- --fixtures 0 --max-tokens 64`:

```
model            : /home/will/loom-tools/models/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf
vocabulary       : 151936 tokens, 333028 trie nodes, loaded in 2.5 s
tokenizer        : detokenize == concat(pieces)  [checked at load]
soundness        : 26/26 fixtures, 11341 mask steps, 0 violations, 15.6 s
masked draw      : 29 tokens in 2.2 s, stop=stop
  text           : '(def (fn Bool () Bool) (lam Bool (if (var 0) (lit bool false) (lit bool true))))\n'
  stats          : {"mask_cache_hit_rate": 0.931, "mask_fallbacks": 0,
                    "mask_pruned_by_layer": {"de-bruijn": 902, "goal-type": 19529,
                                             "ref-hash": 0, "syntax": 4376944},
                    "mask_seconds": 0.003458, "mask_seconds_per_token": 0.000119232,
                    "mask_seconds_per_token_uncached": 0.001220578,
                    "mask_steps": 29, "mask_vocab_size": 151936}
```

PASS, and it carries three things worth stating carefully:

- **R4 holds under the model's own tokenization** with the goal layer in: 26/26
  fixtures, 11,341 mask steps, zero violations, zero fallbacks, over a
  151,936-token vocabulary.
- **The goal layer is the dominant type-layer pruner**, by more than an order of
  magnitude: 19,529 tokens removed against de Bruijn's 902 and the reference
  trie's 0. That is the profile order paying off in the direction Phase A's gate
  pointed.
- **The draw completed and stopped on its own** (`stop=stop`, EOS at a state the
  grammar may end in) with a definition that is byte-identical to
  `corpus/bool_not.loom.sexpr`. Under B1's two pruners the same model at
  temperature 0 was still mid-`(if (var ` after 16 tokens.

  **This is one draw at temperature 0 on the 1.5B model, and it is a
  memorization-shaped success** — identity match against a corpus fixture, which
  is exactly the mechanism Phase A's prediction 6 found behind all 13 of its
  semantic successes. It is a signal that the matrix is worth running, not a
  result. Nothing here is evidence about held-out composition, where Phase A
  measured zero.

**7. The remote path renders, parses and lints.**

```
$ python3 scripts/render-gcp-startup-script.py <out>
rendered ok, no unknown interpolation

$ bash -n <out>
bash -n OK

$ shellcheck <out>
SC2015 (info) at the build-cache seeding line
```

PASS. The one `shellcheck` info is **pre-existing and unchanged** — rendering
`HEAD`'s template reproduces the identical finding at the same line, so this
change introduces no new lint. (`shellcheck-exit=0` recorded in the GPU
build-cache plan predates the `&& … || …` seeding line.)

```
$ bash -n scripts/run-remote-experiment-gcp.sh && shellcheck scripts/run-remote-experiment-gcp.sh
driver bash -n OK
driver-shellcheck-exit=0
```

PASS.

**Not run: the condition-4 matrix itself.** No cloud instance was launched from
this dispatch, by rule. The operator's invocation is recorded below.

### Condition-4 run log

| launch | outcome | cause |
|---|---|---|
| — | see the operator's log | not recorded here; this plan picks the log up at the first matrix that produced records |
| 2 | OOM-killed at 14.3 GB after 259 draws | literal payloads retained in the type state; unbounded transition memo |
| 3 | never started | `us-east1-b` capacity stockout — infrastructure, nothing to fix in the masker |
| 4 | `GGML_ASSERT` abort after 530 draws | prefill fed as one `llama_decode` call, longer than `n_batch` |

Launch numbering is the operator's. Launch 1 is deliberately left blank rather
than guessed at: it produced nothing this plan can cite.

#### Launch 2, 2026‑08‑14 — OOM-killed at 14.3 GB. Cause found and fixed.

The run reached 259 records in ~20 min, wrote its last record at 14:58:11,
then spent **39 minutes inside a single draw** without completing it, and was
OOM-killed at 15:37:24 with anon-rss 14.3 GB and total-vm 70 GB on a 16 GB
box. systemd failed the whole `google-startup-scripts` unit, which killed the
`finish` trap — so no status marker, no upload and no self-delete. Partial
records were salvaged by hand to `prototype/runs/phase-b-partial-oom/`.

**What the salvaged records said.** Only the `none` regime ran (66 cell-runs,
33,420 mask steps). Mask cost was **not** rising monotonically with cumulative
steps — bucketed by cumulative steps the mean s/token went 0.0023, 0.031,
0.0086, 0.0031, 0.019, **0.00099**, 0.0036 — so it was not a global leak
degrading everything. It was per-draw, and it concentrated:

| draw | s/token | cache hit rate | what the model wrote |
|---|---|---|---|
| `clock/nowPair` s1 d3 | 0.6611 | 0.067 | `(def Text (match (app (ref 0x…) (lit text "a")) …))` |
| `clock/now` s1 d4 | 0.5655 | 0.092 | `(def I64 (app (ref 0x…) (lit text "get_current_time_ms")))` |
| `clock/nowPair` s2 d1 | 0.3777 | 0.168 | `(def Text (match (lit text "hh:mm:ss") …))` |
| `clock/nowPair` s2 d0 | 0.3532 | 0.116 | `… (lit text "42")))` |
| `clock/nowPair` s2 d4 | 0.3408 | 0.189 | `… (lit text "PM")))` |

Every one of the five slowest draws contains a **text literal**. In the `none`
regime the model has no examples, so asked for a clock definition it reaches for
strings.

**Root cause, measured.** A string payload is an atom **no consumer reads** —
no pruner looks at it, and `_next_part`'s three reads are the head keyword, the
literal kind word and a match arm's binder count. But `TypeState` accumulated it
anyway, so *every byte of a literal was a distinct type state*. The memoized
byte transition therefore shared nothing, the mask cache never hit, and each
token inside a literal cost a full walk of the 333k-node vocabulary trie **and**
left ~82,000 permanent entries in a memo that had **no bound at all**.

One step inside a text literal, on the real 151,936-token vocabulary:

| | allowed tokens | new transitions | seconds | RSS |
|---|---|---|---|---|
| before | 147,201 | 326,749 | 3.28 | +131 MB |
| after | 147,201 | **422** | **0.62** | **+0.2 MB** |

Sustained inside one literal, the memo grew ~82,000 entries per character:
**+2.38 GB after 64 characters**, against flat afterwards. 14.3 GB corresponds
to ~440 characters of literal ≈ 110–220 tokens of a 512-token draw, so **the
same defect accounts for the 39-minute stall as well as the kill** — there is no
second bug to find, and no unexplained residue.

**This is not a B2 regression.** The transition count at a text-literal position
is identical — 326,749 — with the syntax layer alone, with B1's pruner set, and
with B2's; per-entry cost is in fact *lower* with B2's pruners (313 B against
408 B), because the goal layer prunes subtrees the others retain. The defect is
in the B1 substrate. It went unseen because B1 never ran a live matrix and
**the corpus contains no text literal**, so `MaskSoundnessTest` never walked
that path.

**The fix**, in two parts, because the second must hold where the first has not
yet been found:

- **`ATOM_READ`** names the atom kinds a consumer reads. Everywhere else the
  scanner keeps one byte — enough to answer "is this atom empty?", the only
  other question asked of it — and drops the rest. A whole literal collapses to
  two states. `f64`, `bytes` and `i64` payloads have the same shape and are
  covered by the same rule.
- **`Masker.TRANSITION_CACHE_SIZE`** bounds the memo at 500,000 entries
  (~200 MB at the measured 313–428 B/entry). Eviction is a wholesale clear, not
  an LRU: `_transition` runs once per live trie edge per step, and per-hit
  recency bookkeeping in that loop would cost more than the cache saves.
  `mask_transition_entries` and `mask_transition_clears` are now reported, so a
  run that thrashes the bound says so instead of quietly slowing down.

Steady-state ceiling is **~250 MB**, with the already-capped mask cache.

**Regression guard:** `test_masker.MaskMemoryTest` — sustained steps inside a
literal with the memo asserted flat, the bound asserted to hold and to fire,
eviction asserted not to change the mask, `ATOM_READ` asserted to cover every
consumer, and a text-literal definition walked byte by byte through the mask
after `run_funnel` is checked to accept it. That last one is the coverage the
corpus cannot supply.

**Verified.** 548 tests pass (541 before, +7). All 26 fixtures still walk under
four tokenizations with zero violations and zero liveness fallbacks. Replaying
the five worst draws from the salvaged records costs 30–55× less mask time with
66 MB total growth — though that comparison spans two machines and the salvaged
figures were taken under memory pressure, so the controlled before/after in the
table above is the number to trust.

One thing the incident did **not** turn up as a defect: the run's 81 liveness
fallbacks across 15 draws. That is the behaviour recorded above under
[`mask_fallbacks` means something new](#mask_fallbacks-means-something-new) — with a
goal layer a fallback can mean the prefix is provably dead, and a `none`-regime
draw that opens `(def Text (match (app (ref …` is exactly that.

#### Two further landmines, found while fixing the first

Attempt 1 died 20 minutes in, in the `none` regime. Both of these sat past that
point and would have cost a second run.

1. **`n_ctx` was far too small.** Measured with the real tokenizer, the longest
   prompt per regime is `none` 279, `few_shot` 1,843, **`full_corpus` 11,906**,
   **`held_out` 11,959** tokens. `phase_b.config.json` shipped `n_ctx: 4096`.
   `LlamaCppBackend` does refuse a prompt that will not fit — with a message
   naming the config key, which is the right behaviour — but the run would have
   stopped at the third regime. Raised to **16384**, matching what Phase A
   served with, and `test_the_shipped_config_has_context_for_the_longest_prompt`
   now computes the requirement from the prompts themselves so the config cannot
   drift under it again.
2. **The masked transport was pinned to CPU in committed code.**
   `llama_ffi.LlamaModel` carried `params.n_gpu_layers = 0` with the comment
   "this box is CPU-only, by the plan" — true when Phase B was developed on a
   laptop, catastrophic on the run host. A relaunch from committed code would
   have run the whole condition-4 matrix on four vCPUs with a 24 GB L4 idle.
   Now a config knob, `n_gpu_layers`, defaulting to **-1** — llama.cpp's own
   "all layers, falling back where there is no device", which is right on the
   laptop and on the L4 alike.

   **Provenance caveat:** attempt 1 reportedly ran at 99–100 % SM, which
   committed code cannot do, so the box was carrying a local patch. Attempt 2
   should run from committed code so the recorded results match a revision that
   exists.

Two smaller things went with them: `_recreate`, which runs once per draw, built
fresh context params and so silently dropped `n_threads` and re-tied the batch
to `n_ctx` after the first draw — it now reuses the params built at load; and
batch sizes no longer track `n_ctx` at all (2048/512, llama.cpp's defaults),
since sizing a compute buffer for a 16k micro-batch that never occurs is pure
allocation.

**Still open after this fix:** a text literal genuinely allows 147,201 of the
151,936 tokens, so the *first* step inside each distinct literal context costs a
full trie walk (0.62 s on this laptop's CPU; less on the run host). It is cached
from the second token on, and cached across draws, but a matrix with many
distinct literal contexts pays it repeatedly. Worth watching in attempt 2's
`mask_seconds_per_token_uncached`, and the reason that field is reported
separately.

#### Launch 3 — `us-east1-b` capacity stockout

The instance never started. Nothing in the masker; recorded so the run log
accounts for every launch rather than skipping the ones with no artefact. The
relaunch moved to Europe, which is what makes launch 4 "the Europe relaunch".

#### Launch 4, 2026‑08‑14 — `GGML_ASSERT` abort on the first `full_corpus` prompt

**The OOM fix is confirmed working live.** The run completed two whole regimes —
`none` 330 draws, `few_shot` 200, 530 records — with runner RSS steady at
~1.0 GB and mask cost far below launch 2's:

| | launch 2 (partial) | launch 4 |
|---|---|---|
| mask s/token, mean | 0.01196 | **0.00249** |
| mask s/token, worst draw | 0.66111 | **0.07632** |
| transition entries at the end | unbounded, ~14 GB RSS | 86,237 under a 500,000 cap |

Then, on the **first `full_corpus` prompt**:

```
/opt/loom/llama.cpp/src/llama-context.cpp:1711:
GGML_ASSERT(n_tokens_all <= cparams.n_batch) failed
```

SIGABRT, exit 134, through `llama_decode` via ctypes. The startup script's
`finish` trap worked this time — FAILED marker, logs uploaded, instance
self-deleted.

**This one is mine, from the previous fix.** Decoupling `n_batch` from `n_ctx`
(to avoid a multi-gigabyte compute buffer at `n_ctx` 16384) left `decode`
feeding the whole prompt as a single `llama_decode` call. `few_shot`'s ~1.7k
prompts fit inside a 2048-token batch; `full_corpus`'s ~11.9k do not. Two
regimes passed first, which is exactly why it surfaced late.

It is a `GGML_ASSERT`, not a return code — the process aborts and there is
nothing to catch — so no amount of error handling on this side would have
softened it.

**The fix: chunked prefill.** `decode` now feeds the prompt in `n_batch`-sized
slices. Raising `n_batch` back to `n_ctx` was rejected on sight: it undoes the
buffer sizing that the previous fix existed for, and it would only move the
ceiling rather than remove it.

Both things that could make chunking *silently* wrong were read off the pinned
build rather than assumed — the coordinator flagged this seam as escalate-worthy
and it is the one place in Phase B where a wrong guess corrupts data instead of
crashing:

- **Positions.** `llama_batch_get_one` leaves `pos` null
  (`llama-batch.cpp:931`), and `llama_batch_allocr::init` then assigns positions
  from `memory->seq_pos_max(s) + 1` (`llama-batch.cpp:90-117`) — continuing from
  what is already in the KV cache. Sequential calls chain, which is the property
  the prompt-then-one-token-at-a-time loop already depended on.
- **Logits.** A null `logits` with `output_all` false marks only the final token
  of each batch (`llama-batch.cpp:120-130`), so the last chunk's last token is
  what `llama_get_logits_ith(ctx, -1)` reads. Earlier chunks compute one unused
  row each — the whole cost of chunking.

And the chunk size is now the batch llama.cpp *actually chose*, read back
through `llama_n_batch`, not the one requested: `cparams.n_batch =
min(n_ctx, params.n_batch)` under causal attention
(`llama-context.cpp:245`), and the assert compares against the clamped value.
Computing it here instead of asking would be the same class of guess that
aborted the run.

**One more thing launch 4's records exposed**, fixed in the same pass: the mask
cache reached its 32,768-entry cap during the first two regimes and its policy
was to *stop inserting*. `full_corpus` — the regime carrying R5's bar — would
therefore have run against a cache frozen on what `none` and `few_shot` had
taught it. It now evicts by wholesale clear at the cap, like the transition
memo, and reports `mask_cache_clears`.

**Regression guard:** `test_masker.ChunkedPrefillTest` — gated on the local
GGUF the way the repo gates its other optional-dependency checks. It loads the
1.5B with `n_batch=64` and a prompt several batches long and asserts decode
completes; asserts the effective batch is read back and clamped; asserts chunked
prefill leaves the *same logits* at the final prompt position as a single-batch
prefill (a position bug moves those by whole logits, far outside the last-bit
differences reordered reductions produce) and picks the same next token; asserts
positions survive the per-draw `reset()`; and runs a full masked draw end to end
under a tiny batch. The two abort-prone cases run in a **subprocess**, because a
`GGML_ASSERT` would otherwise kill the test runner and report nothing — a
regression now comes back as a clean failure carrying exit 134.

**Verified.** 555 tests pass. The pre-fix path was reproduced locally to prove
the guard has teeth — same assert, same `llama-context.cpp:1711`, same exit 134,
same ctypes stack — and the fixed `decode` passes on the identical prompt and
batch size. Live mask-sanity is byte-for-byte unchanged: 26/26 fixtures, 0
violations, the same definition reproduced, the same per-layer prune counts.

### What the operator runs

```sh
scripts/run-remote-experiment-gcp.sh \
  --model-identity "Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M" \
  --gguf qwen2.5-coder-7b-instruct-q4_k_m.gguf \
  --config prototype/experiment/phase_b.config.json \
  --remote-output-dir runs/phase-b \
  --dest prototype/runs/phase-b
```

The config is Phase A's matrix with condition 4 substituted: seeds {1, 2, 3},
temperature 0.8, 512 tokens per task and per draw, all four regimes,
leave-one-out on, the three pruners in profile order. `backend`, `model_path`,
`llama_lib`, `model_identity` and `hardware` are left empty so the entry point
refuses a local run; the instance fills them. `baseline_summary` points at the
committed Phase A summary, so the returned `report.md` carries the R5 table and
the prediction-4 verdict without anyone assembling it by hand — condition 4's
bar is `gbnf|full_corpus` at **1.452** accepted per 1k tokens.

## Completion criteria

- B1: every corpus fixture's canonical surface walks token-by-token with the
  full mask stack active and is never pruned (soundness); condition 4 runs
  end-to-end against the stub backend; per-pruner timing appears in records.
  **Met** — see Recorded verification steps 5 and 6, and
  `test_masker.ConditionFourTest`.
- B2: condition 4 live results reported against conditions 1–3 under the
  shared budget rule; R5 answered with numbers; predictions scored.
  **Partly met.** The pruner priority is decided and built, the abstention list
  is extended, and every number R5 and predictions 4–5 need is produced by the
  run report from a recorded baseline. What is outstanding is the run itself,
  which is an operator step by rule.

## What B2 hands the operator, and the next dispatch

- **The one thing left is a launch.** Everything downstream of it is
  mechanical: `report.md` carries the R5 table, the prediction-4 verdict and the
  prediction-5 share on the page.
- **Prediction 5 now has two readings pointing the same way.** B1 measured the
  mask at ~0.03 % of decode; B2 measures ~0.16 % (0.12 ms/token warm,
  1.22 ms/token cold, against ~76 ms/token of CPU decode for the 1.5B). Both are
  the opposite of the prediction's first clause. The L4 decodes far faster than
  this box, so the matrix is where the clause is actually settled — the mask
  cost is transport-independent but the decode it is divided by is not.
- **Two aggression levers remain**, both deliberate: a `(var N)` carries no
  type because the state tracks binder depths and not binder types, and
  `con`/`perform` argument goals need a declaration lookup keyed on a tag that
  has not been written yet. Each is a real pruner; each needs the state to carry
  more than it does.
- **If the live run shows non-zero `mask_fallbacks`**, read it with the note
  above: with a goal layer, a fallback can mean the prefix is provably dead
  rather than that a pruner over-pruned. The two are worth separating before
  drawing a conclusion from the count.

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
