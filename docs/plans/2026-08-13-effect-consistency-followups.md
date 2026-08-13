# Plan — Effect-consistency review follow-ups

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Effect purity soundness](2026-08-13-effect-purity-soundness.md),
[Refinement-to-SMT-LIB translation rules](2026-08-13-refinement-smtlib-translation.md)

## Objective

Close the eight enumerated findings across
[the effect-consistency change review](../reviews/2026-08-13-effect-consistency-change-review.md)
and two later review notes (§6.1.1's circular confidence clause, §3.2.1's
unstated F64 bitwise-equality fork). All eight are documentation- or
test-level: one incomplete normative sentence, one stale status header, one
missing pinned regression test, one review resolution note needing
correction, one undocumented build recipe, five broken cross-references, one
circularly worded soundness check, and one unstated design commitment. None
changes checker or translator behavior.

No visible surface (spec prose, a review note, a README paragraph, and one
test), so this plan carries no mockups.

## Rules

- **No checker/translator behavior changes.** Every fix is prose or test
  code; if any item had turned out to need a behavior change, it would be
  dropped from this pass and escalated rather than done ad hoc. None did.
- **Correct the record, don't just restate it.** Where a source document
  (the prior review's resolution note) turns out to be wrong on the facts
  rather than merely stale, the amendment says so plainly instead of quietly
  reflowing the wording — see the finding below.

## Work

- [x] SPEC.md §3.1.2: add "an operation argument's declared parameter type"
  to the expected-type propagation list.
- [x] SPEC.md status header (line ~3) and README.md-deferred wording aligned
  with README.md's "design specification with a working validation
  prototype."
- [x] `prototype/test_effects.py`: add a dedicated, pinned test for the
  direct-application rejection claim.
- [x] Amend `docs/reviews/2026-08-13-effect-purity-change-review.md`'s
  Resolution section.
- [x] `prototype/README.md`: document the GBNF validator build (pinned
  llama.cpp revision + clone/build recipe).
- [x] Repair the design-sketch references in README.md, SPEC.md (header and
  §14 footer), and the essay-analysis cross-link; import the sketch itself
  since it was found outside the repo.
- [x] SPEC.md §6.1.1: reword the circular confidence clause in the A1
  recomputation check.
- [x] SPEC.md §3.2.1 + the refinement-to-SMT-LIB plan: record the F64
  bitwise-equality design fork.

## Findings during implementation

**Fix 3/4 premise was wrong: the direct-application rejection test already
existed.** The task brief (following the effect-consistency review's finding
2) assumed no test exercised "an effectful lambda as the direct callee of an
application is rejected." `git show 7776d05 -- prototype/test_effects.py`
shows that commit — the one the review itself was reviewing — added exactly
that assertion to `test_effectful_function_application_checks_row_and_capability`:
the `direct` case at the end of that test checks
`(app (lam Unit (perform clock 0 ())) (lit unit))` under an outer
`(cap clock)` ambient row and asserts it fails with "not allowed by the
ambient effect row" — verified interactively at
`definition.term.body.function.body`. Running that single test
(`python3 -m unittest test_effects.EffectTypingTest.test_effectful_function_application_checks_row_and_capability -v`)
confirms it passes today. The effect-consistency review's finding 2 was
itself mistaken, and the effect-purity-change-review's original resolution
note ("tests cover both a typed-`let` acceptance case and direct-application
rejection") was accurate when written.

Given that, this pass did two things instead of literally "adding a missing
test": (1) added `test_effectful_lambda_as_direct_application_callee_is_rejected`,
a dedicated, distinctly named test pinning the claim on its own — the actual
gap finding 2 was gesturing at, since the existing assertion rode along
inside a test named for the acceptance case and would silently vanish if that
test were ever renamed or refactored away; (2) amended the effect-purity
change review's Resolution section with a dated addendum correcting the
later review's mistaken finding, rather than rewriting the original bullet to
match a false premise. See `docs/reviews/2026-08-13-effect-purity-change-review.md`'s
Addendum for the full correction.

**The design sketch was found outside the repo and imported.** It exists at
`~/docs/investigations/2026-08-12-loom-agent-native-language-sketch.md` (not
`~/Documents`), companion to the essay-analysis file that was already
imported into this repo. Imported verbatim to
`docs/investigations/2026-08-12-loom-agent-native-language-sketch.md`, with
its own internal link to `SPEC.md` corrected from the external
`../../loom/SPEC.md` (valid only from its old home under `~/docs/`) to
`../../SPEC.md` (correct from its new home in this repo).

**The `../docs/` prefix defect was broader than the sketch links.** The
essay-analysis link in README.md's Lineage section (line 44) carries the same
wrong `../docs/` prefix as the sketch link on the next line, even though its
target already existed in the repo — fixed alongside the sketch-link
repairs. The SPEC.md §14 footer's essay-analysis link had the identical
defect and was fixed the same way.

**`/tmp/loom-llama-cpp` still exists.** Its `test-gbnf-validator` binary
still runs. `git -C /tmp/loom-llama-cpp rev-parse HEAD` gives
`1f368f354d9edcfea9fd6a1e0989b3e7335a050f`; `describe --tags` fails because
the clone is `--depth 1` shallow with no tag history. `git log -1` dates the
commit 2026-08-13, subject "ggml : fix arm builds, unused var (#26991)".
`CMakeCache.txt` shows no non-default options beyond `CMAKE_BUILD_TYPE=Release`,
so the documented recipe in `prototype/README.md` is a plain default build at
that pinned revision.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test
```

## Completion criteria

- SPEC.md §3.1.2's expected-type context list includes operation arguments.
- SPEC.md's own status header no longer says "Nothing here is implemented."
- `prototype/test_effects.py` has a dedicated test pinning the
  direct-application rejection claim, and the full suite is green.
- The effect-purity change review's resolution note names the actual tests
  and no longer contains an inaccurate claim without correction.
- `prototype/README.md` documents a reproducible GBNF validator build.
- Every design-sketch reference resolves to a real file with a correct
  relative path.
- SPEC.md §6.1.1's A1 recomputation check has no circular clause.
- SPEC.md §3.2.1 and the refinement-to-SMT-LIB plan both state the F64
  bitwise-equality commitment explicitly.
- No checker or translator source file changed.

## Recorded verification

Run on 2026-08-13, from the worktree
`/home/will/loom/.claude/worktrees/agent-a8b4beb9cc88b0ee6`.

**Result: PASS**

1. `task prototype:test`

    ```text
    Ran 88 tests in 0.045s

    OK
    ```

    PASS. 88 tests, one more than the 87 recorded by the refinement-to-SMT-LIB
    plan, matching the one new test added in this pass.

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `task todo:lint`

    ```text
    TODO.md: clean
    ```

    PASS.

4. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.

5. `LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test`

    ```text
    GBNF PASS: 12 valid cases accepted; 11 invalid cases rejected
    ```

    PASS. `/tmp/loom-llama-cpp`'s validator still exists (pinned at
    `1f368f354d9edcfea9fd6a1e0989b3e7335a050f`, documented in
    `prototype/README.md`), so this step ran rather than being recorded NOT RUN.
