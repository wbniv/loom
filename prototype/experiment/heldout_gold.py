"""Deliverable 3 — a verified gold reference term for all eight held-out tasks.

[`docs/plans/2026-08-24-next-lever.md`](../../docs/plans/2026-08-24-next-lever.md)
§4.4: *"A task battery with no verified solution is not a battery."* Five of
the eight tasks already have a hand-solved gold term — §1.1, landed as
`experiment.addressability_audit.HAND_SOLVED` — and this module reuses those
five verbatim rather than re-deriving them. The remaining three
(`headOrElse`, `stampedBytes`, `selectNonNegative`) are authored here, against
the corpus's own canonical IR encoding, exactly as §1.1's fixtures are: never
shown to a model, harness fixtures like `composes`.

``GOLD_TERMS`` is the module's one public surface — ``task_id -> canonical
(def TYPE TERM) surface`` for every task with a gold answer under the §4.3
768-token per-draw cap. It is pure data (no resolver, no model, no I/O) so the
§4.8 check-4 stub test can import it and assert no gold surface appears in any
built prompt without paying for this module's verification pass. Everything
that touches the harness or a tokenizer lives behind ``verify()`` /
``tokenizer_check()`` / ``main()``, run explicitly, never at import time.

`heldout/list/headOrElse` note (plan's own words, `prompts.py`): "uncons
yields Maybe (Pair I64 (List I64)), so the option must be eliminated by a
match before the default applies — the composition does not type by
threading alone." That is the shape of the gold term below: `uncons`'s result
is re-matched into a `Maybe I64` (`Nothing` stays `Nothing`; `Just(pair)`
becomes `Just(head)`, discarding the tail), and only *that* is handed to
`getOrElse` — a literal `(ref …)` to both of the task's two `composes`
elements, which a naive thread-the-value attempt cannot produce.

Run as ``python3 -m experiment.heldout_gold`` from `prototype/` (CPU only, no
network): prints the funnel/semantic verdict for all eight tasks, the
chars/1.37 estimate against a real-tokenizer count, and any drop record.
"""

from __future__ import annotations

import argparse
import re

from experiment.addressability_audit import HAND_SOLVED
from experiment.evaluate import run_funnel, score_semantic
from experiment.prompts import CHARS_PER_TOKEN, HELD_OUT_TASKS
from experiment.resolver import ExperimentResolver

#: §4.3's per-draw cap. A gold term must clear this worst-case, or its task is
#: dropped from the battery before any GPU spend (§4.4).
MAX_DRAW_TOKENS = 768

#: The pinned model this project runs the matrix on (§5, `scripts/run-remote-
#: experiment-gcp.sh`, `experiment.live_mask_sanity.DEFAULT_MODEL`'s sibling).
#: Loaded CPU-only (`n_gpu_layers=0`) purely to tokenize eight short strings —
#: no context, no decode, no GPU.
DEFAULT_MODEL = "/home/will/loom-tools/models-7b-only/qwen2.5-coder-7b-instruct-q4_k_m.gguf"


# --------------------------------------------------------------------------
# The three authored gold terms
# --------------------------------------------------------------------------
#
# Built with tiny local S-expression helpers rather than hand-assembled
# strings, so a paren-counting slip is a Python bug (caught immediately) and
# not a silent malformed fixture. Each `TYPE` below is the task's own
# `expected_type_surface` — never retyped by hand, so it cannot drift from
# what `score_semantic`'s checked+type-exact rule actually compares against.


def _var(n: int) -> str:
    return f"(var {n})"


def _ref(digest_hex: str) -> str:
    return f"(ref {digest_hex})"


def _app(fn: str, arg: str) -> str:
    return f"(app {fn} {arg})"


def _app_n(fn: str, *args: str) -> str:
    for arg in args:
        fn = _app(fn, arg)
    return fn


def _lam(type_surface: str, body: str) -> str:
    return f"(lam {type_surface} {body})"


def _con(digest_hex: str, index: int, args: list[str]) -> str:
    return f"(con {digest_hex} {index} ({' '.join(args)}))"


def _arm(index: int, arity: int, term: str) -> str:
    return f"({index} {arity} {term})"


