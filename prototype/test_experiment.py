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
from experiment.decomposition_probe import eta_skeleton
from experiment.evaluate import ACCEPTED, LAYERS, OUTCOMES, extract_definition, run_funnel, score_semantic
from experiment.heldout_gold import GOLD_TERMS
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
#: A bare hole at `SUM_TASK`'s declared type — accepted and type-exact by
#: construction, and the [decomp-floor-fix] regression fixture: `score_semantic`
#: must refuse it (§5.4), never a stand-in for a genuine held-out success.
HELD_OUT_HOLE = f"(def {SUM_TASK.expected_type_surface} (hole {SUM_TASK.expected_type_surface} ()))"
#: A genuine, hole-free `SUM_TASK` answer — the stub's one held-out success
#: case, so `test_semantic_success_is_scored_by_task_kind` exercises the real
#: floor rather than the eta-skeleton defect it now refuses.
HELD_OUT_GOOD = GOLD_TERMS[SUM_TASK.task_id]

#: Without a grammar the model may emit anything, syntax errors included.
STUB_OUTPUTS = [BOOL_NOT, BROKEN_SYNTAX, BROKEN_SCOPE, BROKEN_REFERENCES, BROKEN_TYPE, HELD_OUT_GOOD]
#: Under `loom.gbnf` a syntax failure is impossible by construction, so the
#: grammar script is the same list with the syntax break removed. That is the
#: whole of what condition 2 buys, modelled exactly.
STUB_GRAMMAR_OUTPUTS = [BOOL_NOT, BROKEN_SCOPE, BROKEN_REFERENCES, BROKEN_TYPE, HELD_OUT_GOOD]


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
        # docs/plans/2026-08-25-hole-decomposition.md §4.2/4.3: byte-copies of
        # addr-full.config.json for the three decomposition-experiment arms.
        "decomp-whole.config.json": "full",
        "decomp-redraft.config.json": "full",
        "decomp-holes.config.json": "full",
        # docs/plans/2026-08-26-hole-elicitation.md §4.2 pilot / §4.3 Stage 1:
        # byte-copies of the decomposition-experiment arms above, address_book
        # unchanged at "full".
        "pilot_b0.config.json": "full",
        "pilot_b1.config.json": "full",
        "pilot_b2.config.json": "full",
        "pilot_b3.config.json": "full",
        "decomp2_whole.config.json": "full",
        "decomp2_redraft.config.json": "full",
        "decomp2_holes.config.json": "full",
        # docs/plans/2026-08-27-model-scale-arm.md §2: byte-copies of the two
        # pilot blocks the 14B arm carries, address_book unchanged at "full" —
        # the arm holds every field but the model fixed, so a different book
        # here would be a second changed variable.
        "scale14_b0.config.json": "full",
        "scale14_b2.config.json": "full",
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
        good = score_semantic(SUM_TASK, run_funnel(HELD_OUT_GOOD, self.resolver), HELD_OUT_GOOD)
        self.assertTrue(good.success)
        self.assertEqual(good.rule, "checked+type-exact")
        self.assertTrue(good.rubric_pending, "R3's hand-scored half must stay visible")
        wrong_type = score_semantic(SUM_TASK, run_funnel(BOOL_NOT, self.resolver), BOOL_NOT)
        self.assertFalse(wrong_type.success)
        self.assertEqual(wrong_type.detail, "type mismatch")
        unchecked = score_semantic(SUM_TASK, run_funnel(BROKEN_TYPE, self.resolver), BROKEN_TYPE)
        self.assertFalse(unchecked.success)
        self.assertFalse(unchecked.rubric_pending)

    def test_held_out_floor_refuses_a_bare_hole_at_the_task_type(self):
        # HELD_OUT_HOLE is accepted and type-exact by construction — the
        # narrowest instance of the eta-skeleton defect below — so this pins
        # the refusal on the one fixture that isolates it from every other
        # held-out task's declared type.
        holed = score_semantic(SUM_TASK, run_funnel(HELD_OUT_HOLE, self.resolver), HELD_OUT_HOLE)
        self.assertFalse(holed.success)
        self.assertEqual(holed.rule, "checked+type-exact")
        self.assertIn("hole", holed.detail)
        self.assertFalse(holed.rubric_pending)

    def test_eta_skeleton_no_longer_meets_the_floor_for_any_held_out_task(self):
        """`[decomp-floor-fix]` regression proof, docs/plans/
        2026-08-25-hole-decomposition.md deliverable 2 / SPEC §5.4.

        The eta-skeleton for a task's declared type — all lambdas, one bare
        `(hole GOAL ())` — passes the whole funnel and is type-exact by
        construction, so before this fix `score_semantic` scored it a
        mechanical-floor success for all 8 held-out tasks (confirmed by
        running `python3 -m experiment.decomposition_probe --section skeleton`
        against the pre-fix `evaluate.py`: every task printed
        `floor_today=True`). A hole-bearing definition lives in `draft/` and
        can never be the target of a binding (§5.4), so every one of the
        eight must now be refused.
        """
        self.assertEqual(len(prompts.HELD_OUT_TASKS), 8, "the plan's eight held-out tasks")
        for task in prompts.HELD_OUT_TASKS:
            skeleton = eta_skeleton(task.expected_type_surface)
            funnel = run_funnel(skeleton, self.resolver)
            # The funnel and the type still pass — isolating the hole clause
            # as the one thing standing between this skeleton and a false
            # "success".
            self.assertEqual(funnel.outcome, ACCEPTED, task.task_id)
            self.assertEqual(funnel.type_surface, task.expected_type_surface, task.task_id)
            result = score_semantic(task, funnel, skeleton)
            self.assertFalse(result.success, task.task_id)
            self.assertEqual(result.rule, "checked+type-exact", task.task_id)
            self.assertIn("hole", result.detail, task.task_id)
            self.assertFalse(result.rubric_pending, task.task_id)


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


#: `heldout/list/headOrElse`'s gold term is the one on the battery with real
#: `match` structure, so the two hole positions this module needs — one under a
#: zero-binder arm, one under a one-binder arm — are both available in a term
#: the funnel already accepts, rather than in a fabricated fixture.
_MAYBE_HASH = "0x" + corpus_registry.HASHES["Maybe"].hex()
_MAYBE_I64 = f"(data {_MAYBE_HASH} (I64))"
#: `Nothing`, under a `(0 0 …)` arm — an arm that binds nothing, so the hole's
#: context is exactly the top-level lambdas and the hole is fillable.
_NOTHING = f"(con {_MAYBE_HASH} 0 ())"
#: The inner `match`, under a `(1 1 …)` arm — one binder whose type is read off
#: the scrutinee's synthesized type, which v1 does not have.
_INNER_MATCH = f"(match (var 0) ((0 2 (con {_MAYBE_HASH} 1 ((var 1))))))"


class HoleObligationTest(unittest.TestCase):
    """§2.2 step 3: what a draft's holes are, and which of them v1 can fill."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.tasks = {task.task_id: task for task in prompts.HELD_OUT_TASKS}
        cls.head = cls.tasks["heldout/list/headOrElse"]
        cls.head_gold = GOLD_TERMS[cls.head.task_id]

    def test_an_eta_skeleton_has_one_hole_under_every_declared_lambda(self):
        for task in prompts.HELD_OUT_TASKS:
            skeleton = eta_skeleton(task.expected_type_surface)
            obligations = prompts.hole_obligations(skeleton, self.resolver)
            domains, _rows, goal = prompts.peel_arrows(task.expected_type_surface)
            self.assertEqual(len(obligations), 1, task.task_id)
            hole = obligations[0]
            self.assertTrue(hole.fillable, task.task_id)
            self.assertEqual(hole.reason, "")
            self.assertEqual(hole.goal_surface, goal, task.task_id)
            self.assertEqual(list(hole.binders), domains, task.task_id)
            self.assertEqual(hole.surface, f"(hole {goal} ())")

    def test_a_gold_term_has_no_obligations_at_all(self):
        """The protocol's fixed point: a hole-free definition is finished."""
        for task_id, gold in GOLD_TERMS.items():
            self.assertEqual(prompts.hole_obligations(gold, self.resolver), (), task_id)

    def test_holes_come_back_in_pre_order_with_paths_that_locate_them(self):
        draft = self.head_gold.replace(_NOTHING, f"(hole {_MAYBE_I64} ())")
        draft = draft.replace(_INNER_MATCH, f"(hole {_MAYBE_I64} ())")
        obligations = prompts.hole_obligations(draft, self.resolver)
        self.assertEqual(len(obligations), 2)
        self.assertEqual([o.goal_surface for o in obligations], [_MAYBE_I64] * 2)
        # Pre-order: the `(0 0 …)` arm before the `(1 1 …)` arm, which is the
        # order their holes appear in the surface.
        self.assertLess(obligations[0].path, obligations[1].path)
        for hole in obligations:
            self.assertEqual(prompts.declared_type_of(draft),
                             self.head.expected_type_surface)

    def test_a_zero_binder_match_arm_leaves_the_context_alone(self):
        """`match` is not disqualifying — *an unknown binder* is.

        An arm that binds nothing adds nothing to Γ, so a hole in it stands
        under exactly the top-level lambdas and is fillable. Reading §2.2 step 3
        as "any hole under a `match` node" would refuse this one, and refuse it
        for a reason that is not true of it.
        """
        draft = self.head_gold.replace(_NOTHING, f"(hole {_MAYBE_I64} ())")
        hole, = prompts.hole_obligations(draft, self.resolver)
        self.assertTrue(hole.fillable)
        domains, _rows, _goal = prompts.peel_arrows(self.head.expected_type_surface)
        self.assertEqual(list(hole.binders), domains)

    def test_a_hole_under_a_match_binder_is_unfillable_and_says_why(self):
        draft = self.head_gold.replace(_INNER_MATCH, f"(hole {_MAYBE_I64} ())")
        hole, = prompts.hole_obligations(draft, self.resolver)
        self.assertFalse(hole.fillable)
        self.assertIn("match", hole.reason)
        self.assertIn("scrutinee", hole.reason)
        # A partial context would read as a complete one, so there is none.
        self.assertEqual(hole.binders, ())
        with self.assertRaises(ValueError):
            prompts.closed_subtask_type(prompts.declared_type_of(draft), hole)

    def test_a_hole_under_a_handle_binder_is_unfillable_and_says_why(self):
        stamped = self.tasks["heldout/sample/stampedBytes"]
        clock = "0x" + prompts._CLOCK.hex()
        draft = (
            f"(def {stamped.expected_type_surface} "
            f"(handle {clock} (lit i64 0) ((0 (hole I64 ()))) (hole I64 ())))")
        first, second = prompts.hole_obligations(draft, self.resolver)
        for hole in (first, second):
            self.assertFalse(hole.fillable)
            self.assertIn("handle", hole.reason)
            self.assertEqual(hole.binders, ())

    def test_lam_let_and_fix_all_contribute_their_annotations(self):
        """The three binders that carry their own type, in one draft.

        `let` is not named in §2.2 step 3, which lists `lam` and `fix`; the rule
        it states is *"fillable iff its binder context is derivable without
        synthesis"*, and a `let`'s binding type is written into the term exactly
        as a `lam`'s is. It is admitted on the stated rule, not on the list.
        """
        recursive = "(fn I64 () I64)"
        draft = (
            "(def (fn I64 () I64) (lam I64 (let Bool (lit bool true) "
            f"(if (var 0) (hole I64 ()) (fix {recursive} 0 (var 1) (hole I64 ()))))))")
        shallow, deep = prompts.hole_obligations(draft, self.resolver)
        self.assertEqual(list(shallow.binders), ["I64", "Bool"])
        self.assertEqual(list(deep.binders), ["I64", "Bool", recursive])
        self.assertTrue(shallow.fillable and deep.fillable)

    def test_the_walker_is_never_handed_anything_that_knows_the_route(self):
        """§4.8 check 2, by signature: a source and a resolver, and nothing else."""
        parameters = inspect.signature(prompts.hole_obligations).parameters
        self.assertEqual(list(parameters), ["source", "resolver"])
        for name in parameters:
            self.assertNotIn("task", name)
        for field in dataclasses.fields(prompts.HoleObligation):
            self.assertNotIn("task", field.name)


