# Plan — Definition-level polymorphism and the Bool elimination form

**Date:** 2026‑08‑13
**Status:** Implemented and verified locally
**Depends on:** [Bootstrap corpus for prior starvation](2026-08-13-bootstrap-corpus.md)
(findings 1 and 2), [Nominal match validation](2026-08-13-nominal-match-validation.md),
[Effect-directed typing](2026-08-13-effect-directed-typing.md),
[Refinement-to-SMT-LIB translation rules](2026-08-13-refinement-smtlib-translation.md)

## Objective

Decide the two §2 language questions the bootstrap corpus escalated, and carry
both decisions through `SPEC.md`, the prototype, the grammar, the tests, and the
corpus itself.

- **Finding 1.** §2.3's rank‑1 `forall` is uninhabitable by any `lam`: §2.3.1
  checks a closed definition's term at type depth 0, so a polymorphic
  signature's own parameter annotation names a type variable that is out of
  scope. No *definition* can be polymorphic.
- **Finding 2.** `Bool` is a base type (§2.2) with no conditional and no nominal
  `match`, so `not`, `filter`, and `contains` are inexpressible. Booleans can be
  produced and consumed by SMT, but nothing can branch on one.

Both are recorded as escalations 1 and 2 of the bootstrap‑corpus plan and pinned
by `test_corpus.ExpressivenessLimitTest`. This plan answers them, and where an
answer lifts a pinned limit it re‑pins the new behaviour rather than deleting the
test — the limit test documents reality, and reality is changing.

Escalation 3 (§11 `extern` has no object encoding) is **not** in scope here; it
is a separate item and a concurrent change.

No visible surface — normative text, prototype layers, grammar, and fixtures
only — so this plan carries no mockups.

## Rules

### R1 — A definition's term is checked at its type's `forall` depth. No new node.

**Decision.** §2.3.1 gains one rule: a definition's *type* is still checked at
term depth 0 and type depth 0, but its *term* is checked at term depth 0 and type
depth **p**, where p is the length of the type's leading `forall` prefix. A
definition whose type is `forall^p T` is implicitly type‑abstracted over those p
variables, and its term is checked against `T`.

That is the whole change. `maybe/map` at `forall a. forall b. (a → b) → Maybe a →
Maybe b` becomes writable with the node vocabulary §2 already has, because the
annotation `(data #Maybe ((tyvar 1)))` is now in scope in the term.

**Mask‑cost accounting — zero tags, zero new stateful machinery.** §2 prices
every decision in mask complexity, so the accounting is the argument:

- **No term tag and no type tag is added.** §2.1 stays at twelve tags for this
  feature (it grows to thirteen for R4, and for nothing else); §2.3 stays at
  seven.
- **The masker needs no lookahead.** A def object is `[0, type, term]` (§4.3), so
  the whole type has already been emitted before the first byte of the term. p is
  a count over bytes the masker has *already produced*, never a prediction.
- **The stateful mask already has the register.** §8.4 concedes that scope needs
  a custom logit processor tracking binder depth. This rule initializes the
  existing type‑depth register to p instead of 0 — an initial value, not a new
  dimension of state.
- **Type‑directed pruning gets easier, not harder.** A `tyvar i` position is
  masked by exactly the same `i < type-depth` test as before.

**Rank‑1 becomes checked rather than asserted.** For "the leading `forall`
prefix" to be well defined, `forall` must be prenex on a definition's type. §2.3
already says "rank‑1 polymorphism only" and nothing enforced it; the new rule
rejects a `forall` anywhere in the definition type after the prefix is removed.
Types *inside* the term (a `hole` goal, a `lam` annotation) are untouched, so
§2.6's polymorphic hole — the only inhabitant `forall` had before this plan —
keeps working exactly as `test_scope` pins it.

