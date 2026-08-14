"""The store's Python-side gate: admission sidecars, and resolver equivalence.

Two things are proven here, and the second is the v0 acceptance criterion from
[the store plan](../docs/plans/2026-08-14-store-v0.md):

1. **The admission oracle's sidecars are what the store's invariants assume** —
   deterministic bytes, a declaration mirror that round-trips to the same
   canonical hash, dependency edges that exclude identity slots, and a typed
   refusal carrying the refusing layer's own error class.
2. **`StoreResolver` is behaviourally identical to `ExperimentResolver`** over
   every object, and produces **byte-identical prompts** for every
   (task, regime) pair the experiment runs — 26 corpus tasks and 8 held-out
   tasks across four regimes, with and without leave-one-out.

The export document is taken from a real seeded store when one is present
(`LOOM_STORE_EXPORT`, or `.loom-store/export-resolver.json` at the repo root),
and otherwise synthesized from the same oracle the store admits through. Both
paths exercise the same sidecars; the store path additionally proves the Rust
side carried them across unchanged, which is asserted explicitly when it is
available. Keeping the fallback is what lets `task prototype:test` stay green on
a checkout with no Rust toolchain, without weakening what it checks when the
toolchain is there.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

import corpus_registry
import store_admit
import transcode
from declarations import DeclarationRegistry
from experiment import prompts
from experiment.evaluate import run_funnel
from experiment.resolver import KIND_ABILITY, KIND_DATA, KIND_DEFINITION, KIND_EXTERN, ExperimentResolver
from experiment.store_resolver import StoreExportError, StoreResolver

REPO_ROOT = Path(__file__).resolve().parent.parent


def oracle_document() -> dict:
    """An export document built straight from the oracle, with no store."""
    objects = [sidecar for _, sidecar in store_admit.corpus_objects()]
    objects.sort(key=lambda sidecar: (sidecar["sequence"], sidecar["hash"]))
    return {"schema": 1, "store": {"contracts": {}}, "objects": objects}


def store_export_path() -> Path | None:
    override = os.environ.get("LOOM_STORE_EXPORT")
    candidate = Path(override) if override else REPO_ROOT / ".loom-store" / "export-resolver.json"
    return candidate if candidate.is_file() else None


class AdmissionSidecarTest(unittest.TestCase):
    """What the oracle emits, checked where the store cannot check it."""

    @classmethod
    def setUpClass(cls):
        cls.emitted = list(store_admit.corpus_objects())

    def test_the_pinned_corpus_admits_completely(self):
        counts: dict[str, int] = {}
        for _, sidecar in self.emitted:
            counts[sidecar["kind"]] = counts.get(sidecar["kind"], 0) + 1
        self.assertEqual(
            counts,
            {
                store_admit.KIND_ABILITY: 8,
                store_admit.KIND_DATA: 4,
                store_admit.KIND_EXTERN: 9,
                store_admit.KIND_DEFINITION: 26,
            },
        )

    def test_every_object_hashes_to_the_name_its_sidecar_claims(self):
        import hashlib

        for obj, sidecar in self.emitted:
            self.assertEqual(hashlib.sha256(obj).hexdigest(), sidecar["hash"])

    def test_sidecar_bytes_are_deterministic(self):
        """Re-seeding must reproduce a byte-identical store, so this must hold."""
        again = list(store_admit.corpus_objects())
        for (_, first), (_, second) in zip(self.emitted, again):
            self.assertEqual(
                store_admit.sidecar_bytes(first), store_admit.sidecar_bytes(second)
            )

    def test_sidecars_carry_no_wall_clock(self):
        """Determinism is a property, not a habit: nothing here may be a time."""
        for _, sidecar in self.emitted:
            text = json.dumps(sidecar)
            self.assertNotIn("timestamp", text)
            self.assertNotIn("admitted_at", text)

    def test_declaration_mirror_round_trips_to_the_same_canonical_hash(self):
        import declarations

        for _, sidecar in self.emitted:
            if sidecar["kind"] == store_admit.KIND_DEFINITION:
                self.assertIsNone(sidecar["object"])
                continue
            recovered = store_admit.json_to_ir(sidecar["object"])
            self.assertEqual(declarations.declaration_hash(recovered).hex(), sidecar["hash"])

    def test_definition_surface_round_trips_to_the_same_identity(self):
        for _, sidecar in self.emitted:
            if sidecar["kind"] != store_admit.KIND_DEFINITION:
                self.assertIsNone(sidecar["surface"])
                continue
            _, _, digest = transcode.transcode_source(sidecar["surface"])
            self.assertEqual(digest, sidecar["hash"])

    def test_dependency_edges_exclude_identity_slots(self):
        """A nominal key and a pinned artifact are not store objects."""
        stored = {sidecar["hash"] for _, sidecar in self.emitted}
        nominal = {corpus_registry.nominal_key(name).hex() for name in corpus_registry.HASHES}
        for _, sidecar in self.emitted:
            for edge in sidecar["deps"]:
                self.assertIn(edge, stored, f"{sidecar['name']} depends on an absent object")
            provenance = sidecar["provenance"]
            if "artifact" in provenance:
                self.assertNotIn(provenance["artifact"], sidecar["deps"])
            if "nominal_key" in provenance:
                self.assertNotIn(provenance["nominal_key"], sidecar["deps"])
        # The corpus's data declarations really do carry a nominal key that is
        # distinct from their store hash, so the exclusion above is load-bearing
        # rather than vacuously true.
        self.assertTrue(nominal.isdisjoint(stored))

    def test_a_definition_that_names_an_absent_ability_is_refused_by_its_own_layer(self):
        registry = corpus_registry.registry()
        resolve = corpus_registry.reference_type(registry)

        class _Pinned:
            declarations = registry
            operation_arity = staticmethod(registry.operation_arity)
            reference_type = staticmethod(resolve)

        invented = "0x" + "01" * 32
        source = f"(def (fn Unit ({invented}) Unit) (lam Unit (var 0)))"
        with self.assertRaises(store_admit.AdmissionRefused) as caught:
            store_admit.definition_sidecar(source, resolver=_Pinned, sequence=0)
        self.assertIn(caught.exception.layer, ("scope", "references", "typecheck"))
        self.assertTrue(caught.exception.error_class)
        self.assertIn("01" * 32, caught.exception.message)

    def test_a_noncanonical_surface_is_refused_at_the_parser(self):
        with self.assertRaises(store_admit.AdmissionRefused) as caught:
            store_admit.definition_sidecar(
                "(def  (fn Bool () Bool) (lam Bool (var 0)))", resolver=None, sequence=0
            )
        self.assertEqual(caught.exception.layer, "parser")
        self.assertEqual(caught.exception.error_class, "SurfaceError")


class StoreResolverEquivalenceTest(unittest.TestCase):
    """`StoreResolver` answers every question `ExperimentResolver` answers."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = ExperimentResolver()
        cls.document = oracle_document()
        exported = store_export_path()
        cls.export_path = exported
        cls.store = StoreResolver.from_path(exported) if exported else StoreResolver(cls.document)

    def test_the_seeded_store_carries_the_oracle_sidecars_unchanged(self):
        if self.export_path is None:
            self.skipTest("no seeded store; run `task store:seed && task store:export`")
        exported = json.loads(self.export_path.read_text(encoding="utf-8"))
        self.assertEqual(exported["objects"], self.document["objects"])

    def test_object_counts_match(self):
        self.assertEqual(self.store.counts(), self.corpus.counts())
        self.assertEqual(len(self.store), len(self.corpus))
        self.assertEqual(
            self.store.counts(),
            {KIND_DEFINITION: 26, KIND_DATA: 4, KIND_ABILITY: 8, KIND_EXTERN: 9},
        )

    def test_digests_match_including_order(self):
        self.assertEqual(self.store.digests(), self.corpus.digests())

    def test_every_hash_resolves_to_the_same_object(self):
        for digest in self.corpus.digests():
            with self.subTest(hash=digest.hex()):
                self.assertIn(digest, self.store)
                self.assertEqual(self.store.resolve(digest), self.corpus.resolve(digest))

    def test_reference_type_matches_for_every_hash(self):
        for digest in self.corpus.digests():
            with self.subTest(hash=digest.hex()):
                try:
                    expected = self.corpus.reference_type(digest)
                except (LookupError, Exception) as error:  # noqa: BLE001
                    with self.assertRaises(type(error)):
                        self.store.reference_type(digest)
                    continue
                self.assertEqual(self.store.reference_type(digest), expected)

    def test_operation_arity_matches_for_every_ability_operation(self):
        for digest in self.corpus.digests():
            found = self.corpus.resolve(digest)
            if found.kind != KIND_ABILITY:
                continue
            for operation in range(4):
                try:
                    expected = self.corpus.operation_arity(digest, operation)
                except LookupError:
                    with self.assertRaises(LookupError):
                        self.store.operation_arity(digest, operation)
                    continue
                self.assertEqual(self.store.operation_arity(digest, operation), expected)

    def test_the_declaration_registries_hold_the_same_objects(self):
        for digest in self.corpus.digests():
            found = self.corpus.resolve(digest)
            with self.subTest(hash=digest.hex(), kind=found.kind):
                if found.kind == KIND_DATA:
                    self.assertEqual(
                        self.store.declarations.data_object(digest),
                        self.corpus.declarations.data_object(digest),
                    )
                elif found.kind == KIND_ABILITY:
                    self.assertEqual(
                        self.store.declarations.ability_object(digest),
                        self.corpus.declarations.ability_object(digest),
                    )
                elif found.kind == KIND_EXTERN:
                    self.assertEqual(
                        self.store.declarations.extern_object(digest),
                        self.corpus.declarations.extern_object(digest),
                    )

    def test_names_resolve_to_the_same_hashes(self):
        for entry in corpus_registry.MANIFEST:
            self.assertEqual(
                self.store.digest_for(entry.name_path), self.corpus.digest_for(entry.name_path)
            )
        for name in list(corpus_registry.HASHES) + list(corpus_registry.EXTERN_HASHES):
            self.assertEqual(self.store.digest_for(name), self.corpus.digest_for(name))

    def test_definitions_come_back_in_the_same_order(self):
        self.assertEqual(self.store.definitions(), self.corpus.definitions())

    def test_entries_carry_the_same_spec_and_identity(self):
        for entry in corpus_registry.MANIFEST:
            digest = bytes.fromhex(entry.identity)
            stored = self.store.entry(digest)
            self.assertEqual(stored.spec, entry.spec)
            self.assertEqual(stored.name_path, entry.name_path)
            self.assertEqual(stored.identity, entry.identity)
            self.assertEqual(stored.source_text(), entry.source_text())

    def test_a_miss_is_a_lookup_error_naming_the_hash(self):
        absent = bytes.fromhex("ab" * 32)
        for resolver in (self.store, self.corpus):
            with self.assertRaises(LookupError) as caught:
                resolver.resolve(absent)
            self.assertIn("ab" * 32, str(caught.exception))
        # `reference_type` refuses through the declaration layer's own class,
        # which is what `ExperimentResolver` does and what the funnel classifies
        # as that stage's rejection — so the two must agree on the *type*, not
        # merely on the fact of refusal.
        with self.assertRaises(Exception) as through_corpus:
            self.corpus.reference_type(absent)
        with self.assertRaises(type(through_corpus.exception)) as through_store:
            self.store.reference_type(absent)
        self.assertIn("ab" * 32, str(through_store.exception))
        with self.assertRaises(LookupError):
            self.store.entry(absent)
        with self.assertRaises(LookupError):
            self.store.digest_for("corpus/does/notExist")

    def test_resolved_types_are_isolated_copies(self):
        digest = self.store.digest_for("corpus/bool/not")
        self.store.resolve(digest).type_ir.append("mutated")
        self.assertNotIn("mutated", self.store.resolve(digest).type_ir)


