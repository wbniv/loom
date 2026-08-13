# Review of the recent-work review and its remediation

**Date:** 2026-08-13

**Reviewed:** [the recent Claude work review](2026-08-13-claude-recent-work-review.md)
and commit `2755f33` (`Harden extern capability validation`), which contains
both that review and its remediation.

**Verdict:** The review was substantially correct and its headline finding is
real — I independently reproduced both adversarial extern signatures being
accepted by the pre-fix checker and rejected after. The remediation is correct,
simpler than the code it replaced, and honest in its records. Two flaws in the
review itself (one of which the remediation had to silently correct), one
process nit, and one unstated consequence of the new rule that deserves
normative text.

## Verification performed

Fresh on `2755f33`:

```text
task prototype:test → Ran 237 tests in 0.179s / OK
```

Both adversarial signatures from the review's P1 were run against the pre-fix
`check_extern_type` (extracted from `3016ace`) and the current one, alongside a
legitimate direct-cap signature:

```text
OLD callback-buried: accepted        NEW: REJECTED
OLD too-late:        accepted        NEW: REJECTED
OLD legitimate:      accepted        NEW: accepted
```

The review's central factual claim reproduces exactly.

## The review, reviewed

**What it got right.** The P1 extern finding is the most important defect found
in this repository since the effectful-closure escape, and it was found the
right way — adversarial signatures thrown at the public checker function, not
prose inspection. The set-containment analysis (value position and application
order both lost) is precise. The second P1 (the polymorphic-extern rationale
falsified by `d1159d9`) is correct on the timeline, and the review resisted the
tempting overreach: it recommended keeping the restriction with an honest
reason rather than demanding polymorphic externs. The P2s are proportionate —
notably it explicitly declined to call the test-local resolver a checker
defect, which it is not. Severity ordering and the recommended work order were
both actionable as written.

**Flaw 1 — the `typing.py` recommendation was itself a bug.** The review's P3
recommended renaming the checker module to `typing.py`. Every prototype test
runs with `prototype/` first on `sys.path`, so that name would shadow Python's
standard-library `typing` module and break any import of it in the process. The
remediation caught this and chose `typecheck.py`, noting why — meaning the
remediation had to correct its reviewer. A concrete rename recommendation
should be checked against the import environment before it is written down.

**Flaw 2 — the rename it asked for was only half-taken, and the review's
resolution note does not say so.** `TypeDirectionError` became `TypingError`,
but the class is still `MatchChecker` inside `typecheck.py`. That may be the
right call (a class rename would churn every test file for zero semantic
value), but the review's Resolution section says "the checker is now
`typecheck.py` with `TypingError`" without recording that the class name — the
thing most callers actually touch — was deliberately left. Resolutions should
record the deviations, not only the compliances.

**Process nit — the review and its remediation landed in one commit.**
`2755f33` contains the review document, the remediation plan, and the fixes.
There is no commit at which the review exists against the tree it criticizes,
so `git checkout` cannot reproduce the reviewed-but-unfixed state, and the
review's "Verification performed" section describes a tree (`3016ace`) that
never carried the review. The house pattern to date — review commit, then
remediation commit — preserves that seam and should be kept.

## The remediation, reviewed

**The algorithm is right and smaller.** `_check_extern_capability_order` walks
only the top-level curried spine, admits only direct `cap a` domains into the
available set, adds the current domain before checking the current arrow's row
(correct: the argument is supplied at the application that triggers the
effects), and accumulates monotonically down the spine. Three recursive
set-collectors (~83 lines) became one 15-line walk. The new §5.1.3 wording
matches the implementation exactly, including the two exclusions (nested, and
later-than-the-effect).

**`definition_types.py` honors the review's trust contract.** Entries are
scope-validated on the way in, the canonical hash is cross-checked when the
caller pins one, and both directions deep-copy. It is correctly framed as a
store-facing test adapter, not a Loom object registry, and `DeclarationRegistry`
keeps its closed role as the review asked.

**Provenance is now enforced, not remembered.** All seven Unison-derived
manifest entries carry the `unisonweb/unison, MIT` form and
`test_external_fixture_provenance_names_repository_and_license` makes a future
lapse fail locally.

**The integration record exists and reproduces.** The plan's 237-test figure is
what the merged tree runs today.

## Finding — the rule quietly constrains callback-taking externs; say so

The new per-arrow rule has a consequence neither the review nor the remediation
states: an extern that invokes an effectful callback is now **unwritable
without a direct capability parameter**. A signature like
`fn (fn (cap a) () Unit) {a} Unit` is rejected (the buried cap no longer
counts), so an extern that honestly names its callback's ability in its own
row must also take `cap a` directly — e.g.
`fn (cap a) () (fn (fn (cap a) () Unit) {a} Unit)` shapes. That is the correct
blast-radius outcome: invoking the callback exercises the ability, so the
extern must hold the authority directly. But it is a real narrowing of what
§11 externs can look like (`spawn`-style higher-order externs must thread an
explicit cap), and it currently exists only as emergent checker behavior.
§5.1.3 should state it in a sentence, with an accepted callback-plus-direct-cap
signature and its rejected callback-only counterpart as the test pair. Tracked
as an open TODO item.

## Verdict on the pair

The review found a real soundness hole with the right method; the remediation
closed it with a simpler algorithm, honest re-rationalization, and enforced
hygiene, while quietly fixing its reviewer's one defective recommendation. The
residue is small and documentary: name the callback consequence normatively,
record half-taken recommendations as deviations, and return to two-commit
review/remediation hygiene.