**Soundness is parametricity, and it comes free.** No literal and no constructor
inhabits `tyvar i`, so a value of a type‑variable type can only arrive as a
parameter and be passed on; nothing can inspect one. §3.2.1 keeps `forall` and
`tyvar` out of the SMT sort fragment, so no refinement predicate can see a type
variable either. The rule adds no way to observe a type at runtime, which is why
it needs no accompanying restriction.

**The stated limit: v0.1 can write a polymorphic definition but cannot
instantiate one.** `ref h` whose stored type is `forall^p T` synthesizes that
quantified type, and v0.1 has no elimination rule for it, so calling a
polymorphic definition still goes through a monomorphic definition of its own.
This is deliberate, and it is why the seed set keeps its `I64` instances
alongside the new generic entry. The intended future shape is *not* a new node
either: first‑order matching of the quantified type against an expected type
supplied the same way §3.1.2 already supplies an effectful lambda's row — "bind
it through a typed `let`". Specifying that needs a `ref` typing rule in the match
layer, which is a concurrent change owned elsewhere, so this plan states the
limit in §3.1.3 and §13 rather than half‑landing the rule.

**Rejected: `tylam`/`tyapp` term nodes.** Two tags, permanently, against §2's
explicit cost model — and they buy less than they look. Because canonical form is
*elaborated* (§3.1), every use site of every polymorphic definition would have to
spell its instantiation as a `tyapp` chain, so the tags are not paid once at the
definition but at every call in every definition forever. They also add the one
thing R1 avoids: a term‑level binder for the *type* depth register, so the
stateful masker gains a second binder discipline. And they would make the corpus
worse before better — a model with no Loom priors would have to learn to emit
instantiation chains it has never seen.

**Rejected: declaring Loom honestly monomorphic at definition level.** Cheapest
of the three, and it was close. What decides against it is that §2.1's `let` row
already says "monomorphic let; polymorphic reuse goes through the store" — a
load‑bearing claim about *why* `let` is monomorphic, which monomorphic
definitions would make false. Worse, it would leave §2.3 tag 6 `forall` and tag 5
`tyvar` inhabitable only by `hole`: two type tags carrying permanent mask
complexity for a construct no complete definition could ever contain. Removing
them instead is a far larger change (it would move §3.2.1's sort table, the
grammar, and the round‑trip fixtures) and would throw away the design's stated
rank‑1 intent. Making the existing tags inhabitable is strictly cheaper than
either keeping them dead or deleting them.

### R2 — `if` is term tag 12, and it is the Bool elimination form

**Decision.** §2.1 gains one node: `if` = `[12, c, t, e]`, surface `(if c t e)`.
Checked against `R`, `c` checks against `Bool` and both branches check against
`R`, all under the ambient effect row; in synthesis position both branches are
synthesized and must agree. `Bool` stays exactly what §2.2 says it is.

**Mask‑cost accounting — one tag, and the cheapest kind of tag there is.**

- Fixed arity 3, no binders. Unlike `match`, `handle`, `lam`, `let`, `fix`, and
  `refine`, `if` does not touch the stateful masker's depth registers at all, so
  the cost really is one row in §8.2's table.
- Type‑directed pruning is unusually strong on it: the first subterm's goal type
  is *always* `Bool` — the only position in the language with a constant goal —
  and both branches inherit the `if`'s own goal, so the mask needs no new
  inference to prune them.
- No new obligation kind. `if` is exhaustive by construction, so §5.3.1's closed
  obligation‑kind registry and §6.2's generation rule are untouched; it emits no
  `exhaustive-match` obligation because there is no match.
- §3.2.1 gains a row in the *terms* table and nothing else: `if c t e` becomes
  `(ite c t e)`. `ite` is already in the interpreted‑symbol allowlist, so the
  trusted theory surface does not grow by one symbol. This is a strict gain for
  refinements, which until now could not branch at all.

**What one tag buys.** Every branch‑on‑Bool function in the corpus backlog at
once: `bool/not`, `maybe/isJust` written directly, `list/filter`, `takeWhile`,
`dropWhile`, `list/contains`, `nat/max`, and every guard in every later tranche.
No other single tag available to v0.1 has a comparable ratio.