class ClosedSubtaskTypeTest(unittest.TestCase):
    """§2.2 step 4: a pure function of two type surfaces, and no term."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.tasks = {task.task_id: task for task in prompts.HELD_OUT_TASKS}

    def test_an_eta_skeletons_hole_closes_back_to_the_declared_type(self):
        """The identity that makes the closure believable at the degenerate case.

        The eta-skeleton's single hole stands under every declared lambda, so
        folding its context back must give the declared type again — for all
        eight, including the two whose types are 384 and 392 characters of
        refinement predicate and capability rows.
        """
        for task in prompts.HELD_OUT_TASKS:
            surface = task.expected_type_surface
            hole, = prompts.hole_obligations(eta_skeleton(surface), self.resolver)
            self.assertEqual(prompts.closed_subtask_type(surface, hole), surface,
                             task.task_id)

    def test_the_effect_row_comes_off_the_declared_type_not_the_term(self):
        """§2.2 step 4's parallel peel, on the one arm that has a row to peel.

        `stampedBytes` carries a closed two-ability row on its innermost arrow
        only. The term records no row anywhere, so a closure that read the term
        could not produce this at all.
        """
        surface = self.tasks["heldout/sample/stampedBytes"].expected_type_surface
        _domains, rows, _goal = prompts.peel_arrows(surface)
        self.assertEqual([len(row) for row in rows], [0, 0, 2])
        hole, = prompts.hole_obligations(eta_skeleton(surface), self.resolver)
        closed = prompts.closed_subtask_type(surface, hole)
        row = "(" + " ".join("0x" + digest.hex() for digest in rows[2]) + ")"
        self.assertIn(row, closed)
        self.assertEqual(closed.count(row), 1)

    def test_a_binder_deeper_than_the_declared_type_closes_at_the_empty_row(self):
        """The case §2.2 step 4 does not spell out, pinned so it cannot drift.

        A `let` or an inner `lam` binder sits below the last declared arrow, and
        the term IR records no effect row for it — only the declared type does,
        and it has run out. It closes at `()`: the restrictive choice, which can
        make a sub-task unsolvable but can never license a fill that performs an
        effect the position forbids. §2.2's re-check is the authority either way.
        """
        draft = ("(def (fn I64 () I64) (lam I64 (let Bool (lit bool true) "
                 "(hole I64 ()))))")
        hole, = prompts.hole_obligations(draft, self.resolver)
        self.assertEqual(
            prompts.closed_subtask_type(prompts.declared_type_of(draft), hole),
            "(fn I64 () (fn Bool () I64))")

    def test_the_closure_is_never_handed_anything_that_knows_the_route(self):
        """§4.8 check 2 by signature: two type surfaces, and no `Task`.

        The plan spells the second argument `context`; it is spelled
        `obligation` here because `HoleObligation` *is* the hole's context — its
        binder types and its goal, and nothing else — and passing the obligation
        keeps the goal and the binders from ever being paired up wrongly by a
        caller.
        """
        parameters = inspect.signature(prompts.closed_subtask_type).parameters
        self.assertEqual(list(parameters), ["declared_type_surface", "obligation"])
        for name in parameters:
            self.assertNotIn("task", name)
        # And it really does run on type surfaces alone: an obligation rebuilt
        # from nothing but two type strings closes exactly as the walked one did.
        surface = self.tasks["heldout/list/sum"].expected_type_surface
        walked, = prompts.hole_obligations(eta_skeleton(surface), self.resolver)
        rebuilt = prompts.HoleObligation(
            path=(), goal_surface=walked.goal_surface, binders=walked.binders)
        self.assertEqual(prompts.closed_subtask_type(surface, rebuilt),
                         prompts.closed_subtask_type(surface, walked))


class SpliceTest(unittest.TestCase):
    """§2.2 step 5: the fill goes back where the hole was, indices intact."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.sum = next(t for t in prompts.HELD_OUT_TASKS if t.task_id == "heldout/list/sum")

    def test_every_gold_answer_round_trips_through_the_eta_skeleton(self):
        """§4.4's expressibility check at the degenerate cut, for all eight.

        The eta-skeleton's closed sub-task type *is* the task's declared type,
        so the gold definition is itself a legal fill for its own skeleton —
        which makes this the sharpest available statement of the round trip: the
        splice must give back the gold bytes exactly, and the result must still
        meet the floor.
        """
        for task in prompts.HELD_OUT_TASKS:
            gold = GOLD_TERMS[task.task_id]
            skeleton = eta_skeleton(task.expected_type_surface)
            hole, = prompts.hole_obligations(skeleton, self.resolver)
            assembled = prompts.splice_fill(skeleton, hole, gold)
            self.assertEqual(assembled, gold, task.task_id)
            funnel = run_funnel(assembled, self.resolver)
            self.assertEqual(funnel.outcome, ACCEPTED, task.task_id)
            self.assertTrue(score_semantic(task, funnel, assembled).success, task.task_id)

    def test_a_nested_fill_lands_with_its_de_bruijn_indices_unchanged(self):
        """The load-bearing case: the fill's body reads variables at the hole.

        `reverseThen`'s inner `(app (ref …) (var 1))` refers to the *outer*
        lambda. Under the fill's own two peeled lambdas it is still `(var 1)`,
        because those lambdas bind the same context in the same order — and the
        assembly is byte-identical to gold, which it could not be if the index
        had had to move.
        """
        task = next(t for t in prompts.HELD_OUT_TASKS
                    if t.task_id == "heldout/list/reverseThen")
        gold = GOLD_TERMS[task.task_id]
        inner = re.search(r"\(app \(ref 0x[0-9a-f]{64}\) \(var 1\)\)", gold).group(0)
        domains, _rows, _goal = prompts.peel_arrows(task.expected_type_surface)
        draft = gold.replace(inner, f"(hole {domains[0]} ())")
        hole, = prompts.hole_obligations(draft, self.resolver)
        self.assertTrue(hole.fillable)
        closed = prompts.closed_subtask_type(prompts.declared_type_of(draft), hole)
        fill = f"(def {closed} {prompts.fill_term_skeleton(hole).replace(hole.surface, inner)})"
        self.assertEqual(run_funnel(fill, self.resolver).outcome, ACCEPTED)
        self.assertIn("(var 1)", fill)
        assembled = prompts.splice_fill(draft, hole, fill)
        self.assertEqual(assembled, gold)
        self.assertTrue(
            score_semantic(task, run_funnel(assembled, self.resolver), assembled).success)

    def test_a_fill_that_does_not_bind_the_context_is_refused_not_spliced(self):
        """Every escape from the contract is a term whose indices mean something
        else, so each one is a rollback, not a splice."""
        surface = self.sum.expected_type_surface
        skeleton = eta_skeleton(surface)
        hole, = prompts.hole_obligations(skeleton, self.resolver)
        with self.assertRaises(prompts.SpliceError):  # too few lambdas
            prompts.splice_fill(skeleton, hole, "(def I64 (lit i64 0))")
        with self.assertRaises(prompts.SpliceError):  # right count, wrong type
            prompts.splice_fill(skeleton, hole, "(def (fn Bool () I64) (lam Bool (lit i64 0)))")
        with self.assertRaises(prompts.SpliceError):  # no hole at that path
            prompts.splice_fill(GOLD_TERMS[self.sum.task_id], hole,
                                GOLD_TERMS[self.sum.task_id])

    def test_an_unfillable_hole_is_refused_by_both_halves_of_the_machinery(self):
        head = next(t for t in prompts.HELD_OUT_TASKS
                    if t.task_id == "heldout/list/headOrElse")
        draft = GOLD_TERMS[head.task_id].replace(_INNER_MATCH, f"(hole {_MAYBE_I64} ())")
        hole, = prompts.hole_obligations(draft, self.resolver)
        with self.assertRaises(prompts.SpliceError):
            prompts.splice_fill(draft, hole, GOLD_TERMS[head.task_id])

    def test_a_spliced_draft_keeps_its_declared_type_and_loses_a_hole(self):
        """§2.2 step 6's monotonicity, stated as an assertion: holes only go away."""
        task = next(t for t in prompts.HELD_OUT_TASKS
                    if t.task_id == "heldout/maybe/mapOrElse")
        skeleton = eta_skeleton(task.expected_type_surface)
        hole, = prompts.hole_obligations(skeleton, self.resolver)
        assembled = prompts.splice_fill(skeleton, hole, GOLD_TERMS[task.task_id])
        self.assertEqual(prompts.declared_type_of(assembled),
                         prompts.declared_type_of(skeleton))
        self.assertLess(len(prompts.hole_obligations(assembled, self.resolver)),
                        len(prompts.hole_obligations(skeleton, self.resolver)))

    def test_a_bare_hole_body_is_recognised_from_the_draft_alone(self):
        """§3's last sentence is enforced, not asked for."""
        for task in prompts.HELD_OUT_TASKS:
            self.assertTrue(prompts.bare_hole_body(eta_skeleton(task.expected_type_surface)),
                            task.task_id)
            self.assertFalse(prompts.bare_hole_body(GOLD_TERMS[task.task_id]), task.task_id)
        head = GOLD_TERMS["heldout/list/headOrElse"]
        self.assertFalse(
            prompts.bare_hole_body(head.replace(_NOTHING, f"(hole {_MAYBE_I64} ())")))
        # No declared type is consulted: a draft that wrote fewer lambdas than
        # its type calls for is judged by what it actually wrote.
        self.assertTrue(prompts.bare_hole_body("(def (fn I64 () I64) (hole (fn I64 () I64) ()))"))


