"""Harvest a run's accepted draws into the store, honestly labelled.

`docs/plans/2026-08-14-corpus-loop.md` R1 and R2 are this module's whole
specification. It is the second half of the seam
[`store_admit.py`](store_admit.py) opened: that module knows how to turn one
definition surface into object bytes plus a sidecar; this one knows which
surfaces a run produced, what is true about where they came from, and how to
get them into a store without believing anything the run said about them.

What it does *not* do is decide whether a generated object is any good. There
is no ranking, no curation policy and no promotion here (R5); the store gains
objects labelled `origin: generated`, and
[`experiment.store_resolver`](experiment/store_resolver.py)'s origin filter
keeps them out of every curated-arm prompt until an experiment arm asks for
them by name.

The three rules that shape the code
-----------------------------------

**The run's verdict is evidence about the run, not about the object.** A record
saying ``funnel_outcome: accepted`` selects the draw; it does not admit it.
Every selected surface goes back through `store_admit.definition_sidecar`,
which runs parser → scope → references → typecheck against the store's *current*
contents and with the §3.3 subsumption collector threaded. A draw the run
accepted and admission refuses is a finding — contract drift, or a corpus that
has moved under it — and it is reported in its own category with the refusing
layer's own error class. It is never dropped, and it never becomes a crash.
The same applies to the recorded `identity`: it is re-derived from the bytes and
a mismatch is refused at the `identity` layer rather than trusted.

**Counting is the deliverable.** One line of JSON, the store CLI's protocol,
carrying `admitted` / `exists` / `refused_on_readmission` — and their sum is
asserted equal to the number of accepted records, so the line cannot quietly
lose a draw. `exists` is not an error: content addressing makes deduplication
free, and a run that drew the same definition seventy-one times *should* say so.

**Nothing in a sidecar may depend on when or where the harvest ran.** The
store's completion criterion is byte-identity on re-seeding, so `sequence`,
`name` and `provenance` are all functions of the records file alone:

* ``sequence`` is `SEQUENCE_BASE_GENERATED` plus the position, among accepted
  records, of the first record that produced this identity. The base reserves a
  band far above the curated corpus's dependency order, which is what makes
  "curated definitions come first, in manifest order, in every store" true by
  construction rather than by harvest ordering.
* ``name`` is ``generated/<task id>/<hash prefix>`` — see `object_name`.
* ``provenance.source`` is the run's own path suffix, never an absolute path.

Idempotence follows: harvesting the same records into the same store a second
time re-derives byte-identical sidecars, every `put` reports `exists`, and the
reported line says `admitted: 0`.

Usage
-----

    python3 harvest.py --records runs/phase-b/records.jsonl        # into $LOOM_STORE
    python3 harvest.py --records runs/phase-b/records.jsonl --dry-run \\
        --resolver .loom-store/export-resolver.json

`--dry-run` re-validates and counts without touching the store, and takes its
resolver from an export document instead of from the binary, so the whole
admission path is exercised on a checkout with no Rust toolchain — which is
what lets `test_harvest.py` be a real test rather than a mock.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import harvest_select
import store_admit
from definition_types import DefinitionTypeRegistry
from experiment.store_resolver import POLICY_ALL, StoreResolver

#: Where the generated band of `sequence` starts. Curated objects are numbered
#: from 0 in the admitter's dependency order (47 of them today), so this leaves
#: four orders of magnitude of headroom and guarantees that every generated
#: definition sorts after every curated one in `export-resolver`, in any store,
#: whatever order the harvests ran in.
#:
#: Two runs harvested into one store therefore *share* the band and can land on
#: the same `sequence`. That is deliberate rather than overlooked: `sequence`
#: orders the curated corpus, where it carries the manifest's dependency order,
#: and generated objects have no order to carry. `export_resolver` sorts by
#: `(sequence, hash)`, so a tie is broken deterministically and the document
#: stays reproducible; what it is not is meaningful across runs. Making it
#: meaningful would mean allocating per-run bands from store state, which would
#: put the harvest's output at the mercy of harvest order — the one thing the
#: byte-identity criterion forbids.
SEQUENCE_BASE_GENERATED = 1_000_000

#: The §5.2 metadata-name prefix every generated object carries. It is a name,
#: not a §5.3 namespace binding — v0 has no bindings — but it is *reserved*: the
#: curated corpus names everything under `corpus/`, so the two populations
#: cannot collide, and `StoreResolver` refuses a rebind if they ever do.
NAME_PREFIX = "generated"

#: How much of the identity goes into the name. 48 bits, git's own "unambiguous
#: in a large repository" abbreviation length; the full identity is in the
#: sidecar's `hash` field, so this is a label, never a lookup key.
NAME_HASH_PREFIX = 12

ACCEPTED = "accepted"

#: `put` outcomes, as the store CLI spells them.
WRITTEN = "written"
EXISTS = "exists"

#: Refusal layer for "the bytes do not hash to the identity the run recorded".
#: Not one of the validator layers — it is the store's own invariant, checked
#: here because this is where a stale record could smuggle a wrong hash in.
LAYER_IDENTITY = "identity"


class HarvestError(RuntimeError):
    """The harvest cannot proceed, and says why on one line."""


@dataclass(frozen=True)
class RunSource:
    """One run's records, with the run block every object from it will carry.

    The harvest used to take exactly one records file, so the run block was a
    property of the whole pass. A diversity-seeking selection needs a *pool* —
    the same structural class may be produced first in one run and best in
    another — so a pass now carries several, and each record's provenance comes
    from the run it was actually drawn in.

    `label` is `source_label`'s machine-independent path suffix, and it is also
    the sort key: sources are ordered by label, never by the order the operator
    typed them, so the output is a function of the *set* of runs harvested.
    """

    label: str
    run: dict
    records: tuple[dict, ...]


# ---------------------------------------------------------------------------
# The run, as the harvest needs it
# ---------------------------------------------------------------------------


def read_records(path: Path) -> list[dict]:
    """Every record in a run's JSONL, in the order the run wrote them."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise HarvestError(f"cannot read records {path}: {error}") from None
    records = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise HarvestError(f"{path}:{number}: not JSON: {error}") from None
    return records