def _match(scrutinee: str, arms: list[str]) -> str:
    return f"(match {scrutinee} ({' '.join(arms)}))"


def _gold_def(task_id: str, term: str, tasks_by_id: dict) -> str:
    """`(def TYPE TERM)`, with `TYPE` read from the task, never retyped."""
    return f"(def {tasks_by_id[task_id].expected_type_surface} {term})"


# Hashes reused from `HAND_SOLVED` where the same object already appears
# there (`_MAYBE_T`'s digest, `_GET_OR_ELSE`), otherwise looked up once via
# `ExperimentResolver.digest_for` against the names `Task.composes` records
# and pinned here as the fixture constants R1.1's style already sets.
_LIST_T = "(data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64))"
_MAYBE_HASH = "0x3ff2104702aeeb53b4dfbc5a09c0441df19f12883e6cf66e21a3bd85420b4e2f"
_UNCONS = "0x1aa47aec06e66f1f563d461eedcf951c9cdab11e7fa26d252536c97160798af5"
_GET_OR_ELSE = "0x2dc64240af4f0bf328f1572c9cd09bca3bed789d5a150a3a8d0c0825b4ad2a2a"
_CLOCK_CAP_T = "(cap 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d)"
_RAND_CAP_T = "(cap 0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475)"
_CLOCK_NOW = "0x1d76cfea633059e7e0523b04b2a25f1bd7681266c2ad9c107fe63ed94b96aabe"
_RAND_BYTES = "0xf403bb626c6758e31f4d6ffe69b657f210dd40ad1b972249788bfb4c6e4d6181"
_PAIR_HASH = "0x98c7ee8d97ddf2707f45d89ac56c68cd24d0d7c7d6b093241b1ab84c88de4d2a"
_WIDEN_POS = "0xd9de68ecf5f6203a5b510e60183904138f5d4b71f60b636616cba82417e3b46d"
_SELECT = "0x4300a5090d354a1ad4dac0ce1a3ff1e96af401c3fca2a6d5c0e685bc5dfdaca4"

#: `_POS`/`_NAT`'s type surface, read off the task's own declared type rather
#: than reconstructed from the refinement predicate by hand (`selectNonNegative`
#: below needs both as intermediate lambda types, and `expected_type_surface`
#: is already the ground truth `score_semantic` checks against).
_SELECT_NONNEG_TYPE_RE = re.compile(
    r"^\(fn Bool \(\) \(fn (?P<pos>.+) \(\) \(fn (?P<nat>.+) \(\) .+\)\)\)$"
)


def _select_non_negative_term(pos_type: str, nat_type: str) -> str:
    """`select(bool, widenPos(pos), nat)` — the refinement widened before the
    two `NAT`-typed choices meet at `nat/select`, per the task's own note."""
    body = _app_n(
        _ref(_SELECT), _var(2), _app(_ref(_WIDEN_POS), _var(1)), _var(0)
    )
    return _lam("Bool", _lam(pos_type, _lam(nat_type, body)))


def _head_or_else_term() -> str:
    """`getOrElse(default, matched)`, where `matched` re-derives a `Maybe I64`
    from `uncons`'s `Maybe (Pair I64 (List I64))` by discarding the tail —
    the match `prompts.py`'s own held-out note says threading cannot skip."""
    mapped_maybe = _match(
        _app(_ref(_UNCONS), _var(1)),
        [
            _arm(0, 0, _con(_MAYBE_HASH, 0, [])),
            _arm(1, 1, _match(_var(0), [_arm(0, 2, _con(_MAYBE_HASH, 1, [_var(1)]))])),
        ],
    )
    body = _app_n(_ref(_GET_OR_ELSE), _var(0), mapped_maybe)
    return _lam(_LIST_T, _lam("I64", body))


def _stamped_bytes_term() -> str:
    """`Pair(clock/now(clockCap), rand/bytes(randCap, n))` — the effectful
    composition, both capabilities performed in the pair's own argument
    order (clock first, matching "began ... paired with")."""
    body = _con(
        _PAIR_HASH,
        0,
        [_app(_ref(_CLOCK_NOW), _var(2)), _app_n(_ref(_RAND_BYTES), _var(1), _var(0))],
    )
    return _lam(_CLOCK_CAP_T, _lam(_RAND_CAP_T, _lam("I64", body)))


