"""Deliverable 4 — the §4.8 stub-backend dry-run, CPU only, no GPU, no network.

[`docs/plans/2026-08-24-next-lever.md`](../../docs/plans/2026-08-24-next-lever.md)
§4.8, run as amended by Amendment A1 (filed after §4.9, replacing check 2). This
is the gate on GPU spend: every check below must print PASS and the script must
exit non-zero the moment any check fails, so a failing gate cannot be missed by
skimming the tail of the output.

Five checks, reusing the landed machinery rather than a second copy of it:

1. The three arms' prompts, built the way `runner` would from the shipped
   `addr-{none,full,typed}.config.json`, differ from `addr-none` only by the
   inserted block — `prompts.address_book_block` is the single source of the
   block text, per its own docstring.
2. (Amended by A1) (a) `typed_address_rows`' blindness, by signature; (b) its
   row set for every task byte-matches `experiment.addressability_audit`'s own
   `addressbook()` recomputation — one source of truth, checked here rather
   than assumed; (c) the per-task route-incompleteness table A1 pastes into
   the plan, reproduced by a check that consults `Task.composes` itself — the
   filter under test never does, and never will.
3. `context_required` for each arm's every prompt clears `n_ctx -
   max_tokens_per_draw`.
4. Every gold term (`experiment.heldout_gold.GOLD_TERMS`) passes `run_funnel`
   and `score_semantic`, and no gold surface leaks into any built prompt in any
   arm — both reused from `heldout_gold` rather than re-asserted here.
5. Route-reference extraction, replayed over the 4,135 recorded held-out draws
   via `experiment.addressability_audit.refs`, reproduces the 12/4,135
   baseline exactly.

    python3 -m experiment.address_book_stub_check   (from prototype/)
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

from experiment import addressability_audit, heldout_gold, prompts, runner
from experiment.evaluate import ACCEPTED
from experiment.prompts import HELD_OUT_TASKS, REGIME_HELD_OUT
from experiment.resolver import ExperimentResolver

CONFIG_DIR = Path(__file__).resolve().parent

#: The three §4.2 arm configs, as committed (commit 44b75a7). Loaded exactly as
#: the runner loads them — `runner.Config.load` anchors `store_export` to this
#: directory and runs `validate()`, so a check here fails the same way a real
#: launch would if a config drifted.
ARM_CONFIGS = ("addr-none", "addr-full", "addr-typed")

#: Amendment A1's per-task route-incompleteness table, reproduced by check 2c.
#: `list`/`maybe`/`clock`/`rand` names below are `Task.composes` entries with
#: their `corpus/` prefix stripped, matching the plan's own prose.
EXPECTED_ROUTE_INCOMPLETE = {
    "heldout/list/concatLength": ("list/append",),
    "heldout/list/mapLength": ("list/map",),
    "heldout/maybe/mapOrElse": ("maybe/map",),
    "heldout/list/headOrElse": ("list/uncons",),
    "heldout/sample/stampedBytes": ("clock/now", "rand/bytes"),
}
EXPECTED_ROUTE_COMPLETE = (
    "heldout/list/reverseThen",
    "heldout/list/sum",
    "heldout/nat/selectNonNegative",
)


def _load_arms() -> dict[str, tuple[runner.Config, object]]:
    """Every arm config, loaded and validated, paired with the resolver the
    runner would build for it (§4.2's curated-only 26-def/47-object store)."""
    arms = {}
    for name in ARM_CONFIGS:
        config = runner.Config.load(CONFIG_DIR / f"{name}.config.json")
        arms[name] = (config, runner.make_resolver(config))
    return arms


# --------------------------------------------------------------------------
# Check 1 — the arms differ from addr-none only by the inserted block
# --------------------------------------------------------------------------


def check_1(arms) -> tuple[bool, list[str]]:
    lines = ["### Check 1 — arms differ from addr-none only by the inserted block\n"]
    none_config, none_resolver = arms["addr-none"]
    ok = True
    for arm_name in ("addr-full", "addr-typed"):
        config, resolver = arms[arm_name]
        for task in HELD_OUT_TASKS:
            control = prompts.build_prompt(
                task, REGIME_HELD_OUT, none_resolver, address_book=none_config.address_book)
            armed = prompts.build_prompt(
                task, REGIME_HELD_OUT, resolver, address_book=config.address_book)
            block = prompts.address_book_block(
                resolver, config.address_book, type_surface=task.expected_type_surface)
            # The block arrives as its own paragraph (`build_prompt` joins
            # blocks with "\n\n"); stripping it and the separator it brought
            # must give back addr-none's bytes exactly.
            stripped = armed.replace(f"\n\n{block}", "", 1)
            match = stripped == control
            ok = ok and match
            lines.append(
                f"{arm_name:<10} {task.task_id:<32} block={len(block):>5}B  "
                f"strip-and-compare={'match' if match else 'MISMATCH'}"
            )
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'} — "
                 f"{len(ARM_CONFIGS) - 1} arms x {len(HELD_OUT_TASKS)} tasks checked")
    return ok, lines


