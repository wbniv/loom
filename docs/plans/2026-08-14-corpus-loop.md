# Plan — Closing the corpus loop: accepted generations enter the store

**Date:** 2026-08-14
**Status:** Complete — built, verified, and the A/B **run and positive**
(2026‑08‑14, run ids `20260814T213313Z` curated / `20260814T221904Z`
generated, both on europe‑west4‑c L4, ~$1.30 total). See
[the A/B verdict](#the-ab-verdict) below. One escalation was raised and
resolved during implementation:
[the arms must differ in what the model sees](#escalation-and-resolution-the-arms-must-differ-in-what-the-model-sees).
**Parent:** SPEC §13's endgame ("accepted generations join the corpus, the
loop closes on itself"), built on
[store v0](2026-08-14-store-v0.md) and the
[masked-generation experiment](2026-08-13-masked-generation-experiment.md)'s
records. Conclusion 5 is the guardrail: the store must not let memorized or
merely-valid artifacts masquerade as synthesis — provenance carries the
difference.

## Objective

Wire the path from a run's accepted draws into the store, honestly labeled,
and make prompt assembly able to draw on them — so the next matrix can
measure, rather than assume, whether model-generated corpus moves acceptance
on tasks the model hasn't seen. The loop closes mechanically here; whether it
*helps* is the follow-up experiment this plan only prepares.

## Rules

### R1 — Harvest admits what the funnel accepted, and nothing looser

A `harvest` entry point (Python, beside the harness) reads a run's
`records.jsonl`, selects records with `funnel_outcome == accepted`, and
admits each definition source through the store's existing oracle `admit`
path. The funnel's verdict is not trusted stale: admission re-validates
through the full chain as always. Dedup is free (content addressing);
`exists` outcomes are counted, not errors. Records that were accepted but
fail re-admission (e.g. contract drift since the run) are reported as their
own category — that count is a *finding*, never silently dropped.

### R2 — Provenance is the load-bearing field

Generated objects carry `origin: "generated"` plus model identity, run id,
condition, regime, seed, and draw — enough to reconstruct exactly which
process produced the bytes. Curated corpus objects keep their existing
provenance. Nothing about a generated object's *tier* is inflated: it enters
at the tier its validation earns (checked at best), and `semantic_success`
from the run is recorded as observation metadata, never as evidence.

### R3 — Prompt assembly filters by origin, and curated-only is the default

`StoreResolver` (or its export) gains an origin filter. The default remains
curated-only and **byte-identical to today's prompts** — proven by the
existing equivalence tests continuing to pass untouched. Including generated
objects is an explicit opt-in flag on the config, because the A/B this
enables is precisely curated vs curated+generated.

### R4 — The measurement is prepared, not run

A run config for the follow-up experiment: full-corpus regime in two arms
(curated; curated+generated), held-out tasks included, same budget rule.
Built and locally verified against the stub backend; the live GPU run is an
operator launch, out of scope here (no cloud from this dispatch).

### R5 — Out of scope

Curation/ranking policies for generated objects; automatic multi-round
self-improvement loops; retraining; any namespace or binding work; evidence
objects beyond the provenance metadata above.

## Visible surface

`harvest` prints one-line JSON counts (`admitted`, `exists`,
`refused_on_readmission`) — line protocol matching the store CLI; no mockup
bundle for a machine-consumed line, recorded per the house rule.

As built, the line also carries `records` / `accepted` / `distinct_identities`
(so the counts can be checked against the run without opening it), the `run`
block, and `refusals` — one entry per refused *identity*, carrying the refusing
layer, its own error class, and how many records it covers. Refusals are a
finding, so they ride on the same line rather than in a log nobody reads. The
literal shape is in the [recorded verification](#recorded-verification).

## Cost

$0 — local only. (The follow-up GPU run, when the operator launches it,
prices like every prior matrix: ~$1–3 of trial credit.)

## Work

- [x] `harvest` entry point + tests (R1, R2) — real fixture: the run records
  under `prototype/runs/phase-b/` (109 accepted draws, **38** distinct
  identities, not the ~31 estimated here).
- [x] Origin filter through export/StoreResolver + curated-only default
  equivalence preserved (R3).
- [x] Two-arm follow-up config, stub-verified (R4), with `n_ctx` sized from the
  arms' own measured prompts.
- [x] Run log + verification recorded here.

## Run log

### What was built

| path | what it owns |
|---|---|
| [`prototype/harvest.py`](../../prototype/harvest.py) | selecting a run's accepted draws, re-admitting them, and the counts |
| [`prototype/test_harvest.py`](../../prototype/test_harvest.py) | the synthetic run fixture, and R1/R2/R3/R4 as assertions |
| [`prototype/store_admit.py`](../../prototype/store_admit.py) | the origin vocabulary and `provenance_extra` (the rest is unchanged) |
| [`prototype/experiment/store_resolver.py`](../../prototype/experiment/store_resolver.py) | the origin filter, and the name-rebind refusal |
| [`prototype/experiment/runner.py`](../../prototype/experiment/runner.py) | `store_export` / `include_generated`, and `make_resolver` |
| [`prototype/experiment/prompts.py`](../../prototype/experiment/prompts.py) | resolver-driven example selection, identity-based leave-one-out, and the measured `CHARS_PER_TOKEN` |
| [`prototype/experiment/followup_curated.config.json`](../../prototype/experiment/followup_curated.config.json) | arm A |
| [`prototype/experiment/followup_generated.config.json`](../../prototype/experiment/followup_generated.config.json) | arm B — identical but for one flag |
| [`store/src/index.rs`](../../store/src/index.rs) | the `origin` index column |
| [`store/src/main.rs`](../../store/src/main.rs) | `origin` in `list` output |

### The harvest/readmission seam: Python admits, Rust lands

`harvest.py` does **not** call `loom-store admit`. It re-validates in Python
through `store_admit.definition_sidecar` — the same entry point corpus seeding
uses, which means the same layer order, the same §3.3 subsumption collector, and
the same refusal classes — and then hands each finished pair to `loom-store
put`, the store's own entry point for "the oracle has already spoken".

The alternative considered and rejected was teaching `loom-store admit` to carry
provenance: it would have meant a dozen new CLI arguments (model identity, run
id, condition, regime, seed, draw, …) threaded through `oracle.rs` into
`store_admit`'s `emit` subcommand, so that Rust could pass through a payload it
has no opinion about. That is a bigger store-crate change than the escalation
budget allowed, and it would have put the shape of the experiment's records into
the store's argument surface, where the next run's schema change would break it.
`put` already accepts an arbitrary oracle-produced sidecar; the harvest is an
oracle, so it uses the oracle's door. **No new Rust argument surface exists.**

The one Rust change is the `origin` column on the index row, surfaced in `list`.
It is what makes verification step 3 a query rather than a file read: the
guardrail "generated never passes for curated" is worth having only if somebody
can see it from the read API. `#[serde(default)]` keeps a pre-existing index
parseable; `fsck` reports `index_diverged` on such a store and `reindex` fixes
it, which is the repair that already existed for exactly this case.

### The naming scheme: `generated/<task id>/<12 hex>`

Example: `generated/corpus/list/append/03d8abd83aae`. Three properties, in the
order they matter.

**It cannot collide with a curated name.** Everything the corpus names lives
under `corpus/`; everything harvested lives under `generated/`. A generated
object landing on a curated name is the one genuinely dangerous failure in this
increment — prompt assembly looks a definition up *by name* and shows it under
that name's spec, so a rebind would serve a model's output as a curated example,
which is precisely conclusion 5's "memorized or merely-valid artifact
masquerading as synthesis". The prefix makes it impossible by construction, and
`StoreResolver._bind_name` refuses a rebind out loud in case it ever isn't.

**It says what the model was asked for.** The task id is copied from the record
verbatim, so a listing greps straight back to the draw.

**It is unique.** One task yields many distinct accepted definitions —
`corpus/clock/now` alone produced 16 of the 34 — so the task id is not a name on
its own.
Twelve hex digits (48 bits, git's own abbreviation length for a large
repository) make it one.

The scheme is therefore **not** a pure function of the object, and that was a
real choice: the phase-b records contain one identity produced under two
different tasks, so first-accepted-record-wins decides the name. That is
deterministic in the records file, the full draw is in `provenance.run` either
way, and the alternative — a content-only `generated/<hash>` — would have thrown
away the one field a human reading `list --kind definition` actually wants.

### The provenance schema

`provenance` gains two blocks for `origin: generated`, and nothing else in the
sidecar schema moves (version stays 1; `store_admit`'s docstring is the record):

```json
"provenance": {
  "origin": "generated",
  "source": "runs/phase-b/records.jsonl",
  "admitter": "prototype.store_admit/1",
  "run": {
    "run_id": "phase-b@2026-08-14T19:01:47Z",
    "started_utc": "2026-08-14T19:01:47Z",
    "model_identity": "Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M",
    "hardware": "g2-standard-4 L4 24GB", "backend": "llama-cpp",
    "temperature": 0.8, "condition": "gbnf+typemask", "regime": "few_shot",
    "seed": 2, "draw": 0, "draw_seed": 200006,
    "task": "corpus/list/append", "task_kind": "corpus"
  },
  "observation": {
    "funnel_outcome": "accepted", "layers_passed": 4,
    "semantic_rule": "identity-match", "semantic_success": false,
    "narrowed": false, "retried": false
  }
}
```

**`observation` is a separate block on purpose.** R2 says the run's
`semantic_success` is never evidence, and a comment saying so is worth less than
a schema saying so: `validation` is what checkers proved, `observation` is what
the run thought, and a later policy layer reading sidecars cannot conflate two
differently-named blocks. Tested
(`ProvenanceTest.test_semantic_success_is_an_observation_and_never_evidence`).

**Nothing is inflated.** `validation` is exactly what the layers earned —
`layers`, the contract version of each, and the subsumption obligation count.
**`spec` stays `null`.** Borrowing the task's spec was considered and rejected:
the task spec describes what was *asked for*, and 61 of the 109 accepted draws
did not satisfy it, so attaching it would be the masquerade R2 forbids under a
different name.

**Nothing depends on when or where the harvest ran.** `run_id` comes from the
run's recorded `started_utc`, `source` is the records path's last three
components (never absolute), and `sequence` is `1_000_000` plus the draw's
position among accepted records. That reserved band is load-bearing rather than
cosmetic: it makes "every curated definition sorts before every generated one,
in every store, whatever order the harvests ran in" true by construction, which
is what keeps `definitions()` order — and therefore prompt order — stable.

**A run with no recorded `model_identity` is refused.** R2.1's "recorded, not
reconstructed" applied at the other end of the pipe: an object that cannot say
which model produced it does not enter.

### Where the origin filter lives, and why there

In `StoreResolver.__init__`, as an `origins` policy (`curated` — the default —
or `all`), applied before an object reaches either registry. `prompts.py` is
untouched.

Three reasons it belongs there and not downstream: it is the only place that
sees provenance at all; every consumer is filtered at once, so an arm cannot be
curated in the prompt and generated in the mask (`digests()` seeds the
reference-hash pruner); and it makes the default *structural* — under `curated`
a harvested store is indistinguishable from an unharvested one, which turns R3's
byte-identity claim into a property rather than a hope.

Two named policies rather than an arbitrary origin set, because the measurement
is exactly *curated vs curated+generated* and a third spelling would be a third
thing to keep honest. An origin outside the schema's closed vocabulary — or a
sidecar with no origin at all — is a `StoreExportError`, never a silent
exclusion: quietly dropping an unrecognised object would shrink the corpus, and
corpus size is the largest effect the experiment ever measured (95.8 % → 71.5 %
rejection).

**Rejected:** filtering in the Rust `export-resolver` (`--origin curated`). One
export would then not serve both arms, the arms would differ by which file they
read instead of by one config flag, and the store would have grown a policy
decision that belongs to the experiment.

### Two stores on disk, deliberately

`.loom-store` is the pinned corpus seed (`task store:seed`), and
`test_store.py::test_the_seeded_store_carries_the_oracle_sidecars_unchanged`
asserts its export *is* the oracle's corpus document — true of a seed, false of
anything harvested. `.loom-store-generated` is the loop's store
(`task store:harvest`): the same corpus plus a run's accepted draws. **Both
follow-up arms read `.loom-store-generated`** and differ only by
`include_generated`, so the A/B is one flag over one store, which is the point.
Both are gitignored and both are reproducible from the repo.

### Four accepted draws were byte-identical to curated corpus objects

Content addressing turned them into `exists` against the curated object, which
keeps its `origin: transpiled` and its `corpus/…` name. That is the correct
answer — the bytes *are* the curated definition — and the guardrail only ever
runs in the safe direction: a generation can never relabel a curated object.

What is lost is the observation that a model reproduced it, which now lives only
in the run records. Recording it in the store would mean a *list* of provenances
per object, which is an evidence-object shape, and R5 defers those. Recorded as
a watch, not built. Tested
(`DeterminismTest.test_a_generation_identical_to_a_curated_object_dedupes_into_it`).

### Escalation and resolution: the arms must differ in what the model *sees*

**Raised.** The first implementation left `prompts.py` untouched, so
`_example_names` still took the full-corpus example list from
`corpus_registry.MANIFEST`. The two arms therefore built **byte-identical
prompts** and differed only in what *resolved*: 81 hashes instead of 47, 60
definitions instead of 26, so a draw naming a generated hash typed instead of
being refused and the masker's reference-hash universe grew.

**Resolved: take the two-line direction.** An arm that only widens the hash
universe tests the references layer, which Phase A measured as a *minor* one —
75 of 664 rejections — while the corpus in context was the largest lever it
found (95.8 % → 71.5 % rejection). Measuring the small thing was not worth
preserving a file freeze.

**`prompts.py` may change for exactly this, because the freeze's purpose was
never the file — it was the invariant**, which is unchanged and is now stated
where it belongs:

> Every existing run path — no store, or a store under the curated policy —
> produces **byte-identical prompts**, proven by the equivalence tests passing
> unmodified.

What changed, and why the invariant survives:

1. **`_example_names(regime, resolver)`** reads `resolver.definitions()` instead
   of `corpus_registry.MANIFEST` for the two full-corpus regimes. It holds
   because `ExperimentResolver.definitions()` *is* the manifest in manifest
   order, and `StoreResolver.definitions()` follows the export's
   `(sequence, hash)` order — where the reserved generated band puts curated
   definitions first, in manifest order, and generated ones after. The ordering
   fell out of the band exactly as predicted; no selection ordering had to be
   fixed.
2. **`few_shot` keeps its four pinned names.** The regime's whole point is a
   small *fixed* set, so letting a store change it would make it a different
   regime. Only the leave-one-out backfill source moved to the resolver, which
   is the manifest under the curated policy.
3. **Leave-one-out excludes by identity, not by name.** The old rule removed
   `task.task_id` from the name list; the new one removes every example whose
   digest is `task.expected_identity`. For a curated-only resolver those are the
   same single name — names and digests are 1:1 — so the bytes do not move. For
   a harvested store the identity rule is the *complete* one: four of phase-b's
   38 accepted identities are byte-identical to curated fixtures, and a store
   assembled in an order where such a draw kept a `generated/…` name would
   otherwise have left the task's own answer sitting in its prompt under a
   different label. Content addressing makes the digest check total.
4. **A definition with no `spec` shows bare.** Harvested definitions have
   `spec: null` (nobody wrote one), and `build_prompt` omits the spec line
   rather than printing a blank one. Every curated definition has a spec —
   asserted — so the branch is unreachable for the curated arm and its bytes are
   untouched.
5. **A definition admitted with no `--name`** is skipped as an example: it has
   no name to look up and no entry to read a spec from. This keeps
   `build_prompt`'s name → digest → entry chain total.

Measured effect, longest prompt per regime, characters:

| regime | corpus resolver | curated arm | generated arm | growth |
|---|---:|---:|---:|---:|
| `none` | 1,098 | 1,098 | 1,098 | 1.00× |
| `few_shot` | 3,346 | 3,346 | 3,346 | 1.00× |
| `full_corpus` | 17,979 | 17,979 | 22,613 | 1.26× |
| `held_out` | 18,183 | 18,183 | 22,817 | 1.25× |

The curated column is identical to the corpus column in every regime, which is
the invariant as a number rather than as a claim.

### Sizing the generated arm's context — the trap that has already cost a launch

Phase B shipped `n_ctx: 4096` against an 11.9k‑token prompt and died at the
third regime. The generated arm's corpus is 26 → 60 definitions, so this was
computed before calling anything done.

**The repo's existing floor was the wrong direction.**
`test_the_shipped_config_has_context_for_the_longest_prompt` divided characters
by 4 — "conservative for English". It is not conservative for this surface. The
phase-b run log's own real-tokenizer numbers say so: `full_corpus` is
17,979 characters and **11,906 tokens**, i.e. **1.51 chars/token**, because
64‑hex hash literals tokenize far denser than prose. The old floor
under-estimated by **2.6×**, in the direction that lets a too-small `n_ctx`
through. `prompts.CHARS_PER_TOKEN = 1.5` now carries the measured figure,
`prompts.context_required()` applies it, and both that test and the two new
follow-up guards use it. `phase_b.config.json` still passes under the honest
divisor (12,635 needed vs 16,384 shipped), so nothing already launched moves.

| | curated arm | generated arm |
|---|---:|---:|
| longest prompt, characters | 18,183 | 22,817 |
| longest prompt, tokens (measured 1.51 chars/token) | 11,959 | **15,110** |
| plus a 512‑token draw | 12,471 | **15,622** |
| `n_ctx` chosen | **32,768** | **32,768** |
| headroom | 20,297 (2.6×) | 17,146 (2.1×) |

**`n_ctx` 16,384 was rejected**: it clears 15,622 by 762 tokens — 4.6 % — which
is not headroom, it is a coin flip. And the margin shrinks with every harvest:
34 generated definitions cost 4,634 characters ≈ 3,069 tokens, about **90 tokens
per generated definition**, so eight more would have pushed it over. At 32,768
the arm absorbs roughly 190 further generated definitions before it is tight.

**Both arms get 32,768, not just the generated one.** A controlled A/B must
differ in exactly one thing, and a differing transport parameter is a confound
for no gain. The cost is KV cache: Qwen2.5‑7B is 28 layers × 4 KV heads × 128
dim, so ~56 KB/token, i.e. 1.75 GiB at 32,768 against ~4.7 GB of Q4_K_M weights
— comfortable on the 24 GB L4. This is only safe because the phase-b fix
decoupled `n_batch` from `n_ctx` (2048/512); without it, a 32k micro-batch
compute buffer would be the next landmine.

`test_both_arms_have_context_for_their_own_longest_prompt` recomputes the
requirement from each arm's own prompts against its own resolver and demands
2× headroom, so neither config can drift under its corpus again.

## Verification

1. `task prototype:test` green, including new harvest tests; the existing
   `StoreResolverEquivalenceTest` passes **unmodified** (R3's default).
2. Harvest of `prototype/runs/phase-b/records.jsonl` into a seeded store:
   reported counts match an independent recount from the records; store
   `fsck` exit 0 after.
3. A generated object's sidecar shows `origin: "generated"` with the run
   metadata; `list --kind definition` distinguishes it from curated by
   sidecar, not by guesswork.
4. The two-arm config runs end-to-end on the stub backend.
5. `task store:test` green (no Rust changes expected; if the export schema
   grows the origin field, its tests grow with it).
6. `task todo:lint`; `git diff --check`.

## Completion criteria

- The loop exists: a fresh store seeded from corpus + harvested generations
  reproduces its counts deterministically on re-harvest (idempotent).
- Curated-only prompts remain byte-identical to pre-loop prompts.
- The two-arm experiment is one operator launch away.

## Recorded verification

Run 2026‑08‑14 on the implementation branch. The numbered steps are the plan's
own, unchanged; raw output follows each.

### 1. `task prototype:test` green, including new harvest tests; the existing `StoreResolverEquivalenceTest` passes **unmodified** (R3's default)

Run with the curated seed's export present
(`.loom-store/export-resolver.json`, 47 objects), so the equivalence tests ran
against the real Rust-produced document.

```
----------------------------------------------------------------------
Ran 635 tests in 68.356s

OK (skipped=1)
```

635 tests: 587 before this increment, +48 from `test_harvest`. The whole of
`StoreResolverEquivalenceTest`, from the same run:

```
test_a_miss_is_a_lookup_error_naming_the_hash (test_store.StoreResolverEquivalenceTest.test_a_miss_is_a_lookup_error_naming_the_hash) ... ok
test_definitions_come_back_in_the_same_order (test_store.StoreResolverEquivalenceTest.test_definitions_come_back_in_the_same_order) ... ok
test_digests_match_including_order (test_store.StoreResolverEquivalenceTest.test_digests_match_including_order) ... ok
test_entries_carry_the_same_spec_and_identity (test_store.StoreResolverEquivalenceTest.test_entries_carry_the_same_spec_and_identity) ... ok
test_every_hash_resolves_to_the_same_object (test_store.StoreResolverEquivalenceTest.test_every_hash_resolves_to_the_same_object) ... ok
test_names_resolve_to_the_same_hashes (test_store.StoreResolverEquivalenceTest.test_names_resolve_to_the_same_hashes) ... ok
test_object_counts_match (test_store.StoreResolverEquivalenceTest.test_object_counts_match) ... ok
test_operation_arity_matches_for_every_ability_operation (test_store.StoreResolverEquivalenceTest.test_operation_arity_matches_for_every_ability_operation) ... ok
test_reference_type_matches_for_every_hash (test_store.StoreResolverEquivalenceTest.test_reference_type_matches_for_every_hash) ... ok
test_resolved_types_are_isolated_copies (test_store.StoreResolverEquivalenceTest.test_resolved_types_are_isolated_copies) ... ok
test_the_declaration_registries_hold_the_same_objects (test_store.StoreResolverEquivalenceTest.test_the_declaration_registries_hold_the_same_objects) ... ok
test_the_seeded_store_carries_the_oracle_sidecars_unchanged (test_store.StoreResolverEquivalenceTest.test_the_seeded_store_carries_the_oracle_sidecars_unchanged) ... ok
test_every_task_and_regime_builds_a_byte_identical_prompt (test_store.PromptEquivalenceTest.test_every_task_and_regime_builds_a_byte_identical_prompt) ... ok
test_narrowing_feedback_also_lands_identically (test_store.PromptEquivalenceTest.test_narrowing_feedback_also_lands_identically) ... ok
```

**Unmodified**, and provably so — and this is the load-bearing line, because
`prompts.py` *did* change (see the escalation above): the equivalence tests are
what prove the change did not move a byte on any existing path.

```
$ git diff --stat -- prototype/test_store.py
$ echo "(no output: the file is untouched by this increment)"
(no output: the file is untouched by this increment)
```

`test_store.py` runs against the *curated* seed, so on its own it only shows
that the filter's default costs nothing when there is nothing to filter. The
stronger claim — byte-identical prompts from a store that **does** hold
generated objects — is
`test_harvest.OriginFilterTest.test_every_task_and_regime_builds_a_byte_identical_prompt`,
which builds `34 tasks × 4 regimes × 2 leave-one-out = 272` prompt pairs through
a harvested export and asserts byte equality on every one. All three levels pass
after the `prompts.py` change: no store, curated store, harvested store under
the curated policy.

`test_masker.py` has one line changed — the `n_ctx` guard's chars-per-token
divisor, 4 → the measured `prompts.CHARS_PER_TOKEN`. It is a *tightening* of an
existing safety check, not an accommodation: the assertion's subject
(`phase_b.config.json`) still passes, with 16,384 against 12,635 required.

**PASS.**

### 2. Harvest of `prototype/runs/phase-b/records.jsonl` into a seeded store: reported counts match an independent recount from the records; store `fsck` exit 0 after

`prototype/runs/` is gitignored, so the records were read from the main
checkout at `/home/will/loom/prototype/runs/phase-b/records.jsonl`. The
`admit --corpus` line's 47-element `objects` array and the harvest line's
34-element one are elided for length and marked as such; nothing else is
altered.

```
$ task store:harvest RECORDS=/home/will/loom/prototype/runs/phase-b/records.jsonl
{"layout_version":1,"status":"created","store":"…/.loom-store-generated"}
{"exists":0,"objects":[ …47 corpus objects, sequence 0–46… ],"status":"admitted","written":47}
{"accepted": 109, "admitted": 34, "distinct_identities": 38, "dry_run": false, "exists": 75, "objects": […34 objects, sequence 1000000–1000107…], "records": 773, "refusals": [], "refused_on_readmission": 0, "run": {"backend": "llama-cpp", "hardware": "g2-standard-4 L4 24GB", "model_identity": "Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M", "run_id": "phase-b@2026-08-14T19:01:47Z", "started_utc": "2026-08-14T19:01:47Z", "temperature": 0.8}, "source": "runs/phase-b/records.jsonl", "status": "harvested"}
{"objects":81,"ok":true,"rows":81}
{"objects":81,"path":"…/.loom-store-generated/export-resolver.json","status":"exported"}
```

The independent recount shares no code with `harvest.py` — it reads the records
and the curated store's `index/types.jsonl` and re-derives the numbers:

```
$ python3 recount.py runs/phase-b/records.jsonl .loom-store/index/types.jsonl
{
 "accepted": 109,
 "distinct_identities": 38,
 "expected_admitted": 34,
 "expected_exists": 75,
 "funnel_outcomes": {
  "accepted": 109,
  "parse": 256,
  "references": 75,
  "scope": 17,
  "typecheck": 316
 },
 "identities_already_curated": 4,
 "identities_new": 34,
 "records": 773
}
```

Every number agrees: 773 records, 109 accepted, 38 distinct identities, of which
4 are byte-identical to curated corpus objects (so 34 new), 75 records are
repeats. `fsck` exit 0 over 81 objects and 81 index rows.

Idempotence, from the completion criteria — the same records into the same store
a second time:

```
{"accepted": 109, "admitted": 0, "distinct_identities": 38, "dry_run": false, "exists": 109, "objects": [], "records": 773, "refusals": [], "refused_on_readmission": 0, …}
```

**PASS** — nothing changed, and the line says so.

`refused_on_readmission` is 0 for this run, which is the honest outcome and not
a missing test: the contracts have not moved since phase-b. The category is
exercised twice in `test_harvest` — a draw the run called accepted whose `ref`
does not resolve (refused at `typecheck`, `TypingError`), and a draw whose
recorded `identity` is not the hash of its own bytes (refused at `identity`).

### 3. A generated object's sidecar shows `origin: "generated"` with the run metadata; `list --kind definition` distinguishes it from curated by sidecar, not by guesswork

```
$ loom-store --store .loom-store-generated list --kind definition
count: 60 origins: {'generated': 34, 'transpiled': 26}

{"hash": "03d8abd83aae…", "kind": "definition", "name": "generated/corpus/list/append/03d8abd83aae", "origin": "generated", "sequence": 1000039, "type": "(fn (data 0x3ff2…(I64)) () (data 0x3ff2…(I64)))"}
{"hash": "0dba3946f35c…", "kind": "definition", "name": "corpus/maybe/mapPoly", "origin": "transpiled", "sequence": 24, "type": "(forall (forall (fn (fn (tyvar 1) () (tyvar 0)) () (fn (data 0x3ff2…((tyvar 1))) () (data 0x3ff2…((tyvar 0)))))))"}
```

The `origin` column is derived from `provenance.origin` in the sidecar and
nothing else — not from the name — so the separation survives any naming
convention. The full sidecar behind the first row (`spec` is `null` and
`observation` is a sibling of `run`, both deliberate):

```json
{
  "deps": ["3ff2104702aeeb53b4dfbc5a09c0441df19f12883e6cf66e21a3bd85420b4e2f"],
  "hash": "03d8abd83aaed7fcb2baffa28fac1db5ea42126cf21ba224a27755dfedc3e5f8",
  "kind": "definition",
  "name": "generated/corpus/list/append/03d8abd83aae",
  "object": null,
  "provenance": {
    "admitter": "prototype.store_admit/1",
    "observation": {"funnel_outcome": "accepted", "layers_passed": 4,
                    "narrowed": false, "retried": false,
                    "semantic_rule": "identity-match", "semantic_success": false},
    "origin": "generated",
    "run": {"backend": "llama-cpp", "condition": "gbnf+typemask", "draw": 0,
            "draw_seed": 200006, "hardware": "g2-standard-4 L4 24GB",
            "model_identity": "Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M",
            "regime": "few_shot", "run_id": "phase-b@2026-08-14T19:01:47Z",
            "seed": 2, "started_utc": "2026-08-14T19:01:47Z",
            "task": "corpus/list/append", "task_kind": "corpus",
            "temperature": 0.8},
    "source": "runs/phase-b/records.jsonl"
  },
  "schema": 1,
  "sequence": 1000039,
  "spec": null,
  "surface": "(def (fn (data 0x3ff2…(I64)) () (data 0x3ff2…(I64))) (lam (data 0x3ff2…(I64)) (let (data 0x3ff2…(I64)) (var 0) (var 1))))",
  "type_surface": "(fn (data 0x3ff2…(I64)) () (data 0x3ff2…(I64)))",
  "validation": {
    "contracts": {"parser": "1.0", "references": "1.0", "scope": "1.0", "typecheck": "1.1"},
    "layers": ["parser", "scope", "references", "typecheck"],
    "obligations": 0
  }
}
```

**PASS.** (Hashes inside type and surface strings elided to `0x3ff2…` for
width; the sidecar on disk carries them in full.)

### 4. The two-arm config runs end-to-end on the stub backend

Both shipped arm configs, loaded as committed and overlaid only with the stub
transport, a two-task subset and one seed (the store export is the real
`.loom-store-generated` one from step 2):

```
$ python3 -m experiment.runner --config followup_curated.stub.json --dry-run
resolver objects   : {"ability": 8, "data": 4, "definition": 26, "extern": 9}
resolver origins   : {"declared": 21, "generated": 0, "transpiled": 26}  (policy: curated)
regimes            : full_corpus, held_out
conditions         : gbnf+typemask
cells to run       : 2

$ python3 -m experiment.runner --config followup_generated.stub.json --dry-run
resolver objects   : {"ability": 8, "data": 4, "definition": 60, "extern": 9}
resolver origins   : {"declared": 21, "generated": 34, "transpiled": 26}  (policy: all)
regimes            : full_corpus, held_out
conditions         : gbnf+typemask
cells to run       : 2
```

Full runs, both exit 0, both writing `records.jsonl` / `summary.json` /
`report.md`:

```
curated    records 4 | resolver_objects {"ability": 8, "data": 4, "definition": 26, "extern": 9}
           resolver_origins {"declared": 21, "generated": 0, "transpiled": 26} | include_generated False | n_ctx 32768
           tokens_prompt [4494, 4494, 4542, 4542]
generated  records 4 | resolver_objects {"ability": 8, "data": 4, "definition": 60, "extern": 9}
           resolver_origins {"declared": 21, "generated": 34, "transpiled": 26} | include_generated True | n_ctx 32768
           tokens_prompt [5653, 5653, 5700, 5700]
```

**PASS**, and the last line is the point of the escalation: the arms now differ
in **what the model is shown** — 4,494 → 5,653 prompt tokens on the stub
tokenizer, +25.8 %, matching the 1.26× character growth measured above — not
only in what resolves. That inequality is asserted, not merely observed:
`FollowUpConfigTest.test_both_arms_run_end_to_end_on_the_stub_backend` requires
every generated-arm prompt to be strictly longer than its curated counterpart,
so the arms can never silently collapse back into a references-only test.

They also still differ in what resolves, which is the second half of the effect:

```
curated digests: 47 definitions: 26
all     digests: 81 definitions: 60
```

`digests()` seeds the masker's reference-hash pruner, so the generated arm both
types and *permits* references the curated arm refuses.

The two arms are asserted to be identical configs but for `include_generated`
and `output_dir` (`test_the_two_arms_differ_only_in_the_origin_flag`) — `n_ctx`
is 32,768 in **both**, so the transport is not a confound — and both are run
end-to-end in the suite, so none of this depends on a manual step.

### 4b. Context sizing for the follow-up arms (added; the trap is not optional)

Not one of the six numbered steps. Recorded because the plan's owner asked for
the number before this could be called done, and because `n_ctx` has already
killed one launch.

```
longest prompt, characters
regime            corpus   curated arm   generated arm   growth
none                1098          1098            1098    1.00x
few_shot            3346          3346            3346    1.00x
full_corpus        17979         17979           22613    1.26x
held_out           18183         18183           22817    1.25x

chars per token, calibrated against the phase-b real-tokenizer numbers
  none              1098 chars /    279 tokens = 3.935 chars/token
  few_shot          3346 chars /   1843 tokens = 1.816 chars/token
  full_corpus      17979 chars /  11906 tokens = 1.510 chars/token
  held_out         18183 chars /  11959 tokens = 1.520 chars/token
  most token-dense regime: 1.510 chars/token — used as the divisor

generated-arm prompt tokens
  full_corpus    calibrated   14975  |  repo's old chars//4 floor    5653
  held_out       calibrated   15007  |  repo's old chars//4 floor    5704

{"peak_prompt_chars": 22817, "peak_tokens_calibrated": 15110,
 "peak_tokens_repo_floor": 5704, "draw_budget": 512,
 "required_calibrated": 15622, "required_repo_floor": 6216}
```

And through the shipped helper, which is what the guard test uses:

```
$ python3 -c "…prompts.context_required(['full_corpus','held_out'], r, draw_tokens=512)"
corpus     12635
curated    12635
generated  15724
```

**Measured requirement: 15,622–15,724 tokens. Chosen `n_ctx`: 32,768 for both
arms** (2.1× headroom on the generated arm, ~190 further generated definitions
of room). 16,384 was rejected at 4.6 % margin. The old `chars // 4` floor would
have reported 6,216 — it would have waved through an `n_ctx` of 8,192 against a
real 15,622-token prompt, which is the same failure mode as phase-b's original
4,096, so the floor was corrected rather than worked around.

**PASS.**

### 5. `task store:test` green (no Rust changes expected; if the export schema grows the origin field, its tests grow with it)

The export schema did not grow; the *index* did, by one field, so its tests grew
with it — two new unit tests plus an extended integration test.

```
running 24 tests
…
test index::tests::the_origin_column_is_lifted_from_the_sidecars_provenance ... ok
test index::tests::a_sidecar_without_provenance_indexes_as_unlabelled_not_as_curated ... ok
test result: ok. 24 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

running 21 tests
…
test a_generated_definition_admits_against_the_stores_own_contents ... ok
test result: ok. 21 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.86s
```

**PASS** — 45 tests, 0 failures (22 unit + 21 integration before this increment;
+2 unit here).

`task store:lint` for good measure:

```
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 5.59s
store:lint exit=0
```

### 6. `task todo:lint`; `git diff --check`

```
TODO.md: clean
todo:lint exit=0
git diff --check exit=0
```

**PASS** — both clean. `TODO.md` is untouched by this branch; moving the corpus
loop item is the orchestrator's call.


## The A/B verdict (2026‑08‑14)

Two arms, identical but for `include_generated`, same zone, same hardware,
same seeds. The curated arm **exactly replicated** phase‑b's cells
(196/55/1.377 and 47/1/0.081) — the cleanest possible baseline. Against it,
the generated arm (34 model-generated definitions added to context,
prompts +26 % tokens):

| metric | curated | generated | Δ |
|---|---|---|---|
| full_corpus acc/1k tok | 1.377 | **1.803** | **+31 %** |
| full_corpus accepted/draws | 55/196 | 72/206 | 28 % → 35 % |
| full_corpus semantic · distinct | 5 · 9 | 6 · 11 | both up |
| tokens to first acceptance | 152 | **98.5** | −35 % |
| repeat rate | 0.836 | 0.847 | diversity held |
| held_out acc/1k tok | 0.081 | **0.244** | **3×** |
| held_out accepted (distinct) | 1 (1) | **3 (3)** | first movement in any run |
| held_out semantic | 0 | 0 | composition still unsolved |

**Reading.** 1.803 is the highest per-token acceptance in the whole
experiment — above plain grammar's corpus-rich 1.452, the bar condition 4
alone could not beat. Feeding the model's own accepted outputs back as
context made it more productive without collapsing diversity, and held-out
acceptance moved for the first time anywhere (3 distinct checker-accepted
definitions vs the 0-or-1 wall). Honest limits: one run per arm, small
held-out counts (1 vs 3 is noise-sensitive), zero held-out *semantic*
success — recall improved, synthesis did not, exactly as conclusion 5
predicted. The loop's next turn (harvest this run, re-run) and a
larger-sample held-out arm are the obvious follow-ups, neither dispatched.

Reports preserved:
[curated](../results/2026-08-14-followup-curated-report.md) ·
[generated](../results/2026-08-14-followup-generated-report.md).


## Turn 2 and the 12-seed sample (2026‑08‑15)

**Turn 2** (run id `20260815T025412Z`; harvest of turn 1 added 7 new
definitions, store at 41 generated): full_corpus **1.728** acc/1k tok
(69/206) vs turn 1's 1.803 — the gain **holds but does not compound**;
held_out fell back to 1 accepted. Reading: the loop banks its recall
improvement in one turn; further self-reproductions add context bytes, not
new capability. [Report](../results/2026-08-15-loop-turn2-report.md).

**12-seed held-out sample** (96 attempts per arm, 4× the original):
- *Curated arm* (`20260815T034950Z`): **4/96 accepted, 0.081 acc/1k tok —
  identical to the 24-attempt rate to the third decimal.** The baseline is
  stable. [Report](../results/2026-08-15-heldout12-curated-report.md).
- *Generated arm* (`20260815T042717Z`,
  [report](../results/2026-08-15-heldout12-generated-report.md)): **7/96
  accepted, 0.142 acc/1k tok, 5 distinct** — above the curated 4/96 in
  every column but **short of turn 1's 0.244 projection and not
  statistically decisive** (7 vs 4 at n = 96, Fisher p ≈ 0.35). The
  held-out acceptance advantage is directional, real-looking, unproven.
- **The first held-out mechanical-floor semantic success — hand-scored
  FAIL.** `heldout/list/reverseThen` seed 4 draw 0 passed checked-tier +
  exact type, and the R3 rubric (spec: "the first list in reverse order,
  with the second following") reveals `λa. λb. let c = b in b` — a
  type-correct function that ignores its first argument and reverses
  nothing. Hand-scored semantic: **0**. Composition remains unachieved,
  and the partly-human metric caught the mechanical floor's first false
  positive exactly as its pre-registration intended.

**Loop verdict, final for this cycle:** the corpus loop reliably buys
recall (+31 % per token, stable across two turns) and buys no measured
composition. Its held-out acceptance advantage (≈1.75×) needs a larger
sample or a diversity-seeking harvest (turn 2 showed self-reproductions
plateau) to become a claim.

## The powered held-out sample (2026‑08‑24) — the advantage is real, composition still isn't

Pre-registered power analysis (n = 952/arm, 80 % power target at the
observed rates, Fisher-exact Monte Carlo — not the normal approximation
alone) scaled the 12-seed sample with 107 fresh seeds per arm, same store
snapshot (41 generated definitions, frozen), same config but for seeds.
[Full report](../results/2026-08-23-heldout-powered-report.md).

- **Pooled: generated 91/952 (9.56 %) vs curated 46/952 (4.83 %).**
  Official pre-registered test — Fisher exact, **two-sided**, α = 0.05:
  **p ≈ 8.4 × 10⁻⁵, odds ratio ≈ 2.08.** The 12-seed sample's directional,
  p ≈ 0.35 result is now decisive: the held-out acceptance advantage is
  **confirmed**, not a projection.
- **Hand-scoring every mechanical-floor "success" in both arms — 2 in
  curated, 21 in generated — finds zero genuine held-out compositions in
  either.** Curated's 2 were one identity, a `List.size` standing in for
  `heldout/list/sum`'s required fold. Generated's 21 deduped to **3**
  distinct identities, all for `heldout/list/reverseThen`, all FAIL: none
  reverses anything, none combines both arguments in spec order.
- **New failure mode, not previously observed: type-collision recycling.**
  19 of generated's 21 flagged records (2 of 3 distinct identities) were
  not fresh reasoning at all — they were a dead object already in the
  store, harvested back on 2026‑08‑14 from `corpus/list/append`
  (`semantic_success: false` at harvest, mechanical acceptance only, R2
  working exactly as designed). `corpus/list/append` and
  `heldout/list/reverseThen` share an identical type signature, so the
  vacuous object type-checks for both and gets regurgitated from the
  full-corpus context to clear a different task's mechanical floor
  without any new reasoning behind it. Only 1 of the 3 identities was
  genuinely fresh model output this run — and it was also wrong
  (`append(b, a)`, no reverse, arguments in the wrong order).

**Loop verdict, updated and now final for this measurement:** the corpus
loop's recall effect (+31 % per token) and its held-out acceptance
advantage (≈2×) are both real and both now measured at a powered sample,
not projected from one. Composition is still zero, everywhere, on every
sample size run so far — and the powered sample surfaced a mechanism for
*why* a larger corpus alone won't fix that on its own: a single
known-wrong harvested object can inflate the mechanical-floor "success"
count on any held-out task whose type happens to collide with the task it
was originally (and wrongly) admitted under. A future harvest that wants
composition, not just recall, needs either semantic (not just mechanical)
admission for held-out-style definitions, or a diversity/dedup step ahead
of harvest that catches type-collision reuse before it's amplified by
being drawn 19 times in one sample.
