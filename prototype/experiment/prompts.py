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

**No hash directory is ever supplied** — unless a config asks for one. Prediction
2 is stated in terms of 64-hex hashes being unguessable in low-example regimes
and becoming available "once examples supply the hashes", so under R4 hashes
enter a prompt only through examples, and `address_book: "none"` (the default,
and what every pre-existing config is in) keeps that exactly.

The address book (2026-08-24 next-lever plan §3/§4)
--------------------------------------------------

`address_book` is the manipulated variable of that plan's three-arm
pre-registration, and it is the *only* thing its arms differ by:

``none``   no block at all — byte-identical to the R4 prompt.
``full``   one row per `ref`-legal store object, in resolver order.
``typed``  the same rows, filtered by §4.2's codomain test against the task's
           own declared type.

A row is `0x<64 hex> <name> : <type surface>` — an address, a name and a type.
Never a term. The block therefore cannot carry a definition's body, and a gold
answer cannot reach the model through it.

**The `typed` filter is deliberately impoverished.** `typed_address_rows` takes a
resolver and a *type surface*, and nothing else. It is not given the `Task`, so
it cannot consult `composes` (the recorded route) or `expected_surface` (a gold
term) even by accident; §4.2 requires that by construction rather than by care,
and `test_experiment.py` pins it adversarially. Selection is a pure function of
the resolver's own types and the task's declared type, so two tasks with the
same declared type and different routes get byte-identical blocks.

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
import sexpr
from transcode import type_to_ir, type_to_surface

from .resolver import KIND_DEFINITION, KIND_EXTERN, ExperimentResolver, Resolved

REGIME_NONE = "none"
REGIME_FEW_SHOT = "few_shot"
REGIME_FULL_CORPUS = "full_corpus"
REGIME_HELD_OUT = "held_out"

REGIMES = (REGIME_NONE, REGIME_FEW_SHOT, REGIME_FULL_CORPUS, REGIME_HELD_OUT)

KIND_CORPUS = "corpus"
KIND_HELD_OUT = "held_out"

#: The three arms of the next-lever pre-registration (§4.2). `none` is the
#: default everywhere, and under it `build_prompt` returns the R4 bytes.
ADDRESS_BOOK_NONE = "none"
ADDRESS_BOOK_FULL = "full"
ADDRESS_BOOK_TYPED = "typed"

ADDRESS_BOOKS = (ADDRESS_BOOK_NONE, ADDRESS_BOOK_FULL, ADDRESS_BOOK_TYPED)

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

#: The address block's one header line. §3 sizes the block as its rows alone
#: (9,202 characters for the full book), and `address_rows` still returns
#: exactly those rows, so that sizing is unchanged; the header is 96 characters
#: of framing on top, without which the block is 35 unlabelled hex lines and the
#: arm tests "does a wall of hashes confuse a 7B" rather than "does addressing
#: help". It is identical across the two address arms, so §4.8's byte-comparison
#: strips it with the rows it heads.
ADDRESS_HEADER = (
    "These objects are already in the store. Each line is one object's address, "
    "its name and its type; write `(ref ADDRESS)` to use it."
)

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


def context_required(
    regimes, resolver, *, leave_one_out=True, draw_tokens=0, address_book=ADDRESS_BOOK_NONE
) -> int:
    """Tokens the longest prompt over `regimes` needs, plus a draw's budget.

    The `n_ctx` a config must carry. Computed from the prompts themselves, so a
    config cannot drift under its own corpus — which is exactly how phase-b
    shipped `n_ctx: 4096` for an 11.9k-token prompt, and, with `address_book`
    passed through, how §4.3.2 keeps a config from drifting under its own
    address book.
    """
    longest = 0
    for regime in regimes:
        for task in tasks_for_regime(regime):
            text = build_prompt(
                task, regime, resolver,
                leave_one_out=leave_one_out,
                address_book=address_book,
            )
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