class GenerationProtocolPromptTest(unittest.TestCase):
    """§3, §4.2 and §4.8 check 1/2 for `generation_protocol`."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.tasks = prompts.HELD_OUT_TASKS
        cls.sum = next(t for t in cls.tasks if t.task_id == "heldout/list/sum")

    # -- the control arm, pinned the way `address_book: none` is -----------

    def test_whole_is_the_default_and_changes_not_one_byte(self):
        """`whole` is today's prompt, or it is not the honest baseline (§4.2)."""
        self.assertEqual(
            inspect.signature(prompts.build_prompt).parameters["generation_protocol"].default,
            prompts.PROTOCOL_WHOLE,
        )
        for regime in REGIMES:
            for task in prompts.tasks_for_regime(regime):
                plain = prompts.build_prompt(task, regime, self.resolver)
                for protocol in (prompts.PROTOCOL_WHOLE, prompts.PROTOCOL_REDRAFT):
                    self.assertEqual(
                        plain,
                        prompts.build_prompt(task, regime, self.resolver,
                                             generation_protocol=protocol),
                        f"{protocol} {task.task_id}")
                self.assertNotIn(prompts.HOLE_PROTOCOL_BLOCK, plain, task.task_id)
                self.assertNotIn("hole", plain.split(prompts.PREAMBLE)[-1], task.task_id)

    def test_redraft_is_byte_identical_to_whole_under_every_address_book(self):
        """§4.8 check 1: `redraft` differs from `whole` in the loop, not the prompt."""
        for book in prompts.ADDRESS_BOOKS:
            for task in self.tasks:
                self.assertEqual(
                    prompts.build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                         address_book=book),
                    prompts.build_prompt(task, REGIME_HELD_OUT, self.resolver,
                                         address_book=book,
                                         generation_protocol=prompts.PROTOCOL_REDRAFT),
                    f"{book} {task.task_id}")

    def test_holes_differs_from_whole_only_by_the_protocol_block(self):
        """§4.8 check 1: strip the §3 block and the control arm's bytes come back."""
        for book in prompts.ADDRESS_BOOKS:
            for task in self.tasks:
                control = prompts.build_prompt(
                    task, REGIME_HELD_OUT, self.resolver, address_book=book)
                armed = prompts.build_prompt(
                    task, REGIME_HELD_OUT, self.resolver, address_book=book,
                    generation_protocol=prompts.PROTOCOL_HOLES)
                self.assertIn(prompts.HOLE_PROTOCOL_BLOCK, armed)
                self.assertEqual(
                    armed.replace(f"\n\n{prompts.HOLE_PROTOCOL_BLOCK}", "", 1), control,
                    f"{book} {task.task_id}")

    def test_the_block_sits_after_the_address_book_and_before_the_narrowing(self):
        armed = prompts.build_prompt(
            self.sum, REGIME_HELD_OUT, self.resolver,
            address_book=prompts.ADDRESS_BOOK_FULL,
            generation_protocol=prompts.PROTOCOL_HOLES,
            narrowing="REJECTED: nope")
        self.assertLess(armed.index(prompts.ADDRESS_HEADER),
                        armed.index(prompts.HOLE_PROTOCOL_BLOCK))
        # Before the narrowing, so a rejection still cannot change the prefix.
        self.assertLess(armed.index(prompts.HOLE_PROTOCOL_BLOCK), armed.index("REJECTED"))
        self.assertLess(armed.index("REJECTED"), armed.index(self.sum.spec))

    def test_the_block_is_the_plans_own_text_and_licenses_nothing_else(self):
        self.assertIn("(hole GOALTYPE ())", prompts.HOLE_PROTOCOL_BLOCK)
        self.assertIn("Do not make the whole body a hole.", prompts.HOLE_PROTOCOL_BLOCK)
        for word in ("compose", "route", "ref 0x", "append", "reverse"):
            self.assertNotIn(word, prompts.HOLE_PROTOCOL_BLOCK)

    def test_an_unknown_generation_protocol_is_refused_by_name(self):
        with self.assertRaises(ValueError) as raised:
            prompts.build_prompt(self.sum, REGIME_HELD_OUT, self.resolver,
                                 generation_protocol="freestyle")
        self.assertIn("freestyle", str(raised.exception))

    # -- the fill prompt ---------------------------------------------------

    def _draft(self, task):
        """The draft a `holes` round would be filling: an accepted skeleton."""
        return eta_skeleton(task.expected_type_surface)

    def _fill_prompt(self, task, **overrides):
        draft = overrides.pop("draft", None) or self._draft(task)
        hole, = prompts.hole_obligations(draft, self.resolver)
        return prompts.build_fill_prompt(
            task.spec, REGIME_HELD_OUT, self.resolver,
            draft_source=draft, obligation=hole, **overrides)

    def test_a_fill_prompt_carries_the_draft_the_hole_and_the_closed_type(self):
        draft = self._draft(self.sum)
        hole, = prompts.hole_obligations(draft, self.resolver)
        closed = prompts.closed_subtask_type(prompts.declared_type_of(draft), hole)
        prompt = self._fill_prompt(self.sum)
        self.assertIn(prompts.PREAMBLE, prompt)
        self.assertIn(draft, prompt)
        self.assertIn(hole.surface, prompt)
        self.assertIn(closed, prompt)
        self.assertIn(prompts.fill_term_skeleton(hole), prompt)
        self.assertIn(self.sum.spec, prompt)
        self.assertTrue(prompt.endswith("\n"))

    def test_a_fill_prompt_narrows_before_its_ask(self):
        prompt = self._fill_prompt(self.sum, narrowing="REJECTED: nope")
        self.assertLess(prompt.index("REJECTED"), prompt.index(prompts.FILL_ASK_HEADER))
        self.assertLess(prompt.index(prompts.FILL_HEADER), prompt.index("REJECTED"))

    def test_a_fill_prompts_address_book_is_filtered_by_the_holes_own_goal(self):
        """§2.3: a fill draw has a type surface of its own, so `typed` needs no
        new machinery — and `full`, which the arms run, is unmoved by any of it."""
        draft = ("(def (fn I64 () I64) (lam I64 (let Bool (lit bool true) "
                 "(hole Bool ()))))")
        hole, = prompts.hole_obligations(draft, self.resolver)
        typed = prompts.build_fill_prompt(
            self.sum.spec, REGIME_HELD_OUT, self.resolver,
            draft_source=draft, obligation=hole,
            address_book=prompts.ADDRESS_BOOK_TYPED)
        closed = prompts.closed_subtask_type(prompts.declared_type_of(draft), hole)
        for row in prompts.typed_address_rows(self.resolver, closed):
            self.assertIn(row, typed)
        self.assertNotEqual(
            prompts.typed_address_rows(self.resolver, closed),
            prompts.typed_address_rows(self.resolver, self.sum.expected_type_surface))
        full = prompts.build_fill_prompt(
            self.sum.spec, REGIME_HELD_OUT, self.resolver,
            draft_source=draft, obligation=hole,
            address_book=prompts.ADDRESS_BOOK_FULL)
        self.assertIn(prompts.address_book_block(
            self.resolver, prompts.ADDRESS_BOOK_FULL), full)

    def test_a_fill_prompt_refuses_an_unfillable_hole(self):
        head = next(t for t in self.tasks if t.task_id == "heldout/list/headOrElse")
        draft = GOLD_TERMS[head.task_id].replace(_INNER_MATCH, f"(hole {_MAYBE_I64} ())")
        hole, = prompts.hole_obligations(draft, self.resolver)
        with self.assertRaises(ValueError):
            prompts.build_fill_prompt(
                head.spec, REGIME_HELD_OUT, self.resolver,
                draft_source=draft, obligation=hole)

    def test_every_fill_prompt_fits_the_planned_context(self):
        """§4.8 check 5's shape: a fill prompt carries a draft as well.

        The worst case available before a run is the largest gold-derived draft
        — `selectNonNegative`'s 779-character eta-skeleton — under the full
        address book.
        """
        for task in self.tasks:
            prompt = self._fill_prompt(task, address_book=prompts.ADDRESS_BOOK_FULL)
            self.assertLessEqual(
                prompts.estimated_tokens(prompt) + 768, 32768, task.task_id)

    # -- §4.8 check 2: blindness, by signature and adversarially -----------

    def test_the_fill_builder_is_never_handed_anything_that_knows_the_route(self):
        parameters = inspect.signature(prompts.build_fill_prompt).parameters
        self.assertNotIn("task", parameters)
        for name in parameters:
            self.assertNotIn("task", name)
        for name, parameter in parameters.items():
            self.assertIsNot(parameter.annotation, prompts.Task, name)

    def _round_prompts(self, task, draft, book):
        """Every prompt one round of the `holes` protocol would build.

        Exactly what the runner will call, in the order it will call it: the
        skeleton draw's prompt, then one fill prompt per fillable hole in the
        draft that came back.
        """
        built = [prompts.build_prompt(
            task, REGIME_HELD_OUT, self.resolver, address_book=book,
            generation_protocol=prompts.PROTOCOL_HOLES)]
        for hole in prompts.hole_obligations(draft, self.resolver):
            if not hole.fillable:
                continue
            built.append(prompts.build_fill_prompt(
                task.spec, REGIME_HELD_OUT, self.resolver,
                draft_source=draft, obligation=hole, address_book=book))
        return built

    def test_two_tasks_with_one_type_and_two_routes_are_indistinguishable(self):
        """§4.8 check 2's adversarial half, at *every stage of every round*.

        Same spec, same declared type, different `composes` and different
        `expected_surface` — the two things a `Task` carries that a prompt must
        never see. If any stage of the protocol read either, these two would
        diverge somewhere; they may not diverge anywhere.
        """
        surface = self.sum.expected_type_surface
        left = prompts.Task(
            task_id="probe/left", kind=KIND_HELD_OUT, spec=self.sum.spec,
            expected_type_surface=surface,
            composes=("corpus/list/foldLeft", "I64.add"),
            expected_surface=GOLD_TERMS[self.sum.task_id])
        right = prompts.Task(
            task_id="probe/right", kind=KIND_HELD_OUT, spec=self.sum.spec,
            expected_type_surface=surface,
            composes=("corpus/nat/select", "corpus/list/reverse", "corpus/maybe/map"),
            expected_surface="(def I64 (lit i64 0))")
        drafts = [
            eta_skeleton(surface),
            GOLD_TERMS["heldout/list/headOrElse"].replace(
                _NOTHING, f"(hole {_MAYBE_I64} ())"),
        ]
        for book in prompts.ADDRESS_BOOKS:
            for draft in drafts:
                self.assertEqual(
                    self._round_prompts(left, draft, book),
                    self._round_prompts(right, draft, book),
                    book)

    def test_no_verified_gold_term_appears_in_any_fill_prompt(self):
        """§4.8 check 6, extended to the stage the plan added: skeleton *or fill*."""
        for task in self.tasks:
            gold = GOLD_TERMS[task.task_id]
            term = gold[gold.index("(lam"):-1]
            for book in prompts.ADDRESS_BOOKS:
                prompt = self._fill_prompt(task, address_book=book)
                self.assertNotIn(gold, prompt, f"{book} {task.task_id}")
                self.assertNotIn(term, prompt, f"{book} {task.task_id} term")
                skeleton = prompts.build_prompt(
                    task, REGIME_HELD_OUT, self.resolver, address_book=book,
                    generation_protocol=prompts.PROTOCOL_HOLES)
                self.assertNotIn(gold, skeleton, f"{book} {task.task_id}")
                self.assertNotIn(term, skeleton, f"{book} {task.task_id} term")

    def test_the_arms_are_exactly_the_three_the_plan_registered(self):
        self.assertEqual(prompts.GENERATION_PROTOCOLS, ("whole", "redraft", "holes"))


