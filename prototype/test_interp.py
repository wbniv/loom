"""Tests for the reference evaluator (`interp.py`).

The suite is organised around what the evaluator makes possible for the first
time: the bootstrap corpus *runs*, deep handlers have operational meaning, and
`I64` wrapping is demonstrable rather than merely stated. See
`docs/plans/2026-08-13-reference-evaluator.md`.
"""

from __future__ import annotations

import unittest

import cbor_canonical
import corpus_registry
import interp
import prelude
from interp import (
    Capability,
    Closure,
    Constructor,
    Continuation,
    EvaluationError,
    ExternValue,
    FuelExhausted,
    HoleRefused,
    INT64_MAX,
    INT64_MIN,
    Interpreter,
    Literal,
    ReferenceCycle,
    UnhandledOperation,
    UnresolvedReference,
    corpus_definition_terms,
    corpus_digest,
    corpus_interpreter,
    i64,
    i64_list,
    python_i64_list,
    scripted_clock,
    seeded_rand,
)

CLOCK = prelude.HASHES["clock"]
RAND = prelude.HASHES["rand"]
NET = prelude.HASHES["net"]

MAYBE = corpus_registry.HASHES["Maybe"]
PAIR = corpus_registry.HASHES["Pair"]
LIST = corpus_registry.HASHES["List"]

ADD = corpus_registry.EXTERN_HASHES["I64.add"]
SUB = corpus_registry.EXTERN_HASHES["I64.sub"]

UNIT_TYPE = [0, 0]
I64_TYPE = [0, 2]
BYTES_TYPE = [0, 5]


def app(head, *arguments):
    """A saturated `app` spine, as `corpus_registry` writes one."""
    for argument in arguments:
        head = [4, head, argument]
    return head


def nothing():
    return Constructor(MAYBE, 0, ())


def just(value):
    return Constructor(MAYBE, 1, (value,))


#: Built once. `corpus_interpreter()` rebuilds both on every call, which is the
#: right default for a caller but 30 ms of re-parsing per test here. Each test
#: still gets its own `Interpreter`, so the definition-value cache stays
#: per-test; only the immutable snapshots are shared.
_DECLARATIONS = corpus_registry.registry()
_TERMS = corpus_definition_terms()


def machine_for(builtins=None, fuel=interp.DEFAULT_FUEL):
    return Interpreter(
        _DECLARATIONS,
        reference_term=_TERMS.reference_term,
        externs=interp.DEFAULT_EXTERNS,
        builtins=builtins,
        fuel=fuel,
    )


class CorpusFixture(unittest.TestCase):
    """Base class holding one interpreter over the whole bootstrap corpus."""

    builtins: dict = {}

    def setUp(self):
        self.machine = machine_for(builtins=dict(self.builtins))

    def definition(self, name_path):
        return self.machine.value_of(corpus_digest(name_path))

    def call(self, name_path, *arguments):
        return self.machine.apply(self.definition(name_path), *arguments)

    def i64_minus(self):
        """A Loom `\\a b -> a - b`, built from the assumed base."""
        return self.machine.evaluate([3, I64_TYPE, [3, I64_TYPE, app([1, SUB], [0, 1], [0, 0])]])

    def i64_plus(self, amount):
        """A Loom `\\x -> x + amount`."""
        return self.machine.evaluate([3, I64_TYPE, app([1, ADD], [0, 0], [2, 2, amount])])


# --------------------------------------------------------------------------
# The corpus runs
# --------------------------------------------------------------------------


