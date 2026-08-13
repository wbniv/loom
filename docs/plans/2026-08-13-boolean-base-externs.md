# Plan — Boolean and comparison base externs

**Date:** 2026‑08‑13
**Status:** Implemented and verified locally
**Depends on:** [Extern object encoding](2026-08-13-extern-object-encoding.md) (the
`[7, type, artifact, abi]` shape and R7's assumed-base pattern), SPEC.md §3.2.1 (the
interpreted-symbol allowlist and per-symbol signature checks), §5.1.3,
[Bootstrap corpus tranche 4](2026-08-13-corpus-tranche-4.md) R5 finding 6
(`nat/select`'s `sat` case)

## Objective

§3.2.1's interpreted-symbol allowlist admits `not and or => = distinct ite` (Core)
and `+ - * div mod abs < <= > >=` (Ints), but the assumed base pinned by the
extern-object-encoding plan supplies interpretations for exactly four of them:
`+ - = <`. Every corpus predicate written so far is therefore a single
comparison, and `nat` is spelled `-1 < i` because `<=` has no extern to carry it.
Tranche 4's `nat/select` obligation hits the sharp edge of this directly: its
`sat` note says proving the branch result nonnegative "would need `and`, which
the assumed base does not supply" (R5 finding 6).

Extend the assumed base with four more externs — `Bool.and`, `Bool.or`,
`Bool.not`, `I64.le` — so `and`, `or`, `not`, and `<=` are reachable the same
way `+ - = <` already are: pinned identity, interpretation-table row, nothing
else. This does not touch the `nat/select` obligation itself (that fixture and
`test_corpus.py` are owned by a concurrent tranche-4 agent); it demonstrates the
newly-reachable shape — a hypothesis conjoining two comparisons with `and` — as
a standalone translation test.

No visible surface (declarations, an interpretation table, and tests), so this
plan carries no mockups.

## Rules

### R1 — Same pattern as the existing five, purely additive

`corpus_registry.py`'s `_EXTERNS` dict, `SMT_INTERPRETATION`, and
`SMT_SIGNATURES` are all keyed by name/hash and iterated generically by
`registry()` — nothing about them assumes exactly five entries. Four new
dict entries, computed-then-pinned identities, no reshaping of the existing
five or of `Obligation`/`CorpusEntry`.

| Name | Type | `abi` | Interpretation |
|---|---|---|---|
| `Bool.and` | `Bool -> Bool -> Bool` | `bool.and` | `and` |
| `Bool.or` | `Bool -> Bool -> Bool` | `bool.or` | `or` |
| `Bool.not` | `Bool -> Bool` | `bool.not` | `not` |
| `I64.le` | `I64 -> I64 -> Bool` | `i64.le` | `<=` |

All four share `HOST_ARTIFACT` — the same published host-adapter identity the
existing five use — because they are host primitives, not a new artifact.

### R2 — The extern's own arity is fixed even though the SMT symbol is variadic

`refinements.py`'s `_interpreted` accepts `and`/`or` at any arity ≥ 2, but an
extern's Loom type is a fixed monomorphic signature (§5.1.3 R3), so `Bool.and`
and `Bool.or` are binary — the same shape `I64.eq`/`I64.lt` already use, just
over a `Bool` domain instead of `I64`. Applying one supplies exactly two
arguments, which satisfies `_interpreted`'s arity ≥ 2 check; a three-way
conjunction is `Bool.and x (Bool.and y z)`, curried the same way `I64.add`
composes into longer sums. `Bool.not` is unary. `I64.le` mirrors `I64.lt`
exactly, domain and arity both.

### R3 — The demonstration is a translation test, not a new corpus obligation

Corpus fixtures and `test_corpus.py` belong to a concurrent agent working
tranche 4's semantics, so this plan does not add a corpus entry. Instead
`test_externs.py` gets one demonstration test building the exact shape
`nat/select`'s `sat` note describes — a hypothesis conjoining two `-1 < _`
comparisons with the new `Bool.and` extern — and asserts the translated script
is deterministic (two independent translations produce byte-identical text).
This shows the previously-impossible predicate is now expressible; it does not
re-litigate whether `nat/select` itself should change, which is out of scope.

## Steps

- [x] `prototype/corpus_registry.py`: `_binary_bool`/`_unary_bool` helpers, four
  `_EXTERNS` entries, four `SMT_INTERPRETATION` rows, updated module comment.
- [x] `prototype/test_externs.py`: pinned identities for the four, registry
  resolution, validator acceptance (reusing the existing shape/capability test
  classes' generic checks), and the `and`-conjunction demonstration.
- [x] Rows in `docs/plans/README.md` and a sentence in `prototype/README.md`.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

## Completion criteria

- Four new externs are storable, pinned, and resolve through the registry
  exactly like the existing five.
- `and`, `or`, `not`, `<=` each have an interpretation-table row.
- A demonstration predicate conjoining two comparisons with `and` translates
  deterministically.
- All pre-existing pinned identities and VC script hashes are unchanged.

## Recorded verification

Run on 2026‑08‑13.

**Result: PASS**

1. `task prototype:test`

    ```text
    test_the_conjoined_hypothesis_translates_using_the_new_extern_hashes (test_externs.ExternConjunctionDemonstrationTest...) ... ok
    test_the_script_is_deterministic (test_externs.ExternConjunctionDemonstrationTest...) ... ok
    test_the_assumed_base_hashes_are_pinned (test_externs.ExternIdentityTest...) ... ok
    test_the_nine_are_distinct_and_disjoint_from_declarations (test_externs.ExternIdentityTest...) ... ok
    test_the_boolean_base_externs_pass_the_validator (test_externs.ExternShapeTest...) ... ok
    test_the_boolean_base_externs_resolve_by_hash (test_externs.ExternRegistryTest...) ... ok
    test_the_nine_assumed_base_externs_are_pure_typed (test_externs.ExternCapabilityHonestyTest...) ... ok

    ----------------------------------------------------------------------
    Ran 253 tests in 0.686s

    OK (skipped=1)
    ```

    PASS (tail shown plus the new tests grepped out; 253 of 253 tests OK, one
    skip for the optional solver run that was already skipped before this
    change — no `z3` on `PATH`).

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `task todo:lint` — run as `python3 ~/python-tui-lib/scripts/todo-lint.py TODO.md`
   (same nested-worktree note as the extern-object-encoding plan)

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

## The four pinned externs

| Name (§5.2 metadata) | Type | `abi` | Interpretation | Identity |
|---|---|---|---|---|
| `I64.le` | `I64 -> I64 -> Bool` | `i64.le` | `<=` | `52e63dfa16dffd7ea93f6a9b56a6da10e78c7745fe8a37c4b9e1ec0d859cb53e` |
| `Bool.and` | `Bool -> Bool -> Bool` | `bool.and` | `and` | `4e303d5118babab70a13f230e374ac4f710b332213056839e9649d14fec5b9e0` |
| `Bool.or` | `Bool -> Bool -> Bool` | `bool.or` | `or` | `3f146d1cf153175629d4e0c7577f4726854c5bb90328f77de7299c3a1c9989f0` |
| `Bool.not` | `Bool -> Bool` | `bool.not` | `not` | `86b89f7556d56a22c80d71c49651d32d127a5925c1e5b8efddc6297ae9cb52b6` |

Artifact: the same `HOST_ARTIFACT` as the existing five
(`ce43337facff58a0c10063b99081d0e4c637eb8936bb783834339555ab8339f7`).

The conjunction demonstration (`test_externs.ExternConjunctionDemonstrationTest`)
builds the hypothesis `(-1 < a) and (-1 < b)` — two `nat`-style comparisons
conjoined with the new `Bool.and` extern, over an outer context of two `I64`
variables — and shows it translates with no `declare-fun` at all (both `and`
and `<` are interpreted) to
`(assert (and (< (- 1) loom.x1) (< (- 1) loom.x2)))`, and that two independent
translations of the same obligation produce byte-identical scripts.

## Residue

- `nat/select`'s `sat` obligation itself is untouched — whether tranche 4
  should now revisit it with a conjoined hypothesis is a decision for the
  agent that owns `corpus_registry.MANIFEST`'s tranche-4 entries and
  `test_corpus.py`, not this plan.
- `Bool.and`/`Bool.or` are binary externs; the SMT-LIB `and`/`or` symbols they
  interpret are variadic, but nothing in the assumed base needs more than two
  operands at a time — wider conjunctions curry, matching how `I64.add`
  already composes into longer sums.