# --------------------------------------------------------------------------
# The protocol-aware cell loop (2026-08-25 hole-decomposition plan §2.2, §4.3)
# --------------------------------------------------------------------------

from experiment.backends import Generation  # noqa: E402 - keeps this file append-only

_HEAD = next(t for t in prompts.HELD_OUT_TASKS if t.task_id == "heldout/list/headOrElse")

#: The draft a `holes` round is built to fill: `headOrElse`'s gold term with its
#: `Nothing` arm blanked to a hole. Funnel-accepted, one fillable hole, two
#: binders — so the splice's de Bruijn claim is exercised rather than dodged.
_DRAFT = GOLD_TERMS[_HEAD.task_id].replace(_NOTHING, f"(hole {_MAYBE_I64} ())")
#: The same term with its *inner* `match` blanked instead: one hole, under a
#: one-binder `match` arm, which is §2.2 step 3's unfillable-in-v1 case.
_UNFILLABLE_DRAFT = GOLD_TERMS[_HEAD.task_id].replace(_INNER_MATCH, f"(hole {_MAYBE_I64} ())")
#: A draft with **two** fillable holes, so a round has to enumerate, fill,
#: splice and then re-enumerate against the *new* draft.
_TWO_HOLE_DRAFT = "(def (fn I64 () I64) (lam I64 (let I64 (hole I64 ()) (hole I64 ()))))"

#: Real banked data: `heldout/nat/selectNonNegative` seed 7, round 0, from
#: `prototype/runs/decomp-holes/records.jsonl` — the 2026-08-26 hole-elicitation
#: plan §2.1 consequence 1's exhibit. Typecheck-rejected at `definition.term`:
#: the body is a **bare** hole under zero lambdas while the declared type wants
#: two. Under the pre-fix guard `funnel.accepted and _is_bare_hole(draft)` this
#: carries `False` — the funnel rejected it, so the conjunct never even asks
#: whether it is a bare hole — even though it plainly is one.
_BANKED_BARE_HOLE_REJECTED = (
    "(def (fn Bool () (fn (refine I64 (app (app (ref "
    "0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) "
    "(lit i64 0)) (var 0))) () (refine I64 (app (app (ref "
    "0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) "
    "(lit i64 -1)) (var 0))))) (hole Bool ()))"
)

#: Also real banked data: `heldout/list/sum` seed 6, round 0. Typecheck-rejected
#: at a sibling `let`-bound argument, nine steps away from the one fillable
#: `I64` hole in tail position — §1.2's "committed sibling, not the hole" case,
#: and what the well-scoped gate's "typecheck layer admits" test is built on.
_BANKED_SIBLING_REJECTED = (
    "(def (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba "
    "(I64)) () I64) (lam (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba "
    "(I64)) (let (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba "
    "(I64)) (con 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba 0 ()) "
    "(let (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) "
    "(con 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba 1 "
    "((app (ref 0x2509a18eb5e81726042a2cef5cd5444955a71c9dce18221ff8a49d0f93c82893) "
    "(var 0)) (var 1))) (hole I64 ())))))"
)

#: A typecheck-rejected draft with **two** fillable holes, the error at the
#: `if` condition — away from both. `_fill_for`'s first obligation is the
#: `then` branch; used to show a relaxed-gate round never exceeds one fill
#: draw even when a second fillable hole is sitting right there.
_TWO_HOLE_SIBLING_REJECTED = (
    "(def (fn I64 () I64) (lam I64 (if (lit i64 5) (hole I64 ()) (hole I64 ()))))"
)


def _fill_for(draft, body, *, resolver, index=0):
    """The fill definition a well-behaved model would write for one hole.

    Built from `prompts`' own closure and skeleton, never hand-typed, so a
    change to either shows up as a test failure rather than as drift.
    """
    obligation = [o for o in prompts.hole_obligations(draft, resolver) if o.fillable][index]
    closed = prompts.closed_subtask_type(prompts.declared_type_of(draft), obligation)
    term = prompts.fill_term_skeleton(obligation).replace(obligation.surface, body)
    return f"(def {closed} {term})"