class PureCorpusTest(CorpusFixture):
    """Every pure fixture, against results computed by hand."""

    def test_every_fixture_evaluates_to_a_value(self):
        """All 26 seeds reach a value; none needs an argument to get there,
        because a definition's own term is closed (§3.1.2)."""
        for entry in corpus_registry.MANIFEST:
            with self.subTest(definition=entry.name_path):
                value = self.definition(entry.name_path)
                self.assertIsInstance(value, interp.Value)

    def test_the_public_factory_wires_the_corpus_the_same_way(self):
        """`machine_for` shares immutable snapshots for speed; this pins that it
        is the same machine `corpus_interpreter()` builds from scratch."""
        machine = corpus_interpreter()
        self.assertEqual(
            machine.apply(machine.value_of(corpus_digest("corpus/list/append")),
                          i64_list([1]), i64_list([2])),
            self.call("corpus/list/append", i64_list([1]), i64_list([2])),
        )

    def test_definition_term_registry_covers_the_manifest(self):
        terms = corpus_definition_terms()
        self.assertEqual(len(terms), len(corpus_registry.MANIFEST))
        for entry in corpus_registry.MANIFEST:
            self.assertIn(bytes.fromhex(entry.identity), terms)

    def test_bool_not(self):
        self.assertEqual(self.call("corpus/bool/not", interp.TRUE), interp.FALSE)
        self.assertEqual(self.call("corpus/bool/not", interp.FALSE), interp.TRUE)

    def test_fold_right_over_a_real_list(self):
        """`foldRight (-) 0 [1,2,3]` associates to the right: 1-(2-(3-0)) = 2."""
        result = self.call("corpus/list/foldRight", self.i64_minus(), i64(0), i64_list([1, 2, 3]))
        self.assertEqual(result, i64(2))

    def test_fold_left_over_a_real_list(self):
        """`foldLeft (-) 0 [1,2,3]` associates to the left: ((0-1)-2)-3 = -6."""
        result = self.call("corpus/list/foldLeft", self.i64_minus(), i64(0), i64_list([1, 2, 3]))
        self.assertEqual(result, i64(-6))

    def test_fold_right_and_fold_left_disagree(self):
        """The two folds are distinguishable only by running them, which is the
        whole point of this module existing."""
        arguments = (self.i64_minus(), i64(0), i64_list([1, 2, 3]))
        self.assertNotEqual(
            self.call("corpus/list/foldRight", *arguments),
            self.call("corpus/list/foldLeft", *arguments),
        )

    def test_append(self):
        result = self.call("corpus/list/append", i64_list([1, 2]), i64_list([3, 4]))
        self.assertEqual(python_i64_list(result), [1, 2, 3, 4])

    def test_append_with_an_empty_side(self):
        self.assertEqual(python_i64_list(self.call("corpus/list/append", i64_list([]), i64_list([3]))), [3])
        self.assertEqual(python_i64_list(self.call("corpus/list/append", i64_list([3]), i64_list([]))), [3])

    def test_reverse(self):
        result = self.call("corpus/list/reverse", i64_list([1, 2, 3]))
        self.assertEqual(python_i64_list(result), [3, 2, 1])

    def test_reverse_of_empty(self):
        self.assertEqual(python_i64_list(self.call("corpus/list/reverse", i64_list([]))), [])

    def test_map(self):
        result = self.call("corpus/list/map", self.i64_plus(10), i64_list([1, 2, 3]))
        self.assertEqual(python_i64_list(result), [11, 12, 13])

    def test_concat(self):
        """`concat` is a `ref` into `append`: the resolver has to supply a
        *body*, not just a type, for this to produce anything."""
        result = self.call("corpus/list/concat", i64_list([1, 2]), i64_list([3]))
        self.assertEqual(python_i64_list(result), [1, 2, 3])

    def test_flat_map(self):
        duplicate = self.machine.evaluate(
            [3, I64_TYPE, [6, LIST, 1, [[0, 0], [6, LIST, 1, [[0, 0], [6, LIST, 0, []]]]]]]
        )
        result = self.call("corpus/list/flatMap", duplicate, i64_list([1, 2]))
        self.assertEqual(python_i64_list(result), [1, 1, 2, 2])

    def test_length_nat_goes_through_the_list_size_extern(self):
        self.assertEqual(self.call("corpus/list/lengthNat", i64_list([1, 2, 3])), i64(3))
        self.assertEqual(self.call("corpus/list/lengthNat", i64_list([])), i64(0))

    def test_uncons(self):
        result = self.call("corpus/list/uncons", i64_list([7, 8]))
        self.assertEqual(result.data, MAYBE)
        self.assertEqual(result.index, 1)
        pair = result.fields[0]
        self.assertEqual(pair.data, PAIR)
        self.assertEqual(pair.fields[0], i64(7))
        self.assertEqual(python_i64_list(pair.fields[1]), [8])

    def test_uncons_of_empty(self):
        self.assertEqual(self.call("corpus/list/uncons", i64_list([])), nothing())

    def test_cons_nat(self):
        result = self.call("corpus/list/consNat", i64(3), i64_list([1]))
        self.assertEqual(python_i64_list(result), [3, 1])

    def test_maybe_is_nothing(self):
        self.assertEqual(self.call("corpus/maybe/isNothing", nothing()), interp.TRUE)
        self.assertEqual(self.call("corpus/maybe/isNothing", just(i64(5))), interp.FALSE)

    def test_maybe_get_or_else(self):
        self.assertEqual(self.call("corpus/maybe/getOrElse", i64(9), nothing()), i64(9))
        self.assertEqual(self.call("corpus/maybe/getOrElse", i64(9), just(i64(5))), i64(5))

    def test_maybe_map(self):
        self.assertEqual(self.call("corpus/maybe/map", self.i64_plus(10), nothing()), nothing())
        self.assertEqual(self.call("corpus/maybe/map", self.i64_plus(10), just(i64(1))), just(i64(11)))

    def test_nat_widen_pos_is_the_identity(self):
        self.assertEqual(self.call("corpus/nat/widenPos", i64(4)), i64(4))

    def test_nat_apply_pos(self):
        self.assertEqual(self.call("corpus/nat/applyPos", self.i64_plus(1), i64(2)), i64(3))

    def test_nat_select(self):
        self.assertEqual(self.call("corpus/nat/select", interp.TRUE, i64(1), i64(2)), i64(1))
        self.assertEqual(self.call("corpus/nat/select", interp.FALSE, i64(1), i64(2)), i64(2))

    def test_a_long_recursion_does_not_touch_the_python_stack(self):
        """The machine is a loop, not a recursive function, so control depth is
        Loom's business. A recursive-descent or CPS evaluator raises
        `RecursionError` here well before the fuel guard fires."""
        values = list(range(2000))
        result = self.call("corpus/list/reverse", i64_list(values))
        self.assertEqual(python_i64_list(result), list(reversed(values)))


