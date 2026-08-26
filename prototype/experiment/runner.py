"""R2's conditions 1-3 under the shared budget rule, and the Phase A report.

Run it with one command::

    task experiment:phase-a                    # uses experiment/phase_a.config.json
    LOOM_EXPERIMENT_CONFIG=my.json task experiment:phase-a

Conditions (R2), of which Phase A runs the first three:

``unconstrained``   no grammar; the model writes whatever it writes.
``gbnf``            sampled under `loom.gbnf`; syntax cannot fail.
``gbnf+rejection``  sampled under `loom.gbnf`, the full checker run on each
                    completed definition, and a rejected draw redrawn with the
                    rejecting layer's error handed back (§8.3-style narrowing at
                    definition granularity). This is the per-token masker's real
                    economic rival, so it is measured on the same axis: accepted
                    definitions per token.

The budget rule (R2) is the load-bearing part and is implemented literally: **a
fixed total token budget per task**, spent across as many draws as it takes,
with accepted definitions counted inside it. Every condition gets the same
number, so masked decoding's late-and-expensive failures and unconstrained
generation's early-and-cheap ones are paid for out of the same purse. A
per-attempt budget would make the conditions incomparable, and the runner has no
way to express one.

``gbnf+typemask``   Phase B's condition 4: no grammar is handed to the model at
                    all. Instead every decoding step is masked by
                    `masker.Masker` — `loom.gbnf` prefix-feasibility, then the
                    type-state pruners — so syntax *and* the pruned type errors
                    become unreachable rather than rejected after the fact. It
                    needs a backend that exposes logits, which is why it has its
                    own transport (`llama-cpp`) and its own no-model stub path.

Comparability boundary, stated because R1 requires it: condition 4 runs on a
different transport from conditions 1-3 (in-process `libllama.so` rather than
`llama-server`), so **end-to-end wall clock is not comparable across the
Phase A / Phase B line**. What is comparable is the budget-rule axis — accepted
definitions per token — and R3's per-token *mask* overhead, which is measured
inside the masker and is transport-independent. The report says so on the page.

The B1 dispatch builds the machinery and proves it on the stub; B2 decides
pruner priority from Phase A's failure distribution and runs the live matrix.
The legacy placeholder condition name `masked` is refused by name, pointing at
the implemented one.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import contracts

from .backends import NO_MASK_BACKEND_MESSAGE, BackendUnavailable, grammar_text, make_backend
from .evaluate import (
    ACCEPTED,
    LAYERS,
    OUTCOMES,
    FunnelTally,
    extract_definition,
    narrowing_note,
    run_funnel,
    score_semantic,
)
from .masker import KNOWN_PRUNER_NAMES, PRUNER_NAMES, build_masker
from .prompts import (
    ADDRESS_BOOK_NONE,
    ADDRESS_BOOK_TYPED,
    ADDRESS_BOOKS,
    KIND_CORPUS,
    KIND_HELD_OUT,
    REGIME_HELD_OUT,
    REGIMES,
    Task,
    all_tasks,
    build_prompt,
    tasks_for_regime,
)
from .resolver import ExperimentResolver
from .store_resolver import POLICY_ALL, POLICY_CURATED, StoreExportError, StoreResolver

CONDITION_UNCONSTRAINED = "unconstrained"
CONDITION_GBNF = "gbnf"
CONDITION_GBNF_REJECTION = "gbnf+rejection"
CONDITION_TYPEMASK = "gbnf+typemask"
#: Phase B's placeholder name before it was implemented. Kept only so a config
#: written against the plan's earlier wording fails with a pointer, not a shrug.
CONDITION_MASKED = "masked"

#: The three Phase A conditions, in R2's order.
CONDITIONS = (CONDITION_UNCONSTRAINED, CONDITION_GBNF, CONDITION_GBNF_REJECTION)

#: Every condition the runner can run, Phase A's three plus Phase B's one.
ALL_CONDITIONS = (*CONDITIONS, CONDITION_TYPEMASK)

#: Conditions that sample under `loom.gbnf`. Their funnel outcomes are the
#: "failure distribution by checker layer for GBNF-valid generations" that R2.1
#: names as Phase A's deliverable into Phase B's design. Condition 4 is
#: deliberately **not** here: the gate table is Phase A's product and adding a
#: condition whose syntax failures are impossible by construction would change
#: what that table means.
GRAMMAR_CONDITIONS = (CONDITION_GBNF, CONDITION_GBNF_REJECTION)

#: Conditions whose syntax cannot fail — by grammar sampling (2, 3) or by mask
#: (4). Used for reporting, never for the Phase A gate.
SYNTAX_CONSTRAINED = (*GRAMMAR_CONDITIONS, CONDITION_TYPEMASK)

DEFAULT_CONFIG = Path(__file__).resolve().parent / "phase_a.config.json"


@dataclass
class Config:
    """Everything a run needs, and everything a rerun needs to reproduce it."""

    backend: str = ""
    server_url: str = ""
    binary: str = ""
    model_path: str = ""
    #: Recorded, not derived: R2.1's reproducibility requirement is a *recorded*
    #: model identity. Left empty for a live run, the runner refuses.
    model_identity: str = ""
    hardware: str = ""
    timeout: float = 900.0
    backend_extra: dict = field(default_factory=dict)
    extra_args: list = field(default_factory=list)

    temperature: float = 0.8
    token_budget_per_task: int = 512
    max_tokens_per_draw: int = 256
    max_draws_per_task: int = 32
    seeds: list = field(default_factory=lambda: [1])
    conditions: list = field(default_factory=lambda: list(CONDITIONS))
    regimes: list = field(default_factory=lambda: list(REGIMES))
    #: `null` for the regime's whole task set, or an explicit list of task ids.
    tasks: list | None = None
    leave_one_out: bool = True
    #: The 2026-08-24 next-lever plan §4.2's manipulated variable: `"none"`
    #: (the R4 prompt, byte for byte — every pre-existing config is here),
    #: `"full"` (every `ref`-legal object's address) or `"typed"` (§4.2's
    #: goal-type filter over the same rows). Recorded on every draw, because
    #: the arm is what §4.5's primary partitions on.
    address_book: str = ADDRESS_BOOK_NONE
    stop_on_semantic_success: bool = False
    output_dir: str = "runs/phase-a"
    #: Truncation applied to the raw model text stored in the JSONL record. The
    #: normalized `source` is always stored whole.
    raw_text_limit: int = 2000

    stub_outputs: list = field(default_factory=list)
    stub_grammar_outputs: list = field(default_factory=list)
    #: Condition 4's stub targets. Defaults to `stub_grammar_outputs`.
    stub_masked_outputs: list = field(default_factory=list)

    # -- Phase B, condition 4 -------------------------------------------
    #: Which type-state pruners are active, by name. An empty list runs the
    #: syntax layer alone, which is the honest ablation baseline for R5.
    pruners: list = field(default_factory=lambda: list(PRUNER_NAMES))
    #: `libllama.so` of the pinned llama.cpp build; empty uses `llama_ffi`'s
    #: default, which is the path the parent plan records.
    llama_lib: str = ""
    #: An earlier run's `summary.json` — Phase A's — that condition 4 is scored
    #: against for R5. Named in the config rather than passed on the command
    #: line so the comparison's provenance is recorded with the run that made
    #: it. Ignored unless condition 4 ran.
    baseline_summary: str = ""

    # -- the corpus loop (docs/plans/2026-08-14-corpus-loop.md R3/R4) ------
    #: A `loom-store export-resolver` document to build the resolver from,
    #: instead of the pinned corpus tree. Empty keeps the original behaviour
    #: exactly: `ExperimentResolver()` over `corpus_registry.MANIFEST`.
    store_export: str = ""
    #: Whether the resolver admits `origin: generated` objects. This is the
    #: whole of the follow-up A/B: two configs identical but for this flag,
    #: reading the same store. False is the default everywhere, and under it a
    #: harvested store is indistinguishable from an unharvested one.
    include_generated: bool = False

    n_ctx: int = 4096
    n_threads: int = 0
    #: Layers offloaded to the GPU by the in-process transport. `-1` is
    #: llama.cpp's own "all layers, falling back where there is no device", so
    #: it is right on a CPU laptop and on the run host alike. `0` forces CPU.
    n_gpu_layers: int = -1

    source_path: str = ""

    @classmethod
    def load(cls, path):
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SystemExit(f"experiment config not found: {path}") from None
        except json.JSONDecodeError as error:
            raise SystemExit(f"experiment config {path} is not valid JSON: {error}") from None
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise SystemExit(
                f"experiment config {path}: unknown keys {', '.join(unknown)}; "
                f"known keys are {', '.join(sorted(known - {'source_path'}))}")
        config = cls(**raw)
        config.source_path = str(path)
        # Anchored to the config's own directory rather than the process's cwd:
        # the remote runner launches from `prototype/` while the config it
        # launches lives in `prototype/experiment/`, so a cwd-relative baseline
        # would resolve on this box and silently vanish on the instance.
        if config.baseline_summary and not Path(config.baseline_summary).is_absolute():
            config.baseline_summary = str(
                (path.parent / config.baseline_summary).resolve())
        # Same anchoring, same reason: the follow-up arms name a store export
        # that sits at the repo root, and both arms must resolve it identically
        # wherever the runner is launched from.
        if config.store_export and not Path(config.store_export).is_absolute():
            config.store_export = str((path.parent / config.store_export).resolve())
        config.validate()
        return config

    def validate(self):
        for condition in self.conditions:
            if condition == CONDITION_MASKED:
                raise SystemExit(
                    "condition 'masked' was Phase B's placeholder name before the masker "
                    f"existed; the implemented condition is {CONDITION_TYPEMASK!r}. R2.1 "
                    "still holds for what it runs: B1 built the core, and pruner priority "
                    "comes from Phase A's failure distribution in B2.")
            if condition not in ALL_CONDITIONS:
                raise SystemExit(
                    f"unknown condition {condition!r}; known conditions: "
                    f"{', '.join(ALL_CONDITIONS)}")
        for pruner in self.pruners:
            # Validated against the *known* set, not the default one: the
            # default is what a config that says nothing gets, and `spine-goal`
            # is opt-in precisely so that stays unchanged (§2.4's follow-up,
            # `docs/plans/2026-08-25-mask-spine-refs.md`).
            if pruner not in KNOWN_PRUNER_NAMES:
                raise SystemExit(
                    f"unknown pruner {pruner!r}; known pruners: "
                    f"{', '.join(KNOWN_PRUNER_NAMES)}")
        for regime in self.regimes:
            if regime not in REGIMES:
                raise SystemExit(f"unknown regime {regime!r}; known regimes: {', '.join(REGIMES)}")
        if self.address_book not in ADDRESS_BOOKS:
            raise SystemExit(
                f"unknown address_book {self.address_book!r}; known address books: "
                f"{', '.join(ADDRESS_BOOKS)}")
        if self.address_book == ADDRESS_BOOK_TYPED and list(self.regimes) != [REGIME_HELD_OUT]:
            # The filter needs a *declared* task type, and only a held-out task
            # has one. Refusing here rather than at the first corpus prompt
            # keeps the failure a config error instead of a mid-run crash.
            raise SystemExit(
                "address_book 'typed' filters on the task's declared type, which "
                "only held-out tasks carry; plan §4.2's arms are the 'held_out' "
                f"regime alone, and this config runs {self.regimes}.")
        if self.token_budget_per_task < 1 or self.max_tokens_per_draw < 1:
            raise SystemExit("token_budget_per_task and max_tokens_per_draw must be positive")
        if not self.seeds:
            raise SystemExit("at least one seed is required; the run must be reproducible")
        if self.include_generated and not self.store_export:
            raise SystemExit(
                "include_generated is set but store_export is empty. Generated "
                "objects exist only in a store; the corpus tree has none, so "
                "this config would silently run the curated arm twice.")
        if self.backend in ("llama-server", "llama-cli", "llama-cpp") and not self.model_identity:
            raise SystemExit(
                "model_identity is empty. R2.1 requires the model and hardware to be "
                "recorded before the run, not reconstructed after it — set "
                '"model_identity" (and "hardware") in the config.')

    def sampling(self):
        return {"temperature": self.temperature, **self.backend_extra}


def _select_tasks(config: Config, regime: str) -> tuple[Task, ...]:
    tasks = tasks_for_regime(regime)
    if config.tasks is None:
        return tasks
    wanted = list(config.tasks)
    index = {task.task_id: task for task in all_tasks()}
    missing = [name for name in wanted if name not in index]
    if missing:
        raise SystemExit(f"unknown task ids in config: {', '.join(missing)}")
    chosen = tuple(index[name] for name in wanted)
    # A regime still only runs the task kind it is defined over, so an explicit
    # list is a filter, never a way to smuggle held-out tasks into `few_shot`.
    kind = KIND_HELD_OUT if regime == "held_out" else KIND_CORPUS
    return tuple(task for task in chosen if task.kind == kind)


def make_resolver(config: Config):
    """The resolver this config's arm runs against.

    Three states, and the first is the one every pre-existing config is in:

    * no `store_export` — `ExperimentResolver()` over the pinned corpus tree,
      byte for byte the behaviour every prior run had;
    * `store_export`, `include_generated: false` — `StoreResolver` under the
      curated origin policy. Same objects, same order, same prompts; the store
      is merely a different way of reading the same corpus, which is what store
      v0's equivalence gate proved;
    * `store_export`, `include_generated: true` — the same store with its
      harvested generations admitted as well.

    The filter is applied here, once, and every consumer inherits it: prompt
    examples, `reference_type` on the decode path, and the masker's
    reference-hash universe. An arm cannot be curated in one and generated in
    another.
    """
    if not config.store_export:
        return ExperimentResolver()
    path = Path(config.store_export)
    if not path.is_file():
        raise SystemExit(
            f"store_export {path} does not exist. Build it with "
            "`task store:seed && task store:export`, or `task store:harvest` "
            "for an arm that needs the generated objects too.")
    policy = POLICY_ALL if config.include_generated else POLICY_CURATED
    try:
        return StoreResolver.from_path(path, origins=policy)
    except StoreExportError as error:
        raise SystemExit(f"store_export {path} is unusable: {error}") from None


def make_masker(config, backend, resolver):
    """Condition 4's masker, over whatever vocabulary the backend tokenizes with.

    The mask is the same object either way; only the vocabulary and the logits
    are the backend's. A backend that cannot expose a vocabulary cannot run
    condition 4, and says so by name rather than failing mid-run.
    """
    vocabulary = getattr(backend, "mask_vocabulary", None)
    if vocabulary is None:
        raise BackendUnavailable(NO_MASK_BACKEND_MESSAGE.format(backend=backend.name))
    return build_masker(vocabulary(), resolver, names=config.pruners)


def _draw(backend, condition, masker, prompt, grammar, max_tokens, seed, temperature):
    """One backend call for one draw attempt. Returns `(generation, mask_fields)`.

    Raises `BackendUnavailable` straight through — `run_task` is the one place
    that decides whether a failure here gets a retry.
    """
    if condition == CONDITION_TYPEMASK:
        # Counters only: the transition and mask caches survive, because they
        # are the reason the per-token cost is what it is.
        masker.reset_stats()
        generation = backend.generate_masked(
            prompt, masker=masker, max_tokens=max_tokens, seed=seed, temperature=temperature)
        mask_fields = masker.stats()
        mask_fields["mask"] = True
        return generation, mask_fields
    generation = backend.generate(
        prompt,
        grammar=grammar if condition in GRAMMAR_CONDITIONS else None,
        max_tokens=max_tokens,
        seed=seed,
        temperature=temperature,
    )
    return generation, {}


def run_task(task, condition, regime, seed, backend, resolver, config, grammar, masker=None, sink=None):
    """One (task, condition, regime, seed) cell, spent down to the budget.

    Every draw's record is built and, if `sink` is given, handed to it
    immediately (`run`'s incremental-persistence path) before the loop moves
    on — so a crash on the *next* draw loses only that one draw, not the cell.
    The full list is still returned for the no-`sink` in-memory contract the
    test suite calls directly.

    Each record carries two additive fields for crash-safety:

    ``cell_done``   true on the record that ends the cell (no room left for a
                    full-cap draw, draw cap hit, or an early semantic-success
                    stop) — the resume completeness marker `run` looks for. A
                    cell cut off mid-draw writes no such record and is rerun
                    from scratch.
    ``retried``     true if this draw needed the one-retry-after-a-hiccup path
                    below.

    **Budget semantics** (plan `2026-08-24-next-lever` §4.3, fixing the §1.3
    defect): a draw is granted only while the *whole* per-draw cap still fits
    in the remaining budget, and every granted draw is allotted exactly
    `max_tokens_per_draw`. No draw is ever handed a leftover fragment, for any
    config — a truncated draw is then a genuine rejection rather than the
    thing that terminates the cell.
    """
    if condition == CONDITION_TYPEMASK and masker is None:  # pragma: no cover - `run` builds it
        raise BackendUnavailable(NO_MASK_BACKEND_MESSAGE.format(backend=backend.name))
    budget = config.token_budget_per_task
    per_draw = config.max_tokens_per_draw
    used = 0
    draws = 0
    narrowing = ""
    records = []
    while budget - used >= per_draw and draws < config.max_draws_per_task:
        max_tokens = per_draw
        prompt = build_prompt(
            task, regime, resolver,
            leave_one_out=config.leave_one_out,
            narrowing=narrowing,
            address_book=config.address_book,
        )
        # The seed varies per draw or every redraw repeats the first draw
        # exactly; the derivation is deterministic so the run still reproduces.
        draw_seed = seed * 100_003 + draws
        retried = False
        try:
            generation, mask_fields = _draw(
                backend, condition, masker, prompt, grammar, max_tokens, draw_seed, config.temperature)
        except BackendUnavailable:
            # A server hiccup (thermal-throttle stall, transient disconnect)
            # looks identical to a hard-down backend until a second attempt
            # also fails. One retry; a second failure propagates and `run`'s
            # abort path takes over.
            retried = True
            generation, mask_fields = _draw(
                backend, condition, masker, prompt, grammar, max_tokens, draw_seed, config.temperature)
        spent = max(1, int(generation.completion_tokens))
        used += spent
        source = extract_definition(generation.text)
        funnel = run_funnel(source, resolver)
        semantic = score_semantic(task, funnel, source)
        # Captured before `narrowing` is updated below, so this reflects what
        # was fed into *this* draw's prompt, not next draw's.
        narrowed = bool(narrowing)
        this_draw = draws
        draws += 1
        if condition == CONDITION_GBNF_REJECTION:
            narrowing = narrowing_note(funnel)
        stop_now = semantic.success and config.stop_on_semantic_success
        cell_done = stop_now or not (budget - used >= per_draw and draws < config.max_draws_per_task)
        record = {
            "task": task.task_id,
            "task_kind": task.kind,
            "condition": condition,
            "regime": regime,
            "address_book": config.address_book,
            "seed": seed,
            "draw": this_draw,
            "draw_seed": draw_seed,
            "narrowed": narrowed,
            "grammar": condition in GRAMMAR_CONDITIONS,
            "budget": budget,
            "tokens_completion": spent,
            "tokens_prompt": int(generation.prompt_tokens),
            "tokens_used": used,
            "tokens_remaining": max(0, budget - used),
            "latency_s": round(float(generation.latency_s), 6),
            "stop_reason": generation.stop_reason,
            "backend": generation.backend,
            "funnel_outcome": funnel.outcome,
            "layers_passed": funnel.layers_passed,
            "error_class": funnel.error_class,
            "error_path": funnel.error_path,
            "error_message": funnel.error_message,
            "de_bruijn_suspected": funnel.de_bruijn_suspected,
            "identity": funnel.identity,
            "type_surface": funnel.type_surface,
            "semantic_success": semantic.success,
            "semantic_rule": semantic.rule,
            "semantic_detail": semantic.detail,
            "rubric_pending": semantic.rubric_pending,
            "source": source,
            "raw": generation.text[: config.raw_text_limit],
            "retried": retried,
            "cell_done": cell_done,
            **mask_fields,
        }
        records.append(record)
        if sink is not None:
            sink(record)
        if stop_now:
            break
    return records


def _cell_key(record):
    """The identity of the (task, condition, regime, seed) cell a record belongs to."""
    return (record["task"], record["condition"], record["regime"], record["seed"])


def run(config: Config, resolver=None, backend=None, *, output_dir=None, fresh=False, log=None):
    """Run every configured cell and return `(records, summary)`.

    With no `output_dir` this is the original in-memory contract: everything
    lives in the returned lists, nothing touches disk. That is what the test
    suite calls directly, and it is unchanged on purpose.

    With `output_dir` given (the CLI's path, via `main`), the run is
    crash-safe:

    - Every draw's record is appended to `<output_dir>/records.jsonl` the
      moment it is built (`run_task`'s `sink`), flushed per write, so a crash
      loses at most the one draw in flight.
    - A `BackendUnavailable` or `KeyboardInterrupt` from the cell loop writes
      `summary.json` and `report.md` for whatever cells finished, then
      re-raises with a "partial run: N of M cells" message instead of dying
      silently.
    - **Resume**: if `records.jsonl` already exists and `fresh` is not set,
      records belonging to a cell whose final draw carries `cell_done: true`
      are loaded and that cell is skipped; anything else on disk is a stale
      partial cell (cut off mid-draw) and is discarded and rerun from draw 0,
      so a resumed run never ends up with duplicate draw records for one
      cell. `fresh=True` (the CLI's `--fresh`) discards the file outright
      instead of resuming from it.
    """
    resolver = resolver or make_resolver(config)
    backend = backend or make_backend(config)
    grammar = grammar_text()
    masker = (make_masker(config, backend, resolver)
              if CONDITION_TYPEMASK in config.conditions else None)
    log = log or (lambda message: print(message, file=sys.stderr))

    records: list[dict] = []
    completed_cells: set[tuple] = set()
    directory = None
    records_path = None
    sink = None
    if output_dir is not None:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        records_path = directory / "records.jsonl"
        if records_path.exists() and not fresh:
            existing = [
                json.loads(line)
                for line in records_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            completed_cells = {_cell_key(r) for r in existing if r.get("cell_done")}
            records = [r for r in existing if _cell_key(r) in completed_cells]
            if completed_cells:
                log(f"resuming: skipping {len(completed_cells)} completed cells")
        # Rewrite clean: drops any partial residue from a cell that was cut
        # off mid-draw last time, so rerunning that cell below never
        # duplicates draw records on disk.
        with records_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

        def sink(record, _path=records_path):
            records.append(record)
            with _path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()

    started = time.monotonic()
    cells = []
    for regime in config.regimes:
        tasks = _select_tasks(config, regime)
        for condition in config.conditions:
            for seed in config.seeds:
                for task in tasks:
                    cells.append((regime, condition, seed, task))
    total = len(cells)
    done = len(completed_cells)
    try:
        for regime, condition, seed, task in cells:
            key = (task.task_id, condition, regime, seed)
            if key in completed_cells:
                continue
            result = run_task(
                task, condition, regime, seed, backend, resolver, config, grammar,
                masker=masker, sink=sink)
            if sink is None:
                records.extend(result)
            done += 1
    except (BackendUnavailable, KeyboardInterrupt) as error:
        message = f"partial run: {done} of {total} cells completed before aborting ({error})"
        if directory is not None:
            summary = summarize(records, config, resolver, time.monotonic() - started)
            write_outputs(records, summary, directory)
            log(f"{message} — records, summary and report written to {directory}")
        raise type(error)(message) from error
    summary = summarize(records, config, resolver, time.monotonic() - started)
    if directory is not None:
        write_outputs(records, summary, directory)
    return records, summary


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def _cells(records):
    """Group by (condition, regime); the unit every R3 metric is reported over."""
    grouped = {}
    for record in records:
        grouped.setdefault((record["condition"], record["regime"]), []).append(record)
    return grouped


def _mask_metrics(rows):
    """R3's per-cell masking numbers, or `{}` when the cell did not mask.

    Returning `{}` is what keeps a Phase A summary byte-identical to what it was
    before condition 4 existed: no masked draw, no key, no report section.
    """
    masked = [row for row in rows if row.get("mask")]
    if not masked:
        return {}
    steps = sum(row.get("mask_steps", 0) for row in masked)
    seconds = sum(row.get("mask_seconds", 0.0) for row in masked)
    decode = sum(row["latency_s"] for row in masked)
    pruned: dict[str, int] = {}
    layer_seconds: dict[str, float] = {}
    calls: dict[str, int] = {}
    for row in masked:
        for layer, count in row.get("mask_pruned_by_layer", {}).items():
            pruned[layer] = pruned.get(layer, 0) + count
        for layer, value in row.get("mask_seconds_by_layer", {}).items():
            layer_seconds[layer] = layer_seconds.get(layer, 0.0) + value
        for layer, count in row.get("mask_calls_by_layer", {}).items():
            calls[layer] = calls.get(layer, 0) + count
    return {
        "draws": len(masked),
        "mask_steps": steps,
        "mask_seconds": round(seconds, 6),
        "mask_seconds_per_token": round(seconds / steps, 9) if steps else 0.0,
        "mask_seconds_per_token_uncached": (
            round(statistics.fmean(
                [row["mask_seconds_per_token_uncached"] for row in masked
                 if row.get("mask_seconds_per_token_uncached")]), 9)
            if any(row.get("mask_seconds_per_token_uncached") for row in masked) else 0.0),
        # R3's headline for the masking-overhead Watch item: what share of the
        # wall clock of a masked draw the mask itself accounts for.
        "mask_share_of_draw_latency": round(seconds / decode, 4) if decode else None,
        "pruned_by_layer": pruned,
        "seconds_by_layer": {layer: round(value, 6) for layer, value in layer_seconds.items()},
        "calls_by_layer": calls,
        "fallbacks": sum(row.get("mask_fallbacks", 0) for row in masked),
        "pruners_enabled": sorted({
            name for row in masked for name in row.get("mask_pruners_enabled", [])}),
        "vocab_size": max(row.get("mask_vocab_size", 0) for row in masked),
    }


def _cell_metrics(rows):
    tokens = sum(row["tokens_completion"] for row in rows)
    accepted = [row for row in rows if row["funnel_outcome"] == ACCEPTED]
    tally = FunnelTally()
    for row in rows:
        tally.add(row["funnel_outcome"])
    attempts = {}
    for row in rows:
        attempts.setdefault((row["task"], row["seed"]), []).append(row)
    solved = [key for key, draws in attempts.items() if any(d["semantic_success"] for d in draws)]
    first_success_tokens = []
    for key in solved:
        draws = sorted(attempts[key], key=lambda d: d["draw"])
        spent = 0
        for draw in draws:
            spent += draw["tokens_completion"]
            if draw["semantic_success"]:
                break
        first_success_tokens.append(spent)
    identities = [row["identity"] for row in accepted if row["identity"]]
    latencies = [row["latency_s"] for row in rows]
    masking = _mask_metrics(rows)
    return {
        **({"masking": masking} if masking else {}),
        "draws": len(rows),
        "attempts": len(attempts),
        "tokens": tokens,
        "accepted": len(accepted),
        "accepted_per_1k_tokens": round(1000 * len(accepted) / tokens, 3) if tokens else 0.0,
        "semantic_successes": len(solved),
        "semantic_success_rate": round(len(solved) / len(attempts), 4) if attempts else 0.0,
        "mean_tokens_to_first_success": (
            round(statistics.fmean(first_success_tokens), 1) if first_success_tokens else None),
        "mean_draws_per_attempt": round(len(rows) / len(attempts), 2) if attempts else 0.0,
        "redraws": len(rows) - len(attempts),
        "distinct_accepted_identities": len(set(identities)),
        "repeated_definition_rate": (
            round(1 - len(set(identities)) / len(identities), 4) if identities else 0.0),
        "mean_latency_s": round(statistics.fmean(latencies), 4) if latencies else 0.0,
        "total_latency_s": round(sum(latencies), 3),
        "funnel": dict(tally.counts),
        "rubric_pending": sum(1 for row in rows if row["rubric_pending"]),
    }


def _error_paths(rows, layer, limit=5):
    counts = {}
    for row in rows:
        if row["funnel_outcome"] == layer and row["error_path"]:
            counts[row["error_path"]] = counts.get(row["error_path"], 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def r5_comparison(cells, baseline_path):
    """R5, as a table: condition 4 against the conditions it has to beat.

    Phase A and Phase B are separate runs on separate transports, so the
    comparison cannot be read off one set of records. It is assembled here from
    this run's cells plus a **recorded** earlier summary, named in the config so
    the number's provenance travels with the result instead of being pasted in
    afterwards. Returns `None` when either half is missing.

    The measure is `accepted_per_1k_tokens`, which is R2's shared-budget rule
    and the one number that survives the R1 comparability boundary: both runs
    spend the same token purse per task, whatever the wall clock says.
    """
    masked = {
        key.split("|", 1)[1]: cell for key, cell in cells.items()
        if key.startswith(f"{CONDITION_TYPEMASK}|")}
    if not masked or not baseline_path:
        return None
    try:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"error": f"baseline summary {baseline_path} unreadable: {error}"}
    prior = baseline.get("cells", {})
    rows = []
    for regime in sorted(masked):
        cell = masked[regime]
        entry = {
            "regime": regime,
            CONDITION_TYPEMASK: cell["accepted_per_1k_tokens"],
            "masked_accepted": cell["accepted"],
            "masked_tokens": cell["tokens"],
        }
        for condition in GRAMMAR_CONDITIONS:
            found = prior.get(f"{condition}|{regime}")
            entry[condition] = found["accepted_per_1k_tokens"] if found else None
        bar = max((entry[c] for c in GRAMMAR_CONDITIONS if entry[c] is not None), default=None)
        entry["bar"] = bar
        entry["delta"] = round(entry[CONDITION_TYPEMASK] - bar, 3) if bar is not None else None
        rows.append(entry)
    comparable = [row for row in rows if row["delta"] is not None]
    return {
        "baseline_summary": str(baseline_path),
        "baseline_run": baseline.get("started_utc"),
        "baseline_backend": baseline.get("config", {}).get("backend"),
        "measure": "accepted_per_1k_tokens",
        "by_regime": rows,
        # Prediction 4 said rejection sampling would stay competitive with
        # masking. It is scored false only if masking beats the best Phase A
        # grammar condition in every regime the two runs share.
        "masking_beats_the_bar_everywhere": (
            all(row["delta"] > 0 for row in comparable) if comparable else None),
        "regimes_masking_wins": sum(1 for row in comparable if row["delta"] > 0),
        "regimes_compared": len(comparable),
    }


def summarize(records, config, resolver, elapsed_s):
    cells = {
        f"{condition}|{regime}": _cell_metrics(rows)
        for (condition, regime), rows in sorted(_cells(records).items())
    }
    grammar_rows = [r for r in records if r["condition"] in GRAMMAR_CONDITIONS]
    gate = {}
    for regime in config.regimes:
        rows = [r for r in grammar_rows if r["regime"] == regime]
        if rows:
            tally = FunnelTally()
            for row in rows:
                tally.add(row["funnel_outcome"])
            gate[regime] = dict(tally.counts)
    overall = FunnelTally()
    for row in grammar_rows:
        overall.add(row["funnel_outcome"])
    scope_rows = [r for r in grammar_rows if r["funnel_outcome"] == "scope"]
    masking = _mask_metrics(records)
    r5 = r5_comparison(cells, config.baseline_summary)
    return {
        **({"masking": masking} if masking else {}),
        **({"r5": r5} if r5 else {}),
        "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round(elapsed_s, 3),
        "config": {k: v for k, v in asdict(config).items() if k not in ("stub_outputs", "stub_grammar_outputs")},
        "sampling": config.sampling(),
        "contract_versions": dict(contracts.VERSIONS),
        "resolver_objects": resolver.counts(),
        # Which arm this was, from the resolver rather than from the config —
        # the config states an intent, this states what the run actually held.
        # Absent for the corpus-built resolver, which has no origins to count.
        **({"resolver_origins": resolver.origin_counts()}
           if hasattr(resolver, "origin_counts") else {}),
        "records": len(records),
        "cells": cells,
        "failure_distribution_by_layer": {
            "scope_note": "grammar-constrained draws only (conditions 2 and 3)",
            "by_regime": gate,
            "overall": dict(overall.counts),
        },
        "de_bruijn_share_of_scope_failures": (
            round(sum(1 for r in scope_rows if r["de_bruijn_suspected"]) / len(scope_rows), 4)
            if scope_rows else None),
        "error_paths": {
            layer: _error_paths(grammar_rows, layer) for layer in LAYERS
        },
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _render_masking(summary):
    """Phase B's section. Empty for a Phase A run, by construction."""
    masking = summary.get("masking")
    if not masking:
        return []
    out = [
        "",
        "## Masking overhead — condition 4 (R3)",
        "",
        "Comparability boundary (R1): condition 4 decodes on the in-process "
        "transport, conditions 1-3 on `llama-server`, so **wall clock is not "
        "comparable across that line**. The comparable numbers are accepted "
        "definitions per token (the budget rule) and the per-token mask "
        "overhead below, which is measured inside the masker.",
        "",
        f"**Masked draws:** {masking['draws']}  ",
        f"**Mask steps:** {masking['mask_steps']}  ",
        f"**Mask time:** {masking['mask_seconds']} s "
        f"({masking['mask_seconds_per_token']} s/token; "
        f"{masking['mask_seconds_per_token_uncached']} s/token uncached)  ",
        f"**Mask share of masked-draw latency:** {masking['mask_share_of_draw_latency']}  ",
        f"**Pruners enabled:** {', '.join(masking['pruners_enabled']) or '(none — syntax only)'}  ",
        f"**Vocabulary:** {masking['vocab_size']} tokens  ",
        f"**Liveness fallbacks:** {masking['fallbacks']} "
        "(steps where the type layer would have emptied a non-empty syntax mask)",
        "",
        "### Tokens pruned and time spent, by layer",
        "",
    ]
    layers = sorted(set(masking["pruned_by_layer"]) | set(masking["seconds_by_layer"]))
    rows = [[
        layer,
        masking["pruned_by_layer"].get(layer, 0),
        masking["calls_by_layer"].get(layer, 0),
        round(masking["seconds_by_layer"].get(layer, 0.0), 6),
    ] for layer in layers]
    out.append(_table(["layer", "tokens pruned", "evaluations", "seconds"], rows))
    out += [
        "",
        "Pruner seconds are *uncached* evaluation time — the marginal cost of "
        "the check. The combined transition and mask caches are part of the "
        "design, not an artefact of the measurement, and their hit rate is in "
        "the per-draw records.",
        "",
        "### Prediction 5 — is Python-side masking overhead material?",
        "",
        "Prediction 5 said masking overhead would be *material relative to "
        "local decode speed* but dominated by model latency. The share below is "
        "that number: mask time over total masked-draw latency, both measured "
        "on the same transport in the same process, so it is a like-for-like "
        "ratio rather than a cross-transport comparison.",
        "",
        f"- **Mask share of masked-draw latency: {masking['mask_share_of_draw_latency']}** "
        "— the figure to score against.",
        f"- Warm: {masking['mask_seconds_per_token']} s/token. "
        f"Cold: {masking['mask_seconds_per_token_uncached']} s/token. "
        "Score against both; the caches are part of the design, so the warm "
        "number is what a run actually pays and the cold one bounds it.",
    ]
    return out


def _render_r5(summary):
    """R5's comparison, when the config recorded a baseline to compare against."""
    r5 = summary.get("r5")
    if not r5:
        return []
    if "error" in r5:
        return ["", "## R5 — condition 4 against conditions 2 and 3", "",
                f"Not computed: {r5['error']}", ""]
    out = [
        "",
        "## R5 — condition 4 against conditions 2 and 3",
        "",
        "The experiment's decisive comparison: does per-token type-directed "
        "masking produce more accepted definitions per token than "
        "definition-level rejection sampling? The measure is "
        f"`{r5['measure']}`, which is R2's shared-budget rule and the one "
        "number that survives R1's comparability boundary — both runs spend the "
        "same token purse per task whatever the wall clock says.",
        "",
        f"**Baseline:** `{r5['baseline_summary']}` "
        f"(run {r5['baseline_run']}, backend {r5['baseline_backend']})",
        "",
    ]
    rows = [[
        row["regime"],
        row[CONDITION_TYPEMASK],
        row[CONDITION_GBNF] if row[CONDITION_GBNF] is not None else "—",
        row[CONDITION_GBNF_REJECTION] if row[CONDITION_GBNF_REJECTION] is not None else "—",
        row["bar"] if row["bar"] is not None else "—",
        row["delta"] if row["delta"] is not None else "—",
        ("masking" if row["delta"] is not None and row["delta"] > 0
         else "baseline" if row["delta"] is not None else "—"),
    ] for row in r5["by_regime"]]
    out.append(_table(
        ["regime", "gbnf+typemask", "gbnf", "gbnf+rejection", "bar", "delta", "wins"], rows))
    verdict = r5["masking_beats_the_bar_everywhere"]
    out += [
        "",
        f"Masking beats the bar in {r5['regimes_masking_wins']} of "
        f"{r5['regimes_compared']} comparable regimes.",
        "",
        "**Prediction 4** said condition 3 would stay competitive with "
        "condition 4 — the honest prediction that threatens the masker. It is "
        + ("**false**: masking beats the best grammar condition in every "
           "comparable regime, so §8.2's complexity is carried by the numbers."
           if verdict is True else
           "**true or partial**: masking does not beat the best grammar "
           "condition everywhere, so the per-token masker is not paying for "
           "itself across the matrix on this measure."
           if verdict is False else
           "not scoreable: no regime had both halves of the comparison."),
        "",
    ]
    return out


def render_report(summary, records):
    config = summary["config"]
    masked = bool(summary.get("masking"))
    out = [
        "# Masked-generation experiment — "
        + ("Phase A results, with Phase B condition 4" if masked else "Phase A results"),
        "",
        f"**Run (UTC):** {summary['started_utc']}  ",
        f"**Backend:** {config['backend'] or '(none)'}  ",
        f"**Model identity:** {config['model_identity'] or '(not recorded — stub or dry run)'}  ",
        f"**Hardware:** {config['hardware'] or '(not recorded)'}  ",
        f"**Sampling:** {json.dumps(summary['sampling'], sort_keys=True)}  ",
        f"**Seeds:** {config['seeds']}  ",
        f"**Token budget per task:** {config['token_budget_per_task']} "
        f"(max {config['max_tokens_per_draw']} per draw, "
        f"max {config['max_draws_per_task']} draws)  ",
        f"**Leave-one-out examples:** {config['leave_one_out']}  ",
        f"**Address book:** {config.get('address_book', 'none')}  ",
        f"**Draws recorded:** {summary['records']} in {summary['elapsed_s']} s  ",
        f"**Resolver objects:** {json.dumps(summary['resolver_objects'], sort_keys=True)}  ",
        f"**Contract versions:** {json.dumps(summary['contract_versions'], sort_keys=True)}",
        "",
        ("Condition 4 (type-directed per-token masking) ran; its masking numbers "
         "are in their own section below. The failure-distribution gate stays a "
         "conditions-2-and-3 table by rule."
         if masked else
         "Conditions 1-3 only. Condition 4 (type-directed per-token masking) is "
         "Phase B and is gated on the failure distribution below."),
        "",
        "## R3 metrics per condition × regime",
        "",
    ]
    headers = [
        "condition", "regime", "attempts", "draws", "tokens", "accepted",
        "acc/1k tok", "semantic", "sem rate", "tok to 1st", "redraws",
        "distinct acc", "repeat rate", "mean lat s",
    ]
    rows = []
    for key, cell in summary["cells"].items():
        condition, regime = key.split("|", 1)
        rows.append([
            condition, regime, cell["attempts"], cell["draws"], cell["tokens"],
            cell["accepted"], cell["accepted_per_1k_tokens"], cell["semantic_successes"],
            cell["semantic_success_rate"],
            cell["mean_tokens_to_first_success"] if cell["mean_tokens_to_first_success"] is not None else "—",
            cell["redraws"], cell["distinct_accepted_identities"],
            cell["repeated_definition_rate"], cell["mean_latency_s"],
        ])
    out += [_table(headers, rows), "", "## Funnel outcome by condition × regime", ""]
    out += [_table(
        ["condition", "regime", *OUTCOMES],
        [
            [key.split("|")[0], key.split("|")[1], *[cell["funnel"].get(o, 0) for o in OUTCOMES]]
            for key, cell in summary["cells"].items()
        ],
    )]

    gate = summary["failure_distribution_by_layer"]
    out += [
        "",
        "## Failure distribution by checker layer — the Phase B gate",
        "",
        "Grammar-constrained draws only (conditions 2 and 3), which is what R2.1 "
        "asks for: Phase B prunes first whatever layer actually kills most "
        "GBNF-valid generations.",
        "",
    ]
    gate_rows = []
    for regime, counts in gate["by_regime"].items():
        total = sum(counts.values()) or 1
        gate_rows.append([
            regime,
            *[counts.get(o, 0) for o in OUTCOMES],
            f"{100 * (total - counts.get(ACCEPTED, 0)) / total:.1f}%",
        ])
    overall = gate["overall"]
    total = sum(overall.values()) or 1
    gate_rows.append([
        "**all**", *[overall.get(o, 0) for o in OUTCOMES],
        f"{100 * (total - overall.get(ACCEPTED, 0)) / total:.1f}%",
    ])
    out += [_table(["regime", *OUTCOMES, "reject rate"], gate_rows)]

    failing = {layer: overall.get(layer, 0) for layer in LAYERS}
    dominant = max(failing, key=lambda layer: failing[layer]) if any(failing.values()) else None
    out += [
        "",
        (f"**Dominant post-syntax failure layer:** `{dominant}` "
         f"({failing[dominant]} of {total} grammar-constrained draws; ties break "
         "in funnel order, so read the row above before acting on a close call). "
         "This is the layer Phase B's incremental type-state masker prunes first."
         if dominant else
         "**No grammar-constrained rejections recorded.**"),
        "",
        f"De Bruijn share of scope failures (heuristic, message-based): "
        f"{summary['de_bruijn_share_of_scope_failures']}",
        "",
        "## Error localization — most frequent failing paths",
        "",
    ]
    for layer in LAYERS:
        paths = summary["error_paths"][layer]
        if paths:
            out.append(f"**{layer}** — " + ", ".join(f"`{p}` ×{n}" for p, n in paths))
    out += _render_masking(summary)
    out += _render_r5(summary)
    out += [
        "",
        "## Outstanding by rule, not by omission",
        "",
        f"- R3's hand-scored rubric on held-out successes is outstanding for "
        f"{sum(c['rubric_pending'] for c in summary['cells'].values())} draws that met "
        "the mechanical floor. The metric is partly human and this line is what keeps "
        "it from being silently dropped.",
        ("- Prediction 5 is scored in the masking section above. Prediction 4 "
         "is scored in the R5 section above."
         if masked and summary.get("r5") and "error" not in summary["r5"] else
         "- Prediction 5 is scored in the masking section above. Prediction 4 "
         "needs a baseline to compare against: set `baseline_summary` in the "
         "run config to a Phase A `summary.json` and the R5 table appears here."
         if masked else
         "- Predictions 4 and 5 (rejection sampling versus masking, and masking "
         "overhead) cannot be scored from Phase A alone: both compare against "
         "condition 4."),
        "",
    ]
    return "\n".join(out) + "\n"


def write_outputs(records, summary, output_dir):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    records_path = directory / "records.jsonl"
    with records_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    summary_path = directory / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = directory / "report.md"
    report_path.write_text(render_report(summary, records), encoding="utf-8")
    return records_path, summary_path, report_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 -m experiment.runner",
        description=(
            "Masked-generation experiment: Phase A's conditions 1-3, and Phase "
            "B's condition 4 ('gbnf+typemask') when the config asks for it."))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to the run config JSON")
    parser.add_argument("--out", default="", help="output directory (overrides the config)")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the resolver, tasks and prompts, and report the plan without generating")
    parser.add_argument("--fresh", action="store_true",
                        help="ignore any records.jsonl already in the output dir and start clean "
                             "(without this, an existing records.jsonl resumes instead)")
    arguments = parser.parse_args(argv)

    config = Config.load(arguments.config)
    if arguments.out:
        config.output_dir = arguments.out

    resolver = make_resolver(config)
    if arguments.dry_run:
        cells = 0
        for regime in config.regimes:
            tasks = _select_tasks(config, regime)
            cells += len(tasks) * len(config.conditions) * len(config.seeds)
        print(f"config             : {config.source_path}")
        print(f"resolver objects   : {json.dumps(resolver.counts(), sort_keys=True)}")
        if hasattr(resolver, "origin_counts"):
            print(f"resolver origins   : {json.dumps(resolver.origin_counts(), sort_keys=True)}"
                  f"  (policy: {resolver.origin_policy})")
        print(f"regimes            : {', '.join(config.regimes)}")
        print(f"conditions         : {', '.join(config.conditions)}")
        print(f"seeds              : {config.seeds}")
        print(f"cells to run       : {cells}")
        print(f"token budget/task  : {config.token_budget_per_task}")
        print(f"upper bound tokens : {cells * config.token_budget_per_task}")
        return 0

    try:
        backend = make_backend(config)
    except BackendUnavailable as error:
        print(str(error), file=sys.stderr)
        return 2

    # `run` writes records.jsonl/summary.json/report.md itself when given an
    # output_dir — incrementally as draws complete, and one last time here on
    # a normal return — so a crash mid-matrix never loses a finished draw.
    try:
        records, summary = run(
            config, resolver=resolver, backend=backend,
            output_dir=config.output_dir, fresh=arguments.fresh)
    except BackendUnavailable as error:
        print(str(error), file=sys.stderr)
        return 2
    directory = Path(config.output_dir)
    records_path = directory / "records.jsonl"
    summary_path = directory / "summary.json"
    report_path = directory / "report.md"
    print(render_report(summary, records))
    print(f"records: {records_path}")
    print(f"summary: {summary_path}")
    print(f"report : {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
