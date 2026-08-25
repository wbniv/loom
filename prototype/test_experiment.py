"""Phase A harness tests, driven end to end by the deterministic stub backend.

The stub emits canned outputs — one valid corpus surface and one broken at each
of the four contract layers — so the funnel, the budget accounting, the JSONL
record and the report (including the failure-distribution-by-layer table that
gates Phase B) are all exercised with no model, no network, and no grammar
sampler. A live run adds a model; it does not add a code path.
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

import corpus_registry
import declarations
from experiment import prompts, runner
from experiment.addressability_audit import HAND_SOLVED
from experiment.backends import BackendUnavailable, StubBackend, make_backend
from experiment.evaluate import ACCEPTED, LAYERS, OUTCOMES, extract_definition, run_funnel, score_semantic
from experiment.prompts import KIND_CORPUS, KIND_HELD_OUT, REGIME_HELD_OUT, REGIMES
from experiment.resolver import KIND_ABILITY, KIND_DATA, KIND_DEFINITION, KIND_EXTERN, ExperimentResolver
from transcode import type_to_surface

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


def crash_safety_config(**overrides):
    """Two one-task cells (seed 1, seed 2), each exactly two draws.

    Small and deterministic on purpose: the crash-safety tests care about
    *which* cell's draws land on disk and *how many* backend calls a resumed
    run makes, not about the harness's usual breadth.
    """
    config = runner.Config(
        backend="stub",
        seeds=[1, 2],
        conditions=[runner.CONDITION_GBNF],
        regimes=["few_shot"],
        tasks=["corpus/bool/not"],
        token_budget_per_task=1000,
        max_tokens_per_draw=60,
        max_draws_per_task=2,
        stub_outputs=STUB_OUTPUTS,
        stub_grammar_outputs=STUB_GRAMMAR_OUTPUTS,
        source_path="<test>",
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    config.validate()
    return config


class _FlakyBackend(StubBackend):
    """A `StubBackend` that raises `BackendUnavailable` on chosen calls.

    Models the real failure this hardening exists for: a draw that stalls
    past the backend's timeout (thermal-throttled decode collapsing to
    0.3 tok/s in the incident this file is a response to). `fail_at` is
    1-based; `fail_forever=True` keeps failing every call from `fail_at` on
    (a hard-down backend — exercises the abort path), `fail_forever=False`
    fails exactly that one call (a hiccup — exercises the retry path).
    """

    def __init__(self, *args, fail_at, fail_forever=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_at = fail_at
        self.fail_forever = fail_forever
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        if self.calls == self.fail_at or (self.fail_forever and self.calls >= self.fail_at):
            raise BackendUnavailable("stub: simulated backend hiccup")
        return super().generate(*args, **kwargs)


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


class ResolverRefusalFunnelTest(unittest.TestCase):
    """A generation naming a hallucinated hash is classified, never a crash.

    Regression for the first GPU run: the model invented ability 0x00..01,
    scope's arity resolver raised DeclarationError, and the funnel crashed the
    runner 552 records in. Per SPEC.md §2.3.1 an unresolvable dependency is
    reported at the consulting layer.
    """

    def test_hallucinated_ability_in_handle_is_a_scope_rejection(self):
        fake = "0x" + "00" * 31 + "01"
        src = f"(def I64 (handle {fake} (lit i64 1) ((0 (var 0))) (var 0)))"
        result = run_funnel(src, ExperimentResolver())
        self.assertEqual(result.outcome, "scope")
        self.assertEqual(result.error_class, "DeclarationError")

    def test_hallucinated_ability_without_clauses_is_a_references_rejection(self):
        fake = "0x" + "00" * 31 + "01"
        src = f"(def I64 (handle {fake} (lit i64 1) () (var 0)))"
        result = run_funnel(src, ExperimentResolver())
        self.assertEqual(result.outcome, "references")


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


class AddressBookTest(unittest.TestCase):
    """The next-lever arms (`docs/plans/2026-08-24-next-lever.md` §3, §4.2, §4.8).

    Two of these tests are the experiment's validity guarantees rather than
    ordinary behaviour checks, and they are written adversarially — each
    constructs the case a *naive* implementation would leak on and asserts it
    does not:

    * **the route must not leak.** `Task.composes` is analysis metadata. An
      implementation that "made sure the route is addressable" would pass every
      happy-path test and quietly turn `addr-typed` into an oracle arm, so the
      tests here feed the filter tasks with fabricated routes and assert the
      block does not move, and assert that a real route element the codomain
      test *excludes* stays excluded.
    * **a gold term must not leak.** Rows carry an address, a name and a type,
      never a term, and no arm may put a verified solution's bytes in a prompt.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.tasks = prompts.HELD_OUT_TASKS
        cls.concat = next(t for t in cls.tasks if t.task_id == "heldout/list/concatLength")

    # -- the control arm ---------------------------------------------------

    def test_none_is_the_default_and_changes_not_one_byte(self):
        """`addr-none` is the R4 prompt, or it is not a control arm."""
        self.assertEqual(
            inspect.signature(prompts.build_prompt).parameters["address_book"].default,
            prompts.ADDRESS_BOOK_NONE,
        )
        for regime in REGIMES:
            for task in prompts.tasks_for_regime(regime):
                plain = prompts.build_prompt(task, regime, self.resolver)
                explicit = prompts.build_prompt(
                    task, regime, self.resolver, address_book=prompts.ADDRESS_BOOK_NONE)
                self.assertEqual(plain, explicit, task.task_id)
                self.assertNotIn(prompts.ADDRESS_HEADER, plain, task.task_id)
        self.assertEqual(runner.Config().address_book, prompts.ADDRESS_BOOK_NONE)

    #: The pre-registered §4.2 arm configs are the only shipped configs allowed
    #: an address book, and each must carry exactly its declared arm.
    ADDRESS_ARM_CONFIGS = {
        "addr-full.config.json": "full",
        "addr-typed.config.json": "typed",
    }

    def test_every_shipped_config_declares_its_registered_arm(self):
        """No config on record silently acquires an address book: only the §4.2
        arm files may carry one, and each must carry exactly its own."""
        for path in sorted(Path(runner.DEFAULT_CONFIG).parent.glob("*.config.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            expected = self.ADDRESS_ARM_CONFIGS.get(
                path.name, prompts.ADDRESS_BOOK_NONE)
            self.assertEqual(
                raw.get("address_book", prompts.ADDRESS_BOOK_NONE),
                expected,
                path.name,
            )

    # -- §4.8 check 1: the arms differ only by the block --------------------

    def test_arms_differ_from_none_only_by_the_inserted_block(self):
        for book in (prompts.ADDRESS_BOOK_FULL, prompts.ADDRESS_BOOK_TYPED):
            for task in self.tasks:
                control = prompts.build_prompt(task, REGIME_HELD_OUT, self.resolver)
                armed = prompts.build_prompt(
                    task, REGIME_HELD_OUT, self.resolver, address_book=book)
                block = prompts.address_book_block(
                    self.resolver, book, type_surface=task.expected_type_surface)
                self.assertIn(block, armed, f"{book} {task.task_id}")
                # The block arrives as its own paragraph; removing it and the
                # separator it brought must give back the control arm's bytes.
                self.assertEqual(armed.replace(f"\n\n{block}", "", 1), control,
                                 f"{book} {task.task_id}")

    def test_the_block_sits_between_the_examples_and_the_ask(self):
        task = self.concat
        armed = prompts.build_prompt(
            task, REGIME_HELD_OUT, self.resolver,
            address_book=prompts.ADDRESS_BOOK_FULL, narrowing="REJECTED: nope")
        example = self.resolver.surface(self.resolver.digest_for("corpus/bool/not"))
        self.assertLess(armed.index(example), armed.index(prompts.ADDRESS_HEADER))
        # Before the narrowing, so a rejection still cannot change the prefix.
        self.assertLess(armed.index(prompts.ADDRESS_HEADER), armed.index("REJECTED"))
        self.assertLess(armed.index("REJECTED"), armed.index(task.spec))

    # -- the rows themselves -----------------------------------------------

    def test_full_is_every_ref_legal_object_and_no_declaration(self):
        rows = prompts.full_address_rows(self.resolver)
        counts = self.resolver.counts()
        self.assertEqual(len(rows), counts[KIND_DEFINITION] + counts[KIND_EXTERN])
        self.assertEqual(len(rows), 35)
        # A `(ref DATA_HASH)` is the illegal draw the plan measures the model
        # making; addressing a data or ability hash would teach it that mistake.
        # Only the *address* column is checked: a nominal hash inside a type
        # (`(data 0x…  (I64))`) is the type's own spelling, not an address, and
        # already reaches the prompt through every example.
        addressed = {row.split(" ", 1)[0] for row in rows}
        for found in (self.resolver.resolve(d) for d in self.resolver.digests()):
            if found.kind in (KIND_DATA, KIND_ABILITY):
                self.assertNotIn(f"0x{found.hex}", addressed, found.name)

    def test_full_is_the_same_block_for_every_task(self):
        """`addr-full` is task-independent by definition — no smuggled filter."""
        blocks = {
            prompts.address_book_block(
                self.resolver, prompts.ADDRESS_BOOK_FULL,
                type_surface=task.expected_type_surface)
            for task in self.tasks
        }
        self.assertEqual(len(blocks), 1)

    def test_a_row_is_an_address_a_name_and_a_type_and_no_definition_body(self):
        """Three columns, and the third is the object's type, exactly.

        Not "contains no term": a refinement type's predicate *is* a term
        (`corpus/math/abs : (fn I64 () (refine I64 (app …)))`), and that term is
        part of the type the checker uses. The invariant that matters is that
        the row carries nothing beyond the type — no `(def …)`, and no object's
        canonical definition surface.
        """
        row_re = re.compile(r"^0x[0-9a-f]{64} \S+ : \S.*$")
        surfaces = [
            found.surface for found in self.resolver.definitions() if found.surface]
        for found in prompts.ref_legal_objects(self.resolver):
            row = prompts.address_row(found)
            self.assertRegex(row, row_re)
            address, name, type_surface = row.split(" ", 2)
            self.assertEqual(address, f"0x{found.hex}")
            self.assertEqual(name, found.name)
            self.assertEqual(type_surface, ": " + type_to_surface(found.type_ir))
            self.assertNotIn("(def ", row)
            for surface in surfaces:
                self.assertNotIn(surface, row, found.name)

    def test_rows_keep_resolver_order_under_the_typed_filter(self):
        """Selection is all the filter decides — it cannot rank the route first."""
        full = list(prompts.full_address_rows(self.resolver))
        for task in self.tasks:
            typed = list(prompts.typed_address_rows(
                self.resolver, task.expected_type_surface))
            self.assertEqual(typed, [row for row in full if row in set(typed)], task.task_id)

    def test_typed_sizes_match_the_audits_recomputed_range(self):
        """One source of truth: the audit calls this filter, so 2-13 holds here."""
        sizes = {
            task.task_id: len(prompts.typed_address_rows(
                self.resolver, task.expected_type_surface))
            for task in self.tasks
        }
        self.assertEqual(min(sizes.values()), 2)
        self.assertEqual(max(sizes.values()), 13)
        self.assertEqual(sizes["heldout/sample/stampedBytes"], 2)
        for task_id, size in sizes.items():
            self.assertLess(size, len(prompts.full_address_rows(self.resolver)), task_id)

    # -- leak invariant (a): no `composes` relationship may surface ---------

    def test_the_filter_is_never_handed_anything_that_knows_the_route(self):
        """§4.8 check 2, by signature: a resolver and a type, and nothing else."""
        parameters = inspect.signature(prompts.typed_address_rows).parameters
        self.assertEqual(list(parameters), ["resolver", "type_surface"])
        for name in parameters:
            self.assertNotIn("task", name)
        # And it really does run on those two arguments alone.
        rows = prompts.typed_address_rows(
            ExperimentResolver(), self.concat.expected_type_surface)
        self.assertTrue(rows)

    def test_a_fabricated_route_does_not_move_one_byte_of_the_block(self):
        """The adversarial case: every name in the store claimed as the route."""
        every_name = tuple(
            found.name for found in prompts.ref_legal_objects(self.resolver))
        for task in self.tasks:
            honest = prompts.build_prompt(
                task, REGIME_HELD_OUT, self.resolver,
                address_book=prompts.ADDRESS_BOOK_TYPED)
            for fake in (every_name, (), ("corpus/list/reverse",), ("nonesuch/definition",)):
                lied_to = prompts.build_prompt(
                    dataclasses.replace(task, composes=fake), REGIME_HELD_OUT,
                    self.resolver, address_book=prompts.ADDRESS_BOOK_TYPED)
                self.assertEqual(honest, lied_to, f"{task.task_id} {fake}")

    def test_two_tasks_with_one_type_and_two_routes_are_indistinguishable(self):
        """A block that differed here would be a channel for the route."""
        surface = self.concat.expected_type_surface
        left = prompts.Task(
            task_id="probe/left", kind=KIND_HELD_OUT, spec="one",
            expected_type_surface=surface, composes=("corpus/list/append", "List.size"))
        right = prompts.Task(
            task_id="probe/right", kind=KIND_HELD_OUT, spec="one",
            expected_type_surface=surface, composes=("corpus/nat/select",))
        self.assertEqual(
            prompts.build_prompt(left, REGIME_HELD_OUT, self.resolver,
                                 address_book=prompts.ADDRESS_BOOK_TYPED),
            prompts.build_prompt(right, REGIME_HELD_OUT, self.resolver,
                                 address_book=prompts.ADDRESS_BOOK_TYPED),
        )

    def test_a_route_element_the_codomain_test_excludes_stays_excluded(self):
        """The sharpest form of the invariant, and it fires on real data.

        `concatLength`'s recorded route is `corpus/list/append` then
        `List.size`, and `append` returns a list, never the task's `I64` body
        goal — so §4.2's filter drops it. An implementation that consulted
        `composes` at all would keep it, and this assertion is how that shows
        up. (The same fact is a live *design* question for §4.8's own check 2,
        which asserts the opposite; see the plan note filed with this change.)
        """
        block = prompts.address_book_block(
            self.resolver, prompts.ADDRESS_BOOK_TYPED,
            type_surface=self.concat.expected_type_surface)
        self.assertIn("corpus/list/append", self.concat.composes)
        self.assertNotIn("corpus/list/append", block)
        self.assertNotIn(
            self.resolver.digest_for("corpus/list/append").hex(), block)
        self.assertIn("List.size", block)

    def test_no_arm_ever_states_a_relationship_between_two_objects(self):
        """A row names one object, and one address. Nothing pairs two of them.

        Names are compared column-exactly, not by substring: `corpus/maybe/map`
        is a prefix of `corpus/maybe/mapPoly`, and a substring match would read
        that coincidence as a stated relationship.
        """
        by_address = {
            f"0x{found.hex}": found
            for found in prompts.ref_legal_objects(self.resolver)
        }
        for book in (prompts.ADDRESS_BOOK_FULL, prompts.ADDRESS_BOOK_TYPED):
            for task in self.tasks:
                block = prompts.address_book_block(
                    self.resolver, book, type_surface=task.expected_type_surface)
                for line in block.splitlines()[1:]:
                    address, name, _ = line.split(" ", 2)
                    self.assertIn(address, by_address, line)
                    self.assertEqual(name, by_address[address].name, line)
                    # Nothing is appended to the row. A second address may
                    # appear inside the type column and only there — a
                    # refinement predicate is a term, so `corpus/math/abs`'s
                    # type legitimately spells `I64.lt`'s digest — but the row
                    # is still exactly this object's own three columns.
                    self.assertEqual(line, prompts.address_row(by_address[address]), line)
                    self.assertNotIn(task.task_id, line)
                    self.assertNotIn(task.spec, line)
        for word in ("compose", "route", "solve", "answer"):
            self.assertNotIn(word, prompts.ADDRESS_HEADER)

    # -- leak invariant (b): no gold term may surface -----------------------

    def test_no_verified_gold_term_appears_in_any_built_prompt(self):
        """§4.4/§4.8 check 4, over the five solutions the audit verifies.

        Deliverable 3 lands `heldout_gold.py`; until it does, the audit's
        `HAND_SOLVED` fixtures are the verified gold terms on record, and they
        are the right thing to test against precisely because they *do* pass
        `run_funnel` and `score_semantic`.
        """
        tasks = {task.task_id: task for task in self.tasks}
        for book in (prompts.ADDRESS_BOOK_NONE, prompts.ADDRESS_BOOK_FULL,
                     prompts.ADDRESS_BOOK_TYPED):
            for task_id, gold in HAND_SOLVED.items():
                prompt = prompts.build_prompt(
                    tasks[task_id], REGIME_HELD_OUT, self.resolver, address_book=book)
                self.assertNotIn(gold, prompt, f"{book} {task_id}")
                # Not just the whole `(def …)` — the term half alone is the
                # answer too, and is what a leak would most plausibly carry.
                term = gold[gold.index("(lam"):-1]
                self.assertNotIn(term, prompt, f"{book} {task_id} term")
                self.assertTrue(
                    score_semantic(tasks[task_id], run_funnel(gold, self.resolver), gold).success
                    or run_funnel(gold, self.resolver).outcome == ACCEPTED, task_id)

    def test_leave_one_out_withholds_a_corpus_answers_own_address(self):
        """The adversarial corpus case: `full` must not re-address the answer.

        Held-out tasks are not corpus entries, so this can never fire for the
        plan's arms — which is exactly why an implementation would forget it,
        and why the withheld definition would come back as a row.
        """
        task = next(t for t in prompts.corpus_tasks() if t.task_id == "corpus/list/reverse")
        rows = prompts.address_rows(
            self.resolver, prompts.ADDRESS_BOOK_FULL,
            exclude_identity=task.expected_identity)
        self.assertNotIn(task.expected_identity, "\n".join(rows))
        kept = prompts.address_rows(self.resolver, prompts.ADDRESS_BOOK_FULL)
        self.assertIn(task.expected_identity, "\n".join(kept))
        prompt = prompts.build_prompt(
            task, prompts.REGIME_FULL_CORPUS, self.resolver,
            address_book=prompts.ADDRESS_BOOK_FULL)
        self.assertNotIn(task.expected_identity, prompt)
        self.assertNotIn(task.expected_surface, prompt)

    def test_typed_refuses_a_task_that_declares_no_type(self):
        """Rather than deriving a goal from the gold surface, which is a leak."""
        task = next(t for t in prompts.corpus_tasks() if t.task_id == "corpus/list/reverse")
        self.assertEqual(task.expected_type_surface, "")
        with self.assertRaises(ValueError) as raised:
            prompts.build_prompt(
                task, prompts.REGIME_FULL_CORPUS, self.resolver,
                address_book=prompts.ADDRESS_BOOK_TYPED)
        self.assertIn("declared type", str(raised.exception))
        with self.assertRaises(ValueError):
            prompts.typed_address_rows(self.resolver, "")

    # -- §4.8 check 3, and the config surface ------------------------------

    def test_every_arm_fits_the_planned_context(self):
        for book, budget in ((prompts.ADDRESS_BOOK_NONE, 768),
                             (prompts.ADDRESS_BOOK_FULL, 768),
                             (prompts.ADDRESS_BOOK_TYPED, 768)):
            required = prompts.context_required(
                [REGIME_HELD_OUT], self.resolver, draw_tokens=budget, address_book=book)
            self.assertLessEqual(required, 32768, book)
        none_required = prompts.context_required(
            [REGIME_HELD_OUT], self.resolver, address_book=prompts.ADDRESS_BOOK_NONE)
        full_required = prompts.context_required(
            [REGIME_HELD_OUT], self.resolver, address_book=prompts.ADDRESS_BOOK_FULL)
        self.assertGreater(full_required, none_required)

    def test_a_run_records_its_arm_on_every_draw(self):
        """§4.5 partitions draws by arm, so the arm rides on the draw."""
        records, summary = runner.run(stub_config(address_book=prompts.ADDRESS_BOOK_FULL))
        self.assertTrue(records)
        self.assertTrue(all(r["address_book"] == "full" for r in records))
        self.assertEqual(summary["config"]["address_book"], "full")
        control, _ = runner.run(stub_config())
        self.assertTrue(all(r["address_book"] == "none" for r in control))
        self.assertGreater(
            max(r["tokens_prompt"] for r in records),
            max(r["tokens_prompt"] for r in control),
        )

    def test_an_unknown_address_book_is_refused_by_name(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(address_book="everything").validate()
        self.assertIn("everything", str(raised.exception))
        with self.assertRaises(ValueError):
            prompts.address_rows(self.resolver, "everything")

    def test_typed_is_refused_outside_the_held_out_regime(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(
                address_book=prompts.ADDRESS_BOOK_TYPED,
                regimes=["full_corpus", "held_out"],
            ).validate()
        self.assertIn("held_out", str(raised.exception))
        runner.Config(
            address_book=prompts.ADDRESS_BOOK_TYPED, regimes=["held_out"]).validate()
        runner.Config(
            address_book=prompts.ADDRESS_BOOK_FULL, regimes=list(REGIMES)).validate()


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
        # The summary must carry the live contract versions; the version
        # values themselves are pinned in test_contracts, not here.
        import contracts

        self.assertEqual(
            self.summary["contract_versions"]["typecheck"],
            contracts.version("typecheck"))

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


class CrashSafetyTest(unittest.TestCase):
    """The failure this hardening answers: hours of CPU decode, one draw over
    the backend timeout, `BackendUnavailable`, and the old runner wrote
    nothing at all. `runner.run`'s `output_dir` path (only taken when a
    caller asks for it — the in-memory contract every other test in this file
    uses is unchanged) persists every draw as it lands, survives a dead
    backend with a readable partial summary/report, and resumes instead of
    redoing completed cells.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def test_records_are_persisted_as_the_run_goes_not_only_at_the_end(self):
        config = crash_safety_config()
        with tempfile.TemporaryDirectory() as directory:
            records, _ = runner.run(config, resolver=self.resolver, output_dir=directory)
            on_disk = [
                json.loads(line)
                for line in (Path(directory) / "records.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(on_disk), len(records))
            self.assertEqual({r["draw_seed"] for r in on_disk}, {r["draw_seed"] for r in records})
            self.assertTrue(all("cell_done" in r and "retried" in r for r in on_disk))

    def test_a_dead_backend_leaves_completed_records_and_a_partial_summary_and_report(self):
        config = crash_safety_config()
        backend = _FlakyBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS, fail_at=3, fail_forever=True)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(BackendUnavailable) as raised:
                runner.run(config, resolver=self.resolver, backend=backend, output_dir=directory)
            self.assertIn("partial run: 1 of 2 cells", str(raised.exception))

            # Cell 1 (seed 1) ran to completion — two draws — before cell 2
            # died on the first attempt of its first draw, so exactly cell
            # 1's records made it to disk, nothing was silently lost, and
            # nothing from the dead cell is half-written.
            records_path = Path(directory) / "records.jsonl"
            on_disk = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(on_disk), 2)
            self.assertEqual({r["seed"] for r in on_disk}, {1})
            self.assertTrue(on_disk[-1]["cell_done"])

            summary = json.loads((Path(directory) / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["records"], 2)
            report = (Path(directory) / "report.md").read_text(encoding="utf-8")
            self.assertIn("Phase A results", report)

    def test_resume_skips_the_completed_cell_and_finishes_the_rest(self):
        config = crash_safety_config()
        dead_backend = _FlakyBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS, fail_at=3, fail_forever=True)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(BackendUnavailable):
                runner.run(config, resolver=self.resolver, backend=dead_backend, output_dir=directory)

            logged = []
            fresh_backend = StubBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS)
            records, summary = runner.run(
                config, resolver=self.resolver, backend=fresh_backend,
                output_dir=directory, log=logged.append)

            self.assertTrue(any("resuming: skipping 1 completed cells" in m for m in logged), logged)
            # Only cell 2's two draws needed redoing; cell 1 was skipped, not
            # regenerated, so the fresh backend was called exactly twice.
            self.assertEqual(fresh_backend.draws, 2)
            self.assertEqual(len(records), 4)
            self.assertEqual({r["seed"] for r in records}, {1, 2})
            draw_keys = [(r["task"], r["condition"], r["regime"], r["seed"], r["draw"]) for r in records]
            self.assertEqual(len(draw_keys), len(set(draw_keys)), "resume must not duplicate a draw")
            self.assertEqual(summary["records"], 4)
            on_disk = [
                json.loads(line)
                for line in (Path(directory) / "records.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(on_disk), 4)

    def test_fresh_refuses_to_clobber_by_default_and_obeys_with_the_flag(self):
        config = crash_safety_config()
        with tempfile.TemporaryDirectory() as directory:
            first_backend = StubBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS)
            runner.run(config, resolver=self.resolver, backend=first_backend, output_dir=directory)

            # Default: an existing, fully-complete records.jsonl is resumed
            # rather than clobbered, so a backend with nothing left to do is
            # never called at all.
            resumed_backend = StubBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS)
            runner.run(config, resolver=self.resolver, backend=resumed_backend, output_dir=directory)
            self.assertEqual(resumed_backend.draws, 0)

            # `fresh=True` (the CLI's `--fresh`) obeys: it discards the old
            # file and every cell is redrawn from scratch.
            fresh_backend = StubBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS)
            records, _ = runner.run(
                config, resolver=self.resolver, backend=fresh_backend,
                output_dir=directory, fresh=True)
            self.assertEqual(fresh_backend.draws, 4)
            self.assertEqual(len(records), 4)

    def test_a_backend_hiccup_is_retried_once_and_recorded(self):
        config = crash_safety_config(seeds=[1], max_draws_per_task=1)
        backend = _FlakyBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS, fail_at=1, fail_forever=False)
        with tempfile.TemporaryDirectory() as directory:
            records, _ = runner.run(config, resolver=self.resolver, backend=backend, output_dir=directory)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["retried"])
            self.assertTrue(records[0]["cell_done"])
            # The failed first attempt plus the successful retry.
            self.assertEqual(backend.calls, 2)

    def test_a_second_consecutive_failure_is_not_swallowed(self):
        config = crash_safety_config(seeds=[1], max_draws_per_task=1)
        backend = _FlakyBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS, fail_at=1, fail_forever=True)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(BackendUnavailable):
                runner.run(config, resolver=self.resolver, backend=backend, output_dir=directory)
            # Nothing landed on disk: the very first draw never succeeded.
            on_disk = (Path(directory) / "records.jsonl").read_text(encoding="utf-8")
            self.assertEqual(on_disk, "")


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


class _AllotmentRecordingBackend(StubBackend):
    """A `StubBackend` that records each draw's allotment and spends all of it.

    Two properties matter for the budget guard. It captures the `max_tokens`
    the runner hands to *every* backend call, which is the quantity §4.3
    constrains; and it reports `completion_tokens == max_tokens`, so the
    cumulative budget actually binds instead of the stub's four-chars-per-token
    trickle leaving the budget arm of the loop condition untested.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.allotments: list[int] = []

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        self.allotments.append(max_tokens)
        generation = super().generate(
            prompt, grammar=grammar, max_tokens=max_tokens, seed=seed, temperature=temperature)
        return dataclasses.replace(
            generation, completion_tokens=max_tokens, stop_reason="length")


class BudgetSemanticsTest(unittest.TestCase):
    """No draw is ever handed a leftover fragment — plan §4.3, fixing §1.3.

    The defect this guards against: the loop used to allot
    `min(max_tokens_per_draw, budget - used)` and to keep drawing while any
    budget at all remained, so a cell's last draw got whatever scrap was left
    and truncated by construction — 100 % of held-out cells on record were
    terminated by such a draw. The corrected rule is that a draw happens only
    when a *whole* cap fits in what is left, and then gets exactly that cap.

    Every case below drives the real `runner.run` with a stub backend on CPU;
    the arithmetic is never re-derived here, it is read back off the backend.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def _allotments(self, *, budget, cap, max_draws):
        """Run one real cell and return (allotments handed out, records)."""
        config = stub_config(
            token_budget_per_task=budget,
            max_tokens_per_draw=cap,
            max_draws_per_task=max_draws,
            conditions=[runner.CONDITION_GBNF],
            regimes=["few_shot"],
            tasks=["corpus/bool/not"],
        )
        backend = _AllotmentRecordingBackend(STUB_OUTPUTS, STUB_GRAMMAR_OUTPUTS)
        records, _ = runner.run(config, resolver=self.resolver, backend=backend)
        return backend.allotments, records

    def test_the_historical_failing_shape_grants_no_fragment_draw(self):
        """budget=1000, cap=768: one full draw, and the 232-token scrap is dropped.

        This is the shape the defect was invisible in — a budget that is not a
        multiple of the cap. The old loop drew twice, the second draw allotted
        232 tokens and truncated; the cell then "ended" on that truncation.
        """
        allotments, records = self._allotments(budget=1000, cap=768, max_draws=8)
        self.assertEqual(allotments, [768])
        self.assertEqual(len(records), 1)
        self.assertTrue(records[-1]["cell_done"])

    def test_the_4_3_arm_values_give_exactly_eight_full_cap_draws(self):
        """§4.3: budget 6144, cap 768, max_draws 8 → 8 × 768, the n=320/arm basis.

        §4.7's power calculation is 8 tasks × 5 seeds × 8 draws = 320 draws per
        arm. If a cell yields anything but eight draws, that n is wrong.
        """
        allotments, records = self._allotments(budget=6144, cap=768, max_draws=8)
        self.assertEqual(allotments, [768] * 8)
        self.assertEqual(len(records), 8)
        self.assertEqual(sum(allotments), 6144)
        self.assertTrue(records[-1]["cell_done"])

    def test_every_granted_draw_across_a_spread_of_configs_gets_the_full_cap(self):
        """Whatever the combination, an allotment is the cap or the draw is not made."""
        cases = [
            (6144, 768, 8),    # the §4.3 arms: draw cap and budget bind together
            (1000, 768, 8),    # budget not a multiple of the cap
            (768, 768, 8),     # exactly one draw fits
            (767, 768, 8),     # not even one draw fits
            (400, 60, 8),      # the draw cap binds first
            (400, 60, 3),      # a lower draw cap binds first
            (512, 512, 32),    # every shipped pre-§4.3 config's shape
            (1536, 500, 8),    # 3 full draws, 36 tokens stranded
            (100, 7, 32),      # many small draws, 2 tokens stranded
        ]
        for budget, cap, max_draws in cases:
            with self.subTest(budget=budget, cap=cap, max_draws=max_draws):
                allotments, records = self._allotments(
                    budget=budget, cap=cap, max_draws=max_draws)
                self.assertEqual(len(records), len(allotments))
                for index, allotment in enumerate(allotments):
                    self.assertEqual(allotment, cap, f"draw {index} was handed a fragment")
                self.assertLessEqual(len(allotments), max_draws)
                self.assertLessEqual(sum(allotments), budget)
                # And the loop stopped for a reason: either the draw cap, or
                # too little budget left for one more whole draw.
                if len(allotments) < max_draws:
                    self.assertLess(budget - sum(allotments), cap)

    def test_a_budget_smaller_than_one_draw_yields_no_draw_at_all(self):
        """No partial-cap draw ever happens — for any config, including this one."""
        allotments, records = self._allotments(budget=767, cap=768, max_draws=8)
        self.assertEqual(allotments, [])
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