def accepted_records(records: list[dict]) -> list[dict]:
    """R1's selection, and nothing looser: `funnel_outcome == accepted`."""
    return [record for record in records if record.get("funnel_outcome") == ACCEPTED]


def run_identity(summary: dict, records_path: Path) -> dict:
    """The run block every harvested object carries, from the run's summary.

    R2 wants "enough to reconstruct exactly which process produced the bytes",
    and the per-draw half of that (condition, regime, seed, draw) is in each
    record. The per-run half — which model, on which hardware, at which moment —
    exists only in `summary.json`, which is why the harvest requires one.

    A run with no recorded `model_identity` is refused rather than admitted
    unlabelled. That is the same rule the runner applies before a live run
    (R2.1's "recorded, not reconstructed"), applied at the other end: an object
    that cannot say which model produced it has no business being provenance.
    """
    config = summary.get("config") or {}
    model_identity = config.get("model_identity") or ""
    if not model_identity:
        raise HarvestError(
            "the run summary records no model_identity; refusing to admit "
            "generations that cannot say which model produced them "
            "(R2). Set it in the run config, or pass --model-identity for a "
            "run whose identity is known but unrecorded."
        )
    started = summary.get("started_utc") or ""
    return {
        "run_id": f"{records_path.parent.name}@{started}",
        "started_utc": started,
        "model_identity": model_identity,
        "hardware": config.get("hardware") or "",
        "backend": config.get("backend") or "",
        "temperature": config.get("temperature"),
    }


