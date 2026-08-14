# Plan — Masked-generation experiment, Phase A substrate and harness

**Date:** 2026‑08‑13
**Status:** Implemented; stub-backend path PASS, live run gated on the T5 model item
**Implements:** [The masked-generation experiment](2026-08-13-masked-generation-experiment.md) — R1, R2, R2.1 (Phase A), R3, R4, and the Work section's first two Phase A boxes
**Decides:** nothing about the design; the design of record is the plan above

## Objective

Build the substrate and harness Phase A needs, and nothing else: R1's disposable
store-shaped resolver, R4's four corpus regimes with a task set that includes
held-out compositional tasks, and R2's conditions 1–3 runnable with one command
under the shared fixed-token-budget-per-task rule. The deliverable that matters
downstream is **R3's funnel classification, aggregated into the failure
distribution by checker layer** — the number R2.1 says Phase B's masker gets
designed against.

Explicitly out, by rule rather than by scheduling: per-token masking anywhere
(condition 4 is refused by name), namespaces, leases, policy admission,
persistence, garbage collection.

No visible surface beyond generated report tables, which are markdown emitted by
the runner itself and shown in full below, so this plan carries no mockups.

## What was built

`prototype/experiment/` — a package, not five more files in `prototype/`. The
prototype directory's file table is the README's index of the *language*
prototype's contract surface; `resolver.py`, `prompts.py` and `runner.py` are
names with no Loom meaning and do not belong next to `scope.py` and
`typecheck.py`. The package boundary is the consumer/consumed boundary R1 draws,
and it is visible in a directory listing.

| Module | Role |
|---|---|
| `experiment/resolver.py` | R1's resolver: one hash-keyed lookup surface over `DeclarationRegistry` + `DefinitionTypeRegistry` + the corpus fixture bytes. Answers *what type does this hash have*, *what is this hash*, *what are its canonical bytes*. |
| `experiment/prompts.py` | R4's four regimes, the corpus-drawn task set, and the eight held-out compositional tasks with their expected types. |
| `experiment/backends.py` | The model seam — one callable, prompt (+ optional grammar) to tokens. llama.cpp server, llama.cpp CLI, deterministic stub. |
| `experiment/evaluate.py` | R3's funnel (parse → scope → references → typecheck), the operationalized semantic-success rule, and condition 3's narrowing note. |
| `experiment/runner.py` | Conditions 1–3 under the shared budget rule, the JSONL run record, the aggregate report and the Phase B gate table. |
| `experiment/phase_a.config.json` | The shipped config. `backend` is empty, so the one-command entry point refuses until the T5 item lands. |
| `prototype/test_experiment.py` | 40 tests; the whole harness end to end on the stub backend. |

Nothing in the package re-implements a checker. Every layer is reached through
its published `validate_source` entry point (`prototype/contracts.py`), which is
the point: the funnel has to measure the layers the prototype actually ships.

### The resolver (R1)

`ExperimentResolver` builds once at construction and is immutable thereafter:
26 corpus definitions, 4 data declarations, 8 builtin abilities, 9 assumed-base
externs — 47 hash-keyed objects. `reference_type` resolves definitions first,
then declarations, and refuses an unknown hash exactly as
`corpus_registry.reference_type`'s closure does; a test pins the two against
each other over every corpus and extern hash. It is also the honest lower bound
for R6's "what API must the store expose to the masker": whatever this class
needed is the floor.

### The regimes (R4)

`none` / `few_shot` / `full_corpus` / `held_out`. The first three run the
corpus-drawn task set; `held_out` runs the compositional set with full-corpus
context. R4 lists the fourth alongside the other three, and it is the only one
that is a property of the *task* rather than of the prompt — kept explicit
rather than smoothed away, because R3 scores the two task kinds by different
rules.

Two harness decisions the parent plan does not state, both made so a
pre-registered prediction stays testable:

- **No hash directory is ever supplied.** Prediction 2 is phrased in terms of
  64‑hex hashes being unguessable in low-example regimes and becoming available
  "once examples supply the hashes". Handing the model a name→hash table would
  make that prediction untestable, so the harness does not have one; hashes
  enter a prompt only through examples. A test asserts the `none` regime's
  prompt contains no 64‑hex hash and the `few_shot` prompt does.