class PromptEquivalenceTest(unittest.TestCase):
    """The acceptance gate: byte-identical prompts from either resolver."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = ExperimentResolver()
        exported = store_export_path()
        cls.store = (
            StoreResolver.from_path(exported) if exported else StoreResolver(oracle_document())
        )

    def test_every_task_and_regime_builds_a_byte_identical_prompt(self):
        pairs = 0
        for regime in prompts.REGIMES:
            for task in prompts.tasks_for_regime(regime):
                for leave_one_out in (True, False):
                    with self.subTest(regime=regime, task=task.task_id, loo=leave_one_out):
                        expected = prompts.build_prompt(
                            task, regime, self.corpus, leave_one_out=leave_one_out
                        )
                        actual = prompts.build_prompt(
                            task, regime, self.store, leave_one_out=leave_one_out
                        )
                        self.assertEqual(actual, expected)
                    pairs += 1
        # 4 regimes: three over 26 corpus tasks, one over 8 held-out tasks,
        # each built twice for the leave-one-out flag.
        self.assertEqual(pairs, (26 * 3 + 8) * 2)

    def test_narrowing_feedback_also_lands_identically(self):
        task = prompts.corpus_tasks()[0]
        narrowing = "The previous draw was rejected at typecheck: expected Bool."
        self.assertEqual(
            prompts.build_prompt(
                task, prompts.REGIME_FEW_SHOT, self.store, narrowing=narrowing
            ),
            prompts.build_prompt(
                task, prompts.REGIME_FEW_SHOT, self.corpus, narrowing=narrowing
            ),
        )

    def test_the_full_corpus_prompt_is_not_trivially_short(self):
        """Guard against the two resolvers agreeing because both showed nothing."""
        task = prompts.held_out_tasks()[0]
        prompt = prompts.build_prompt(task, prompts.REGIME_FULL_CORPUS, self.store)
        self.assertGreater(len(prompt), 4000)
        self.assertIn("(def ", prompt)


class FunnelEquivalenceTest(unittest.TestCase):
    """The validation funnel reaches the same verdict through either resolver."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = ExperimentResolver()
        exported = store_export_path()
        cls.store = (
            StoreResolver.from_path(exported) if exported else StoreResolver(oracle_document())
        )

    def test_every_corpus_fixture_funnels_identically(self):
        for entry in corpus_registry.MANIFEST:
            source = entry.source_text()
            with self.subTest(fixture=entry.fixture):
                self.assertEqual(
                    run_funnel(source, self.store), run_funnel(source, self.corpus)
                )

    def test_a_hallucinated_hash_is_refused_identically(self):
        source = "(def (fn Unit () Unit) (lam Unit (ref 0x" + "01" * 32 + ")))"
        through_store = run_funnel(source, self.store)
        through_corpus = run_funnel(source, self.corpus)
        self.assertEqual(through_store, through_corpus)
        self.assertFalse(through_store.accepted)


