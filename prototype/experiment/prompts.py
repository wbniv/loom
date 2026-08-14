"""R4's four corpus regimes, and the task set they are run over.

Two things live here because they are one decision: what the model is *shown*
and what it is *asked for* have to move together, or the regimes stop being
comparable.

Regimes (R4)
------------

``none``         No examples at all.
``few_shot``     A small fixed example set (`FEW_SHOT_NAMES`).
``full_corpus``  Every definition the resolver holds, in its own order —
                 manifest (dependency) order for the curated corpus, then any
                 harvested generations after it (see `_example_names`).
``held_out``     Full-corpus context, but the tasks are new spec texts that
                 require *composing* corpus definitions rather than recalling
                 one.

The first three run the corpus-drawn task set; `held_out` runs `HELD_OUT_TASKS`.
R4 lists the fourth item alongside the other three as a "corpus regime", and it
is the only one of the four that is a property of the *task* rather than of the
prompt — that asymmetry is real, and is kept explicit here rather than smoothed
away, because R3 scores the two task kinds by different rules.

**No hash directory is ever supplied.** Prediction 2 is stated in terms of
64-hex hashes being unguessable in low-example regimes and becoming available
"once examples supply the hashes", so hashes enter a prompt only through
examples. Handing the model a name-to-hash table would make prediction 2
untestable, so the harness does not have one.

**Leave-one-out is on by default.** A corpus-drawn task under `full_corpus`
would otherwise carry its own answer verbatim in the prompt, and semantic
success would measure transcription. `leave_one_out=False` restores the
verbatim condition, which is what prediction 6's memorization-pressure claim
needs; the flag's value is written into every run record so the two are never
confused after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import corpus_registry
import prelude
from transcode import type_to_surface

from .resolver import ExperimentResolver

REGIME_NONE = "none"
REGIME_FEW_SHOT = "few_shot"
REGIME_FULL_CORPUS = "full_corpus"
REGIME_HELD_OUT = "held_out"

REGIMES = (REGIME_NONE, REGIME_FEW_SHOT, REGIME_FULL_CORPUS, REGIME_HELD_OUT)

KIND_CORPUS = "corpus"
KIND_HELD_OUT = "held_out"

#: The small few-shot set: one boolean eliminator, one `match` over a nominal
#: data type, one recursive `fix` with a measure and a cross-definition `ref`,
#: and one effectful definition with a capability parameter. Four definitions
#: covering the four shapes a generation can take, chosen once and pinned so the
#: regime is reproducible rather than "whatever the first four entries were".
FEW_SHOT_NAMES = (
    "corpus/bool/not",
    "corpus/maybe/map",
    "corpus/list/append",
    "corpus/clock/now",
)

PREAMBLE = """\
You write Loom v0.1 definitions in its canonical S-expression surface.

The surface is fixed-spacing and canonical: exactly one top-level `(def TYPE \
TERM)` form, single spaces between fields, no comments, no newlines, no \
leading or trailing whitespace.

Types:   I64 Bool Unit F64 Text Bytes | (data HASH (TYPE ...)) | (fn DOMAIN \
(ROW) CODOMAIN) | (refine TYPE TERM) | (cap HASH) | (tyvar N) | (forall TYPE)
Terms:   (var N) (ref HASH) (lit KIND VALUE) (lam TYPE TERM) (app TERM TERM) \
(let TYPE TERM TERM) (con HASH INDEX (TERM ...)) (match TERM ((INDEX ARITY \
TERM) ...)) (perform HASH INDEX (TERM ...)) (handle HASH TERM ((INDEX TERM) \
...) TERM) (fix TYPE N TERM TERM) (hole TYPE ()) (if TERM TERM TERM)

Variables are de Bruijn indices counted outward from the innermost binder. A \
HASH is `0x` followed by exactly 64 lowercase hex digits. An effect row is \
`()` when empty, otherwise ability hashes sorted bytewise ascending.

