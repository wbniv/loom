"""Tests for the bootstrap corpus seed set and its recorded expressiveness limits.

The second half of this file pins what the bootstrap plan's tranche ordering
rests on: what Loom v0.1 can and cannot express. Each claim is asserted here so
that a later change to the calculus that lifts a limit fails loudly and the plan
gets revisited, rather than the limit quietly outliving the reason for it. That
is exactly what happened to the third limit — recursion is now typed and its
measure can name a non-initial argument (§2.5), so the test that pinned the limit
was replaced by one that pins the capability, alongside the narrower limit the
new rule leaves in place.
"""

from __future__ import annotations

import hashlib
import unittest

import corpus_registry
import matches
import references
import scope
from corpus_registry import MANIFEST, TIERS
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
                    with self.assertRaises(matches.TypeDirectionError):
                        matches.validate_source(source, self.registry, resolver)

    def test_every_fixture_is_pure_and_capability_free(self):
        # Nothing in the seed set may smuggle in an effect: the tranche is
        # arithmetic-free and ability-free by construction (plan R5), and the
        # empty row on every arrow is what makes that checkable rather than
        # merely intended.
        def assert_pure(node, path):
            if not isinstance(node, list) or not node:
                return
            if node[0] == 2 and len(node) == 4:
                self.assertEqual(node[2], [], f"{path}: nonempty effect row")
            if node[0] == 4 and len(node) == 2:
                self.fail(f"{path}: seed definitions carry no capability values")
            for index, child in enumerate(node):
                assert_pure(child, f"{path}[{index}]")

        for entry in MANIFEST:
            with self.subTest(fixture=entry.fixture):
                assert_pure(parse_source(entry.source_text())[1], entry.name_path)

    def test_few_shot_pairs_carry_spec_text_and_canonical_surface(self):
        pairs = corpus_registry.few_shot_pairs()
        self.assertEqual(len(pairs), len(MANIFEST))
        for (spec, surface), entry in zip(pairs, MANIFEST):
            self.assertEqual(spec, entry.spec)
            self.assertTrue(surface.startswith("(def "))
            self.assertFalse(surface.endswith("\n"))
            parse_source(surface)

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


class ExpressivenessLimitTest(unittest.TestCase):
    """Limits the tranche ordering depends on. Each failure means revisit the plan."""

    def setUp(self):
        self.registry = corpus_registry.registry()
        self.maybe = corpus_registry.HASHES["Maybe"]
        self.list = corpus_registry.HASHES["List"]

    def test_a_polymorphic_definition_is_unwritable(self):
        # `forall` binds only inside the type (§2.3.1), and there is no
        # term-level type abstraction, so a `lam` annotation can never name the
        # bound type variable. This is why the whole seed set is monomorphic.
        maybe_a = [1, self.maybe, [[5, 0]]]
        list_a = [1, self.list, [[5, 0]]]
        polymorphic_head = [
            0,
            [6, [2, list_a, [], maybe_a]],
            [3, list_a, [7, [0, 0], [[0, 0, [6, self.maybe, 0, []]],
                                     [1, 2, [6, self.maybe, 1, [[0, 1]]]]]]],
        ]
        parse_source(def_to_surface(polymorphic_head))  # the surface is well-formed
        with self.assertRaises(scope.ScopeError) as caught:
            scope.check_definition(polymorphic_head, self.registry.operation_arity)
        self.assertIn("type index 0 is out of scope at depth 0", str(caught.exception))

    def test_bool_has_no_elimination_form(self):
        # §3.1.1 requires a match scrutinee to synthesize a nominal data type,
        # and Bool is a base type (§2.2). There is no conditional, so every
        # branch-on-Bool function is out of tranche 1.
        branch_on_bool = [0, [2, BOOL, [], I64],
                          [3, BOOL, [7, [0, 0], [[0, 0, [2, 2, 1]], [1, 0, [2, 2, 0]]]]]]
        scope.check_definition(branch_on_bool, self.registry.operation_arity)
        with self.assertRaises(matches.TypeDirectionError) as caught:
            matches.validate_source(def_to_surface(branch_on_bool), self.registry)
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
            with self.subTest(position=position), self.assertRaises(matches.TypeDirectionError) as caught:
                matches.validate_source(def_to_surface(merge), self.registry, resolver)
            self.assertIn("type mismatch", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
