# TODO — loom

<!-- todo-lint: disable=open-rank -->
<!-- 2026-08-12: escape hatch for the five unranked items below, added while running
     as Sonnet 5 (ranking is Fable-only). Re-rank on next Fable pass, then remove this
     disable — do not let it become house convention. -->

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

- [ ] **Specify the namespace policy object format (SPEC.md §5.3, §6.2 gap).**
  `policy-ref` (§5.3) and "policy allows"/"policy-required properties" (§6.2) are used
  normatively but the policy object itself — what a `stats/POLICY`-style definition
  actually contains (required evidence levels per obligation kind, allowed assumption
  counts per §11, lease rules) — is never specified. Blocks any real store
  implementation, since §6.3's monotone-rebind check needs a policy to check against.

- [ ] **Define builtin ability signatures — a reference prelude (SPEC.md §2.4 gap).**
  `clock`, `rand`, `fsRead`, `fsWrite`, `net`, `spawn`, `div`, `ffi` are named as
  well-known hashes but no operation signature is given for any of them. Needed before
  §8's generation loop or §11's FFI boundary can be exercised even hypothetically.

- [ ] **Define the refinement-to-SMT-LIB translation rules (SPEC.md §3.2 gap).** §3.2
  names the target fragment (QF_UFLIRA + datatypes) but not the encoding rules from
  Loom refinement terms to SMT-LIB terms. Needed before an `A3 proof` obligation
  (§6.1) can actually be discharged by a solver rather than asserted.

- [ ] **Bootstrap-corpus plan for open problem 1 (SPEC.md §13, prior starvation).**
  Concrete version of "transpile verified existing code": pick a small existing
  typed/verified corpus (candidates: a subset of Unison base, or F*/Idris examples)
  and sketch the transpilation into Loom canonical form, to seed both a training
  signal and the in-context few-shot examples §8.4 relies on for fluency.

- [ ] **Add explicit confidence-bound fields to the evidence schema (SPEC.md §13, open
  problem 6).** Extend the `A1 property` evidence payload (§6.1) beyond a bare run
  count to carry a stated failure-probability bound at a stated confidence, relative
  to a stated generator — makes policy thresholds (§5.3) numeric instead of positional
  without making the accept/refuse decision itself fuzzy (§3.4).

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

- ✅ 2026-08-13 — [stateful-scope] Specified every binder convention and added
  path-aware term/type de Bruijn validation with resolved handler arities. See
  [plan](docs/plans/2026-08-13-stateful-scope-validation.md).
- ✅ 2026-08-12 — [sexpr-grammar] Prototyped S-expr isomorph + canonical-CBOR
  transcoder; matches SPEC.md §4.4 worked-example hash exactly. See [prototype/](prototype/).


## Inbox — auto-captured plan deferrals

_Auto-added from plan "Out of scope"/"Deferred" sections at commit time. Triage each into M1/M2/etc. and delete it here — it will not come back._

<!-- BEGIN auto-captured-deferrals (managed by audit-plan-deferrals.sh — triage these into the curated sections above; the fingerprint ledger means a deleted item is NOT re-added) -->
- [verify] **2026-08-13-stateful-scope-validation** — Verification section present but no PASS recorded — run + record the steps. _from [2026-08-13-stateful-scope-validation.md](docs/plans/2026-08-13-stateful-scope-validation.md)_  <!-- fp:f4a42fd18b8a381c -->
<!-- END auto-captured-deferrals -->
