# Review of recent Claude-authored Loom work

**Date:** 2026-08-13

**Scope:** `7776d05..3016ace`, including the bootstrap corpus, namespace policy
and evidence work, refinement translation, extern objects, definition-level
polymorphism and `if`, typed `fix`/`ref`, measure selection, and first-order
`forall` instantiation.

**Verdict:** This is ambitious, mostly disciplined work with unusually strong
plans and regression coverage. The new corpus is doing its intended job: it is
forcing underspecified language decisions into executable form. However, the
extern capability check has a real soundness hole that can bypass Loom's core
blast-radius guarantee. The interaction between forall instantiation and
externs also leaves the specification with an obsolete rationale. These should
be fixed before adding another corpus tranche.

## Verification performed

Fresh verification on `3016ace`:

```text
task prototype:test
Ran 231 tests in 0.161s
OK

LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test
GBNF PASS: 15 valid cases accepted; 16 invalid cases rejected

task todo:lint
TODO.md: clean

git diff --check 7776d05..HEAD
(exit 0)
```

The report also exercised two adversarial extern signatures directly against
`check_extern_type`; both were incorrectly accepted as capability-honest.

## Findings

### P1 — Extern capability validation counts unavailable capabilities

`prototype/declarations.py` collects every ability found in any effect row,
then separately collects capabilities recursively from every function-domain
type. It only compares the two sets. This loses both **value position** and
**application order**.

Consequently, both of these signatures are accepted:

```text
# Capability is buried inside a callback; the extern never receives cap a.
fn (fn (cap a) () Unit) -{a}-> Unit

# The effect occurs at the first application, before cap a is supplied.
fn Bytes -{a}-> (fn (cap a) () Bytes)
```

The first receives a function value that might accept a capability later, not a
capability value. The second can exercise `a` as soon as the first argument is
applied, while the matching capability is only a later curried argument. The
checker accepts both because `_capabilities_in` descends into nested function
types and `_domain_capabilities` scans the complete codomain spine.

This violates `SPEC.md` §5.1.3's stated purpose: an extern call is not a
`perform`, and ordinary application deliberately does not re-check capability
presence because normal functions may have captured it. An extern has no Loom
body or closure in which to capture one.

Recommendation: define capability honesty per arrow, not as whole-type set
containment. At each effectful arrow, every ability in that arrow's row must
already have a corresponding **direct `cap a` value among earlier curried
domains**, including the current domain if the call convention makes that value
available before the arrow's effect. Do not count capabilities nested inside
data or function types. Add the two signatures above as rejection tests plus
positive tests for one and several preceding direct capability parameters.

This requires coordinated edits to `SPEC.md`, `check_extern_type`, and
`test_externs.py`; changing only the traversal would leave the normative “in
some domain position” wording too weak.

### P1 — The polymorphic-extern rationale became false after forall instantiation

The extern specification and `check_extern_type` reject `forall` because “v0.1
has no term-level type application, so a polymorphic extern could never be used
at an instance.” That was true when the extern work landed. It stopped being
true in `d1159d9`: a quantified `ref` is now instantiated in any checking
position by matching it against an expected type. The rule is term-kind
agnostic; an extern reference would be just as usable through a typed `let` as a
definition reference if quantified extern types were admitted.

The restriction itself may still be desirable—foreign ABIs often need a
monomorphic representation—but the current justification contradicts the
implemented language.

Recommendation: make an explicit design choice. Either permit rank-1
polymorphic externs under the same checking-position instantiation rule, with a
specified ABI monomorphization contract, or retain the rejection because v0.1
extern ABIs are monomorphic. The latter is safer and smaller; update the spec,
implementation docstring, plan, and tests to use that reason rather than
claiming the value is unusable.

### P2 — Stored-definition reference typing remains a test-local facility

`MatchChecker` correctly injects a `ReferenceTypeResolver`, but the general
`DeclarationRegistry.reference_type()` resolves externs only. The polymorphic
definition test constructs a one-off hash-to-type lambda for `mapPoly`.
Therefore the feature proves the type rule but not a reusable store-facing path
from a stored definition hash to its validated declared type.

This is consistent with the prototype's “no store” boundary, so it is not a
checker defect. It is nevertheless easy to overread “a quantified ref can now
be called” as end-to-end repository functionality when only the rule and a test
adapter exist.

