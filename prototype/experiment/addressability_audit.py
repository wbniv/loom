"""The independent, from-repository-data reproduction of plan §1's diagnostics.

[`docs/plans/2026-08-24-next-lever.md`](../../docs/plans/2026-08-24-next-lever.md)
§1 pastes six numbered blocks, produced by ad-hoc code during the design
session, to argue that two published reports' "0 of 22 non-vacuous defs solve
a held-out task" premise measures the wrong thing. This script is Deliverable
1: the same six blocks, recomputed here from the checked-in corpus, the
checked-in `.loom-store-*` exports, and the gitignored `prototype/runs/`
records, via the harness's own loaders — `experiment.resolver`,
`experiment.store_resolver`, `experiment.prompts`, `experiment.evaluate`, and
`experiment.runner`. No GPU, no network, and nothing here refers to §1's
pasted numbers; it computes its own.

Six sections, one function each, printed in this order by a bare invocation
(``python3 -m experiment.addressability_audit`` from `prototype/`), or singly
via ``--section``:

``solved``      §1.1 — five hand-written held-out solutions, curated-only,
                run through the harness's own `run_funnel` + `score_semantic`.
``routes``      §1.2's first table — per-task route addressability against the
                curated `held_out` prompt.
``stores``      §1.2's second table — the same check across every store size
                the project has exported.
``refs``        §1.2's third table — behavioural `(ref …)` rates over every
                held-out draw on record.
``censoring``   §1.3 — cell-budget truncation, held-out and `full_corpus`.
``addressbook`` §4's arm-sizing inputs — `addr-full`'s row count and token
                cost, and `addr-typed`'s per-task row count under §4.2's
                codomain-erasure filter. Not one of §1's pasted blocks (no
                exact table to diff against — §4.2 only states an inline
                7-13 range), included because Deliverable 1's brief asks for
                it and every other section already reuses this file's
                resolver-and-type-IR machinery.

The held-out draw universe (`refs` and the held-out half of `censoring`)
------------------------------------------------------------------------

`prototype/runs/` is gitignored (R1's working-tree note, plan §1.4), so
"every held-out draw on record" is not "every `records.jsonl` under
`prototype/runs/`" — the working tree also carries early Aug-13/14
prototyping runs (`phase-a-*`, `phase-b-*`, `followup-*`, `heldout12-*`) that
predate the harness the two 2026-08-24 reports and the 2026-08-23 powered A/B
report actually cite, plus one exact-duplicate file
(`sweep-runlist-20260824T162810Z/runs/records.jsonl` is byte-identical to
`sweep-size08/runs/records.jsonl` — the runlist landing commit's demo output,
not a second run). `HELD_OUT_RUN_FILES` below is the explicit, named list:
the three runs `diversity_report.py`'s `_RUN_LABELS` maps (`diverse-followup`,
`sizematch-followup`, `diverse-heldout12`), the two `docs/results/2026-08-23-
heldout-powered-report.md` names (`heldout-powered-curated`,
`heldout-powered-generated`), and the four `corpus_size_sweep_analysis.py`
points (`sweep-size{08,15,25,41}`). Summing their held-out draws gives
exactly 4,135 — the total every downstream number below is checked against.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from experiment import runner
from experiment.evaluate import run_funnel, score_semantic
from experiment.prompts import (
    HELD_OUT_TASKS,
    REGIME_HELD_OUT,
    address_row,
    build_prompt,
    estimated_tokens,
    ref_legal_objects,
    typed_address_rows,
)
from experiment.resolver import KIND_DATA, KIND_DEFINITION, KIND_EXTERN, ExperimentResolver
from experiment.store_resolver import POLICY_ALL, StoreResolver

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
CONFIG_DIR = Path(__file__).resolve().parent

#: See the module docstring. Order is print order for `refs`/`censoring`.
HELD_OUT_RUN_FILES = (
    ("heldout-powered-curated", RUNS_DIR / "heldout-powered-curated" / "records.jsonl"),
    ("heldout-powered-generated", RUNS_DIR / "heldout-powered-generated" / "records.jsonl"),
    ("sweep-size08", RUNS_DIR / "sweep-size08" / "runs" / "records.jsonl"),
    ("sweep-size15", RUNS_DIR / "sweep-size15" / "runs" / "records.jsonl"),
    ("sweep-size25", RUNS_DIR / "sweep-size25" / "runs" / "records.jsonl"),
    ("sweep-size41", RUNS_DIR / "sweep-size41" / "runs" / "records.jsonl"),
    ("diverse-followup", RUNS_DIR / "diverse-followup" / "records.jsonl"),
    ("sizematch-followup", RUNS_DIR / "sizematch-followup" / "records.jsonl"),
    ("diverse-heldout12", RUNS_DIR / "diverse-heldout12" / "records.jsonl"),
)

#: The four corpus-size-sweep store-size points, config name to run file — the
#: same nine-way split `corpus_size_sweep_analysis.py` reads, restricted here
#: to `full_corpus` for the store-size censoring rates.
SWEEP_SIZE_RUN_FILES = HELD_OUT_RUN_FILES[2:6]

#: §1.2's store-size table. `generated` reuses `followup_generated.config.json`
#: only for its `store_export`/`include_generated` fields — the config's own
#: run parameters (seeds, budget) are irrelevant here, since this section only
#: ever builds a resolver from it, never runs a cell.
STORE_SIZE_CONFIGS = (
    ("sweep08", "sweep08.config.json"),
    ("sweep15", "sweep15.config.json"),
    ("sweep25", "sweep25.config.json"),
    ("sweep41", "sweep41.config.json"),
    ("generated", "followup_generated.config.json"),
)

_REF_RE = re.compile(r"\(ref (0x[0-9a-f]{64})\)")


def _load_records(path: Path, regime: str):
    """Every record in one `records.jsonl` matching `regime`, tagged with `path`.

    The tag matters: two arms of the same A/B (`heldout-powered-curated` vs
    `-generated`) can share every one of `(task, condition, regime, seed)`, so
    grouping into cells without the source file would silently merge two
    different cells' draws into one.
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("regime") == regime:
                record["_source"] = str(path)
                yield record


