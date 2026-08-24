"""Run every diversity-harvest arm end to end on the stub backend.

`docs/plans/2026-08-23-diversity-harvest.md` verification step 6. The arms are
loaded **as committed** and overlaid only with the stub transport, a two-task
subset and one seed — so what is exercised is the shipped config, not a
paraphrase of it.

Why a script and not only a test: the numbers it prints (per-arm prompt tokens,
resolver composition, context requirement against `n_ctx`) are what the plan's
verification section has to paste, and a test that asserts them silently is not
evidence anybody can read. `test_diversity_arms.py` carries the assertions; this
prints the table.

    python3 -m experiment.diversity_stub_check
"""

from __future__ import annotations

import sys
from pathlib import Path

import corpus_registry
from experiment import prompts, runner

ARMS = (
    "diverse_followup",
    "sizematch_followup",
    "diverse_heldout12",
    "sizematch_heldout12",
)

CONFIG_DIR = Path(__file__).resolve().parent


def corpus_surface(task_id: str) -> str:
    """A definition the stub can emit that the checkers will accept.

    The same helper `test_harvest.corpus_surface` uses, so the stub emits a real
    curated definition rather than a hand-written surface that might drift from
    the corpus.
    """
    entry = next(e for e in corpus_registry.MANIFEST if e.name_path == task_id)
    return entry.source_text().rstrip("\n")


def stubbed(config):
    config.backend = "stub"
    config.model_identity = "stub"
    config.tasks = ["corpus/bool/not", "heldout/maybe/mapOrElse"]
    config.seeds = [1]
    config.max_draws_per_task = 2
    config.token_budget_per_task = 200
    config.max_tokens_per_draw = 200
    config.stub_outputs = [corpus_surface("corpus/bool/not")]
    config.stub_grammar_outputs = list(config.stub_outputs)
    config.stub_masked_outputs = list(config.stub_outputs)
    config.validate()
    return config


def main() -> int:
    rows = []
    for name in ARMS:
        shipped = runner.Config.load(CONFIG_DIR / f"{name}.config.json")
        resolver = runner.make_resolver(shipped)
        # The context requirement is computed against the *shipped* draw budget
        # and regimes, before the stub overlay shrinks them — otherwise this
        # would report the requirement of a two-task smoke run and the `n_ctx`
        # guard would mean nothing.
        required = prompts.context_required(
            shipped.regimes, resolver, draw_tokens=shipped.max_tokens_per_draw
        )
        definitions = len(list(resolver.definitions()))
        digests = len(resolver.digests())

        records, summary = runner.run(stubbed(runner.Config.load(CONFIG_DIR / f"{name}.config.json")))
        if not records:
            print(f"{name}: NO RECORDS", file=sys.stderr)
            return 1
        rows.append(
            {
                "arm": name,
                "definitions": definitions,
                "digests": digests,
                "origins": summary["resolver_origins"],
                "required": required,
                "n_ctx": shipped.n_ctx,
                "records": len(records),
                "prompt_tokens": [row["tokens_prompt"] for row in records],
            }
        )

    header = f"{'arm':<22}{'defs':>5}{'digests':>9}{'gen':>5}{'required':>10}{'n_ctx':>8}{'head':>7}{'recs':>6}  stub prompt tokens"
    print(header)
    for row in rows:
        print(
            f"{row['arm']:<22}{row['definitions']:>5}{row['digests']:>9}"
            f"{row['origins'].get('generated', 0):>5}{row['required']:>10}"
            f"{row['n_ctx']:>8}{row['n_ctx'] / row['required']:>6.2f}x"
            f"{row['records']:>6}  {row['prompt_tokens']}"
        )

    # The arms must differ in what the model is *shown*, not only in what
    # resolves. Equal prompt tokens would mean the A/B had quietly collapsed
    # into a test of the references layer — the escalation the corpus-loop plan
    # raised and resolved, restated for these arms.
    diverse = next(r for r in rows if r["arm"] == "diverse_followup")
    sizematch = next(r for r in rows if r["arm"] == "sizematch_followup")
    print()
    print(f"diverse vs sizematch prompt tokens : {diverse['prompt_tokens']} vs {sizematch['prompt_tokens']}")
    print(f"context required                   : {diverse['required']} vs {sizematch['required']}")
    if diverse["prompt_tokens"] == sizematch["prompt_tokens"]:
        print("FAIL: the two arms build identical prompts", file=sys.stderr)
        return 1
    print("OK: the arms differ in what the model is shown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
