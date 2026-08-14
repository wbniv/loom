"""Phase B B1: the mask, tested with no model at all.

The critical property is R4's, and it gets the most space here: **the mask never
excludes a valid continuation**. `MaskSoundnessTest` walks every corpus fixture
token by token under four different tokenizations — including one that emits a
token per byte and two that deliberately straddle grammar atoms — and asserts
that the fixture's own next token is in the mask at every single step. An
unsound mask silently corrupts the experiment, so the suite is written to catch
it rather than to demonstrate that the mask prunes.

That it *does* prune is the second half: `PrunerTest` holds the targeted
probes where each layer claims a proof, and `ConditionFourTest` runs the whole
condition end to end on the stub and then switches each pruner off to show the
run diverging into exactly the failure that pruner exists to prevent.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import corpus_registry
from experiment import runner
from experiment.backends import (
    DECOY_HASH,
    DECOY_INDEX,
    DECOY_SYNTAX,
    NO_MASK_BACKEND_MESSAGE,
    BackendUnavailable,
    LlamaCppBackend,
    StubBackend,
    make_backend,
    scripted_vocabulary,
    select_token,
)
from experiment.evaluate import ACCEPTED, run_funnel
from experiment.gbnf import Grammar, GrammarError, loom_grammar
from experiment.masker import (
    PRUNABLE,
    PRUNER_NAMES,
    DeBruijnPruner,
    Masker,
    ReferenceHashPruner,
    StaticVocabulary,
    TypeState,
    build_masker,
)
from experiment.resolver import ExperimentResolver

HERE = Path(__file__).resolve().parent

SURFACES = tuple(
    entry.source_text().rstrip("\n") for entry in corpus_registry.MANIFEST)
NAMES = tuple(entry.name_path for entry in corpus_registry.MANIFEST)

#: A definition with no hash in it — the de Bruijn probes' target.
BOOL_NOT = (HERE / "corpus" / "bool_not.loom.sexpr").read_text(encoding="utf-8").strip()
#: A definition that *does* carry hashes — the reference pruner's target.
HASHED = (HERE / "corpus" / "maybe_is_nothing_i64.loom.sexpr").read_text(
    encoding="utf-8").strip()


def chunk(data: bytes, size: int):
    return [data[i:i + size] for i in range(0, len(data), size)]


def greedy(data: bytes, vocabulary, longest=8):
    """Longest-match tokenization — the shape a BPE vocabulary produces."""
    pieces, index = [], 0
    while index < len(data):
        for length in range(min(longest, len(data) - index), 0, -1):
            if vocabulary.lookup(data[index:index + length]) is not None:
                pieces.append(data[index:index + length])
                index += length
                break
        else:  # pragma: no cover - the vocabulary contains every single byte
            raise AssertionError(f"no token covers {data[index:index + 4]!r}")
    return pieces


class GrammarTest(unittest.TestCase):
    """The syntax layer is a prefix oracle over `loom.gbnf`, read at run time."""

    @classmethod
    def setUpClass(cls):
        cls.grammar = loom_grammar()

    def test_every_corpus_fixture_is_accepted(self):
        for name, surface in zip(NAMES, SURFACES):
            with self.subTest(fixture=name):
                self.assertTrue(self.grammar.accepts(surface.encode("utf-8")))

    def test_forms_the_corpus_does_not_use_are_still_accepted(self):
        # The corpus has no text or f64 literal; the mask must still handle them,
        # so the grammar layer is exercised on them here rather than nowhere.
        for surface in (
            '(def Text (lit text "hi (there) \\"q\\""))',
            "(def F64 (lit f64 0x0000000000000000))",
            "(def Bytes (lit bytes 0x))",
            "(def Bytes (lit bytes 0xdeadbeef))",
            "(def Bool (lit unit))\n",
        ):
            with self.subTest(surface=surface):
                self.assertTrue(self.grammar.accepts(surface.encode("utf-8")))

    def test_noncanonical_and_truncated_surfaces_are_refused(self):
        for surface in (
            "(def  Bool (lit unit))",          # double space
            "(def Bool (lit i64 01))",         # leading zero
            "(def Bool (ref 0xABCD))",         # upper-case hex, wrong length
            "(def Bool (lit bool yes))",
            "(def Bool (var 0)",               # unbalanced
            "(def Bool (lit unit)) trailing",
        ):
            with self.subTest(surface=surface):
                self.assertFalse(self.grammar.accepts(surface.encode("utf-8")))

    def test_a_prefix_is_alive_and_incomplete(self):
        state = self.grammar.feed(self.grammar.initial, b"(def Bool (lit bool ")
        self.assertTrue(state)
        self.assertFalse(self.grammar.can_end(state))
        self.assertEqual(
            "".join(sorted(chr(byte) for byte in self.grammar.allowed_bytes(state))), "ft")

    def test_allowed_bytes_narrow_to_the_atom(self):
        after_hash = self.grammar.feed(self.grammar.initial, b"(def Bool (ref 0x")
        self.assertEqual(
            "".join(sorted(chr(b) for b in self.grammar.allowed_bytes(after_hash))),
            "0123456789abcdef")
        after_index = self.grammar.feed(self.grammar.initial, b"(def Bool (var ")
        self.assertEqual(
            "".join(sorted(chr(b) for b in self.grammar.allowed_bytes(after_index))),
            "0123456789")

    def test_a_dead_prefix_stays_dead(self):
        state = self.grammar.feed(self.grammar.initial, b"(dfe ")
        self.assertFalse(state)
        self.assertFalse(self.grammar.feed(state, b"Bool"))

    def test_repetition_and_group_sugar_compile(self):
        grammar = Grammar('root ::= "a" ("b" | "c")* "d"? [0-9]{2}')
        for good in (b"a12", b"abc34", b"abbd99", b"ad00"):
            self.assertTrue(grammar.accepts(good), good)
        for bad in (b"a1", b"a123", b"ab", b"adb12"):
            self.assertFalse(grammar.accepts(bad), bad)

    def test_a_broken_grammar_is_a_compile_error_not_a_match_error(self):
        with self.assertRaises(GrammarError):
            Grammar('root ::= missing')
        with self.assertRaises(GrammarError):
            Grammar('other ::= "a"')


class TypeStateTest(unittest.TestCase):
    """The scanner's depths must mirror `scope.py`, atom by atom."""

    def state(self, prefix: str) -> TypeState:
        return TypeState().feed(prefix.encode("utf-8"))

    def test_lambda_and_let_bind_one_each(self):
        self.assertEqual(self.state("(def (fn Bool () Bool) (lam Bool (").top.base_term, 1)
        self.assertEqual(
            self.state("(def Bool (let Bool (lit unit) (").top.base_term, 1)
        self.assertEqual(
            self.state("(def Bool (let Bool (").top.base_term, 0,
            "a let's bound term is checked before the binder exists")

    def test_match_arm_binds_its_own_declared_count(self):
        state = self.state("(def Bool (match (var 0) ((1 2 (")
        self.assertEqual(state.top.base_term, 2)
        state = self.state("(def Bool (match (var 0) ((0 0 (")
        self.assertEqual(state.top.base_term, 0)

    def test_forall_raises_the_type_depth_and_the_prenex_carries_to_the_term(self):
        self.assertEqual(self.state("(def (forall (forall (").top.base_type, 2)
        state = self.state("(def (forall (forall (tyvar 0))) (")
        self.assertEqual(state.prenex, 2)
        self.assertEqual(state.top.base_type, 2)

    def test_refine_and_hole_bind_one_in_their_sub_terms(self):
        self.assertEqual(self.state("(def (refine Bool (").top.base_term, 1)
        self.assertEqual(self.state("(def Bool (hole Bool ((").top.base_term, 1)

    def test_a_handler_operation_body_is_depth_unknown(self):
        state = self.state(
            "(def Bool (handle 0x" + "aa" * 32 + " (lit unit) ((0 (")
        self.assertTrue(state.depth_unknown)
        self.assertFalse(self.state("(def Bool (lam Bool (").depth_unknown)

    def test_atom_kinds_distinguish_a_hash_from_a_float_or_a_byte_string(self):
        self.assertEqual(self.state("(def Bool (ref ").atom_kind, "hash")
        self.assertEqual(self.state("(def (cap ").atom_kind, "hash")
        self.assertEqual(self.state("(def (fn Bool (").atom_kind, "row-elem")
        self.assertEqual(self.state("(def F64 (lit f64 ").atom_kind, "none")
        self.assertEqual(self.state("(def Bytes (lit bytes ").atom_kind, "none")
        self.assertEqual(self.state("(def Bool (var ").atom_kind, "uint:var")
        self.assertEqual(self.state("(def (tyvar ").atom_kind, "uint:tyvar")
        self.assertEqual(self.state("(def Bool (con 0x" + "ab" * 32 + " ").atom_kind,
                         "uint:free")

    def test_a_text_literal_does_not_confuse_the_frame_stack(self):
        state = self.state('(def Text (lit text "a (b) c"))')
        self.assertEqual(len(state.stack), 1)
        self.assertEqual(self.state('(def Text (lit text "a (b').atom_kind, "string")

    def test_every_corpus_fixture_scans_to_a_balanced_stack(self):
        for name, surface in zip(NAMES, SURFACES):
            with self.subTest(fixture=name):
                self.assertEqual(len(self.state(surface).stack), 1)

    def test_the_prunable_atom_kinds_are_the_ones_a_pruner_reads(self):
        self.assertEqual(
            PRUNABLE, frozenset({"hash", "row-elem", "uint:var", "uint:tyvar", "head"}))


