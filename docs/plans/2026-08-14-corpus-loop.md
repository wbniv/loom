# Plan — Closing the corpus loop: accepted generations enter the store

**Date:** 2026-08-14
**Status:** Designed; not yet built
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

## Cost

$0 — local only. (The follow-up GPU run, when the operator launches it,
prices like every prior matrix: ~$1–3 of trial credit.)

## Work

- [ ] `harvest` entry point + tests (R1, R2) — real fixture: the committed
  run records under `prototype/runs/phase-b/` (109 accepted draws,
  ~31 distinct identities).
- [ ] Origin filter through export/StoreResolver + curated-only default
  equivalence preserved (R3).
- [ ] Two-arm follow-up config, stub-verified (R4).
- [ ] Run log + verification recorded here.

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