def source_label(records_path: Path) -> str:
    """A machine-independent `provenance.source`.

    An absolute path would put this checkout's location into every sidecar, and
    a sidecar that differs between two checkouts breaks the store's byte
    identity criterion. The last three components are enough to find the run and
    stable everywhere: `runs/phase-b/records.jsonl`.
    """
    parts = records_path.parts[-3:]
    return "/".join(parts)


def object_name(record: dict, identity: str) -> str:
    """The §5.2 metadata name a harvested definition gets.

    ``generated/<task id>/<12 hex of the identity>``.

    Three jobs, in order of how much they matter:

    1. **It cannot collide with a curated name.** Everything the corpus names
       lives under `corpus/`; everything here lives under `generated/`. That is
       what stops a generated object from ever being served to prompt assembly
       under a curated definition's spec — conclusion 5's guardrail, enforced by
       the shape of the string rather than by a policy somebody has to run.
    2. **It says what the model was asked for.** The task id is the single most
       useful thing to see in `loom-store list --kind definition`, and it is
       taken from the record verbatim rather than transformed, so it greps
       straight back to the draw.
    3. **It is unique.** One task yields many distinct accepted definitions, so
       the task id alone is not a name; the identity prefix makes it one.

    The name is therefore *not* a pure function of the object: the phase-b
    records contain one identity produced under two different tasks. First
    accepted record wins, which is deterministic in the records file, and the
    full draw is in `provenance.run` either way — so nothing is lost, and the
    alternative (a content-only name like `generated/<hash>`) would have thrown
    away the one field a human reading a listing actually wants.
    """
    return f"{NAME_PREFIX}/{record['task']}/{identity[:NAME_HASH_PREFIX]}"


def provenance_for(record: dict, run: dict, source: str) -> dict:
    """The two blocks R2 asks for, and the line between them.

    `run` reconstructs the process. `observation` records what the *run* thought
    of the draw — `semantic_success` above all — and it is a sibling of neither
    `validation` nor `deps` on purpose. R2 is explicit that a run's semantic
    verdict is never evidence; keeping it in a block named `observation` makes
    that structural, so a later policy layer reading sidecars cannot mistake a
    hand-scored rubric result for something a checker proved.
    """
    return {
        "run": {
            **run,
            "condition": record.get("condition", ""),
            "regime": record.get("regime", ""),
            "seed": record.get("seed"),
            "draw": record.get("draw"),
            "draw_seed": record.get("draw_seed"),
            "task": record.get("task", ""),
            "task_kind": record.get("task_kind", ""),
        },
        "observation": {
            "funnel_outcome": record.get("funnel_outcome", ""),
            "layers_passed": record.get("layers_passed"),
            "semantic_rule": record.get("semantic_rule", ""),
            "semantic_success": record.get("semantic_success"),
            "narrowed": record.get("narrowed"),
            "retried": record.get("retried"),
        },
    }


# ---------------------------------------------------------------------------
# Re-admission
# ---------------------------------------------------------------------------


class AdmissionContext:
    """A resolver that grows as the harvest admits, over a store's contents.

    `store_admit.definition_sidecar` asks a resolver for three things, and this
    supplies all three. The reason it is not simply a `StoreResolver` is the
    fourth thing the harvest needs: a definition admitted at record *k* must be
    referenceable by a definition admitted at record *k+1*, because a run that
    composed one generation out of another would otherwise have its second
    generation refused at the references layer for naming a hash the store now
    holds. No accepted draw in the phase-b records does this — checked, zero of
    38 — so today it changes no count; it is here because the first run that
    does compose would otherwise fail in a way that looked like a real refusal.

    Declarations come from the store and never grow: v0 admits no declarations
    from generation, and R5 keeps it that way.
    """

    def __init__(self, base: StoreResolver):
        self._base = base
        self._definitions = DefinitionTypeRegistry(base.declarations.operation_arity)
        for resolved in base.definitions():
            self._definitions.add_source(resolved.surface, expected_hash=resolved.digest)

    @property
    def declarations(self):
        return self._base.declarations

    @property
    def operation_arity(self):
        return self._base.declarations.operation_arity

    def reference_type(self, digest: bytes) -> list:
        try:
            return self._definitions.reference_type(digest)
        except LookupError:
            return self._base.declarations.reference_type(digest)

    def add(self, surface: str, digest: bytes) -> None:
        self._definitions.add_source(surface, expected_hash=digest)

    def holds(self, digest: bytes) -> bool:
        try:
            self._definitions.reference_type(digest)
        except LookupError:
            return False
        return True


