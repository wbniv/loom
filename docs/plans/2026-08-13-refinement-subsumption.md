# Plan — §3.3 subsumption in `typecheck.py`

**Date:** 2026‑08‑13
**Status:** Implemented and verified locally
**TODO entry:** `[T2] Implement §3.3 subsumption in typecheck (unblocked by the
obligation pipeline)`
**Depends on:**
[The obligation pipeline, and what a `sat` verdict means](2026-08-13-obligation-pipeline.md)
(R1 — typing emits, never solves; `obligations.py`'s `subtyping_condition`/
`emit_condition`; residue 1, this plan), `SPEC.md` §3.2.1 (the VC unit,
`{x:T|φ} <: {x:T|ψ}`), §3.3 (refinement subtyping, admitted rather than
checked during typing)

## Objective

Residue 1 of the obligation-pipeline plan: `SPEC.md` §3.3 subsumption is
specified and the design fork that blocked it — whether typing may call a
solver — is closed (it may not; it emits), but `typecheck.py`'s `check`
method still meets a `refine` type only by structural equality
(`corpus_registry.MANIFEST`'s three `structural` tranche-4 entries). This
plan writes the subsumption rule: a checking-mode mismatch that survives
refinement erasure is a genuine type error exactly as before; one that
disappears under erasure is `{x:T|φ} <: {x:T|ψ}`, and typing *admits* it,
emitting an obligation rather than either rejecting or waiting for a verdict.

No visible surface (a typing rule, a manifest re-tier, tests), so this plan
carries no mockups.

## Rules

### R1 — Erasure agreement decides eligibility; one VC per differing position

**The rule.** When `check(term, expected, …)`'s existing structural-equality
test fails (`actual := synth(term, …) != expected`), and the existing
`forall`-instantiation fallback does not apply, a second fallback runs before
the final `type mismatch` failure: erase every `refine` node from both
`actual` and `expected` (§3.2.1's own erasure — recursively, including inside
`data` type arguments and `fn` domains/codomains) and compare the results.

- **Erasure disagrees** (a different base sort, a different data-type hash, a
  different `fn` shape): no subsumption applies. This is not a refinement
  question at all, and the original `type mismatch` fires exactly as before.
- **Erasure agrees**: `actual` and `expected` differ *only* by their
  refinement predicates, at one or more positions, and `actual` and `expected`
  are walked in parallel to find every one of them.

**One VC per position, not one for the outermost type.** §3.2.1 states the
translation unit as `{x:T|φ} <: {x:T|ψ}` — a single base type and a single
pair of predicates — not a whole composite type. A type can carry more than
one refinement (`Pair {n|φ₁} {n|φ₂}`, or a `fn` whose domain *and* codomain are
both independently refined), and each is its own claim with its own subtype
obligation; collapsing them into one VC over the outermost type would need a
conjunction the fragment does not ask for here and would obscure which half
of a composite mismatch is the one that actually needs discharging.
`test_subsumption.SubsumptionTest.test_multi_position_emission_within_one_type_comparison`
exercises this directly: `Pair(pos, pos)` checked against `Pair(nat, nat)`
emits two independent obligations, one per field, not one obligation about
the pair.

**A missing predicate is `true`, on either side.** §3.2.1: "a bare `T` is
`{x:T|true}`." Concretely:

- `actual` unrefined, `expected` refined (`corpus/math/abs`'s and
  `corpus/list/lengthNat`'s shape — the body synthesizes a plain `I64`, the
  codomain is `refine I64 (-1 < v)`): `weaker = true`, `stronger = ψ`.
- `actual` refined, `expected` unrefined — exactly §3.3's own `{x:T|φ} <: T`
  case: `weaker = φ`, `stronger = true`.

**Recursing into a refinement's own base.** After handling the predicate
difference (if any) at one position, the walk continues into that position's
base type (`refine T φ`'s `T` against the other side's corresponding base),
because `T` can itself carry a further refinement one level down. No corpus
fixture or synthetic test needs more than one level, but the walk is written
generally rather than assuming a fixed depth.

**Rejected: comparing whole types with one solver-visible predicate per
side, conjoining nested differences.** This would need constructing a
conjunction term (`and φ₁ φ₂ …`) that does not exist in the source and does
not correspond to a hypothesis or goal any part of the program actually
states — it would be checker-synthesized, not admitted from the term, and it
would also produce one obligation whose script mixes unrelated positions
(the pair's first field failing for a different reason than its second would
be reported as one indistinguishable failure). Per-position keeps each claim
exactly what §3.2.1 already defines a claim to be.

### R2 — No context beyond the base: `outer_context` is always empty

**The rule.** Every VC this rule emits uses `subtyping_condition(base, weaker,
stronger)` with the default `outer_context=()` — never any of the current
typing `environment`.

**Why, precisely.** §3.2.1 does say "any surrounding term context appended to
Γ after the refined value" — but that clause describes a `Γ` built once, when
the obligation's hypotheses and goal are *authored* against a specific known
context (a body-level `ensures` claim, the only present example being the
hand-written obligations `corpus_registry.MANIFEST` still pins for
`nat/select`'s and `list/consNat`'s bodies). A subsumption predicate is
different in kind: it is `φ`/`ψ` exactly as it was written *inside the type
annotation itself* — a `refine` node in a `fn` domain/codomain, a `lam`
parameter, a constructor field. Per §2.3.1, "function codomains do not
implicitly bind their domain value; Loom v0.1 does not have dependent
function arrows," and every refinement predicate this checker has ever
walked (the whole tranche-4 corpus, plus every synthetic fixture this plan
adds) references only its own index 0. The current term-checking
`environment` is therefore not what `φ`/`ψ` were checked against when the
type annotation was itself validated — a `refine` type's own predicate has no
way to see it — and passing `environment` through as `outer_context` would be
wrong, not merely unnecessary: it would silently add hypotheses and goal
context the predicate never had the syntax to reference.

**This is not a guess; it is the pinned test.** `corpus/nat/widenPos`'s
manifest obligation (`subtype.pos-nat`) is the one place in the corpus where
a real subsumption site and a real pinned VC coincide, and it pins
`outer_context=()` while the check site's own `environment` at that point is
`[pos]` (one entry — the lambda's own parameter, which is also the term being
subsumed). §2.1's implementation confirms this by reproducing that pin
byte-for-byte (`test_corpus.CorpusObligationTest.test_widenpos_pinned_obligation_is_now_checker_emitted`,
verified below) — if `outer_context` had instead been `environment`, that
hash would have moved, and it did not.

**Consequence, stated so it is not later mistaken for a bug.** A subsumption
VC can never reference a value other than the one being subsumed. This is a
real (if currently unreachable) expressiveness limit relative to what a
future dependent-refinement extension might want, but it is not a limit this
plan introduces — it follows from §2.3.1's existing "no dependent function
arrows" rule applied honestly to what a `check()` call site can observe.
Reaching further would require typecheck.py to *also* track which part of
its running `environment` a given `refine` annotation was validated against,
which is a different, larger change than "admit a subsumption typing did not
have before."

### R3 — The collector is opt-in; no collector means no subsumption

**The rule.** `MatchChecker` gains a third constructor parameter,
`obligations: list | None = None`, mirroring the existing
`reference_type`-injection pattern. `validate_source` gains the same
parameter and threads it through unchanged. When a caller supplies a list,
every subsumption site admitted while checking one definition appends an
`(obligation_id, obligations.VerificationCondition)` pair to it, in emission
order, `obligation_id` built from the check-site path
(`f"subsumption@{path}"`). When the parameter is left `None` — the default,
and what every existing caller before this plan does — `_subsume` returns
`False` unconditionally and the caller's original `type mismatch` failure
fires exactly as it always has.

**Why not "collect nowhere, but still let it through."** §3.2's "nothing is
ever silently unverified — every obligation has an evidence entry, even if
that entry is `assumption`" rules out a version of this rule that admits a
subsumption and drops the obligation on the floor: an admitted-but-unrecorded
mismatch would be exactly the silent gap §3.2 forbids, and worse, it would be
a **behaviour change for every existing caller** of `validate_source` and
`MatchChecker`, none of which pass or expect an obligations parameter today.
Requiring a caller to *ask* for subsumption by supplying somewhere to put its
obligations is what keeps the no-collector path — every call site that
existed before this plan — identical to what it computed before this plan.

**Why this makes the bump MINOR, not MAJOR.** Per `CONTRACTS.md`'s bump
table: "an input the previous version accepted is now rejected" or "canonical
bytes … change for any input the previous version accepted" is MAJOR; "an
input the previous version rejected loudly … is now accepted, with nothing
previously accepted changed" or "a new optional parameter whose default
preserves behaviour" is MINOR. Both apply here and neither is contradicted:
the newly accepted inputs (the three re-tiered fixtures, called *with* a
collector) were rejected loudly before (`TypingError`, "type mismatch"), and
every input previously accepted is checked identically, byte for byte,
because the new parameter defaults to behaviour-preserving. `typecheck`
1.0 → **1.1**.

### R4 — What re-tiers, what does not, and why the difference matters

Tracing each of tranche 4's `structural` fixtures against the running typing
environment at its one (or, for `math/abs`, two) subsumption site(s):

| Fixture | Subsumption site(s) | Checker-emitted condition | Matches the pinned obligation? |
|---|---|---|---|
| `corpus/nat/widenPos` | `definition.term.body` — the whole body is `(var 0)` at `pos`, checked against the declared `nat` codomain | `weaker = 0<v`, `stronger = -1<v`, `base = I64` | **Yes — byte-for-byte, same script, same hash** |
| `corpus/math/abs` | `definition.term.body.then` and `.else` — the `if`'s two branches, both synthesizing plain `I64`, checked against the `nat` codomain | `weaker = true`, `stronger = -1<v`, `base = I64` (both sites, hence one shared hash) | No — the pinned obligation is `authored` and states the branch condition as a hypothesis; the checker-emitted one cannot, because nothing in `check()` sees the enclosing `if`'s condition at that point |
| `corpus/list/lengthNat` | `definition.term.body` — `List.size (var 0)` synthesizes plain `I64`, checked against the `nat` codomain | `weaker = true`, `stronger = -1<v`, `base = I64` | No — the pinned obligation is `authored` and states an equality with `List.size`'s result as a hypothesis; the checker-emitted one cannot reach into the reference at all |

All three re-tier from `structural` to `checked`: typing **admits** every one
of them regardless of which case it is, because R1's erasure test and R3's
collector are the whole of what typing consults — never a verdict (the
obligation-pipeline plan's R1, unchanged by this plan). The difference is
what happens *after* typing, at the (separate, not-yet-wired) oracle pass:

- `widenPos`'s checker-emitted VC **is** the argument for its own soundness —
  it is exact and a live solver proves it (§2.1 below).
- `math/abs`'s and `lengthNat`'s checker-emitted VCs are a strictly *weaker*
  claim than the hand-authored ones already pinned in the manifest — dropping
  the `if` condition (`math/abs`) or the meaning of `List.size` (`lengthNat`)
  — and a live solver **refutes** both (§2.1 below). This is not unsound: the
  obligation-pipeline plan's R1 already established that a solver verdict is
  evidence, never a typing precondition, and no code path in this prototype
  connects a verdict back to typing acceptance. It is, however, worth stating
  loudly rather than smoothing over, which is why `test_corpus.py` pins it as
  its own test
  (`test_math_abs_and_lengthnat_checker_emitted_obligations_differ_from_the_pin`)
  rather than leaving it to be discovered by whoever next runs a solver over
  everything `validate_source` can emit. The actual soundness argument for
  these two definitions remains the hand-authored obligation the manifest
  already pinned before this plan, unchanged by it — reaching further needs
  body-VC generation (§3.2.1's stated future work), which this plan does not
  attempt.

**No pinned hash moves.** All six `corpus_registry.MANIFEST` obligations —
the three already `checked` plus the three re-tiered here — keep the exact
`script_hash` they had before this plan, verified below. The only obligation
whose *producer* moves from "this was written by hand" to "this is what the
checker itself now emits" is `nat/widenPos`'s, and it moves without changing
a byte of the script it was already pinned against.

## Work

- [x] Erasure-agreement test and the per-position walk in `typecheck.py`
  (`_erase_refinements`, `_subsumption_sites`, `_walk_subsumption_sites`) (R1).
- [x] `MatchChecker.__init__` gains `obligations: list | None = None`;
  `check`'s final fallback gains `_subsume`, which emits via
  `obligations.subtyping_condition` (imported lazily to break the
  `typecheck.py`⇄`obligations.py` module cycle) (R1, R3).
- [x] `validate_source` gains the same `obligations` parameter, threaded
  through unchanged (R3).
- [x] Re-tier `corpus/math/abs`, `corpus/list/lengthNat`, `corpus/nat/widenPos`
  to `checked` in `corpus_registry.MANIFEST`; drop their `deferred` reasons;
  leave all three pinned `obligations` tuples untouched (R4).
- [x] `test_corpus.CorpusFixtureTest.test_every_fixture_reaches_its_declared_validation_tier`
  threads a collector unconditionally for `checked` entries.
- [x] `test_corpus.CorpusObligationTest` gains
  `test_widenpos_pinned_obligation_is_now_checker_emitted` (the closure) and
  `test_math_abs_and_lengthnat_checker_emitted_obligations_differ_from_the_pin`
  (the loud non-closure) (R4).
- [x] `test_corpus.ExpressivenessLimitTest`'s structural-equality test is
  renamed and re-commented to state precisely what it still tests: the
  no-collector path, unchanged (R3).
- [x] New `test_subsumption.py`: with-collector success and the exact emitted
  condition, without-collector rejection (both the omitted-default and
  explicit-`None` forms), erased-shape disagreement rejecting even with a
  collector, both `φ = true` directions, multi-position emission, the
  reflexive no-op case, and one round trip through
  `obligations.emit_condition` to a script (R1, R2, R3).
- [x] Wire `test_subsumption` into `Taskfile.yml`'s `prototype:test` list.
- [x] `contracts.py` `typecheck` 1.0 → 1.1; `test_contracts.py`'s pinned
  literal; `CONTRACTS.md`'s current-versions table (R3).
- [x] `prototype/README.md` and `docs/plans/README.md` updated.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
LOOM_SMT_SOLVER=/path/to/z3 python3 -m unittest test_corpus.CorpusObligationTest -v   # optional
```

## Completion criteria

- The three `structural` tranche-4 fixtures reach `checked`, and every other
  fixture's tier and every pinned obligation's `script_hash` is unchanged.
- The no-collector path — every call site that existed before this plan —
  behaves identically to before this plan, proven by the unmodified
  structural-equality test still passing.
- `nat/widenPos`'s pinned obligation and the checker's own emitted obligation
  at its one subsumption site are the same VC, same script, same hash.
- `typecheck` contract is 1.1, and `CONTRACTS.md`/`contracts.py`/
  `test_contracts.py` agree.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

1. `task prototype:test`

    ```text
    ----------------------------------------------------------------------
    Ran 304 tests in 1.011s

    OK (skipped=1)
    ```

    PASS. 294 before this plan (measured by stashing this plan's changes and
    re-running the identical module list), plus 8 new in `test_subsumption.py`
    and 2 new in `test_corpus.CorpusObligationTest`
    (`test_widenpos_pinned_obligation_is_now_checker_emitted` and
    `test_math_abs_and_lengthnat_checker_emitted_obligations_differ_from_the_pin`)
    = 304. The single skip is the optional solver run, executed separately as
    step 5. (The unittest module list run directly, without `-v`, is
    reproduced here; `task prototype:test` runs the same list with `-v` and
    the same count.)

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `task todo:lint`

    ```text
    TODO.md: clean
    exit=0
    ```

    PASS.

4. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.

5. `LOOM_SMT_SOLVER=…/z3 python3 -m unittest test_corpus.CorpusObligationTest -v`
   (optional; **Z3 version 5.0.0 — 64 bit**, unpacked from the `z3-solver`
   wheel into a scratch directory exactly as the obligation-pipeline plan did
   — z3 is not on this machine's `PATH` and is not a dependency of the suite)

    ```text
    test_every_obligation_predicate_is_inside_the_decidable_fragment ... ok
    test_every_obligation_reproduces_its_pinned_script_hash ... ok
    test_every_verdict_is_declared_and_a_sat_says_why ... ok
    test_math_abs_and_lengthnat_checker_emitted_obligations_differ_from_the_pin ... ok
    test_no_sat_obligation_is_refuted_and_the_exact_one_is_named ... ok
    test_one_verification_condition_is_one_memo_ledger_row ... ok
    test_pinned_outcomes_are_what_the_rule_derives ... ok
    test_producer_agrees_with_the_fixtures_own_refinement_predicates ... ok
    test_refinement_erasure_makes_a_refined_element_list_one_sort ... ok
    test_refinements_and_obligations_imply_each_other ... ok
    test_solver_verdicts_match_when_a_solver_is_available ... ok
    test_widenpos_pinned_obligation_is_now_checker_emitted ... ok

    ----------------------------------------------------------------------
    Ran 12 tests in 0.243s

    OK
    ```

    PASS. The six pinned verdicts were re-produced by the solver (unchanged
    from the obligation-pipeline plan's run), not predicted.

### Live-solver re-derivation of the checker's own emitted obligations

Not manifest data — these are ephemeral, produced only when a caller supplies
a collector, and are not added to `corpus_registry.MANIFEST`. Re-derived here
because the task explicitly calls for outcomes to be checked against a live
solver rather than predicted:

```text
=== corpus/math/abs (2 auto-emitted site(s)) ===
  subsumption@definition.term.body.then: verdict=sat exact=True outcome=refuted hash=1f9ee763db33aa6ea17a32df0258dcf31c22b90da0f97a0beb1bddfab07a77a1
  subsumption@definition.term.body.else: verdict=sat exact=True outcome=refuted hash=1f9ee763db33aa6ea17a32df0258dcf31c22b90da0f97a0beb1bddfab07a77a1
  [pinned] ensures.nonnegative: verdict=unsat outcome=proved hash=3f2827e4… (unchanged)

=== corpus/list/lengthNat (1 auto-emitted site(s)) ===
  subsumption@definition.term.body: verdict=sat exact=True outcome=refuted hash=1f9ee763db33aa6ea17a32df0258dcf31c22b90da0f97a0beb1bddfab07a77a1
  [pinned] ensures.nonnegative: verdict=sat outcome=undischarged hash=253432ac… (unchanged)

=== corpus/nat/widenPos (1 auto-emitted site(s)) ===
  subsumption@definition.term.body: verdict=unsat exact=True outcome=proved hash=0aee355c… (== pinned subtype.pos-nat, byte for byte)
  [pinned] subtype.pos-nat: verdict=unsat outcome=proved hash=0aee355c… (unchanged)
```

Confirms R4's table exactly: `widenPos` closes (checker-emitted == pinned,
same hash, `unsat`/`proved`); `math/abs` and `lengthNat` do not (checker-
emitted is a different, weaker, and — on this live solver — **refuted**
claim; their pinned obligations are untouched and still `proved`/
`undischarged` respectively). No pinned `script_hash` in
`corpus_registry.MANIFEST` moved. Old→new hash table: **empty** — nothing
moved.

### Residue

1. **`math/abs` and `lengthNat` still need body-VC generation to close for
   real.** Their re-tier to `checked` is sound under this plan's rule (typing
   never consults a verdict), but the *argument* that they are correct is
   still the hand-authored obligation the manifest pinned before this plan.
   The checker's own automatic subsumption at their sites produces a
   strictly weaker, live-solver-refuted claim, because nothing before body-VC
   generation exists can feed an `if` branch's condition or an extern's
   assumed range into what a bare structural mismatch emits. This was
   already recorded as residue 3 of the obligation-pipeline plan
   (`nat/select`'s VC understates its own premises) and residue 1 of this
   plan's own dependency; this plan does not attempt to close it, and no
   pinned obligation changed as a result of this finding — it is reported,
   not acted on.
2. **The refuted, ephemeral obligations this plan's own re-derivation
   surfaces are not persisted anywhere.** `obligations.py`'s
   `emit`/`emit_definition` already have this shape — the caller decides what
   to do with an `EmittedObligation`, and nothing in this prototype wires
   admission (§5.3.2) to consult one. This plan's collector is the same
   contract: a caller that wants to *do* something with a refuted automatic
   subsumption (cover it explicitly, per §6, or surface it as a lint) has
   everything it needs (the obligation, the verdict, the outcome) but nothing
   in this prototype calls that caller yet.
3. **`R2`'s "always empty `outer_context`" is a real, if currently
   unreachable, limit.** A hypothetical future refinement that named an
   *enclosing* binder (which §2.3.1 does not permit today — no dependent
   arrows) would need this rule extended to also track which part of the
   running `environment` a given annotation was checked against. Nothing in
   v0.1's grammar can currently write such a predicate, so this is recorded
   rather than designed around.