class _ScriptedBackend(StubBackend):
    """A stub that answers by *prompt shape*: skeleton asks and fill asks differ.

    The `holes` protocol makes two kinds of call in one cell, so a single
    round-robin script cannot express a scenario. This one keeps a script per
    kind and repeats each script's last entry, which is exactly what
    `fill_attempts_per_hole` needs: the same bad fill offered twice.
    """

    def __init__(self, skeletons, fills=(), *, spend_the_cap=False):
        super().__init__(list(skeletons))
        self.skeleton_script = list(skeletons)
        self.fill_script = list(fills) or ["(def Bool (lit bool true))"]
        self.skeleton_prompts: list[str] = []
        self.fill_prompts: list[str] = []
        self.allotments: list[int] = []
        self.spend_the_cap = spend_the_cap

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        fill = prompts.FILL_HEADER in prompt
        script = self.fill_script if fill else self.skeleton_script
        seen = self.fill_prompts if fill else self.skeleton_prompts
        text = script[min(len(seen), len(script) - 1)]
        seen.append(prompt)
        self.prompts.append(prompt)
        self.allotments.append(max_tokens)
        self.draws += 1
        natural = max(1, len(text) // 4)
        used = max_tokens if self.spend_the_cap else min(natural, max_tokens)
        return Generation(
            text=text, completion_tokens=used, prompt_tokens=max(1, len(prompt) // 4),
            latency_s=0.0, stop_reason="length" if used < natural else "stop",
            backend=self.name)


class _FlakyScriptedBackend(_ScriptedBackend):
    """`_ScriptedBackend` that goes hard-down from its `fail_at`-th call on."""

    def __init__(self, *args, fail_at, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_at = fail_at
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        if self.calls >= self.fail_at:
            raise BackendUnavailable("stub: simulated backend hiccup")
        return super().generate(*args, **kwargs)


def protocol_config(protocol, **overrides):
    """One held-out cell of one task, small enough to assert on record by record."""
    config = runner.Config(
        backend="stub",
        seeds=[1],
        conditions=[runner.CONDITION_GBNF],
        regimes=[REGIME_HELD_OUT],
        tasks=[_HEAD.task_id],
        token_budget_per_task=6000,
        max_tokens_per_draw=60,
        max_draws_per_task=2,
        generation_protocol=protocol,
        address_book=prompts.ADDRESS_BOOK_FULL,
        stub_outputs=STUB_OUTPUTS,
        stub_grammar_outputs=STUB_GRAMMAR_OUTPUTS,
        source_path="<test>",
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    config.validate()
    return config


class GenerationProtocolConfigTest(unittest.TestCase):
    """Deliverable 1: the arm configs the plan shipped must load and validate."""

    ARMS = ("whole", "redraft", "holes")

    def test_the_three_shipped_arm_configs_load_and_validate(self):
        directory = HERE / "experiment"
        for arm in self.ARMS:
            with self.subTest(arm=arm):
                config = runner.Config.load(directory / f"decomp-{arm}.config.json")
                config.validate()
                self.assertEqual(config.generation_protocol, arm)
                # §4.2 / §4.3's pinned fields, read back off the file rather
                # than restated: a drifted arm is a drifted experiment.
                self.assertEqual(config.address_book, prompts.ADDRESS_BOOK_FULL)
                self.assertEqual(config.regimes, [REGIME_HELD_OUT])
                self.assertEqual(config.conditions, [runner.CONDITION_TYPEMASK])
                self.assertEqual(config.pruners, ["goal-type", "de-bruijn", "ref-hash"])
                self.assertEqual(config.token_budget_per_task, 4608)
                self.assertEqual(config.max_tokens_per_draw, 768)
                self.assertEqual(config.max_draws_per_task, 64)
                self.assertEqual(config.seeds, [1, 2, 3, 4, 5, 6, 7, 8])
                self.assertFalse(config.stop_on_semantic_success)
                # §4.3.6's protocol constants, which the arms do not restate.
                self.assertEqual(config.fills_per_round_max, 6)
                self.assertEqual(config.fill_attempts_per_hole, 2)

    def test_whole_is_the_default_so_every_older_config_is_unmoved(self):
        self.assertEqual(runner.Config().generation_protocol, prompts.PROTOCOL_WHOLE)
        for name in ("addr-full.config.json", "phase_a.config.json", "phase_b.config.json"):
            config = runner.Config.load(HERE / "experiment" / name)
            self.assertEqual(config.generation_protocol, prompts.PROTOCOL_WHOLE, name)

    def test_an_unknown_protocol_is_refused_by_name(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(generation_protocol="freestyle").validate()
        self.assertIn("freestyle", str(raised.exception))
        self.assertIn("holes", str(raised.exception))

    def test_the_protocol_constants_must_be_positive(self):
        for field in ("fills_per_round_max", "fill_attempts_per_hole"):
            with self.subTest(field=field):
                with self.assertRaises(SystemExit):
                    runner.Config(**{field: 0}).validate()


class RedraftProtocolTest(unittest.TestCase):
    """§4.2's middle arm: `whole` plus §8.3 narrowing, and nothing else."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def _run(self, protocol, **overrides):
        config = protocol_config(protocol, max_draws_per_task=3, **overrides)
        backend = _ScriptedBackend([BROKEN_TYPE])
        records, summary = runner.run(config, resolver=self.resolver, backend=backend)
        return records, summary, backend

    def test_whole_never_narrows_so_every_prompt_in_a_cell_is_identical(self):
        records, _, backend = self._run(prompts.PROTOCOL_WHOLE)
        self.assertEqual(len(records), 3)
        self.assertEqual(len(set(backend.prompts)), 1)
        self.assertFalse(any(r["narrowed"] for r in records))
        self.assertTrue(all(r["role"] == "whole" and r["candidate"] for r in records))

    def test_redraft_narrows_after_the_first_rejection_and_not_before(self):
        records, _, backend = self._run(prompts.PROTOCOL_REDRAFT)
        self.assertEqual(len(records), 3)
        self.assertEqual([r["narrowed"] for r in records], [False, True, True])
        # §4.8 check 1 at run time, not just at prompt-builder time: draw 0 of
        # a `redraft` cell is byte-identical to draw 0 of a `whole` cell.
        _, _, control = self._run(prompts.PROTOCOL_WHOLE)
        self.assertEqual(backend.prompts[0], control.prompts[0])
        self.assertIn("rejected by the typecheck layer", backend.prompts[1])

    def test_redraft_spends_the_same_purse_the_same_way_as_whole(self):
        whole, _, whole_backend = self._run(prompts.PROTOCOL_WHOLE)
        redraft, _, redraft_backend = self._run(prompts.PROTOCOL_REDRAFT)
        self.assertEqual(whole_backend.allotments, redraft_backend.allotments)
        self.assertEqual([r["tokens_used"] for r in whole],
                         [r["tokens_used"] for r in redraft])
        self.assertEqual([r["draw_seed"] for r in whole], [r["draw_seed"] for r in redraft])


class HolesProtocolTest(unittest.TestCase):
    """§2.2's six-step round, driven end to end through the stub backend.

    Every path §4.8 check 7 names is exercised here: the accepted-draft path,
    the rejected-draft path, the bare-hole path, the unfillable-hole path and
    the assembly-rollback path — plus the two rollbacks §2.2 states as
    properties rather than as code (monotonicity, and a splice refusal).
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def _run(self, skeletons, fills=(), **overrides):
        config = protocol_config(prompts.PROTOCOL_HOLES, **overrides)
        backend = _ScriptedBackend(skeletons, fills)
        records, summary = runner.run(config, resolver=self.resolver, backend=backend)
        return records, summary, backend

    @staticmethod
    def _by_role(records, role):
        return [r for r in records if r["role"] == role]

    # -- the accepted-draft path, end to end -------------------------------

    def test_a_round_drafts_fills_splices_and_rechecks(self):
        """§2.2 read straight through: the assembled candidate is the gold term."""
        fill = _fill_for(_DRAFT, _NOTHING, resolver=self.resolver)
        records, summary, backend = self._run([_DRAFT], [fill], max_draws_per_task=2)

        self.assertEqual([r["role"] for r in records], ["skeleton", "fill", "candidate"])
        skeleton, fill_record, candidate = records

        self.assertEqual(skeleton["funnel_outcome"], ACCEPTED)
        self.assertEqual(skeleton["holes"], 1)
        self.assertEqual(skeleton["holes_fillable"], 1)
        self.assertFalse(skeleton["bare_hole_body"])
        self.assertFalse(skeleton["candidate"])
        # §4.3.1: a hole-bearing draft never meets the floor, whatever its type.
        self.assertFalse(skeleton["semantic_success"])

        self.assertEqual(fill_record["splice_outcome"], "spliced")
        self.assertEqual(fill_record["assembled_outcome"], ACCEPTED)
        self.assertEqual(fill_record["hole_binders"], 2)
        self.assertEqual(fill_record["draft_holes_before"], 1)
        self.assertEqual(fill_record["draft_holes_after"], 0)
        self.assertFalse(fill_record["candidate"])
        self.assertEqual(fill_record["semantic_rule"], "fill-draw")

        self.assertTrue(candidate["candidate"])
        self.assertEqual(candidate["source"], GOLD_TERMS[_HEAD.task_id])
        self.assertEqual(candidate["funnel_outcome"], ACCEPTED)
        self.assertEqual(candidate["holes"], 0)
        self.assertTrue(candidate["semantic_success"])
        self.assertEqual(candidate["tokens_completion"], 0)
        self.assertEqual(candidate["fills_spliced"], 1)
        self.assertEqual(candidate["fills_rolled_back"], 0)
        self.assertTrue(candidate["cell_done"])

        # The zero-token assembly is not a draw, and no per-draw rate counts it.
        cell = summary["cells"][f"{runner.CONDITION_GBNF}|{REGIME_HELD_OUT}"]
        self.assertEqual(cell["draws"], backend.draws)
        self.assertEqual(cell["draws"], 2)
        self.assertEqual(cell["protocol"]["rounds"], 1)
        self.assertEqual(cell["protocol"]["fills_spliced"], 1)

    def test_a_second_hole_is_enumerated_against_the_spliced_draft(self):
        """Two holes, two fills, and the second obligation comes from the *new* draft."""
        first = _fill_for(_TWO_HOLE_DRAFT, "(lit i64 1)", resolver=self.resolver)
        spliced = prompts.splice_fill(
            _TWO_HOLE_DRAFT,
            [o for o in prompts.hole_obligations(_TWO_HOLE_DRAFT, self.resolver)
             if o.fillable][0],
            first)
        second = _fill_for(spliced, "(var 0)", resolver=self.resolver)
        records, _, _ = self._run([_TWO_HOLE_DRAFT], [first, second], max_draws_per_task=3)

        fills = self._by_role(records, "fill")
        self.assertEqual([f["splice_outcome"] for f in fills], ["spliced", "spliced"])
        self.assertEqual([f["fill_index"] for f in fills], [0, 1])
        self.assertNotEqual(fills[0]["hole_path"], fills[1]["hole_path"])
        self.assertNotEqual(fills[0]["closed_type"], fills[1]["closed_type"])
        candidate, = self._by_role(records, "candidate")
        self.assertEqual(candidate["holes"], 0)
        self.assertEqual(candidate["fills_spliced"], 2)
        self.assertEqual(
            candidate["source"], "(def (fn I64 () I64) (lam I64 (let I64 (lit i64 1) (var 0))))")

    def test_fills_per_round_max_caps_the_round(self):
        first = _fill_for(_TWO_HOLE_DRAFT, "(lit i64 1)", resolver=self.resolver)
        records, _, backend = self._run(
            [_TWO_HOLE_DRAFT], [first], max_draws_per_task=2, fills_per_round_max=1)
        self.assertEqual(len(self._by_role(records, "fill")), 1)
        candidate = self._by_role(records, "candidate")[0]
        self.assertEqual(candidate["holes"], 1, "the round stopped at one fill")

    # -- the paths that do not fill ----------------------------------------

    def test_a_rejected_draft_is_the_rounds_candidate_and_narrows_the_next(self):
        records, _, backend = self._run([BROKEN_TYPE], max_draws_per_task=2)
        self.assertEqual([r["role"] for r in records],
                         ["skeleton", "candidate", "skeleton", "candidate"])
        self.assertEqual(backend.fill_prompts, [], "a rejected draft is never filled")
        self.assertEqual([r["round"] for r in records], [0, 0, 1, 1])
        self.assertIn("rejected by the typecheck layer", backend.skeleton_prompts[1])
        self.assertTrue(records[2]["narrowed"])
        for candidate in self._by_role(records, "candidate"):
            self.assertEqual(candidate["source"], BROKEN_TYPE)
            self.assertFalse(candidate["semantic_success"])

    def test_a_bare_hole_body_gets_no_fills_and_ends_the_round(self):
        """§3's last sentence, enforced rather than merely asked for."""
        bare = eta_skeleton(_HEAD.expected_type_surface)
        records, _, backend = self._run([bare], max_draws_per_task=1)
        self.assertEqual([r["role"] for r in records], ["skeleton", "candidate"])
        self.assertEqual(backend.fill_prompts, [])
        self.assertTrue(records[0]["bare_hole_body"])
        self.assertEqual(records[0]["funnel_outcome"], ACCEPTED)
        candidate = records[1]
        self.assertEqual(candidate["source"], bare)
        self.assertEqual(candidate["holes"], 1)
        # Accepted and type-exact — and refused by §4.3.1's floor rule anyway.
        self.assertEqual(candidate["type_surface"], _HEAD.expected_type_surface)
        self.assertFalse(candidate["semantic_success"])
        self.assertIn("hole", candidate["semantic_detail"])

    def test_an_unfillable_hole_is_recorded_with_its_reason_and_not_drawn_for(self):
        records, summary, backend = self._run([_UNFILLABLE_DRAFT], max_draws_per_task=1)
        self.assertEqual(backend.fill_prompts, [])
        skeleton = records[0]
        self.assertEqual(skeleton["holes"], 1)
        self.assertEqual(skeleton["holes_fillable"], 0)
        self.assertEqual(len(skeleton["hole_reasons"]), 1)
        self.assertIn("match", skeleton["hole_reasons"][0])
        cell = summary["cells"][f"{runner.CONDITION_GBNF}|{REGIME_HELD_OUT}"]
        self.assertEqual(cell["protocol"]["fillable_hole_fraction"], 0.0)
        self.assertEqual(sum(cell["protocol"]["unfillable_reasons"].values()), 1)

    def test_a_draft_with_no_holes_makes_the_protocol_redraft(self):
        """§4.2: 'if the model declines to write a hole, `holes` **is** `redraft`'."""
        good = GOLD_TERMS[_HEAD.task_id]
        records, _, backend = self._run([good], max_draws_per_task=1)
        self.assertEqual(backend.fill_prompts, [])
        self.assertEqual([r["role"] for r in records], ["skeleton", "candidate"])
        self.assertEqual(records[0]["holes"], 0)
        self.assertTrue(records[1]["semantic_success"])

    # -- the rollback paths ------------------------------------------------

    def _rollback(self, fill, **overrides):
        return self._run([_DRAFT], [fill], max_draws_per_task=3, **overrides)

    def test_an_assembly_that_fails_the_recheck_is_rolled_back(self):
        """§2.2's authority clause: the re-check, not the closure, decides."""
        first, second = prompts.hole_obligations(_DRAFT, self.resolver)[0].binders
        # Accepted standalone, at a type that is not the hole's — the model
        # wrote a well-typed definition of the wrong thing.
        wrong = f"(def (fn {first} () (fn {second} () {second})) (lam {first} (lam {second} (var 0))))"
        self.assertEqual(run_funnel(wrong, self.resolver).outcome, ACCEPTED)
        records, _, backend = self._rollback(wrong)

        fills = self._by_role(records, "fill")
        self.assertEqual(len(fills), 2, "one retry per §4.3.6's fill_attempts_per_hole")
        for fill_record in fills:
            self.assertEqual(fill_record["funnel_outcome"], ACCEPTED)
            self.assertEqual(fill_record["splice_outcome"], "rolled-back")
            self.assertEqual(fill_record["assembled_outcome"], "typecheck")
            self.assertTrue(fill_record["assembled_error"])
        # The failure is fed back for the retry, and only for it.
        self.assertFalse(fills[0]["narrowed"])
        self.assertTrue(fills[1]["narrowed"])
        self.assertIn("rejected by the typecheck layer", backend.fill_prompts[1])

        candidate, = self._by_role(records, "candidate")
        self.assertEqual(candidate["source"], _DRAFT, "the draft is restored, not damaged")
        self.assertEqual(candidate["fills_attempted"], 2)
        self.assertEqual(candidate["fills_rolled_back"], 2)
        self.assertEqual(candidate["fills_spliced"], 0)

    def test_a_fill_that_fills_a_hole_with_a_hole_is_rolled_back(self):
        """§2.2's monotonicity: 'holes only ever disappear'."""
        holey = _fill_for(_DRAFT, f"(hole {_MAYBE_I64} ())", resolver=self.resolver)
        self.assertEqual(run_funnel(holey, self.resolver).outcome, ACCEPTED)
        records, _, backend = self._rollback(holey)
        fills = self._by_role(records, "fill")
        self.assertEqual([f["splice_outcome"] for f in fills], ["rolled-back", "rolled-back"])
        # The assembly typechecks — it is the *hole count* that refuses it.
        self.assertEqual(fills[0]["assembled_outcome"], ACCEPTED)
        self.assertEqual(fills[0]["draft_holes_before"], 1)
        self.assertIn("another hole", backend.fill_prompts[1])
        candidate, = self._by_role(records, "candidate")
        self.assertEqual(candidate["source"], _DRAFT)
        self.assertEqual(candidate["holes"], 1)

    def test_a_fill_that_cannot_be_spliced_is_refused_not_forced(self):
        obligation, = prompts.hole_obligations(_DRAFT, self.resolver)
        inner = obligation.binders[1]
        short = f"(def (fn {inner} () {inner}) (lam {inner} (var 0)))"
        records, _, backend = self._rollback(short)
        fills = self._by_role(records, "fill")
        self.assertEqual([f["splice_outcome"] for f in fills],
                         ["splice-error", "splice-error"])
        self.assertEqual(fills[0]["assembled_outcome"], "")
        self.assertIn("could not be spliced back", backend.fill_prompts[1])
        self.assertEqual(self._by_role(records, "candidate")[0]["source"], _DRAFT)

    def test_a_fill_the_funnel_rejects_never_reaches_the_splice(self):
        records, _, backend = self._rollback(BROKEN_TYPE)
        fills = self._by_role(records, "fill")
        self.assertEqual([f["splice_outcome"] for f in fills],
                         ["fill-rejected", "fill-rejected"])
        self.assertEqual(fills[0]["assembled_outcome"], "")
        self.assertIn("rejected by the typecheck layer", backend.fill_prompts[1])

    def test_one_hole_exhausting_its_attempts_ends_the_round(self):
        records, _, backend = self._run(
            [_TWO_HOLE_DRAFT], [BROKEN_TYPE], max_draws_per_task=5)
        first_round = [r for r in records if r["round"] == 0]
        self.assertEqual(len(self._by_role(first_round, "fill")), 2)
        # The second hole is never reached: §2.2 step 6 ends the round.
        self.assertEqual({f["fill_index"] for f in self._by_role(first_round, "fill")}, {0})
        self.assertEqual(self._by_role(first_round, "candidate")[0]["holes"], 2)

    # -- §4.3.2's purse, which binds for every kind of draw ----------------

    def test_every_draw_skeleton_or_fill_is_charged_a_full_cap_to_one_purse(self):
        fill = _fill_for(_DRAFT, _NOTHING, resolver=self.resolver)
        config = protocol_config(
            prompts.PROTOCOL_HOLES,
            token_budget_per_task=250, max_tokens_per_draw=60, max_draws_per_task=64)
        backend = _ScriptedBackend([_DRAFT], [fill], spend_the_cap=True)
        records, summary = runner.run(config, resolver=self.resolver, backend=backend)

        # 250 // 60 = 4 whole-cap draws; the 10-token scrap buys nothing.
        self.assertEqual(backend.allotments, [60] * 4)
        self.assertEqual(backend.draws, 4)
        draws = [r for r in records if r["role"] in runner.DRAW_ROLES]
        self.assertEqual(sum(r["tokens_completion"] for r in draws), 240)
        self.assertLessEqual(max(r["tokens_used"] for r in records), 250)
        # Skeletons and fills are the same event to the purse.
        self.assertEqual(len([r for r in draws if r["role"] == "skeleton"]), 2)
        self.assertEqual(len([r for r in draws if r["role"] == "fill"]), 2)
        self.assertTrue(records[-1]["cell_done"])
        self.assertEqual(records[-1]["role"], "candidate")

    def test_a_budget_that_cannot_fund_one_draw_runs_no_round_at_all(self):
        config = protocol_config(
            prompts.PROTOCOL_HOLES, token_budget_per_task=59, max_tokens_per_draw=60)
        backend = _ScriptedBackend([_DRAFT])
        records, _ = runner.run(config, resolver=self.resolver, backend=backend)
        self.assertEqual(records, [])
        self.assertEqual(backend.draws, 0)

    def test_a_purse_exhausted_mid_round_still_scores_the_partial_draft(self):
        fill = _fill_for(_DRAFT, _NOTHING, resolver=self.resolver)
        records, _, backend = self._run([_DRAFT], [fill], max_draws_per_task=1)
        self.assertEqual(backend.draws, 1)
        self.assertEqual([r["role"] for r in records], ["skeleton", "candidate"])
        candidate = records[1]
        self.assertEqual(candidate["source"], _DRAFT, "the unfilled draft is the candidate")
        self.assertTrue(candidate["cell_done"])
        self.assertEqual(candidate["fills_attempted"], 0)

    def test_stop_on_semantic_success_stops_on_a_candidate(self):
        fill = _fill_for(_DRAFT, _NOTHING, resolver=self.resolver)
        records, _, backend = self._run(
            [_DRAFT], [fill], max_draws_per_task=64, token_budget_per_task=6000,
            stop_on_semantic_success=True)
        self.assertEqual([r["role"] for r in records], ["skeleton", "fill", "candidate"])
        self.assertTrue(records[-1]["semantic_success"])
        self.assertTrue(records[-1]["cell_done"])

    # -- the record, and what analysis reads off it ------------------------

    def test_every_record_keeps_the_fields_the_harness_already_wrote(self):
        fill = _fill_for(_DRAFT, _NOTHING, resolver=self.resolver)
        records, _, _ = self._run([_DRAFT], [fill], max_draws_per_task=2)
        required = {
            "task", "task_kind", "condition", "regime", "address_book", "seed",
            "draw", "draw_seed", "narrowed", "grammar", "budget",
            "tokens_completion", "tokens_prompt", "tokens_used", "tokens_remaining",
            "latency_s", "stop_reason", "backend", "funnel_outcome", "layers_passed",
            "error_class", "error_path", "error_message", "de_bruijn_suspected",
            "identity", "type_surface", "semantic_success", "semantic_rule",
            "semantic_detail", "rubric_pending", "source", "raw", "retried",
            "cell_done",
        }
        added = {"generation_protocol", "role", "round", "candidate", "holes",
                 "holes_fillable", "hole_reasons"}
        for record in records:
            self.assertTrue(required <= set(record), sorted(required - set(record)))
            self.assertTrue(added <= set(record), sorted(added - set(record)))
            self.assertEqual(record["generation_protocol"], prompts.PROTOCOL_HOLES)
        draw_indexes = [r["draw"] for r in records]
        self.assertEqual(draw_indexes, sorted(set(draw_indexes)))

    def test_the_report_renders_the_protocol_telemetry_only_for_a_holes_run(self):
        fill = _fill_for(_DRAFT, _NOTHING, resolver=self.resolver)
        records, summary, _ = self._run([_DRAFT], [fill], max_draws_per_task=2)
        report = runner.render_report(summary, records)
        self.assertIn("Protocol telemetry", report)
        self.assertIn("**Generation protocol:** holes", report)
        plain, plain_summary = runner.run(
            protocol_config(prompts.PROTOCOL_WHOLE, max_draws_per_task=1),
            resolver=self.resolver, backend=_ScriptedBackend([_DRAFT]))
        plain_report = runner.render_report(plain_summary, plain)
        self.assertNotIn("Protocol telemetry", plain_report)
        self.assertNotIn("Generation protocol", plain_report)
        self.assertNotIn("protocol", plain_summary)


class FillGateTest(unittest.TestCase):
    """Deliverable 2, 2026-08-26 hole-elicitation plan §2.1: the fill gate that
    discharges row 4. `"accepted"` (default) is the pre-existing rule, pinned
    byte for byte; `"well-scoped"` is the relaxation — parse, scope and
    references block, typecheck admits — with §3's bare-hole rule evaluated
    unconditionally (consequence 1) and relaxed rounds capped at one fill draw
    (consequence 4). Every fixture that stands in for "a rejected draft with a
    fillable hole" is real banked data from `runs/decomp-holes/records.jsonl`,
    not hand-built, so the gate is proven against the shapes it actually has
    to handle.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def _run(self, skeletons, fills=(), **overrides):
        config = protocol_config(prompts.PROTOCOL_HOLES, **overrides)
        backend = _ScriptedBackend(skeletons, fills)
        records, summary = runner.run(config, resolver=self.resolver, backend=backend)
        return records, summary, backend

    @staticmethod
    def _by_role(records, role):
        return [r for r in records if r["role"] == role]

    # -- the default, pinned ------------------------------------------------

    def test_fill_gate_defaults_to_accepted(self):
        self.assertEqual(runner.Config().fill_gate, runner.FILL_GATE_ACCEPTED)
        for name in ("decomp-whole.config.json", "decomp-redraft.config.json",
                     "decomp-holes.config.json"):
            config = runner.Config.load(HERE / "experiment" / name)
            self.assertEqual(config.fill_gate, runner.FILL_GATE_ACCEPTED, name)

    def test_an_unknown_fill_gate_is_refused_by_name(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(fill_gate="parses").validate()
        self.assertIn("parses", str(raised.exception))
        self.assertIn("well-scoped", str(raised.exception))

    def test_default_gate_is_byte_identical_to_explicit_accepted(self):
        """Item 1: 'existing behavior byte-identical under the default.'"""
        fill = _fill_for(_DRAFT, _NOTHING, resolver=self.resolver)
        default_records, _, _ = self._run([_DRAFT], [fill], max_draws_per_task=2)
        explicit_records, _, _ = self._run(
            [_DRAFT], [fill], max_draws_per_task=2, fill_gate=runner.FILL_GATE_ACCEPTED)
        self.assertEqual(default_records, explicit_records)

    def test_default_gate_still_refuses_a_typecheck_rejected_hole(self):
        """The default gate is exactly the old rule: only a *funnel-accepted*
        draft's holes reach a fill — a typecheck-rejected draft never does,
        even one with a perfectly fillable hole (real banked data, §1.2's
        "committed sibling, not the hole" case)."""
        records, _, backend = self._run([_BANKED_SIBLING_REJECTED], max_draws_per_task=1)
        self.assertEqual(backend.fill_prompts, [])
        self.assertEqual(records[0]["funnel_outcome"], "typecheck")
        self.assertEqual(records[0]["holes_fillable"], 1)
        self.assertFalse(records[0]["bare_hole_body"])

    # -- each blocking layer blocks, under well-scoped -----------------------

    def test_well_scoped_gate_blocks_at_parse(self):
        records, _, backend = self._run(
            [BROKEN_SYNTAX], max_draws_per_task=1, fill_gate=runner.FILL_GATE_WELL_SCOPED)
        self.assertEqual(backend.fill_prompts, [], "no IR, so no obligations (§2.1's table)")
        self.assertEqual(records[0]["funnel_outcome"], "parse")

    def test_well_scoped_gate_blocks_at_scope(self):
        records, _, backend = self._run(
            [BROKEN_SCOPE], max_draws_per_task=1, fill_gate=runner.FILL_GATE_WELL_SCOPED)
        self.assertEqual(backend.fill_prompts, [],
                         "a de Bruijn index out of range voids splice_fill's alignment claim")
        self.assertEqual(records[0]["funnel_outcome"], "scope")

    def test_well_scoped_gate_blocks_at_references(self):
        records, _, backend = self._run(
            [BROKEN_REFERENCES], max_draws_per_task=1, fill_gate=runner.FILL_GATE_WELL_SCOPED)
        self.assertEqual(backend.fill_prompts, [],
                         "an unresolvable hash in the declared type surface never fills")
        self.assertEqual(records[0]["funnel_outcome"], "references")

    # -- typecheck admits, under well-scoped ---------------------------------

    def test_well_scoped_gate_admits_a_typecheck_rejected_draft(self):
        """§2.1's relaxation, on real banked data: a draft that dies at
        typecheck — nine steps from its own hole (§1.2) — still gets a fill
        draw, where the default gate above refused it outright."""
        fill = _fill_for(_BANKED_SIBLING_REJECTED, "(lit i64 0)", resolver=self.resolver)
        records, _, backend = self._run(
            [_BANKED_SIBLING_REJECTED], [fill], max_draws_per_task=2,
            fill_gate=runner.FILL_GATE_WELL_SCOPED)
        self.assertEqual(len(backend.fill_prompts), 1)
        skeleton = records[0]
        self.assertEqual(skeleton["funnel_outcome"], "typecheck")
        self.assertEqual(skeleton["fill_gate"], runner.FILL_GATE_WELL_SCOPED)
        fills = self._by_role(records, "fill")
        self.assertEqual(len(fills), 1)
        # §2.1 consequence 3: the re-check stays the authority. The sibling
        # error the fill never touched (§1.2) rejects the assembly too.
        self.assertEqual(fills[0]["splice_outcome"], "rolled-back")
        self.assertEqual(fills[0]["assembled_outcome"], "typecheck")

    # -- the bare-hole rule, unconditional (consequence 1) -------------------

    def test_bare_hole_rule_is_evaluated_unconditionally_under_well_scoped(self):
        """Fail-then-pass on real banked data: `heldout/nat/selectNonNegative`
        seed 7 round 0 — `runner.py`'s own pre-fix docstring exhibit. FAIL
        first: replay the old guard and show its verdict is wrong. PASS
        second: the fixed runner refuses the fill anyway."""
        draft = _BANKED_BARE_HOLE_REJECTED
        funnel = run_funnel(draft, self.resolver)
        self.assertEqual(funnel.outcome, "typecheck", "the banked outcome, pinned")
        self.assertFalse(funnel.accepted)
        self.assertTrue(prompts.bare_hole_body(draft), "the draft IS a bare hole")

        # FAIL: `funnel.accepted and _is_bare_hole(draft)`, replayed exactly.
        # It reports "not bare" for every rejected draft, whatever its shape —
        # including this one, which plainly is one.
        old_guard_verdict = funnel.accepted and prompts.bare_hole_body(draft)
        self.assertFalse(
            old_guard_verdict,
            "documents the bug this test guards against: the pre-fix conjunct "
            "misreports a genuinely bare, rejected draft as not bare")

        # PASS: the fixed runner evaluates the rule unconditionally — under
        # the one gate that can even reach this draft — and refuses the fill.
        records, _, backend = self._run(
            [draft], max_draws_per_task=1, fill_gate=runner.FILL_GATE_WELL_SCOPED)
        self.assertEqual(backend.fill_prompts, [], "the fixed gate must refuse the fill")
        skeleton = records[0]
        self.assertTrue(skeleton["bare_hole_body"], "recomputed unconditionally")
        self.assertEqual(skeleton["funnel_outcome"], "typecheck")

    def test_accepted_gate_bare_hole_telemetry_is_unchanged(self):
        """Item 1's byte-identity at the field level, not just the admission
        decision: under the default gate the same banked draft's
        `bare_hole_body` still reads `False`, exactly as it always has —
        the unconditional rule is `well-scoped`-only, by design (§2.1)."""
        records, _, _ = self._run([_BANKED_BARE_HOLE_REJECTED], max_draws_per_task=1)
        self.assertFalse(records[0]["bare_hole_body"])

    # -- the 1-fill cap on a relaxed-gate round (consequence 4) --------------

    def test_relaxed_gate_round_never_exceeds_one_fill_draw(self):
        """§2.1 consequence 4: 'relaxed-gate rounds are capped at one fill
        draw.' Two fillable holes are on offer and the model's fill is
        rejected outright, so an uncapped round (6 fills/round, 2
        attempts/hole, §4.3.6) would try hole 0 twice before ever reaching
        hole 1. The relaxed round tries once, period."""
        records, _, backend = self._run(
            [_TWO_HOLE_SIBLING_REJECTED], [BROKEN_TYPE], max_draws_per_task=2,
            fill_gate=runner.FILL_GATE_WELL_SCOPED)
        self.assertEqual(len(backend.fill_prompts), 1)
        fills = self._by_role(records, "fill")
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["splice_outcome"], "fill-rejected")
        candidate, = self._by_role(records, "candidate")
        self.assertEqual(candidate["fills_attempted"], 1)
        self.assertEqual(candidate["holes"], 2, "neither hole was touched")

    def test_an_accepted_draft_keeps_the_normal_caps_under_well_scoped(self):
        """The relaxation is per-*round*, not per-gate: a funnel-accepted
        draft under the well-scoped gate still gets the full §4.3.6 retry
        budget, exactly as it does under the default gate."""
        first, second = prompts.hole_obligations(_DRAFT, self.resolver)[0].binders
        wrong = (f"(def (fn {first} () (fn {second} () {second})) "
                 f"(lam {first} (lam {second} (var 0))))")
        self.assertEqual(run_funnel(wrong, self.resolver).outcome, ACCEPTED)
        records, _, backend = self._run(
            [_DRAFT], [wrong], max_draws_per_task=3, fill_gate=runner.FILL_GATE_WELL_SCOPED)
        fills = self._by_role(records, "fill")
        self.assertEqual(len(fills), 2, "an accepted draft keeps both retry attempts")


class HolesCrashSafetyTest(unittest.TestCase):
    """Per-draw persistence and resume, under the round protocol.

    The property the round adds: a cell always ends on a **candidate** record,
    so `cell_done` still marks a complete cell, and a cell interrupted
    mid-round is discarded whole rather than resumed onto a half-filled draft.
    A resumed cell therefore neither double-spends its purse nor loses its
    draft — it is either skipped entirely or redrawn from round 0.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.fill = _fill_for(_DRAFT, _NOTHING, resolver=ExperimentResolver())

    def _config(self, **overrides):
        return protocol_config(
            prompts.PROTOCOL_HOLES, seeds=[1, 2], max_draws_per_task=2, **overrides)

    def test_every_record_of_a_round_lands_on_disk_as_it_is_built(self):
        with tempfile.TemporaryDirectory() as directory:
            records, _ = runner.run(
                self._config(), resolver=self.resolver,
                backend=_ScriptedBackend([_DRAFT], [self.fill]), output_dir=directory)
            on_disk = [
                json.loads(line) for line in
                (Path(directory) / "records.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(on_disk), len(records))
            self.assertEqual(len(on_disk), 6)  # 2 cells × (skeleton, fill, candidate)
            self.assertTrue(all(r["role"] in ("skeleton", "fill", "candidate") for r in on_disk))
            # Only the candidate that ends a cell is marked complete.
            self.assertEqual([r["role"] for r in on_disk if r["cell_done"]],
                             ["candidate", "candidate"])

    def test_a_cell_cut_off_mid_round_is_discarded_and_redrawn_whole(self):
        # Cell 1 takes calls 1-2; cell 2's skeleton is call 3 and its fill is
        # call 4 — so the cell dies *mid-round*, which is the case the round
        # protocol adds and the one this test is about.
        dead = _FlakyScriptedBackend([_DRAFT], [self.fill], fail_at=4)
        with tempfile.TemporaryDirectory() as directory:
            config = self._config()
            with self.assertRaises(BackendUnavailable) as raised:
                runner.run(config, resolver=self.resolver, backend=dead, output_dir=directory)
            self.assertIn("partial run: 1 of 2 cells", str(raised.exception))
            path = Path(directory) / "records.jsonl"
            on_disk = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            # Cell 1's three records; cell 2 died on its *fill*, so its
            # skeleton is on disk but its cell is incomplete.
            self.assertEqual([r["seed"] for r in on_disk], [1, 1, 1, 2])
            self.assertEqual(on_disk[-1]["role"], "skeleton")
            self.assertFalse(on_disk[-1]["cell_done"])

            logged = []
            fresh = _ScriptedBackend([_DRAFT], [self.fill])
            records, summary = runner.run(
                config, resolver=self.resolver, backend=fresh,
                output_dir=directory, log=logged.append)
            self.assertTrue(any("skipping 1 completed cells" in m for m in logged), logged)
            # Cell 2 was redrawn from round 0 — two draws, not one — and cell 1
            # was not redrawn at all, so the purse is spent once per cell.
            self.assertEqual(fresh.draws, 2)
            self.assertEqual(len(records), 6)
            keys = [(r["task"], r["condition"], r["regime"], r["seed"], r["draw"])
                    for r in records]
            self.assertEqual(len(keys), len(set(keys)), "resume must not duplicate a record")
            self.assertEqual(
                [r["role"] for r in records if r["seed"] == 2],
                ["skeleton", "fill", "candidate"], "the resumed cell kept its draft")
            self.assertEqual(
                [r["source"] for r in records if r["candidate"]],
                [GOLD_TERMS[_HEAD.task_id]] * 2)
            self.assertEqual(summary["records"], 6)

    def test_a_completed_holes_run_resumes_to_a_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._config()
            runner.run(config, resolver=self.resolver,
                       backend=_ScriptedBackend([_DRAFT], [self.fill]), output_dir=directory)
            again = _ScriptedBackend([_DRAFT], [self.fill])
            records, _ = runner.run(
                config, resolver=self.resolver, backend=again, output_dir=directory)
            self.assertEqual(again.draws, 0, "a complete cell is never re-spent")
            self.assertEqual(len(records), 6)


# --------------------------------------------------------------------------
# Narrowing-note legibility (2026-08-26 hole-elicitation plan §2.4)
# --------------------------------------------------------------------------

from experiment.evaluate import narrowing_note  # noqa: E402 - keeps this file append-only

#: A raw type-IR `repr` artefact, in either of the two shapes the banked
#: `--section blame` regex (`expected \[|got \[|b'`) was built to catch: a
#: bracketed Python list literal, or a Python `bytes` literal.
_REPR_ARTEFACT = re.compile(r"expected \[|got \[|b'")

#: `decomp-redraft`'s first `TypingError` rejection, byte for byte
#: (`prototype/runs/decomp-redraft/records.jsonl`, `error_class ==
#: "TypingError"`). Before this fix its `error_message` was:
#:   "definition.term.body: type mismatch: expected [1, b'.\xe91\xa3ta2\x88,
#:   \xdb\xc63\x85\xcc\xafs \xa5CrX\x9b&\r\xea\xa1\xc8Q\xa5\x9e\x8d\xba',
#:   [[0, 2]]], got [2, [0, 2], [], [0, 1]]"
#: — a raw `repr` of both a `data` type (with its 32-byte hash) and a `fn`
#: type, which is what makes it a fixture that exercises both the bytes-digest
#: and the compound-type-node halves of the rendering fix at once.
_BANKED_TYPE_MISMATCH_SOURCE = (
    "(def (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) "
    "() (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64))) "
    "(lam (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) "
    "(app (ref 0x4fb7cc71149d69f56fb423f341abd7be1fe28c6e5d92fbdb22485498d1dea41d) "
    "(app (ref 0x4bd80df0fc10754098795f5fe2bd676a20f933192622f10455b7f55dff5ad5ae) (var 0)))))"
)


class NarrowingNoteRenderingTest(unittest.TestCase):
    """`[narrowing-legibility]` — §2.4 of the 2026-08-26 hole-elicitation plan.

    37-42 % of the banked arms' narrowing notes handed the model a raw Python
    `repr` of the type IR instead of its canonical surface. This is a
    rendering fix at `typecheck.py`'s error-text construction (what
    `narrowing_note` relays verbatim, per its own docstring) — not a
    rewording, so every assertion here is "no repr leaked", never a specific
    wording.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    def test_broken_type_note_renders_the_canonical_surface_not_a_repr(self):
        # BROKEN_TYPE = "(def Bool (lit i64 1))": a base-type mismatch,
        # I64 checked against declared Bool — the simplest instance of
        # typecheck.py's dominant `_fail` site (line ~243).
        funnel = run_funnel(BROKEN_TYPE, self.resolver)
        self.assertEqual(funnel.outcome, "typecheck")
        note = narrowing_note(funnel)
        self.assertNotRegex(note, _REPR_ARTEFACT)
        self.assertNotIn("[0, 1]", note)
        self.assertNotIn("[0, 2]", note)
        self.assertIn(type_to_surface([0, 1]), note)  # "Bool"
        self.assertIn(type_to_surface([0, 2]), note)  # "I64"

    def test_function_and_data_type_note_renders_both_as_surfaces(self):
        # A regression fixture drawn from a real banked note (see the module
        # constant's docstring): a `fn` type mismatched against a `data`
        # type whose bytes hash is exactly the artefact §2.4 names —
        # `b'?\xf2\x10G...'` in an encoding the model has never seen.
        funnel = run_funnel(_BANKED_TYPE_MISMATCH_SOURCE, self.resolver)
        self.assertEqual(funnel.outcome, "typecheck")
        note = narrowing_note(funnel)
        self.assertNotRegex(note, _REPR_ARTEFACT)
        self.assertNotIn("[2,", note)
        self.assertNotIn("b'", note)
        self.assertIn(
            "(data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64))",
            note)
        self.assertIn("(fn I64 () Bool)", note)

    def test_accepted_draws_carry_no_note_at_all(self):
        # `narrowing_note` returns "" on acceptance (evaluate.py's own
        # short-circuit) — confirms the rendering fix left that branch alone.
        self.assertEqual(narrowing_note(run_funnel(BOOL_NOT, self.resolver)), "")

    def test_banked_arms_replay_to_zero_repr_notes(self):
        """§2.4's quantification, replayed rather than asserted: reconstruct
        every rejected draw's `FunnelResult` from its banked `source` with
        today's (fixed) checker, rebuild its narrowing note, and confirm the
        banked-data repr fraction — 37-42 % before this fix, matching the
        plan's `--section blame` table exactly — is 0 % after it, on all
        three decomposition arms identically (this fix is deliberately not
        gated by any elicitation block).
        """
        total_rejected = 0
        total_raw = 0
        for arm in ("whole", "redraft", "holes"):
            path = HERE / "runs" / f"decomp-{arm}" / "records.jsonl"
            with path.open(encoding="utf-8") as handle:
                records = [json.loads(line) for line in handle]
            rejected = [
                r for r in records
                if r.get("role") != "candidate" and r.get("funnel_outcome") not in (None, ACCEPTED)]
            self.assertGreater(len(rejected), 0, arm)
            # The banked `error_message` is what `--section blame` counted to
            # get 37-42 % — reproduced here as the "before" figure.
            before = sum(1 for r in rejected if _REPR_ARTEFACT.search(r.get("error_message") or ""))
            self.assertGreater(before / len(rejected), 0.30, f"{arm}: banked repr fraction moved")
            for record in rejected:
                funnel = run_funnel(record["source"], self.resolver)
                # The fix touches only rendering; the funnel's classification
                # of each banked draw must reproduce exactly.
                self.assertEqual(funnel.outcome, record["funnel_outcome"], (arm, record.get("draw")))
                note = narrowing_note(funnel)
                if _REPR_ARTEFACT.search(note):
                    total_raw += 1
                total_rejected += 1
        self.assertEqual(total_raw, 0, "every arm must move identically, to exactly 0 raw-IR notes")
        self.assertGreater(total_rejected, 2000, "sanity: all three banked arms were replayed")


if __name__ == "__main__":
    unittest.main()
