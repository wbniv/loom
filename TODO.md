# TODO — loom

**Status markers:** `[ ]` open · `[wip]` in progress · `[verify]` implemented, verification
not yet run+recorded (run the linked plan's steps, paste raw output + PASS/FAIL back into
the plan, then promote) · `[x]` done (`## Done` only).

**Delegation tier:** the bracket also carries a `T0`–`T5` rank, tier last — `[T4]`,
`[wip T2]`, `[verify T3]`. It says how much *thinking* the item needs, and `/next` uses it
to dispatch to the cheapest model that can do the work:

| Tier | Work | Goes to |
|---|---|---|
| `T0` | Mechanical lookup — grep, count, "which file defines X" | haiku, read-only |
| `T1` | Mechanical edit with a known recipe | sonnet @ medium |
| `T2` | Bounded implementation — one module, clear spec | sonnet @ high |
| `T3` | Multi-file work against a settled plan — **default when unranked** | opus @ medium |
| `T4` | Design *and* implementation; unknown root cause | opus @ high |
| `T5` | Do it yourself inline — or it needs a human, hardware, or a vendor console | *(no agent)* |

Ranking is itself `T5`: the orchestrator assigns tiers inline and never delegates that
step, at any scale. Only `## Open` carries tiers — Watch, Parked and Done items are not
dispatchable, and an item returning from Watch or Parked is ranked fresh. Full rubric:
`~/CLAUDE.md` — Delegation.

Plan-first: non-trivial work gets a `docs/plans/YYYY-MM-DD-<topic>.md` and an entry here.
Check conformance with `task todo:lint`.

## Open

- [wip T4] <!-- agent:a78b419a50bbcf3fd --> **Decide definition-level polymorphism (corpus finding 1).** Rank-1 `forall`
  is uninhabitable by any `lam`: §2.3.1 checks terms at type depth 0, so a polymorphic
  signature's own parameter annotation is out of scope. Options: `tylam`/`tyapp` nodes
  (mask cost), thread the type's `forall` depth into the term, or declare Loom
  honestly monomorphic at definition level. See
  [plan](docs/plans/2026-08-13-bootstrap-corpus.md). (T4: core §2 design call.)

- [wip T4] <!-- agent:a78b419a50bbcf3fd --> **Decide the Bool elimination form (corpus finding 2).** `Bool` is a base type
  with no conditional and no nominal match, so `not`, `filter`, `contains` are
  inexpressible. Options: an `if` node, demoting Bool to prelude data, or accepting
  the gap. Deliberately not worked around with a corpus `Bool2`. (T4: core §2 design.)

- [wip T3] <!-- agent:acd6df31962cc59f2 --> **Specify the extern object encoding (§11; blocks corpus tranche 2).** §11's
  `extern` has no object encoding among §4.3's kinds, so assumed-base definitions
  (`I64.add`, `List.size`, …) cannot be stored. One new object kind, following the
  §5.3.1 authoring pattern.

- [wip T3] <!-- agent:a68fa054bbec849fc --> **Extend the type-directed layer to `fix` and `ref` (corpus finding 3).** Both
  pass scope/reference validation but have no match-layer typing rule, capping corpus
  recursion at the structural tier. Measures per §2.5; `ref` types resolved from the
  registry.

- [T5] **Confirm Unison base licensing before scaling the corpus past the seed set.**
  GitHub reports no machine-detectable license for unisonweb/base; nothing is vendored
  yet (three-line stdlib eliminators), but scaling needs written confirmation. (T5:
  needs a human decision outside the repo.)

## Watch

- Type-directed masking overhead (SPEC.md §8.2, §13 open problem 3) — how much
  pruning is affordable per emitted token is an empirical systems question; revisit
  once the S-expression grammar prototype (above) exists and can be benchmarked.

- Lease acquisition/renewal/expiry protocol for namespaces (SPEC.md §5.3, §13 open
  problem 4) — "a lease held by one agent or principal" has no protocol defined yet;
  revisit once agent-count assumptions are less speculative.