class PolymorphismTest(CorpusFixture):
    """§3.1.3: a definition typed `forall^p T` *is* its type abstraction, and no
    term node abstracts or applies a type — so instantiation is erased at runtime
    with nothing to erase, and the value of a quantified `ref` is its body's."""

    def test_map_poly_behaves_exactly_like_the_monomorphic_map(self):
        for argument in (nothing(), just(i64(1)), just(i64(-7))):
            with self.subTest(argument=argument):
                self.assertEqual(
                    self.call("corpus/maybe/mapPoly", self.i64_plus(10), argument),
                    self.call("corpus/maybe/map", self.i64_plus(10), argument),
                )

    def test_map_poly_is_not_restricted_to_i64_at_runtime(self):
        """Parametricity is structural (§3.1.3): nothing observes the element,
        so the same value maps a `Bytes` payload with no instantiation step."""
        constant = self.machine.evaluate([3, [5, 1], [2, 5, b"\xab"]])
        result = self.call("corpus/maybe/mapPoly", constant, just(Literal(4, "x")))
        self.assertEqual(result, just(Literal(5, b"\xab")))


# --------------------------------------------------------------------------
# Effects, capabilities, and the absence of ambient authority
# --------------------------------------------------------------------------


class EffectTest(CorpusFixture):
    builtins = {}

    def setUp(self):
        self.calls = []
        behaviours = {}
        clock = scripted_clock([1000, 2000, 3000, 4000])
        rand = seeded_rand(7)
        for key, behaviour in {**clock, **rand}.items():
            behaviours[key] = self._recording(key, behaviour)
        self.machine = machine_for(builtins=behaviours)
        self.clock_cap = self.machine.mint_capability(CLOCK, "clock")
        self.rand_cap = self.machine.mint_capability(RAND, "rand")

    def _recording(self, key, behaviour):
        def wrapper(arguments, path):
            self.calls.append(key)
            return behaviour(arguments, path)

        return wrapper

    def test_clock_now(self):
        self.assertEqual(self.call("corpus/clock/now", self.clock_cap), i64(1000))

    def test_clock_now_pair_calls_the_clock_twice_through_a_ref(self):
        result = self.call("corpus/clock/nowPair", self.clock_cap)
        self.assertEqual(result, Constructor(PAIR, 0, (i64(1000), i64(2000))))
        self.assertEqual(self.calls, [(CLOCK, 0), (CLOCK, 0)])

    def test_clock_stamped_runs_a_callback_that_performs(self):
        callback = self.machine.evaluate([3, UNIT_TYPE, [8, CLOCK, 0, []]])
        result = self.call("corpus/clock/stamped", self.clock_cap, callback)
        self.assertEqual(result, Constructor(PAIR, 0, (i64(1000), i64(2000))))

    def test_rand_bytes_returns_exactly_the_requested_count(self):
        result = self.call("corpus/rand/bytes", self.rand_cap, i64(4))
        self.assertIsInstance(result, Literal)
        self.assertEqual(result.kind, interp.KIND_BYTES)
        self.assertEqual(len(result.value), 4)

    def test_rand_bytes_of_a_negative_count_is_empty(self):
        """§2.4: `rand.bytes n` returns exactly `max(n, 0)` bytes."""
        result = self.call("corpus/rand/bytes", self.rand_cap, i64(-3))
        self.assertEqual(result.value, b"")

    def test_evaluation_order_is_encoding_order(self):
        """`sample/nowAndBytes` is `Pair (perform clock…) (perform rand…)`. §2
        does not fix an order, so the evaluator takes CBOR field order (§R1) —
        and that decision is observable, so it is pinned here."""
        self.call("corpus/sample/nowAndBytes", self.clock_cap, self.rand_cap)
        self.assertEqual(self.calls, [(CLOCK, 0), (RAND, 0)])

    def test_a_capability_is_minted_only_by_the_runtime(self):
        capability = self.machine.mint_capability(CLOCK)
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.ability, CLOCK)

    def test_minting_refuses_an_ability_the_registry_does_not_know(self):
        with self.assertRaises(EvaluationError) as caught:
            self.machine.mint_capability(b"\x00" * 32)
        self.assertIn("ability", str(caught.exception))

    def test_no_corpus_definition_evaluates_to_a_capability(self):
        """§2.4: a capability is "never constructible in the language"."""
        for entry in corpus_registry.MANIFEST:
            with self.subTest(definition=entry.name_path):
                self.assertNotIsInstance(self.definition(entry.name_path), Capability)


class NoAmbientAuthorityTest(CorpusFixture):
    """The evaluator ships no clock and no entropy (§2.4, §R8)."""

    def test_an_unhandled_perform_is_an_error_with_a_path(self):
        machine = machine_for()
        capability = machine.mint_capability(CLOCK)
        with self.assertRaises(UnhandledOperation) as caught:
            machine.apply(machine.value_of(corpus_digest("corpus/clock/now")), capability)
        self.assertIn(CLOCK.hex(), str(caught.exception))
        self.assertTrue(caught.exception.path)

    def test_the_default_builtin_table_is_empty(self):
        machine = machine_for()
        self.assertEqual(dict(machine.builtins), {})

    def test_a_behaviour_for_a_different_operation_does_not_answer(self):
        machine = machine_for(builtins=scripted_clock([1]))
        capability = machine.mint_capability(RAND)
        with self.assertRaises(UnhandledOperation):
            machine.apply(machine.value_of(corpus_digest("corpus/rand/bytes")), capability, i64(1))