def _cell_key(record: dict) -> tuple:
    return (record["_source"], record["task"], record["condition"], record["regime"], record["seed"])


def _group_cells(records) -> dict[tuple, list[dict]]:
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for record in records:
        cells[_cell_key(record)].append(record)
    for draws in cells.values():
        draws.sort(key=lambda r: r["draw"])
    return cells


# --------------------------------------------------------------------------
# §1.1 — the pool already contains the compositions
# --------------------------------------------------------------------------

#: Five held-out tasks solved by hand, curated definitions only, exactly the
#: two-definition route `Task.composes` records for each. Written directly
#: against the corpus's own canonical IR encoding (`corpus/*.loom.sexpr`):
#: `List I64` is `(data 0x2ee931a3… (I64))`, `Maybe I64` is
#: `(data 0x3ff21047… (I64))`, and every corpus call is a bare `(ref HASH)` —
#: these are fixtures for `run_funnel`/`score_semantic`, never shown to a
#: model, exactly like `composes` itself (plan §4.4 pins the same rule for
#: Deliverable 3's gold terms).
_LIST_T = "(data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64))"
_MAYBE_T = "(data 0x3ff2104702aeeb53b4dfbc5a09c0441df19f12883e6cf66e21a3bd85420b4e2f (I64))"
_APPEND = "0x32f5d833f0b7c42ea8252e7ec8810657e9e9d132d395d30a7259e683bc31f791"
_LIST_SIZE = "0x4bd80df0fc10754098795f5fe2bd676a20f933192622f10455b7f55dff5ad5ae"
_MAP = "0x617903dc2f185adc90f658f482357c9961001882d693cab0c4701ae518e21ade"
_REVERSE = "0x9d677953e4471fb4b1c80accfd4f2cb48d59b08073a9e431f74bd1f0020e249b"
_MAYBE_MAP = "0xa4b7f01ca0cbe6e6fd3494feb556cb6b7c8c4453152e7797e201f1b5e5449cf4"
_GET_OR_ELSE = "0x2dc64240af4f0bf328f1572c9cd09bca3bed789d5a150a3a8d0c0825b4ad2a2a"
_FOLD_LEFT = "0x7c880749df1f488a834cc9b2352d0d064dba904e2c7cfd83af762cee2d3b665f"
_I64_ADD = "0x23d1e0891aef622110302fe247b7148de5eb61a09f30138cfe7bd09d6cf7e6d7"

