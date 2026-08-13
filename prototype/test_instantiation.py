"""Tests for §3.1.3 first-order `forall` instantiation.

A quantified `ref` — a term that synthesizes `forall^p T` — is instantiated by
matching `T` against an expected type wherever it is *checked*, most often
because a typed `let` names that expected type explicitly (§3.1.3). Synthesis
position is untouched: a quantified reference used as an application's
function, say, still synthesizes its quantified type verbatim.
"""

from __future__ import annotations

import unittest

import corpus_registry
import references
import scope
from definition_types import DefinitionTypeRegistry
from typecheck import TypingError, validate_source
from transcode import parse_source

I64 = [0, 2]
BOOL = [0, 1]


def resolver(mapping):
    """A store stand-in: a hash-to-type mapping that raises on a miss."""
    return lambda digest: mapping[digest]


class InstantiationTest(unittest.TestCase):
    def setUp(self):
        self.registry = corpus_registry.registry()
        self.maybe = corpus_registry.HASHES["Maybe"].hex()
        # forall a. a -> a
        self.identity_hash = b"i" * 32
        self.identity_type = [6, [2, [5, 0], [], [5, 0]]]
        entry = next(e for e in corpus_registry.MANIFEST if e.name_path == "corpus/maybe/mapPoly")
        self.mappoly_hash = bytes.fromhex(entry.identity)
        self.mappoly_type = parse_source(entry.source_text())[1]
        self.mappoly_resolve = corpus_registry.reference_type(self.registry)

    def definition(self, type_surface: str, term_surface: str) -> str:
        return f"(def {type_surface} {term_surface})"

    def assert_type_error(self, source: str, message: str, reference_type) -> None:
        with self.assertRaises(TypingError) as caught:
            validate_source(source, self.registry, reference_type)
        self.assertIn(message, str(caught.exception))

    def test_monomorphic_instantiation_via_typed_let(self):
        # `let (I64 -> I64) = ref identity in ...` instantiates `forall a. a
        # -> a` at `I64` by matching the body `tyvar 0 -> tyvar 0` against the
        # `let`'s annotation, exactly where §3.1.2 already supplies a row.
        ident = f"(ref 0x{self.identity_hash.hex()})"
        term = f"(let (fn I64 () I64) {ident} (app (var 0) (lit i64 1)))"
        source = self.definition("I64", term)
        validate_source(source, self.registry, resolver({self.identity_hash: self.identity_type}))

    def test_mappoly_instantiated_at_i64_is_a_proof_definition(self):
        # §13's residue: `corpus/maybe/mapPoly` was writable but not
        # instantiable. Calling it at `I64` through a typed `let` — validated
        # through scope, references, and the match layer — is the proof that
        # instantiation closes that gap.
        maybe_i64 = f"(data 0x{self.maybe} (I64))"
        instance = f"(fn (fn I64 () I64) () (fn {maybe_i64} () {maybe_i64}))"
        call = f"(ref 0x{self.mappoly_hash.hex()})"
        term = (
            f"(lam (fn I64 () I64) "
            f"(lam {maybe_i64} "
            f"(let {instance} {call} (app (app (var 0) (var 2)) (var 1)))))"
        )
        source = self.definition(instance, term)

        scope.validate_source(source, self.registry.operation_arity)
        references.validate_source(source, self.registry)
        validate_source(source, self.registry, self.mappoly_resolve)

    def test_corpus_resolver_returns_isolated_validated_definition_types(self):
        first = self.mappoly_resolve(self.mappoly_hash)
        first.clear()
        self.assertEqual(self.mappoly_resolve(self.mappoly_hash), self.mappoly_type)

    def test_definition_type_registry_rejects_unscoped_and_misidentified_input(self):
        types = DefinitionTypeRegistry(self.registry.operation_arity)
        with self.assertRaises(scope.ScopeError):
            types.add_source("(def I64 (var 0))")
        with self.assertRaisesRegex(ValueError, "does not match canonical hash"):
            types.add_source("(def I64 (lit i64 1))", b"x" * 32)

    def test_polymorphic_caller_instantiates_with_its_own_type_variable(self):
        # A caller polymorphic in its own `a` calls mapPoly at that same `a`,
        # collapsing mapPoly's two variables to one. The expected type's
        # `tyvar 0` nodes are the *caller's* binder — opaque to this layer,
        # never substituted — and bind like any other concrete subtree.
        maybe_a = f"(data 0x{self.maybe} ((tyvar 0)))"
        instance = f"(fn (fn (tyvar 0) () (tyvar 0)) () (fn {maybe_a} () {maybe_a}))"
        caller_type = f"(forall {instance})"
        call = f"(ref 0x{self.mappoly_hash.hex()})"
        term = (
            f"(lam (fn (tyvar 0) () (tyvar 0)) "
            f"(lam {maybe_a} "
            f"(let {instance} {call} (app (app (var 0) (var 2)) (var 1)))))"
        )
        source = self.definition(caller_type, term)
        validate_source(source, self.registry, self.mappoly_resolve)

    def test_inconsistent_binding_is_rejected(self):
        # mapPoly's `tyvar 1` would have to be both `I64` (from the function
        # argument's domain) and `Bool` (from the option argument) — no
        # single binding satisfies both occurrences.
        instance = f"(fn (fn I64 () I64) () (fn (data 0x{self.maybe} (Bool)) () (data 0x{self.maybe} (I64))))"
        source = self.definition(instance, f"(ref 0x{self.mappoly_hash.hex()})")
        self.assert_type_error(source, "matched both", self.mappoly_resolve)

    def test_unbound_type_variable_is_rejected(self):
        # `forall a. Unit -> I64` never mentions `a` in its body, so nothing
        # in the expected type can supply a binding for it.
        const_hash = b"c" * 32
        const_type = [6, [2, [0, 0], [], I64]]
        source = self.definition("(fn Unit () I64)", f"(ref 0x{const_hash.hex()})")
        self.assert_type_error(source, "were never matched", resolver({const_hash: const_type}))

    def test_structural_mismatch_is_rejected(self):
        # `forall a. a -> a` has no first-order match against a non-function
        # expected type: a `fn` pattern cannot match a `base` target.
        source = self.definition("I64", f"(ref 0x{self.identity_hash.hex()})")
        self.assert_type_error(source, "cannot match", resolver({self.identity_hash: self.identity_type}))

    def test_row_variable_in_a_quantified_type_is_refused_explicitly(self):
        # §3.1.3's rule substitutes types only; a row variable inside the
        # quantified body is row polymorphism, which stays unimplemented and
        # must fail explicitly rather than being silently matched away.
        row_poly_hash = b"r" * 32
        row_poly_type = [6, [2, I64, [[5, 0]], I64]]
        source = self.definition("(fn I64 () I64)", f"(ref 0x{row_poly_hash.hex()})")
        self.assert_type_error(
            source,
            "row-polymorphic effect checking is not implemented",
            resolver({row_poly_hash: row_poly_type}),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