# --------------------------------------------------------------------------
# The store address book (2026-08-24 next-lever plan §3, §4.2)
# --------------------------------------------------------------------------


def ref_legal_objects(resolver: ExperimentResolver) -> tuple[Resolved, ...]:
    """Every object a `(ref …)` may legally name, in resolver order.

    Definitions and externs; not data or ability declarations, which are
    nominal hashes with no reference type — a `(ref DATA_HASH)` is exactly the
    illegal draw §1.2 measures the model making, and listing one would teach it
    that mistake. For the curated resolver this is 35 of 47 digests.
    """
    return tuple(
        found
        for found in (resolver.resolve(digest) for digest in resolver.digests())
        if found.kind in (KIND_DEFINITION, KIND_EXTERN)
    )


def address_row(found: Resolved) -> str:
    """One book row: an address, a name, a type. Never a term."""
    return f"0x{found.hex} {found.name} : {type_to_surface(found.type_ir)}"


def _erase(type_ir: list) -> list:
    """§3.2.1's refinement erasure: `refine T φ` -> `erase(T)`, recursively."""
    tag = type_ir[0]
    if tag == 3:  # refine
        return _erase(type_ir[1])
    if tag == 1:  # data
        return [1, type_ir[1], [_erase(a) for a in type_ir[2]]]
    if tag == 2:  # fn
        return [2, _erase(type_ir[1]), type_ir[2], _erase(type_ir[3])]
    if tag == 6:  # forall
        return [6, _erase(type_ir[1])]
    return type_ir  # base, cap, tyvar: nothing to erase


def _kth_codomain(type_ir: list, k: int) -> list | None:
    """The type after peeling `k` `fn` arrows, or `None` if it has fewer."""
    current = type_ir
    for _ in range(k):
        if current[0] != 2:
            return None
        current = current[3]
    return current


def _body_goal(type_ir: list) -> list:
    """A task's own type, peeled of every `fn` arrow — the type its written
    term's innermost body must check against."""
    current = type_ir
    while current[0] == 2:
        current = current[3]
    return _erase(current)


#: §2.4's spine depths. A `ref` at the head of a k-ary application spine checked
#: against goal G must resolve to a type whose k-th codomain erases to G; every
#: held-out route saturates at three arguments or fewer.
CODOMAIN_DEPTHS = (0, 1, 2, 3)


def _admits_goal(type_ir: list, goal: list) -> bool:
    if type_ir[0] == 6:  # a bare `forall` can instantiate to anything
        return True
    return any(
        (peeled := _kth_codomain(type_ir, k)) is not None and _erase(peeled) == goal
        for k in CODOMAIN_DEPTHS
    )


def body_goal_of(type_surface: str) -> list:
    """The body goal of a declared type, parsed from its canonical surface."""
    if not type_surface.strip():
        raise ValueError("a goal-type filter needs a declared type surface")
    return _body_goal(type_to_ir(sexpr.parse_all(type_surface)[0]))


def typed_address_rows(resolver: ExperimentResolver, type_surface: str) -> tuple[str, ...]:
    """§4.2's goal-type filter — **a resolver and a type, and nothing else**.

    Object `o` is listed iff some k in `CODOMAIN_DEPTHS` has `o`'s k-th codomain
    erasing (§3.2.1) to the declared type's body goal, or `o`'s type is a bare
    `forall`. Rows keep resolver order, so which rows survive is the only thing
    the filter decides — it cannot rank the route first either.

    The two-argument signature is the guarantee, not a convenience: this
    function is never handed a `Task`, so it cannot read `composes` or
    `expected_surface`, and two tasks with the same declared type and different
    routes are indistinguishable to it.
    """
    goal = body_goal_of(type_surface)
    return tuple(
        address_row(found)
        for found in ref_legal_objects(resolver)
        if _admits_goal(found.type_ir, goal)
    )


