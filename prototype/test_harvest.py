"""The corpus loop's gate: harvest counts, provenance, and the origin filter.

[The corpus-loop plan](../docs/plans/2026-08-14-corpus-loop.md) makes three
claims that are only worth as much as the tests behind them, and each has a
section here:

1. **R1 — harvest admits what the funnel accepted and nothing looser.** The
   run's verdict selects a draw; it never admits one. A record the run called
   `accepted` that the store refuses is counted in its own category and named,
   and the three counts always sum to the number of accepted records.
2. **R2 — provenance is load-bearing.** Every harvested object carries the run
   that made it, its `origin` is `generated`, its tier is whatever validation
   earned, and the run's `semantic_success` sits in an `observation` block that
   is structurally not evidence.
3. **R3 — curated-only is the default, and it is byte-identical.** The strong
   form: a *harvested* export document, containing generated objects, still
   builds prompts byte-for-byte identical to the corpus-built resolver's under
   the default policy. `test_store.py`'s equivalence suite proves the same thing
   over a curated store and is deliberately left untouched; this file is what
   proves the filter itself does not shift a byte.

The fixture is synthetic and lives in this file. Committed run output is
gitignored — `prototype/runs/` — so a test that read a real run would pass on
the machine that produced it and fail everywhere else. The synthetic records are
built by hashing real canonical surfaces through the same encoder the store
uses, so the identities are genuine rather than invented, and the deliberately
broken cases (a stale hash, a hallucinated reference) are broken on purpose and
say so.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cbor_canonical
import corpus_registry
import harvest as harvest_module
import store_admit
import transcode
from declarations import DeclarationError
from experiment import prompts, runner
from experiment.resolver import ExperimentResolver
from experiment.store_resolver import (
    POLICY_ALL,
    POLICY_CURATED,
    StoreExportError,
    StoreResolver,
)

CONFIG_DIR = Path(__file__).resolve().parent / "experiment"

#: A definition nobody wrote: the identity function on `I64`. Not in the corpus,
#: references nothing, and types under the pinned declarations.
IDENTITY_I64 = "(def (fn I64 () I64) (lam I64 (var 0)))"

#: A second one, distinct from the first.
CONST_I64 = "(def I64 (lit i64 1633072800000))"

#: A third, so a `full_corpus` prompt has more than one generated neighbour.
CONST_BOOL = "(def Bool (if (lit bool true) (lit bool false) (lit bool true)))"

#: A definition naming a hash that exists nowhere. The `references` layer
#: refuses it — which is the point: the fixture claims the run accepted it.
HALLUCINATED = "(def (fn Unit () Unit) (lam Unit (ref 0x" + "01" * 32 + ")))"


def identity_of(source: str) -> str:
    """The canonical identity of a surface, by the same route the store takes."""
    return hashlib.sha256(cbor_canonical.encode(transcode.parse_source(source))).hexdigest()


def corpus_surface(name: str) -> str:
    """A curated definition's own surface, for the "the model reproduced it" case."""
    entry = next(e for e in corpus_registry.MANIFEST if e.name_path == name)
    return entry.source_text().rstrip("\n")


def record(
    source: str,
    *,
    outcome: str = "accepted",
    identity: str | None = None,
    task: str = "corpus/bool/not",
    regime: str = "few_shot",
    seed: int = 1,
    draw: int = 0,
    semantic_success: bool = False,
) -> dict:
    """One run record, with only the fields the harvest reads."""
    return {
        "source": source,
        "raw": source,
        # A rejected draw has no identity — the run records "" for anything that
        # did not reach the encoder — so only accepted rows get one derived.
        "identity": (
            identity
            if identity is not None
            else (identity_of(source) if outcome == "accepted" else "")
        ),
        "funnel_outcome": outcome,
        "layers_passed": 4 if outcome == "accepted" else 2,
        "condition": "gbnf+typemask",
        "regime": regime,
        "seed": seed,
        "draw": draw,
        "draw_seed": 100000 + draw,
        "task": task,
        "task_kind": "held_out" if task.startswith("heldout/") else "corpus",
        "semantic_rule": "identity-match",
        "semantic_success": semantic_success,
        "narrowed": False,
        "retried": False,
    }