class AbiEnvelopeTest(unittest.TestCase):
    """§2.4's canonical runtime ABI envelope, `[status, payload]`."""

    def test_success_envelope(self):
        self.assertEqual(interp.abi_success(b"\x01").value, cbor_canonical.encode([0, b"\x01"]))
        self.assertEqual(interp.abi_success(b"\x01").value, bytes.fromhex("82004101"))

    def test_failure_envelope_carries_diagnostic_text(self):
        self.assertEqual(interp.abi_failure("no").value, cbor_canonical.encode([1, "no"]))

    def test_an_envelope_is_a_bytes_literal(self):
        self.assertEqual(interp.abi_success(b"").kind, interp.KIND_BYTES)
        self.assertEqual(interp.abi_failure("x").kind, interp.KIND_BYTES)

    def test_a_caller_supplied_ability_can_answer_with_one(self):
        machine = machine_for(builtins={(NET, 0): lambda arguments, path: interp.abi_success(b"ok")})
        capability = machine.mint_capability(NET)
        result = machine.evaluate([8, NET, 0, [[2, 5, b"req"]]], (capability,))
        self.assertEqual(result.value, cbor_canonical.encode([0, b"ok"]))


# --------------------------------------------------------------------------
# Handlers: deep, and multi-shot
# --------------------------------------------------------------------------


def rand_handler(handled, operation_zero, return_clause):
    """`handle rand handled {0 -> …; 1 -> k 0} return`, the shape every
    tranche-3 handler fixture uses."""
    return [9, RAND, handled, [[0, operation_zero], [1, app([0, 0], [2, 2, 0])]], return_clause]


class HandlerTest(CorpusFixture):
    def test_rand_with_stub_replaces_the_operation_result(self):
        machine = machine_for()
        capability = machine.mint_capability(RAND)
        result = machine.apply(machine.value_of(corpus_digest("corpus/rand/withStub")), capability)
        self.assertEqual(result, Literal(interp.KIND_BYTES, b"\x00\x00\x00\x00"))

    def test_a_handled_fixture_needs_no_ambient_behaviour(self):
        """The handler discharges `rand` from the row (§3.1.2), so this runs on
        an interpreter with no entropy of any kind installed."""
        machine = machine_for()
        self.assertEqual(dict(machine.builtins), {})
        machine.apply(machine.value_of(corpus_digest("corpus/rand/withStub")), machine.mint_capability(RAND))

    def test_resample_invokes_one_continuation_twice_and_combines_both(self):
        """The acceptance test for the whole design.

        `corpus/rand/resample`'s clause body is
        `match (k 0x00) { Pair a b -> match (k 0xff) { Pair c d -> Pair a d } }`
        over a handler whose return clause is `\\r -> Pair r r`. The `0x00` can
        only come from the first invocation of `k` and the `0xff` only from the
        second, so `Pair 0x00 0xff` is unreachable for a one-shot continuation
        and unreachable for an implementation that re-executes from the start.

        §13's residue recorded this fixture as "operationally meaningless" in
        the prototype. It is not, any more.
        """
        machine = machine_for()
        capability = machine.mint_capability(RAND)
        result = machine.apply(machine.value_of(corpus_digest("corpus/rand/resample")), capability)
        self.assertEqual(
            result,
            Constructor(PAIR, 0, (Literal(interp.KIND_BYTES, b"\x00"), Literal(interp.KIND_BYTES, b"\xff"))),
        )

    def test_the_continuation_is_a_first_class_value(self):
        """Bind `k` through a `let` and invoke it after the clause body has
        already done other work: it is an ordinary value, not a control keyword."""
        machine = machine_for()
        # handle rand (perform rand.bytes 1) { 0 -> let f = k in f 0xaa } (\r -> r)
        clause = [5, [2, BYTES_TYPE, [], BYTES_TYPE], [0, 0], app([0, 0], [2, 5, b"\xaa"])]
        term = rand_handler([8, RAND, 0, [[2, 2, 1]]], clause, [0, 0])
        self.assertEqual(machine.evaluate(term), Literal(interp.KIND_BYTES, b"\xaa"))

    def test_handlers_are_deep_the_resumption_is_handled_again(self):
        """The continuation re-installs the handler frame, so a `perform` inside
        the resumption is caught by the *same* handler. Under shallow semantics
        the second `perform` here would escape and raise `UnhandledOperation`."""
        machine = machine_for()
        performed = [8, RAND, 0, [[2, 2, 1]]]
        term = rand_handler(
            [6, PAIR, 0, [performed, performed]],
            app([0, 0], [2, 5, b"\x01"]),
            [0, 0],
        )
        result = machine.evaluate(term)
        self.assertEqual(
            result,
            Constructor(PAIR, 0, (Literal(interp.KIND_BYTES, b"\x01"), Literal(interp.KIND_BYTES, b"\x01"))),
        )

    def test_the_innermost_handler_wins(self):
        machine = machine_for()
        inner = rand_handler([8, RAND, 0, [[2, 2, 1]]], app([0, 0], [2, 5, b"\x02"]), [0, 0])
        outer = rand_handler(inner, app([0, 0], [2, 5, b"\xee"]), [0, 0])
        self.assertEqual(machine.evaluate(outer), Literal(interp.KIND_BYTES, b"\x02"))

    def test_an_operation_clause_may_ignore_its_continuation(self):
        """Discarding `k` is abortive handling — the handled computation simply
        never resumes, and the clause's own value is the handler's result."""
        machine = machine_for()
        term = rand_handler([8, RAND, 0, [[2, 2, 1]]], [2, 5, b"\xcc"], [0, 0])
        self.assertEqual(machine.evaluate(term), Literal(interp.KIND_BYTES, b"\xcc"))

    def test_the_operation_parameters_bind_below_the_continuation(self):
        """§2.3.1: the clause "adds those parameters in signature order, then
        adds the resumption continuation as index 0; the last parameter is index
        1". `rand.bytes` has one parameter, so returning `var 1` from the clause
        returns the *argument the program performed with* — 41 here."""
        machine = machine_for()
        term = rand_handler([8, RAND, 0, [[2, 2, 41]]], [0, 1], [0, 0])
        self.assertEqual(machine.evaluate(term), i64(41))

    def test_the_return_clause_binds_the_handled_result_at_index_zero(self):
        machine = machine_for()
        term = rand_handler(
            [8, RAND, 0, [[2, 2, 1]]],
            app([0, 0], [2, 5, b"\x07"]),
            [6, PAIR, 0, [[0, 0], [0, 0]]],
        )
        self.assertEqual(
            machine.evaluate(term),
            Constructor(PAIR, 0, (Literal(interp.KIND_BYTES, b"\x07"), Literal(interp.KIND_BYTES, b"\x07"))),
        )

    def test_a_continuation_is_an_immutable_value(self):
        """A clause that simply returns `var 0` hands the continuation itself
        back as the handler's result — the sharpest way to look at one. Its
        frames are a frozen tuple, which is the property multi-shot resumption
        rests on (§R14): re-pushing them cannot observe a changed world."""
        machine = machine_for()
        term = rand_handler([8, RAND, 0, [[2, 2, 1]]], [0, 0], [0, 0])
        value = machine.evaluate(term)
        self.assertIsInstance(value, Continuation)
        self.assertIsInstance(value.frames, tuple)
        self.assertEqual(value.ability, RAND)
        self.assertEqual(value.operation, 0)
        with self.assertRaises(Exception):
            value.frames = ()

    def test_a_perform_inside_a_handler_for_another_ability_is_not_captured(self):
        """A `handle` discharges exactly one ability; a `clock` perform under a
        `rand` handler still needs a clock."""
        machine = machine_for()
        term = rand_handler([8, CLOCK, 0, []], app([0, 0], [2, 5, b"\x00"]), [0, 0])
        with self.assertRaises(UnhandledOperation) as caught:
            machine.evaluate(term)
        self.assertIn(CLOCK.hex(), str(caught.exception))