# --------------------------------------------------------------------------
# Check 2 — as replaced by Amendment A1
# --------------------------------------------------------------------------


def check_2a(arms) -> tuple[bool, list[str]]:
    lines = ["### Check 2a — typed_address_rows' blindness, by signature\n"]
    parameters = list(inspect.signature(prompts.typed_address_rows).parameters)
    ok = parameters == ["resolver", "type_surface"]
    lines.append(f"typed_address_rows(resolver, type_surface) parameters: {parameters}")
    # And it really runs on those two arguments alone, against a fresh resolver
    # that carries no memory of any config or task.
    _, typed_resolver = arms["addr-typed"]
    probe = prompts.typed_address_rows(
        typed_resolver, HELD_OUT_TASKS[0].expected_type_surface)
    ok = ok and bool(probe)
    lines.append(f"probe call with (resolver, type_surface) alone returns {len(probe)} rows")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def check_2b(arms) -> tuple[bool, list[str]]:
    lines = ["### Check 2b — typed row sets byte-match the audit's recomputation\n"]
    _, typed_resolver = arms["addr-typed"]
    audit_stats = addressability_audit.addressbook(typed_resolver)
    ok = True
    for task in HELD_OUT_TASKS:
        built_rows = prompts.typed_address_rows(typed_resolver, task.expected_type_surface)
        audit_names = audit_stats["typed_which_by_task"][task.task_id]
        audit_rows = tuple(
            prompts.address_row(typed_resolver.resolve(typed_resolver.digest_for(name)))
            for name in audit_names
        )
        match = built_rows == audit_rows
        ok = ok and match
        lines.append(
            f"{task.task_id:<32} built={len(built_rows):>2} rows  audit={len(audit_rows):>2} rows  "
            f"{'match' if match else 'MISMATCH'}"
        )
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def check_2c(arms) -> tuple[bool, list[str]]:
    lines = ["### Check 2c — per-task route-incompleteness table (Amendment A1)\n"]
    lines.append(
        "Task.composes is read here, in the check, never by typed_address_rows "
        "(check 2a pins that by signature).\n"
    )
    _, typed_resolver = arms["addr-typed"]
    tasks_by_id = {task.task_id: task for task in HELD_OUT_TASKS}
    actual_incomplete = {}
    actual_complete = []
    for task in HELD_OUT_TASKS:
        rows = prompts.typed_address_rows(typed_resolver, task.expected_type_surface)
        addressed = {row.split(" ", 1)[0] for row in rows}
        missing = tuple(
            name.removeprefix("corpus/")
            for name in task.composes
            if f"0x{typed_resolver.digest_for(name).hex()}" not in addressed
        )
        if missing:
            actual_incomplete[task.task_id] = missing
        else:
            actual_complete.append(task.task_id)
        status = "ROUTE-INCOMPLETE" if missing else "complete"
        lines.append(f"{task.task_id:<32} {status:<17} missing={list(missing)}")

    ok = (
        len(actual_incomplete) == 5
        and actual_incomplete == EXPECTED_ROUTE_INCOMPLETE
        and sorted(actual_complete) == sorted(EXPECTED_ROUTE_COMPLETE)
    )
    lines.append(f"\n{len(actual_incomplete)} of {len(tasks_by_id)} tasks route-incomplete "
                 f"(expected 5); complete: {sorted(actual_complete)} "
                 f"(expected {sorted(EXPECTED_ROUTE_COMPLETE)})")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 3 — context_required clears n_ctx - max_tokens_per_draw for every arm