HAND_SOLVED = {
    # append(list1, list2) then measure — the assumed-base primitive over the
    # curated composition.
    "heldout/list/concatLength": (
        f"(def (fn {_LIST_T} () (fn {_LIST_T} () I64)) "
        f"(lam {_LIST_T} (lam {_LIST_T} (app (ref {_LIST_SIZE}) "
        f"(app (app (ref {_APPEND}) (var 1)) (var 0))))))"
    ),
    # map(f, list) then measure — a higher-order argument threaded through.
    "heldout/list/mapLength": (
        f"(def (fn (fn I64 () I64) () (fn {_LIST_T} () I64)) "
        f"(lam (fn I64 () I64) (lam {_LIST_T} (app (ref {_LIST_SIZE}) "
        f"(app (app (ref {_MAP}) (var 1)) (var 0))))))"
    ),
    # append(reverse(list1), list2) — two corpus calls in sequence.
    "heldout/list/reverseThen": (
        f"(def (fn {_LIST_T} () (fn {_LIST_T} () {_LIST_T})) "
        f"(lam {_LIST_T} (lam {_LIST_T} (app (app (ref {_APPEND}) "
        f"(app (ref {_REVERSE}) (var 1))) (var 0)))))"
    ),
    # getOrElse(default, map(f, opt)) — composition order is the whole task.
    "heldout/maybe/mapOrElse": (
        f"(def (fn (fn I64 () I64) () (fn {_MAYBE_T} () (fn I64 () I64))) "
        f"(lam (fn I64 () I64) (lam {_MAYBE_T} (lam I64 "
        f"(app (app (ref {_GET_OR_ELSE}) (var 0)) "
        f"(app (app (ref {_MAYBE_MAP}) (var 2)) (var 1)))))))"
    ),
    # foldLeft(I64.add, 0, list) — a fold whose combiner is an extern ref.
    "heldout/list/sum": (
        f"(def (fn {_LIST_T} () I64) "
        f"(lam {_LIST_T} (app (app (app (ref {_FOLD_LEFT}) (ref {_I64_ADD})) "
        f"(lit i64 0)) (var 0))))"
    ),
}


def solved(resolver: ExperimentResolver) -> list[dict]:
    """§1.1 — run every `HAND_SOLVED` fixture through the real funnel + scorer."""
    tasks = {task.task_id: task for task in HELD_OUT_TASKS}
    rows = []
    for task_id, surface in HAND_SOLVED.items():
        task = tasks[task_id]
        funnel = run_funnel(surface, resolver)
        semantic = score_semantic(task, funnel, surface)
        rows.append(
            {
                "task": task_id,
                "chars": len(surface),
                # §1.1's own measured completion tokenization: 1.37 ch/token,
                # median over `len(record["raw"]) / record["tokens_completion"]`
                # across the 4,135 held-out draws on record (see `refs`) — not
                # `prompts.CHARS_PER_TOKEN`, which is the prompt-side estimate.
                "completion_tokens": round(len(surface) / 1.37),
                "funnel": funnel.outcome,
                "mechfloor": semantic.success,
            }
        )
    return rows


# --------------------------------------------------------------------------
# §1.2 (table 1) — per-task route addressability, curated `held_out` prompt
# --------------------------------------------------------------------------


def routes(resolver: ExperimentResolver) -> list[dict]:
    """Every held-out task's route, checked against its own real prompt."""
    rows = []
    for task in HELD_OUT_TASKS:
        prompt = build_prompt(task, REGIME_HELD_OUT, resolver)
        elements = []
        for name in task.composes:
            digest_hex = resolver.digest_for(name).hex()
            present = digest_hex in prompt
            elements.append((name.removeprefix("corpus/"), present))
        rows.append(
            {
                "task": task.task_id,
                "ok": all(present for _, present in elements),
                "elements": elements,
            }
        )
    return rows


# --------------------------------------------------------------------------
# §1.2 (table 2) — addressability across every exported store size
# --------------------------------------------------------------------------


def stores() -> list[dict]:
    """`routes`'s all-elements-present check, generalized over store exports."""
    curated = ExperimentResolver()
    curated_hashes = {found.hex for found in curated.definitions()}
    rows = []
    for label, config_name in STORE_SIZE_CONFIGS:
        config = runner.Config.load(CONFIG_DIR / config_name)
        resolver = runner.make_resolver(config)
        reference_task = HELD_OUT_TASKS[0]
        reference_prompt = build_prompt(reference_task, REGIME_HELD_OUT, resolver)
        reach = sum(1 for digest_hex in curated_hashes if digest_hex in reference_prompt)
        addressable = []
        for task in HELD_OUT_TASKS:
            prompt = build_prompt(task, REGIME_HELD_OUT, resolver)
            if all(resolver.digest_for(name).hex() in prompt for name in task.composes):
                addressable.append(task.task_id.rsplit("/", 1)[-1])
        rows.append(
            {
                "store": label,
                "defs": len(list(resolver.definitions())),
                "prompt_chars": len(reference_prompt),
                "reach_of_26": reach,
                "tasks_addressable": len(addressable),
                "which": addressable,
            }
        )
    return rows


