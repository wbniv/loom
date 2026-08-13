# Plan — Bootstrap corpus tranche 4: the refinement slice

**Date:** 2026‑08‑13
**Status:** Implemented and verified locally
**Depends on:** [Bootstrap corpus for prior starvation](2026-08-13-bootstrap-corpus.md)
(R1 the F\* role and the licence discipline, R2 mapping losses, R5 the assumed
base, R6 tiers, R7 manifest conventions),
[Bootstrap corpus tranche 3](2026-08-13-corpus-tranche-3.md) (integration‑record
format, and the both‑directions manifest‑field pattern),
[Refinement‑to‑SMT‑LIB translation rules](2026-08-13-refinement-smtlib-translation.md),
`SPEC.md` §2.3 (`refine` is `[3, T, φ]`), §2.3.1 (no dependent arrows), §3.2 (the
decidable fragment), §3.2.1 (the verification condition, the interpretation
table, canonical scripts), §3.3 (refinement subtyping), §5.1.3 (externs), §6.1
(the assurance lattice), §6.2 (obligations), §6.4 (the memo ledger)

## Objective

Build tranche 4 of the bootstrap corpus: refinement‑carrying definitions from
F\*, transpiled type‑first, non‑dependent arrows only. This is the tranche the
bootstrap plan's R1 kept F\* around for, and the first whose fixtures carry
`refine` types and therefore §6.2 obligations at all.

"Exercise §3.2.1 end to end" needs a definition, because there is no solver in
the loop and §3.2.1's own text says verification‑condition generation for
function bodies is future work. What it means here: **for every `ensures`‑style
claim in the tranche, the §3.2.1 refinement‑subtyping verification condition is
built, its canonical SMT‑LIB script is emitted byte for byte, and that script's
SHA‑256 — the §6.4 memo‑ledger payload key — is pinned in a test.** The
obligation's solver input exists, is deterministic, and is regression‑guarded.
A solver is run over each script when one is available, and the verdict is
pinned too, but never as a dependency of the suite.

R3 below scopes exactly which of those claims a solver can discharge today and
which are waiting on body‑VC generation. That scoping is the deliverable, not a
caveat attached to one.

No visible surface (fixtures and normative text only), so this plan carries no
mockups.

## Rules

### R1 — F\*, verified rather than assumed: Apache‑2.0, and three named modules

