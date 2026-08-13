"""Phase A harness tests, driven end to end by the deterministic stub backend.

The stub emits canned outputs — one valid corpus surface and one broken at each
of the four contract layers — so the funnel, the budget accounting, the JSONL
record and the report (including the failure-distribution-by-layer table that
gates Phase B) are all exercised with no model, no network, and no grammar
sampler. A live run adds a model; it does not add a code path.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

import corpus_registry
import declarations
from experiment import prompts, runner
from experiment.backends import BackendUnavailable, StubBackend, make_backend
from experiment.evaluate import ACCEPTED, LAYERS, OUTCOMES, extract_definition, run_funnel, score_semantic
from experiment.prompts import KIND_CORPUS, KIND_HELD_OUT, REGIMES
from experiment.resolver import KIND_ABILITY, KIND_DATA, KIND_DEFINITION, KIND_EXTERN, ExperimentResolver

HERE = Path(__file__).resolve().parent

BOOL_NOT = (HERE / "corpus" / "bool_not.loom.sexpr").read_text(encoding="utf-8").strip()
UNKNOWN_HASH = "0x" + "ab" * 32

BROKEN_SYNTAX = "(def Bool (lam Bool (if (var 0)"
BROKEN_SCOPE = "(def (fn Bool () Bool) (lam Bool (var 3)))"
BROKEN_REFERENCES = f"(def (data {UNKNOWN_HASH} ()) (hole (data {UNKNOWN_HASH} ()) ()))"
BROKEN_TYPE = "(def Bool (lit i64 1))"

SUM_TASK = next(t for t in prompts.HELD_OUT_TASKS if t.task_id == "heldout/list/sum")
HELD_OUT_HOLE = f"(def {SUM_TASK.expected_type_surface} (hole {SUM_TASK.expected_type_surface} ()))"

#: Without a grammar the model may emit anything, syntax errors included.
STUB_OUTPUTS = [BOOL_NOT, BROKEN_SYNTAX, BROKEN_SCOPE, BROKEN_REFERENCES, BROKEN_TYPE, HELD_OUT_HOLE]
#: Under `loom.gbnf` a syntax failure is impossible by construction, so the
#: grammar script is the same list with the syntax break removed. That is the
#: whole of what condition 2 buys, modelled exactly.
STUB_GRAMMAR_OUTPUTS = [BOOL_NOT, BROKEN_SCOPE, BROKEN_REFERENCES, BROKEN_TYPE, HELD_OUT_HOLE]


def stub_config(**overrides):
    config = runner.Config(
        backend="stub",
        seeds=[1],
        conditions=list(runner.CONDITIONS),
        regimes=["few_shot", "held_out"],
        tasks=["corpus/bool/not", "heldout/list/sum"],
        token_budget_per_task=400,
        max_tokens_per_draw=60,
        max_draws_per_task=8,
        stub_outputs=STUB_OUTPUTS,
        stub_grammar_outputs=STUB_GRAMMAR_OUTPUTS,
        source_path="<test>",
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    config.validate()
    return config


class ResolverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def test_holds_every_corpus_definition_and_declaration(self):
        counts = self.resolver.counts()
        self.assertEqual(counts[KIND_DEFINITION], len(corpus_registry.MANIFEST))
        self.assertEqual(counts[KIND_DATA], len(corpus_registry.HASHES))
        self.assertEqual(counts[KIND_EXTERN], len(corpus_registry.EXTERN_HASHES))
        self.assertGreater(counts[KIND_ABILITY], 0)

    def test_resolves_definitions_by_hash_and_by_name(self):
        for entry in corpus_registry.MANIFEST:
            digest = bytes.fromhex(entry.identity)
            found = self.resolver.resolve(digest)
            self.assertEqual(found.kind, KIND_DEFINITION)
            self.assertEqual(found.name, entry.name_path)
            self.assertEqual(found.surface, entry.source_text().rstrip("\n"))
            self.assertEqual(self.resolver.digest_for(entry.name_path), digest)

    def test_reference_type_agrees_with_the_corpus_resolver(self):
        reference = corpus_registry.reference_type()
        for entry in corpus_registry.MANIFEST:
            digest = bytes.fromhex(entry.identity)
            self.assertEqual(self.resolver.reference_type(digest), reference(digest))
        for digest in corpus_registry.EXTERN_HASHES.values():
            self.assertEqual(self.resolver.reference_type(digest), reference(digest))

    def test_unknown_hash_raises_rather_than_guessing(self):
        with self.assertRaises(LookupError):
            self.resolver.resolve(bytes.fromhex("ab" * 32))
        # Same refusal as `corpus_registry.reference_type`'s closure: the
        # declaration registry has the last word and reports its own class.
        with self.assertRaises(declarations.DeclarationError):
            self.resolver.reference_type(bytes.fromhex("ab" * 32))

    def test_returned_types_are_isolated_copies(self):
        digest = self.resolver.digest_for("corpus/bool/not")
        first = self.resolver.resolve(digest).type_ir
        first.append("mutated")
        self.assertNotIn("mutated", self.resolver.resolve(digest).type_ir)


class PromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def test_regimes_supply_the_expected_example_counts(self):
        # A held-out task is not in the corpus, so leave-one-out cannot fire and
        # the counts are the regimes' own.
        task = SUM_TASK
        self.assertEqual(prompts.example_names(prompts.REGIME_NONE, task), ())
        self.assertEqual(
            prompts.example_names(prompts.REGIME_FEW_SHOT, task), prompts.FEW_SHOT_NAMES)
        self.assertEqual(
            len(prompts.example_names(prompts.REGIME_FULL_CORPUS, task)),
            len(corpus_registry.MANIFEST))

    def test_leave_one_out_removes_the_task_and_keeps_the_few_shot_size(self):
        task = next(t for t in prompts.corpus_tasks() if t.task_id == "corpus/bool/not")
        names = prompts.example_names(prompts.REGIME_FEW_SHOT, task)
        self.assertNotIn("corpus/bool/not", names)
        self.assertEqual(len(names), len(prompts.FEW_SHOT_NAMES))
        full = prompts.example_names(prompts.REGIME_FULL_CORPUS, task)
        self.assertNotIn("corpus/bool/not", full)
        self.assertEqual(len(full), len(corpus_registry.MANIFEST) - 1)
        kept = prompts.example_names(prompts.REGIME_FEW_SHOT, task, leave_one_out=False)
        self.assertIn("corpus/bool/not", kept)

    def test_prompt_carries_the_ask_the_examples_and_no_hash_directory(self):
        task = next(t for t in prompts.corpus_tasks() if t.task_id == "corpus/list/reverse")
        prompt = prompts.build_prompt(task, prompts.REGIME_FEW_SHOT, self.resolver)
        self.assertIn(task.spec, prompt)
        self.assertIn(self.resolver.surface(self.resolver.digest_for("corpus/bool/not")), prompt)
        self.assertNotIn(task.expected_surface, prompt)
        # Prediction 2 needs hashes to arrive only through examples, so the
        # no-example regime must contain no 64-hex hash anywhere.
        none_prompt = prompts.build_prompt(task, prompts.REGIME_NONE, self.resolver)
        self.assertIsNone(re.search(r"0x[0-9a-f]{64}", none_prompt))
        self.assertIsNotNone(re.search(r"0x[0-9a-f]{64}", prompt))

    def test_narrowing_is_appended_before_the_ask(self):
        task = prompts.corpus_tasks()[0]
        plain = prompts.build_prompt(task, prompts.REGIME_NONE, self.resolver)
        narrowed = prompts.build_prompt(
            task, prompts.REGIME_NONE, self.resolver, narrowing="REJECTED: nope")
        self.assertNotIn("REJECTED", plain)
        self.assertIn("REJECTED: nope", narrowed)
        self.assertLess(narrowed.index("REJECTED"), narrowed.index(task.spec))

    def test_task_sets(self):
        self.assertEqual(len(prompts.corpus_tasks()), len(corpus_registry.MANIFEST))
        self.assertEqual(len(prompts.HELD_OUT_TASKS), 8)
        for regime in (prompts.REGIME_NONE, prompts.REGIME_FEW_SHOT, prompts.REGIME_FULL_CORPUS):
            self.assertTrue(all(t.kind == KIND_CORPUS for t in prompts.tasks_for_regime(regime)))
        self.assertTrue(
            all(t.kind == KIND_HELD_OUT for t in prompts.tasks_for_regime(prompts.REGIME_HELD_OUT)))
        with self.assertRaises(ValueError):
            prompts.tasks_for_regime("nonesuch")

    def test_held_out_specs_are_new_and_composition_shaped(self):
        corpus_specs = {entry.spec for entry in corpus_registry.MANIFEST}
        for task in prompts.HELD_OUT_TASKS:
            self.assertNotIn(task.spec, corpus_specs, task.task_id)
            self.assertGreaterEqual(len(task.composes), 2, task.task_id)
            self.assertEqual(task.scoring_rule, "checked+type-exact")

    def test_every_held_out_expected_type_is_well_formed(self):
        """A typed hole at the expected type must pass all four layers.

        This is what stops a typo in an expected type from silently scoring
        every held-out generation as a failure.
        """
        for task in prompts.HELD_OUT_TASKS:
            surface = task.expected_type_surface
            probe = f"(def {surface} (hole {surface} ()))"
            self.assertEqual(run_funnel(probe, self.resolver).outcome, ACCEPTED, task.task_id)


class FunnelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def test_each_canned_output_lands_on_its_own_layer(self):
        expected = {
            BOOL_NOT: ACCEPTED,
            BROKEN_SYNTAX: "parse",
            BROKEN_SCOPE: "scope",
            BROKEN_REFERENCES: "references",
            BROKEN_TYPE: "typecheck",
        }
        for source, outcome in expected.items():
            self.assertEqual(run_funnel(source, self.resolver).outcome, outcome, source[:40])

    def test_layers_passed_counts_up_with_the_funnel(self):
        self.assertEqual(run_funnel(BROKEN_SYNTAX, self.resolver).layers_passed, 0)
        self.assertEqual(run_funnel(BROKEN_SCOPE, self.resolver).layers_passed, 1)
        self.assertEqual(run_funnel(BROKEN_REFERENCES, self.resolver).layers_passed, 2)
        self.assertEqual(run_funnel(BROKEN_TYPE, self.resolver).layers_passed, 3)
        self.assertEqual(run_funnel(BOOL_NOT, self.resolver).layers_passed, 4)

    def test_scope_failures_are_flagged_for_the_de_bruijn_prediction(self):
        self.assertTrue(run_funnel(BROKEN_SCOPE, self.resolver).de_bruijn_suspected)
        self.assertFalse(run_funnel(BROKEN_TYPE, self.resolver).de_bruijn_suspected)

    def test_extraction_is_uniform_and_generous(self):
        self.assertEqual(extract_definition(f"```\n{BOOL_NOT}\n```"), BOOL_NOT)
        self.assertEqual(extract_definition(f"  {BOOL_NOT}  \n"), BOOL_NOT)
        self.assertEqual(extract_definition(f"{BOOL_NOT} and that is the answer"), BOOL_NOT)
        self.assertEqual(extract_definition(BOOL_NOT), BOOL_NOT)

    def test_corpus_semantic_success_is_identity_match(self):
        task = next(t for t in prompts.corpus_tasks() if t.task_id == "corpus/bool/not")
        good = score_semantic(task, run_funnel(BOOL_NOT, self.resolver), BOOL_NOT)
        self.assertTrue(good.success)
        self.assertEqual(good.rule, "identity-match")
        self.assertFalse(good.rubric_pending)
        # A different, perfectly valid definition is not this task's answer.
        other = self.resolver.surface(self.resolver.digest_for("corpus/list/reverse"))
        bad = score_semantic(task, run_funnel(other, self.resolver), other)
        self.assertFalse(bad.success)

    def test_held_out_semantic_success_is_checked_plus_type_exact(self):
        good = score_semantic(SUM_TASK, run_funnel(HELD_OUT_HOLE, self.resolver), HELD_OUT_HOLE)
        self.assertTrue(good.success)
        self.assertEqual(good.rule, "checked+type-exact")
        self.assertTrue(good.rubric_pending, "R3's hand-scored half must stay visible")
        wrong_type = score_semantic(SUM_TASK, run_funnel(BOOL_NOT, self.resolver), BOOL_NOT)
        self.assertFalse(wrong_type.success)
        self.assertEqual(wrong_type.detail, "type mismatch")
        unchecked = score_semantic(SUM_TASK, run_funnel(BROKEN_TYPE, self.resolver), BROKEN_TYPE)
        self.assertFalse(unchecked.success)
        self.assertFalse(unchecked.rubric_pending)


class BackendTest(unittest.TestCase):
    def test_no_backend_points_at_the_t5_model_item(self):
        config = runner.Config(source_path="phase_a.config.json")
        with self.assertRaises(BackendUnavailable) as raised:
            make_backend(config)
        message = str(raised.exception)
        self.assertIn("T5", message)
        self.assertIn("2026-08-13-masked-generation-experiment.md", message)
        self.assertIn("phase_a.config.json", message)

    def test_unknown_backend_names_the_known_ones(self):
        with self.assertRaises(BackendUnavailable) as raised:
            make_backend(runner.Config(backend="gpt"))
        self.assertIn("llama-server", str(raised.exception))

    def test_stub_is_deterministic_and_honours_the_grammar_split(self):
        backend = StubBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS)
        plain = [backend.generate("p", max_tokens=1000).text for _ in range(len(STUB_OUTPUTS))]
        self.assertEqual(plain, STUB_OUTPUTS)
        grammared = StubBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS)
        drawn = [
            grammared.generate("p", grammar="g", max_tokens=1000).text
            for _ in range(len(STUB_GRAMMAR_OUTPUTS))
        ]
        self.assertEqual(drawn, STUB_GRAMMAR_OUTPUTS)
        self.assertNotIn(BROKEN_SYNTAX, drawn)

    def test_stub_never_exceeds_the_per_draw_cap(self):
        backend = StubBackend([BOOL_NOT])
        generation = backend.generate("p", max_tokens=3)
        self.assertEqual(generation.completion_tokens, 3)
        self.assertEqual(generation.stop_reason, "length")


class ConfigTest(unittest.TestCase):
    def test_shipped_config_loads_and_refuses_to_run(self):
        config = runner.Config.load(runner.DEFAULT_CONFIG)
        self.assertEqual(config.regimes, list(REGIMES))
        self.assertEqual(config.conditions, list(runner.CONDITIONS))
        with self.assertRaises(BackendUnavailable):
            make_backend(config)

    def test_condition_four_is_refused_by_name(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(conditions=["masked"]).validate()
        self.assertIn("Phase B", str(raised.exception))

    def test_a_live_backend_needs_a_recorded_model_identity(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(backend="llama-cli", model_path="/tmp/model.gguf").validate()
        self.assertIn("model_identity", str(raised.exception))

    def test_unknown_config_keys_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({"backend": "stub", "budget": 10}), encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                runner.Config.load(path)
            self.assertIn("budget", str(raised.exception))


class EndToEndStubRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = stub_config()
        cls.resolver = ExperimentResolver()
        cls.records, cls.summary = runner.run(cls.config, resolver=cls.resolver)

    def test_every_configured_cell_produced_records(self):
        cells = {(r["condition"], r["regime"]) for r in self.records}
        self.assertEqual(
            cells,
            {(c, g) for c in self.config.conditions for g in self.config.regimes},
        )

    def test_records_carry_the_full_run_record(self):
        required = {
            "task", "task_kind", "condition", "regime", "seed", "draw", "draw_seed",
            "tokens_completion", "tokens_prompt", "tokens_used", "budget",
            "funnel_outcome", "layers_passed", "error_class", "error_path",
            "semantic_success", "semantic_rule", "rubric_pending", "source",
            "latency_s", "backend", "narrowed", "grammar",
        }
        for record in self.records:
            self.assertTrue(required <= set(record), sorted(required - set(record)))
            self.assertIn(record["funnel_outcome"], OUTCOMES)

    def test_the_budget_rule_is_per_task_and_shared_by_every_condition(self):
        spent = {}
        for record in self.records:
            key = (record["task"], record["condition"], record["regime"], record["seed"])
            spent[key] = spent.get(key, 0) + record["tokens_completion"]
        for key, total in spent.items():
            self.assertLessEqual(total, self.config.token_budget_per_task, key)
        budgets = {record["budget"] for record in self.records}
        self.assertEqual(budgets, {self.config.token_budget_per_task})

    def test_the_grammar_removes_syntax_failures_and_only_those(self):
        grammar_outcomes = {r["funnel_outcome"] for r in self.records if r["grammar"]}
        plain_outcomes = {r["funnel_outcome"] for r in self.records if not r["grammar"]}
        self.assertNotIn("parse", grammar_outcomes)
        self.assertIn("parse", plain_outcomes)

    def test_all_four_layers_and_acceptance_are_observed(self):
        observed = {record["funnel_outcome"] for record in self.records}
        self.assertEqual(observed, set(OUTCOMES))

    def test_rejection_sampling_narrows_after_a_rejected_draw(self):
        rejection = [r for r in self.records if r["condition"] == runner.CONDITION_GBNF_REJECTION]
        self.assertTrue(any(r["narrowed"] for r in rejection))
        blind = [r for r in self.records if r["condition"] == runner.CONDITION_GBNF]
        self.assertFalse(any(r["narrowed"] for r in blind))

    def test_semantic_success_is_scored_by_task_kind(self):
        corpus_hits = [
            r for r in self.records
            if r["task_kind"] == KIND_CORPUS and r["semantic_success"]]
        self.assertTrue(corpus_hits)
        self.assertTrue(all(r["semantic_rule"] == "identity-match" for r in corpus_hits))
        held_out_hits = [
            r for r in self.records
            if r["task_kind"] == KIND_HELD_OUT and r["semantic_success"]]
        self.assertTrue(held_out_hits)
        self.assertTrue(all(r["rubric_pending"] for r in held_out_hits))

    def test_summary_carries_the_phase_b_gate(self):
        gate = self.summary["failure_distribution_by_layer"]
        self.assertEqual(set(gate["by_regime"]), set(self.config.regimes))
        for counts in gate["by_regime"].values():
            self.assertEqual(counts.get("parse", 0), 0)
        self.assertEqual(
            sum(gate["overall"].values()),
            sum(1 for r in self.records if r["grammar"]))
        self.assertIsNotNone(self.summary["de_bruijn_share_of_scope_failures"])
        self.assertEqual(set(self.summary["error_paths"]), set(LAYERS))
        self.assertEqual(
            self.summary["contract_versions"]["typecheck"], "1.0")

    def test_report_states_the_gate_and_the_dominant_layer(self):
        report = runner.render_report(self.summary, self.records)
        self.assertIn("Failure distribution by checker layer", report)
        self.assertIn("Dominant post-syntax failure layer", report)
        for layer in LAYERS:
            self.assertIn(layer, report)
        self.assertIn("hand-scored rubric", report)

    def test_outputs_are_written(self):
        with tempfile.TemporaryDirectory() as directory:
            records_path, summary_path, report_path = runner.write_outputs(
                self.records, self.summary, directory)
            lines = records_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), len(self.records))
            self.assertEqual(json.loads(lines[0])["task"], self.records[0]["task"])
            self.assertIn("cells", json.loads(summary_path.read_text(encoding="utf-8")))
            self.assertIn("Phase A results", report_path.read_text(encoding="utf-8"))

    def test_a_rerun_with_the_same_config_reproduces_the_run(self):
        again, _ = runner.run(stub_config(), resolver=self.resolver)
        self.assertEqual(
            [(r["task"], r["condition"], r["draw"], r["funnel_outcome"]) for r in again],
            [(r["task"], r["condition"], r["draw"], r["funnel_outcome"]) for r in self.records])


class CliTest(unittest.TestCase):
    """The one-command entry point, with its streams captured.

    The failure path prints a long operator-facing message; capturing it keeps
    `task prototype:test` readable while still asserting on what it says.
    """

    @staticmethod
    def _main(argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = runner.main(argv)
        return status, out.getvalue(), err.getvalue()

    def test_dry_run_reports_the_plan_without_a_backend(self):
        status, out, _ = self._main(["--dry-run"])
        self.assertEqual(status, 0)
        self.assertIn("cells to run", out)
        self.assertIn("token budget/task", out)

    def test_missing_backend_exits_non_zero_with_the_pointer(self):
        status, _, err = self._main([])
        self.assertEqual(status, 2)
        self.assertIn("T5", err)

    def test_a_stub_run_writes_its_three_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "stub.json"
            payload = {
                "backend": "stub",
                "seeds": [1],
                "conditions": ["gbnf"],
                "regimes": ["few_shot"],
                "tasks": ["corpus/bool/not"],
                "token_budget_per_task": 120,
                "max_tokens_per_draw": 60,
                "max_draws_per_task": 4,
                "stub_outputs": STUB_OUTPUTS,
                "stub_grammar_outputs": STUB_GRAMMAR_OUTPUTS,
                "output_dir": str(Path(directory) / "out"),
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            status, out, _ = self._main(["--config", str(config_path)])
            self.assertEqual(status, 0)
            self.assertIn("Phase A results", out)
            for name in ("records.jsonl", "summary.json", "report.md"):
                self.assertTrue((Path(directory) / "out" / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