# --------------------------------------------------------------------------
# I64 wrapping — §3.2.1's fidelity limit, made executable
# --------------------------------------------------------------------------


class WrappingI64Test(CorpusFixture):
    def test_abs_at_int_min_is_negative(self):
        """The headline case.

        §3.2.1 states the gap from the solver's side: "`Int` does not wrap, so a
        proof that depends on 64-bit overflow is unsound", and lists `-` among
        the symbols "whose `Int` meaning departs from `I64`'s wrapping meaning".
        `corpus/math/abs` is `\\x -> if x < 0 then 0 - x else x` and its declared
        type claims `{v : I64 | -1 < v}`. At `INT_MIN` the subtraction wraps and
        the result is `INT_MIN` — negative, and a counterexample to the
        definition's own refinement.

        This is the proved-but-false-on-hardware case the obligation pipeline's
        reserved countermodel-validation rule exists to catch
        (`docs/plans/2026-08-13-obligation-pipeline.md`, "Rejected: concrete
        evaluation of the countermodel"): that rule needs an evaluator, and this
        is the evaluator. Enabling it is deliberately a separate change —
        `obligations.py` is untouched by this plan.
        """
        result = self.call("corpus/math/abs", i64(INT64_MIN))
        self.assertEqual(result, i64(INT64_MIN))
        self.assertLess(result.value, 0)

    def test_abs_is_correct_everywhere_else_that_matters(self):
        for argument, expected in ((-5, 5), (0, 0), (7, 7), (INT64_MIN + 1, INT64_MAX)):
            with self.subTest(argument=argument):
                self.assertEqual(self.call("corpus/math/abs", i64(argument)), i64(expected))

    def test_addition_wraps_at_the_top(self):
        result = self.machine.evaluate(app([1, ADD], [2, 2, INT64_MAX], [2, 2, 1]))
        self.assertEqual(result, i64(INT64_MIN))

    def test_subtraction_wraps_at_the_bottom(self):
        result = self.machine.evaluate(app([1, SUB], [2, 2, INT64_MIN], [2, 2, 1]))
        self.assertEqual(result, i64(INT64_MAX))

    def test_wrap_is_two_s_complement(self):
        self.assertEqual(interp.wrap_i64(2**63), INT64_MIN)
        self.assertEqual(interp.wrap_i64(-(2**63) - 1), INT64_MAX)
        self.assertEqual(interp.wrap_i64(0), 0)
        for value in (INT64_MIN, -1, 0, 1, INT64_MAX):
            self.assertEqual(interp.wrap_i64(value), value)