def fixture_records() -> list[dict]:
    """The synthetic run. Every category the harvest must distinguish, once.

    Nine records, six of them accepted:

    * two draws of `IDENTITY_I64` — the second is the free deduplication
      content addressing gives, and must be reported as `exists`;
    * `CONST_I64` and `CONST_BOOL` — two more genuinely new objects;
    * `HALLUCINATED`, labelled accepted, which the references layer refuses:
      the "contract drift since the run" case, reported not dropped;
    * a draw whose recorded `identity` is a lie about its own bytes;
    * three records the funnel rejected, which must not be selected at all.
    """
    return [
        record(IDENTITY_I64, task="corpus/nat/select", draw=0),
        record("(def Bool (lit bool", outcome="parse", draw=1),
        record(IDENTITY_I64, task="corpus/nat/select", draw=2, seed=2),
        record(CONST_I64, task="corpus/clock/now", draw=3),
        record(HALLUCINATED, task="heldout/maybe/mapOrElse", regime="held_out", draw=4),
        record(CONST_BOOL, task="corpus/bool/not", draw=5),
        record("(def Bool (ref 0x" + "ab" * 32 + "))", outcome="references", draw=6),
        record(CONST_I64, identity="cc" * 32, task="corpus/clock/now", draw=7),
        record("(def I64 (var 0))", outcome="scope", draw=8),
    ]


def fixture_summary(model_identity: str = "synthetic-model/1") -> dict:
    return {
        "started_utc": "2026-08-14T00:00:00Z",
        "config": {
            "model_identity": model_identity,
            "hardware": "test bench",
            "backend": "stub",
            "temperature": 0.8,
        },
    }


def corpus_document() -> dict:
    """An export document for a store holding exactly the pinned corpus."""
    objects = [sidecar for _, sidecar in store_admit.corpus_objects()]
    objects.sort(key=lambda sidecar: (sidecar["sequence"], sidecar["hash"]))
    return {"schema": 1, "store": {"contracts": {}}, "objects": objects}