class ExportDocumentTest(unittest.TestCase):
    """The export is refused rather than half-read when it is wrong."""

    def test_a_wrong_schema_is_refused(self):
        with self.assertRaises(StoreExportError):
            StoreResolver({"schema": 99, "objects": []})

    def test_a_missing_objects_array_is_refused(self):
        with self.assertRaises(StoreExportError):
            StoreResolver({"schema": 1})

    def test_a_tampered_surface_is_caught_by_the_identity_check(self):
        document = oracle_document()
        for sidecar in document["objects"]:
            if sidecar["kind"] == KIND_DEFINITION:
                sidecar["surface"] = "(def (fn Bool () Bool) (lam Bool (var 0)))"
                break
        with self.assertRaises(StoreExportError) as caught:
            StoreResolver(document)
        self.assertIn("hashes to", str(caught.exception))

    def test_a_tampered_type_column_is_caught_against_the_reconstruction(self):
        document = oracle_document()
        for sidecar in document["objects"]:
            if sidecar["kind"] == KIND_DEFINITION:
                sidecar["type_surface"] = "(fn I64 () I64)"
                break
        with self.assertRaises(StoreExportError) as caught:
            StoreResolver(document)
        self.assertIn("index type surface", str(caught.exception))

    def test_a_tampered_declaration_mirror_is_caught_by_the_declaration_layer(self):
        document = oracle_document()
        for sidecar in document["objects"]:
            if sidecar["kind"] == KIND_ABILITY:
                sidecar["object"][2].append([[], [0, 0]])
                break
        with self.assertRaises(Exception) as caught:
            StoreResolver(document)
        self.assertEqual(type(caught.exception).__name__, "DeclarationError")

    def test_an_empty_store_builds_an_empty_resolver_rather_than_failing(self):
        resolver = StoreResolver({"schema": 1, "objects": []})
        self.assertEqual(len(resolver), 0)
        self.assertEqual(resolver.definitions(), ())
        self.assertIsInstance(resolver.declarations, DeclarationRegistry)


if __name__ == "__main__":
    unittest.main()
