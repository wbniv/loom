# Plan — Policy-object validation prototype

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** SPEC.md §5.3.1 (policy object), §5.3.2 (resolution, descent,
domination), §6.1.1 (A1 payload), §6.1.2 (assurance order), §4.2 (deterministic
CBOR), §12 (the `stats/median` worked example);
docs/plans/2026-08-13-namespace-policy-object.md (the design that specified
§5.3.1/§5.3.2 in the first place)

## Objective

The namespace-policy-object plan specified §5.3.1/§5.3.2 as normative prose and
verified only that `task prototype:test` still passed and that the pinned
default-policy hash reproduced by hand — it recorded no executable check of
the policy object's own grammar, of requirement satisfaction, or of
domination. That is a residual risk: the spec text could contain an internal
inconsistency (an example that doesn't validate against its own rules, a
domination rule that admits an obviously-wrong case) with nothing to catch it.

Close that gap with a prototype module in the existing `prototype/` layer
pattern: canonically validate a policy object, check `E ⊒ R` requirement
satisfaction (§6.1.2, reused rather than reinvented), check policy domination
per §5.3.2's table, and pin both the default-policy hash and the §12 worked
example's arithmetic as tests that run in CI via `task prototype:test`.

No visible surface (a Python module and its tests), so this plan carries no
mockups.

## Rules

- **Validate the object, not a store.** `prototype/declarations.py` and
  `prototype/refinements.py` establish the layer's boundary discipline: each
  module validates and compares canonical objects, and none of them resolve
  references against a live store. `policies.py` follows the same line —
  it validates a policy object's shape and compares two policy objects or a
  policy point against an evidence point. It does not resolve `policy-ref`
  by name-path, perform admission, or implement leases or amendment descent;
  there is no store in this repository to resolve against.
- **Reuse `cbor_canonical`, don't reimplement it.** Hashing is
  `sha256(cbor_canonical.encode(validated_object))`, exactly as
  `declarations.declaration_hash` does for data/ability declarations. This is
  what makes the pinned default-policy hash a real regression test rather
  than a hand-verified one-off.
- **One lattice-point shape serves both evidence and requirements.** §5.3.1's
  requirement grammar — `[level]` for A0/A2/A3, `[1, bound, confidence,
  generator]` for A1 — is exactly the shape §6.1.2 already orders. Rather than
  modeling the full seven-element A1 payload record (generator, seed, runs,
  failures, bound, confidence, method) and projecting out three fields, the
  module compares evidence and requirements as the same four-shape "lattice
  point," which is what `E ⊒ R` and rule domination both actually compare.
  Cross-level comparison is `evidence_level >= requirement_level`, except when
  both sides are A1, where it falls through to the exact-rational,
  same-generator comparison — this single rule reproduces "A0 met by
  anything," "A2/A3 satisfy any A1 requirement," and "A1 needs the same
  generator" without three special cases.
- **Rationals compare by cross-multiplication, never as floats.** `bound` and
  `confidence` are canonical `[num, den]` pairs; `a <= b` is
  `a.num * b.den <= b.num * a.den`. This matches §6.1.2's "cross-multiplied
  integers, no float rounding" verbatim.
- **The domination `rules` test stays sound-but-incomplete on purpose.**
  §5.3.2 is explicit that the test — "each predecessor rule dominated by a
  *single* successor rule whose selector is a prefix of it" — deliberately
  refuses cases where a successor is only as strict as a predecessor through a
  *conjunction* of its rules, because an exact test would need a meet inside
  A1 across generators that §6.1.2 does not define. The test suite pins this:
  a successor whose two narrow rules are semantically at least as strict as a
  predecessor's one broad rule, but neither is individually a prefix, must be
  refused. Completing that test is out of scope and would contradict the
  spec's own stated design.