- **Leave-one-out is on by default.** A corpus-drawn task under `full_corpus`
  would otherwise carry its own answer verbatim and semantic success would
  measure transcription. `leave_one_out: false` restores the verbatim
  condition, which is what prediction 6's memorization-pressure claim needs. The
  flag's value is written into every run record, so the two runs can never be
  confused after the fact.

### The held-out compositional task set

Eight new spec texts, none of them a corpus entry's spec, each answerable only
by composing corpus definitions and the assumed base. Expected types are built
as IR from the same hashes the corpus uses and rendered through the canonical
transcoder, and a test proves each one is well-formed by running
`(def T (hole T ()))` through all four layers — so a typo in an expected type
becomes a test failure rather than a silent scoring bug that fails every
held-out generation.

| Task | Ask | Expected type | Composes |
|---|---|---|---|
| `heldout/list/concatLength` | The number of elements you get when the second list is placed after the first. | `List I64 -> List I64 -{}> I64` | `list/append` + `List.size` |
| `heldout/list/mapLength` | The number of elements a list has once a function has been applied to every one of them. | `(I64 -{}> I64) -> List I64 -{}> I64` | `list/map` + `List.size` |
| `heldout/list/reverseThen` | The first list in reverse order, with the second list following it. | `List I64 -> List I64 -{}> List I64` | `list/reverse` + `list/append` |
| `heldout/maybe/mapOrElse` | The result of applying a function to the option's value, or the supplied default when the option is empty. | `(I64 -{}> I64) -> Maybe I64 -> I64 -{}> I64` | `maybe/map` + `maybe/getOrElse` |
| `heldout/list/headOrElse` | The first element of a list, or the supplied default when the list is empty. | `List I64 -> I64 -{}> I64` | `list/uncons` + `maybe/getOrElse` |
| `heldout/list/sum` | The result of adding every element of a list together, starting from zero. | `List I64 -{}> I64` | `list/foldLeft` + `I64.add` |
| `heldout/sample/stampedBytes` | The wall-clock time at which a draw of the requested number of random bytes began, paired with the bytes that were drawn. | `cap clock -> cap rand -> I64 -{rand,clock}> Pair I64 Bytes` | `clock/now` + `rand/bytes` |
| `heldout/nat/selectNonNegative` | A choice, made on a boolean, between a positive integer and a nonnegative one, given back as a nonnegative integer. | `Bool -> {n\|0<n} -> {n\|-1<n} -{}> {n\|-1<n}` | `nat/widenPos` + `nat/select` |

The set is deliberately not eight variations of one shape: two of them
(`headOrElse`, `mapOrElse`) do not type by threading alone and need an
eliminator in between, one is effectful with a two-ability closed row whose
bytewise sort order is itself a thing to get right, and one is the refinement
composition that needs a widening before the choice can be made.

### The funnel and semantic success (R3)

`run_funnel` runs parse → scope → references → typecheck and classifies by
**error class**, not by position, which is what makes it robust to the layers
being cumulative (`references.validate_source` re-runs scope; every entry point
re-parses). `layers_passed` records depth independently.

One normalization, `extract_definition`, is applied identically to every
condition before the funnel: strip a markdown fence, strip surrounding
whitespace, truncate to the first balanced parenthesized form. All three are
no-ops under the grammar and all three are generous to unconstrained
generation — without the third, condition 1 would lose most draws to trailing
chatter rather than to the canonical surface, and R3's parse-acceptance number
would be measuring politeness. Uniform, so it cannot flatter one condition.

Semantic success is operationalized now, per R3, not at analysis time:

- **corpus-drawn** — identity match against the pinned fixture identity. A
  match with differing surface bytes is scored a *failure* and flagged, because
  at equal identity that would mean the parser accepted a non-canonical
  surface, which is a parser bug worth surfacing loudly.
- **held-out** — the mechanical floor: funnel-accepted *and* type surface
  exactly equal to the expected type. Every such record carries
  `rubric_pending: true` and the report counts them, because R3 says the metric
  is partly human "so it cannot be silently dropped mid-run". The hand-scored
  rubric on a fixed sample is an outstanding obligation and the report says so
  on every run.