**Rejected: demoting `Bool` to a prelude data declaration.** The ripple is not
merely large, it is destructive at the far end. §2.2 literal kind 1 would go, so
the literal table and the base‑type codes renumber; §2.3 tag 3 `refine` says φ is
"a term of type Bool", which would become a term of some nominal data type; and
§3.2.1 maps `Bool` to SMT‑LIB `Bool` precisely so that the script's last assert
can be `(assert (not <goal>))`. A goal of datatype sort cannot be negated, so
demoting `Bool` would take the entire refinement‑to‑SMT pipeline with it. The
cheap‑looking option is the one that breaks the most.

**Rejected: a general base‑type eliminator.** `Bool` is the only base type with a
finite, small case set. `I64`, `F64`, `Text`, and `Bytes` would need a default
arm, so the node would carry an optional trailing branch and a variable arm list
— a strictly more complex mask shape than `if`, for zero additional
expressiveness in v0.1.

**Rejected (again, and deliberately): a corpus `Bool2 = False | True` data type.**
The bootstrap plan refused it in R5 and this plan does not resurrect it. A second
boolean type is a prior a model would learn and the language would then
contradict. The whole point of answering the finding at the §2 level is to avoid
teaching the workaround.

### R3 — Two decisions, two different answers, and that is the point

R1 adds nothing to §2's tables; R2 adds exactly one row. The asymmetry is not
inconsistency: `if` is inexpressible without a node, while polymorphism was
blocked by a *depth initialization*, not by a missing construct. Paying a tag for
the first and none for the second is the cost model applied, not abandoned.

The one place they interact is the mask's type‑depth register, and they do not
collide: R1 changes its initial value, R2 changes no depth at all.

**Tag allocation.** Term tag **12** = `if` (the next free term tag; §2.1 now runs
0–12). No type tag is allocated. Recorded for whoever allocates next: the next
free *term* tag is 13, and the next free general *type* tag is **8**, not 7 —
type tag 7 is already spoken for by §5.1.1's declaration‑local `self`, which is
valid only inside a data declaration but must never be re‑used at the type level
elsewhere.

### R4 — Both corpus findings get a fixture, not just a spec paragraph

A limit lifted in prose only is not carried through. Each decision lands a seed
fixture that was impossible before it:

| Fixture | Name path | Proves |
|---|---|---|
| `bool_not.loom.sexpr` | `corpus/bool/not` | R2 — the exact definition bootstrap R5 found inexpressible |
| `maybe_map_poly.loom.sexpr` | `corpus/maybe/mapPoly` | R1 — a genuinely generic `forall a. forall b.` definition |

Both reach tier `checked`, so the whole implemented stack — canonicity, scope,
references, and the type‑directed match layer — validates them. The existing
`corpus/maybe/map` at `I64` stays: R1's stated limit means the monomorphic
instance is still the only callable form, and keeping both is the honest record
of that.

### R5 — Limit tests are re‑pinned, never deleted

`test_corpus.ExpressivenessLimitTest` exists so that lifting a limit fails
loudly. Both of its first two tests now assert the *new* reality plus the
residue:

- polymorphism: a polymorphic definition now passes scope **and** the match
  layer; a `tyvar` index at or past the prefix depth is still out of scope; and a
  non‑prenex definition type is rejected.
- `Bool`: `if` checks and synthesizes; `match` on a `Bool` scrutinee still fails
  with the same §3.1.1 message, because `Bool` did not become nominal.

Neither replacement test asserts anything about `ref` or `fix` typing, so the
concurrent work adding those rules cannot be broken by this file.

## Work

- [x] Decide R1 and R2 with the rejected alternatives and the mask accounting.
- [x] `SPEC.md` §2.1: add term tag 12 `if`.
- [x] `SPEC.md` §2.3.1: check a definition's term at its type's `forall` depth;
  require the quantifier prefix to be prenex.