The bootstrap plan's R1 left F\*'s licence unstated because tranche 4 was not
being built. It is stated now, from the source rather than from memory:
[FStarLang/FStar](https://github.com/FStarLang/FStar)'s `LICENSE` was fetched on
2026‑08‑13 and is the **Apache License, Version 2.0**. Attributions therefore
read `F* (FStarLang/FStar, Apache-2.0) <module>.<name>`, and
`test_corpus.CorpusFixtureTest.test_external_fixture_provenance_names_repository_and_license`
gained a second arm asserting exactly that shape for every entry whose source
begins `F*`, alongside the Unison arm it already enforced.

The cited definitions were read on the same day from three files in `ulib/`:

| File | What was read | Line |
|---|---|---|
| `Prims.fst` | `type nat = i: int{i >= 0}` | 478 |
| `Prims.fst` | `type pos = i: int{i > 0}` | 481 |
| `FStar.Math.Lib.fst` | `val abs: x:int -> Tot (y:int{ (x >= 0 ==> y = x) /\ (x < 0 ==> y = -x) })` | 64 |
| `FStar.Math.Lib.fst` | `val max: x:int -> y:int -> Tot (z:int{ (x >= y ==> z = x) /\ (x < y ==> z = y) })` | 68 |
| `FStar.List.Tot.Base.fst` | `val length: list 'a -> Tot nat` | 73 |
| `FStar.List.Tot.Base.fst` | `val map: ('a -> Tot 'b) -> list 'a -> Tot (list 'b)` | 150 |
| `FStar.List.Tot.Base.fst` | `val list_refb: #a:eqtype -> #p:(a -> Tot bool) -> l:list a { for_all p l } -> Tot (list (x:a{ p x }) {…})` | 570 |

Nothing is vendored: no F\* source text enters this repository, exactly as with
Unison. `list_refb` is cited because it is where `list (x:a{p x})` — a list
whose *element type* is refined — actually appears in the F\* standard library;
its `Cons` step is what `corpus/list/consNat` transpiles.

### R2 — Type‑first means every weakening is named, and the first one costs half of F\*

R1 of the bootstrap plan rejected F\* as the *primary* corpus for one reason:
"take almost any verified F\* function and its type is a dependent arrow.
Dropping the dependency to fit §2.3.1 does not lose decoration — it changes the
proposition." Building the tranche makes that concrete, and the concrete form is
sharper than the prediction.

**A Loom refinement predicate may name the refined value and nothing else.**
`refine T φ` puts the refined value at term index 0 (§2.3, §3.2.1). A codomain
refinement that also named the *argument* would be a dependent function arrow,
and §2.3.1 states outright that v0.1 has none. So of F\*'s two `Math.Lib`
signatures above, the entire postcondition is unreachable:

- `abs`'s `(x >= 0 ==> y = x) /\ (x < 0 ==> y = -x)` **pins the value**. In Loom
  only `y ≥ 0` survives — a strictly weaker proposition that is nonetheless the
  one everybody actually uses `abs`'s refinement for.
- `max`'s `(x >= y ==> z = x) /\ (x < y ==> z = y)` likewise collapses to "the
  result is one of the two", which is not statable either, so `corpus/nat/select`
  keeps only nonnegativity.

Three further subtractions, each recorded in the manifest entry that pays it:

- **`<=` does not exist.** R5's assumed base interprets exactly `+ - = <`
  (`I64.add`, `I64.sub`, `I64.eq`, `I64.lt`). `Prims.nat`'s `i >= 0` is therefore
  written `-1 < i`, which is the same predicate over the SMT‑LIB `Int` §3.2.1
  gives `I64` — not an approximation, but worth writing down because the corpus
  surface no longer looks like the F\* one.
- **`max`'s own comparison is lifted to a parameter.** Comparing two `nat`s means
  passing them to `I64.lt`, whose domain is plain `I64`; that needs `{x:T|φ} <: T`,
  which R3 shows is unimplemented. So `corpus/nat/select` takes the boolean.
- **The list recursions are dropped.** `list_refb` and `map` at refined element
  types would need a measure over `List {n | -1 < n}`, and the assumed base's
  `List.size : List I64 -> I64` is monomorphic — bootstrap residue 5, recurring
  unchanged. Only the element step transpiles.

### R3 — What "checked" can mean here: a term meets a `refine` type only by structural equality

`typecheck.py` has no subsumption rule. §3.3 specifies refinement subtyping and
`refinements.py` *generates its verification condition*, but nothing in the
type‑directed layer consults either: `MatchChecker.check` compares the
synthesized type to the expected one with `actual == expected`, and a `refine`
node is just another type constructor in that comparison. Two consequences, both
now pinned by
`test_corpus.ExpressivenessLimitTest.test_a_term_meets_a_refine_type_only_by_structural_equality`:

- **No widening.** `{n | 0 < n}` does not flow into `{n | -1 < n}`.
- **No erasure either.** A plain `I64` inhabits neither, so no arithmetic result
  and no extern call can land in a refined codomain.

What *does* work is a refinement flowing through **unchanged** — including
inside a `(data …)` type argument and on both sides of a higher‑order parameter.
That is the whole of the `checked` region for this tranche, and it is why the six
fixtures split 3/3:

| # | Definition | Type | Tier | Shape it exercises |
|---|---|---|---|---|
| 1 | `math/abs` | `I64 -> {y \| -1 < y}` | `structural` | A refined codomain over a computed result: `if` + two interpreted externs |
| 2 | `list/lengthNat` | `List I64 -> {n \| -1 < n}` | `structural` | A refined codomain over an **extern** result — the assumed base reaching a refinement |
| 3 | `nat/widenPos` | `{n \| 0 < n} -> {n \| -1 < n}` | `structural` | §3.3 refinement subtyping itself, written out as a definition |
| 4 | `list/consNat` | `{a \| -1 < a} -> List {a \| -1 < a} -> List {a \| -1 < a}` | `checked` | A refinement **inside a data type argument**, constructed and returned |
| 5 | `nat/applyPos` | `({a \| -1 < a} -> {b \| 0 < b}) -> {a \| -1 < a} -> {b \| 0 < b}` | `checked` | Refinements in both halves of a higher‑order parameter |
| 6 | `nat/select` | `Bool -> {n \| -1 < n} -> {n \| -1 < n} -> {n \| -1 < n}` | `checked` | `if` at a refined result type (§3.1.4 meets §2.3) |

Three `structural` entries is more than any previous tranche, and that is a
finding rather than a shortfall: it is the first measurement of how much of §3.3
is specified but unbuilt. Each carries its `deferred` reason, and R6's
both‑directions tier test means implementing subsumption turns all three red and
forces the tier to be re‑declared.

**Rejected: holes with refined goals.** §2.6 confines a term containing holes to
the draft region, and the bootstrap plan's R6 already ruled that "a corpus of
draft‑region definitions is not a corpus". A hole would have made all six
`checked` and taught nothing. What is deferred here is *checking*, not content —
the same answer R6 gave, at a new layer.

### R4 — The obligation is manifest data, enforced in both directions

Tranche 3 established the pattern: a claim a fixture makes about itself goes on
the entry as data and is tested in both directions, so the field can never be
flipped to silence a failure. Tranche 4 adds `CorpusEntry.obligations`, a tuple
of `corpus_registry.Obligation`, and enforces:

- an entry whose **type** contains a `refine` node must carry at least one
  obligation; and
- an entry carrying an obligation must have a `refine` in its type.

(`test_corpus.CorpusObligationTest.test_refinements_and_obligations_imply_each_other`.)
A refinement therefore cannot enter the corpus without its obligation arriving
with it, which is §3.2's "nothing is ever silently unverified" as a property of
the manifest rather than a sentence in the spec.

An `Obligation` is §3.2.1's verification condition and nothing more: `base` is
the refined type `T` at index 0, `outer_context` is "any surrounding term context
appended to `Γ` after the refined value", `weaker` is `φ`, `stronger` is `ψ`.
`Obligation.script()` calls `refinements.subtype_script` with the corpus's own
`SMT_SIGNATURES` (the assumed base, new here) and the existing
`SMT_INTERPRETATION`, and `script_hash` pins the result. Four more tests:

- every pinned hash regenerates, and a second translation is the same bytes;
- both halves of every subtyping pair translate on their own over the
  obligation's `Γ`, so nothing is pinned that the translator would refuse;
- every `verdict` is declared, and a `sat` must record what is missing;
- `corpus/nat/widenPos` and `corpus/nat/applyPos` share a script hash **on
  purpose** — §3.2.1: "the obligation's name never enters the script, so two
  differently named obligations with the same verification condition share one
  memo‑ledger row (§6.4)" — and the test asserts they agree byte for byte.

**Only externs get signatures.** `SMT_SIGNATURES` covers the five assumed‑base
externs and no corpus definition. That is §3.2.1's own reasoning read the right
way round: "a def object has a body a future version could unfold; an extern has
none", so a predicate that named a corpus *definition* would be pinning an
uninterpreted symbol whose meaning a later version may change. Predicates here
name externs only.

**Rejected: a separate `test_corpus_obligations.py` wired into the Taskfile.**
The obligation tests are manifest‑consistency tests — they are the third
instance of the `tier` / `effect_free` both‑directions pattern, and splitting the
third one into its own file puts the same invariant style in two places and adds
a Taskfile edit for nothing. `refinements.py`'s *own* behaviour is already
covered by `test_refinements.py`; what is new here is what the manifest claims,
which is `test_corpus.py`'s subject.

### R5 — Which `ensures` claims are dischargeable today, and which are not

The scoping this tranche exists to produce. Six obligations, three `unsat`
(valid — the goal follows, and §3.2.1 says the obligation earns A3 `proof`
evidence) and three `sat`.

A `sat` here is **not** "we did not try hard enough". §3.2.1 is explicit that
`sat` *refutes* the obligation and the binding is rejected. Every `sat` below is
a claim that is **true** and whose proof needs a fact the v0.1 verification
condition cannot carry — which means that wiring these obligations into a
binding check today would reject three correct definitions. That is a
spec‑level finding, recorded in the residue below rather than absorbed.

**Dischargeable today (`unsat`):**

1. **`nat/widenPos :: subtype.pos-nat`** — `{n | 0 < n} <: {n | -1 < n}`. Pure
   §3.3, one context variable, no data sorts. The flagship: the one obligation
   whose discharge would turn its own fixture from `structural` into `checked`.
2. **`nat/applyPos :: subtype.argument-pos-nat`** — the same verification
   condition reached from the contravariant side, and deliberately the same
   pinned hash.
3. **`math/abs :: ensures.nonnegative`** — `Γ = [y, x]`,
   `H = [y = ite(x < 0, 0 - x, x)]`, `g = -1 < y`. Valid, and the most
   informative script in the tranche (see finding 1 below).

**Not dischargeable today (`sat`), with the specific missing fact:**

4. **`list/lengthNat :: ensures.nonnegative`** — `H = [n = List.size xs]`.
   `List.size` is deliberately absent from `SMT_INTERPRETATION` (bootstrap R5:
   "uninterpreted; the R4 measure primitive"), so the solver learns congruence
   and no lower bound. F\* proves `length : list 'a -> Tot nat` **by induction**;
   §3.2's fragment is quantifier‑free and has no induction principle. Routes:
   an A0 range assumption on the extern (§5.1.3 already makes externs A0), or
   body‑VC generation over the recursive definition.
5. **`list/consNat :: ensures.head-nonnegative`** — the element refinement is
   **erased**. §3.2.1 refinement‑erases a type in sort position "recursively,
   including inside data type arguments", so `List {n | -1 < n}` and `List I64`
   are literally the same monomorphized sort — asserted directly by
   `test_refinement_erasure_makes_a_refined_element_list_one_sort` — and "a
   refinement in an argument position therefore contributes no hypothesis".
   Nothing inside the fragment recovers it. Stating the invariant for a *whole*
   list would additionally need a quantifier the fragment does not have.
6. **`nat/select :: ensures.nonnegative`** — `H` holds exactly one predicate
   (§3.2.1: `{x:T|φ} <: {x:T|ψ}` becomes `H = [φ]`), and the two branch values'
   own `nat` refinements are erased in `Γ`, so neither is assumable alongside the
   body summary. Conjoining them would need `and`, which the assumed base does
   not supply, and a multi‑hypothesis `Γ ⊢ H ⊨ g` is precisely what body‑VC
   generation would build.

**The honest summary in one line:** what v0.1 can discharge is *subtyping between
two refinements over one already‑refined value*. Everything that needs a fact
about how a value was **computed** — which is what an `ensures` on a function
body is — is reachable only by hand‑authoring `φ` as a body summary in the
manifest, and only lands `unsat` when that summary happens to be expressible in
`+ - = <` plus `ite`. `math/abs` is the case where it is; the other three are
the cases where it is not.

### R6 — Grammar surfaces

`corpus/` is not globbed by `validate_gbnf.py` the way `examples/` is, so
surfaces are copied into `EXTRA_VALID` deliberately. Two were added.
`examples/03_refinement.loom.sexpr` already exercises `refine` at the top of a
definition type, but never:

- **as both halves of an arrow** — `nat/widenPos`, `(fn (refine …) () (refine …))`;
- **nested inside a `(data …)` type argument** — `list/consNat`, which is the
  position §3.2.1's erasure has to recurse into and the grammar had never been
  shown accepting.

## Work

- [x] Verify F\*'s licence from the repository rather than assuming it, and read
  the cited definitions from `ulib/` (R1).
- [x] Enumerate what the type‑first transpile loses, per entry (R2).
- [x] Establish by construction, not assertion, that a term meets a `refine`
  type only by structural equality, and pin it as an expressiveness limit (R3).
- [x] Build six fixtures — three `checked`, three `structural` with recorded
  `deferred` reasons — and pin their identities.
- [x] Add `corpus_registry.Obligation`, `CorpusEntry.obligations`, `VERDICTS`,
  and `SMT_SIGNATURES`; attach one obligation per fixture with its script hash
  and expected verdict pinned (R4).
- [x] Add `test_corpus.CorpusObligationTest`: hash regeneration and determinism,
  the both‑directions refinement/obligation rule, in‑fragment predicates,
  verdict declaration with a mandatory note on `sat`, the shared memo‑ledger
  row, erasure‑makes‑one‑sort, and an **optional** solver run gated on
  `LOOM_SMT_SOLVER` or `z3` on `PATH`.
- [x] Extend the provenance test with an F\* arm (R1).
- [x] Add two refinement surfaces to `validate_gbnf.py`'s `EXTRA_VALID` (R6).
- [x] Update `prototype/README.md`'s corpus narrative and file table.
- [x] Add this plan's row to `docs/plans/README.md`.
- [x] Re-declare tranche 4 as built in the bootstrap-corpus plan
  (strike-through), move its Status to "Tranches 1–4", and record the F\*
  licence verification in its R1.
- [x] Scope the dischargeable‑today set against the rest (R5).

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
LOOM_GBNF_VALIDATOR=/path/to/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
LOOM_SMT_SOLVER=/path/to/z3 python3 -m unittest test_corpus.CorpusObligationTest   # optional
```

## Completion criteria

- Six new fixtures exist in `prototype/corpus/`, each canonical and
  identity‑pinned, with its tier declared and enforced in both directions.
- Every `ensures`‑style claim in the tranche has a §3.2.1 verification condition
  whose canonical script's SHA‑256 is pinned in a test and regenerates.
- The manifest field carrying them is enforced in both directions, like `tier`
  and `effect_free` before it.
- Which claims are dischargeable today and which wait on body‑VC generation is
  written down per obligation, with the specific missing fact named.
- Provenance names FStarLang/FStar and Apache‑2.0, verified from the repository,
  and every weakening the type‑first transpile imposed is recorded on the entry
  that pays it.
- `typecheck.py`, `refinements.py`, `declarations.py`, `scope.py`,
  `transcode.py`, `loom.gbnf`, and `SPEC.md` are untouched.

## Recorded verification

Run on 2026‑08‑13.

**Result: PASS**

1. `task prototype:test`

    ```text
    ----------------------------------------------------------------------
    Ran 249 tests in 0.634s

    OK (skipped=1)
    ```

    PASS (249 of 249 OK — 241 before this plan plus 8: seven in the new
    `CorpusObligationTest` and one new `ExpressivenessLimitTest`. The six new
    manifest entries are covered automatically by the manifest‑iterating tests
    in `CorpusFixtureTest`. The single skip is the optional solver run, executed
    separately as step 6.)

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test`

    ```text
    GBNF PASS: 21 valid cases accepted; 16 invalid cases rejected
    ```

    PASS (19 valid cases before this plan; 21 after — the `nat/widenPos` and
    `list/consNat` surfaces added to `EXTRA_VALID`).

4. `task todo:lint`

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

6. `LOOM_SMT_SOLVER=…/z3 python3 -m unittest test_corpus.CorpusObligationTest -v`
   (optional; **Z3 version 5.0.0 - 64 bit**, obtained by unpacking the
   `z3-solver` wheel into a scratch directory — z3 is *not* on this machine's
   `PATH` and is not a dependency of the suite)

    ```text
    test_every_obligation_predicate_is_inside_the_decidable_fragment ... ok
    test_every_obligation_reproduces_its_pinned_script_hash ... ok
    test_every_verdict_is_declared_and_a_sat_says_why ... ok
    test_one_verification_condition_is_one_memo_ledger_row ... ok
    test_refinement_erasure_makes_a_refined_element_list_one_sort ... ok
    test_refinements_and_obligations_imply_each_other ... ok
    test_solver_verdicts_match_when_a_solver_is_available ... ok

    ----------------------------------------------------------------------
    Ran 7 tests in 0.159s

    OK
    ```

    PASS. All six pinned verdicts were produced by the solver, not predicted:
    three `unsat`, three `sat`, matching the manifest exactly.

### Pinned identities added

| Name path | Fixture | Tier | Identity (SHA-256) |
|---|---|---|---|
| `corpus/math/abs` | `math_abs_nat.loom.sexpr` | `structural` | `722a6900553dbe78a5fea5116255d5519deab85db50049222cfbb9f38c79b093` |
| `corpus/list/lengthNat` | `list_length_nat.loom.sexpr` | `structural` | `7ebd41f6467f08bc3876f6a4d137198115b6dd954ba68523440f3f9445cbd636` |
| `corpus/nat/widenPos` | `nat_widen_pos.loom.sexpr` | `structural` | `d9de68ecf5f6203a5b510e60183904138f5d4b71f60b636616cba82417e3b46d` |
| `corpus/list/consNat` | `list_cons_nat.loom.sexpr` | `checked` | `77c735fb26b542c3288ecb6dda4bca9f337c20bab57aa02aa057895d132e0c9f` |
| `corpus/nat/applyPos` | `nat_apply_pos.loom.sexpr` | `checked` | `48e49ab0d1ae05af9f075a14f5af944cc267fa88095f0e8fbdb07bbaedd92ff8` |
| `corpus/nat/select` | `nat_select.loom.sexpr` | `checked` | `4300a5090d354a1ad4dac0ce1a3ff1e96af401c3fca2a6d5c0e685bc5dfdaca4` |

The bootstrap corpus now carries **26 fixtures** total (6 from tranche 1's built
subset, 7 from tranche 2, 7 from tranche 3, and these 6).

### Pinned verification-condition script hashes

The §6.4 memo‑ledger payload key for each obligation: the SHA‑256 of the
canonical SMT‑LIB script `refinements.subtype_script` emits for it.

| Owner | Obligation | Script SHA-256 | Verdict |
|---|---|---|---|
| `corpus/math/abs` | `ensures.nonnegative` | `3f2827e45b57868083f5281a54e7527086fce2ed7fd1e2b562fb61c602c6b883` | `unsat` |
| `corpus/list/lengthNat` | `ensures.nonnegative` | `253432acedceb5a09769bb82edff1c73f0f8100a213b7a940107493b1cfbe4c5` | `sat` |
| `corpus/nat/widenPos` | `subtype.pos-nat` | `0aee355cf7a5bdffb9ae32b9c859203e96140431c978d21b0572d3f1a9cf00c1` | `unsat` |
| `corpus/list/consNat` | `ensures.head-nonnegative` | `067345e1c37280e8047dfb020e7f5086a7bcd19bbda18406ba4a7b2f92ff30db` | `sat` |
| `corpus/nat/applyPos` | `subtype.argument-pos-nat` | `0aee355cf7a5bdffb9ae32b9c859203e96140431c978d21b0572d3f1a9cf00c1` | `unsat` |
| `corpus/nat/select` | `ensures.nonnegative` | `952812314f7eb1da073261e40ec289e7a0a8b8d3a6afef61073e596eb4bbaa08` | `sat` |

`nat/widenPos` and `nat/applyPos` share `0aee355c…` deliberately — the §6.4
property, exercised rather than asserted.

The `nat/widenPos` script in full, since it is the whole of §3.3 in seven lines:

```smt2
(set-logic ALL)
(declare-const loom.x0 Int)
(assert (and (<= (- 9223372036854775808) loom.x0) (<= loom.x0 9223372036854775807)))
(assert (< 0 loom.x0))
(assert (not (< (- 1) loom.x0)))
(check-sat)
(exit)
```

### Findings, recorded rather than fixed

1. **`math/abs` is provable in the encoding and false on real hardware at
   `INT_MIN` — a live instance of §3.2.1's stated `Int` fidelity limit, inside
   the corpus.** The obligation is `unsat` because the I64 domain axiom on the
   *result* variable makes the one overflowing model infeasible; it does not
   model the wrap, it excludes it. On a wrapping 64‑bit `I64.sub`,
   `0 - (-2^63) = -2^63`, which is negative, so the `ensures` is false. §3.2.1
   already says "`Int` does not wrap, so a proof that depends on 64‑bit overflow
   is unsound", and says the interpretation of `I64.sub` as `-` "is exactly as
   strong as that extern's mandatory A0 justification (§5.1.3)". This is the
   first corpus entry where that sentence has teeth: the A3 this obligation
   would earn is A3 relative to an A0 assumption, and the overflow hides in the
   assumption, not in the proof. Recorded, not fixed — fixing it means a
   bit‑precise encoding, which leaves the named fragment.
2. **A `sat` verdict on a *true* claim rejects a correct binding.** §3.2.1 says
   `sat` "refutes the obligation and the binding is rejected". Three of six
   obligations here are `sat` while their claims are true, because the v0.1 VC
   shape cannot carry their premises. So the current wording turns an
   *expressiveness* limit into a *rejection*, where `unknown` — which §3.2.1
   already handles by leaving the obligation undischarged for weaker evidence —
   is the outcome the situation actually calls for. Escalated below.
3. **`refinements.py` is more complete than `typecheck.py` at the same spec
   section.** The translator handles refinement types, erasure, monomorphized
   datatypes, and subtyping VCs; the type‑directed layer has no subsumption rule
   at all, so the two never meet. Nothing calls `subtype_script` from typing.
   That gap is the entire reason three fixtures are `structural`, and it is a
   single, well‑scoped piece of work rather than a design question — R3.
4. **The manifest now hand‑authors body summaries.** `math/abs`'s and
   `nat/select`'s `weaker` predicates are *our* description of what the body
   computes, not a derived fact. That is the honest boundary of the tranche and
   is stated on the `Obligation` docstring, but a wrong summary here would be
   §13 open problem 2 in miniature — a contract that verifies a program it does
   not describe. It is safe only because the summaries are three lines each and
   sit next to the fixtures they summarize; it does not scale, and body‑VC
   generation is what replaces it.
5. **No F\* `decreases` came across, despite R1 naming it as F\*'s unique
   advantage.** Every fixture in this tranche is non‑recursive — the recursions
   were dropped for the monomorphic‑measure reason in R2 — so the one thing F\*
   supplies that Unison does not is still unspent. It is not reachable until the
   measure problem (bootstrap residue 5) moves.

### Residue and escalations

1. **§3.3 refinement subtyping is specified, its VC is generated, and no typing
   rule consults it.** Wiring `refinements.subtype_script` into `MatchChecker`
   as a subsumption rule would move three of this tranche's six fixtures from
   `structural` to `checked` and is the single highest‑value piece of work the
   corpus has surfaced. It needs a decision this plan does not make: whether the
   type‑directed layer may call a solver at all, or whether it emits obligations
   for a later pass. **Escalated — a design call, not a corpus call.**
2. **`sat` should not be the verdict for an inexpressible premise (finding 2).**
   Either §3.2.1 distinguishes "the VC is refuted" from "the VC as v0.1 can
   build it is refuted", or v0.1's VC shape grows a multi‑hypothesis form. As
   written, a checker wired to §3.2.1 today would reject three correct
   definitions in this repository's own corpus. **Escalated — a `SPEC.md`
   change, and this plan does not touch `SPEC.md`.**
3. **The assumed base supplies no `and`, `or`, `not`, `<=`, or `>=`, though
   §3.2.1's allowlist admits all five.** The allowlist is a closed set of SMT‑LIB
   symbols; the *externs* that could be interpreted as them do not exist, so a
   conjunctive refinement is unwritable and every predicate here is a single
   comparison. Adding `Bool.and`/`Bool.or`/`Bool.not` and `I64.le` to R5's
   assumed base is mechanical and would widen the expressible refinement
   language considerably. Not done here: R5's "the assumed base is kept to five,
   all enumerable, all pinned" is a deliberate §11 auditing property, and
   growing it is that plan's call.
4. **A list‑element invariant is not statable at all.** §3.2's fragment is
   quantifier‑free, so "every element of this list is nonnegative" has no form,
   and §3.2.1's erasure means the element refinement in `List {n | -1 < n}`
   contributes nothing either. `corpus/list/consNat` carries the strongest
   approximation available — a claim about the head — and it is `sat`.
5. **Bootstrap residue 5 blocked this tranche too**, unchanged: `List.size`'s
   monomorphic `List I64 -> I64` cannot measure a recursion over
   `List {n | -1 < n}`, so the F\* list functions arrive as element steps rather
   than as the recursive definitions they are. Same cause, second tranche.
