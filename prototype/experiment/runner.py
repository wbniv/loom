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
import typecheck

from .backends import NO_MASK_BACKEND_MESSAGE, BackendUnavailable, grammar_text, make_backend
from .evaluate import (
    ACCEPTED,
    LAYERS,
    OUTCOMES,
    FunnelTally,
    SemanticResult,
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
    GENERATION_PROTOCOLS,
    HOLE_BLOCK_CHECKER_HOLED,
    HOLE_BLOCK_PROTOCOL,
    HOLE_BLOCKS,
    KIND_CORPUS,
    KIND_HELD_OUT,
    PROTOCOL_HOLES,
    PROTOCOL_REDRAFT,
    PROTOCOL_WHOLE,
    REGIME_HELD_OUT,
    REGIMES,
    SpliceError,
    Task,
    all_tasks,
    bare_hole_body,
    build_fill_prompt,
    build_prompt,
    checker_holed_cut,
    closed_subtask_type,
    declared_type_of,
    hole_obligations,
    splice_fill,
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

#: What a record is, under the 2026-08-25 hole-decomposition plan §2.2. Three
#: of the four are **draws** — one backend call each, one full-cap grant each,
#: against the same per-cell purse; the fourth is the round's *candidate*, the
#: assembled definition §4.5 scores, which costs no tokens because the model
#: never wrote it in one piece.
ROLE_WHOLE = "whole"
ROLE_SKELETON = "skeleton"
ROLE_FILL = "fill"
ROLE_CANDIDATE = "candidate"

#: The roles that cost a draw. Everything in the summary that is *per draw* —
#: tokens, acc/1k, the funnel tally, latency — is computed over these alone, so
#: a zero-token assembly record can never inflate a rate.
DRAW_ROLES = (ROLE_WHOLE, ROLE_SKELETON, ROLE_FILL)

#: Why a splice did not land, recorded per fill draw (§4.6's protocol telemetry).
SPLICE_SPLICED = "spliced"
SPLICE_ROLLED_BACK = "rolled-back"
SPLICE_ERROR = "splice-error"
SPLICE_FILL_REJECTED = "fill-rejected"

#: The 2026-08-26 hole-elicitation plan §2.1's fill gate. `"accepted"` is the
#: pre-existing rule: a skeleton's holes are only eligible for a fill once the
#: draft itself has cleared all four funnel layers. `"well-scoped"` is row 4's
#: relaxation, discharged exactly: parse, scope and references must pass —
#: typecheck need not — because those three layers are what `closed_subtask_type`
#: and `splice_fill`'s de Bruijn alignment claim depend on (§2.1's table).
FILL_GATE_ACCEPTED = "accepted"
FILL_GATE_WELL_SCOPED = "well-scoped"
FILL_GATES = (FILL_GATE_ACCEPTED, FILL_GATE_WELL_SCOPED)

#: A fill definition is not a candidate — §4.5 scores the round's final draft,
#: and only that. Scoring the fill against the *task* would double-count the
#: degenerate case where a hole's closed type is the task's declared type, so
#: the fill record carries this verdict instead of a task-level one.
_FILL_SEMANTIC = SemanticResult(
    success=False,
    rule="fill-draw",
    detail="a fill definition is not a candidate; the round's final draft is",
    rubric_pending=False,
)

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
    #: The 2026-08-25 hole-decomposition plan §4.2's manipulated variable.
    #: `"whole"` is today's protocol — independent draws, no feedback — and is
    #: the default, so every config written before this field existed runs byte
    #: for byte what it ran. `"redraft"` adds §8.3 narrowing on rejection and
    #: nothing else; `"holes"` adds §2.2's round protocol on top of that, so
    #: `holes − redraft` is the hole protocol alone.
    generation_protocol: str = PROTOCOL_WHOLE
    #: §4.3.6's protocol constants, fixed by the plan before any run. They are
    #: config fields rather than module constants so a dry-run check can drive
    #: the round to its limits without editing the harness; the arms ship
    #: without them and get exactly these values.
    fills_per_round_max: int = 6
    fill_attempts_per_hole: int = 2
    #: The 2026-08-26 hole-elicitation plan §2.1's fill gate: `"accepted"` (the
    #: pre-existing rule) or `"well-scoped"` (row 4's relaxation). Defaults to
    #: `"accepted"` so every config written before this field existed runs byte
    #: for byte what it ran. Under `"well-scoped"`, a relaxed-gate round — one
    #: whose skeleton was *not* funnel-accepted — is capped at one fill draw
    #: per hole and one hole per round (§2.1 consequence 4), overriding
    #: `fills_per_round_max` / `fill_attempts_per_hole` for that round only; an
    #: accepted draft keeps those constants exactly as before.
    fill_gate: str = FILL_GATE_ACCEPTED
    #: The 2026-08-26 hole-elicitation plan §2.2 B2 (`hole-required`): for the
    #: first `hole_required_rounds` rounds of a cell, a round whose draft
    #: carried no hole at all — or nothing but a bare one (§3's rule) — gets
    #: the hole-demand note appended to, never substituted for, that round's
    #: §8.3 narrowing note. `0` (default) means every config written before
    #: this field existed runs byte for byte what it ran; the pilot's B2 arm
    #: is the only one that sets it, to `3`. Read only by the `holes`
    #: protocol's round loop — `whole` and `redraft` never see it.
    hole_required_rounds: int = 0
    #: The 2026-08-26 hole-elicitation plan §4.2's Stage-0 manipulated
    #: variable: which candidate block a `holes`-arm cell runs. `"§3-block"`
    #: is the banked block and the default, so every config written before
    #: this field existed runs byte for byte what it ran. `"exemplar"` is the
    #: only value that changes the *prompt*; `"checker-holed"` is B3, whose
    #: whole mechanism is `hole_at_error` seeding in the round loop below.
    #: Read only by the `holes` protocol — `whole` and `redraft` never see it.
    hole_block: str = HOLE_BLOCK_PROTOCOL
    #: The 2026-08-27 feedback-legibility plan §2.1's seam:
    #: `typecheck._render`/`_render_row`'s rendering of a type-IR node
    #: embedded in a `TypingError` message, which `evaluate.narrowing_note`
    #: relays to the model verbatim (§8.3). `"surface"` (default) is
    #: `8ed72cd`'s fix, so every config written before this field existed
    #: runs byte for byte what it ran. `"repr"` reconstructs the pre-`8ed72cd`
    #: rendering — the feedback-legibility arm's control condition — without
    #: a second checkout of `typecheck.py`.
    narrowing_note_render: str = typecheck.NARROWING_NOTE_SURFACE
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
        if self.generation_protocol not in GENERATION_PROTOCOLS:
            raise SystemExit(
                f"unknown generation_protocol {self.generation_protocol!r}; known "
                f"protocols: {', '.join(GENERATION_PROTOCOLS)}")
        if self.fills_per_round_max < 1 or self.fill_attempts_per_hole < 1:
            raise SystemExit(
                "fills_per_round_max and fill_attempts_per_hole must be positive; "
                "plan §4.3.6 fixes them at 6 and 2")
        if self.fill_gate not in FILL_GATES:
            raise SystemExit(
                f"unknown fill_gate {self.fill_gate!r}; known fill gates: "
                f"{', '.join(FILL_GATES)}")
        if self.hole_block not in HOLE_BLOCKS:
            raise SystemExit(
                f"unknown hole_block {self.hole_block!r}; known hole blocks: "
                f"{', '.join(HOLE_BLOCKS)}")
        if self.narrowing_note_render not in typecheck.NARROWING_NOTE_RENDERS:
            raise SystemExit(
                f"unknown narrowing_note_render {self.narrowing_note_render!r}; known "
                f"renders: {', '.join(typecheck.NARROWING_NOTE_RENDERS)}")
        if self.hole_required_rounds < 0:
            raise SystemExit(
                "hole_required_rounds must be >= 0; plan §2.2 B2's pilot arm "
                "sets it to 3")
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


@dataclass
class _DrawResult:
    """One granted, full-cap backend call and what came back from it."""

    generation: object
    mask_fields: dict
    retried: bool
    spent: int
    source: str
    funnel: object
    seed: int


class _CellRun:
    """One (task, condition, regime, seed) cell: its purse, its draws, its records.

    Every generation protocol shares this object, and that is what makes
    §4.3.2's budget rule protocol-neutral: a whole-term draw, a skeleton draw
    and a fill draw are the *same event* here — one full-cap grant charged to
    one per-cell purse. The purse binds, never the draw cap alone, and no draw
    is ever handed a leftover fragment.

    **Budget semantics** (plan `2026-08-24-next-lever` §4.3, fixing the §1.3
    defect, inviolable here): a draw is granted only while the *whole* per-draw
    cap still fits in the remaining budget, and every granted draw is allotted
    exactly `max_tokens_per_draw`. A truncated draw is then a genuine rejection
    rather than the thing that terminates the cell.

    `draws` counts backend calls — it is what `max_draws_per_task` caps and what
    the per-draw seed is derived from. `index` counts *records*, which for the
    `holes` protocol is larger, because each round emits a zero-token candidate
    record for the assembled definition §4.5 scores.
    """

    def __init__(self, task, condition, regime, seed, backend, resolver, config,
                 grammar, masker, sink):
        self.task = task
        self.condition = condition
        self.regime = regime
        self.seed = seed
        self.backend = backend
        self.resolver = resolver
        self.config = config
        self.grammar = grammar
        self.masker = masker
        self.sink = sink
        self.records: list[dict] = []
        self.used = 0
        self.draws = 0
        self.index = 0

    @property
    def budget(self):
        return self.config.token_budget_per_task

    @property
    def per_draw(self):
        return self.config.max_tokens_per_draw

    def can_draw(self):
        """Is there room for one more *whole*-cap draw, under both caps?"""
        return (self.budget - self.used >= self.per_draw
                and self.draws < self.config.max_draws_per_task)

    def draw(self, prompt) -> _DrawResult:
        """Spend one full-cap draw on `prompt`. The caller has checked `can_draw`."""
        # The seed varies per draw or every redraw repeats the first draw
        # exactly; the derivation is deterministic so the run still reproduces.
        draw_seed = self.seed * 100_003 + self.draws
        retried = False
        try:
            generation, mask_fields = _draw(
                self.backend, self.condition, self.masker, prompt, self.grammar,
                self.per_draw, draw_seed, self.config.temperature)
        except BackendUnavailable:
            # A server hiccup (thermal-throttle stall, transient disconnect)
            # looks identical to a hard-down backend until a second attempt
            # also fails. One retry; a second failure propagates and `run`'s
            # abort path takes over.
            retried = True
            generation, mask_fields = _draw(
                self.backend, self.condition, self.masker, prompt, self.grammar,
                self.per_draw, draw_seed, self.config.temperature)
        spent = max(1, int(generation.completion_tokens))
        self.used += spent
        self.draws += 1
        source = extract_definition(generation.text)
        return _DrawResult(
            generation=generation, mask_fields=mask_fields, retried=retried,
            spent=spent, source=source, funnel=run_funnel(source, self.resolver),
            seed=draw_seed)

    def emit(self, *, role, round_index, narrowed, source, funnel, semantic,
             cell_done, candidate, draw=None, extra=None):
        """Build one JSONL record, hand it to the sink, and keep it.

        `draw=None` is the round-candidate record: an assembled definition the
        model never wrote in one piece, so it has no generation behind it and
        costs no tokens. Everything else is a draw.
        """
        generation = draw.generation if draw is not None else None
        record = {
            "task": self.task.task_id,
            "task_kind": self.task.kind,
            "condition": self.condition,
            "regime": self.regime,
            "address_book": self.config.address_book,
            "seed": self.seed,
            "draw": self.index,
            "draw_seed": draw.seed if draw is not None else -1,
            "narrowed": narrowed,
            "grammar": self.condition in GRAMMAR_CONDITIONS,
            "budget": self.budget,
            "tokens_completion": draw.spent if draw is not None else 0,
            "tokens_prompt": int(generation.prompt_tokens) if generation is not None else 0,
            "tokens_used": self.used,
            "tokens_remaining": max(0, self.budget - self.used),
            "latency_s": round(float(generation.latency_s), 6) if generation is not None else 0.0,
            "stop_reason": generation.stop_reason if generation is not None else "assembled",
            "backend": generation.backend if generation is not None else "harness",
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
            "raw": generation.text[: self.config.raw_text_limit] if generation is not None else "",
            "retried": draw.retried if draw is not None else False,
            "cell_done": cell_done,
            # -- protocol telemetry (§4.6), additive: every field above is
            # exactly what it was before decomposition existed.
            "generation_protocol": self.config.generation_protocol,
            "fill_gate": self.config.fill_gate,
            "hole_required_rounds": self.config.hole_required_rounds,
            # §4.2's Stage-0 arm label. On *every* record, not just the
            # skeleton ones, because E1 (fill-reaching draw rate) and E2
            # (assembly liveness) are per-block rates whose numerator lives on
            # fill records and whose denominator lives on skeleton records —
            # a pooled pilot `records.jsonl` has to partition on one field.
            "hole_block": self.config.hole_block,
            "role": role,
            "round": round_index,
            "candidate": candidate,
            **(draw.mask_fields if draw is not None else {}),
            **(extra or {}),
        }
        self.index += 1
        self.records.append(record)
        if self.sink is not None:
            self.sink(record)
        return record


def _narrows(config, condition):
    """Does a rejected draw feed its error back into the next prompt?

    Two independent reasons it might: Phase A's condition 3, which *is*
    definition-level narrowing; and plan §4.2's `redraft` / `holes` arms, which
    add it under any condition (the arms run `gbnf+typemask`, where §8.3
    narrowing had never been run). `whole` under any condition but 3 is
    unnarrowed, which is what keeps the control arm today's control arm.
    """
    return (condition == CONDITION_GBNF_REJECTION
            or config.generation_protocol in (PROTOCOL_REDRAFT, PROTOCOL_HOLES))


def _hole_census(source, resolver):
    """`(obligations, telemetry)` for one definition, tolerant of a broken draw.

    A draw rejected at the syntax layer has no IR to walk, so the census is
    `0 holes` rather than an exception — the record still has to be written.
    """
    try:
        obligations = hole_obligations(source, resolver)
    except Exception:  # noqa: BLE001 - an unparseable draw is data, not a crash
        return (), {"holes": 0, "holes_fillable": 0, "hole_reasons": []}
    reasons = []
    for obligation in obligations:
        if not obligation.fillable and obligation.reason not in reasons:
            reasons.append(obligation.reason)
    return obligations, {
        "holes": len(obligations),
        "holes_fillable": sum(1 for o in obligations if o.fillable),
        "hole_reasons": reasons,
    }


def _is_bare_hole(source):
    """§3's enforced rule, tolerant of a draw that does not parse."""
    try:
        return bare_hole_body(source)
    except Exception:  # noqa: BLE001 - same reason as `_hole_census`
        return False


def _fill_admitted(config, funnel, bare):
    """The 2026-08-26 plan §2.1 gate: may this skeleton's holes reach a fill?

    `"accepted"` (default) is exactly the pre-existing rule, byte for byte:
    `funnel.accepted and not bare`. `"well-scoped"` admits any draft that
    reached the typecheck layer — `layers_passed >= 3` means parse, scope and
    references all passed, whatever order the funnel ran them in, whether or
    not typecheck itself then rejected the draft — subject to §3's bare-hole
    rule, which the caller must have evaluated *unconditionally* (not gated on
    `funnel.accepted`) for this to be the check §2.1 consequence 1 requires.
    """
    if config.fill_gate == FILL_GATE_WELL_SCOPED:
        return funnel.layers_passed >= 3 and not bare
    return funnel.accepted and not bare


#: A splice refusal, in `narrowing_note`'s own shape so the fill retry reads
#: like every other §8.3 note the model has seen.
def _splice_narrowing(message):
    return (f"The previous answer could not be spliced back at the hole: {message}\n"
            "Write a different definition that avoids this.")


#: The monotonicity refusal. §2.2's draft is monotone — "holes only ever
#: disappear" — so a fill whose own body is hole-bearing is rolled back rather
#: than spliced, which is also what stops a round from filling a hole with
#: itself forever.
MONOTONE_NOTE = (
    "The previous answer put another hole where the hole was, so the draft did "
    "not shrink.\nWrite a different definition that avoids this."
)


#: The 2026-08-26 plan §2.2 B2 (`hole-required`) hole-demand note, verbatim.
#: Appended to — never substituted for — the round's §8.3 narrowing note for
#: the first `config.hole_required_rounds` rounds of a cell, whenever that
#: round's draft carried no hole at all or nothing but a bare one. Protocol
#: enforcement, not persuasion: the same move the bare-hole rule already makes
#: for §3's other sentence, applied here to its first one.
HOLE_REQUIRED_NOTE = (
    "The previous answer had no `(hole GOALTYPE ())` in it. Write the same "
    "definition again, but replace the one subterm you are least sure of with "
    "`(hole GOALTYPE ())`, where GOALTYPE is the type that subterm must have."
)


def _with_hole_required_note(narrowing, round_index, draft, census, config):
    """§2.2 B2: append the hole-demand note when this round earns one.

    Earns one iff three things all hold: the arm actually enforces it
    (`hole_required_rounds > 0`), this round is inside the enforced window
    (`round_index < hole_required_rounds` — the round that just ran, so the
    note lands in the *next* round's prompt and the window closes exactly
    after `hole_required_rounds` rounds), and the draft just drawn carried no
    hole at all or nothing but a bare one. The bare-hole check is the same
    structural rule §3 already enforces (`_is_bare_hole`), evaluated here
    unconditionally — independent of `config.fill_gate` — because eliciting a
    hole and admitting one to a fill are different questions.

    Appended, never substituted: `narrowing_note`'s own text (or the empty
    string, on an accepted draft) survives untouched, with the demand note on
    its own line after it.
    """
    if not (config.hole_required_rounds and round_index < config.hole_required_rounds):
        return narrowing, False
    if census["holes"] > 0 and not _is_bare_hole(draft):
        return narrowing, False
    combined = f"{narrowing}\n{HOLE_REQUIRED_NOTE}" if narrowing else HOLE_REQUIRED_NOTE
    return combined, True


#: The `checker-holed` telemetry every skeleton record carries, at its inert
#: value. Written on every arm — not just B3 — so a pooled pilot
#: `records.jsonl` has one record shape and §4.6's per-block accounting is a
#: partition rather than a join.
_CHECKER_HOLED_INERT = {
    "checker_holed_eligible": False,
    "checker_holed": False,
    "checker_holed_reason": "",
    "checker_holed_path": "",
    "checker_holed_goal": "",
    "checker_holed_outcome": "",
    "checker_holed_source": "",
}


def _checker_holed_seed(config, draft, funnel, resolver):
    """§2.2 B3: the round's `hole_at_error` seed, and its telemetry.

    Returns `(seed_source, fields)`, with `seed_source` empty on every arm but
    `checker-holed` and on every B3 round whose draft the typecheck layer did
    not reject. Three conditions gate it and all three are necessary:

    * the arm is B3. Nothing else in the harness reads `hole_at_error`, so
      every other block's round is byte-identical to what it was;
    * the draft was rejected **at typecheck**. A parse/scope/references
      rejection has no meaningful error path into a term (§2.1's table says
      why those three layers block a fill at all), and an accepted draft has
      no failing node to walk up from;
    * `hole_at_error` found an ancestor to cut at. It refuses far more often
      than it cuts, which is the point (§2.2, §4.7 check 10).

    The seeded draft is **not** waved past the fill gate: the caller re-runs
    the funnel on it and applies `_fill_admitted` exactly as it would to a
    draft the model wrote. A cut often repairs the typecheck failure outright
    — a hole inhabits its goal type by fiat (SPEC §2.6), so the error it
    replaced is gone — and such a seed is admitted by the `"accepted"` gate on
    its own merits rather than by exemption.
    """
    if config.hole_block != HOLE_BLOCK_CHECKER_HOLED:
        return "", dict(_CHECKER_HOLED_INERT)
    if funnel.outcome != "typecheck":
        return "", dict(_CHECKER_HOLED_INERT)
    cut = checker_holed_cut(draft, funnel.error_path, resolver)
    fields = dict(_CHECKER_HOLED_INERT, checker_holed_eligible=True)
    if not cut.source:
        fields["checker_holed_reason"] = cut.reason
        return "", fields
    seeded_funnel = run_funnel(cut.source, resolver)
    fields.update({
        "checker_holed": True,
        "checker_holed_path": ".".join(str(step) for step in cut.path),
        "checker_holed_goal": cut.goal_surface,
        "checker_holed_outcome": seeded_funnel.outcome,
        "checker_holed_source": cut.source,
    })
    return cut.source, fields


def _run_whole_protocol(cell):
    """`whole` and `redraft`: one draw is one candidate (§4.2).

    Byte for byte today's loop. `redraft` differs from `whole` in exactly one
    place — `_narrows` — and in nothing else, which is what makes draw 0 of
    every cell identical across the two arms.
    """
    config = cell.config
    narrowing = ""
    while cell.can_draw():
        prompt = build_prompt(
            cell.task, cell.regime, cell.resolver,
            leave_one_out=config.leave_one_out,
            narrowing=narrowing,
            address_book=config.address_book,
            generation_protocol=config.generation_protocol,
        )
        # Captured before `narrowing` is updated below, so this reflects what
        # was fed into *this* draw's prompt, not next draw's.
        narrowed = bool(narrowing)
        round_index = cell.index
        draw = cell.draw(prompt)
        semantic = score_semantic(cell.task, draw.funnel, draw.source)
        if _narrows(config, cell.condition):
            narrowing = narrowing_note(draw.funnel)
        stop_now = semantic.success and config.stop_on_semantic_success
        _, census = _hole_census(draw.source, cell.resolver)
        cell.emit(
            role=ROLE_WHOLE, round_index=round_index, narrowed=narrowed,
            source=draw.source, funnel=draw.funnel, semantic=semantic,
            cell_done=stop_now or not cell.can_draw(), candidate=True,
            draw=draw, extra=census)
        if stop_now:
            break


def _fill_the_holes(cell, round_index, draft, funnel, *,
                     fills_per_round_max=None, fill_attempts_per_hole=None):
    """§2.2 steps 3-6, run until the round ends. Returns the round's draft.

    One hole at a time, always the first fillable one in pre-order, up to
    `fills_per_round_max` of them. Each hole gets up to `fill_attempts_per_hole`
    draws, the failure of each fed back as the next attempt's narrowing note.
    A hole that is never filled ends the round — the draft keeps its holes and
    is scored as it stands.

    `fills_per_round_max` / `fill_attempts_per_hole` default to the config's
    §4.3.6 constants (6 and 2). The caller overrides both to 1 for a
    relaxed-gate round — §2.1 consequence 4 — without touching the config
    object every other round in the cell still reads.

    Three things roll a splice back, and the last two are the runner's job
    because `splice_fill` is a pure function that cannot know the round:

    * the assembled definition fails `run_funnel` — §2.2's re-check, and the
      *authority*, since step 4's closure is deliberately a heuristic;
    * the assembled definition has no fewer holes than the draft did, i.e. the
      fill filled a hole with a hole. §2.2's monotonicity ("holes only ever
      disappear") is stated as a property of the protocol, so it is enforced
      here rather than assumed;
    * `splice_fill` itself refuses (`SpliceError`) — a fill that did not open
      with the hole's own binders, whose de Bruijn indices would therefore mean
      something else once moved.

    Nothing is scored until the *assembled* definition has been through all four
    funnel layers, so an over-permissive closure costs a rolled-back splice and
    can never produce a false success.
    """
    config = cell.config
    resolver = cell.resolver
    max_fills = (config.fills_per_round_max if fills_per_round_max is None
                 else fills_per_round_max)
    max_attempts = (config.fill_attempts_per_hole if fill_attempts_per_hole is None
                    else fill_attempts_per_hole)
    attempted = spliced = rolled_back = 0
    fills = 0
    while fills < max_fills and cell.can_draw():
        obligations = hole_obligations(draft, resolver)
        fillable = [o for o in obligations if o.fillable]
        if not fillable:
            # No holes left, or every one left is a `match`/`handle` binder v1
            # cannot type. Either way the round is over and the draft stands.
            break
        obligation = fillable[0]
        closed = closed_subtask_type(declared_type_of(draft), obligation)
        note = ""
        landed = False
        for attempt in range(max_attempts):
            if not cell.can_draw():
                break
            prompt = build_fill_prompt(
                cell.task.spec, cell.regime, resolver,
                draft_source=draft, obligation=obligation,
                narrowing=note, address_book=config.address_book,
                exclude_identity=(cell.task.expected_identity
                                  if config.leave_one_out else ""))
            narrowed = bool(note)
            draw = cell.draw(prompt)
            attempted += 1
            assembled = ""
            assembled_funnel = None
            remaining = len(obligations)
            if not draw.funnel.accepted:
                outcome = SPLICE_FILL_REJECTED
                note = narrowing_note(draw.funnel)
            else:
                try:
                    assembled = splice_fill(draft, obligation, draw.source)
                except SpliceError as error:
                    outcome = SPLICE_ERROR
                    note = _splice_narrowing(str(error))
                else:
                    assembled_funnel = run_funnel(assembled, resolver)
                    remaining = len(hole_obligations(assembled, resolver))
                    if not assembled_funnel.accepted:
                        outcome = SPLICE_ROLLED_BACK
                        rolled_back += 1
                        note = narrowing_note(assembled_funnel)
                    elif remaining >= len(obligations):
                        outcome = SPLICE_ROLLED_BACK
                        rolled_back += 1
                        note = MONOTONE_NOTE
                    else:
                        outcome = SPLICE_SPLICED
                        spliced += 1
                        landed = True
            _, census = _hole_census(draw.source, resolver)
            cell.emit(
                role=ROLE_FILL, round_index=round_index, narrowed=narrowed,
                source=draw.source, funnel=draw.funnel, semantic=_FILL_SEMANTIC,
                cell_done=False, candidate=False, draw=draw,
                extra={
                    **census,
                    "fill_index": fills,
                    "fill_attempt": attempt,
                    "hole_path": ".".join(str(step) for step in obligation.path),
                    "hole_goal": obligation.goal_surface,
                    "hole_binders": len(obligation.binders),
                    "closed_type": closed,
                    "splice_outcome": outcome,
                    "assembled_outcome": (
                        assembled_funnel.outcome if assembled_funnel is not None else ""),
                    "assembled_error": (
                        assembled_funnel.error_message or ""
                        if assembled_funnel is not None else ""),
                    "draft_holes_before": len(obligations),
                    "draft_holes_after": remaining if landed else len(obligations),
                })
            if landed:
                draft = assembled
                funnel = assembled_funnel
                fills += 1
                break
        if not landed:
            # `fill_attempts_per_hole` spent on this hole, or the purse ran out
            # mid-hole. Either ends the round (§2.2 step 6).
            break
    return draft, funnel, attempted, spliced, rolled_back


def _run_holes_protocol(cell):
    """`holes`: §2.2's round, run until the purse is spent.

    One round is: a skeleton draw, a check, and — only if the draft clears the
    §2.1 fill gate (`config.fill_gate`) and its body is not a bare hole (§3,
    enforced unconditionally) — obligation enumeration, closure, fill draws,
    splice and re-check, until no fillable hole is left or a hole cannot be
    filled. Under the default `"accepted"` gate that is exactly "funnel-accepted
    and not bare", byte for byte what this loop always did; under
    `"well-scoped"` a draft that reached the typecheck layer but was rejected
    there is admitted too, at the §2.1 consequence 4 caps. The round's
    candidate is its final draft, emitted as its own zero-token record and
    scored by the same `run_funnel` + `score_semantic` every other arm's
    candidates are scored by.

    The three protocols degenerate cleanly, and the loop shows it: a draft with
    no hole makes this `redraft`, and a run with no rejection makes that
    `whole`.
    """
    config = cell.config
    narrowing = ""
    round_index = 0
    while cell.can_draw():
        prompt = build_prompt(
            cell.task, cell.regime, cell.resolver,
            leave_one_out=config.leave_one_out,
            narrowing=narrowing,
            address_book=config.address_book,
            generation_protocol=PROTOCOL_HOLES,
            hole_block=config.hole_block,
        )
        narrowed = bool(narrowing)
        draw = cell.draw(prompt)
        draft, funnel = draw.source, draw.funnel
        # Narrowing is a property of the *skeleton*: a rejected draft is fed
        # back to the next round. A fill's failures narrow the fill, not the
        # round after it.
        narrowing = narrowing_note(funnel)
        _, census = _hole_census(draft, cell.resolver)
        if config.fill_gate == FILL_GATE_WELL_SCOPED:
            # §2.1 consequence 1: once the gate can admit a draft the funnel
            # rejected, `funnel.accepted and _is_bare_hole(draft)` is a hole in
            # the guard — every rejected draft would carry `False` whatever its
            # shape. Evaluated unconditionally instead.
            bare = _is_bare_hole(draft)
        else:
            bare = funnel.accepted and _is_bare_hole(draft)
        # §2.2 B2: computed from *this* draft, so it lands in the *next*
        # round's prompt — same handoff point as `narrowing_note` above, and
        # independent of the fill gate (a hole can be demanded whether or not
        # this draft's holes, if any, ever reach a fill).
        narrowing, hole_required_note_added = _with_hole_required_note(
            narrowing, round_index, draft, census, config)
        # §2.2 B3, computed here so its telemetry rides the skeleton record —
        # but *after* B2's note, which asks the model for a hole and must not
        # be silenced by the harness having inserted one. Whether the round
        # was a relaxed one is a property of the draft the model wrote, so it
        # is captured before the seed can replace it (§2.1 consequence 4).
        skeleton_accepted = funnel.accepted
        seed, checker_holed_fields = _checker_holed_seed(
            config, draft, funnel, cell.resolver)
        cell.emit(
            role=ROLE_SKELETON, round_index=round_index, narrowed=narrowed,
            source=draft, funnel=funnel,
            semantic=score_semantic(cell.task, funnel, draft),
            cell_done=False, candidate=False, draw=draw,
            extra={**census, "bare_hole_body": bare,
                   "hole_required_note_added": hole_required_note_added,
                   **checker_holed_fields})
        if seed:
            # "Send the repaired draft straight to the fill path" (§2.2 B3).
            # Straight to the *path*, not past the *gate*: the seed is
            # re-checked and re-judged below by the same two rules — the §2.1
            # gate and §3's bare-hole rule — every other draft is judged by.
            # The skeleton record above still reports what the model wrote,
            # which is what it is answerable for.
            draft = seed
            funnel = run_funnel(draft, cell.resolver)
            bare = _is_bare_hole(draft)

        attempted = spliced = rolled_back = 0
        if _fill_admitted(config, funnel, bare):
            # §2.1 consequence 4: a draft the well-scoped gate admits but the
            # funnel did not accept is a *relaxed-gate* round — capped at one
            # fill draw for one hole. An accepted draft (both gates, always
            # under the default) keeps §4.3.6's constants unchanged. A B3 seed
            # is judged by the *model's* draft here: a cut that repaired the
            # typecheck error does not turn a rejected round into a full-purse
            # one, or the harness would be buying itself fill draws.
            relaxed_round = not skeleton_accepted
            draft, funnel, attempted, spliced, rolled_back = _fill_the_holes(
                cell, round_index, draft, funnel,
                fills_per_round_max=1 if relaxed_round else None,
                fill_attempts_per_hole=1 if relaxed_round else None)

        semantic = score_semantic(cell.task, funnel, draft)
        stop_now = semantic.success and config.stop_on_semantic_success
        _, census = _hole_census(draft, cell.resolver)
        cell.emit(
            role=ROLE_CANDIDATE, round_index=round_index, narrowed=narrowed,
            source=draft, funnel=funnel, semantic=semantic,
            cell_done=stop_now or not cell.can_draw(), candidate=True,
            extra={
                **census,
                "bare_hole_body": bare,
                # §4.6's gate accounting, at the round level: was this
                # round's final draft grown from a seed the harness cut, or
                # from the draft the model wrote? A composed definition has to
                # be attributable to one or the other before B3's diagnostic
                # means anything.
                "checker_holed": bool(seed),
                "fills_attempted": attempted,
                "fills_spliced": spliced,
                "fills_rolled_back": rolled_back,
            })
        round_index += 1
        if stop_now:
            break


def run_task(task, condition, regime, seed, backend, resolver, config, grammar, masker=None, sink=None):
    """One (task, condition, regime, seed) cell, spent down to the budget.

    Every record is built and, if `sink` is given, handed to it immediately
    (`run`'s incremental-persistence path) before the loop moves on — so a
    crash on the *next* draw loses only that one draw, not the cell. The full
    list is still returned for the no-`sink` in-memory contract the test suite
    calls directly.

    Each record carries two additive fields for crash-safety:

    ``cell_done``   true on the record that ends the cell (no room left for a
                    full-cap draw, draw cap hit, or an early semantic-success
                    stop) — the resume completeness marker `run` looks for. A
                    cell cut off mid-draw writes no such record and is rerun
                    from scratch. Under `holes` the cell always ends on a
                    **candidate** record, because every round emits one, so a
                    cell interrupted mid-round is discarded whole and never
                    resumes onto a half-filled draft.
    ``retried``     true if this draw needed the one-retry-after-a-hiccup path.

    Which loop runs is `config.generation_protocol`, and the budget rule is the
    same object in both (`_CellRun`): every draw a round makes, skeleton or
    fill, is an ordinary full-cap draw against the one per-cell purse.

    The feedback-legibility seam (§2.1) is set here, once per cell, from
    `config.narrowing_note_render` — every `_fail` site `typecheck.py` reaches
    for the rest of this cell renders under whichever value this config carries.
    """
    if condition == CONDITION_TYPEMASK and masker is None:  # pragma: no cover - `run` builds it
        raise BackendUnavailable(NO_MASK_BACKEND_MESSAGE.format(backend=backend.name))
    typecheck.set_narrowing_note_render(config.narrowing_note_render)
    cell = _CellRun(
        task, condition, regime, seed, backend, resolver, config, grammar, masker, sink)
    if config.generation_protocol == PROTOCOL_HOLES:
        _run_holes_protocol(cell)
    else:
        _run_whole_protocol(cell)
    return cell.records


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


def _tally(values):
    """A count per distinct value, insertion-ordered — a small histogram for a
    summary field, spelled once instead of at each site that wants one."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _protocol_metrics(rows):
    """§4.6's protocol telemetry, or `{}` when no round protocol ran.

    Returning `{}` is what keeps every pre-decomposition summary byte-identical:
    no `holes` record, no key, no report section.
    """
    if not any(row.get("generation_protocol") == PROTOCOL_HOLES for row in rows):
        return {}
    skeletons = [row for row in rows if row.get("role") == ROLE_SKELETON]
    fills = [row for row in rows if row.get("role") == ROLE_FILL]
    candidates = [row for row in rows if row.get("role") == ROLE_CANDIDATE]
    accepted_skeletons = [r for r in skeletons if r["funnel_outcome"] == ACCEPTED]
    reasons: dict[str, int] = {}
    for row in skeletons:
        for reason in row.get("hole_reasons", []):
            reasons[reason] = reasons.get(reason, 0) + 1
    outcomes: dict[str, int] = {}
    for row in fills:
        outcome = row.get("splice_outcome", "")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    holes_seen = sum(row.get("holes", 0) for row in accepted_skeletons)
    fillable_seen = sum(row.get("holes_fillable", 0) for row in accepted_skeletons)
    return {
        "rounds": len(candidates),
        "skeleton_draws": len(skeletons),
        "accepted_skeletons": len(accepted_skeletons),
        # §6's licensing rows turn on this number: below 20 % a null primary is
        # a starved protocol, not a refuted one.
        "accepted_skeleton_rate": (
            round(len(accepted_skeletons) / len(skeletons), 4) if skeletons else 0.0),
        "bare_hole_drafts": sum(1 for row in skeletons if row.get("bare_hole_body")),
        # §2.2 B2's own telemetry: how many skeleton rounds actually carried
        # the hole-demand note forward. `0` on every arm but `hole-required`
        # (or on `hole-required` once its `hole_required_rounds` window has
        # closed for every cell), which is what makes this the mechanical
        # check that B2 fired at all.
        "hole_required_notes_added": sum(
            1 for row in skeletons if row.get("hole_required_note_added")),
        # §2.2 B3's own telemetry, and §4.6's attribution surface for it. All
        # zero on every arm but `checker-holed`. `eligible` is the denominator
        # the refusal rate is honest against — B3 only ever runs on a
        # typecheck-rejected draft — and `refusals` is the histogram that says
        # *why* it declined, since refusing is this mechanism's default answer
        # and a silent zero would otherwise be indistinguishable from a bug.
        "checker_holed_eligible": sum(
            1 for row in skeletons if row.get("checker_holed_eligible")),
        "checker_holed_seeds": sum(1 for row in skeletons if row.get("checker_holed")),
        "checker_holed_accepted": sum(
            1 for row in skeletons if row.get("checker_holed_outcome") == ACCEPTED),
        "checker_holed_refusals": _tally(
            row.get("checker_holed_reason", "") for row in skeletons
            if row.get("checker_holed_eligible") and not row.get("checker_holed")),
        "checker_holed_candidates": sum(
            1 for row in candidates if row.get("checker_holed")),
        "holes_per_accepted_skeleton": (
            round(holes_seen / len(accepted_skeletons), 3) if accepted_skeletons else 0.0),
        "fillable_hole_fraction": (
            round(fillable_seen / holes_seen, 4) if holes_seen else 0.0),
        "unfillable_reasons": reasons,
        "fill_draws": len(fills),
        "fill_outcomes": outcomes,
        "fills_spliced": outcomes.get(SPLICE_SPLICED, 0),
        "fills_rolled_back": outcomes.get(SPLICE_ROLLED_BACK, 0),
        "fill_tokens": sum(row["tokens_completion"] for row in fills),
        "skeleton_tokens": sum(row["tokens_completion"] for row in skeletons),
        "candidates": len(candidates),
        "hole_free_candidates": sum(1 for row in candidates if not row.get("holes", 0)),
        "holes_per_candidate": (
            round(sum(row.get("holes", 0) for row in candidates) / len(candidates), 3)
            if candidates else 0.0),
    }


def _cell_metrics(rows):
    # Only *draws* carry tokens, a funnel verdict the model is answerable for,
    # and latency. A round-candidate record is an assembly, so counting it here
    # would inflate every per-draw rate in the `holes` arm and in no other.
    draw_rows = [row for row in rows if row.get("role", ROLE_WHOLE) in DRAW_ROLES]
    protocol = _protocol_metrics(rows)
    tokens = sum(row["tokens_completion"] for row in draw_rows)
    accepted = [row for row in draw_rows if row["funnel_outcome"] == ACCEPTED]
    tally = FunnelTally()
    for row in draw_rows:
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
    latencies = [row["latency_s"] for row in draw_rows]
    masking = _mask_metrics(draw_rows)
    return {
        **({"masking": masking} if masking else {}),
        **({"protocol": protocol} if protocol else {}),
        "draws": len(draw_rows),
        "attempts": len(attempts),
        "tokens": tokens,
        "accepted": len(accepted),
        "accepted_per_1k_tokens": round(1000 * len(accepted) / tokens, 3) if tokens else 0.0,
        "semantic_successes": len(solved),
        "semantic_success_rate": round(len(solved) / len(attempts), 4) if attempts else 0.0,
        "mean_tokens_to_first_success": (
            round(statistics.fmean(first_success_tokens), 1) if first_success_tokens else None),
        "mean_draws_per_attempt": round(len(draw_rows) / len(attempts), 2) if attempts else 0.0,
        "redraws": len(draw_rows) - len(attempts),
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
    protocol = _protocol_metrics(records)
    r5 = r5_comparison(cells, config.baseline_summary)
    return {
        **({"masking": masking} if masking else {}),
        **({"protocol": protocol} if protocol else {}),
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


def _render_protocol(summary):
    """§4.6's protocol telemetry. Empty for every non-`holes` run, by construction."""
    protocol = summary.get("protocol")
    if not protocol:
        return []
    out = [
        "",
        "## Protocol telemetry — the `holes` arm (plan §4.6)",
        "",
        "Reported, not leaned on. The primary is the composed-definition rate "
        "over **candidates** (§4.5); these are the numbers that say whether the "
        "protocol actually ran, and §6's licensing rows turn on the "
        "accepted-skeleton rate in particular — below 20 % a null primary means "
        "the protocol was starved, not refuted.",
        "",
        f"**Rounds:** {protocol['rounds']}  ",
        f"**Skeleton draws:** {protocol['skeleton_draws']} "
        f"({protocol['accepted_skeletons']} accepted, rate "
        f"{protocol['accepted_skeleton_rate']})  ",
        f"**Bare-hole drafts (§3, unfilled by rule):** {protocol['bare_hole_drafts']}  ",
        *([f"**Hole-required notes added (§2.2 B2):** "
           f"{protocol['hole_required_notes_added']}  "]
          if protocol["hole_required_notes_added"] else []),
        *([f"**Checker-holed seeds (§2.2 B3):** {protocol['checker_holed_seeds']} "
           f"of {protocol['checker_holed_eligible']} typecheck-rejected drafts "
           f"({protocol['checker_holed_accepted']} of the seeds then typecheck; "
           f"{protocol['checker_holed_candidates']} rounds ended on one). "
           "**Exploratory — B3 is barred from the primary family by §2.2's "
           "pre-commitment**, because the harness choosing where to cut breaks "
           "2026-08-25 §2.1's no-oracle property.  "]
          if protocol["checker_holed_eligible"] else []),
        f"**Holes per accepted skeleton:** {protocol['holes_per_accepted_skeleton']} "
        f"({protocol['fillable_hole_fraction']} of them fillable in v1)  ",
        f"**Fill draws:** {protocol['fill_draws']} "
        f"({protocol['fills_spliced']} spliced, "
        f"{protocol['fills_rolled_back']} rolled back)  ",
        f"**Completion tokens:** {protocol['skeleton_tokens']} on skeletons, "
        f"{protocol['fill_tokens']} on fills — one purse, per §4.3.2  ",
        f"**Candidates:** {protocol['candidates']} "
        f"({protocol['hole_free_candidates']} hole-free; "
        f"{protocol['holes_per_candidate']} holes each on average)",
        "",
    ]
    if protocol["fill_outcomes"]:
        out += [_table(
            ["fill outcome", "count"],
            sorted(protocol["fill_outcomes"].items())), ""]
    if protocol["checker_holed_refusals"]:
        out += ["**`hole_at_error` refusals, by reason** (§2.2 B3 — refusing is "
                "the default answer, so this histogram is the mechanism "
                "working, not failing):", ""]
        out += [f"- {reason} — ×{count}"
                for reason, count in sorted(protocol["checker_holed_refusals"].items())]
        out += [""]
    if protocol["unfillable_reasons"]:
        out += ["**Unfillable holes, by reason** (§2.2 step 3's v1 boundary):", ""]
        out += [f"- {reason} — ×{count}"
                for reason, count in sorted(protocol["unfillable_reasons"].items())]
        out += [""]
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
        # Only when it is not the default, so every Phase A / Phase B report
        # written before decomposition existed renders byte-identically.
        *([f"**Generation protocol:** {config['generation_protocol']} "
           f"(≤ {config['fills_per_round_max']} fills per round, "
           f"≤ {config['fill_attempts_per_hole']} attempts per hole)  "]
          if config.get("generation_protocol", PROTOCOL_WHOLE) != PROTOCOL_WHOLE else []),
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
    out += _render_protocol(summary)
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
        print(f"generation protocol: {config.generation_protocol}")
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
