"""Run every corpus-size-sweep arm end to end on the stub backend.

`docs/plans/2026-08-24-corpus-size-sweep.md`'s verification section. Same
method as `diversity_stub_check.py` (`docs/plans/2026-08-23-diversity-harvest.md`
step 6): the arms are loaded **as committed** and overlaid only with the stub
transport, a two-task subset and one seed, so what is exercised is the shipped
config, not a paraphrase of it.

Two things this prints that the plan's pre-registration depends on:

* **n_ctx headroom at the largest arm.** `sweep41` carries the most resolver
  content of the four; if it doesn't fit `n_ctx` with room to spare, none of
  the others will either, and the sweep needs a smaller max size before any
  GPU is touched.
* **Monotone prompt-token growth with store size.** The whole point of the
  sweep is that the four arms differ *only* in how much generated content the
  resolver carries. If `sweep08`'s prompt were the same size as `sweep41`'s,
  the resolver would not be doing what the store's definition counts say it
  is doing, and the pre-registered "mass" hypothesis would have nothing to
  bind to.

    python3 -m experiment.corpus_size_sweep_stub_check
"""

from __future__ import annotations

import sys
from pathlib import Path

import corpus_registry
from experiment import prompts, runner

ARMS = ("sweep08", "sweep15", "sweep25", "sweep41")
SIZES = {"sweep08": 8, "sweep15": 15, "sweep25": 25, "sweep41": 41}

CONFIG_DIR = Path(__file__).resolve().parent


def corpus_surface(task_id: str) -> str:
    """A definition the stub can emit that the checkers will accept.

    The same helper `test_harvest.corpus_surface` and `diversity_stub_check`
    use, so the stub emits a real curated definition rather than a hand-written
    surface that might drift from the corpus.
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
        # Context requirement against the *shipped* draw budget and regimes,
        # before the stub overlay shrinks them — otherwise this would report
        # the requirement of a two-task smoke run and the n_ctx guard would
        # mean nothing.
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
                "size": SIZES[name],
                "definitions": definitions,
                "digests": digests,
                "origins": summary["resolver_origins"],
                "required": required,
                "n_ctx": shipped.n_ctx,
                "records": len(records),
                "prompt_tokens": [row["tokens_prompt"] for row in records],
            }
        )

    header = f"{'arm':<10}{'size':>5}{'defs':>5}{'digests':>9}{'gen':>5}{'required':>10}{'n_ctx':>8}{'head':>7}{'recs':>6}  stub prompt tokens"
    print(header)
    for row in rows:
        print(
            f"{row['arm']:<10}{row['size']:>5}{row['definitions']:>5}{row['digests']:>9}"
            f"{row['origins'].get('generated', 0):>5}{row['required']:>10}"
            f"{row['n_ctx']:>8}{row['n_ctx'] / row['required']:>6.2f}x"
            f"{row['records']:>6}  {row['prompt_tokens']}"
        )

    largest = next(r for r in rows if r["arm"] == "sweep41")
    print()
    print(f"sweep41 headroom: n_ctx={largest['n_ctx']} required={largest['required']} "
          f"({largest['n_ctx'] / largest['required']:.2f}x)")
    if largest["n_ctx"] <= largest["required"]:
        print("FAIL: the largest arm does not fit n_ctx", file=sys.stderr)
        return 1

    # Nesting (§ pre-registration) implies each arm's resolver strictly grows;
    # the stub's prompt-token count over the same fixed two-task/one-seed
    # sample is the cheapest observable proxy for that without a GPU.
    ordered = sorted(rows, key=lambda r: r["size"])
    totals = [sum(r["prompt_tokens"]) for r in ordered]
    print(f"\nprompt-token totals by size (must be non-decreasing): "
          f"{list(zip([r['size'] for r in ordered], totals))}")
    if any(b < a for a, b in zip(totals, totals[1:])):
        print("FAIL: prompt tokens do not grow monotonically with store size", file=sys.stderr)
        return 1
    print("OK: sweep41 fits n_ctx with headroom, and prompt tokens grow monotonically with size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