Answer with the single `(def ...)` form and nothing else.\
"""

EXAMPLE_HEADER = "Here are definitions in this surface, each with what it does."

#: Characters per token for *this* surface — a floor, and a measured one.
#:
#: The phase-b run log records the longest curated prompts at `full_corpus`
#: 11,906 and `held_out` 11,959 real tokens (Qwen2.5-Coder-7B), and those same
#: prompts are 17,979 and 18,183 characters: **1.51 chars/token**. The reason is
#: hash literals — 64 hex digits tokenize far denser than prose — so the
#: 4-chars-per-token rule of thumb that reads as "conservative" for English is
#: *optimistic by 2.6x* here, which is the wrong direction for a check whose job
#: is to stop a run dying at the fourth regime. Anything sizing `n_ctx` divides
#: by this, not by 4.
CHARS_PER_TOKEN = 1.5


def estimated_tokens(text: str) -> int:
    """A conservative token count for a prompt, without loading a tokenizer."""
    return int(len(text) / CHARS_PER_TOKEN) + 1


def context_required(regimes, resolver, *, leave_one_out=True, draw_tokens=0) -> int:
    """Tokens the longest prompt over `regimes` needs, plus a draw's budget.

    The `n_ctx` a config must carry. Computed from the prompts themselves, so a
    config cannot drift under its own corpus — which is exactly how phase-b
    shipped `n_ctx: 4096` for an 11.9k-token prompt.
    """
    longest = 0
    for regime in regimes:
        for task in tasks_for_regime(regime):
            text = build_prompt(task, regime, resolver, leave_one_out=leave_one_out)
            longest = max(longest, estimated_tokens(text))
    return longest + draw_tokens


@dataclass(frozen=True)
class Task:
    """One thing the model is asked to produce, with how it will be scored.

    `expected_identity` drives R3's identity-match rule for corpus-drawn tasks;
    `expected_type_surface` drives the checked-plus-type-exact mechanical floor
    for held-out ones. Exactly one of the two is set, and `kind` says which.
    """

    task_id: str
    kind: str
    spec: str
    expected_identity: str = ""
    expected_surface: str = ""
    expected_type_surface: str = ""
    expected_tier: str = ""
    composes: tuple[str, ...] = ()
    note: str = ""

    @property
    def scoring_rule(self) -> str:
        return "identity-match" if self.kind == KIND_CORPUS else "checked+type-exact"


# --------------------------------------------------------------------------
# Held-out compositional tasks
# --------------------------------------------------------------------------
#
# New spec texts, none of them a corpus entry's spec, each answerable only by
# composing corpus definitions and the assumed base. Expected types are built as
# IR from the same hashes the corpus uses and rendered through the canonical
# transcoder, so a typo becomes a `SurfaceError` at import rather than a silent
# scoring bug. `composes` records the intended route; it is analysis metadata
# and is never shown to the model.

_I64 = [0, 2]
_BOOL = [0, 1]
_BYTES = [0, 5]

_LIST = corpus_registry.HASHES["List"]
_MAYBE = corpus_registry.HASHES["Maybe"]
_PAIR = corpus_registry.HASHES["Pair"]
_CLOCK = prelude.HASHES["clock"]
_RAND = prelude.HASHES["rand"]
_LT = corpus_registry.EXTERN_HASHES["I64.lt"]


def _data(digest: bytes, arguments: list) -> list:
    return [1, digest, arguments]


def _fn(domain: list, row, codomain: list) -> list:
    """`domain -{row}> codomain`, with the row sorted the way §2.3 requires."""
    return [2, domain, sorted(row), codomain]


def _cap(digest: bytes) -> list:
    return [4, digest]


def _refine_lt(bound: int) -> list:
    """`{v : I64 | bound < v}`, the corpus's own `nat`/`pos` encoding."""
    return [3, _I64, [4, [4, [1, _LT], [2, 2, bound]], [0, 0]]]


_LIST_I64 = _data(_LIST, [_I64])
_MAYBE_I64 = _data(_MAYBE, [_I64])
_NAT = _refine_lt(-1)
_POS = _refine_lt(0)


def _held_out(task_id, spec, type_ir, composes, note=""):
    return Task(
        task_id=task_id,
        kind=KIND_HELD_OUT,
        spec=spec,
        expected_type_surface=type_to_surface(type_ir),
        composes=composes,
        note=note,
    )