# --------------------------------------------------------------------------
# The assumed base
# --------------------------------------------------------------------------


class ExternTableTest(CorpusFixture):
    def test_the_default_table_is_exactly_the_assumed_base(self):
        """Both directions: no assumed-base extern lacks an implementation, and
        no implementation names a hash the assumed base does not have."""
        self.assertEqual(
            set(interp.DEFAULT_EXTERNS),
            set(corpus_registry.EXTERN_HASHES.values()),
        )
        self.assertEqual(len(interp.DEFAULT_EXTERNS), 9)

    def test_every_extern_reference_resolves_to_a_curried_value_of_the_right_arity(self):
        expected = {
            "I64.add": 2, "I64.sub": 2, "I64.eq": 2, "I64.lt": 2, "I64.le": 2,
            "Bool.and": 2, "Bool.or": 2, "Bool.not": 1, "List.size": 1,
        }
        for name, digest in corpus_registry.EXTERN_HASHES.items():
            with self.subTest(extern=name):
                value = self.machine.value_of(digest)
                self.assertIsInstance(value, ExternValue)
                self.assertEqual(value.arity, expected[name])

    def test_arithmetic_and_comparison_agree_with_the_smt_interpretation(self):
        cases = {
            "I64.add": (([2, 2, 2], [2, 2, 3]), i64(5)),
            "I64.sub": (([2, 2, 2], [2, 2, 3]), i64(-1)),
            "I64.eq": (([2, 2, 2], [2, 2, 2]), interp.TRUE),
            "I64.lt": (([2, 2, 2], [2, 2, 3]), interp.TRUE),
            "I64.le": (([2, 2, 3], [2, 2, 3]), interp.TRUE),
            "Bool.and": (([2, 1, True], [2, 1, False]), interp.FALSE),
            "Bool.or": (([2, 1, True], [2, 1, False]), interp.TRUE),
            "Bool.not": (([2, 1, True],), interp.FALSE),
        }
        for name, (arguments, expected) in cases.items():
            with self.subTest(extern=name):
                digest = corpus_registry.EXTERN_HASHES[name]
                self.assertEqual(self.machine.evaluate(app([1, digest], *arguments)), expected)

    def test_an_extern_partially_applied_stays_a_value(self):
        partial = self.machine.evaluate([4, [1, ADD], [2, 2, 1]])
        self.assertIsInstance(partial, ExternValue)
        self.assertEqual(partial.applied, (i64(1),))
        self.assertEqual(self.machine.apply(partial, i64(2)), i64(3))

    def test_list_size_walks_the_cons_spine(self):
        digest = corpus_registry.EXTERN_HASHES["List.size"]
        self.assertEqual(self.machine.apply(self.machine.value_of(digest), i64_list([1, 2, 3, 4])), i64(4))

    def test_list_size_refuses_a_non_list(self):
        digest = corpus_registry.EXTERN_HASHES["List.size"]
        with self.assertRaises(EvaluationError) as caught:
            self.machine.apply(self.machine.value_of(digest), i64(1))
        self.assertIn("List", str(caught.exception))

    def test_a_host_callback_may_re_enter_the_machine(self):
        """§5.1.3 provides for callback externs, so a host implementation can
        legitimately call back into the machine. The nested run must not disturb
        the outer run's in-progress reference resolution — a `ref` resolved
        after the callback returns still resolves."""
        holder = {}

        def callback(arguments, path):
            machine = holder["machine"]
            appended = machine.apply(
                machine.value_of(corpus_digest("corpus/list/append")),
                i64_list([1]), i64_list([2]),
            )
            return i64(len(python_i64_list(appended)))

        machine = machine_for(builtins={(NET, 0): callback})
        holder["machine"] = machine
        one = [6, LIST, 1, [[2, 2, 1], [6, LIST, 0, []]]]
        two = [6, LIST, 1, [[2, 2, 2], [6, LIST, 0, []]]]
        term = [6, PAIR, 0, [
            [8, NET, 0, [[2, 5, b"x"]]],
            app([1, corpus_digest("corpus/list/concat")], one, two),
        ]]
        result = machine.evaluate(term)
        self.assertEqual(result.fields[0], i64(2))
        self.assertEqual(python_i64_list(result.fields[1]), [1, 2])

    def test_an_extern_with_no_implementation_is_refused(self):
        machine = Interpreter(corpus_registry.registry(), externs={})
        with self.assertRaises(EvaluationError) as caught:
            machine.value_of(ADD)
        self.assertIn("implementation", str(caught.exception))

    def test_an_extern_argument_of_the_wrong_literal_kind_is_refused(self):
        with self.assertRaises(EvaluationError) as caught:
            self.machine.evaluate(app([1, ADD], [2, 2, 1], [2, 1, True]))
        self.assertIn("literal kind", str(caught.exception))


# --------------------------------------------------------------------------
# Recursion, fuel, and the things an evaluator refuses
# --------------------------------------------------------------------------


