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
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import corpus_registry
import transcode
from experiment import prompts, runner
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
    ATOM_READ,
    LIT_KIND_NAMES,
    PRUNABLE,
    PRUNER_NAMES,
    DeBruijnPruner,
    GoalTypePruner,
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


class GoalTypePrunerTest(unittest.TestCase):
    """B2's goal-type layer, probed where it claims a proof and where it does not.

    Phase A put `typecheck` at the top of the failure distribution (590 of 1,671
    grammar-constrained draws), localized at `definition.term`, so these are the
    cases that decide whether the dominant layer is actually being pruned.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.goals = GoalTypePruner(cls.resolver.digests(), cls.resolver.reference_type)
        cls.blind = GoalTypePruner(cls.resolver.digests())

    def veto(self, prefix: str, char: str, pruner=None) -> bool:
        pruner = pruner or self.goals
        return pruner.veto(TypeState().feed(prefix.encode("utf-8")), ord(char))

    # -- the declared type becomes the term's goal -------------------------

    def test_the_declared_type_is_captured_and_becomes_the_terms_goal(self):
        state = TypeState().feed(b"(def (fn Bool () Bool) (")
        self.assertEqual(state.top.goal_in, b"(fn Bool () Bool)")
        # ... and a prenex `forall` is peeled exactly as `check_definition` does.
        state = TypeState().feed(b"(def (forall (fn (tyvar 0) () (tyvar 0))) (")
        self.assertEqual(state.top.goal_in, b"(fn (tyvar 0) () (tyvar 0))")

    def test_a_declared_type_this_layer_cannot_read_abstains(self):
        # Rank-2: `forall_prefix` refuses it, so there is no goal and no veto.
        prefix = "(def (fn (forall Bool) () Bool) ("
        self.assertEqual(TypeState().feed(prefix.encode()).top.goal_in, b"")
        for char in "lcfr":
            self.assertFalse(self.veto(prefix, char), char)

    # -- 1. the forced annotation -----------------------------------------

    def test_a_lambda_annotation_is_forced_to_the_goal_domain(self):
        opened = "(def (fn Bool () I64) (lam "
        self.assertEqual(TypeState().feed(opened.encode()).forced, b"Bool")
        self.assertFalse(self.veto(opened, "B"))
        for char in "IFTUb(":
            self.assertTrue(self.veto(opened, char), char)
        # The run is consumed byte by byte and stops having an opinion at its end.
        self.assertFalse(self.veto(opened + "Boo", "l"))
        self.assertTrue(self.veto(opened + "Boo", "k"))
        self.assertEqual(TypeState().feed((opened + "Bool").encode()).forced, b"")

    def test_a_forced_annotation_spans_a_whole_nested_type(self):
        domain = "(fn I64 () Bool)"
        opened = f"(def (fn {domain} () Bool) (lam "
        state = TypeState().feed(opened.encode())
        self.assertEqual(state.forced, domain.encode("ascii"))
        for index in range(len(domain)):
            with self.subTest(offset=index):
                self.assertFalse(self.veto(opened + domain[:index], domain[index]))

    def test_a_fix_annotation_is_forced_to_the_whole_goal(self):
        opened = "(def (fn Bool () Bool) (fix "
        self.assertEqual(TypeState().feed(opened.encode()).forced, b"(fn Bool () Bool)")
        self.assertFalse(self.veto(opened, "("))
        self.assertTrue(self.veto(opened, "B"))

    def test_nothing_is_forced_where_the_goal_is_unknown(self):
        # `app` synthesizes both parts, so a `lam` under one has no goal.
        opened = "(def Bool (app (lam "
        self.assertEqual(TypeState().feed(opened.encode()).forced, b"")
        for char in "BIFTU(":
            self.assertFalse(self.veto(opened, char), char)

    # -- 2. head feasibility ----------------------------------------------

    def test_a_lambda_head_needs_a_function_goal(self):
        self.assertTrue(self.veto("(def Bool (l", "a"))
        self.assertFalse(self.veto("(def (fn Bool () Bool) (l", "a"))
        # `let` and `lit` keep the bare `l` alive at a base goal.
        self.assertFalse(self.veto("(def Bool (", "l"))
        self.assertFalse(self.veto("(def Bool (l", "e"))

    def test_a_literal_head_needs_a_base_goal(self):
        self.assertTrue(self.veto("(def (fn Bool () Bool) (l", "i"))
        self.assertFalse(self.veto("(def Bool (l", "i"))

    def test_a_constructor_head_needs_a_nominal_goal(self):
        self.assertTrue(self.veto("(def Bool (", "c"))
        nominal = "(data 0x" + "ab" * 32 + " ())"
        self.assertFalse(self.veto(f"(def {nominal} (", "c"))

    def test_a_fix_head_needs_a_function_goal(self):
        self.assertTrue(self.veto("(def Bool (", "f"))
        self.assertFalse(self.veto("(def (fn Bool () Bool) (", "f"))

    def test_a_finished_head_is_judged_at_its_terminator_not_extended(self):
        """The terminator case, because getting it wrong killed every `lam`.

        A space does not extend `lam` into `lam ` — it ends the atom, and what
        must be judged there is the head that was written.
        """
        self.assertFalse(self.veto("(def (fn Bool () Bool) (lam", " "))
        self.assertTrue(self.veto("(def Bool (lam", " "))
        # A word that is not a head at all is the grammar's business.
        self.assertFalse(self.veto("(def Bool (nonesuch", " "))

    def test_a_head_the_goal_cannot_reject_is_never_vetoed(self):
        for prefix, char in (("(def Bool (", "m"), ("(def Bool (", "h"),
                             ("(def Bool (", "a"), ("(def Bool (", "p")):
            self.assertFalse(self.veto(prefix, char), char)

    def test_a_ref_head_is_refused_when_no_digest_could_meet_the_goal(self):
        """The dead-end the layer declines to walk into.

        If nothing the resolver holds could be named here, `(ref …)` could only
        be followed by digits the layer would then refuse one by one until the
        mask emptied and fell back for liveness. Refusing the head is the same
        proof applied one atom earlier.

        **On this corpus the veto is inert**, and the test says so rather than
        hiding it: one corpus definition is polymorphic, and §3.1.3 instantiates
        a `forall` against any goal, so exactly one digest survives every goal
        and `ref` always stays feasible. The mechanism is therefore driven here
        against a resolver that holds only an ill-fitting type -- which is the
        situation a *larger* corpus of monomorphic definitions produces.
        """
        digest = bytes.fromhex("ab" * 32)
        only_i64 = GoalTypePruner([digest], lambda _: [0, 2])   # I64
        self.assertTrue(only_i64.veto(TypeState().feed(b"(def Bool ("), ord("r")))
        self.assertFalse(only_i64.veto(TypeState().feed(b"(def I64 ("), ord("r")))
        # With no resolver at all there is nothing to prove, so the head stays.
        self.assertFalse(self.veto("(def Bool (", "r", pruner=self.blind))
        # And the corpus's own polymorphic definition is why the real pruner
        # keeps `ref` alive at a goal no monomorphic definition could meet.
        self.assertFalse(self.veto("(def Bool (", "r"))

    # -- 3/4. literal kinds and constructor hashes -------------------------

    def test_a_literal_kind_word_is_fixed_by_a_base_goal(self):
        self.assertFalse(self.veto("(def Bool (lit ", "b"))
        for char in "iftu":
            self.assertTrue(self.veto("(def Bool (lit ", char), char)
        self.assertFalse(self.veto("(def I64 (lit ", "i"))
        self.assertTrue(self.veto("(def I64 (lit ", "b"))
        # Terminators judge the finished word, they do not extend it.
        self.assertFalse(self.veto("(def Bool (lit bool", " "))
        self.assertTrue(self.veto("(def Unit (lit bool", " "))
        self.assertFalse(self.veto("(def Unit (lit unit", ")"))

    def test_literal_kinds_and_base_codes_agree_position_for_position(self):
        """The correspondence the kind veto is built on, asked of the source.

        `synth` tag 2 returns `[0, term[1]]`, so a literal's kind code *is* a
        base-type code. If those two tables ever drift apart the veto above
        starts naming the wrong word, and it would be a silent unsoundness.
        """
        from transcode import BASE_CODE, LIT_KIND
        self.assertEqual(
            [name.decode("ascii") for name in LIT_KIND_NAMES],
            [name for name, _ in sorted(LIT_KIND.items(), key=lambda kv: kv[1])])
        self.assertEqual(sorted(LIT_KIND.values()), sorted(BASE_CODE.values()))

    def test_a_constructor_hash_is_fixed_by_the_nominal_goal(self):
        digest = "ab" * 32
        prefix = f"(def (data 0x{digest} ()) (con 0x"
        for index in range(len(digest)):
            with self.subTest(offset=index):
                self.assertFalse(self.veto(prefix + digest[:index], digest[index]))
        self.assertTrue(self.veto(prefix, "c"))
        self.assertTrue(self.veto(prefix + digest, "c"))
        self.assertFalse(self.veto(prefix + digest, " "))
        self.assertTrue(self.veto(prefix + digest[:-2], " "))

    # -- 5. the goal-filtered digest universe ------------------------------

    def test_a_ref_digest_must_resolve_to_a_type_meeting_the_goal(self):
        wanted = self.resolver.digest_for("corpus/bool/not").hex()
        goal = "(fn Bool () Bool)"
        self.assertEqual(
            transcode.type_to_surface(self.resolver.reference_type(
                self.resolver.digest_for("corpus/bool/not"))), goal)
        for index in range(len(wanted)):
            with self.subTest(offset=index):
                self.assertFalse(self.veto(f"(def {goal} (ref 0x{wanted[:index]}",
                                           wanted[index]))
        # The same digest at a goal its type cannot meet is gone by its 4th
        # digit at the latest -- and `ref-hash` would have kept every one.
        other = "(fn I64 () I64)"
        refused = any(self.veto(f"(def {other} (ref 0x{wanted[:index]}", wanted[index])
                      for index in range(8))
        self.assertTrue(refused)

    def test_a_polymorphic_definition_survives_every_goal(self):
        """§3.1.3 instantiates a `forall` against whatever is expected.

        Deciding that per byte would mean re-implementing `_instantiate`, so a
        quantified type is kept at every goal. The proof stays one-sided.
        """
        polymorphic = [
            found for found in self.resolver.definitions()
            if found.type_ir and found.type_ir[0] == 6]
        if not polymorphic:
            self.skipTest("the corpus holds no polymorphic definition")
        digest = polymorphic[0].digest.hex()
        for goal in ("(fn Bool () Bool)", "(fn I64 () I64)"):
            with self.subTest(goal=goal):
                for index in range(len(digest)):
                    self.assertFalse(
                        self.veto(f"(def {goal} (ref 0x{digest[:index]}", digest[index]))

    # -- goal propagation, and where it deliberately stops ------------------

    def test_an_if_condition_is_Bool_even_under_an_unknown_goal(self):
        # `check` tag 12 and `synth` tag 12 both check the condition against
        # BOOL, so this is the one goal that needs no goal above it.
        state = TypeState().feed(b"(def Bool (app (if (")
        self.assertEqual(state.top.goal_in, b"Bool")
        self.assertTrue(self.veto("(def Bool (app (if (l", "a"))
        # ... and the branches inherit the outer goal, which here is unknown.
        state = TypeState().feed(b"(def Bool (app (if (var 0) (")
        self.assertEqual(state.top.goal_in, b"")

    def test_match_arms_and_handler_clauses_inherit_the_goal(self):
        arm = TypeState().feed(b"(def Bool (match (var 0) ((0 0 (")
        self.assertEqual(arm.top.goal_in, b"Bool")
        clause = TypeState().feed(
            b"(def Bool (handle 0x" + b"aa" * 32 + b" (lit unit) ((0 (")
        self.assertEqual(clause.top.goal_in, b"Bool")
        self.assertTrue(clause.depth_unknown,
                        "the de Bruijn abstention is independent of the goal")
        ret = TypeState().feed(
            b"(def Bool (handle 0x" + b"aa" * 32 + b" (lit unit) () (")
        self.assertEqual(ret.top.goal_in, b"Bool")

    def test_the_synthesis_positions_are_abstentions_not_omissions(self):
        """Every position this layer deliberately says nothing about.

        Each is a checker rule that synthesizes rather than checks, so no goal
        exists to prune against. They are listed here so that a later change
        that starts propagating one has to come through this test.
        """
        unknown = {
            "app function": b"(def Bool (app (",
            "app argument": b"(def Bool (app (var 0) (",
            "let bound": b"(def Bool (let Bool (",
            "let body": b"(def Bool (let Bool (var 0) (",
            "match scrutinee": b"(def Bool (match (",
            "con field": b"(def (data 0x" + b"ab" * 32 + b" ()) (con 0x" + b"ab" * 32 + b" 0 ((",
            "hole annotation": b"(def Bool (hole (",
            "refine predicate": b"(def (refine Bool (",
        }
        for name, prefix in unknown.items():
            with self.subTest(position=name):
                state = TypeState().feed(prefix)
                self.assertEqual(state.top.goal_in, b"", name)
                self.assertEqual(state.forced, b"", name)

    def test_a_var_type_is_never_pruned(self):
        # The binder-type environment is not carried, so `(var N)` is the de
        # Bruijn layer's business alone at every goal.
        for goal in ("Bool", "(fn Bool () Bool)"):
            for digit in "0123456789":
                self.assertFalse(
                    self.veto(f"(def {goal} (lam Bool (var ", digit), (goal, digit))

    # -- the coupling the proofs are written against ------------------------

    def test_the_funnel_supplies_no_subsumption_collector(self):
        """§3.3 subsumption does not fire in this experiment, and the vetoes
        above are written not to depend on that -- every type comparison they
        make is on refinement *erasure*, which is subsumption's own
        precondition. This test exists so that wiring a collector into
        `run_funnel` has to come past a line that names the coupling, rather
        than silently widening what the checker accepts under a mask built for
        the narrower rule.
        """
        import inspect

        from experiment import evaluate
        source = inspect.getsource(evaluate.run_funnel)
        self.assertIn("typecheck.validate_source(source", source)
        self.assertNotIn("obligation", source)


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
        # A hash position inside a definition whose goal is a function type:
        # the goal layer keeps the corpus's function-typed digests, so the mask
        # is tiny but alive, and the type layers -- not syntax alone -- are what
        # made it tiny.
        self.masker.reset()
        self.masker.accept_bytes(b"(def (fn Bool () Bool) (ref 0x")
        step = self.masker.step()
        self.assertTrue(step.allowed)
        self.assertFalse(step.fallback)
        self.assertLess(step.size, len(self.vocabulary) // 10)
        type_layers = sum(count for layer, count in step.pruned.items() if layer != "syntax")
        self.assertGreater(type_layers, 0)
        self.assertGreater(step.pruned.get("goal-type", 0), 0)


class MaskMemoryTest(unittest.TestCase):
    """The masker's memory, which a live run found unbounded the hard way.

    Condition 4's first live matrix was OOM-killed at 14.3 GB anon-rss on a
    16 GB box after stalling for 39 minutes inside a single draw. Every one of
    the five slowest draws contained a `(lit text "…")`, and the cause measured
    out exactly: a string payload is an atom no consumer reads, but `TypeState`
    accumulated it anyway, so **every byte of a literal was a distinct state**.
    Nothing shared, the mask cache never hit, and each token inside a literal
    cost a full walk of the 333k-node vocabulary trie and left ~82,000 permanent
    entries in a memo that had no bound at all.

    Measured on the real 151,936-token vocabulary: one step inside a text
    literal took 3.28 s, added 326,749 transition entries and +131 MB; a
    sustained walk reached +2.38 GB after 64 characters. With the payload
    dropped the same step takes 0.62 s, adds 422 entries and +0.2 MB, and the
    sustained walk is flat.

    The corpus contains no text literal, which is why `MaskSoundnessTest` never
    walked this path — so the coverage is here, and deliberately does not depend
    on a model or on the corpus growing one.
    """

    @classmethod
    def setUpClass(cls):
        cls.resolver = ExperimentResolver()
        cls.vocabulary = scripted_vocabulary(SURFACES, max_piece=4)

    LITERAL = b'(def Text (lit text "'

    def test_a_literal_payload_collapses_to_a_constant_number_of_states(self):
        """The state-level cause. 54 characters used to mean 54 states."""
        for label, prefix, body in (
            ("text", self.LITERAL, b"the quick brown fox jumps over the lazy dog 0123456789"),
            ("bytes", b"(def Bytes (lit bytes 0x", b"ab" * 40),
            ("f64", b"(def F64 (lit f64 0x", b"0123456789abcdef"),
            ("i64", b"(def I64 (lit i64 ", b"1234567890" * 5),
        ):
            with self.subTest(literal=label):
                state = TypeState().feed(prefix)
                distinct = set()
                for byte in body:
                    distinct.add(state)
                    state = state.advance(byte)
                self.assertLessEqual(
                    len(distinct), 3,
                    f"{label} payload retains per-character state: {len(distinct)} "
                    f"distinct states over {len(body)} bytes")

    def test_a_text_literal_does_not_grow_the_transition_memo(self):
        """The regression guard proper: sustained steps inside one literal.

        Entry count rather than RSS, because entries are what the measurement
        showed growing and an entry-count assertion does not flake on a shared
        machine.
        """
        masker = build_masker(self.vocabulary, self.resolver)
        masker.accept_bytes(self.LITERAL)
        masker.step()
        masker.accept_bytes(b"ab")
        masker.step()
        settled = len(masker._transitions)
        for _ in range(120):
            masker.step()
            masker.accept_bytes(b"ab")
        self.assertEqual(
            len(masker._transitions), settled,
            "the transition memo grew while walking a text literal — the "
            "literal's payload is being retained in the type state again")
        self.assertEqual(masker.transition_clears, 0)

    def test_a_long_literal_keeps_hitting_the_mask_cache(self):
        """The other half of the same fault: hit rate collapsed to ~0.07 live."""
        masker = build_masker(self.vocabulary, self.resolver)
        masker.accept_bytes(self.LITERAL)
        for _ in range(60):
            masker.step()
            masker.accept_bytes(b"x")
        stats = masker.stats()
        self.assertGreater(stats["mask_cache_hit_rate"], 0.9, stats)

    def test_the_transition_memo_is_bounded_and_says_when_it_evicts(self):
        """Memory is bounded by construction, not only by the fix above.

        The `ATOM_READ` fix removes the pathology that was found; the cap is
        what makes the bound hold against the one that has not been.
        """
        masker = build_masker(self.vocabulary, self.resolver)
        masker._transition_cache_size = 64
        for surface in SURFACES:
            masker.reset()
            for byte in surface.encode("utf-8"):
                masker.step()
                masker.accept_bytes(bytes((byte,)))
                self.assertLessEqual(len(masker._transitions), 64)
        self.assertGreater(masker.transition_clears, 0)
        stats = masker.stats()
        self.assertEqual(stats["mask_transition_clears"], masker.transition_clears)
        self.assertLessEqual(stats["mask_transition_entries"], 64)

    def test_a_full_mask_cache_evicts_rather_than_freezing(self):
        """A frozen cache is a cache that stops learning.

        Launch 4 hit the 32,768-entry cap during the first two regimes, so
        `full_corpus` — the regime carrying R5's bar — would have run against a
        cache that could no longer take an entry for any position in it.
        """
        masker = build_masker(self.vocabulary, self.resolver)
        masker._mask_cache_size = 8
        for surface in SURFACES[:4]:
            masker.reset()
            for byte in surface.encode("utf-8"):
                masker.step()
                masker.accept_bytes(bytes((byte,)))
                self.assertLessEqual(len(masker._mask_cache), 8)
        self.assertGreater(masker.mask_cache_clears, 0)
        # The point of evicting: the cache is still taking entries at the end.
        self.assertGreater(len(masker._mask_cache), 0)
        self.assertEqual(masker.stats()["mask_cache_clears"], masker.mask_cache_clears)

    def test_eviction_does_not_change_the_mask(self):
        """A cache is only ever a speedup. Same position, same answer."""
        prefix = b"(def (fn Bool () Bool) (lam Bool (if (var 0) "
        roomy = build_masker(self.vocabulary, self.resolver)
        roomy.accept_bytes(prefix)
        cramped = build_masker(self.vocabulary, self.resolver)
        cramped._transition_cache_size = 1
        cramped._mask_cache_size = 1
        cramped.accept_bytes(prefix)
        self.assertEqual(roomy.step().allowed, cramped.step().allowed)

    def test_the_atoms_that_are_kept_are_the_ones_that_are_read(self):
        """`ATOM_READ` has to cover every consumer of an atom's content.

        Two kinds of consumer: the pruners (`PRUNABLE`), and `_next_part`'s own
        three reads — the head keyword, the literal kind word, and a match arm's
        binder count. Dropping a kind that is read would be silent corruption
        rather than a crash, so the set is asserted rather than commented.
        """
        self.assertLessEqual(PRUNABLE, ATOM_READ)
        for kind in ("head", "lit-kind", "uint:free"):
            self.assertIn(kind, ATOM_READ)
        # And the reads still work end to end, on the paths that do them.
        state = TypeState().feed(b"(def Bool (match (var 0) ((0 12 ")
        self.assertEqual(state.top.binders, 12, "arm binder count was truncated")
        state = TypeState().feed(b"(def Bool (lit bool ")
        self.assertEqual(state.top.lit_kind, "bool", "literal kind word was truncated")
        state = TypeState().feed(b"(def Bool (perform 0x" + b"ab" * 32 + b" 7 ")
        self.assertEqual(state.top.kind, "perform", "head keyword was truncated")

    def test_the_mask_admits_a_text_literal_byte_by_byte(self):
        """R4 over the path the corpus does not cover.

        The soundness rule is about definitions the funnel accepts, so the
        definition is run through the funnel here rather than assumed: if
        `run_funnel` accepts it, every one of its bytes must have been offered.
        """
        source = '(def Text (lit text "hello \\" world"))'
        self.assertEqual(run_funnel(source, self.resolver).outcome, ACCEPTED)
        masker = build_masker(self.vocabulary, self.resolver)
        masker.reset()
        for index, byte in enumerate(source.encode("utf-8")):
            token = self.vocabulary.lookup(bytes((byte,)))
            self.assertIsNotNone(token, f"vocabulary gap at byte {index}")
            step = masker.step()
            self.assertIn(
                token, step.allowed,
                f"MASK EXCLUDED A VALID CONTINUATION at byte {index} "
                f"({chr(byte)!r}) after {masker.text[-40:]!r}")
            masker.accept_token(token)
        self.assertTrue(masker.can_end)
        self.assertEqual(masker.fallbacks, 0)


MODELS_DIR = Path(os.environ.get(
    "LOOM_MODELS_DIR", Path.home() / "loom-tools/models"))
SMALL_GGUF = MODELS_DIR / "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"


class ChunkedPrefillTest(unittest.TestCase):
    """Prefill longer than one batch, which aborted a live run at 530 draws.

    `llama_decode` carries `GGML_ASSERT(n_tokens_all <= cparams.n_batch)`. That
    is an abort, not a return code — the process takes SIGABRT and there is
    nothing to catch — so once `n_batch` stopped tracking `n_ctx`, the first
    `full_corpus` prompt (~11.9k tokens against a 2048 batch) killed the run.
    `few_shot`'s ~1.7k prompts had fit, which is why two whole regimes passed
    first.

    These need the real library and a real GGUF, so they are gated the way the
    repo gates its other optional-dependency checks. They are cheap: a 1.5B
    model, a few hundred tokens, and contexts small enough that the interesting
    ratio (prompt ≫ batch) is reached without a long prompt.
    """

    @classmethod
    def setUpClass(cls):
        if not SMALL_GGUF.is_file():
            raise unittest.SkipTest(
                f"no GGUF at {SMALL_GGUF}; set LOOM_MODELS_DIR to run the "
                "chunked-prefill checks")
        try:
            from experiment.llama_ffi import FfiUnavailable, load_library
        except ImportError as error:      # pragma: no cover - import guard
            raise unittest.SkipTest(str(error)) from error
        try:
            load_library(None)
        except FfiUnavailable as error:
            raise unittest.SkipTest(f"libllama.so unavailable: {error}") from error

    @staticmethod
    def model(**overrides):
        from experiment.llama_ffi import LlamaModel
        settings = dict(n_ctx=1024, n_gpu_layers=0)
        settings.update(overrides)
        return LlamaModel(str(SMALL_GGUF), **settings)

    PROMPT = "def fibonacci(n):\n    # returns the nth Fibonacci number\n" * 24

    def test_the_effective_batch_is_read_back_not_assumed(self):
        """llama.cpp clamps `n_batch` to `n_ctx`; the assert uses the clamp."""
        with self.model(n_ctx=512, n_batch=8192) as model:
            self.assertLessEqual(model.n_batch, 512)
            self.assertGreater(model.n_batch, 0)
            self.assertLessEqual(model.n_ubatch, model.n_batch)

    def test_a_prompt_longer_than_the_batch_decodes(self):
        """The regression proper, in the shape the crash took.

        Run in a subprocess: a `GGML_ASSERT` aborts the interpreter, so an
        in-process regression would kill the whole test run and report nothing.
        Here it comes back as exit 134 and a readable failure.
        """
        script = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(HERE)!r})
            from experiment.llama_ffi import LlamaModel
            with LlamaModel({str(SMALL_GGUF)!r}, n_ctx=1024, n_batch=64,
                            n_gpu_layers=0) as model:
                tokens = model.tokenize({self.PROMPT!r})
                assert len(tokens) > 4 * model.n_batch, (
                    "prompt must be several batches long to exercise chunking; "
                    f"got {{len(tokens)}} tokens against n_batch={{model.n_batch}}")
                model.decode(tokens)
                logits = model.logits()
                assert len(logits) == model.n_vocab
                print("OK", len(tokens), model.n_batch)
        """)
        finished = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=600)
        self.assertEqual(
            finished.returncode, 0,
            f"chunked prefill aborted (exit {finished.returncode}).\n"
            f"stdout: {finished.stdout}\nstderr: {finished.stderr[-2000:]}")
        self.assertIn("OK", finished.stdout)

    def test_chunked_prefill_leaves_the_same_context_as_one_batch(self):
        """Positions and KV across chunks, which a crash would not have caught.

        A position bug does not abort — it silently shifts the whole prompt and
        corrupts every generation after it, which is worse. So the two paths are
        compared on the logits they leave at the final prompt position: a
        misplaced chunk moves those by whole logits, far outside the last-bit
        differences that reordered reductions produce.
        """
        with self.model(n_batch=2048) as whole:
            tokens = whole.tokenize(self.PROMPT)
            whole.decode(tokens)
            reference = list(whole.logits())
        with self.model(n_batch=64) as chunked:
            self.assertLess(chunked.n_batch, len(tokens) // 4)
            chunked.decode(tokens)
            actual = list(chunked.logits())
        self.assertEqual(len(reference), len(actual))
        worst = max(abs(a - b) for a, b in zip(reference, actual))
        self.assertLess(worst, 0.5, f"chunked prefill diverged by {worst}")
        self.assertEqual(
            reference.index(max(reference)), actual.index(max(actual)),
            "chunked and single-batch prefill disagree on the next token")

    def test_positions_stay_right_across_the_per_draw_context_reset(self):
        """`reset()` recreates the context once per draw; batch sizes and the
        position counter have to survive it, or draw 2 decodes into a KV cache
        that still believes it holds draw 1."""
        with self.model(n_batch=64) as model:
            tokens = model.tokenize(self.PROMPT)
            model.decode(tokens)
            first = list(model.logits())
            batch_before = model.n_batch
            model.reset()
            self.assertEqual(model.n_batch, batch_before)
            self.assertEqual(model._position, 0)
            model.decode(tokens)
            second = list(model.logits())
        worst = max(abs(a - b) for a, b in zip(first, second))
        self.assertLess(worst, 0.5, f"the same prompt after reset diverged by {worst}")

    def test_a_masked_draw_runs_end_to_end_under_a_tiny_batch(self):
        """The crash path exactly: backend, mask, prompt longer than a batch."""
        script = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(HERE)!r})
            from experiment.backends import LlamaCppBackend
            from experiment.masker import build_masker
            from experiment.resolver import ExperimentResolver
            backend = LlamaCppBackend({str(SMALL_GGUF)!r}, n_ctx=1024,
                                      n_gpu_layers=0)
            backend.n_batch = 64
            masker = build_masker(backend.mask_vocabulary(), ExperimentResolver())
            result = backend.generate_masked(
                {self.PROMPT!r}, masker=masker, max_tokens=8, seed=1, temperature=0.0)
            text = result if isinstance(result, str) else result.text
            assert text.startswith("(def"), text
            print("OK", repr(text[:40]))
        """)
        finished = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=900)
        self.assertEqual(
            finished.returncode, 0,
            f"masked draw aborted (exit {finished.returncode}).\n"
            f"stdout: {finished.stdout}\nstderr: {finished.stderr[-2000:]}")
        self.assertIn("OK", finished.stdout)


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
        self.assertEqual(
            masker.enabled_pruners,
            tuple(name for name in PRUNER_NAMES if name != "de-bruijn"))
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

        # The hash decoy is refused by *two* layers once B2's goal pruner is in:
        # `ref-hash` because no digest extends it, `goal-type` because no digest
        # of the goal's type extends it either. That overlap is the point of
        # prioritising by Phase A's profile, so it is asserted rather than
        # designed around: the decoy comes back only when both are off.
        masker = self.masker()
        masker.accept_bytes(b"(def (fn Bool () Bool) (ref 0x")
        hash_decoy = self.vocabulary.lookup(DECOY_HASH)
        self.assertNotIn(hash_decoy, masker.step().allowed)
        masker.enable("ref-hash", False)
        self.assertNotIn(hash_decoy, masker.step().allowed)
        masker.enable("goal-type", False)
        self.assertIn(hash_decoy, masker.step().allowed)

    def test_the_goal_layer_narrows_a_hash_position_further_than_existence_does(self):
        """`goal-type` prunes by *type*, where `ref-hash` prunes by existence.

        Same position, same resolver: the goal layer alone leaves strictly fewer
        tokens than the existence layer alone, because a digest that resolves
        but resolves to the wrong type is still refused.
        """
        prefix = b"(def Bool (ref 0x"
        by_existence = self.masker(names=["ref-hash"])
        by_existence.accept_bytes(prefix)
        by_type = self.masker(names=["goal-type"])
        by_type.accept_bytes(prefix)
        wide, narrow = by_existence.step(), by_type.step()
        self.assertTrue(set(narrow.allowed) < set(wide.allowed))

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

    def test_the_r5_comparison_is_produced_from_a_recorded_baseline(self):
        """R5 has to be readable off the run report, not reconstructed later.

        Phase A and Phase B are separate runs on separate transports, so the
        comparison is assembled from this run's cells plus a Phase A
        `summary.json` named in the config. The baseline below is shaped like
        the real one and carries the real bar: `gbnf|full_corpus` at 1.452
        accepted per 1k tokens, which is the number condition 4 must beat.
        """
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "phase-a-summary.json"
            baseline.write_text(json.dumps({
                "started_utc": "2026-08-14T11:14:03Z",
                "config": {"backend": "llama-server"},
                "cells": {
                    "gbnf|few_shot": {"accepted_per_1k_tokens": 0.376},
                    "gbnf+rejection|few_shot": {"accepted_per_1k_tokens": 0.326},
                    "gbnf|full_corpus": {"accepted_per_1k_tokens": 1.452},
                },
            }), encoding="utf-8")
            _, records, summary = self.run_condition_four(
                baseline_summary=str(baseline))

        r5 = summary["r5"]
        self.assertEqual(r5["measure"], "accepted_per_1k_tokens")
        row = next(r for r in r5["by_regime"] if r["regime"] == "few_shot")
        # The bar is the *best* Phase A grammar condition, not whichever is
        # listed first -- masking has to beat the strongest baseline.
        self.assertEqual(row["bar"], 0.376)
        self.assertEqual(row["gbnf+rejection"], 0.326)
        self.assertEqual(
            row["delta"], round(row[runner.CONDITION_TYPEMASK] - 0.376, 3))
        self.assertEqual(r5["regimes_compared"], 1)

        report = runner.render_report(summary, records)
        self.assertIn("## R5 — condition 4 against conditions 2 and 3", report)
        self.assertIn("gbnf+rejection", report)
        self.assertIn("Prediction 4", report)
        self.assertIn("Prediction 5", report)

    def test_the_r5_section_is_absent_without_a_baseline_and_says_how(self):
        _, records, summary = self.run_condition_four()
        self.assertNotIn("r5", summary)
        report = runner.render_report(summary, records)
        self.assertNotIn("## R5 —", report)
        self.assertIn("baseline_summary", report)

    def test_an_unreadable_baseline_is_reported_not_swallowed(self):
        _, records, summary = self.run_condition_four(
            baseline_summary="/nonexistent/phase-a-summary.json")
        self.assertIn("error", summary["r5"])
        self.assertIn("## R5 —", runner.render_report(summary, records))

    def test_the_shipped_config_has_context_for_the_longest_prompt(self):
        """The landmine attempt 1 died too early to reach.

        `full_corpus` and `held_out` prompts are ~11.9k tokens; the masked
        transport refuses a prompt that will not fit and the run stops. Attempt 1
        died in `none`, whose longest prompt is 279 tokens, so a 4096 context
        looked fine right up until the fourth regime.

        Measured in characters rather than tokens so the check needs no model.
        The divisor used to be 4 characters per token, on the "conservative for
        English" rule of thumb. It is not conservative here: this run's own
        numbers put the `full_corpus` prompt at 17,979 characters and 11,906
        real tokens — **1.51** chars/token, because 64-hex hash literals
        tokenize densely — so the old floor under-estimated by 2.6x, in the
        direction that lets a too-small `n_ctx` through. `prompts.CHARS_PER_TOKEN`
        now carries the measured figure and `prompts.context_required` applies
        it; this config still passes, with room, under the honest divisor.
        """
        config = runner.Config.load(HERE / "experiment" / "phase_b.config.json")
        needed = prompts.context_required(
            config.regimes, self.resolver,
            leave_one_out=config.leave_one_out,
            draw_tokens=config.max_tokens_per_draw)
        self.assertGreaterEqual(
            config.n_ctx, needed,
            f"n_ctx={config.n_ctx} cannot hold the longest prompt plus a "
            f"{config.max_tokens_per_draw}-token draw ({needed} tokens)")

    def test_the_shipped_phase_b_config_is_ready_for_the_live_matrix(self):
        """The condition-4 config an operator launches, checked as a whole.

        It is the deliverable, so its matrix is asserted rather than described:
        Phase A's seeds and budget, all four regimes, condition 4 alone, the
        profile-ordered pruner set, and the backend seam left empty so the entry
        point refuses until the runner fills it in.
        """
        path = HERE / "experiment" / "phase_b.config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(config["conditions"], [runner.CONDITION_TYPEMASK])
        self.assertEqual(config["seeds"], [1, 2, 3])
        self.assertEqual(config["token_budget_per_task"], 512)
        self.assertEqual(config["max_tokens_per_draw"], 512)
        self.assertEqual(config["regimes"], list(runner.REGIMES))
        self.assertEqual(config["pruners"], list(PRUNER_NAMES))
        self.assertEqual(config["temperature"], 0.8)
        for empty in ("backend", "model_path", "llama_lib", "model_identity", "hardware"):
            self.assertEqual(config[empty], "", empty)
        # -1 is "all layers, falling back where there is no device". A committed
        # 0 here ran the matrix on the instance's four vCPUs with the L4 idle.
        self.assertEqual(config["n_gpu_layers"], -1)
        # And it loads: every key is one `Config` knows, so a live run does not
        # discover a typo after paying for an instance. `load` anchors the
        # baseline to the config's own directory, so the path it produces is
        # the one the remote runner will read whatever its cwd is.
        loaded = runner.Config.load(path)
        self.assertEqual(loaded.conditions, [runner.CONDITION_TYPEMASK])
        baseline = Path(loaded.baseline_summary)
        self.assertTrue(baseline.is_absolute())
        self.assertTrue(baseline.is_file(), f"baseline summary missing: {baseline}")
        self.assertIn("cells", json.loads(baseline.read_text(encoding="utf-8")))

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