def full_address_rows(resolver: ExperimentResolver) -> tuple[str, ...]:
    """Every `ref`-legal object's row, in resolver order — `addr-full`."""
    return tuple(address_row(found) for found in ref_legal_objects(resolver))


def address_rows(
    resolver: ExperimentResolver,
    address_book: str,
    *,
    type_surface: str = "",
    exclude_identity: str = "",
) -> tuple[str, ...]:
    """The rows one arm shows for one task, in resolver order.

    `exclude_identity` is leave-one-out carried into the book. It never fires
    for the plan's arms — a held-out task is not a corpus entry and has no
    `expected_identity` — but a corpus-drawn task under an address book would
    otherwise be handed the address of the very definition the prompt is
    withholding, and leave-one-out's job is that its answer is not in the
    prompt in *any* form.
    """
    if address_book not in ADDRESS_BOOKS:
        raise ValueError(
            f"unknown address_book {address_book!r}; known: {', '.join(ADDRESS_BOOKS)}")
    if address_book == ADDRESS_BOOK_NONE:
        return ()
    rows = (
        full_address_rows(resolver) if address_book == ADDRESS_BOOK_FULL
        else typed_address_rows(resolver, type_surface)
    )
    if exclude_identity:
        prefix = f"0x{exclude_identity} "
        rows = tuple(row for row in rows if not row.startswith(prefix))
    return rows


def address_book_block(
    resolver: ExperimentResolver,
    address_book: str,
    *,
    type_surface: str = "",
    exclude_identity: str = "",
) -> str:
    """The exact block `build_prompt` inserts, or `""` for `none`.

    §4.8's first check strips this string from an address arm's prompt and
    compares the remainder byte-for-byte with `addr-none`, so this is the one
    place the block's text is built.
    """
    rows = address_rows(
        resolver, address_book, type_surface=type_surface, exclude_identity=exclude_identity)
    if not rows:
        return ""
    return "\n".join([ADDRESS_HEADER, *rows])


def _task_address_block(
    task: Task,
    resolver: ExperimentResolver,
    address_book: str,
    *,
    leave_one_out: bool,
) -> str:
    """`address_book_block` for a task, supplying only its *declared* type.

    A corpus-drawn task declares no type — `expected_type_surface` is empty and
    the only type it has is the one inside its gold surface. Reading that would
    make the filter a function of the answer, so `typed` refuses the task
    outright rather than quietly deriving a goal from a fixture.
    """
    if address_book == ADDRESS_BOOK_TYPED and not task.expected_type_surface.strip():
        raise ValueError(
            f"address_book 'typed' filters on a task's declared type, and "
            f"{task.task_id!r} ({task.kind}) declares none. The next-lever arms "
            f"(§4.2) are the 'held_out' regime only.")
    return address_book_block(
        resolver,
        address_book,
        type_surface=task.expected_type_surface,
        exclude_identity=task.expected_identity if leave_one_out else "",
    )


def build_prompt(
    task: Task,
    regime: str,
    resolver: ExperimentResolver,
    *,
    leave_one_out: bool = True,
    narrowing: str = "",
    address_book: str = ADDRESS_BOOK_NONE,
) -> str:
    """The full prompt for one (task, regime) pair.

    `narrowing` carries condition 3's §8.3-style feedback from the previous
    rejected draw. It is appended after the examples and before the ask, so the
    prompt prefix is byte-identical across conditions until a rejection has
    actually happened — which is what makes the conditions comparable on tokens.

    `address_book` inserts §3's block between the examples and `narrowing` —
    before it, not after, so the prefix-identity property above survives the
    new block. At the default `"none"` not one byte of this function's output
    changes, which is what makes `addr-none` the control arm rather than a
    fourth thing.
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
    book = _task_address_block(task, resolver, address_book, leave_one_out=leave_one_out)
    if book:
        blocks.append(book)
    if narrowing:
        blocks.append(narrowing)
    blocks.append(f"Now write this definition.\n{task.spec}")
    return "\n\n".join(blocks) + "\n"
