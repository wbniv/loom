# Review of corpus tranche 4 — the refinement slice

**Date:** 2026-08-13

**Reviewed commit:** `fadc3ae` (worktree branch, merged), per
[the tranche-4 plan](../plans/2026-08-13-corpus-tranche-4.md).

**Verdict:** The strongest tranche of the four, precisely because half of its
obligations *fail*. Six fixtures, six pinned canonical VC scripts, and a
deliberate three/three split between dischargeable subtyping claims (`unsat`)
and true claims the v0.1 fragment cannot carry (`sat`) — each `sat` with a
precise diagnosis. The two escalations it raises are the right ones and are
genuinely design decisions, not implementation gaps; both are now ranked TODO
items. One of them (`sat` semantics) is, in this reviewer's judgment, a latent
normative bug in §3.2.1 that this tranche is the first to make concrete.

## Verification performed

Independently on the merged tree, not from the agent's records:

- `task prototype:test` → 249 tests, OK (1 skip: the optional solver run);
  GBNF 21 valid / 16 invalid; lint and `git diff --check` clean.
- **All six VC script hashes reproduced** from the manifest's `Obligation.script()`
  through `refinements.subtype_script` — every pin matches.
- **All six solver verdicts reproduced** with a freshly installed z3 5.0
  (separate from the agent's unpacked wheel): 3 `unsat`, 3 `sat`, exactly as
  pinned. The verdicts in the manifest are facts, not predictions.
- **The shared memo-row property is real**: `nat/widenPos` and `nat/applyPos`
  produce byte-identical scripts and one SHA-256 — §3.2.1's
  one-VC-one-memo-row claim demonstrated with a live collision, on purpose.
- **Provenance verified at source**: `FStarLang/FStar` reports SPDX
  `Apache-2.0`; the enforced provenance string matches.
- **The escalation's textual premise checks out**: SPEC.md line 563 does say
  "`sat` refutes the obligation and the binding is rejected."

## What the tranche does well

- **The `sat` cases are the payload.** A corpus that only contained provable
  obligations would demonstrate the translator; this one maps the fragment's
  boundary with three true-but-unprovable claims, each attributed to a specific
  cause: `List.size` uninterpreted (nothing bounds it below; F* proves it by
  induction, the fragment is quantifier-free), refinement erasure collapsing
  `List {n|-1<n}` and `List I64` into one SMT sort (element predicates
  contribute no hypothesis), and the single-hypothesis VC shape with no `and`
  in the assumed base. That is exactly the map a future oracle implementer
  needs.
- **`math/abs` gives §3.2.1's stated unsoundness its first teeth**: provable in
  the idealized-`Int` encoding, false on wrapping hardware at `INT_MIN`. The
  limit was declared when the translator landed; now there is a pinned,
  concrete instance.
- **Optional tooling handled correctly**: the solver step is env-gated, the
  suite skips rather than fails without it, and the agent went to the trouble
  of actually producing verdicts rather than asserting them.
- **The provenance lesson stuck**: the license was fetched and verified before
  the attribution string was written anywhere, and the enforcement test grew an
  F* arm.
- **Honest tiering**: the three `structural` fixtures are structural for one
  shared, recorded reason (finding 1 below), not three vague ones.

## Findings ratified into the backlog

**1. (T4, escalated by the agent) §3.3 subtyping is specified, its VC is
generated, and nothing consults it.** `refinements.subtype_script` has no
caller in `typecheck.py`; this alone causes all three structural tiers. The
design fork — solver-in-the-typing-loop versus obligation *emission* for a
separate oracle pass — is genuinely open, though the spec's own architecture
(§6's evidence objects, the oracle as a distinct layer, §3.4's crisp-decision
boundary) leans heavily toward emission: typing stays fast and decidable,
obligations become store objects, and the solver's verdict becomes evidence
rather than a typing precondition.

**2. (T4, escalated by the agent; sharpened here) `sat` is the wrong verdict
semantics, and more wrong than the escalation states.** The agent's framing —
`sat` conflates refutation with an inexpressible premise — is correct but
understates the problem: a `sat` model *never* distinguishes a genuine
counterexample from an artifact of the encoding's abstractions (uninterpreted
symbols, erased refinements, idealized `Int`). §3.2.1's "sat refutes and the
binding is rejected" is only sound when the script contains no abstraction —
otherwise a spec-conforming checker rejects three correct definitions in this
repository's own corpus today. The rule needs a three-way outcome (proven /
refuted-by-validated-countermodel / undischarged-by-this-VC), and deciding
when a countermodel counts as validated is the design core. The three pinned
`sat` cases are the ready-made test corpus for whatever rule lands.

**3. (T2) The assumed base has no `and`, `or`, `not`, `<=`.** §3.2.1's
allowlist admits them; no extern supplies them, so every corpus predicate is a
single comparison and `nat` is spelled `-1 < i`. Adding the boolean/comparison
externs (pinned identities + interpretation rows, the established pattern)
lets predicates state conjunctions and `≥` naturally and directly relieves the
single-hypothesis limitation behind one of the three `sat` cases.

**4. (T3) The production-language Watch trigger is half met and now has a
concrete gate.** Tranches 3 and 4 both landed with zero IR, tag, or spec
changes — the "two consecutive tranches" half of trigger (a). The remaining
half is versioned parser/scope/reference/type-checking contracts, which is now
the single infrastructural item standing between the Watch entry and
promotion.

Residue accepted as recorded (no new items): F*'s `decreases` still has not
crossed (the monomorphic `List.size` wall recurs — bootstrap residue 5), and
the multi-shot handler from tranche 3 remains operationally meaningless
without an evaluator.

## Critique of the work itself

Small and few. The obligation tests went into `test_corpus.py` rather than a
new file — a deviation from the brief, but argued correctly (third instance of
the enforced-both-directions manifest pattern; splitting one invariant style
across two files buys nothing). The `Obligation.weaker` predicates are
hand-authored body summaries, which the docstring and plan state plainly —
that is the tranche's honest boundary, but reviewers should note the corpus
now contains claims whose *premises* are asserted rather than derived; body-VC
generation, when it exists, must reproduce or replace them. And `abs` earning
`unsat` partly because its hand-authored summary is conveniently expressible
is worth remembering when quoting "three of six discharge": the denominator is
shaped by what could be authored, not sampled from F* at random.

## Verdict

Tranche 4 closes the bootstrap plan with the corpus doing what it was designed
for — converting underspecified corners of the spec into pinned, executable
disagreements. The four-tranche corpus now spans structural eliminators,
recursion with measures, effects and handlers, and refinement obligations with
canonical solver inputs: 20+ fixtures, every identity pinned, every limit that
was hit either lifted or recorded. The two T4 design items it surfaced are the
last spec seams between the prototype and a real oracle loop.
