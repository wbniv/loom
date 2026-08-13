# Review of the effect documentation and fixture consistency change

**Date:** 2026-08-13

**Reviewed commit:** `7776d05` (`Align effect documentation and fixtures`)

**Verdict:** A faithful, verified implementation of the prior review's
recommendations. No code behavior changed and no behavioral defect was found.
The findings below are documentation-precision gaps: one normative sentence in
`SPEC.md` is incomplete, one normative claim is untested, the resolution notes
overstate test coverage, and the spec's own status header now contradicts the
README it was aligned with.

## Scope and verification

The review compared `7776d05` with its parent, inspected the new plan, the
`SPEC.md` contextual-typing addition, the promoted fixture, the amended plan
records, and the README status rewrite. Fresh verification on the reviewed
tree:

```text
task prototype:test
Ran 65 tests in 0.038s
OK
```

The `05_clock_handler` fixture was confirmed **byte-identical** to the
canonical one-line block in `docs/loom-vs-lisp.md`, and the spec's
direct-application rejection claim was confirmed against the checker by hand
(see finding 2).

## What improved

- **The contextual-typing cliff is now a specified decision, not an
  implementation accident.** `SPEC.md` §3.1.2 names the expected-type
  propagation contexts and states that Loom v0.1 has no ascription term, with
  the typed-`let` idiom as the prescribed workaround. This was the prior
  review's principal design question, and option 1 (specify propagation
  contexts) was the right choice for a canonical-form language.
- **The documentation sample can no longer drift.** Promoting the clock
  handler to `05_clock_handler.loom.sexpr` puts it under round-trip, scope,
  and effect-directed validation, and the document now links to the fixture as
  authoritative rather than carrying a second copy of the truth.
- **Verification bookkeeping is honest again.** The purity plan's GBNF step
  was actually rerun (12 valid + 11 invalid cases) rather than left as an
  internally inconsistent "NOT RUN" under a PASS header, and the rerun is
  labeled as such rather than silently rewriting history.
- **The status claims converged toward reality** — in the README. See finding
  3 for the half left behind.

## Findings

### 1. P2 — The expected-type context list omits `perform` arguments

`SPEC.md` §3.1.2 now enumerates the contexts that propagate an expected type:
definition annotation, checked lambda codomain, constructor field, application
parameter, typed `let` binding, expected match-arm result, handler clause
result. The checker has one more: **operation arguments are checked against
the declared parameter types** (`matches.py`, `perform` synthesis). An
effectful lambda passed as a `perform` argument whose declared parameter type
is an annotated `fn` row would be checked, not synthesized — the enumerated
list says otherwise. No builtin ability currently takes a function-typed
parameter, so the gap is unobservable with the v0.1 prelude, but the sentence
is normative and should be complete: add "an operation argument's declared
parameter type" to the list.

### 2. P3 — The direct-application rejection claim is true but untested

> **Correction (2026-08-13, follow-ups pass):** this finding was wrong.
> Commit `7776d05` did add a direct-application rejection assertion, inside
> `test_effectful_function_application_checks_row_and_capability`; the review
> was made against a working-tree snapshot that misrepresented the file. The
> prior review's resolution note was accurate as written. The follow-ups pass
> nevertheless added a dedicated named test
> (`test_effectful_lambda_as_direct_application_callee_is_rejected`) so the
> normative claim has its own pinned negative test.

§3.1.2 states that an effectful lambda "as the direct callee of an
application" is rejected even when the ambient row permits its effect. That
claim was verified by hand during this review (the checker rejects it at the
callee's body, path `…function.body`), but no test in the suite exercises a
direct `(app (lam …) …)` with an effectful body. The resolution section of the
[effect-purity change review](2026-08-13-effect-purity-change-review.md)
says "tests cover both a typed-`let` acceptance case and direct-application
rejection" — the acceptance case exists
(`test_effectful_function_application_checks_row_and_capability`, which
predates the reviewed commit), but the direct-application rejection test does
not. Add it; a normative "is rejected" sentence deserves a pinned negative
test, and the resolution note should not claim coverage ahead of it.

### 3. P2 — `SPEC.md`'s own status header still says "Nothing here is implemented"

The commit rewrote the root README status to "design specification with a
working validation prototype" — correctly — but `SPEC.md` line 3 still opens
with "**Status:** Design fiction made precise. Nothing here is implemented."
The two files now disagree about the same fact. The spec header should point
at the prototype boundary the README describes (or defer to the README) rather
than deny the prototype exists.

### 4. P3 — The recorded verification command depends on a `/tmp` build

Both amended plans record
`LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator`. That
binary is an ephemeral local build: after a reboot the recorded command is not
re-runnable as written, and nothing in the repository says how to recreate it.
The record is honest as history, but reproducibility wants one sentence in
`prototype/README.md` (or a `task` entry) giving the pinned llama.cpp revision
and build command that produced the validator.

### 5. P3 — Pre-existing: the design-sketch links are doubly broken

Not introduced by this commit, but adjacent to files it touched: `README.md`
and `SPEC.md` reference the design sketch as
`../docs/investigations/2026-08-12-loom-agent-native-language-sketch.md`
(five references total, including the §14 footer and the essay-analysis
cross-link). Two defects compound: the `../docs/…` prefix is wrong relative to
repo-root files (it escapes the repository), and the sketch file itself was
never imported — it exists nowhere in the repository. Either import the sketch
from its source or rewrite the references to say the sketch is external;
either way the relative paths need fixing.

## Recommended follow-up

A single small pass (tracked as the `[T2]` review-follow-ups item in
`TODO.md`): complete the §3.1.2 context list, fix the `SPEC.md` status header,
add the direct-application rejection test and correct the prior review's
resolution note, document the GBNF validator build, and repair or remove the
sketch references. None of it changes checker behavior; all of it keeps the
normative surface trustworthy, which is the property this repository trades
on.