### The conditions and the budget rule (R2)

`unconstrained` / `gbnf` / `gbnf+rejection`. The budget rule is implemented
literally: a fixed total token budget **per task**, spent across as many draws
as it takes, with accepted definitions counted inside it. Every condition gets
the same number; the runner has no way to express a per-attempt budget. Draw
seeds are derived deterministically (`seed * 100003 + draw`) so redraws differ
from each other and a rerun still reproduces the run exactly — a test asserts
that.

`gbnf+rejection` hands the rejecting layer and its error back into the next
prompt (§8.3-style narrowing at *definition* granularity). Narrowing text is
appended after the examples and before the ask, so the prompt prefix is
byte-identical across conditions until a rejection has actually happened.

Condition 4 is refused by name with a message that says why: R2.1 builds the
masker against the failure distribution, not before it.

### The model seam

One method, `generate(prompt, *, grammar, max_tokens, seed, temperature)`. Three
implementations: `LlamaServerBackend` (llama.cpp `/completion`; preferred,
because the response carries exact `tokens_predicted` and R2's budget rule is
only as honest as its token accounting), `LlamaCliBackend`
(`llama-cli --grammar-file`, token counts scraped from llama.cpp's timing lines,
and it **refuses rather than estimating** if the scrape fails), and
`StubBackend`. `loom.gbnf` is handed to llama.cpp unchanged; the harness never
interprets it. There is no per-token hook anywhere in the file.

The stub carries two scripts rather than one: with a grammar it draws from
outputs that all parse, without one it may draw a syntax break. That is exactly
what condition 2 buys from llama.cpp, so a stub run exercises the same branches
a live run does.

### What the one-command run still needs from the T5 item

`task experiment:phase-a` reads `prototype/experiment/phase_a.config.json`
(override with `LOOM_EXPERIMENT_CONFIG`). It ships with `backend: ""` and exits
2 with an operator-facing message naming the blocking T5 item and quoting the
parent plan's Work line. To run live the operator supplies exactly three things:

1. `backend` — `llama-server` (plus `server_url`) or `llama-cli` (plus `binary`
   and `model_path` to a local GGUF).
2. `model_identity` — refused if empty for a live backend, because R2.1 requires
   the model to be *recorded before running*, not reconstructed afterwards.
3. `hardware` — free text, recorded into every report header.

Everything else (budget, seeds, sampling, regimes, conditions) already has a
default. `--dry-run` reports the run's shape and its upper-bound token cost
without touching a model: 774 cells and an upper bound of 396 288 completion tokens at the shipped
defaults.

## Deviations from the parent plan

- **The `held_out` regime is a task-set axis, not a prompt axis.** R4 lists it
  with the other three; the harness implements it as full-corpus context over
  the compositional task set, and says so in `prompts.py`. Nothing else is
  consistent with R3 scoring the two task kinds by different rules.
- **Two harness decisions the parent plan does not state** — no hash directory,
  leave-one-out on by default — both taken to keep pre-registered predictions 2
  and 6 testable, both recorded in every run record.
- **A fifth module (`backends.py`) beyond the four the item names.** The model
  seam is the one part of the harness that is allowed to be unavailable, and
  keeping its failure mode in its own file is what lets `runner.py` treat "no
  model" as one caught exception.
- **Error localization and repair cost are recorded, not analysed.** R3 asks
  how far in a draw fails and how much of the prefix survives narrowing. Phase A
  records the failing layer, the failing path, the draw index and the redraw
  count; prefix survival under §8.3 narrowing is a Phase B measurement because
  it is defined against the incremental interface Phase B builds.

## Verification

1. `task prototype:test`

```
Ran 334 tests in 1.122s

OK (skipped=1)
```

PASS — 40 of those are the new `test_experiment` suite (294 before this change;
the one skip is the pre-existing optional-solver test in `test_corpus`).

2. `python3 -m py_compile prototype/*.py prototype/experiment/*.py`

```
(no output)
```

PASS.

3. `task todo:lint`

```
TODO.md: clean
```

PASS.

4. `git diff --check`

```
(no output)
```

PASS.