# --------------------------------------------------------------------------
# §1.2 (table 3) — behavioural ref rates over every held-out draw on record
# --------------------------------------------------------------------------


def _route_hashes(resolver: ExperimentResolver, *, definitions_only: bool) -> dict[str, set[str]]:
    """Each held-out task's route, as a set of `0x`-prefixed digests.

    `definitions_only` drops the route's extern half (`List.size`, `I64.add`,
    …). The two "required" rows in §1.2's draws table need it: an extern's
    hash is common in a draw's `(ref …)` set regardless of task (33.5% of all
    draws ref *some* extern, §1.2), so counting a route "hit" on an extern
    alone conflates "the model knows a common extern hash" with "the model
    referenced this task's specific route" — the corpus-definition half is the
    one the addressing question is actually about (the externs are never
    rendered as examples either, per §1.2's prose, so they get their own
    reported category, `ref_to_extern`, rather than folding into this one).
    """
    out = {}
    for task in HELD_OUT_TASKS:
        hashes = set()
        for name in task.composes:
            digest = resolver.digest_for(name)
            if definitions_only:
                kind = resolver.resolve(digest).kind
                if kind != KIND_DEFINITION:
                    continue
            hashes.add("0x" + digest.hex())
        out[task.task_id] = hashes
    return out


def refs(resolver: ExperimentResolver) -> dict:
    """§1.2's draws table, over `HELD_OUT_RUN_FILES`."""
    required_any = _route_hashes(resolver, definitions_only=False)
    required_defs = _route_hashes(resolver, definitions_only=True)

    total = has_any = to_corpus = to_extern = to_data = to_required = to_all_required = 0
    for _, path in HELD_OUT_RUN_FILES:
        for record in _load_records(path, REGIME_HELD_OUT):
            total += 1
            draw_refs = {match.lower() for match in _REF_RE.findall(record.get("raw", ""))}
            if draw_refs:
                has_any += 1
            any_corpus = any_extern = any_data = False
            for digest_hex in draw_refs:
                try:
                    found = resolver.resolve(bytes.fromhex(digest_hex[2:]))
                except LookupError:
                    continue
                any_corpus = any_corpus or found.kind == KIND_DEFINITION
                any_extern = any_extern or found.kind == KIND_EXTERN
                any_data = any_data or found.kind == KIND_DATA
            to_corpus += any_corpus
            to_extern += any_extern
            to_data += any_data
            required = required_defs.get(record["task"], set())
            if draw_refs & required:
                to_required += 1
            if required and required <= draw_refs:
                to_all_required += 1
    return {
        "draws": total,
        "has_any_ref": has_any,
        "ref_to_corpus_def": to_corpus,
        "ref_to_extern": to_extern,
        "ref_to_DATA_hash": to_data,
        "ref_to_a_REQUIRED_def": to_required,
        "ref_to_ALL_required_defs": to_all_required,
    }


# --------------------------------------------------------------------------
# §1.3 — cell censoring
# --------------------------------------------------------------------------


def _cell_stats(cells: dict[tuple, list[dict]]) -> dict:
    n = len(cells)
    draws_per_cell = [len(draws) for draws in cells.values()]
    truncated = sum(
        1 for draws in cells.values() if draws[-1]["stop_reason"] == "length" and draws[-1]["cell_done"]
    )
    first_tokens = [draws[0]["tokens_completion"] for draws in cells.values()]
    first_over_400 = sum(1 for tokens in first_tokens if tokens >= 400)
    non_truncated = [sum(1 for r in draws if r["stop_reason"] != "length") for draws in cells.values()]
    total_draws = sum(draws_per_cell)
    truncated_draws = sum(
        1 for draws in cells.values() for record in draws if record["stop_reason"] == "length"
    )
    return {
        "cells": n,
        "draws": total_draws,
        "draws_per_cell_mean": round(statistics.mean(draws_per_cell), 2) if n else 0.0,
        "draws_per_cell_median": statistics.median(draws_per_cell) if n else 0.0,
        "cells_truncated": truncated,
        "cells_truncated_pct": round(100 * truncated / n, 1) if n else 0.0,
        "truncated_draws": truncated_draws,
        "truncated_draws_pct": round(100 * truncated_draws / total_draws, 1) if total_draws else 0.0,
        "first_draw_tokens_mean": round(statistics.mean(first_tokens), 1) if n else 0.0,
        "first_draw_tokens_median": statistics.median(first_tokens) if n else 0.0,
        "first_draw_over_400": first_over_400,
        "first_draw_over_400_pct": round(100 * first_over_400 / n, 1) if n else 0.0,
        "non_truncated_per_cell_mean": round(statistics.mean(non_truncated), 2) if n else 0.0,
        "non_truncated_per_cell_median": statistics.median(non_truncated) if n else 0.0,
    }