def _authored_gold(tasks_by_id: dict) -> dict[str, str]:
    """The three gold surfaces not already in `HAND_SOLVED` (plan §1.1)."""
    match = _SELECT_NONNEG_TYPE_RE.match(
        tasks_by_id["heldout/nat/selectNonNegative"].expected_type_surface
    )
    if not match:
        raise ValueError(
            "heldout/nat/selectNonNegative's declared type no longer matches the "
            "shape this gold term assumes (Bool -> POS -> NAT -> NAT); the "
            "term needs re-deriving against the new type, not patching."
        )
    return {
        "heldout/list/headOrElse": _gold_def(
            "heldout/list/headOrElse", _head_or_else_term(), tasks_by_id
        ),
        "heldout/sample/stampedBytes": _gold_def(
            "heldout/sample/stampedBytes", _stamped_bytes_term(), tasks_by_id
        ),
        "heldout/nat/selectNonNegative": _gold_def(
            "heldout/nat/selectNonNegative",
            _select_non_negative_term(match.group("pos"), match.group("nat")),
            tasks_by_id,
        ),
    }


_TASKS_BY_ID = {task.task_id: task for task in HELD_OUT_TASKS}

#: The module's one public surface: every held-out task with a gold term
#: under the §4.3 768-token cap, mapping straight to its canonical
#: `(def TYPE TERM)` surface. Pure data — never shown to a model (§4.4), and
#: importable by the §4.8 check-4 stub test with no resolver/model cost.
GOLD_TERMS: dict[str, str] = {**HAND_SOLVED, **_authored_gold(_TASKS_BY_ID)}


# --------------------------------------------------------------------------
# Verification — machine-checked, run explicitly (never at import time)
# --------------------------------------------------------------------------


def verify(resolver: ExperimentResolver | None = None) -> tuple[list[dict], list[dict]]:
    """Every gold term through the real `run_funnel` + `score_semantic`.

    Returns `(rows, drops)`. A task drops if it has no gold term at all, or
    its gold term's chars/1.37 estimate exceeds `MAX_DRAW_TOKENS` — §4.4's
    stated stopping condition, checked here rather than assumed.
    """
    resolver = resolver if resolver is not None else ExperimentResolver()
    rows: list[dict] = []
    drops: list[dict] = []
    for task in HELD_OUT_TASKS:
        surface = GOLD_TERMS.get(task.task_id)
        if surface is None:
            drops.append({"task": task.task_id, "reason": "no gold term authored"})
            continue
        funnel = run_funnel(surface, resolver)
        semantic = score_semantic(task, funnel, surface)
        estimated_tokens = round(len(surface) / CHARS_PER_TOKEN)
        row = {
            "task": task.task_id,
            "chars": len(surface),
            "estimated_tokens": estimated_tokens,
            "funnel": funnel.outcome,
            "mechfloor": semantic.success,
            "detail": semantic.detail,
        }
        rows.append(row)
        if estimated_tokens > MAX_DRAW_TOKENS:
            drops.append({
                "task": task.task_id,
                "reason": f"estimated {estimated_tokens} tok > {MAX_DRAW_TOKENS}-tok §4.3 cap",
            })
    return rows, drops


def prompt_leak_check() -> list[str]:
    """§4.8 check 4's other half, run here as a sanity check on this module's
    own table (the pinned assertion itself belongs to the stub check, which
    imports `GOLD_TERMS` rather than duplicating this list).

    Returns the task ids for which a gold surface appears verbatim in any of
    the three arms' built prompts, over every held-out task — empty is the
    only acceptable result.
    """
    from experiment.prompts import (
        ADDRESS_BOOK_FULL,
        ADDRESS_BOOK_NONE,
        ADDRESS_BOOK_TYPED,
        REGIME_HELD_OUT,
        build_prompt,
    )

    resolver = ExperimentResolver()
    offenders = []
    for task in HELD_OUT_TASKS:
        gold = GOLD_TERMS.get(task.task_id)
        if gold is None:
            continue
        for address_book in (ADDRESS_BOOK_NONE, ADDRESS_BOOK_FULL, ADDRESS_BOOK_TYPED):
            prompt = build_prompt(task, REGIME_HELD_OUT, resolver, address_book=address_book)
            if gold in prompt:
                offenders.append(f"{task.task_id} ({address_book})")
    return offenders