HELD_OUT_TASKS = (
    _held_out(
        "heldout/list/concatLength",
        "The number of elements you get when the second list is placed after the first.",
        _fn(_LIST_I64, [], _fn(_LIST_I64, [], _I64)),
        ("corpus/list/append", "List.size"),
        "Append composed with the assumed-base measure primitive.",
    ),
    _held_out(
        "heldout/list/mapLength",
        "The number of elements a list has once a function has been applied to every one of them.",
        _fn(_fn(_I64, [], _I64), [], _fn(_LIST_I64, [], _I64)),
        ("corpus/list/map", "List.size"),
        "A higher-order argument threaded into map, then measured.",
    ),
    _held_out(
        "heldout/list/reverseThen",
        "The first list in reverse order, with the second list following it.",
        _fn(_LIST_I64, [], _fn(_LIST_I64, [], _LIST_I64)),
        ("corpus/list/reverse", "corpus/list/append"),
        "Two corpus definitions in sequence; no new recursion needed.",
    ),
    _held_out(
        "heldout/maybe/mapOrElse",
        "The result of applying a function to the option's value, "
        "or the supplied default when the option is empty.",
        _fn(_fn(_I64, [], _I64), [], _fn(_MAYBE_I64, [], _fn(_I64, [], _I64))),
        ("corpus/maybe/map", "corpus/maybe/getOrElse"),
        "Three arguments, and the composition order is the whole task.",
    ),
    _held_out(
        "heldout/list/headOrElse",
        "The first element of a list, or the supplied default when the list is empty.",
        _fn(_LIST_I64, [], _fn(_I64, [], _I64)),
        ("corpus/list/uncons", "corpus/maybe/getOrElse"),
        "uncons yields Maybe (Pair I64 (List I64)), so the option must be "
        "eliminated by a `match` before the default applies — the composition "
        "does not type by threading alone.",
    ),
    _held_out(
        "heldout/list/sum",
        "The result of adding every element of a list together, starting from zero.",
        _fn(_LIST_I64, [], _I64),
        ("corpus/list/foldLeft", "I64.add"),
        "A fold whose combining function is an extern reference.",
    ),
    _held_out(
        "heldout/sample/stampedBytes",
        "The wall-clock time at which a draw of the requested number of random "
        "bytes began, paired with the bytes that were drawn.",
        _fn(
            _cap(_CLOCK),
            [],
            _fn(_cap(_RAND), [], _fn(_I64, [_RAND, _CLOCK], _data(_PAIR, [_I64, _BYTES]))),
        ),
        ("corpus/clock/now", "corpus/rand/bytes"),
        "The effectful composition: two capabilities, a two-ability closed row "
        "on the innermost arrow only, and the row's bytewise sort order.",
    ),
    _held_out(
        "heldout/nat/selectNonNegative",
        "A choice, made on a boolean, between a positive integer and a "
        "nonnegative one, given back as a nonnegative integer.",
        _fn(_BOOL, [], _fn(_POS, [], _fn(_NAT, [], _NAT))),
        ("corpus/nat/widenPos", "corpus/nat/select"),
        "The refinement composition: the positive argument has to be widened "
        "before the choice can be made at the nonnegative type.",
    ),
)


def corpus_tasks() -> tuple[Task, ...]:
    """One task per manifest entry, asked for by its own spec text."""
    return tuple(
        Task(
            task_id=entry.name_path,
            kind=KIND_CORPUS,
            spec=entry.spec,
            expected_identity=entry.identity,
            expected_surface=entry.source_text().rstrip("\n"),
            expected_tier=entry.tier,
            note=entry.deferred,
        )
        for entry in corpus_registry.MANIFEST
    )


def held_out_tasks() -> tuple[Task, ...]:
    return HELD_OUT_TASKS


def tasks_for_regime(regime: str) -> tuple[Task, ...]:
    """The task set a regime is run over."""
    if regime not in REGIMES:
        raise ValueError(f"unknown regime {regime!r}; known regimes: {', '.join(REGIMES)}")
    if regime == REGIME_HELD_OUT:
        return held_out_tasks()
    return corpus_tasks()


def all_tasks() -> tuple[Task, ...]:
    return corpus_tasks() + held_out_tasks()


