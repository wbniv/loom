# Review of the effect-purity and documentation changes

**Date:** 2026-08-13

**Reviewed commits:** `fcb34bf` (`Fix effect purity soundness`) and `72736d0`
(`Add Loom-vs-Lisp doc; ignore session transcripts`)

**Verdict:** The soundness repair is correct and appropriately conservative.
No new correctness defect was found in the patch. Several documentation and
language-design edges should be resolved before extending the checker.

## Scope and verification

The review compared both commits with their parent revisions, inspected the
effect checker, declaration registry, tests, normative specification, plans,
README material, and the new Loom-versus-Lisp example.

Fresh verification on the reviewed tree produced:

```text
task prototype:test
Ran 64 tests in 0.045s
OK

LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test
GBNF PASS: 11 valid cases accepted; 11 invalid cases rejected

task todo:lint
TODO.md: clean

git diff --check
(exit 0)
```

## What improved

### The closure-escape bug is real and is now closed

Before `fcb34bf`, lambda synthesis inspected the body under the surrounding
ambient effect allowance but assigned the resulting function an empty effect
row. A lambda created inside a handler could therefore use the handled ability,
escape as a supposedly pure value, and later run outside the handler. That
directly contradicted the audit guarantee in `SPEC.md` §2.4.

Synthesizing a lambda body under `()` makes the implementation agree with the
empty row it assigns. The two regression tests cover both the complete escape
shape and the lower-level synthesis rule. This is the right minimal repair for
the current bidirectional subset.

### Operation-less abilities now have coherent semantics

Rejecting `handle` for an ability with no operations resolves a genuine
specification/checker disagreement. In particular, it prevents a vacuously
exhaustive `div` handler from making divergence disappear from the visible
effect row. The rule is stated normatively and tested at the public validation
boundary.

### The ancillary changes are disciplined

The match diagnostic change preserves nested error attribution instead of
rewriting every type mismatch in an arm. The registry optimization retains
isolation by copying the returned parameter and result types, while avoiding an
unnecessary copy of the whole verified ability declaration. Neither change
widens acceptance.

### The explanatory document is useful and honest about projection

`docs/loom-vs-lisp.md` correctly distinguishes the canonical surface from Lisp
and explicitly labels the indented example as a display projection rather than
an accepted alternative spelling. Ignoring `docs/transcripts/` also removes
session-local artifacts from repository status without hiding product source.

## Findings and recommendations

### P1 — Decide how effectful lambdas obtain an expected type

The new synthesis rule is sound but creates an intentional elaboration cliff:
an effectful lambda is accepted only where the checker already has an annotated
`fn` type against which to check it. The same lambda in synthesis position—even
inside a context that permits the effect—is rejected. A typed `let` can supply
that context today, but a direct application or another synthesis-only position
cannot.

This is acceptable for a prototype, and the plan acknowledges it, but it should
become an explicit language design decision rather than an implementation
accident. Before expanding application or polymorphism support, choose one of:

1. retain the rule and specify exactly which constructs propagate expected
   types;
2. add a type-ascription term that can carry a latent effect row; or
3. infer a closed latent row from a lambda body.

The first option best matches Loom's preference for canonical, predictable
checking. Add positive and negative examples to `SPEC.md`, including direct
application and typed `let`.

### P1 — Correct verification status bookkeeping

The effect-purity plan records the grammar step as “NOT RUN” while its header
says “Implemented and verified locally” and `docs/plans/README.md` reports
“Implemented; PASS.” The grammar was unchanged, so this is not evidence of a
code defect, but the recorded state is internally inconsistent.

The validator is available in this environment and the fresh run passes all 22
cases. Update the plan with that result rather than relying on a previous
milestone's result. Plans should use “PASS” only when every listed required
verification step either ran or is explicitly classified as not applicable.

### P2 — Make handler-row wording consistent

The effect-directed plan's completion criterion says the handled ability is
absent from the continuation's ambient row. `SPEC.md` §3.1.2 more precisely says
the continuation receives the **outer** ambient row, so an ability already
allowed outside remains present. The implementation follows the specification.

Change the plan criterion to say that the handler removes only the allowance it
introduces and that the continuation uses the unchanged outer row. This avoids
future reviewers “fixing” correct code to satisfy an over-broad criterion.

### P2 — Use canonical notation in the soundness counterexample

The effect-purity plan calls its counterexample accepted Loom but writes
`clock` where the canonical surface requires the ability's 32-byte hash. It is
clear to a human, yet it cannot be passed to the parser as shown. Either label
the block as schematic Loom or use the pinned clock hash and provide the actual
reproduction. Soundness reports benefit from executable counterexamples.

### P2 — Turn the larger documentation sample into a checked fixture

The larger program in `docs/loom-vs-lisp.md` currently validates, but no test
connects the prose block to the parser and type checker. It can drift as the
surface or builtin hashes change. Store its canonical one-line form under
`prototype/examples/` and include it in both round-trip and effect-directed
validation, or add a documentation-snippet test that extracts the canonical
block.

Prefer a fixture: it preserves one authoritative byte sequence and lets the
document link to it, as the smaller examples already do.

### P3 — Update the repository status claim

The root README still says “design fiction, unimplemented,” while the repository
now contains a working canonical parser, CBOR encoder, scope/reference
validators, builtin registry, and a partial bidirectional checker. The caveat
made sense at import time but now understates what exists.

Describe Loom as a design specification with a working validation prototype,
then enumerate the deliberately missing runtime, store, full type system,
refinement solver, and evidence oracle. This preserves honesty without
contradicting the rest of the repository.

## Recommended next milestone

Do a small documentation-and-fixture consistency pass before adding more type
rules:

1. amend the two plan inconsistencies and record the fresh GBNF PASS;
2. define the contextual-typing policy for effectful lambdas in `SPEC.md`;
3. promote the larger clock-handler example to a validated fixture; and
4. revise the root status paragraph to describe the implemented prototype
   boundary accurately.

After that, the next checker work should follow the language roadmap rather than
adding more local exceptions. Row polymorphism is the largest stated effect
boundary, but it should not begin until canonical row-variable instantiation
and contextual propagation rules have their own specification and plan.

## Resolution

Implemented on 2026-08-13 under the
[effect documentation and fixture consistency plan](../plans/2026-08-13-effect-documentation-fixture-consistency.md):

- `SPEC.md` now defines the contexts that propagate expected types and the
  deliberate rejection of effectful lambdas in synthesis-only positions.
- Tests cover both a typed-`let` acceptance case and direct-application
  rejection.
- Handler continuation wording and the purity plan's GBNF record are aligned
  with observed behavior.
- The clock-handler sample is the canonical `05_clock_handler` fixture and is
  covered by surface, scope, and effect-directed validation.
- The root README now describes the working prototype and its missing layers.

All 65 prototype tests and all 23 GBNF cases pass.