def censoring() -> dict:
    """§1.3 — held-out cell censoring, and `full_corpus`'s per-store-size rate."""
    held_out_records = []
    stop_reason_tally: Counter = Counter()
    for _, path in HELD_OUT_RUN_FILES:
        batch = list(_load_records(path, REGIME_HELD_OUT))
        held_out_records.extend(batch)
    held_out_cells = _group_cells(held_out_records)
    for draws in held_out_cells.values():
        for record in draws:
            stop_reason_tally[(record["stop_reason"], record["cell_done"])] += 1
    held_out = _cell_stats(held_out_cells)
    held_out["stop_reason_x_cell_done"] = dict(stop_reason_tally)

    per_size = {}
    all_full_corpus_records = []
    for label, path in SWEEP_SIZE_RUN_FILES:
        batch = list(_load_records(path, "full_corpus"))
        all_full_corpus_records.extend(batch)
        cells = _group_cells(batch)
        stats = _cell_stats(cells)
        per_size[label] = stats
    full_corpus_all = _cell_stats(_group_cells(all_full_corpus_records))

    return {"held_out": held_out, "full_corpus_by_size": per_size, "full_corpus_pooled": full_corpus_all}


# --------------------------------------------------------------------------
# §4 — address-book sizing (not one of §1's pasted blocks)
# --------------------------------------------------------------------------


def addressbook(resolver: ExperimentResolver) -> dict:
    """`addr-full`'s row count/size, and `addr-typed`'s per-task row count.

    §4.2's filter, applied literally: object `o` is listed for task `t` iff
    some k in {0,1,2,3} has `o`'s k-th codomain erasing to `t`'s body goal, or
    `o`'s type is a bare `forall`. Static and task-declared-type-only, exactly
    as §4.2 requires — it never looks at `composes` or a gold term.

    Deliverable 2 landed that filter in `experiment.prompts` as the thing the
    arms are actually built from, so this section now *calls* it rather than
    carrying a second copy: the sizing reported here and the block a run ships
    cannot drift apart. `full_book_chars` stays the rows alone, which is what
    §3's 9,202 counts — `prompts.ADDRESS_HEADER` is not part of the sizing.
    """
    ref_legal = ref_legal_objects(resolver)
    full_rows = [address_row(found) for found in ref_legal]
    full_block = "\n".join(full_rows)

    by_row = {address_row(found): found.name for found in ref_legal}
    typed_counts = {
        task.task_id: [by_row[row] for row in typed_address_rows(resolver, task.expected_type_surface)]
        for task in HELD_OUT_TASKS
    }

    return {
        "ref_legal_objects": len(ref_legal),
        "full_book_chars": len(full_block),
        "full_book_tokens": estimated_tokens(full_block),
        "typed_rows_by_task": {task_id: len(names) for task_id, names in typed_counts.items()},
        "typed_which_by_task": typed_counts,
    }


# --------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------


def print_solved(rows: list[dict]) -> None:
    print("### 1.1 Five held-out tasks solved by hand, curated definitions only\n")
    for row in rows:
        print(
            f"{row['task']:<32} chars={row['chars']:>4}  ~{row['completion_tokens']} completion tokens  "
            f"funnel={row['funnel']}  mechfloor={row['mechfloor']}"
        )


def print_routes(rows: list[dict]) -> None:
    print("### 1.2 Per-task route addressability (curated held_out prompt)\n")
    for row in rows:
        status = "OK" if row["ok"] else "BLOCKED"
        parts = "  ".join(f"{name}={'present' if present else 'ABSENT'}" for name, present in row["elements"])
        print(f"{row['task']:<32} {status:<8} {parts}")