- [x] `SPEC.md` §3.1.3 (new): definition-level polymorphism, its limit, and the
  mask accounting.
- [x] `SPEC.md` §3.1.4 (new): the `if` typing rule and why `Bool` stays base.
- [x] `SPEC.md` §3.2.1: `if` translates to `(ite c t e)`.
- [x] `SPEC.md` §8.2: `if`'s constant-goal condition position in the pruning tier.
- [x] `SPEC.md` §12: render the worked example's Bool branch as `if`, not as a
  `match` the calculus never had.
- [x] `SPEC.md` §13 open problem 1: two of the three residues resolved; state the
  instantiation limit that remains.
- [x] `transcode.py`, `loom.gbnf`, `scope.py`, `references.py`, `matches.py`,
  `refinements.py` for tag 12; `scope.py` and `matches.py` for the `forall` depth.
- [x] Corpus: `bool/not` and a generic `maybe/mapPoly`, with pinned identities.
- [x] Re-pin the two expressiveness limit tests; add `if` and `forall`-depth
  coverage to the round-trip, scope, match, refinement, and GBNF suites.
- [x] Rows in `docs/plans/README.md`; update `prototype/README.md`.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
```

Note: as in the bootstrap-corpus plan, `task` resolves the Taskfile relative to
this nested `.claude/worktrees/…` checkout, so `task todo:lint` is recorded as
the equivalent absolute-path linter invocation against this worktree's `TODO.md`.

## Completion criteria

- Both findings have a decision on the record with the rejected alternatives and
  an explicit mask-cost accounting.
- The decisions are carried through every affected spec section, every prototype
  layer, the grammar, and the tests — no layer knows about `if` or the `forall`
  depth that another layer does not.
- The golden §4.4 identity and every pre-existing corpus identity are unchanged:
  no existing definition's bytes move.
- A polymorphic definition and a branch-on-Bool definition each exist as a
  validated corpus fixture with a pinned identity.
- The lifted limits are re-pinned as new behaviour rather than deleted.

## Recorded verification

Run on 2026‑08‑13.

**Result: PASS**

1. `task prototype:test`

    ```text
    test_bool_is_eliminated_by_if_and_is_still_not_nominal (test_corpus.ExpressivenessLimitTest.test_bool_is_eliminated_by_if_and_is_still_not_nominal) ... ok
    test_recursion_and_stored_references_stop_at_the_structural_tier (test_corpus.ExpressivenessLimitTest.test_recursion_and_stored_references_stop_at_the_structural_tier) ... ok
    test_the_forall_prefix_bounds_type_variables_and_must_be_prenex (test_corpus.ExpressivenessLimitTest.test_the_forall_prefix_bounds_type_variables_and_must_be_prenex) ... ok

    ----------------------------------------------------------------------
    Ran 165 tests in 0.074s

    OK
    ```

    PASS (tail shown; 165 of 165 OK — the 155 that existed before this plan,
    which included the two limit tests it re-pins, plus 10 new). The golden §4.4
    identity is covered by `test_worked_example_matches_spec_4_4` and the four
    pre-existing corpus identities by
    `test_every_fixture_is_canonical_and_keeps_its_pinned_identity`; both pass
    unchanged, so no existing definition's bytes moved.

2. `python3 -m py_compile prototype/*.py`

    ```text
    py_compile exit=0
    ```

    PASS.

3. `LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test`

    ```text
    GBNF PASS: 14 valid cases accepted; 14 invalid cases rejected
    ```

    PASS (was 11 and 11: two `if` surface cases added to the positive list — one
    of them nested in the condition — and three to the negative list: two arities
    and an `if/then/else` keyword spelling the surface does not have).

4. `task todo:lint` — run as
   `python3 ~/python-tui-lib/scripts/todo-lint.py TODO.md` (see the note above)

    ```text
    TODO.md: clean
    exit=0
    ```

    PASS.

5. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.