def write_run(directory: Path, records: list[dict], summary: dict) -> Path:
    """Lay a synthetic run out on disk the way a real one is laid out."""
    directory.mkdir(parents=True, exist_ok=True)
    records_path = directory / "records.jsonl"
    records_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in records), encoding="utf-8"
    )
    (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return records_path


def run_harvest(records_path: Path, summary: dict, document: dict):
    """A dry-run harvest, returning `(report, {hash: sidecar})`."""
    collected: dict[str, dict] = {}

    def sink(_object, sidecar, _status):
        collected.setdefault(sidecar["hash"], sidecar)

    report = harvest_module.harvest(
        records_path=records_path,
        summary=summary,
        document=document,
        store=None,
        sink=sink,
    )
    return report, collected


def harvested_document(document: dict, sidecars: dict[str, dict]) -> dict:
    """`document` plus every harvested sidecar it does not already hold.

    Assembled exactly the way `Store::export_resolver` assembles it — sorted by
    `(sequence, hash)` — so a resolver built from this is built from the same
    bytes a real store would have handed it.
    """
    known = {sidecar["hash"] for sidecar in document["objects"]}
    objects = list(document["objects"])
    objects += [sidecar for hash_, sidecar in sidecars.items() if hash_ not in known]
    objects.sort(key=lambda sidecar: (sidecar["sequence"], sidecar["hash"]))
    return {"schema": 1, "store": document.get("store", {}), "objects": objects}


class HarvestFixture(unittest.TestCase):
    """Shared synthetic run, harvested once against a corpus-only store."""

    @classmethod
    def setUpClass(cls):
        cls._scratch = tempfile.TemporaryDirectory()
        cls.run_dir = Path(cls._scratch.name) / "runs" / "synthetic"
        cls.records_path = write_run(cls.run_dir, fixture_records(), fixture_summary())
        cls.document = corpus_document()
        cls.report, cls.sidecars = run_harvest(
            cls.records_path, fixture_summary(), cls.document
        )

    @classmethod
    def tearDownClass(cls):
        cls._scratch.cleanup()

    def sidecar_for(self, source: str) -> dict:
        return self.sidecars[identity_of(source)]


class SelectionAndCountsTest(HarvestFixture):
    """R1 — what is selected, what is admitted, and what is merely reported."""

    def test_only_accepted_records_are_selected(self):
        self.assertEqual(self.report["records"], 9)
        self.assertEqual(self.report["accepted"], 6)

    def test_the_three_counts_account_for_every_accepted_record(self):
        total = (
            self.report["admitted"]
            + self.report["exists"]
            + self.report["refused_on_readmission"]
        )
        self.assertEqual(total, self.report["accepted"])

    def test_the_counts_are_the_ones_the_fixture_was_built_to_produce(self):
        self.assertEqual(self.report["admitted"], 3)
        self.assertEqual(self.report["exists"], 1)
        self.assertEqual(self.report["refused_on_readmission"], 2)

    def test_a_redrawn_definition_is_an_exists_and_not_an_error(self):
        # Two records carry `IDENTITY_I64`; one object comes out of it.
        self.assertEqual(self.report["exists"], 1)
        self.assertIn(identity_of(IDENTITY_I64), self.sidecars)

    def test_a_draw_the_run_accepted_and_the_store_refuses_is_reported_not_dropped(self):
        refusals = {entry["identity"]: entry for entry in self.report["refusals"]}
        hallucinated = refusals[identity_of(HALLUCINATED)]
        # The refusing layer's own error class, not a harvest-invented one —
        # `ref` into a definition is resolved when the checker asks for its
        # type, so an unresolvable hash surfaces at `typecheck`.
        self.assertEqual(hallucinated["layer"], "typecheck")
        self.assertEqual(hallucinated["error_class"], "TypingError")
        self.assertIn("has no resolvable type", hallucinated["message"])
        self.assertEqual(hallucinated["task"], "heldout/maybe/mapOrElse")
        self.assertNotIn(identity_of(HALLUCINATED), self.sidecars)

    def test_a_recorded_identity_that_is_not_the_hash_of_the_bytes_is_refused(self):
        refusals = {entry["identity"]: entry for entry in self.report["refusals"]}
        drift = refusals["cc" * 32]
        self.assertEqual(drift["layer"], harvest_module.LAYER_IDENTITY)
        self.assertIn(identity_of(CONST_I64), drift["message"])

    def test_a_run_without_a_recorded_model_identity_is_refused(self):
        with self.assertRaises(harvest_module.HarvestError) as caught:
            harvest_module.run_identity(fixture_summary(model_identity=""), self.records_path)
        self.assertIn("model_identity", str(caught.exception))

    def test_the_selector_is_the_funnel_outcome_and_nothing_looser(self):
        selected = harvest_module.accepted_records(fixture_records())
        self.assertTrue(all(row["funnel_outcome"] == "accepted" for row in selected))
        self.assertEqual(len(selected), 6)


class ProvenanceTest(HarvestFixture):
    """R2 — what a harvested object says about where it came from."""

    def test_origin_is_generated(self):
        for sidecar in self.sidecars.values():
            self.assertEqual(sidecar["provenance"]["origin"], store_admit.ORIGIN_GENERATED)

    def test_the_run_block_reconstructs_the_draw(self):
        run = self.sidecar_for(CONST_I64)["provenance"]["run"]
        self.assertEqual(run["model_identity"], "synthetic-model/1")
        self.assertEqual(run["run_id"], "synthetic@2026-08-14T00:00:00Z")
        self.assertEqual(run["condition"], "gbnf+typemask")
        self.assertEqual(run["regime"], "few_shot")
        self.assertEqual(run["seed"], 1)
        self.assertEqual(run["draw"], 3)
        self.assertEqual(run["task"], "corpus/clock/now")

    def test_semantic_success_is_an_observation_and_never_evidence(self):
        sidecar = self.sidecar_for(CONST_I64)
        self.assertIn("semantic_success", sidecar["provenance"]["observation"])
        self.assertNotIn("semantic_success", sidecar["validation"])
        self.assertNotIn("semantic_success", sidecar["provenance"]["run"])

    def test_the_tier_is_whatever_validation_earned_and_nothing_is_inflated(self):
        validation = self.sidecar_for(CONST_I64)["validation"]
        self.assertEqual(validation["layers"], list(store_admit.DEFINITION_LAYERS))
        self.assertEqual(validation["contracts"], dict(
            (layer, __import__("contracts").version(layer))
            for layer in store_admit.DEFINITION_LAYERS))
        # No spec: nobody wrote one. Borrowing the task's spec would describe
        # what was *asked for*, which a generated definition need not satisfy —
        # the masquerade R2 forbids.
        self.assertIsNone(self.sidecar_for(CONST_I64)["spec"])

    def test_provenance_source_is_machine_independent(self):
        self.assertEqual(self.report["source"], "runs/synthetic/records.jsonl")
        for sidecar in self.sidecars.values():
            self.assertEqual(sidecar["provenance"]["source"], "runs/synthetic/records.jsonl")

    def test_an_admitter_may_not_rewrite_the_fields_the_oracle_owns(self):
        with self.assertRaises(ValueError):
            store_admit.definition_sidecar(
                IDENTITY_I64,
                resolver=ExperimentResolver(),
                sequence=0,
                provenance_extra={"origin": "transpiled"},
            )


class NamingTest(HarvestFixture):
    """R2's naming scheme, and the collision it is shaped to make impossible."""

    def test_every_name_is_reserved_under_the_generated_prefix(self):
        for sidecar in self.sidecars.values():
            self.assertTrue(sidecar["name"].startswith(harvest_module.NAME_PREFIX + "/"))

    def test_no_generated_name_can_collide_with_a_curated_one(self):
        curated = {entry.name_path for entry in corpus_registry.MANIFEST}
        self.assertTrue(all(name.startswith("corpus/") for name in curated))
        for sidecar in self.sidecars.values():
            self.assertNotIn(sidecar["name"], curated)

    def test_the_name_carries_the_task_and_the_identity_prefix(self):
        sidecar = self.sidecar_for(CONST_I64)
        self.assertEqual(
            sidecar["name"],
            f"generated/corpus/clock/now/{identity_of(CONST_I64)[:12]}",
        )

    def test_names_are_unique_across_the_harvest(self):
        names = [sidecar["name"] for sidecar in self.sidecars.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_a_generated_object_cannot_take_a_curated_name(self):
        document = harvested_document(self.document, self.sidecars)
        stolen = json.loads(json.dumps(document))
        victim = next(
            sidecar for sidecar in stolen["objects"]
            if (sidecar.get("provenance") or {}).get("origin") == "transpiled"
        )
        thief = next(
            sidecar for sidecar in stolen["objects"]
            if (sidecar.get("provenance") or {}).get("origin") == "generated"
        )
        thief["name"] = victim["name"]
        with self.assertRaises(StoreExportError) as caught:
            StoreResolver(stolen, origins=POLICY_ALL)
        self.assertIn(victim["name"], str(caught.exception))


class DeterminismTest(HarvestFixture):
    """The store's byte-identity criterion, extended to harvested objects."""

    def test_sequence_lands_in_the_reserved_generated_band(self):
        for sidecar in self.sidecars.values():
            self.assertGreaterEqual(
                sidecar["sequence"], harvest_module.SEQUENCE_BASE_GENERATED
            )
        curated = max(sidecar["sequence"] for sidecar in self.document["objects"])
        self.assertLess(curated, harvest_module.SEQUENCE_BASE_GENERATED)

    def test_sequence_is_a_function_of_the_records_file_alone(self):
        # Position among *accepted* records, so the first accepted draw gets the
        # base exactly — and gets it again on any later harvest of the same run.
        self.assertEqual(
            self.sidecar_for(IDENTITY_I64)["sequence"],
            harvest_module.SEQUENCE_BASE_GENERATED,
        )

    def test_re_harvesting_the_same_records_emits_byte_identical_sidecars(self):
        _, again = run_harvest(self.records_path, fixture_summary(), self.document)
        self.assertEqual(sorted(again), sorted(self.sidecars))
        for hash_, sidecar in again.items():
            self.assertEqual(
                store_admit.sidecar_bytes(sidecar),
                store_admit.sidecar_bytes(self.sidecars[hash_]),
            )

    def test_re_harvesting_into_a_store_that_already_holds_them_changes_nothing(self):
        document = harvested_document(self.document, self.sidecars)
        report, _ = run_harvest(self.records_path, fixture_summary(), document)
        self.assertEqual(report["admitted"], 0)
        self.assertEqual(report["exists"], 4)
        self.assertEqual(report["refused_on_readmission"], 2)
        self.assertEqual(report["accepted"], 6)

    def test_a_generation_identical_to_a_curated_object_dedupes_into_it(self):
        # Content addressing says a byte-identical reproduction of a curated
        # definition *is* that definition. It lands as `exists` against the
        # curated object and does not relabel it `generated` — the guardrail
        # only ever runs in the safe direction.
        surface = corpus_surface("corpus/bool/not")
        run_dir = Path(self._scratch.name) / "runs" / "echo"
        records_path = write_run(
            run_dir, [record(surface, task="corpus/bool/not")], fixture_summary()
        )
        report, collected = run_harvest(records_path, fixture_summary(), self.document)
        self.assertEqual(report["admitted"], 0)
        self.assertEqual(report["exists"], 1)
        stored = next(
            sidecar for sidecar in self.document["objects"]
            if sidecar["hash"] == identity_of(surface)
        )
        self.assertEqual(stored["provenance"]["origin"], store_admit.ORIGIN_TRANSPILED)
        self.assertEqual(stored["name"], "corpus/bool/not")
        self.assertIn(identity_of(surface), collected)


class OriginFilterTest(HarvestFixture):
    """R3 — curated-only is the default, and the default moves no bytes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.harvested = harvested_document(cls.document, cls.sidecars)
        cls.corpus_resolver = ExperimentResolver()
        cls.curated = StoreResolver(cls.harvested, origins=POLICY_CURATED)
        cls.everything = StoreResolver(cls.harvested, origins=POLICY_ALL)

    def test_the_default_policy_is_curated(self):
        self.assertEqual(StoreResolver(self.harvested).origin_policy, POLICY_CURATED)

    def test_the_curated_arm_sees_exactly_the_corpus(self):
        self.assertEqual(self.curated.counts(), self.corpus_resolver.counts())
        self.assertEqual(self.curated.digests(), self.corpus_resolver.digests())

    def test_the_generated_arm_sees_more(self):
        self.assertEqual(len(self.everything), len(self.curated) + len(self.sidecars))
        self.assertEqual(
            self.everything.origin_counts()[store_admit.ORIGIN_GENERATED], len(self.sidecars)
        )
        self.assertEqual(self.curated.origin_counts()[store_admit.ORIGIN_GENERATED], 0)

    def test_every_task_and_regime_builds_a_byte_identical_prompt(self):
        """The strong form of R3, over a store that *does* hold generations."""
        built = 0
        for task in prompts.all_tasks():
            for regime in prompts.REGIMES:
                for leave_one_out in (True, False):
                    expected = prompts.build_prompt(
                        task, regime, self.corpus_resolver, leave_one_out=leave_one_out
                    )
                    actual = prompts.build_prompt(
                        task, regime, self.curated, leave_one_out=leave_one_out
                    )
                    self.assertEqual(actual, expected, f"{task.task_id}|{regime}")
                    built += 1
        self.assertEqual(built, len(prompts.all_tasks()) * len(prompts.REGIMES) * 2)

    def test_the_full_corpus_prompt_is_not_trivially_short(self):
        prompt = prompts.build_prompt(prompts.all_tasks()[0], "full_corpus", self.curated)
        self.assertGreater(len(prompt), 2000)
        self.assertIn("(def ", prompt)

    def test_a_generated_hash_resolves_only_in_the_generated_arm(self):
        digest = bytes.fromhex(identity_of(CONST_I64))
        self.assertIsNotNone(self.everything.resolve(digest))
        with self.assertRaises(LookupError):
            self.curated.resolve(digest)
        # `reference_type` falls through to the declaration registry, which
        # refuses with the declaration layer's own error — the same behaviour
        # `ExperimentResolver` has, unchanged by the filter.
        with self.assertRaises((LookupError, DeclarationError)):
            self.curated.reference_type(digest)

    def test_the_masker_universe_follows_the_same_filter(self):
        # `digests()` is what seeds the reference-hash pruner. An arm that was
        # curated in the prompt and generated in the mask would be neither.
        self.assertNotIn(bytes.fromhex(identity_of(CONST_I64)), self.curated.digests())
        self.assertIn(bytes.fromhex(identity_of(CONST_I64)), self.everything.digests())

    def test_an_unknown_origin_is_refused_rather_than_silently_excluded(self):
        tampered = json.loads(json.dumps(self.harvested))
        tampered["objects"][0]["provenance"]["origin"] = "scraped"
        with self.assertRaises(StoreExportError) as caught:
            StoreResolver(tampered)
        self.assertIn("scraped", str(caught.exception))

    def test_an_object_with_no_origin_is_refused_rather_than_read_as_curated(self):
        tampered = json.loads(json.dumps(self.harvested))
        tampered["objects"][0]["provenance"].pop("origin")
        with self.assertRaises(StoreExportError):
            StoreResolver(tampered)

    def test_an_unknown_policy_is_refused(self):
        with self.assertRaises(StoreExportError):
            StoreResolver(self.harvested, origins="whatever")


class FollowUpConfigTest(HarvestFixture):
    """R4 — the two arms, loaded as shipped and run on the stub backend."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.export = Path(cls._scratch.name) / "export-resolver.json"
        cls.export.write_text(
            json.dumps(harvested_document(cls.document, cls.sidecars)), encoding="utf-8"
        )

    def arms(self):
        return {
            "curated": runner.Config.load(CONFIG_DIR / "followup_curated.config.json"),
            "generated": runner.Config.load(CONFIG_DIR / "followup_generated.config.json"),
        }

    def test_the_two_arms_differ_only_in_the_origin_flag(self):
        arms = self.arms()
        curated = {k: v for k, v in vars(arms["curated"]).items()}
        generated = {k: v for k, v in vars(arms["generated"]).items()}
        differing = {
            key for key in curated
            if curated[key] != generated[key]
        }
        self.assertEqual(differing, {"include_generated", "output_dir", "source_path"})
        self.assertIs(curated["include_generated"], False)
        self.assertIs(generated["include_generated"], True)

    def test_both_arms_name_the_same_store(self):
        arms = self.arms()
        self.assertEqual(arms["curated"].store_export, arms["generated"].store_export)
        self.assertTrue(arms["curated"].store_export.endswith(
            ".loom-store-generated/export-resolver.json"))

    def test_the_arms_run_the_full_corpus_and_held_out_regimes(self):
        for config in self.arms().values():
            self.assertEqual(config.regimes, ["full_corpus", "held_out"])
            self.assertEqual(config.conditions, ["gbnf+typemask"])
            self.assertEqual(config.token_budget_per_task, 512)

    def test_include_generated_without_a_store_is_refused(self):
        with self.assertRaises(SystemExit):
            runner.Config(include_generated=True).validate()

    def _stubbed(self, config):
        """The shipped arm, pointed at the fixture store and the stub backend."""
        config.store_export = str(self.export)
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

    def test_both_arms_run_end_to_end_on_the_stub_backend(self):
        seen = {}
        for name, config in self.arms().items():
            records, summary = runner.run(self._stubbed(config))
            self.assertTrue(records, f"{name} arm produced no records")
            self.assertEqual(summary["resolver_objects"]["definition"],
                             26 + (len(self.sidecars) if name == "generated" else 0))
            seen[name] = summary
        # The arm is legible in the summary without reading the config back.
        self.assertEqual(
            seen["curated"]["resolver_origins"][store_admit.ORIGIN_GENERATED], 0)
        self.assertEqual(
            seen["generated"]["resolver_origins"][store_admit.ORIGIN_GENERATED],
            len(self.sidecars))

    def test_a_config_with_no_store_export_still_builds_the_corpus_resolver(self):
        config = runner.Config(backend="stub", stub_outputs=["x"], source_path="<test>")
        self.assertIsInstance(runner.make_resolver(config), ExperimentResolver)

    def test_a_missing_store_export_is_a_clear_refusal(self):
        config = runner.Config(store_export="/nonexistent/export.json", source_path="<test>")
        with self.assertRaises(SystemExit) as caught:
            runner.make_resolver(config)
        self.assertIn("task store:harvest", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