5. Stub-backend end-to-end run, report rendered (`test_experiment.EndToEndStubRunTest`)

```
## Failure distribution by checker layer — the Phase B gate

| regime | parse | scope | references | typecheck | accepted | reject rate |
|---|---|---|---|---|---|---|
| few_shot | 0 | 3 | 3 | 4 | 6 | 62.5% |
| held_out | 0 | 3 | 4 | 3 | 6 | 62.5% |
| **all** | 0 | 6 | 7 | 7 | 12 | 62.5% |
```

PASS — the table's shape is what Phase B consumes. The numbers are the stub's
canned script and carry no information about any model; that is the point of a
stub run.

6. One-command entry point with no backend configured — `task experiment:phase-a`

```
No model backend is configured, so Phase A cannot run.

Phase A's model and hardware selection is a T5 item — it needs the operator, not
an agent, and the plan requires the choice to be *recorded before running*:
...
task: Failed to run task "experiment:phase-a": exit status 2
```

PASS.

7. Live smoke generation against a local llama.cpp binary

**NOT RUN.** No `llama-cli`, `llama-server`, `llama-gbnf-validator` or
`test-gbnf-validator` is on `PATH` in this environment. Optional by the item's
own terms; the live run is gated on the T5 model-selection item and gets
recorded by the runner itself when it happens.

## Hardening amendment (2026-08-13)

A real full-matrix run on CPU exposed the gap the completion criteria above
don't cover: a draw exceeded the backend timeout hours in (thermal throttling
had collapsed decode to 0.3 tok/s), `BackendUnavailable` propagated out of
`run()`, and the process died having written **nothing** — `runner.py`
buffered every record in memory and only wrote `records.jsonl`/`summary.json`/
`report.md` at the very end, and there was no way to resume. `experiment/runner.py`
and `test_experiment.py` were hardened in response, with no change to the
records schema beyond two additive per-draw fields:

- **Append-mode records.** When `run()` is given an `output_dir` (the CLI's
  path, via `main`), every draw's record is appended to `records.jsonl` the
  moment it is built and flushed per write, instead of being held in memory
  until the end. Callers that call `run()` directly with no `output_dir` — the
  rest of the test suite — get the original pure in-memory contract,
  unchanged.
- **Partial-run artifacts.** A `BackendUnavailable` or `KeyboardInterrupt`
  from the cell loop now writes `summary.json`/`report.md` for whatever cells
  finished before re-raising with a "partial run: N of M cells" message,
  instead of the process dying silently mid-matrix.
- **Resume.** Each draw record carries an additive `cell_done: true` on the
  record that ends its `(task, condition, regime, seed)` cell — the
  completeness marker. On startup, if `records.jsonl` already exists, cells
  whose completeness marker is present are loaded and skipped ("resuming:
  skipping N completed cells"); a cell cut off mid-draw has no such marker and
  is discarded and rerun from draw 0, so a resumed run never duplicates draw
  records. `--fresh` discards the existing file outright instead of resuming.
- **Per-draw retry.** One retry after a `BackendUnavailable` on a single draw
  (a server hiccup, not necessarily a hard-down backend), recorded on the
  record as an additive `retried: true`. A second consecutive failure is not
  swallowed — it propagates into the partial-write abort path above.

Covered by `test_experiment.CrashSafetyTest` (incremental persistence, partial
artifacts on a dead backend, resume skipping a completed cell and finishing
the rest, `--fresh`'s refuse-then-obey behaviour, and the retry-once path).

## Completion criteria

- [x] R1's resolver exists, unifies the registries behind one lookup surface,
  and builds none of R1's excluded machinery.
- [x] R4's four regimes construct prompts; the task set includes eight held-out
  compositional tasks with expected types proven well-formed.
- [x] Conditions 1–3 run with one command under the shared budget rule.
- [x] R3's funnel classifies by checker layer and the semantic rule is
  operationalized for both task kinds, with the human half flagged.
- [x] The failure-distribution-by-layer table that gates Phase B is produced.
- [x] No per-token masking anywhere; condition 4 refused by name.
- [ ] The live Phase A run — gated on the T5 model-selection item, recorded by
  the runner into `runs/phase-a/` and reported against the pre-registered
  predictions.
