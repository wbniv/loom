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

- [wip T3] <!-- agent:a8627be33ae0b215c --> **Build corpus tranche 3: the effectful slice.** Unison ability code against
  §2.4's eight builtins, closed rows only, exercising `perform`, `handle`, and `cap`
  at tier `checked` — the tranche where the Unison-over-F* corpus choice pays off.
  Definition selection is open (the plan names the shape, not the list), and R8 says
  the per-definition cost stops falling here, so also record whether a transpiler
  tool is now warranted. See [plan](docs/plans/2026-08-13-bootstrap-corpus.md). (T3:
  multi-definition selection judgment plus a tool-threshold call, against a settled
  plan.)

- [T3] **Build corpus tranche 4: the refinement slice.** F*-sourced
  refinement-carrying definitions, transpiled type-first, non-dependent arrows only —
  the first tranche to generate `ensures` obligations and exercise §3.2.1 end to end
  (VC generation is refinement subtyping only, so scope what an obligation can
  actually discharge today and record the rest). See
  [plan](docs/plans/2026-08-13-bootstrap-corpus.md). (T3: source selection judgment
  plus the first obligations, against a settled plan; dispatch after tranche 3
  merges — same corpus files.)

## Watch

- Re-evaluate the production implementation language, then migrate the validation
  engine from Python according to that decision. Rust is the current leading
  candidate, not a predetermined outcome; compare at least Rust and one credible
  alternative against deterministic performance, memory safety, closed IR types,
  CBOR/WASM/SMT integration, deployment, ecosystem risk, and implementation cost.
  Promote this to Open when **either**: (a) two consecutive corpus tranches require
  no canonical IR/tag changes and the parser, scope, reference, and type-checking
  contracts are versioned; (b) type-directed masking or validation is integrated
  into an interactive generation loop; (c) the prototype must run as a persistent
  or security-sensitive service; or (d) profiling shows Python consumes at least
  25% of an agreed end-to-end latency budget. Record the language decision before
  implementation. Keep Python as the differential reference oracle; require the
  replacement to match acceptance, canonical CBOR bytes, hashes, and pinned fixture
  identities before it becomes authoritative.

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

Entries here are plain bullets: what to check, how often, and the trigger that
promotes it back to Open.

## Parked

_Nothing parked. Entries here are plain bullets — intentionally shelved work, with the
condition that would unpark it._

## Done

- ✅ 2026-08-13 — [corpus-tranche-2] Built six recursive fixtures at tier checked with
  the corpus's first ref dependency chain; concat's monomorphic wall recorded.
  See [plan](docs/plans/2026-08-13-corpus-tranche-2.md).
- ✅ 2026-08-13 — [callback-extern] Stated the callback-extern consequence in §5.1.3
  with the accepted/rejected test pair pinning the per-arrow rule's reach.
  See [plan](docs/plans/2026-08-13-callback-extern-consequence.md).
- ✅ 2026-08-13 — [claude-review-remediation] Hardened extern capability order,
  reconciled monomorphic ABIs with forall instantiation, added validated
  definition-type resolution and provenance enforcement, and renamed the
  expanded checker. See
  [plan](docs/plans/2026-08-13-claude-review-remediation.md).
- ✅ 2026-08-13 — [forall-instantiation] Implemented first-order instantiation of
  quantified refs in checking position; mapPoly-at-I64 proof definition validates.
  See [plan](docs/plans/2026-08-13-forall-instantiation.md).
- ✅ 2026-08-13 — [measure-selection] Added the `fix` position field `[10, T, k, m, b]`
  selecting the decreasing argument; `list/foldRight` reaches `checked` at k=2.
  See [plan](docs/plans/2026-08-13-measure-selection.md).
- ✅ 2026-08-13 — [poly-and-bool] Threaded `forall` depth into term checking (zero
  tags, prenex rank-1 enforced) and added `if` as tag 12; both corpus limits lifted.
  See [plan](docs/plans/2026-08-13-polymorphism-and-bool-elimination.md).
- ✅ 2026-08-13 — [extern-encoding] Specified kind-7 extern objects (§5.1.3) with
  capability-honest rows, five pinned corpus externs, and 29 tests; tranche 2 unblocked.
  See [plan](docs/plans/2026-08-13-extern-object-encoding.md).
- ✅ 2026-08-13 — [corpus-license] Re-sourced corpus attributions to the MIT-licensed
  unisonweb/unison main repo (metadata only, no identity change); scaling unblocked.
  See [plan](docs/plans/2026-08-13-bootstrap-corpus.md).
- ✅ 2026-08-13 — [fix-ref-typing] Added `fix` typing with measure-shape checking and
  resolver-backed `ref` typing (20 tests); corpus tier re-declared at merge.
  See [plan](docs/plans/2026-08-13-fix-ref-typing.md).
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