# --------------------------------------------------------------------------


def check_3(arms) -> tuple[bool, list[str]]:
    lines = ["### Check 3 — context_required <= n_ctx - max_tokens_per_draw, every arm\n"]
    ok = True
    for name in ARM_CONFIGS:
        config, resolver = arms[name]
        bare = prompts.context_required(
            config.regimes, resolver, address_book=config.address_book)
        threshold = config.n_ctx - config.max_tokens_per_draw
        clears = bare <= threshold
        ok = ok and clears
        lines.append(
            f"{name:<10} longest prompt={bare:>6} tok  "
            f"n_ctx({config.n_ctx}) - max_tokens_per_draw({config.max_tokens_per_draw}) "
            f"= {threshold:>6}  {'OK' if clears else 'EXCEEDS'}"
        )
    lines.append(f"\nresult: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 4 — every gold term passes the funnel, and none leaks into a prompt
# --------------------------------------------------------------------------


def check_4() -> tuple[bool, list[str]]:
    lines = ["### Check 4 — gold terms pass run_funnel/score_semantic; none leak into a prompt\n"]
    resolver = ExperimentResolver()
    rows, drops = heldout_gold.verify(resolver)
    all_pass = all(row["funnel"] == ACCEPTED and row["mechfloor"] for row in rows)
    for row in rows:
        lines.append(
            f"{row['task']:<32} funnel={row['funnel']:<9} mechfloor={row['mechfloor']}"
        )
    if drops:
        for drop in drops:
            lines.append(f"DROPPED: {drop['task']:<32} {drop['reason']}")
    covers_all_eight = len(rows) == len(HELD_OUT_TASKS) and not drops
    offenders = heldout_gold.prompt_leak_check()
    lines.append(f"\ngold terms checked: {len(rows)}/{len(HELD_OUT_TASKS)}, drops={len(drops)}")
    if offenders:
        lines.append("LEAK — gold surface found in a built prompt:")
        for offender in offenders:
            lines.append(f"  {offender}")
    else:
        lines.append("no gold surface appears in any built prompt (none/full/typed)")
    ok = all_pass and covers_all_eight and not offenders
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Check 5 — route-reference extraction reproduces the 12/4,135 baseline
# --------------------------------------------------------------------------


def check_5() -> tuple[bool, list[str]]:
    lines = ["### Check 5 — route-reference extraction over the 4,135-draw baseline\n"]
    resolver = ExperimentResolver()
    stats = addressability_audit.refs(resolver)
    ok = stats["draws"] == 4135 and stats["ref_to_ALL_required_defs"] == 12
    lines.append(f"draws                      {stats['draws']:>5}  (expected 4135)")
    lines.append(f"ref_to_ALL_required_defs   {stats['ref_to_ALL_required_defs']:>5}  (expected 12)")
    lines.append(f"result: {'PASS' if ok else 'FAIL'}")
    return ok, lines


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def main() -> int:
    arms = _load_arms()
    checks = [
        ("1", lambda: check_1(arms)),
        ("2a", lambda: check_2a(arms)),
        ("2b", lambda: check_2b(arms)),
        ("2c", lambda: check_2c(arms)),
        ("3", lambda: check_3(arms)),
        ("4", check_4),
        ("5", check_5),
    ]
    all_ok = True
    for index, (number, fn) in enumerate(checks):
        if index:
            print()
        ok, lines = fn()
        for line in lines:
            print(line)
        all_ok = all_ok and ok

    print()
    print(f"### Deliverable 4 verdict: {'ALL CHECKS PASS' if all_ok else 'AT LEAST ONE CHECK FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