- **Obligation-kind and requirement-level registries are closed, and rejection
  is total.** An unrecognized policy-map key, obligation kind tag, or
  requirement level raises `PolicyError` rather than being admitted at a
  degraded level — this is §6.1.1's method-tag discipline applied to
  governance, restated in §5.3.1.

## Work

- [x] Add `prototype/policies.py`: structural validation (`validate_policy`),
  canonical hashing (`policy_hash`/`policy_bytes`), the closed obligation-kind
  registry and id decomposition (`decompose_obligation_id`), selector
  validation and conjunctive matching (`validate_selector`,
  `matching_rules`), lattice-point validation and comparison (`validate_point`,
  `at_least`, `satisfies`), and domination (`dominates`, plus its per-key
  helpers).
- [x] Add `prototype/test_policies.py`: the pinned default-policy hash and
  bytes, representative-policy acceptance, one rejection case per structural
  rule, obligation-id decomposition, conjunctive selector matching,
  satisfaction positives/negatives (including the §12 arithmetic and a
  different-generator refusal), and domination positives/negatives (including
  the pinned incompleteness case).
- [x] Wire `test_policies` into `Taskfile.yml`'s `prototype:test` command.
- [x] Add `policies.py`/`test_policies.py` rows to `prototype/README.md`'s
  files table and a boundary-narrative paragraph stating what the module does
  not do (no store, no admission, no leases, no descent).
- [x] Add this plan's row to `docs/plans/README.md`.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

## Completion criteria

- `policy_hash([6, {}])` reproduces `901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c`
  as an executable test, not a hand-verified `printf | sha256sum` line.
- The module rejects at least one representative case for every structural
  rule §5.3.1 states: key range, array sortedness/uniqueness, canonical
  rationals, selector shape, requirement level, and the closed obligation-kind
  registry.
- `satisfies` reproduces §12's `ensures.isMiddleOf` evidence
  (`[461, 1000000] @ [99, 100]` under `#c1d0…`) satisfying the `stats/POLICY`
  rule, and refuses the same payload under a different generator.
- `dominates` accepts at least one genuinely-stronger successor and refuses at
  least one case per domination-table key, plus the deliberately incomplete
  `rules` case.
- `task prototype:test` runs `test_policies` alongside the existing suites
  with no regressions.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

1. `task prototype:test`

    ```text
    test_recorded_bound_is_within_the_stated_threshold (test_policies.WorkedExampleArithmeticTest.test_recorded_bound_is_within_the_stated_threshold) ... ok
    test_recorded_evidence_satisfies_stats_policy_rule (test_policies.WorkedExampleArithmeticTest.test_recorded_evidence_satisfies_stats_policy_rule) ... ok
    test_recorded_evidence_under_a_different_generator_is_refused (test_policies.WorkedExampleArithmeticTest.test_recorded_evidence_under_a_different_generator_is_refused) ... ok
    test_stats_policy_forbids_all_assumptions (test_policies.WorkedExampleArithmeticTest.test_stats_policy_forbids_all_assumptions) ... ok
    test_stats_policy_hash_is_stable (test_policies.WorkedExampleArithmeticTest.test_stats_policy_hash_is_stable) ... ok

    ----------------------------------------------------------------------
    Ran 141 tests in 0.053s

    OK
    ```

    PASS (tail shown; 141 of 141 tests OK — 87 pre-existing across
    `test_roundtrip`/`test_scope`/`test_references`/`test_prelude`/
    `test_matches`/`test_effects`/`test_refinements` as of this run, plus 54
    new in `test_policies`; the pre-existing count has grown past the 65
    recorded in earlier plans as concurrent work has landed).

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `task todo:lint`

    ```text
    /home/will/loom/.claude/worktrees/agent-a6e61ad584af546f0/TODO.md: clean
    exit=0
    ```

    PASS (invoked as `python3 ~/python-tui-lib/scripts/todo-lint.py TODO.md`
    from the worktree, per the note in the namespace-policy-object plan about
    `task todo:lint`'s relative include path from a nested worktree).

4. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.