class Harvest:
    """One pass over a run's accepted draws. Counts are the product."""

    def __init__(self, context: AdmissionContext, run: dict, source: str):
        self.context = context
        self.run = run
        self.source = source
        self.admitted = 0
        self.exists = 0
        self.refused = 0
        self.not_selected = 0
        self.refusals: dict[str, dict] = {}
        self.objects: list[dict] = []
        self._sequence: dict[str, int] = {}
        self._named: dict[str, str] = {}

    def sequence_for(self, identity: str, position: int) -> int:
        """Stable across re-harvests: a function of the records file alone."""
        if identity not in self._sequence:
            self._sequence[identity] = SEQUENCE_BASE_GENERATED + position
        return self._sequence[identity]

    def name_for(self, record: dict, identity: str) -> str:
        if identity not in self._named:
            self._named[identity] = object_name(record, identity)
        return self._named[identity]

    def refuse(self, record: dict, layer: str, error_class: str, message: str) -> None:
        """Record a refusal once per identity, counting every record it covers.

        A refused draw redrawn thirty times is one finding and thirty records;
        collapsing it to one record would break the count invariant, and
        expanding it to thirty findings would bury the finding.
        """
        self.refused += 1
        identity = record.get("identity") or ""
        found = self.refusals.get(identity)
        if found is None:
            self.refusals[identity] = {
                "identity": identity,
                "task": record.get("task", ""),
                "layer": layer,
                "error_class": error_class,
                "message": message,
                "records": 1,
            }
        else:
            found["records"] += 1

    def admit(
        self,
        record: dict,
        position: int,
        run: dict | None = None,
        source: str | None = None,
    ) -> tuple[bytes, dict] | None:
        """Re-validate one accepted record. `None` means it was refused.

        `run` and `source` default to the pass's own, which is what a
        single-run harvest wants; a pooled harvest passes the run block of the
        run the record was actually drawn in, so provenance never inherits a
        neighbouring run's model identity.
        """
        run = self.run if run is None else run
        source = self.source if source is None else source
        surface = (record.get("source") or "").rstrip("\n")
        claimed = record.get("identity") or ""
        sequence = self.sequence_for(claimed, position)
        try:
            obj, sidecar = store_admit.definition_sidecar(
                surface,
                resolver=self.context,
                sequence=sequence,
                name=self.name_for(record, claimed),
                spec=None,
                origin=store_admit.ORIGIN_GENERATED,
                provenance_source=source,
                provenance_extra=provenance_for(record, run, source),
            )
        except store_admit.AdmissionRefused as refused:
            self.refuse(record, refused.layer, refused.error_class, refused.message)
            return None
        if sidecar["hash"] != claimed:
            # The run's own identity column disagrees with the bytes. Never
            # trust it stale: refuse, and name both hashes.
            self.refuse(
                record,
                LAYER_IDENTITY,
                "IdentityDrift",
                f"the recorded identity {claimed} is not the hash of the "
                f"recorded source, which is {sidecar['hash']}",
            )
            return None
        if not self.context.holds(bytes.fromhex(sidecar["hash"])):
            self.context.add(sidecar["surface"], bytes.fromhex(sidecar["hash"]))
        return obj, sidecar


# ---------------------------------------------------------------------------
# The store, as the harvest talks to it
# ---------------------------------------------------------------------------