Recommendation: document the resolver trust contract next to
`ReferenceTypeResolver`: returned types must come from scope-validated stored
definitions, and resolver results must be immutable snapshots. Add a small
`DefinitionTypeRegistry` test double shared by `test_fix_ref.py` and
`test_instantiation.py`, or extend `corpus_registry` to resolve manifest
definition identities as well as externs. Do not fold definition objects into
`DeclarationRegistry`; its closed object-kind role is currently clear.

### P2 — Corpus attribution is inconsistent after the licensing cleanup

Commit `8e85730` standardized corpus provenance on the MIT-licensed
`unisonweb/unison` repository, but the later manifest entries for
`corpus/maybe/mapPoly` and `corpus/bool/not` say only “Unison base” and omit both
the repository and license. Other entries use the intended
“Unison (unisonweb/unison, MIT)” form.

This does not affect identity because provenance is metadata, but it partially
reintroduces the ambiguity the licensing commit was meant to close.

Recommendation: use the standardized source string for every Unison-derived
entry and add a manifest test requiring repository and license markers for
external-source fixtures. That makes future tranche additions fail locally
instead of relying on review memory.

### P2 — The change set is too broad for its recorded verification narratives

The range contains nearly eight thousand added lines across specification,
policy semantics, SMT translation, type checking, grammar, and corpus fixtures,
with several conflict-resolving merge commits. Individual plans report clean
baselines such as “214 pre-existing tests unchanged,” but concurrent branches
and merge resolution mean those statements are not equivalent to verifying the
integrated range.

The integrated tree does pass all current checks, which is good. What is missing
is one release-style record tying the final 231-test/31-grammar-case state to the
combined semantic changes and pinned identities.

Recommendation: add a single integration plan or release note after each corpus
tranche. It should record the full suite, grammar suite, golden identity,
manifest identities, and cross-module invariants after all merges. Keep the
feature plans, but do not treat their worktree-local baselines as the final
integration proof.

### P3 — Error taxonomy and module naming lag behind the checker’s scope

`matches.py` and `TypeDirectionError` began as nominal-match prototypes. The
module now implements lambdas, application, effects, handlers, `if`, `fix`,
references, and forall instantiation. Diagnostics still say “nominal match
layer” for unrelated failures.

This is not a semantic problem, but it makes new boundaries harder to describe
and encourages more unrelated rules to accumulate in one class.

Recommendation: before row polymorphism or another major term rule, rename the
module to `typing.py` and the error to `TypingError`, retaining compatibility
aliases for one milestone if useful. Separate instantiation and declaration
type substitution into focused helpers with direct unit tests. This is a
mechanical refactor; do it independently of new semantics.

## What was done well

- The corpus is effective as a design probe rather than a vanity example set.
  `if`, prenex polymorphism, reference typing, and measure selection each arose
  from a concrete blocked definition.
- Surface changes are costed against mask complexity and canonical identity,
  especially the `fix` position field.
- Unsupported behavior generally fails explicitly: row polymorphism,
  synthesis-position forall elimination, nested quantifiers, unresolved
  references, and multi-argument measures are not silently guessed.
- The plans preserve rejected alternatives and explain why the chosen design is
  canonical, which will matter when these decisions are revisited.
- Tests pin both positive capabilities and deliberate limits instead of merely
  deleting obsolete failure cases.

## Recommended order of work

1. Fix extern capability honesty and add adversarial tests.
2. Reword or redesign polymorphic extern handling in light of instantiation.
3. Normalize corpus provenance and enforce it in the manifest tests.
4. Add an integrated tranche verification record.
5. Refactor `matches.py` before expanding the type system further.

The first two belong in one small spec-and-validator milestone because they both
change the contract at the foreign boundary. The remaining items can follow
without blocking correctness.

## Resolution

All findings were implemented on 2026-08-13 under the
[Claude review remediation and tranche integration plan](../plans/2026-08-13-claude-review-remediation.md):

- Extern capability honesty is now checked per arrow in application order;
  nested and too-late capabilities have regression tests.
- Externs remain monomorphic because v0.1 has no ABI monomorphization contract,
  not because quantified references are unusable.
- `DefinitionTypeRegistry` supplies immutable, scope-validated definition types
  and the corpus resolver now covers manifest definitions as well as externs.
- Every Unison-derived manifest entry names `unisonweb/unison` and MIT, enforced
  by a corpus test.
- Integrated verification records 237 tests, 31 grammar cases, pinned
  identities, compilation, lint, and diff checks.
- The checker is now `typecheck.py` with `TypingError`; `matches.py` remains a
  compatibility shim. The name avoids shadowing Python's standard `typing`
  module.
