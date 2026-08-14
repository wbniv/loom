"""The case store: what a differential record is, and how one is merged.

A *case* is one (layer, entry point, input, environment) tuple together with
everything the layer's gate compares: the accept/reject verdict, the declared
error class on rejection, and — where the layer emits them — canonical bytes and
the identity derived from them.

The same case is reached many times over a full test run, from different tests.
That is a feature, not duplication to be suppressed: the provenance list is the
union, so a consumer can see which of the prototype's tests each input came
from. What is *not* tolerated is the same case reaching two different verdicts —
that means either a nondeterministic layer or an input the harness recorded
lossily, and both make the export a lie. `merge` raises on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import jsonio


class RecordConflict(RuntimeError):
    """The same case was observed with two different outcomes."""


#: Export order for layers, and the only names a record may carry. This is
#: `CONTRACTS.md`'s migration order, not alphabetical: the port lands in this
#: sequence, so an export read top to bottom is read in porting order.
LAYER_ORDER = (
    "parser",
    "declarations",
    "scope",
    "references",
    "typecheck",
    "refinements",
    "policies",
)


@dataclass
class Case:
    """One differential record, before serialization."""

    layer: str
    entry_point: str
    encoded_input: dict
    environment: str | None
    verdict: str
    error_class: str | None
    canonical_bytes_hex: str | None
    identity_hash: str | None
    extra: dict = field(default_factory=dict)
    provenance: set = field(default_factory=set)

    @property
    def key(self) -> str:
        return jsonio.canonical(
            {
                "layer": self.layer,
                "entry_point": self.entry_point,
                "input": self.encoded_input,
                "environment": self.environment,
            }
        )

    @property
    def case_id(self) -> str:
        import hashlib

        return hashlib.sha256(self.key.encode("utf-8")).hexdigest()

    @property
    def outcome(self) -> str:
        """Everything the gate compares, as canonical text — the conflict key."""
        return jsonio.canonical(
            {
                "verdict": self.verdict,
                "error_class": self.error_class,
                "canonical_bytes_hex": self.canonical_bytes_hex,
                "identity_hash": self.identity_hash,
                "extra": self.extra,
            }
        )

    def to_record(self) -> dict:
        return {
            "record": "case",
            "case_id": self.case_id,
            "layer": self.layer,
            "entry_point": self.entry_point,
            "input": self.encoded_input,
            "environment": self.environment,
            "verdict": self.verdict,
            "error_class": self.error_class,
            "canonical_bytes_hex": self.canonical_bytes_hex,
            "identity_hash": self.identity_hash,
            "extra": self.extra,
            "provenance": [
                {"origin": origin, "module": module, "test": test}
                for origin, module, test in sorted(self.provenance)
            ],
        }


class Recorder:
    """Accumulates cases and the environments they refer to."""

    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}
        self._environments: dict[str, dict] = {}
        #: Set while a wrapped entry point is executing, so an inner call made
        #: by an outer one is attributed to the same test.
        self.provenance: tuple[str, str, str] | None = None
        self.enabled = False

    # ── environments ────────────────────────────────────────────────────
    def environment(self, kind: str, payload) -> str:
        """Register an environment document and return its stable id."""
        encoded = jsonio.encode(payload)
        env_id = jsonio.digest({"kind": kind, "payload": encoded})
        self._environments.setdefault(env_id, {"kind": kind, "payload": encoded})
        return env_id

    def environment_records(self) -> list[dict]:
        return [
            {"record": "environment", "environment": env_id, **document}
            for env_id, document in sorted(self._environments.items())
        ]

    # ── cases ───────────────────────────────────────────────────────────
    def merge(self, case: Case) -> Case:
        if case.layer not in LAYER_ORDER:
            raise ValueError(f"unknown layer {case.layer!r}")
        if self.provenance is not None:
            case.provenance.add(self.provenance)
        existing = self._cases.get(case.key)
        if existing is None:
            self._cases[case.key] = case
            return case
        if existing.outcome != case.outcome:
            raise RecordConflict(
                f"{case.layer}/{case.entry_point}: the same input produced two outcomes\n"
                f"  first: {existing.outcome}\n  again: {case.outcome}\n"
                f"  input: {case.key}"
            )
        existing.provenance |= case.provenance
        return existing

    def cases(self) -> list[Case]:
        """Every case, in a total order that does not depend on capture order."""
        return sorted(
            self._cases.values(),
            key=lambda case: (LAYER_ORDER.index(case.layer), case.entry_point, case.case_id),
        )

    def counts(self) -> dict[str, dict[str, int]]:
        """Per-layer accepted/rejected counts."""
        result: dict[str, dict[str, int]] = {}
        for case in self.cases():
            bucket = result.setdefault(case.layer, {"accept": 0, "reject": 0})
            bucket[case.verdict] += 1
        return result