class StoreCli:
    """The `loom-store` binary, invoked for exactly two things.

    Admission runs here, in Python, because that is where the validators live —
    so the harvest cannot use `loom-store admit`, whose oracle call has no way
    to carry a run's provenance. It uses `put` instead, the store's own entry
    point for "the oracle has already spoken", which is precisely what has
    happened by the time this class is called. No new Rust argument surface, and
    the Python/Rust seam stays exactly where store v0 drew it.
    """

    def __init__(self, binary: str, store: str | None):
        self.binary = binary
        self.store = store

    def _run(self, arguments: list[str]) -> dict:
        command = [self.binary]
        if self.store:
            command += ["--store", self.store]
        command += arguments
        try:
            finished = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as error:
            raise HarvestError(f"cannot run {self.binary}: {error}") from None
        line = finished.stdout.strip().splitlines()
        if not line:
            raise HarvestError(
                f"{' '.join(command)} said nothing on stdout "
                f"(exit {finished.returncode}): {finished.stderr.strip()}"
            )
        payload = json.loads(line[-1])
        if finished.returncode != 0:
            raise HarvestError(f"{' '.join(arguments)} failed: {json.dumps(payload)}")
        return payload

    def export_resolver(self) -> dict:
        return self._run(["export-resolver"])

    def put(self, object_path: Path, sidecar_path: Path) -> str:
        payload = self._run(["put", "--sidecar", str(sidecar_path), str(object_path)])
        return payload["status"]


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def sources_from(
    records_paths: list[Path],
    summaries: dict[Path, dict],
    run_overrides: dict[Path, dict] | None = None,
) -> list[RunSource]:
    """Read every records file and sort the runs by their machine-independent label."""
    overrides = run_overrides or {}
    sources = [
        RunSource(
            label=source_label(path),
            run=overrides.get(path) or run_identity(summaries.get(path) or {}, path),
            records=tuple(read_records(path)),
        )
        for path in records_paths
    ]
    labels = [source.label for source in sources]
    if len(set(labels)) != len(labels):
        raise HarvestError(
            "two records files share the machine-independent source label "
            f"{sorted(label for label in labels if labels.count(label) > 1)[0]!r}; "
            "provenance could not tell their objects apart"
        )
    return sorted(sources, key=lambda source: source.label)


def candidates_from(sources: list[RunSource]) -> list[harvest_select.Candidate]:
    """One candidate per distinct accepted identity, at the record that first produced it.

    Pool order is the canonical order R2 pins: sources by label, records within
    a source in the order the run wrote them. `distinct-shape`'s first-of-a-class
    rule therefore resolves the same way on every machine.
    """
    seen: dict[str, harvest_select.Candidate] = {}
    for source in sources:
        for record in accepted_records(list(source.records)):
            identity = record.get("identity") or ""
            if identity in seen:
                continue
            seen[identity] = harvest_select.Candidate(
                identity=identity,
                task=record.get("task", "") or "",
                surface=(record.get("source") or "").rstrip("\n"),
            )
    return list(seen.values())