def tokenizer_check(model_path: str = DEFAULT_MODEL, lib_path: str = "") -> list[dict] | str:
    """Real-tokenizer completion-token counts for every gold term, against
    the chars/1.37 estimate §1.1 and this module both use.

    Loads the pinned llama.cpp GGUF CPU-only (`n_gpu_layers=0`) purely to
    tokenize eight short strings — no context beyond what fits them, no
    decode, no GPU. Returns the exact blocker string (not an approximation)
    if the GGUF or the shared library is unavailable on this machine.
    """
    from experiment.llama_ffi import FfiUnavailable, LlamaModel

    try:
        model = LlamaModel(model_path, lib_path=lib_path or None, n_ctx=512, n_gpu_layers=0)
    except FfiUnavailable as error:
        return f"BLOCKED: real tokenizer unavailable — {error}"

    rows = []
    for task_id, surface in GOLD_TERMS.items():
        real_tokens = len(model.tokenize(surface))
        estimated = round(len(surface) / CHARS_PER_TOKEN)
        rows.append({
            "task": task_id,
            "chars": len(surface),
            "estimated_tokens_1.37": round(len(surface) / 1.37),
            "estimated_tokens_CHARS_PER_TOKEN": estimated,
            "real_tokens": real_tokens,
        })
    return rows


# --------------------------------------------------------------------------
# Printing / CLI
# --------------------------------------------------------------------------


def print_verify(rows: list[dict], drops: list[dict]) -> None:
    print("### 4.4 Gold reference terms — funnel + semantic verdict\n")
    for row in rows:
        print(
            f"{row['task']:<32} chars={row['chars']:>4}  ~{row['estimated_tokens']} tok  "
            f"funnel={row['funnel']:<9} mechfloor={row['mechfloor']}"
        )
    print()
    if drops:
        print("dropped from the battery:")
        for drop in drops:
            print(f"  {drop['task']:<32} {drop['reason']}")
    else:
        print("no drops — all 8 held-out tasks have a gold term under the 768-token cap")


def print_leak_check(offenders: list[str]) -> None:
    print("\n### Gold-term prompt-leak sanity check (all 3 arms, all 8 tasks)\n")
    if offenders:
        print("LEAK — gold surface found in a built prompt:")
        for offender in offenders:
            print(f"  {offender}")
    else:
        print("clean — no gold surface appears in any built prompt (none/full/typed)")


def print_tokenizer_check(result: list[dict] | str) -> None:
    print("\n### Real-tokenizer check vs the chars/1.37 estimate\n")
    if isinstance(result, str):
        print(result)
        return
    for row in result:
        delta = row["real_tokens"] - row["estimated_tokens_1.37"]
        print(
            f"{row['task']:<32} chars={row['chars']:>4}  "
            f"est(1.37)={row['estimated_tokens_1.37']:>4}  real={row['real_tokens']:>4}  "
            f"delta={delta:+d}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-tokenizer", action="store_true",
        help="skip the real-tokenizer check (funnel/semantic/leak checks still run)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="GGUF for the real-tokenizer check")
    parser.add_argument("--lib", default="", help="path to libllama.so (default: the pinned build)")
    arguments = parser.parse_args()

    resolver = ExperimentResolver()
    rows, drops = verify(resolver)
    print_verify(rows, drops)

    offenders = prompt_leak_check()
    print_leak_check(offenders)

    if not arguments.skip_tokenizer:
        result = tokenizer_check(arguments.model, arguments.lib)
        print_tokenizer_check(result)

    if len(GOLD_TERMS) - len(drops) < 6:
        print(
            "\n§4.4 stopping condition: battery below six tasks — "
            "this plan pauses before any GPU spend."
        )
        return 1
    return 0 if not offenders else 1


if __name__ == "__main__":
    raise SystemExit(main())