class FixAndFuelTest(CorpusFixture):
    def diverging(self):
        """`fix (I64 -> I64) 0 measure (\\x -> self x)` — total-looking, and not."""
        loop_type = [2, I64_TYPE, [], I64_TYPE]
        measure = [3, I64_TYPE, [2, 2, 0]]
        return [10, loop_type, 0, measure, [3, I64_TYPE, app([0, 1], [0, 0])]]

    def test_fuel_exhaustion_is_an_explicit_error_not_a_hang(self):
        """§2.5 makes totality an oracle obligation, so the evaluator must be
        able to run a wrongly-total term. It ends the run, with a path."""
        with self.assertRaises(FuelExhausted) as caught:
            self.machine.evaluate(app(self.diverging(), [2, 2, 1]), fuel=500)
        self.assertIn("step budget", str(caught.exception))
        self.assertTrue(caught.exception.path)

    def test_fuel_is_per_run_not_per_interpreter(self):
        self.machine.evaluate(app([1, ADD], [2, 2, 1], [2, 2, 1]), fuel=200)
        self.assertEqual(self.call("corpus/list/lengthNat", i64_list([1, 2])), i64(2))

    def test_a_run_that_needs_more_fuel_than_it_gets_fails_rather_than_truncating(self):
        with self.assertRaises(FuelExhausted):
            self.machine.apply(
                self.definition("corpus/list/reverse"), i64_list(list(range(50))), fuel=40
            )

    def test_the_measure_is_never_evaluated(self):
        """§2.5's measure is for the oracle; §3.1.5 says evaluation of `fix`
        does not consult it. A measure that *cannot* be evaluated — a hole — is
        therefore harmless, which is the sharpest way to state the rule."""
        loop_type = [2, I64_TYPE, [], I64_TYPE]
        unevaluable_measure = [11, [2, I64_TYPE, [], I64_TYPE], []]
        identity = [10, loop_type, 0, unevaluable_measure, [3, I64_TYPE, [0, 0]]]
        self.assertEqual(self.machine.evaluate(app(identity, [2, 2, 8])), i64(8))

    def test_the_position_field_is_never_consulted_either(self):
        """`k` names the decreasing argument for the oracle and binds nothing
        (§2.3.1), so an out-of-range `k` changes no runtime behaviour."""
        loop_type = [2, I64_TYPE, [], I64_TYPE]
        measure = [3, I64_TYPE, [2, 2, 0]]
        identity = [10, loop_type, 99, measure, [3, I64_TYPE, [0, 0]]]
        self.assertEqual(self.machine.evaluate(app(identity, [2, 2, 8])), i64(8))

    def test_a_fix_whose_body_demands_itself_is_a_clean_error(self):
        loop_type = [2, I64_TYPE, [], I64_TYPE]
        measure = [3, I64_TYPE, [2, 2, 0]]
        with self.assertRaises(EvaluationError) as caught:
            self.machine.evaluate([10, loop_type, 0, measure, [0, 0]])
        self.assertIn("before it is bound", str(caught.exception))


class RefusalTest(CorpusFixture):
    def test_a_hole_is_refused_with_a_path(self):
        with self.assertRaises(HoleRefused) as caught:
            self.machine.evaluate([11, I64_TYPE, []], path="draft")
        self.assertEqual(caught.exception.path, "draft")
        self.assertIn("draft region", str(caught.exception))

    def test_a_hole_nested_inside_a_reachable_branch_is_refused(self):
        term = [12, [2, 1, True], [11, I64_TYPE, []], [2, 2, 0]]
        with self.assertRaises(HoleRefused) as caught:
            self.machine.evaluate(term)
        self.assertIn(".then", caught.exception.path)

    def test_a_hole_in_an_unreachable_branch_never_runs(self):
        """Call-by-value evaluates what it reaches, and only that."""
        term = [12, [2, 1, True], [2, 2, 5], [11, I64_TYPE, []]]
        self.assertEqual(self.machine.evaluate(term), i64(5))

    def test_an_unresolved_reference_is_refused_never_guessed(self):
        machine = Interpreter(corpus_registry.registry())
        with self.assertRaises(UnresolvedReference) as caught:
            machine.value_of(b"\x11" * 32)
        self.assertIn("11" * 32, str(caught.exception))

    def test_a_resolver_that_returns_a_self_reference_is_a_cycle_not_a_hang(self):
        """Content addressing makes a real cycle unconstructible — a body cannot
        contain its own hash. This is the defensive path for a resolver that
        lies, and it fails fast instead of burning the fuel budget."""
        digest = b"\x22" * 32
        machine = Interpreter(
            corpus_registry.registry(),
            reference_term=lambda requested: [1, requested],
        )
        with self.assertRaises(ReferenceCycle) as caught:
            machine.value_of(digest)
        self.assertIn(digest.hex(), str(caught.exception))

    def test_applying_a_non_function_is_refused(self):
        with self.assertRaises(EvaluationError) as caught:
            self.machine.evaluate(app([2, 2, 1], [2, 2, 2]))
        self.assertIn("cannot apply", str(caught.exception))

    def test_a_non_bool_condition_is_refused(self):
        with self.assertRaises(EvaluationError) as caught:
            self.machine.evaluate([12, [2, 2, 1], [2, 2, 1], [2, 2, 0]])
        self.assertIn("Bool", str(caught.exception))

    def test_a_match_on_a_non_constructor_is_refused(self):
        with self.assertRaises(EvaluationError) as caught:
            self.machine.evaluate([7, [2, 2, 1], [[0, 0, [2, 2, 0]]]])
        self.assertIn("constructor", str(caught.exception))

    def test_a_missing_arm_is_refused_rather_than_falling_through(self):
        scrutinee = [6, MAYBE, 0, []]
        with self.assertRaises(EvaluationError) as caught:
            self.machine.evaluate([7, scrutinee, [[1, 1, [2, 2, 0]]]])
        self.assertIn("no arm", str(caught.exception))

    def test_an_out_of_range_de_bruijn_index_is_refused(self):
        with self.assertRaises(EvaluationError) as caught:
            self.machine.evaluate([0, 3])
        self.assertIn("out of range", str(caught.exception))

    def test_an_unknown_term_tag_is_refused(self):
        with self.assertRaises(EvaluationError) as caught:
            self.machine.evaluate([13, 0])
        self.assertIn("unknown term tag", str(caught.exception))

    def test_a_definition_object_is_required_where_one_is_expected(self):
        with self.assertRaises(EvaluationError):
            self.machine.evaluate_definition([2, 2, 1])