class PrunerTest(unittest.TestCase):
    """Each pruner's proof, probed where it claims one and where it does not."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.hashes = ReferenceHashPruner(cls.resolver.digests())
        cls.indices = DeBruijnPruner()

    def veto(self, pruner, prefix: str, char: str) -> bool:
        return pruner.veto(TypeState().feed(prefix.encode("utf-8")), ord(char))

    # -- reference hashes ------------------------------------------------

    def test_a_hex_prefix_that_extends_no_known_digest_is_pruned(self):
        known = {digest.hex() for digest in self.resolver.digests()}
        self.assertFalse(any(digest.startswith("dead") for digest in known),
                         "the probe below assumes no digest starts with 'dead'")
        self.assertTrue(self.veto(self.hashes, "(def Bool (ref 0xdea", "d"))
        # ... and the first digit of a real digest is not.
        real = sorted(known)[0]
        self.assertFalse(self.veto(self.hashes, "(def Bool (ref 0x", real[0]))
        self.assertFalse(self.veto(self.hashes, f"(def Bool (ref 0x{real[:10]}", real[10]))

    def test_every_corpus_hash_survives_the_trie_digit_by_digit(self):
        for digest in self.resolver.digests():
            text = digest.hex()
            with self.subTest(digest=text[:12]):
                for index in range(len(text)):
                    prefix = f"(def Bool (ref 0x{text[:index]}"
                    self.assertFalse(self.veto(self.hashes, prefix, text[index]))

    def test_an_empty_row_is_not_a_truncated_hash(self):
        # `()` reaches the pruner as a hash-position atom that is empty. Vetoing
        # its `)` was a real unsoundness: every `(fn T () U)` in the corpus died.
        self.assertFalse(self.veto(self.hashes, "(def (fn Bool (", ")"))
        self.assertFalse(self.veto(self.hashes, "(def (fn Bool (", "("))

    def test_a_float_or_byte_literal_is_never_treated_as_a_hash(self):
        self.assertFalse(self.veto(self.hashes, "(def F64 (lit f64 0xdea", "d"))
        self.assertFalse(self.veto(self.hashes, "(def Bytes (lit bytes 0xdea", "d"))

    def test_a_complete_unknown_hash_is_refused_at_its_terminator(self):
        unknown = "(def Bool (ref 0x" + "ab" * 32
        self.assertTrue(self.veto(self.hashes, unknown, ")"))
        known = self.resolver.digest_for("corpus/bool/not").hex()
        self.assertFalse(self.veto(self.hashes, f"(def Bool (ref 0x{known}", ")"))

    # -- de Bruijn indices -----------------------------------------------

    def test_an_index_at_or_past_the_depth_is_pruned(self):
        one_binder = "(def (fn Bool () Bool) (lam Bool (var "
        self.assertFalse(self.veto(self.indices, one_binder, "0"))
        for digit in "123456789":
            self.assertTrue(self.veto(self.indices, one_binder, digit), digit)
        two_binders = "(def Bool (lam Bool (lam Bool (var "
        self.assertFalse(self.veto(self.indices, two_binders, "1"))
        self.assertTrue(self.veto(self.indices, two_binders, "2"))

    def test_a_partial_index_is_pruned_on_its_minimum_completion(self):
        # depth 12: `1` is fine, but `13`, `19` and anything longer are not.
        deep = "(def Bool " + "(lam Bool " * 12 + "(var "
        self.assertFalse(self.veto(self.indices, deep, "1"))
        self.assertFalse(self.veto(self.indices, deep + "1", "1"))
        self.assertTrue(self.veto(self.indices, deep + "1", "2"))
        self.assertTrue(self.veto(self.indices, deep + "1", "9"))

    def test_var_and_tyvar_are_the_only_heads_their_first_letter_can_reach(self):
        """The precondition the head-level veto needs, taken from `loom.gbnf`.

        Refusing the `v` after `(` is only sound while `var` is the *one* term
        head beginning with `v` — likewise `t` and `tyvar` in type position. The
        corpus walk would only catch a regression here if some fixture happened
        to use the new head, so the grammar is asked directly: from the position
        in question, take the unique continuation and see where it lands.
        """
        grammar = loom_grammar()

        def head_after(prefix: bytes, letter: bytes) -> bytes:
            state = grammar.feed(grammar.initial, prefix + letter)
            self.assertTrue(state, f"{prefix + letter!r} is not even a live prefix")
            head = bytearray(letter)
            while True:
                allowed = grammar.allowed_bytes(state)
                if 0x20 in allowed:
                    return bytes(head)
                self.assertEqual(
                    len(allowed), 1,
                    f"more than one head continues {bytes(head)!r}: "
                    f"{sorted(chr(byte) for byte in allowed)}")
                byte = next(iter(allowed))
                head.append(byte)
                state = grammar.step(state, byte)

        self.assertEqual(head_after(b"(def Bool (", b"v"), b"var")
        self.assertEqual(head_after(b"(def (", b"t"), b"tyvar")
        self.assertEqual(head_after(b"(def (fn Bool ((", b"t"), b"tyvar")

    def test_no_binder_in_scope_prunes_the_var_head_itself(self):
        self.assertTrue(self.veto(self.indices, "(def Bool (", "v"))
        self.assertFalse(self.veto(self.indices, "(def Bool (", "r"))
        self.assertFalse(self.veto(self.indices, "(def Bool (lam Bool (", "v"))

    def test_no_type_binder_in_scope_prunes_the_tyvar_head(self):
        self.assertTrue(self.veto(self.indices, "(def (", "t"))
        self.assertFalse(self.veto(self.indices, "(def (forall (", "t"))
        self.assertFalse(self.veto(self.indices, "(def (", "f"))

    def test_a_row_variable_is_bounded_by_the_type_depth(self):
        # `(fn T (` opens the row itself; the row *variable* is the `(` inside it.
        self.assertTrue(self.veto(self.indices, "(def (fn Bool ((", "t"))
        self.assertFalse(self.veto(self.indices, "(def (forall (fn Bool ((", "t"))
        self.assertFalse(self.veto(self.indices, "(def (forall (fn Bool ((tyvar ", "0"))
        self.assertTrue(self.veto(self.indices, "(def (forall (fn Bool ((tyvar ", "1"))

    def test_a_free_uint_is_never_bounded(self):
        prefix = "(def Bool (con 0x" + "ab" * 32 + " "
        for digit in "0123456789":
            self.assertFalse(self.veto(self.indices, prefix, digit))

    def test_the_pruner_abstains_where_the_depth_is_unknown(self):
        unknown = "(def Bool (handle 0x" + "aa" * 32 + " (lit unit) ((0 (var "
        for digit in "0123456789":
            self.assertFalse(self.veto(self.indices, unknown, digit))
        self.assertFalse(self.veto(self.indices, unknown[: -len("(var ")], "v"))


class MaskSoundnessTest(unittest.TestCase):
    """R4. The property the whole of Phase B rests on.

    Every corpus fixture, under four tokenizations, with the full mask stack
    active: the fixture's own next token is in the mask at every step, and the
    walk finishes on a grammar state that may end.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.vocabulary = scripted_vocabulary(SURFACES, max_piece=4)
        # One masker for the whole suite: its caches are the reason this is
        # affordable, and sharing them is exactly what a real run does.
        cls.masker = build_masker(cls.vocabulary, cls.resolver)

    def walk(self, surface: str, pieces, masker=None):
        masker = masker or self.masker
        masker.reset()
        for index, piece in enumerate(pieces):
            token = self.vocabulary.lookup(piece)
            self.assertIsNotNone(token, f"vocabulary gap at {piece!r}")
            step = masker.step()
            self.assertIn(
                token, step.allowed,
                f"MASK EXCLUDED A VALID CONTINUATION at token {index} ({piece!r})\n"
                f"  after   : {masker.text[-70:]!r}\n"
                f"  pruned  : {step.pruned}\n"
                f"  atom    : {masker.tstate.atom_kind} {masker.tstate.atom!r}")
            masker.accept_token(token)
        self.assertTrue(masker.can_end, "the fixture did not end on a complete state")

    def test_every_fixture_byte_by_byte(self):
        for name, surface in zip(NAMES, SURFACES):
            with self.subTest(fixture=name, tokenization="1 byte"):
                self.walk(surface, chunk(surface.encode("utf-8"), 1))

    def test_every_fixture_in_atom_straddling_chunks(self):
        for name, surface in zip(NAMES, SURFACES):
            with self.subTest(fixture=name, tokenization="3 bytes"):
                self.walk(surface, chunk(surface.encode("utf-8"), 3))

    def test_every_fixture_under_longest_match_tokenization(self):
        for name, surface in zip(NAMES, SURFACES):
            with self.subTest(fixture=name, tokenization="greedy"):
                self.walk(surface, greedy(surface.encode("utf-8"), self.vocabulary))

    def test_soundness_holds_for_every_pruner_subset(self):
        # Fewer pruners can only widen the mask, but the subsets are where a
        # toggle bug would hide, so they are walked rather than argued about.
        subsets = ([], ["ref-hash"], ["de-bruijn"], list(PRUNER_NAMES))
        for names in subsets:
            masker = build_masker(self.vocabulary, self.resolver, names=names)
            with self.subTest(pruners=tuple(names)):
                for surface in SURFACES[:3]:
                    self.walk(surface, greedy(surface.encode("utf-8"), self.vocabulary),
                              masker=masker)

    def test_no_fixture_walk_needed_a_liveness_fallback(self):
        self.assertEqual(
            self.masker.fallbacks, 0,
            "a fallback means the type layer emptied a mask it should not have")

    def test_the_mask_shrinks_hard_and_still_offers_something(self):
        self.masker.reset()
        self.masker.accept_bytes(b"(def Bool (ref 0x")
        step = self.masker.step()
        self.assertTrue(step.allowed)
        self.assertLess(step.size, len(self.vocabulary) // 10)
        self.assertGreater(step.pruned["ref-hash"], 0)


class MaskerApiTest(unittest.TestCase):
    """The R2/R3 surface: toggles, per-layer counters, timings, EOS."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.vocabulary = scripted_vocabulary(SURFACES, max_piece=4)

    def masker(self, names=PRUNER_NAMES):
        return build_masker(self.vocabulary, self.resolver, names=names)

    def test_each_pruner_is_individually_toggleable(self):
        masker = self.masker()
        self.assertEqual(masker.enabled_pruners, PRUNER_NAMES)
        masker.enable("de-bruijn", False)
        self.assertEqual(masker.enabled_pruners, ("ref-hash",))
        masker.enable("de-bruijn", True)
        self.assertEqual(masker.enabled_pruners, PRUNER_NAMES)
        with self.assertRaises(KeyError):
            masker.enable("nonesuch", False)

    def test_toggling_a_pruner_off_widens_the_mask_at_a_pruned_position(self):
        masker = self.masker()
        masker.accept_bytes(b"(def (fn Bool () Bool) (lam Bool (var ")
        tight = masker.step()
        masker.enable("de-bruijn", False)
        loose = masker.step()
        self.assertLess(tight.size, loose.size)
        self.assertTrue(set(tight.allowed) <= set(loose.allowed))

    def test_each_layer_is_individually_timed_and_counted(self):
        masker = self.masker()
        masker.accept_bytes(b"(def Bool (ref 0x")
        step = masker.step()
        self.assertEqual(set(step.seconds_by_layer), {"syntax", *PRUNER_NAMES})
        for layer, seconds in step.seconds_by_layer.items():
            self.assertGreaterEqual(seconds, 0.0, layer)
        self.assertGreater(step.seconds, 0.0)
        stats = masker.stats()
        self.assertEqual(set(stats["mask_pruned_by_layer"]), {"syntax", *PRUNER_NAMES})
        self.assertEqual(set(stats["mask_seconds_by_layer"]), {"syntax", *PRUNER_NAMES})
        self.assertEqual(set(stats["mask_calls_by_layer"]), {"syntax", *PRUNER_NAMES})
        self.assertGreater(stats["mask_seconds"], 0.0)
        self.assertEqual(stats["mask_vocab_size"], len(self.vocabulary))
        self.assertEqual(stats["mask_pruners_enabled"], list(PRUNER_NAMES))

    def test_eos_is_offered_exactly_when_the_definition_may_end(self):
        masker = self.masker()
        eos = min(self.vocabulary.eos_ids)
        masker.accept_bytes(BOOL_NOT.encode("utf-8")[:-1])
        self.assertNotIn(eos, masker.step().allowed)
        masker.accept_bytes(b")")
        step = masker.step()
        self.assertTrue(step.can_end)
        self.assertIn(eos, step.allowed)

    def test_a_syntactically_impossible_token_is_never_offered(self):
        masker = self.masker()
        decoy = self.vocabulary.lookup(DECOY_SYNTAX)
        self.assertIsNotNone(decoy)
        for prefix in (b"", b"(def ", b"(def Bool (ref 0x", b"(def Bool (var "):
            masker.reset()
            masker.accept_bytes(prefix)
            self.assertNotIn(decoy, masker.step().allowed, prefix)

    def test_each_pruner_removes_its_own_decoy_and_only_that(self):
        masker = self.masker()
        masker.accept_bytes(b"(def (fn Bool () Bool) (lam Bool (var ")
        index_decoy = self.vocabulary.lookup(DECOY_INDEX)
        self.assertNotIn(index_decoy, masker.step().allowed)
        masker.enable("de-bruijn", False)
        self.assertIn(index_decoy, masker.step().allowed)

        masker = self.masker()
        masker.accept_bytes(b"(def Bool (ref 0x")
        hash_decoy = self.vocabulary.lookup(DECOY_HASH)
        self.assertNotIn(hash_decoy, masker.step().allowed)
        masker.enable("ref-hash", False)
        self.assertIn(hash_decoy, masker.step().allowed)

    def test_the_cache_is_a_speedup_and_not_a_different_answer(self):
        cold = build_masker(self.vocabulary, self.resolver)
        warm = build_masker(self.vocabulary, self.resolver)
        prefix = b"(def (fn Bool () Bool) (lam Bool (if (var 0) "
        cold.accept_bytes(prefix)
        first = cold.step()
        second = cold.step()
        warm.accept_bytes(prefix)
        self.assertEqual(first.allowed, second.allowed)
        self.assertEqual(first.allowed, warm.step().allowed)
        self.assertGreater(cold.stats()["mask_cache_hits"], 0)

    def test_a_vocabulary_indexes_its_pieces_as_a_trie(self):
        vocabulary = StaticVocabulary([b"a", b"ab", b"abc", b"b", b"<eos>"], eos_ids={4})
        self.assertEqual(len(vocabulary), 5)
        self.assertEqual(vocabulary.lookup(b"ab"), 1)
        self.assertIsNone(vocabulary.lookup(b"zz"))
        self.assertEqual(vocabulary.subtree_size[0], 4)
        self.assertEqual(vocabulary.trie_nodes, 5)

    def test_select_token_is_argmax_over_the_mask_at_temperature_zero(self):
        logits = [0.0, 9.0, 5.0, 5.0]
        self.assertEqual(select_token((0, 2, 3), logits, 0.0, None), 2)
        self.assertEqual(select_token((0, 2), logits, 0.0, None), 2)
        with self.assertRaises(ValueError):
            select_token((), logits, 0.0, None)


class ConditionFourTest(unittest.TestCase):
    """Condition 4 end to end on the stub: config, records, report, toggles."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()

    @staticmethod
    def config(**overrides):
        config = runner.Config(
            backend="stub",
            seeds=[1],
            conditions=[runner.CONDITION_TYPEMASK],
            regimes=["few_shot"],
            tasks=["corpus/bool/not"],
            token_budget_per_task=200,
            max_tokens_per_draw=200,
            max_draws_per_task=3,
            stub_outputs=[BOOL_NOT],
            stub_grammar_outputs=[BOOL_NOT],
            stub_masked_outputs=[BOOL_NOT],
            source_path="<test>",
        )
        for key, value in overrides.items():
            setattr(config, key, value)
        config.validate()
        return config

    def run_condition_four(self, **overrides):
        config = self.config(**overrides)
        return config, *runner.run(config, resolver=self.resolver)

    def test_the_condition_is_named_and_the_placeholder_points_at_it(self):
        self.assertEqual(runner.CONDITION_TYPEMASK, "gbnf+typemask")
        self.assertIn(runner.CONDITION_TYPEMASK, runner.ALL_CONDITIONS)
        self.assertNotIn(runner.CONDITION_TYPEMASK, runner.GRAMMAR_CONDITIONS)
        with self.assertRaises(SystemExit) as raised:
            runner.Config(conditions=["masked"]).validate()
        self.assertIn("gbnf+typemask", str(raised.exception))

    def test_an_unknown_pruner_is_refused_by_the_config(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(pruners=["nonesuch"]).validate()
        self.assertIn("nonesuch", str(raised.exception))

    def test_a_full_mask_run_reproduces_the_target_and_is_accepted(self):
        _, records, summary = self.run_condition_four()
        self.assertTrue(records)
        for record in records:
            self.assertTrue(record["mask"])
            self.assertEqual(record["source"], BOOL_NOT)
            self.assertEqual(record["funnel_outcome"], ACCEPTED)
            self.assertTrue(record["semantic_success"])

    def test_records_carry_the_per_token_instrumentation(self):
        _, records, _ = self.run_condition_four()
        for record in records:
            for key in (
                "mask_steps", "mask_seconds", "mask_seconds_per_token",
                "mask_pruned_by_layer", "mask_seconds_by_layer",
                "mask_calls_by_layer", "mask_fallbacks", "mask_vocab_size",
            ):
                self.assertIn(key, record)
            self.assertGreater(record["mask_steps"], 0)
            self.assertEqual(
                set(record["mask_pruned_by_layer"]), {"syntax", *PRUNER_NAMES})
            self.assertGreater(record["mask_pruned_by_layer"]["syntax"], 0)
            self.assertEqual(record["mask_fallbacks"], 0)

    def test_the_summary_and_report_gain_a_masking_section(self):
        _, records, summary = self.run_condition_four()
        masking = summary["masking"]
        self.assertGreater(masking["mask_steps"], 0)
        self.assertEqual(sorted(masking["pruners_enabled"]), sorted(PRUNER_NAMES))
        cell = summary["cells"][f"{runner.CONDITION_TYPEMASK}|few_shot"]
        self.assertIn("masking", cell)
        report = runner.render_report(summary, records)
        self.assertIn("Masking overhead", report)
        self.assertIn("Comparability boundary", report)
        for layer in ("syntax", *PRUNER_NAMES):
            self.assertIn(layer, report)

    def test_a_phase_a_only_run_is_untouched_by_phase_b(self):
        config = self.config(
            conditions=list(runner.CONDITIONS),
            stub_outputs=[BOOL_NOT], stub_grammar_outputs=[BOOL_NOT])
        records, summary = runner.run(config, resolver=self.resolver)
        self.assertNotIn("masking", summary)
        for record in records:
            self.assertNotIn("mask", record)
            self.assertNotIn("mask_steps", record)
        for cell in summary["cells"].values():
            self.assertNotIn("masking", cell)
        report = runner.render_report(summary, records)
        self.assertIn("Conditions 1-3 only", report)
        self.assertNotIn("Masking overhead", report)

    def test_switching_off_the_de_bruijn_pruner_lets_a_scope_error_through(self):
        _, records, _ = self.run_condition_four(pruners=["ref-hash"])
        outcomes = {record["funnel_outcome"] for record in records}
        self.assertIn("scope", outcomes)
        self.assertTrue(any("(var 9" in record["source"] for record in records))

    def test_a_hash_carrying_target_is_reproduced_when_the_pruners_are_on(self):
        _, records, _ = self.run_condition_four(stub_masked_outputs=[HASHED])
        for record in records:
            self.assertEqual(record["source"], HASHED)
            self.assertEqual(record["funnel_outcome"], ACCEPTED)
            self.assertGreater(record["mask_pruned_by_layer"]["ref-hash"], 0)

    def test_switching_off_the_hash_pruner_lets_an_unresolvable_hash_through(self):
        _, records, _ = self.run_condition_four(
            pruners=["de-bruijn"], stub_masked_outputs=[HASHED])
        self.assertTrue(any("0xdead" in record["raw"] for record in records),
                        [record["raw"][:90] for record in records])
        self.assertNotIn(ACCEPTED, {record["funnel_outcome"] for record in records})

    def test_the_syntax_layer_alone_still_keeps_every_draw_grammatical(self):
        # With both pruners off the decoys win and the draw diverges, possibly
        # into the token cap. What must survive is the syntax layer's guarantee:
        # whatever came out is a live prefix of `loom.gbnf`, never garbage.
        _, records, _ = self.run_condition_four(pruners=[])
        grammar = loom_grammar()
        for record in records:
            self.assertTrue(
                grammar.feed(grammar.initial, record["raw"].encode("utf-8")),
                record["raw"][:120])

    def test_the_budget_rule_is_the_same_purse_as_every_other_condition(self):
        config, records, _ = self.run_condition_four()
        spent = sum(record["tokens_completion"] for record in records)
        self.assertLessEqual(spent, config.token_budget_per_task)
        self.assertEqual({r["budget"] for r in records}, {config.token_budget_per_task})

    def test_a_masked_run_writes_its_three_outputs(self):
        _, records, summary = self.run_condition_four()
        with tempfile.TemporaryDirectory() as directory:
            records_path, summary_path, report_path = runner.write_outputs(
                records, summary, directory)
            first = json.loads(records_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertTrue(first["mask"])
            self.assertIn("masking", json.loads(summary_path.read_text(encoding="utf-8")))
            self.assertIn("Masking overhead", report_path.read_text(encoding="utf-8"))


class MaskBackendTest(unittest.TestCase):
    """The transport seam, without loading a shared library."""

    def test_a_backend_without_logits_refuses_condition_four_by_name(self):
        config = runner.Config(backend="llama-server", server_url="http://x",
                               model_identity="test")
        backend = make_backend(config)
        with self.assertRaises(BackendUnavailable) as raised:
            runner.make_masker(config, backend, ExperimentResolver())
        message = str(raised.exception)
        self.assertIn("llama-cpp", message)
        self.assertIn("llama-server", message)
        self.assertIn("gbnf+typemask", message)
        self.assertIn("llama-server", NO_MASK_BACKEND_MESSAGE.format(backend="x"))

    def test_the_llama_cpp_backend_is_known_and_needs_a_model_path(self):
        with self.assertRaises(BackendUnavailable) as raised:
            make_backend(runner.Config(backend="llama-cpp", model_identity="test"))
        self.assertIn("model_path", str(raised.exception))
        with self.assertRaises(BackendUnavailable) as raised:
            make_backend(runner.Config(backend="gpt"))
        self.assertIn("llama-cpp", str(raised.exception))

    def test_the_llama_cpp_backend_refuses_the_phase_a_conditions(self):
        backend = LlamaCppBackend("/nonexistent.gguf")
        with self.assertRaises(BackendUnavailable) as raised:
            backend.generate("prompt")
        self.assertIn("condition 4", str(raised.exception))

    def test_a_missing_library_or_model_is_a_backend_error_not_a_crash(self):
        backend = LlamaCppBackend("/nonexistent.gguf", lib_path="/nonexistent.so")
        with self.assertRaises(BackendUnavailable) as raised:
            backend.mask_vocabulary()
        self.assertIn("nonexistent", str(raised.exception))

    def test_a_live_backend_needs_a_recorded_model_identity(self):
        with self.assertRaises(SystemExit) as raised:
            runner.Config(backend="llama-cpp", model_path="/x.gguf").validate()
        self.assertIn("model_identity", str(raised.exception))

    def test_the_stub_exposes_a_vocabulary_covering_its_own_script(self):
        backend = StubBackend([BOOL_NOT], [BOOL_NOT], [BOOL_NOT])
        vocabulary = backend.mask_vocabulary()
        self.assertGreater(len(vocabulary), 1000)
        self.assertTrue(vocabulary.eos_ids)
        for piece in greedy(BOOL_NOT.encode("utf-8"), vocabulary, longest=4):
            self.assertIsNotNone(vocabulary.lookup(piece))

    def test_the_stub_masked_draw_is_reproducible(self):
        resolver = ExperimentResolver()
        texts = []
        for _ in range(2):
            backend = StubBackend([BOOL_NOT], [BOOL_NOT], [BOOL_NOT])
            masker = build_masker(backend.mask_vocabulary(), resolver)
            texts.append(backend.generate_masked("p", masker=masker, max_tokens=200).text)
        self.assertEqual(texts[0], texts[1])
        self.assertEqual(texts[0], BOOL_NOT)


if __name__ == "__main__":
    unittest.main()
