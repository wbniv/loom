"""Tests for the bootstrap corpus seed set and its recorded expressiveness limits.

The second half of this file pins what the bootstrap plan's tranche ordering
rests on: what Loom v0.1 can and cannot express. Each claim is asserted here so
that a later change to the calculus that lifts a limit fails loudly and the plan
gets revisited, rather than the limit quietly outliving the reason for it. All
three original limits have now been lifted that way — two by the
polymorphism-and-Bool-elimination plan, the third by the measure-selection plan
(recursion is typed and its measure can name a non-initial argument, §2.5) —
and each lifted-limit test was replaced by one pinning the new capability plus
the narrower residue the new rule leaves in place.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

import corpus_registry
import obligations
import refinements
import typecheck as matches
import references
import scope
from corpus_registry import MANIFEST, OUTCOMES, TIERS, VERDICTS
from declarations import declaration_hash
from transcode import def_to_surface, parse_source, transcode_source

I64 = [0, 2]
BOOL = [0, 1]


class CorpusDeclarationTest(unittest.TestCase):
    def test_nominal_keys_are_reproducible_and_prefixed_apart_from_builtins(self):
        for name in corpus_registry.HASHES:
            expected = hashlib.sha256(f"loom:v0.1:corpus:{name}".encode("ascii")).digest()
            self.assertEqual(corpus_registry.declaration(name)[1], expected)
        import prelude

        self.assertFalse(set(corpus_registry.HASHES.values()) & set(prelude.HASHES.values()))

    def test_declarations_register_under_their_pinned_hashes(self):
        registry = corpus_registry.registry()
        for name, digest in corpus_registry.HASHES.items():
            self.assertEqual(declaration_hash(corpus_registry.declaration(name)), digest)
            self.assertEqual(registry.data(digest).parameter_count, corpus_registry.declaration(name)[2])

    def test_recursive_list_declaration_uses_declaration_local_self(self):
        # Cons carries (a, List a); the tail is the §5.1.1 `self` form, never a
        # not-yet-computable hash of the declaration being hashed.
        list_declaration = corpus_registry.declaration("List")
        self.assertEqual(list_declaration[3][1], [[5, 0], [7, [[5, 0]]]])

    def test_constructor_names_cover_every_declared_constructor(self):
        for name, names in corpus_registry.CONSTRUCTOR_NAMES.items():
            self.assertEqual(len(names), len(corpus_registry.declaration(name)[3]))


class CorpusFixtureTest(unittest.TestCase):
    def setUp(self):
        self.registry = corpus_registry.registry()

    def test_manifest_and_directory_agree(self):
        on_disk = sorted(path.name for path in corpus_registry.CORPUS_DIR.glob("*.loom.sexpr"))
        self.assertEqual(sorted(entry.fixture for entry in MANIFEST), on_disk)

    def test_every_fixture_is_canonical_and_keeps_its_pinned_identity(self):
        for entry in MANIFEST:
            with self.subTest(fixture=entry.fixture):
                source = entry.source_text()
                ir, encoded, digest = transcode_source(source)
                self.assertEqual(def_to_surface(ir) + "\n", source)
                self.assertEqual(parse_source(def_to_surface(ir)), ir)
                self.assertEqual(digest, entry.identity)
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), entry.identity)

    def test_every_fixture_reaches_its_declared_validation_tier(self):
        for entry in MANIFEST:
            with self.subTest(fixture=entry.fixture):
                self.assertIn(entry.tier, TIERS)
                source = entry.source_text()
                scope.validate_source(source, self.registry.operation_arity)
                references.validate_source(source, self.registry)
                resolver = corpus_registry.reference_type(self.registry)
                if entry.tier == "checked":
                    self.assertEqual(entry.deferred, "")
                    matches.validate_source(source, self.registry, resolver)
                else:
                    self.assertNotEqual(entry.deferred, "", "a structural entry must record why")
                    with self.assertRaises(matches.TypingError):
                        matches.validate_source(source, self.registry, resolver)

    @staticmethod
    def _type_effects(definition_type):
        """Every nonempty effect row and every `cap` ability in a definition type.

        The definition *type* is the whole audit surface (§2.4: "the row is the
        static audit surface; the capability is the dynamic blast-radius
        bound"). Scanning it is not a weaker check than scanning the term: a
        capability is unforgeable and no term node constructs one, so the only
        way a `cap a` reaches a closed definition's environment is through its
        type — and `perform` needs one (§3.1.2). A definition whose type carries
        no row and no `cap` therefore cannot perform anything, `handle` or no
        `handle`.
        """
        rows: list[list] = []
        caps: list[bytes] = []

        def walk(node):
            if not isinstance(node, list) or not node:
                return
            if node[0] == 2 and len(node) == 4:
                if node[2]:
                    rows.append(node[2])
            if node[0] == 4 and len(node) == 2:
                caps.append(node[1])
            for child in node:
                walk(child)

        walk(definition_type)
        return rows, caps

    def test_every_effect_free_fixture_is_pure_and_capability_free(self):
        # Tranches 1 and 2 are arithmetic-free and ability-free by construction
        # (plan R5), and the empty row on every arrow is what makes that
        # checkable rather than merely intended. Tranche 3 declares itself
        # effectful in the manifest instead of being exempted from this test:
        # `effect_free` is data on the entry and the test below asserts the
        # other direction, so the flag cannot be flipped to silence a failure.
        for entry in MANIFEST:
            if not entry.effect_free:
                continue
            with self.subTest(fixture=entry.fixture):
                rows, caps = self._type_effects(parse_source(entry.source_text())[1])
                self.assertEqual(rows, [], f"{entry.name_path}: nonempty effect row")
                self.assertEqual(caps, [], f"{entry.name_path}: carries a capability value")

    def test_every_effectful_fixture_carries_the_effects_it_declares(self):
        # The other direction, so `effect_free=False` is a claim rather than an
        # exemption: an entry declaring itself effectful must actually mention
        # an ability — in a row, a capability, or both.
        for entry in MANIFEST:
            if entry.effect_free:
                continue
            with self.subTest(fixture=entry.fixture):
                rows, caps = self._type_effects(parse_source(entry.source_text())[1])
                self.assertTrue(rows or caps,
                                f"{entry.name_path}: declared effectful but its type names no ability")

    def test_every_fixture_row_is_closed_and_names_only_builtin_abilities(self):
        # R2's dropped feature, asserted: Unison's ability-polymorphic `{g}` has
        # no checkable form here, so no row may end in a row variable
        # (`typecheck._closed_row` refuses one) and every ability named by a row
        # or a capability is one of §2.4's eight builtins.
        import prelude

        builtins = set(prelude.HASHES.values())
        for entry in MANIFEST:
            with self.subTest(fixture=entry.fixture):
                rows, caps = self._type_effects(parse_source(entry.source_text())[1])
                for row in rows:
                    for item in row:
                        self.assertIsInstance(item, bytes, f"{entry.name_path}: row variable in a row")
                        self.assertIn(item, builtins, f"{entry.name_path}: row names a non-builtin ability")
                        self.assertEqual(row, sorted(row), f"{entry.name_path}: row is not sorted bytewise")
                for ability in caps:
                    self.assertIn(ability, builtins, f"{entry.name_path}: cap of a non-builtin ability")

    def test_few_shot_pairs_carry_spec_text_and_canonical_surface(self):
        pairs = corpus_registry.few_shot_pairs()
        self.assertEqual(len(pairs), len(MANIFEST))
        for (spec, surface), entry in zip(pairs, MANIFEST):
            self.assertEqual(spec, entry.spec)
            self.assertTrue(surface.startswith("(def "))
            self.assertFalse(surface.endswith("\n"))
            parse_source(surface)

    def test_external_fixture_provenance_names_repository_and_license(self):
        for entry in MANIFEST:
            with self.subTest(fixture=entry.fixture):
                if entry.source.startswith("Unison"):
                    self.assertIn("unisonweb/unison", entry.source)
                    self.assertIn("MIT", entry.source)
                if entry.source.startswith("F*"):
                    self.assertIn("FStarLang/FStar", entry.source)
                    self.assertIn("Apache-2.0", entry.source)
                    self.assertRegex(entry.source, r"\bFStar\.[A-Za-z.]+|\bPrims\b")

    def test_manifest_declares_dependencies_before_use(self):
        # The store has no forward references, so no entry may name a later
        # entry's identity. Nothing in tranche 1 uses `ref` at all, which is the
        # strongest form of that property and is asserted directly.
        seen: set[str] = set()
        for entry in MANIFEST:
            hashes = set()

            def collect(node):
                if isinstance(node, bytes):
                    hashes.add(node.hex())
                elif isinstance(node, list):
                    for child in node:
                        collect(child)

            collect(parse_source(entry.source_text()))
            self.assertFalse(hashes & {e.identity for e in MANIFEST if e.identity not in seen},
                             f"{entry.name_path} names a definition not yet in the store")
            seen.add(entry.identity)


def _has_refinement(node) -> bool:
    if isinstance(node, list):
        if node and node[0] == 3 and len(node) == 3 and isinstance(node[1], list):
            return True
        return any(_has_refinement(child) for child in node)
    return False


def _refinement_predicates(node, found=None) -> list:
    """Every `φ` occurring as the predicate of a `refine T φ` node in a type."""
    found = [] if found is None else found
    if isinstance(node, list):
        if node and node[0] == 3 and len(node) == 3 and isinstance(node[1], list):
            found.append(node[2])
        for child in node:
            _refinement_predicates(child, found)
    return found


class CorpusObligationTest(unittest.TestCase):
    """The §3.2.1 verification conditions tranche 4's `ensures` claims produce.

    Absent a solver in the loop, "exercised end to end" means exactly this: the
    obligation's canonical solver input exists, is deterministic, and is pinned
    by content hash, so a change anywhere in the translator, the interpretation
    table, or a fixture's predicate moves a hash and fails here.
    """

    def setUp(self):
        self.registry = corpus_registry.registry()

    def test_every_obligation_reproduces_its_pinned_script_hash(self):
        pinned = [(entry, obligation) for entry in MANIFEST for obligation in entry.obligations]
        self.assertTrue(pinned, "tranche 4 onwards, the manifest carries obligations")
        for entry, obligation in pinned:
            with self.subTest(fixture=entry.fixture, obligation=obligation.name):
                script = obligation.script(self.registry)
                self.assertEqual(refinements.script_hash(script), obligation.script_hash)
                # Determinism, not merely stability: a second translation of the
                # same verification condition is the same bytes (§3.2.1, §4.2).
                self.assertEqual(obligation.script(self.registry), script)
                self.assertTrue(script.endswith("(check-sat)\n(exit)\n"))
                self.assertTrue(script.startswith("(set-logic ALL)\n"))

    def test_refinements_and_obligations_imply_each_other(self):
        # Both directions, like `tier` and `effect_free`: a `refine` in a
        # definition's type may not enter the corpus without an obligation, and
        # an obligation may not be attached to a fixture that claims none.
        for entry in MANIFEST:
            with self.subTest(fixture=entry.fixture):
                refined = _has_refinement(parse_source(entry.source_text())[1])
                self.assertEqual(refined, bool(entry.obligations),
                                 f"{entry.name_path}: refinement/obligation mismatch")

    def test_every_obligation_predicate_is_inside_the_decidable_fragment(self):
        # §3.2: nothing is ever silently unverified — but equally, nothing is
        # pinned that the translator would refuse. Both halves of every
        # subtyping pair are translated on their own, over the obligation's own
        # context — §3.2.1's `Γ = [T] ++ outer`, which is what lets a predicate
        # reach a surrounding binder without a dependent arrow.
        for entry in MANIFEST:
            for obligation in entry.obligations:
                context = [obligation.base, *obligation.outer_context]
                for label, predicate in (("weaker", obligation.weaker), ("stronger", obligation.stronger)):
                    with self.subTest(fixture=entry.fixture, obligation=obligation.name, half=label):
                        refinements.obligation_script(
                            context, [], predicate, self.registry,
                            corpus_registry.SMT_SIGNATURES, corpus_registry.SMT_INTERPRETATION)

    def test_every_verdict_is_declared_and_a_sat_says_why(self):
        # `verdict` is the raw solver answer and stays a fact. The other
        # direction on it: a `sat` is never a shrug, so it must record which
        # fact the verification condition could not carry — whether that fact
        # makes the model an artifact (undischarged) or not (refuted).
        for entry in MANIFEST:
            for obligation in entry.obligations:
                with self.subTest(fixture=entry.fixture, obligation=obligation.name):
                    self.assertIn(obligation.verdict, VERDICTS)
                    self.assertIn(obligation.outcome, OUTCOMES)
                    self.assertIn(obligation.producer, obligations.PRODUCERS)
                    if obligation.verdict == "sat":
                        self.assertNotEqual(obligation.note, "",
                                            "a sat obligation must record what is missing")

    def test_pinned_outcomes_are_what_the_rule_derives(self):
        # §3.2.1's three-way outcome, recomputed from a freshly emitted script
        # rather than trusted: the manifest may not pin an outcome the rule does
        # not produce, and may not silence one it does.
        for entry in MANIFEST:
            for obligation in entry.obligations:
                with self.subTest(fixture=entry.fixture, obligation=obligation.name):
                    emitted = obligation.emit(self.registry)
                    self.assertEqual(emitted.script_hash, obligation.script_hash)
                    self.assertEqual(emitted.script, obligation.script(self.registry))
                    self.assertEqual(emitted.outcome(obligation.verdict), obligation.outcome)

    def test_producer_agrees_with_the_fixtures_own_refinement_predicates(self):
        # Both directions on `producer`, derived rather than trusted. §3.2.1's
        # one specified producer is refinement subtyping, and a subtyping pair
        # is exactly a pair of predicates that both occur on `refine` nodes in
        # the definition's own type. A hand-authored body summary never does —
        # so the manifest cannot relabel one to buy itself a refutation.
        for entry in MANIFEST:
            predicates = _refinement_predicates(parse_source(entry.source_text())[1])
            for obligation in entry.obligations:
                with self.subTest(fixture=entry.fixture, obligation=obligation.name):
                    from_type = (obligation.weaker in predicates
                                 and obligation.stronger in predicates)
                    self.assertEqual(
                        from_type, obligation.producer == obligations.PRODUCER_SUBTYPING,
                        f"{entry.name_path}: producer/refinement-predicate mismatch")

    def test_no_sat_obligation_is_refuted_and_the_exact_one_is_named(self):
        # The whole point of the three-way rule: every `sat` in this corpus is a
        # true claim, so none may come out `refuted`. The second half is the
        # finding that must not be smoothed — corpus/nat/select's script *is*
        # translation-exact, and only generator faithfulness saves it, because
        # its Γ drops refinements the definition's type carries.
        translation_exact = set()
        for entry in MANIFEST:
            for obligation in entry.obligations:
                emitted = obligation.emit(self.registry)
                if obligation.verdict == "sat":
                    self.assertEqual(obligation.outcome, obligations.OUTCOME_UNDISCHARGED,
                                     f"{entry.name_path}: a true claim was refuted")
                if emitted.exactness.translation_faithful:
                    translation_exact.add((entry.name_path, obligation.verdict))
        self.assertIn(("corpus/nat/select", "sat"), translation_exact,
                      "corpus/nat/select's sat is translation-exact; if that stopped "
                      "being true the recorded finding needs revisiting")

    def test_one_verification_condition_is_one_memo_ledger_row(self):
        # §3.2.1: "the obligation's name never enters the script, so two
        # differently named obligations with the same verification condition
        # share one memo-ledger row (§6.4)". The manifest carries such a pair on
        # purpose, so the property is exercised rather than asserted in prose.
        by_hash: dict[str, set[str]] = {}
        for entry in MANIFEST:
            for obligation in entry.obligations:
                by_hash.setdefault(obligation.script_hash, set()).add(obligation.name)
        shared = {digest: names for digest, names in by_hash.items() if len(names) > 1}
        self.assertTrue(shared, "the corpus keeps a differently-named same-VC pair")
        for digest, names in shared.items():
            scripts = {obligation.script(self.registry)
                       for entry in MANIFEST for obligation in entry.obligations
                       if obligation.script_hash == digest}
            self.assertEqual(len(scripts), 1, f"{sorted(names)} disagree on bytes")

    def test_refinement_erasure_makes_a_refined_element_list_one_sort(self):
        # §3.2.1's "recursively, including inside data type arguments", as a
        # property rather than a reading: `List {n | -1 < n}` and `List I64` are
        # the same monomorphized sort, which is why the element predicate of
        # corpus/list/consNat contributes no hypothesis to its obligation.
        translator = refinements.ObligationTranslator(
            self.registry, corpus_registry.SMT_SIGNATURES, corpus_registry.SMT_INTERPRETATION)
        refined = translator.sort(corpus_registry._LIST_NAT, "refined")
        plain = translator.sort(corpus_registry._LIST_I64, "plain")
        self.assertEqual(refined, plain)

    def test_solver_verdicts_match_when_a_solver_is_available(self):
        solver = os.environ.get("LOOM_SMT_SOLVER") or shutil.which("z3")
        if not solver:
            self.skipTest("no SMT solver on PATH; set LOOM_SMT_SOLVER to run this check")
        for entry in MANIFEST:
            for obligation in entry.obligations:
                with self.subTest(fixture=entry.fixture, obligation=obligation.name):
                    with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False) as handle:
                        handle.write(obligation.script(self.registry))
                        path = handle.name
                    try:
                        completed = subprocess.run([solver, path], capture_output=True, text=True, timeout=60)
                    finally:
                        os.unlink(path)
                    self.assertEqual(completed.stdout.strip(), obligation.verdict)


class ExpressivenessLimitTest(unittest.TestCase):
    """What the tranche ordering depends on. Each failure means revisit the plan."""

    def setUp(self):
        self.registry = corpus_registry.registry()
        self.maybe = corpus_registry.HASHES["Maybe"]
        self.list = corpus_registry.HASHES["List"]

    def test_a_polymorphic_definition_is_written_at_its_forall_depth(self):
        # Lifted limit (§3.1.3): a definition typed `forall^p` is the type
        # abstraction itself, so its term is checked at type depth p and a `lam`
        # annotation may name the bound variable. Was `..._is_unwritable`.
        maybe_a = [1, self.maybe, [[5, 0]]]
        list_a = [1, self.list, [[5, 0]]]
        polymorphic_head = [
            0,
            [6, [2, list_a, [], maybe_a]],
            [3, list_a, [7, [0, 0], [[0, 0, [6, self.maybe, 0, []]],
                                     [1, 2, [6, self.maybe, 1, [[0, 1]]]]]]],
        ]
        source = def_to_surface(polymorphic_head)
        self.assertEqual(parse_source(source), polymorphic_head)
        scope.check_definition(polymorphic_head, self.registry.operation_arity)
        matches.validate_source(source, self.registry)

    def test_the_forall_prefix_bounds_type_variables_and_must_be_prenex(self):
        # The residue of the lifted limit. Depth p is exactly the prefix length,
        # and the prefix must be prenex for p to be well defined at all.
        beyond_prefix = [0, [6, [2, [5, 0], [], [5, 0]]], [3, [5, 1], [0, 0]]]
        with self.assertRaises(scope.ScopeError) as caught:
            scope.check_definition(beyond_prefix, self.registry.operation_arity)
        self.assertIn("type index 1 is out of scope at depth 1", str(caught.exception))

        rank_two = [0, [2, I64, [], [6, [2, [5, 0], [], [5, 0]]]], [3, I64, [11, I64, []]]]
        with self.assertRaises(scope.ScopeError) as caught:
            scope.check_definition(rank_two, self.registry.operation_arity)
        self.assertIn("must be prenex", str(caught.exception))

    def test_bool_is_eliminated_by_if_and_is_still_not_nominal(self):
        # Lifted limit (§3.1.4): `if` is the elimination form for Bool. Bool did
        # not become nominal, so `match` on a Bool scrutinee still fails exactly
        # as before. Was `test_bool_has_no_elimination_form`.
        branch_with_if = [0, [2, BOOL, [], I64],
                          [3, BOOL, [12, [0, 0], [2, 2, 1], [2, 2, 0]]]]
        matches.validate_source(def_to_surface(branch_with_if), self.registry)

        match_on_bool = [0, [2, BOOL, [], I64],
                         [3, BOOL, [7, [0, 0], [[0, 0, [2, 2, 1]], [1, 0, [2, 2, 0]]]]]]
        scope.check_definition(match_on_bool, self.registry.operation_arity)
        with self.assertRaises(matches.TypingError) as caught:
            matches.validate_source(def_to_surface(match_on_bool), self.registry)
        self.assertIn("match scrutinee does not synthesize a nominal data type", str(caught.exception))

    def test_a_recursive_definition_reaches_the_checked_tier(self):
        # The third recorded limit is lifted, and this is what replaced it:
        # `fix` selects its decreasing argument (§2.5), and the corpus resolver
        # resolves the assumed-base List.size, so a recursive tranche-2 shape
        # typechecks. `list/append` descends on its first argument (position 0).
        # rec=2, xs=1, ys=0 under the two lambdas; in the Cons arm the tail is 0,
        # the head 1, and everything else shifts by two (§2.3.1).
        list_i64 = [1, self.list, [I64]]
        append_type = [2, list_i64, [], [2, list_i64, [], list_i64]]
        append_body = [3, list_i64, [3, list_i64, [7, [0, 1], [
            [0, 0, [0, 0]],
            [1, 2, [6, self.list, 1, [[0, 1], [4, [4, [0, 4], [0, 0]], [0, 2]]]]],
        ]]]]
        size = corpus_registry.EXTERN_HASHES["List.size"]
        append = [0, append_type, [10, append_type, 0, [1, size], append_body]]
        source = def_to_surface(append)
        self.assertEqual(parse_source(source), append)
        scope.validate_source(source, self.registry.operation_arity)
        references.validate_source(source, self.registry)
        matches.validate_source(source, self.registry, corpus_registry.reference_type(self.registry))

    def test_a_term_meets_a_refine_type_only_by_structural_equality(self):
        # Tranche 4's limit (SPEC.md §3.3): refinement subtyping is specified
        # and its verification condition is generated (`refinements.py`), but
        # the type-directed layer implements no subsumption rule, so `{x|0<x}`
        # does not flow into `{x|-1<x}` and no plain `I64` inhabits either.
        # Lifting this must turn three tranche-4 entries from `structural` to
        # `checked`, so the plan gets revisited rather than the tier going stale.
        lt = corpus_registry.EXTERN_HASHES["I64.lt"]
        nat = [3, I64, [4, [4, [1, lt], [2, 2, -1]], [0, 0]]]
        pos = [3, I64, [4, [4, [1, lt], [2, 2, 0]], [0, 0]]]
        widen = [0, [2, pos, [], nat], [3, pos, [0, 0]]]
        forget = [0, [2, nat, [], I64], [3, nat, [0, 0]]]
        resolver = corpus_registry.reference_type(self.registry)
        for label, definition in (("widening", widen), ("erasure", forget)):
            source = def_to_surface(definition)
            self.assertEqual(parse_source(source), definition)
            scope.validate_source(source, self.registry.operation_arity)
            with self.subTest(label), self.assertRaises(matches.TypingError) as caught:
                matches.validate_source(source, self.registry, resolver)
            self.assertIn("type mismatch", str(caught.exception))

        # Reflexively, a refinement does flow — which is what keeps the other
        # three tranche-4 entries at tier `checked`.
        identity = [0, [2, nat, [], nat], [3, nat, [0, 0]]]
        matches.validate_source(def_to_surface(identity), self.registry, resolver)

    def test_a_measure_cannot_read_more_than_one_argument(self):
        # The limit measure selection does *not* lift: one measure over one
        # argument. `merge` on two sorted lists needs `size xs + size ys` —
        # neither argument decreases alone — so it must take `div` in v0.1, and
        # no choice of position makes it statable.
        list_i64 = [1, self.list, [I64]]
        merge_type = [2, list_i64, [], [2, list_i64, [], list_i64]]
        size = corpus_registry.EXTERN_HASHES["List.size"]
        # A measure reading both arguments has the spine `List -> List -> I64`,
        # which is not `fn D_k () I64` at either position.
        both = [3, list_i64, [3, list_i64, [4, [1, size], [0, 0]]]]
        body = [3, list_i64, [3, list_i64, [0, 1]]]
        resolver = corpus_registry.reference_type(self.registry)
        for position in (0, 1):
            merge = [0, merge_type, [10, merge_type, position, both, body]]
            with self.subTest(position=position), self.assertRaises(matches.TypingError) as caught:
                matches.validate_source(def_to_surface(merge), self.registry, resolver)
            self.assertIn("type mismatch", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