def print_stores(rows: list[dict]) -> None:
    print("### 1.2 Addressability across every exported store size\n")
    header = f"{'store':<10}{'defs':>5}{'prompt':>8}{'reach/26':>9}  tasks addressable      which"
    print(header)
    for row in rows:
        print(
            f"{row['store']:<10}{row['defs']:>5}{row['prompt_chars']:>8}{row['reach_of_26']:>9}"
            f"  {len(row['which'])}/8" + " " * (24 - len(f"{len(row['which'])}/8"))
            + f"{row['which']}"
        )


def print_refs(stats: dict) -> None:
    print("### 1.2 Behavioural ref rates over every held-out draw on record\n")
    total = stats["draws"]
    for key in (
        "draws", "has_any_ref", "ref_to_corpus_def", "ref_to_extern",
        "ref_to_DATA_hash", "ref_to_a_REQUIRED_def", "ref_to_ALL_required_defs",
    ):
        count = stats[key]
        pct = 100 * count / total if total else 0.0
        label = key if key != "ref_to_DATA_hash" else "ref_to_DATA_hash(illegal)"
        print(f"{label:<34}{count:>5}  {pct:>5.1f}%")


def print_censoring(stats: dict) -> None:
    print("### 1.3 Cell censoring — held-out\n")
    held_out = stats["held_out"]
    tally = held_out["stop_reason_x_cell_done"]
    print(f"cross-tab stop_reason x cell_done: Counter({dict(tally)!r})")
    print(f"cells={held_out['cells']}  draws/cell: mean {held_out['draws_per_cell_mean']} "
          f"median {held_out['draws_per_cell_median']}")
    print(f"cells terminated by a truncated draw: {held_out['cells_truncated']}/{held_out['cells']} "
          f"= {held_out['cells_truncated_pct']}%")
    print(f"FIRST draw of each cell: mean {held_out['first_draw_tokens_mean']:.0f} "
          f"median {held_out['first_draw_tokens_median']:.0f}")
    print(f"cells whose first draw alone consumed >=400 of the 512-token cell budget: "
          f"{held_out['first_draw_over_400']}/{held_out['cells']} = {held_out['first_draw_over_400_pct']}%")
    print(f"non-truncated draws per cell: mean {held_out['non_truncated_per_cell_mean']} "
          f"median {held_out['non_truncated_per_cell_median']}")

    print("\n### 1.3 Cell censoring — full_corpus\n")
    pooled = stats["full_corpus_pooled"]
    print(f"full_corpus: {pooled['cells_truncated']}/{pooled['cells']} cells truncated "
          f"({pooled['cells_truncated_pct']}%), {pooled['non_truncated_per_cell_mean']} usable draws/cell")
    rates = ", ".join(
        f"{label}={stats['full_corpus_by_size'][label]['truncated_draws_pct']:.1f}%"
        for label, _ in SWEEP_SIZE_RUN_FILES
    )
    print(f"truncated-draw rate by store size (flat, per plan §1.3): {rates}")


def print_addressbook(stats: dict) -> None:
    print("### 4 Address-book sizing (not one of §1's pasted blocks — see module docstring)\n")
    print(f"ref-legal objects (addr-full rows): {stats['ref_legal_objects']}")
    print(f"addr-full block: {stats['full_book_chars']} characters, "
          f"~{stats['full_book_tokens']} prompt tokens")
    print("\naddr-typed rows by task (§4.2's codomain-erasure filter):")
    for task_id, count in stats["typed_rows_by_task"].items():
        print(f"  {task_id:<32} {count:>3} rows  {sorted(stats['typed_which_by_task'][task_id])}")
    counts = list(stats["typed_rows_by_task"].values())
    print(f"\nrange across the 8 tasks: {min(counts)}-{max(counts)} "
          f"(plan §4.2 states 7-13 inline; no pasted table to diff against — see docstring)")


SECTIONS = {
    "solved": (lambda resolver: print_solved(solved(resolver))),
    "routes": (lambda resolver: print_routes(routes(resolver))),
    "stores": (lambda resolver: print_stores(stores())),
    "refs": (lambda resolver: print_refs(refs(resolver))),
    "censoring": (lambda resolver: print_censoring(censoring())),
    "addressbook": (lambda resolver: print_addressbook(addressbook(resolver))),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--section", choices=sorted(SECTIONS), default=None,
        help="print one section only; default prints all six in a fixed order",
    )
    arguments = parser.parse_args()

    resolver = ExperimentResolver()
    order = [arguments.section] if arguments.section else [
        "solved", "routes", "stores", "refs", "censoring", "addressbook",
    ]
    for index, name in enumerate(order):
        if index:
            print()
        SECTIONS[name](resolver)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
