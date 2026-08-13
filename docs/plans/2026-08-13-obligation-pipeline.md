# Plan — The obligation pipeline, and what a `sat` verdict means

**Date:** 2026‑08‑13
**Status:** Implemented and verified locally
**TODO entry:** `[T4] Define the obligation pipeline: who consults the solver, and
what `sat` means (§3.2.1/§3.3/§6.2 seam; tranche‑4 escalations 1+2)`
**Depends on:**
[Refinement‑to‑SMT‑LIB translation rules](2026-08-13-refinement-smtlib-translation.md)
(the canonical script and its byte‑level pins),
[Bootstrap corpus tranche 4](2026-08-13-corpus-tranche-4.md) (the six pinned
obligations and the three `sat` diagnoses — this plan's test corpus),
[the tranche‑4 review](../reviews/2026-08-13-corpus-tranche-4-review.md)
(findings 1 and 2, ratified into the backlog),
`SPEC.md` §3.1 (elaboration), §3.2/§3.2.1 (the fragment, the VC, the script),
§3.3 (refinement subtyping), §3.4 (crisp by design), §5.1.3 (externs are A0),
§5.3.2 (admission), §6.1–§6.3 (evidence kinds, obligations, monotone assurance),
§6.4 (the memo ledger)

## Objective

Close the two entangled seams tranche 4 escalated:

- **(a) Nothing consults the subtyping verification condition.** `§3.3` is
  specified, `refinements.subtype_script` generates its VC, and no caller exists.
  Whether the typing layer may call a solver at all is an open architectural
  fork.
- **(b) `sat` is the wrong verdict semantics.** §3.2.1 says "`sat` refutes the
  obligation and the binding is rejected". A `sat` model is produced against an
  *abstraction* — uninterpreted symbols, erased refinements, idealized `Int` —
  so it need not correspond to any real Loom valuation. A checker conforming to
  the sentence as written rejects three correct definitions in this repository's
  own corpus today.

Both are normative calls. This plan makes them, states the replacement rules in
`SPEC.md`, and lands the prototype surface that makes them executable: an
emission layer, a mechanical exactness check, and a three‑way outcome derived
from `(raw verdict, exactness)`.

No visible surface (normative text, one new prototype module, tests), so this
plan carries no mockups.

## Rules

### R1 — Decision (a): the typing layer **emits** obligations; a separate oracle pass discharges them

**The rule.** Typing never invokes a solver. The typing layer's job ends at
producing, for each refinement‑subtyping site it admits, an *obligation* whose
canonical verification condition and SMT‑LIB script (§3.2.1) are determined.
A separate **oracle pass** runs solvers over those scripts and mints §6.1
evidence from the results. Admission (§5.3.2) consults the *evidence*, never the
solver. The three stages are:

```
typing (decidable, solver-free)  →  emission: (obligation-id, VC, script, script-hash)
      →  oracle pass: solver verdict  →  evidence (§6.1)  →  admission (§5.3.2)
```

Consequences that make this more than a diagram:

- **Typing terminates on a schedule.** Type checking a definition never blocks
  on a solver call and never becomes undecidable because a predicate got hard.
  §3.3 subsumption is *admitted at typing time* against a recorded obligation;
  it does not wait for a verdict.
- **The memo ledger becomes reachable.** §6.4 keys evidence on the script hash,
  not the obligation's name. Emission produces that hash before any solver runs,
  so the pass is a cache lookup first and a solver call second — which is the
  whole of P4/P5's economics. A solver in the typing loop would key work on the
  typing site instead, and the tranche‑4 collision (`nat/widenPos` and
  `nat/applyPos` sharing one script) would be two solver calls rather than one
  ledger row.
- **The verdict is evidence, not a typing precondition.** §6.2 already says every
  obligation carries exactly one evidence entry and A0 is legal but loud. A
  solver failure therefore degrades the *evidence level*, not the *type*. That
  is what lets an undischargeable obligation be covered explicitly (§6.3) rather
  than making the definition untypeable.
- **§3.4 stays intact.** The referee gate stays two‑valued and stays at
  admission, where a policy compares evidence against a requirement. Nothing at
  the margin is graded.

**Rejected: solver‑in‑the‑typing‑loop.** Calling `subtype_script` from
`MatchChecker` at each subsumption site is fewer moving parts and would flip
three corpus fixtures to `checked` immediately. It is rejected on four counts.
Typing would inherit the solver's termination behaviour, so `unknown` and a
timeout would have to mean *type error* — §3.2.1 explicitly says they mean
undischarged. Identity would become inference‑strength‑dependent in spirit if not
in bytes, against §3.1's "identity never depends on inference strength". Evidence
would have two producers (the typechecker and the oracle pass) with no single
place to apply §6.3's monotonicity. And every regeneration (P4) would re‑pay
solver cost that §6.4 exists to eliminate. The spec's own architecture — §6's
evidence objects, the oracle as a distinct layer in §1, §5.3.2's evidence‑
consulting admission — already assumes emission; this rule states it.

**Not in scope here:** implementing §3.3 subsumption in `typecheck.py`. That is
now unblocked (it is a typing‑layer change that emits rather than solves) but it
is a separate, larger change that would re‑tier three corpus fixtures. Recorded
as residue 1.

### R2 — Decision (b): `sat` refutes only a **validated countermodel**; the outcome is three‑way

**The rule.** A solver verdict is a *raw fact* about a script. The **outcome** of
an obligation is derived from that fact plus whether the script is **exact**:

| Raw verdict | Exact | Outcome | Effect |
|---|---|---|---|
| `unsat` | either | `proved` | A3 `proof` evidence is available (§6.1), unchanged |
| `sat` | yes | `refuted` | the countermodel is validated; the binding is rejected |
| `sat` | no | `undischarged` | no evidence from this VC; cover explicitly (§6) |
| `unknown`, timeout | either | `undischarged` | as today |
| out of fragment | — | `undischarged` | no script exists, so no verdict |

`refuted` and `undischarged` are distinct because they are different claims. A
refutation says *the proposition is false*; an undischarged obligation says
*this verification condition proved nothing either way*. Collapsing them is the
current spec bug: it converts every expressiveness limit into a rejection.

**Exactness is a property of the emitted script, checked mechanically, in two
independent parts.** A model of the script counts as a countermodel of the
obligation only if it can be read back as a real Loom valuation of the real
obligation. Two things can break that, at two different stages.

**E‑gen — generator faithfulness (obligation → VC).** The verification condition
must have been produced by a verification‑condition producer this specification
names. v0.1 names exactly one: refinement subtyping (§3.2.1). A VC whose
hypotheses are *asserted* rather than derived — a hand‑authored body summary, the
shape the corpus manifest uses today because body‑VC generation is future work —
is not generator‑faithful, because its hypothesis list is not known to be
everything the program establishes at that point. A model that violates a
premise the VC forgot to state is an artifact of the VC, not a counterexample to
the program.

Under R1 this is not a runtime burden: the emission layer is the only thing that
mints a VC, and it stamps the producer. E‑gen is therefore satisfied by
construction for anything the pipeline produces, and fails exactly where a VC
arrives from somewhere else — which is the honest statement of §3.2.1's
"verification‑condition generation for function bodies is future work".

**E‑tr — translation faithfulness (VC → script).** Five conditions, each read off
the translator's own record of what it did while emitting the script, so there
is no second walk that can disagree with the first:

1. **No uninterpreted reference.** No `declare-fun` was emitted: every `ref` in
   `H` or `g` had an interpretation‑table entry. An uninterpreted symbol lets the
   solver invent a function the real definition does not compute.
2. **Concrete sorts only.** No `declare-sort` was emitted: `F64`, `Text`, and
   `Bytes` never reached sort position. Their sorts are uninterpreted, of
   unrelated cardinality, and `F64` equality in the encoding is *bitwise*
   (§3.2.1) rather than IEEE‑754 numeric — so a model over them is not a
   valuation of the corresponding Loom type.
3. **No erased refinement.** No `refine` node was dropped in sort position — in
   a context type, or inside a data type argument. Erasure is what makes
   `List {n | -1 < n}` and `List I64` one sort; a model may then assign the list
   an element the refinement forbids.
4. **Faithful symbols only.** Every interpreted symbol the script used is in the
   faithful subset of §3.2.1's allowlist — `not and or => = distinct ite`,
   `< <= > >=` — and none is in the idealizing subset `+ - * div mod abs`, whose
   SMT‑LIB `Int` meaning departs from `I64`'s wrapping meaning. This is the
   countermodel side of §3.2.1's already‑stated `Int` fidelity limit: an
   unbounded intermediate makes a model unrealizable on real hardware.
5. **Every `Int`‑sorted symbol is domain‑bounded.** §3.2.1's I64 domain axiom is
   emitted for context variables only, so the only `Int`‑sorted symbols admitted
   are context variables and integer literals. A `match` binder at sort `Int`
   reads a datatype field that no axiom bounds, and a model may set it outside
   `I64`.

**Exactness never removes the A0 dependence on the interpretation table.**
Mapping `I64.lt` onto `<` is a claim about a foreign artifact and is exactly as
strong as that extern's mandatory A0 justification (§5.1.3, unchanged). E‑tr says
that *given* the table's entries, the encoding introduces no further gap.
Condition 4 is a separate matter: `Int` differs from `I64` even when `I64.add`
is precisely what its A0 says it is.

**Rejected: concrete evaluation of the countermodel.** The strongest rule is to
take the solver's model, substitute it into the original Loom term, and evaluate
under real semantics — accepting the refutation only if the predicate really
comes out false. It is strictly more precise than syntactic exactness (it would
validate a `sat` on an arithmetic script whose model happens not to overflow),
and it is the right long‑term answer. It needs an evaluator, and the prototype
has none — §13's residue notes the multi‑shot handler is already operationally
meaningless for the same reason. Reserved as future work, and named as such in
`SPEC.md` so the syntactic rule is visibly a floor rather than the ceiling.

**Rejected: drop `refuted` entirely and make every `sat` undischarged.** Simplest
of all, and sound. It is rejected because it discards the one thing a solver is
uniquely good at — finding a concrete counterexample to a claim an author got
wrong — and because a rule that can never say "no" gives the generating agent
(P1, §3.4) no signal that its refinement is false rather than merely hard. The
exact fragment is small today, but `nat/widenPos` demonstrates it is non‑empty.

**Rejected: making a generator‑unfaithful `unsat` undischarged too.** The
symmetric rule would say an `unsat` under an *asserted* premise proves nothing,
and it has a real argument behind it — a wrong body summary is tranche‑4's
finding 4, "a contract that verifies a program it does not describe". It is
rejected because that is not the same defect. An abstraction invents a *witness*
out of nothing, which is what makes a model untrustworthy; an asserted premise
leaves the `unsat` a genuine proof of a claim *conditional on that premise*, and
a conditional claim is exactly what A0 accounting already exists for (§5.1.3,
§5.3.1). Handling it twice would double‑count it and would suppress a real
proof. `SPEC.md` states the asymmetry and its reason rather than leaving it to be
inferred.

**Rejected: downgrading an inexact `unsat`.** Tempting for symmetry, and
`math/abs` is the case that invites it — provable in the encoding, false on
wrapping hardware at `INT_MIN`. It is rejected because §3.2.1 already handles
that direction: the A3 an obligation earns over an interpreted extern is A3
*relative to* an A0 assumption, and §5.3.1's assumption count is where it
surfaces. Adding a second mechanism for the same fact would double‑count it.
Exactness is recorded on the `unsat` side too, because it is precisely the flag
that says whether the A3 is unconditional or A0‑relative, but it changes no
outcome there.

### R3 — The manifest records the raw verdict as a fact and the outcome as a claim

`Obligation.verdict` keeps recording what a solver actually returns — it is an
observation, reproduced by the optional solver run, and it must not be
overwritten by an interpretation of it. Two fields are added beside it:

- `producer` — which verification‑condition producer built this VC. `"subtype"`
  is §3.2.1's one specified producer; `"authored"` says the hypothesis is a
  hand‑written body summary, which is what four of the six tranche‑4 obligations
  are.
- `outcome` — the derived three‑way result, pinned as manifest data.

Both are enforced in both directions, the pattern `tier`, `effect_free`, and
`obligations` already established:

- `producer == "subtype"` **iff** both halves of the pair occur as predicates of
  `refine` nodes in the entry's own declared type. A hand‑authored body summary
  cannot be found there, and a genuine subtyping pair always can. So the
  manifest cannot relabel an authored VC as generated to buy itself a
  refutation.
- `outcome` **equals** `obligations.outcome(verdict, exactness)` recomputed from
  the freshly emitted script. So the manifest cannot pin an outcome the rule
  does not produce.

### R4 — What the six pinned obligations become, and the one that is not what it looks like

Recomputed from the emitted scripts (all six pinned hashes unchanged):

| Obligation | Raw verdict | E‑gen | E‑tr | Exact | Outcome |
|---|---|---|---|---|---|
| `math/abs :: ensures.nonnegative` | `unsat` | ✗ authored | ✗ uses `-` | no | `proved` |
| `list/lengthNat :: ensures.nonnegative` | `sat` | ✗ authored | ✗ `List.size` uninterpreted | no | **`undischarged`** |
| `nat/widenPos :: subtype.pos-nat` | `unsat` | ✓ | ✓ | **yes** | `proved` |
| `list/consNat :: ensures.head-nonnegative` | `sat` | ✗ authored | ✗ erased refinement; `Int` match binder | no | **`undischarged`** |
| `nat/applyPos :: subtype.argument-pos-nat` | `unsat` | ✓ | ✓ | **yes** | `proved` |
| `nat/select :: ensures.nonnegative` | `sat` | ✗ authored | **✓** | no | **`undischarged`** |

All three `sat` cases land as `undischarged`, as required: no correct definition
is rejected. But the third row of that group is reported loudly rather than
smoothed:

**`corpus/nat/select`'s script is translation‑exact.** Its VC uses only `=`,
`ite`, and `<` over `Int` context variables with the domain axiom; it declares no
uninterpreted function, no opaque sort, no datatype, and erases no refinement.
The translator introduced no abstraction at all. So the countermodel — `b` true,
`x₂ = x₀ = -5` — is a real valuation *of the verification condition as written*.

What saves the definition is E‑gen, and the reason is worth stating exactly: the
manifest's `outer_context=(Bool, I64, I64)` writes the two branch arguments as
plain `I64`, but the definition's declared type is
`Bool -> {n | -1 < n} -> {n | -1 < n} -> {n | -1 < n}`. The refinements were not
erased by the translator — they were **dropped by hand when the VC was
authored**. Tranche 4's note attributes this `sat` to "the two branch values'
own `nat` refinements are erased in Γ"; that reading is off by one stage. The
erasure §3.2.1 performs would happen in *sort* position and would leave the
hypothesis behind; what actually happened is that the hand‑authored VC never
stated the premises in the first place. E‑gen catches it, but only because the
producer is declared honestly — which is exactly why R3 makes `producer`
enforceable from the fixture's own type rather than trusting the field.

The corpus claim is therefore corrected rather than merely re‑bucketed: the
`nat/select` note now says the VC omits premises the definition's type supplies,
and names multi‑hypothesis body‑VC generation as the fix. The tranche‑4 residue
item about the assumed base lacking `and` remains true and still applies, but it
is not the whole cause.

### R5 — Where the code goes: a new `obligations.py`, and `refinements.py` reports rather than judges

`refinements.py` learns to **record what abstractions it used** while emitting a
script — five booleans/sets, all populated on paths that already run, none of
which touches a rendered byte. It gains no policy: it does not know what
"exact" means. That keeps the module a translator, and it keeps the exactness
facts co‑located with the single walk that establishes them, so no second
traversal can silently disagree with the first.

`obligations.py` is the new emission layer and holds the policy: the
`VerificationCondition` record with its producer stamp, `emit` (the
`(obligation-id, script, script-hash)` triples the corpus already builds by
hand), the exactness rule of R2, and `outcome`. It also carries the
pipeline's ordering: `emit_definition` typechecks the definition first and
refuses to emit for one that does not typecheck, because obligation emission is
a *consequence* of typing, not an alternative to it.

**Rejected: a solver call anywhere in the prototype.** `obligations.py` emits and
judges; it never shells out. The optional solver run stays exactly where
tranche 4 put it, in a test, env‑gated.

**Rejected: putting emission in `typecheck.py`.** The module is already the
largest in the prototype and its subject is bidirectional typing. Emission
consumes typing's output; a separate module makes the pipeline's stages legible
and keeps `typecheck.py` free of anything SMT‑shaped.

**Rejected: keeping the new tests in `test_corpus.py`.** Tranche 4 argued
correctly that *manifest* claims belong in `test_corpus.py`. The exactness rule
is `obligations.py`'s own behaviour, which is `test_refinements.py`'s situation,
not the manifest's — so `test_obligations.py` is new, and the manifest‑coherence
half (`producer`, `outcome`, both directions) stays in `test_corpus.py`.

## Work

- [x] State the emission pipeline in `SPEC.md` §3.2.1, with a §3.3 sentence and a
  §6.2 echo (R1).
- [x] Rewrite §3.2.1's verdict paragraph as the three‑way outcome, define
  exactness with its two parts and five mechanical conditions, and name concrete
  evaluation as the reserved stronger rule (R2).
- [x] Record used abstractions in `refinements.py` without changing a rendered
  byte (R5).
- [x] Add `prototype/obligations.py`: `VerificationCondition`, `emit`,
  `emit_definition`, `Exactness`, `outcome` (R1, R2, R5).
- [x] Add `producer` and `outcome` to `corpus_registry.Obligation`; correct the
  `nat/select` note (R3, R4).
- [x] Extend `test_corpus.CorpusObligationTest` with both‑directions tests for
  `producer` and `outcome` (R3).
- [x] Add `test_obligations.py`: the exactness rule directly — an exact script's
  `sat` is a refutation, an inexact script's `sat` is undischarged, one test per
  E‑tr condition, and the pipeline's typecheck‑before‑emit ordering (R5).
- [x] Wire `test_obligations` into `task prototype:test`.
- [x] Update `prototype/README.md` and add this plan's row to
  `docs/plans/README.md`.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
LOOM_SMT_SOLVER=/path/to/z3 python3 -m unittest test_corpus.CorpusObligationTest   # optional
```

## Completion criteria

- `SPEC.md` states who consults the solver, and a `sat` no longer rejects a
  binding unless its countermodel is validated.
- The exactness rule is stated precisely enough that two implementers compute
  the same answer from the emitted script.
- All six tranche‑4 script hashes still reproduce, byte for byte.
- The three `sat` obligations land as `undischarged`; no correct corpus
  definition is rejected under the new rule.
- Any `sat` case that *is* exact is reported rather than smoothed.

## Recorded verification

Run on 2026‑08‑13.

**Result: PASS**

1. `task prototype:test`

    ```text
    ----------------------------------------------------------------------
    Ran 272 tests in 0.870s

    OK (skipped=1)
    ```

    PASS (249 before this plan plus 23: twenty in the new `test_obligations.py`
    and three new manifest tests in `test_corpus.CorpusObligationTest`. The 249
    baseline was re-measured on this tree by stashing the three modified
    prototype files and re-running the pre-existing module list. The single skip
    is the optional solver run, executed separately as step 5.)

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
   (optional; **Z3 version 5.0.0 - 64 bit**, unpacked from the `z3-solver` wheel
   into a scratch directory — z3 is not on this machine's `PATH` and is not a
   dependency of the suite)

    ```text
    test_every_obligation_predicate_is_inside_the_decidable_fragment ... ok
    test_every_obligation_reproduces_its_pinned_script_hash ... ok
    test_every_verdict_is_declared_and_a_sat_says_why ... ok
    test_no_sat_obligation_is_refuted_and_the_exact_one_is_named ... ok
    test_one_verification_condition_is_one_memo_ledger_row ... ok
    test_pinned_outcomes_are_what_the_rule_derives ... ok
    test_producer_agrees_with_the_fixtures_own_refinement_predicates ... ok
    test_refinement_erasure_makes_a_refined_element_list_one_sort ... ok
    test_refinements_and_obligations_imply_each_other ... ok
    test_solver_verdicts_match_when_a_solver_is_available ... ok

    ----------------------------------------------------------------------
    Ran 10 tests in 0.235s

    OK
    ```

    PASS. The six pinned verdicts were produced by the solver, not predicted.

### The exactness table, reproduced

Emitted by `obligations.emit` over the manifest — raw output, with the final
column asserting the pinned §6.4 script hash is unchanged:

```text
obligation                                           verdict E-gen  E-tr  outcome   hash-ok
corpus/math/abs :: ensures.nonnegative               unsat   False  False proved       True
corpus/list/lengthNat :: ensures.nonnegative         sat     False  False undischarged True
corpus/nat/widenPos :: subtype.pos-nat               unsat   True   True  proved       True
corpus/list/consNat :: ensures.head-nonnegative      sat     False  False undischarged True
corpus/nat/applyPos :: subtype.argument-pos-nat      unsat   True   True  proved       True
corpus/nat/select :: ensures.nonnegative             sat     False  True  undischarged True
```

### Residue

1. **§3.3 subsumption is still unimplemented in `typecheck.py`.** The design
   fork that blocked it is now closed — the typing layer admits the subsumption
   and emits the obligation — but the typing rule itself is not written, so
   `corpus/math/abs`, `corpus/list/lengthNat`, and `corpus/nat/widenPos` remain
   `structural`. That is now a bounded implementation task against a settled
   design rather than an open question.
2. **The exact fragment is small.** Under E‑tr, exactness excludes every
   arithmetic operator, so today only subtyping between two comparison
   predicates over context variables qualifies. That is the honest floor;
   concrete evaluation (rejected above, reserved in `SPEC.md`) is what widens it,
   and a bit‑precise encoding would widen condition 4 specifically.
3. **`corpus/nat/select`'s VC understates its own premises** (R4). Correcting it
   needs a multi‑hypothesis VC — `and` in the assumed base is one half (the
   already‑ranked T2 item), body‑VC generation the other. Left as recorded rather
   than patched, because changing the VC changes a pinned script hash and that
   belongs to whichever plan builds the generator.
4. **E‑gen is trivially satisfiable in the prototype**, since the corpus declares
   its own `producer`. The both‑directions test in R3 is what keeps it honest,
   and it is a real check — it derives the answer from the fixture's declared
   type — but a live pipeline would have the emitter stamp it instead, and no
   emitter‑stamped VC exists outside `obligations.emit` yet.
5. **An `unsat` under a hand‑authored premise still earns `proved`**, by the
   asymmetry argued in R2. `corpus/math/abs` is the live case: its A3 is
   conditional both on `I64.sub`'s A0 and on the manifest's summary of what the
   body computes. Nothing here makes that condition visible in an evidence
   object; it becomes visible when §5.3.1's assumption count is actually
   computed over emitted obligations, which no code does yet.
