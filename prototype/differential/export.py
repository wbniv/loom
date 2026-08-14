"""`python3 -m differential export` — write the L0 JSON-lines export.

The file is byte-identical across runs on the same tree: there is no timestamp,
no host name, no path outside the repository, no dict-order dependence, and
every collection is sorted before it is written. That property is the point —
a consumer diffs two exports to see whether the reference moved, and a header
that changes every run makes the diff useless.

Layout, one JSON object per line:

  1. a `header` record — schema version, the seven contract versions this export
     was cut against, the fixture counts, and the per-layer verdict summary;
  2. every `environment` record, sorted by id — the declaration registries the
     cases refer to, lifted out of the cases because thousands share each one;
  3. every `case` record, in migration order (`parser` first, `policies` last),
     then by entry point, then by case id.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import SCHEMA_VERSION, jsonio
from .recorder import LAYER_ORDER, Recorder

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "l0.jsonl"


def collect(include_tests: bool = True) -> Recorder:
    """Install the harness, drive the fixtures (and the tests), return the cases."""
    from . import fixtures, instrument, suite

    recorder = Recorder()
    instrument.install(recorder)
    recorder.enabled = True
    try:
        fixtures.run(recorder)
        if include_tests:
            result = suite.run(recorder)
            # Recorded in the header, because a skipped test is the one way the
            # export can differ between two machines on the same tree: three of
            # the prototype's tests are conditional on a local SMT solver or a
            # seeded store, and if one of those runs it drives calls the others
            # do not. Stating which were skipped makes that visible in a diff
            # instead of showing up as an unexplained change in case counts.
            recorder.suite = {
                "modules": suite.modules(),
                "tests_run": result.testsRun,
                "skipped": sorted(test.id() for test, _ in result.skipped),
            }
            if not result.wasSuccessful():
                raise SystemExit(
                    "differential: the prototype test suite failed under instrumentation; "
                    f"{len(result.failures)} failures, {len(result.errors)} errors. "
                    "The export is only meaningful over a green suite."
                )
    finally:
        recorder.enabled = False
    return recorder


def header(recorder: Recorder, scope: str) -> dict:
    import contracts

    from .fixtures import sources

    fixture_names = [name for name, _ in sources()]
    counts = recorder.counts()
    document = {
        "record": "header",
        "schema_version": SCHEMA_VERSION,
        "generator": "prototype/differential",
        "scope": scope,
        "contracts": {name: contracts.VERSIONS[name] for name in sorted(contracts.VERSIONS)},
        "layers": list(LAYER_ORDER),
        "fixtures": {
            "corpus": sum(1 for name in fixture_names if name.startswith("corpus/")),
            "examples": sum(1 for name in fixture_names if name.startswith("examples/")),
        },
        "counts": {layer: counts.get(layer, {"accept": 0, "reject": 0}) for layer in LAYER_ORDER},
        "totals": {
            "cases": len(recorder.cases()),
            "environments": len(recorder.environment_records()),
            "accept": sum(bucket["accept"] for bucket in counts.values()),
            "reject": sum(bucket["reject"] for bucket in counts.values()),
            # Cases whose input contains a value `jsonio` could not represent.
            # A consumer cannot replay those, so the number is stated rather
            # than left for someone to discover by grepping for `$opaque`.
            "opaque_inputs": sum(
                1 for case in recorder.cases() if jsonio.contains_opaque(case.encoded_input)
            ),
        },
    }
    if recorder.suite is not None:
        document["suite"] = recorder.suite
    return document


def render(recorder: Recorder, scope: str) -> str:
    lines = [jsonio.canonical(header(recorder, scope))]
    lines += [jsonio.canonical(record) for record in recorder.environment_records()]
    lines += [jsonio.canonical(case.to_record()) for case in recorder.cases()]
    return "\n".join(lines) + "\n"


def summary(recorder: Recorder) -> str:
    counts = recorder.counts()
    width = max(len(layer) for layer in LAYER_ORDER)
    rows = [f"{'layer'.ljust(width)}  accepted  rejected     total"]
    total_accept = total_reject = 0
    for layer in LAYER_ORDER:
        bucket = counts.get(layer, {"accept": 0, "reject": 0})
        total_accept += bucket["accept"]
        total_reject += bucket["reject"]
        rows.append(
            f"{layer.ljust(width)}  {bucket['accept']:8d}  {bucket['reject']:8d}  {bucket['accept'] + bucket['reject']:8d}"
        )
    rows.append(
        f"{'ALL'.ljust(width)}  {total_accept:8d}  {total_reject:8d}  {total_accept + total_reject:8d}"
    )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m differential", description=__doc__.splitlines()[0])
    subcommands = parser.add_subparsers(dest="command", required=True)

    export = subcommands.add_parser("export", help="write the L0 JSON-lines export")
    export.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help=f"output path (default: {DEFAULT_OUTPUT})")
    export.add_argument(
        "--only",
        choices=("fixtures", "all"),
        default="all",
        help="'fixtures' drives only the 26 corpus entries, the 5 examples, and the pinned "
        "declarations/obligations/policies; 'all' also runs the prototype test suite (default)",
    )
    export.add_argument("--stdout", action="store_true", help="write the export to stdout instead of a file")

    arguments = parser.parse_args(argv)
    if arguments.command != "export":  # pragma: no cover - argparse enforces this
        parser.error(f"unknown command {arguments.command!r}")

    scope = "fixtures" if arguments.only == "fixtures" else "fixtures+tests"
    recorder = collect(include_tests=arguments.only == "all")
    text = render(recorder, scope)

    if arguments.stdout:
        sys.stdout.write(text)
    else:
        arguments.out.write_text(text, encoding="utf-8")
        print(f"wrote {arguments.out} ({len(text.encode('utf-8'))} bytes, scope={scope})")
    print(summary(recorder), file=sys.stderr if arguments.stdout else sys.stdout)
    return 0