def harvest(
    *,
    records_path: Path | None = None,
    summary: dict | None = None,
    document: dict,
    store: StoreCli | None,
    workspace: Path | None = None,
    run_override: dict | None = None,
    sink=None,
    sources: list[RunSource] | None = None,
    policy: str = harvest_select.POLICY_ALL,
    exclude_task_prefixes: tuple[str, ...] = (),
) -> dict:
    """Re-admit every accepted draw and report the counts. One dict, one line.

    With `store`, each object is landed and the store's own `put` outcome
    decides `admitted` vs `exists`. Without it (`--dry-run`), the same decision
    is made from the export document plus what this pass has already seen —
    which is the independent recount the plan's verification step 2 compares
    against, and it must agree.

    `sink(object_bytes, sidecar, status)` is called for every record that
    re-admitted, in records order, before the counts are updated. It is how a
    caller that wants the objects themselves — a test building a harvested
    export document without a Rust toolchain — gets them without this function
    having to grow a second return value nobody else wants.
    """
    if sources is None:
        if records_path is None:
            raise HarvestError("harvest needs either records_path or sources")
        sources = [
            RunSource(
                label=source_label(records_path),
                run=run_override or run_identity(summary or {}, records_path),
                records=tuple(read_records(records_path)),
            )
        ]

    base = StoreResolver(document, origins=POLICY_ALL)
    already = {sidecar["hash"] for sidecar in document.get("objects", [])}
    context = AdmissionContext(base)

    # Selection runs over the whole pool before anything is admitted, because
    # `size-match` orders by identity and `distinct-shape` compares a candidate
    # against every class already taken — neither is a decision a streaming pass
    # could make. `all` short-circuits to "every candidate", which is what keeps
    # the default byte-identical to the pre-selection harvest.
    candidates = candidates_from(sources)
    selection = harvest_select.select(
        policy,
        candidates,
        occupied=harvest_select.curated_classes(document, context.operation_arity),
        already_held=frozenset(already),
        exclude_task_prefixes=tuple(exclude_task_prefixes),
        operation_arity=context.operation_arity,
    )
    chosen = selection.identities

    pass_ = Harvest(context, sources[0].run, sources[0].label)

    total_records = 0
    total_accepted = 0
    distinct: set[str] = set()
    position = 0
    for source in sources:
        total_records += len(source.records)
        accepted = accepted_records(list(source.records))
        total_accepted += len(accepted)
        for record in accepted:
            distinct.add(record.get("identity"))
            here = position
            position += 1
            if record.get("identity") not in chosen:
                pass_.not_selected += 1
                continue
            result = pass_.admit(record, here, source.run, source.label)
            if result is None:
                continue
            obj, sidecar = result
            digest = sidecar["hash"]
            if store is None:
                status = EXISTS if digest in already else WRITTEN
            else:
                stem = workspace / digest
                stem.with_suffix(".bin").write_bytes(obj)
                stem.with_suffix(".json").write_bytes(store_admit.sidecar_bytes(sidecar))
                status = store.put(stem.with_suffix(".bin"), stem.with_suffix(".json"))
            if sink is not None:
                sink(obj, sidecar, status)
            if status == WRITTEN:
                pass_.admitted += 1
                pass_.objects.append(
                    {"hash": digest, "name": sidecar["name"], "sequence": sidecar["sequence"]}
                )
            else:
                pass_.exists += 1
            already.add(digest)

    counted = pass_.admitted + pass_.exists + pass_.refused + pass_.not_selected
    if counted != total_accepted:
        raise HarvestError(
            f"count invariant broken: admitted {pass_.admitted} + exists "
            f"{pass_.exists} + refused {pass_.refused} + not_selected "
            f"{pass_.not_selected} = {counted}, but "
            f"{total_accepted} records were accepted"
        )

    report = {
        "status": "harvested",
        "records": total_records,
        "accepted": total_accepted,
        "admitted": pass_.admitted,
        "exists": pass_.exists,
        "refused_on_readmission": pass_.refused,
        "not_selected": pass_.not_selected,
        "distinct_identities": len(distinct),
        "refusals": sorted(pass_.refusals.values(), key=lambda entry: entry["identity"]),
        "objects": pass_.objects,
        "selection": selection.report(),
        "runs": [{"source": source.label, "run": source.run} for source in sources],
        "dry_run": store is None,
    }
    if len(sources) == 1:
        # The single-run shape the corpus-loop plan's recorded line has, kept
        # verbatim so a consumer of that line does not have to learn a new one.
        report["run"] = sources[0].run
        report["source"] = sources[0].label
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise HarvestError(f"cannot read {path}: {error}") from None
    except json.JSONDecodeError as error:
        raise HarvestError(f"{path} is not valid JSON: {error}") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="harvest",
        description="Admit a run's accepted draws into the store as origin=generated.",
    )
    parser.add_argument(
        "--records",
        required=True,
        type=Path,
        action="append",
        help="a run's records.jsonl; repeat to pool several runs into one candidate set",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        action="append",
        default=None,
        help="a run's summary.json (default: beside each records file). When given, "
        "must be repeated once per --records, in the same order.",
    )
    parser.add_argument(
        "--select",
        default=harvest_select.POLICY_ALL,
        help=f"selection policy: {harvest_select.POLICY_ALL} (default, admits every "
        f"accepted draw), {harvest_select.POLICY_DISTINCT_SHAPE}, or "
        f"{harvest_select.POLICY_SIZE_MATCH}:<n>",
    )
    parser.add_argument(
        "--exclude-task-prefix",
        action="append",
        default=[],
        help="drop candidates whose task id starts with this prefix; repeatable. "
        "Every arm of the diversity-harvest plan passes 'heldout/'.",
    )
    parser.add_argument("--store", default=None, help="store directory (default: the CLI's own)")
    parser.add_argument(
        "--store-bin",
        default="store/target/debug/loom-store",
        help="the loom-store binary",
    )
    parser.add_argument(
        "--resolver",
        type=Path,
        default=None,
        help="an export-resolver document to validate against; implies --dry-run "
        "when the store binary is not used",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="re-validate and count without landing anything",
    )
    parser.add_argument("--out", type=Path, default=None, help="keep the emitted pairs here")
    parser.add_argument("--run-id", default=None, help="override the derived run id")
    parser.add_argument(
        "--model-identity",
        default=None,
        help="the model identity for a run whose summary does not record one",
    )
    arguments = parser.parse_args(argv)

    try:
        summaries_given = arguments.summary or []
        if summaries_given and len(summaries_given) != len(arguments.records):
            raise HarvestError(
                f"{len(arguments.records)} --records but {len(summaries_given)} "
                "--summary; give one summary per records file, in the same order, "
                "or none at all"
            )
        if arguments.run_id and len(arguments.records) > 1:
            raise HarvestError("--run-id names one run; it cannot stand for a pool of them")

        summaries: dict[Path, dict] = {}
        overrides: dict[Path, dict] = {}
        for index, records in enumerate(arguments.records):
            if not records.is_file():
                # Checked first and by itself: run output is gitignored
                # (`prototype/runs/`), so "no such run" is the failure a fresh
                # checkout hits, and it must not arrive disguised as a complaint
                # about the summary that is missing for the same reason.
                raise HarvestError(
                    f"no records at {records}. Run output is not committed "
                    "(`prototype/runs/` is gitignored); point --records at a run "
                    "directory you have."
                )
            summary_path = (
                summaries_given[index] if summaries_given else records.parent / "summary.json"
            )
            summary = _read_json(summary_path) if summary_path.is_file() else {}
            if arguments.model_identity:
                summary.setdefault("config", {})["model_identity"] = arguments.model_identity
            summaries[records] = summary
            run = run_identity(summary, records)
            if arguments.run_id:
                run["run_id"] = arguments.run_id
            overrides[records] = run

        store = None if arguments.dry_run else StoreCli(arguments.store_bin, arguments.store)
        if arguments.resolver is not None:
            document = _read_json(arguments.resolver)
        elif store is not None:
            document = store.export_resolver()
        else:
            raise HarvestError("--dry-run needs --resolver: there is no store to ask")

        run_sources = sources_from(arguments.records, summaries, overrides)

        with tempfile.TemporaryDirectory() as scratch:
            workspace = arguments.out or Path(scratch)
            workspace.mkdir(parents=True, exist_ok=True)
            report = harvest(
                sources=run_sources,
                document=document,
                store=store,
                workspace=workspace,
                policy=arguments.select,
                exclude_task_prefixes=tuple(arguments.exclude_task_prefix),
            )
    except HarvestError as error:
        sys.stdout.write(json.dumps({"error": "harvest", "message": str(error)}) + "\n")
        return 5

    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