- Extensional-equality memo layer for intensional identity (SPEC.md §4.1, §13 open
  problem 5) — semantically identical definitions currently duplicate evidence effort;
  revisit once the memo ledger (§6.4) has real usage data showing this actually costs
  something.

_Nothing being watched. Entries here are plain bullets: what to check, how often, and the
trigger that promotes it back to Open._

## Parked

_Nothing parked. Entries here are plain bullets — intentionally shelved work, with the
condition that would unpark it._

## Done

- ✅ 2026-08-13 — [bootstrap-corpus] Chose Unison base, transpiled and validated 4 seed
  definitions, pinned 3 expressiveness limits as tests, specified tranches 2–4.
  See [plan](docs/plans/2026-08-13-bootstrap-corpus.md).
- ✅ 2026-08-13 — [policy-prototype] Implemented policy validation, satisfaction, and
  domination with 54 tests pinning the default hash and §12 arithmetic executable.
  See [plan](docs/plans/2026-08-13-policy-validation-prototype.md).
- ✅ 2026-08-13 — [effect-followups] Closed all eight review follow-ups: spec wording,
  status header, pinned tests, GBNF build recipe, imported sketch, fixed links.
  See [plan](docs/plans/2026-08-13-effect-consistency-followups.md).
- ✅ 2026-08-13 — [policy-object] Specified §5.3.1–§5.3.2 policy objects: rules and
  selectors, budgets, upward resolution over a pinned default, monotone amendment.
  See [plan](docs/plans/2026-08-13-namespace-policy-object.md).
- ✅ 2026-08-13 — [smtlib-rules] Specified §3.2.1 deterministic VC-to-SMT-LIB scripts
  and implemented the translator with 22 tests and explicit out-of-fragment refusal.
  See [plan](docs/plans/2026-08-13-refinement-smtlib-translation.md).
- ✅ 2026-08-13 — [evidence-bounds] Specified the A1 payload with generator, exact
  rational bound/confidence, Clopper–Pearson method, and partial-order rebind rules.
  See [plan](docs/plans/2026-08-13-evidence-confidence-bounds.md).
- ✅ 2026-08-13 — [effect-consistency] Specified contextual effectful-lambda
  checking, aligned effect plans, and promoted the clock-handler documentation
  sample to a round-trip and type-checked fixture. See
  [plan](docs/plans/2026-08-13-effect-documentation-fixture-consistency.md).
- ✅ 2026-08-13 — [effect-purity] Fixed effectful-closure escape (synthesized lambdas
  are now pure), banned handling operation-less abilities, with regression tests. See
  [plan](docs/plans/2026-08-13-effect-purity-soundness.md).
- ✅ 2026-08-13 — [effect-typing] Added closed-row effect-directed checking for
  function calls, operation signatures/capabilities, and exhaustive handlers
  with typed continuations. See
  [plan](docs/plans/2026-08-13-effect-directed-typing.md).
- ✅ 2026-08-13 — [nominal-match] Added parameterized constructor checking and
  exhaustive nominal match validation with verified binder types/order. See
  [plan](docs/plans/2026-08-13-nominal-match-validation.md).
- ✅ 2026-08-13 — [builtin-prelude] Pinned eight nominal builtin ability
  declarations, operation ABIs, hashes, and a preloaded verified registry. See
  [plan](docs/plans/2026-08-13-builtin-ability-prelude.md).
- ✅ 2026-08-13 — [declaration-objects] Added hashed data/ability declarations,
  recursive self types, a verified registry, and nominal bounds/arity checks. See
  [plan](docs/plans/2026-08-13-declaration-objects-reference-validation.md).
- ✅ 2026-08-13 — [stateful-scope] Specified every binder convention and added
  path-aware term/type de Bruijn validation with resolved handler arities. See
  [plan](docs/plans/2026-08-13-stateful-scope-validation.md).
- ✅ 2026-08-12 — [sexpr-grammar] Prototyped S-expr isomorph + canonical-CBOR
  transcoder; matches SPEC.md §4.4 worked-example hash exactly. See [prototype/](prototype/).