def _example_names(regime: str, resolver: ExperimentResolver) -> tuple[str, ...]:
    """The regime's example set, drawn from whatever corpus the resolver holds.

    The full-corpus regimes read `resolver.definitions()` rather than
    `corpus_registry.MANIFEST`, which is what makes the corpus-loop A/B an
    experiment about *what the model sees* rather than only about what resolves.
    Widening the hash universe alone would test the references layer, and
    Phase A already measured references as a minor layer (75 of 664 rejections);
    the corpus in context was the largest lever it found.

    The curated arm is unchanged, and structurally so rather than by care:

    * `ExperimentResolver.definitions()` *is* `corpus_registry.MANIFEST` in
      manifest order, so a run with no store is byte-for-byte what it was;
    * `StoreResolver.definitions()` follows the export's `(sequence, hash)`
      order, and `harvest.py` numbers generated objects from a reserved band
      four orders of magnitude above the corpus — so curated definitions come
      first, in manifest order, and generated ones follow in harvest order.

    `few_shot` keeps its pinned four names: the regime's whole point is a small
    *fixed* set, and letting a store change it would make it a different regime.
    """
    if regime == REGIME_NONE:
        return ()
    if regime == REGIME_FEW_SHOT:
        return FEW_SHOT_NAMES
    # A store can hold a definition admitted without a `--name`. It has no §5.2
    # metadata name to look up and no entry to read a spec from, so it cannot be
    # shown as an example; skipping it here is the only place that decision has
    # to be made, and it keeps `build_prompt`'s name→digest→entry chain total.
    return tuple(found.name for found in resolver.definitions() if found.name)


def example_names(
    regime: str,
    task: Task,
    resolver: ExperimentResolver | None = None,
    *,
    leave_one_out: bool = True,
) -> tuple[str, ...]:
    """The definitions a regime shows for this task, in prompt order.

    `resolver` defaults to a corpus-built one. That default is the pinned corpus
    and nothing else, so it is exactly the curated arm; it exists for callers
    that want the regime's shape without building a store, and `build_prompt`
    never uses it.

    With `leave_one_out`, a corpus-drawn task never sees its own answer. The
    exclusion is by **identity, not by name**: a harvested store can hold a
    generated definition whose bytes are the task's fixture (four of phase-b's
    38 accepted identities were exactly that), and excluding it by name would
    leave the answer in the prompt under a `generated/…` label — the precise
    leak leave-one-out exists to prevent. Content addressing makes the identity
    check the complete one, and for a curated-only resolver it removes the same
    single name the old by-name rule did.

    When that empties a slot in the small few-shot set, the next unused
    definition backfills it, so the regime keeps its size instead of silently
    shrinking for exactly the tasks it was meant to help.
    """
    if regime not in REGIMES:
        raise ValueError(f"unknown regime {regime!r}; known regimes: {', '.join(REGIMES)}")
    resolver = resolver if resolver is not None else ExperimentResolver()
    names = list(_example_names(regime, resolver))
    if not leave_one_out or task.kind != KIND_CORPUS or not task.expected_identity:
        return tuple(names)
    answers = {
        name for name in names
        if resolver.digest_for(name).hex() == task.expected_identity
    }
    if not answers:
        return tuple(names)
    wanted = len(names)
    names = [name for name in names if name not in answers]
    if regime == REGIME_FEW_SHOT:
        for name in _example_names(REGIME_FULL_CORPUS, resolver):
            if len(names) >= wanted:
                break
            if name not in names and name not in answers:
                names.append(name)
    return tuple(names)


def build_prompt(
    task: Task,
    regime: str,
    resolver: ExperimentResolver,
    *,
    leave_one_out: bool = True,
    narrowing: str = "",
) -> str:
    """The full prompt for one (task, regime) pair.

    `narrowing` carries condition 3's §8.3-style feedback from the previous
    rejected draw. It is appended after the examples and before the ask, so the
    prompt prefix is byte-identical across conditions until a rejection has
    actually happened — which is what makes the conditions comparable on tokens.
    """
    blocks = [PREAMBLE]
    names = example_names(regime, task, resolver, leave_one_out=leave_one_out)
    if names:
        lines = [EXAMPLE_HEADER]
        for name in names:
            found = resolver.resolve(resolver.digest_for(name))
            entry = resolver.entry(found.digest)
            # Every curated definition has a §5.2 spec, so this branch never
            # fires for the curated arm and the prompt bytes are untouched. A
            # harvested definition has none — nobody wrote one — and it shows
            # bare rather than under a borrowed spec, which would describe what
            # was *asked for* rather than what the definition does.
            lines.append(f"\n{entry.spec}\n{found.surface}" if entry.spec
                         else f"\n{found.surface}")
        blocks.append("\n".join(lines))
    if narrowing:
        blocks.append(narrowing)
    blocks.append(f"Now write this definition.\n{task.spec}")
    return "\n\n".join(blocks) + "\n"