# --------------------------------------------------------------------------
# Values, environments, and the immutability multi-shot rests on
# --------------------------------------------------------------------------


class ValueTest(CorpusFixture):
    def test_a_bool_literal_and_an_i64_literal_never_compare_equal(self):
        """Python's `bool` is an `int` subclass; §2.2's kinds are not."""
        self.assertNotEqual(Literal(interp.KIND_BOOL, True), Literal(interp.KIND_I64, 1))
        self.assertNotEqual(interp.FALSE, i64(0))

    def test_unit_carries_no_payload(self):
        """§2.2: `unit`'s node is the two-element array `[2, 0]`."""
        self.assertEqual(self.machine.evaluate([2, 0]), interp.UNIT)
        self.assertIsNone(interp.UNIT.value)

    def test_an_f64_literal_keeps_its_canonical_bytes(self):
        raw = bytes.fromhex("3ff0000000000000")
        value = self.machine.evaluate([2, 3, raw])
        self.assertEqual(value, Literal(interp.KIND_F64, raw))
        self.assertNotEqual(value, Literal(interp.KIND_BYTES, raw))

    def test_values_are_immutable(self):
        for value in (i64(1), Constructor(MAYBE, 0, ()), Capability(CLOCK)):
            with self.subTest(value=value):
                with self.assertRaises(Exception):
                    value.kind = 9

    def test_a_closure_captures_its_environment(self):
        outer = self.machine.evaluate([3, I64_TYPE, [3, I64_TYPE, app([1, ADD], [0, 1], [0, 0])]])
        add_two = self.machine.apply(outer, i64(2))
        self.assertIsInstance(add_two, Closure)
        self.assertEqual(self.machine.apply(add_two, i64(40)), i64(42))
        self.assertEqual(self.machine.apply(add_two, i64(0)), i64(2))

    def test_match_binders_put_the_last_field_at_index_zero(self):
        """§2.3.1, checked directly: `Pair a b` with arm body `var 0` yields the
        *second* field, and `var 1` the first."""
        scrutinee = [6, PAIR, 0, [[2, 2, 10], [2, 2, 20]]]
        self.assertEqual(self.machine.evaluate([7, scrutinee, [[0, 2, [0, 0]]]]), i64(20))
        self.assertEqual(self.machine.evaluate([7, scrutinee, [[0, 2, [0, 1]]]]), i64(10))

    def test_let_binds_only_in_its_body(self):
        term = [5, I64_TYPE, [2, 2, 7], app([1, ADD], [0, 0], [2, 2, 1])]
        self.assertEqual(self.machine.evaluate(term), i64(8))

    def test_an_environment_supplied_by_the_caller_starts_at_index_zero(self):
        self.assertEqual(self.machine.evaluate([0, 0], (i64(3), i64(4))), i64(3))
        self.assertEqual(self.machine.evaluate([0, 1], (i64(3), i64(4))), i64(4))

    def test_a_definition_value_is_cached_and_identical_across_uses(self):
        first = self.definition("corpus/list/append")
        second = self.definition("corpus/list/append")
        self.assertIs(first, second)

    def test_evaluate_source_runs_a_canonical_surface_directly(self):
        entry = next(e for e in corpus_registry.MANIFEST if e.name_path == "corpus/bool/not")
        value = self.machine.evaluate_source(entry.source_text().rstrip("\n"))
        self.assertEqual(self.machine.apply(value, interp.TRUE), interp.FALSE)

    def test_a_path_stays_bounded_under_tail_recursion(self):
        """Paths are diagnostics; an uncapped one would grow with the step count
        rather than the term. `contracts.py` does not cover path strings."""
        with self.assertRaises(FuelExhausted) as caught:
            self.machine.apply(self.definition("corpus/list/foldLeft"),
                               self.i64_minus(), i64(0), i64_list(list(range(400))), fuel=3000)
        self.assertLessEqual(len(caught.exception.path), interp._PATH_LIMIT + 1)


if __name__ == "__main__":
    unittest.main()
