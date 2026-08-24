"""Score the diversity-harvest arms against the recorded baselines.

`docs/plans/2026-08-23-diversity-harvest.md` verification step 7. Written and
committed **before any arm was launched**, which is the point: every metric, every
comparison and every prediction threshold below is fixed in advance, so the
post-run job is to read numbers out rather than to decide which numbers to read.

    python3 -m experiment.diversity_report --runs-dir ../prototype/runs

It reports whatever it finds and says so about whatever it does not, so it is
runnable today against the recorded baselines alone — which is how it was
checked before the arms it exists to score existed.

The one metric that is new here
-------------------------------

`vacuous share of accepted` applies the harvest's own G1 and G2 gates to what
the model **emitted**, not to what was harvested. It is the mechanical companion
to the hand-scored rubric: a draw that is constant-valued, or that ignores a
parameter its type promised to consume, is type-correct and semantically empty,
and counting those needs no reviewer. Baselines from the recorded runs are
0.040 (turn 1) and 0.043 (turn 2) at `full_corpus`, 0.143 (1 of 7) at `held_out`.

What this deliberately does not do
----------------------------------

No significance test is computed for held-out acceptance. At n = 96 the recorded
arms are 4/96 and 7/96, Fisher p ≈ 0.35; printing a p-value per comparison would
invite reading one of them as a result. The plan moved the powered contrast to
`full_corpus` for exactly this reason, and the held-out columns are reported as
counts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import harvest_select

#: Recorded baselines, from docs/results/. Hard-coded rather than re-derived so
#: that a comparison is against the *published* number, and any drift between
#: this table and a re-read of the runs is itself a finding.
BASELINES = {
    ("curated", "full_corpus"): {"accepted": 55, "draws": 196, "acc_1k": 1.377, "distinct": 9},
    ("generated-t1", "full_corpus"): {"accepted": 72, "draws": 206, "acc_1k": 1.803, "distinct": 11},
    ("generated-t2", "full_corpus"): {"accepted": 69, "draws": 206, "acc_1k": 1.728, "distinct": 11},
    ("curated", "held_out"): {"accepted": 4, "attempts": 96, "acc_1k": 0.081, "distinct": 2},
    ("generated", "held_out"): {"accepted": 7, "attempts": 96, "acc_1k": 0.142, "distinct": 5},
}

#: Which run directory belongs to which arm of this plan.
ARM_RUNS = {
    "diverse-followup": "diverse",
    "sizematch-followup": "sizematch",
    "diverse-heldout12": "diverse",
    "sizematch-heldout12": "sizematch",
}


def is_vacuous(surface: str) -> bool | None:
    """G1 ∪ G2 applied to an emitted draw. `None` when it cannot be analysed."""
    try:
        shape = harvest_select.shape_of(surface)
    except harvest_select.SelectionError:
        return None
    return shape.is_constant or bool(shape.unused_parameters)


def read_run(directory: Path) -> dict | None:
    summary_path = directory / "summary.json"
    records_path = directory / "records.jsonl"
    if not (summary_path.is_file() and records_path.is_file()):
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {"name": directory.name, "summary": summary, "records": records}


def vacuity(records: list[dict], regime: str) -> tuple[int, int, int]:
    """(vacuous, accepted, unanalysable) among accepted draws in one regime."""
    accepted = [
        record
        for record in records
        if record.get("funnel_outcome") == "accepted" and record.get("regime") == regime
    ]
    vacuous = 0
    unanalysable = 0
    for record in accepted:
        verdict = is_vacuous((record.get("source") or "").rstrip("\n"))
        if verdict is None:
            unanalysable += 1
        elif verdict:
            vacuous += 1
    return vacuous, len(accepted), unanalysable


def cells(run: dict) -> dict[str, dict]:
    return {
        key.split("|", 1)[1]: cell
        for key, cell in run["summary"]["cells"].items()
    }


def mechanical_floor(records: list[dict]) -> list[dict]:
    """Held-out draws that clear the floor and therefore need hand scoring.

    Accepted by the funnel **and** an exact declared-type match. The rubric in
    the plan applies to exactly these and to nothing else, so listing them is
    what stops a semantic success from being scored selectively.
    """
    return [
        record
        for record in records
        if record.get("regime") == "held_out"
        and record.get("funnel_outcome") == "accepted"
        and record.get("semantic_success")
    ]


def render(runs: list[dict]) -> list[str]:
    out: list[str] = []
    out.append("## Metrics by arm × regime")
    out.append("")
    header = (
        f"{'arm / run':<26}{'regime':<13}{'draws':>7}{'acc':>5}{'acc/1k':>9}"
        f"{'distinct':>9}{'repeat':>8}{'sem':>5}{'vacuous':>9}"
    )
    out.append("```")
    out.append(header)
    for run in runs:
        for regime, cell in sorted(cells(run).items()):
            vacuous, accepted, unanalysable = vacuity(run["records"], regime)
            share = f"{vacuous / accepted:.3f}" if accepted else "—"
            if unanalysable:
                share += f" (+{unanalysable}?)"
            out.append(
                f"{run['name']:<26}{regime:<13}{cell['draws']:>7}{cell['accepted']:>5}"
                f"{cell['accepted_per_1k_tokens']:>9.3f}"
                f"{cell['distinct_accepted_identities']:>9}"
                f"{cell['repeated_definition_rate']:>8.3f}"
                f"{cell['semantic_successes']:>5}{share:>9}"
            )
    out.append("")
    out.append("recorded baselines")
    for (arm, regime), row in BASELINES.items():
        out.append(
            f"{arm:<26}{regime:<13}{row.get('draws', row.get('attempts', 0)):>7}"
            f"{row['accepted']:>5}{row['acc_1k']:>9.3f}{row['distinct']:>9}"
        )
    out.append("```")
    return out


def score(runs: list[dict]) -> list[str]:
    """The six pre-registered predictions, scored or reported unscoreable."""
    by_arm = {ARM_RUNS.get(run["name"]): run for run in runs if run["name"] in ARM_RUNS}
    heldout12 = {
        ARM_RUNS[run["name"]]: run
        for run in runs
        if run["name"] in ("diverse-heldout12", "sizematch-heldout12")
    }
    followup = {
        ARM_RUNS[run["name"]]: run
        for run in runs
        if run["name"] in ("diverse-followup", "sizematch-followup")
    }

    out = ["", "## Pre-registered predictions", ""]

    def line(tag: str, text: str, verdict: str) -> None:
        out.append(f"- **{tag}** — {text} → **{verdict}**")

    def acc(run, regime):
        cell = cells(run).get(regime)
        return cell["accepted_per_1k_tokens"] if cell else None

    # P1: diverse held-out acc/1k in [0.08, 0.25]
    diverse12 = heldout12.get("diverse")
    if diverse12 is None:
        line("P1", "diverse held_out acc/1k tok in [0.08, 0.25]", "NOT RUN")
    else:
        value = acc(diverse12, "held_out")
        line(
            "P1",
            f"diverse held_out acc/1k tok in [0.08, 0.25]; observed {value:.3f}",
            "HELD" if 0.08 <= value <= 0.25 else "FAILED",
        )

    # P2: zero hand-scored semantic successes.
    if diverse12 is None:
        line("P2", "zero held-out draws score 1 under the rubric", "NOT RUN")
    else:
        floor = mechanical_floor(diverse12["records"])
        line(
            "P2",
            f"zero held-out draws score 1 under the rubric; "
            f"{len(floor)} draw(s) met the mechanical floor and need hand scoring",
            "PENDING HAND SCORE" if floor else "HELD (nothing reached the floor)",
        )

    # P3: diverse > sizematch on held-out acc/1k.
    if "diverse" in heldout12 and "sizematch" in heldout12:
        a, b = acc(heldout12["diverse"], "held_out"), acc(heldout12["sizematch"], "held_out")
        line("P3", f"diverse {a:.3f} vs sizematch {b:.3f} at held_out",
             "HELD" if a > b else "FAILED")
    elif "diverse" in followup and "sizematch" in followup:
        a, b = acc(followup["diverse"], "held_out"), acc(followup["sizematch"], "held_out")
        line("P3", f"(followup shape only) diverse {a:.3f} vs sizematch {b:.3f} at held_out",
             "HELD" if a > b else "FAILED")
    else:
        line("P3", "diverse beats sizematch on held_out acc/1k tok", "NOT RUN")

    # P4: diverse full_corpus >= 1.377 and within +/-15% of 1.803/1.728.
    diverseF = followup.get("diverse")
    if diverseF is None:
        line("P4", "diverse full_corpus acc/1k tok >= 1.377 and within 15 % of 1.803/1.728",
             "NOT RUN")
    else:
        value = acc(diverseF, "full_corpus")
        band = [1.803, 1.728]
        within = any(abs(value - b) / b <= 0.15 for b in band)
        line(
            "P4",
            f"diverse full_corpus acc/1k tok {value:.3f} vs curated 1.377 and "
            f"turn 1/2 1.803/1.728, with 63 % fewer generated definitions",
            "HELD" if value >= 1.377 and within else "FAILED",
        )

    # P5: repeat rate below the 0.836-0.847 band.
    if diverseF is None:
        line("P5", "diverse repeat rate falls below the 0.836–0.847 band", "NOT RUN")
    else:
        cell = cells(diverseF).get("full_corpus")
        rate = cell["repeated_definition_rate"]
        line("P5", f"diverse full_corpus repeat rate {rate:.3f} vs the 0.836–0.847 band",
             "HELD" if rate < 0.836 else "FAILED")

    # P6: diverse emits fewer vacuous accepted draws than sizematch.
    if "diverse" in followup and "sizematch" in followup:
        shares = {}
        for arm in ("diverse", "sizematch"):
            vacuous, accepted, _ = vacuity(followup[arm]["records"], "full_corpus")
            shares[arm] = vacuous / accepted if accepted else float("nan")
        line(
            "P6",
            f"vacuous share of accepted at full_corpus: diverse {shares['diverse']:.3f} "
            f"vs sizematch {shares['sizematch']:.3f}",
            "HELD" if shares["diverse"] < shares["sizematch"] else "FAILED",
        )
    else:
        line("P6", "diverse emits a lower vacuous share than sizematch", "NOT RUN")

    return out


def hand_score_worksheet(runs: list[dict]) -> list[str]:
    """Every held-out draw that met the mechanical floor, ready to be scored."""
    out = ["", "## Hand-scoring worksheet (rubric in the plan)", ""]
    found = False
    for run in runs:
        for record in mechanical_floor(run["records"]):
            found = True
            out += [
                f"### {run['name']} · {record.get('task')} · "
                f"seed {record.get('seed')} draw {record.get('draw')}",
                "",
                "```",
                (record.get("source") or "").strip(),
                "```",
                "",
                "- spec: _(paste the task spec)_",
                "- score: _(1 only if it computes the specified function for every "
                "input of the declared type)_",
                "- reason: _(one line)_",
                "",
            ]
    if not found:
        out.append("No held-out draw met the mechanical floor in the runs present.")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="diversity_report")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="a run directory name to include; repeat. Default: every directory "
        "under --runs-dir that has both a summary.json and a records.jsonl.",
    )
    arguments = parser.parse_args(argv)

    names = arguments.run or sorted(p.name for p in arguments.runs_dir.iterdir() if p.is_dir())
    runs = []
    for name in names:
        run = read_run(arguments.runs_dir / name)
        if run is not None:
            runs.append(run)
    if not runs:
        print(f"no runs with summary.json + records.jsonl under {arguments.runs_dir}",
              file=sys.stderr)
        return 1

    lines = render(runs) + score(runs) + hand_score_worksheet(runs)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
