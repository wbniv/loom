# Plan — Bootstrap corpus for prior starvation

**Date:** 2026‑08‑13
**Status:** Tranche 1 seed set implemented and verified locally; tranches 2–4 specified, not built
**Depends on:** SPEC.md §2 (node and type vocabulary), §2.4 (builtin abilities), §2.5
(totality), §2.6 (holes), §3.1.1 (nominal constructor and match typing), §3.2.1
(SMT translation and the interpreted-symbol allowlist), §4 (canonical form and
identity), §5.1.1 (data declarations), §5.2 (meta objects), §6.2 (obligations),
§8.4 (feasibility on 2026 decoders), §11 (the boundary), §13 open problem 1

## Objective

Turn §13 open problem 1 from "a plan, not a result" into a corpus with a first
tranche on disk. §8.4 ends on the sharpest sentence in the spec — *"a masked
model with no Loom corpus produces well-formed, well-scoped, type-plausible
junk. Validity today; fluency only after the bootstrap problem (§13.1) is paid
down."* Everything else in §8 is buildable with 2026 technology; this is the one
input the design cannot mask its way to.

This plan picks the source corpus, states what transpilation loses, orders a
concrete first tranche so that no definition precedes its dependencies, fixes
the storage shape so a §8.4 few‑shot prompt reads straight off it, and lands
four hand‑transpiled definitions as validated fixtures.

Out of scope, deliberately: a transpiler *tool* (R8 argues hand‑first is
correct at this size); evidence objects for the seed set (§6 machinery exists,
but nothing in tranche 1 carries a refinement, so there is nothing yet to
discharge); and any change to §2's node vocabulary, however much R4 and R5 want
one — those are recorded as residue for the orchestrator, not decided here.

No visible surface (fixtures and normative text only), so this plan carries no
mockups.

## Rules

### R1 — The primary corpus is Unison base; F\* is a secondary source for tranche 4

Four candidates, judged on one question: **how many definitions land in canonical
Loom with nothing invented and nothing silently weakened?**

| Candidate | What matches | What breaks |
|---|---|---|
| **Unison base** | No typeclasses at all, so zero dictionary elaboration. Rank‑1 HM polymorphism. Algebraic abilities — §2.4 is explicitly modelled on them and the spec links Unison's docs. Content‑addressed store, so §4/§5's whole shape is native. | No refinements. No totality checker, so no measure is ever written down. `[a]` is a builtin sequence, not an ADT. |
| **Idris 2 / Agda stdlib** | Totality‑checked upstream, so termination is genuinely established. | Dependent types overshoot rank‑1 badly: `Vect n a` has no Loom encoding, and §2.3.1 states outright that v0.1 has no dependent function arrows. Interfaces are typeclasses. Implicit arguments everywhere. The *non*‑dependent residue is the Unison fragment anyway. |
| **F\*** | Refinements match §3.2 almost literally, and `decreases` is §2.5's measure already written down — the only candidate that supplies one. | Effects are a monadic lattice (`Tot`/`Div`/`ST`/`Ex`), not ability rows; `ST` has no encoding among §2.4's eight abilities. Most interesting signatures are dependent arrows. |
| Plain proven‑total functions | Least friction. | Not a corpus — a selection criterion. Applied *within* whichever corpus is chosen. |

**Chosen: Unison base as primary.** The deciding argument is not that Unison
matches Loom's type system best — F\* matches the *type* system better — but that
Unison matches Loom's **term** language, and the term language is what §8.4 needs
priors over. A Unison structural eliminator transpiles with **no type weakened**;
only names are erased, and §5.2 puts names outside identity anyway.

**Rejected: F\* as primary.** Take almost any verified F\* function and its type
is a dependent arrow. Dropping the dependency to fit §2.3.1 does not lose
decoration — it changes the proposition. The transpiled definition is then no
longer the verified one, while *looking* like it is. That manufactures §13 open
problem 2 (a wrong contract verifying a wrong program) at corpus scale, in the
one artifact whose whole purpose is to be trusted as exemplary. F\* keeps a real
but narrow role: its refinement‑carrying lemmas over `int` and `list` whose
arrows are already non‑dependent are the source for tranche 4, transpiled
type‑first.

**Rejected: Idris/Agda as primary.** Its advantage over Unison is upstream
totality checking, and R4 shows that advantage evaporates: Loom cannot record a
proved measure for structural recursion anyway, so the imported termination
argument has nowhere to land.

**Source and licence, stated rather than assumed.** The definitions are from
[unisonweb/base](https://github.com/unisonweb/base); `Optional.getOrElse` and
`Either.mapRight` were spot‑checked against the
[Unison docs](https://www.unison-lang.org/docs/fundamentals/control-flow/exception-handling/).
The GitHub API reports **no machine‑detectable licence** for that repository as
of 2026‑08‑13 (`license: null`). Nothing is vendored: no Unison source text
enters this repository, and each seed entry is a three‑to‑five‑line structural
eliminator that is identical in every ML‑family standard library. **Confirm
licensing in writing before scaling past the seed set** — that is a real
residual risk, recorded here rather than assumed away.

### R2 — Mapping losses, enumerated

Stated as a list because "we transpiled Unison" is only honest with the
subtractions attached.

- **`[a]` becomes a cons‑list ADT.** Unison's list is a builtin finger‑tree
  sequence with O(1) access at both ends; Loom has no builtin sequence, so the
  corpus declares `List a = Nil | Cons a (List a)`. The *performance contract* is
  lost. §13's non‑goals already exclude a performance model, so this is a
  deliberate deferral, not an oversight.
- **Arithmetic disappears.** Unison's `Nat`/`Int` carry builtin arithmetic. Loom
  v0.1 has **no arithmetic terms at all** — `+` exists only in §3.2.1's
  *interpretation* allowlist, which maps a definition hash to an SMT symbol and
  therefore presupposes a definition that already exists. Arithmetic enters as
  assumed base (R5).
- **No measures come across.** Unison is not total and has no termination
  checker, so no recursive Unison definition supplies a measure. Every measure in
  tranche 2 is authored by us (R4).
- **Row polymorphism is dropped.** Unison's ability‑polymorphic signatures
  (`{g}`) have no checkable form here — `matches._closed_row` refuses a row
  containing a `tyvar`. Tranche 1 is ability‑free and tranche 3 uses closed rows
  only.
- **Nested patterns and guards are desugared.** Loom's `match` is one level,
  exhaustive, constructor‑indexed, with an explicit binder count (§2.1, §3.1.1).
  Unison `cases` with nested or literal patterns becomes nested `match`. This is
  elaboration (§3.1) and is identity‑relevant: two desugarings are two
  definitions.
- **Local mutual recursion is dropped.** `fix` binds one recursive value, so a
  mutually recursive group must be tupled or defunctionalized. Excluded from
  tranches 1–3.
- **Names, docs, `test>` watches, and `delay`/`force` are dropped.** Names and
  prose go to meta objects (§5.2); the rest has no Loom counterpart.
- **No dictionaries are lost, because there are none.** This is the whole
  advantage over Idris and F\*: Unison has no typeclasses, so nothing has to be
  elaborated away and nothing about the transpiled term is a compilation
  artifact.

### R3 — The seed set is monomorphic, because a polymorphic definition is unwritable in v0.1

Not a simplification — a hard limit, found while designing the tranche and
verified.

§2.3 offers rank‑1 `forall`, and §2.3.1 says `forall T` adds one type binder
**throughout `T`** — that is, inside the type only. There is no term‑level type
abstraction in §2.1's twelve tags, and §2.3.1 checks a closed definition's term
at type depth 0. But `lam` is "fully annotated", so the term of
`forall (fn (List a) () (Maybe a))` must annotate its parameter as `(data
#List ((tyvar 0)))` — a type variable that is out of scope in the term:

```text
definition.term.parameter-type.args[0]: type index 0 is out of scope at depth 0
```

So `forall` is inhabitable only by a `hole` (as `test_scope` already
demonstrates), never by a `lam`. **Every seed definition is therefore
instantiated at a concrete type**, `I64` by convention, and its polymorphic
source signature is recorded as metadata.

**Rejected: waiting for the language to grow a `tylam`/`tyapp` pair.** That is a
change to §2's closed node set, which §2 says is "mask complexity paid forever",
and it is not this plan's call. Monomorphic instances are complete, canonical,
checkable Loom definitions today; the corpus does not need to be blocked on it.
It is listed as residue below, and `test_corpus.ExpressivenessLimitTest`
asserts the limit so that lifting it fails loudly here.

**The cost, stated:** a model trained on this corpus sees no `forall` and no
`tyvar` in term position — because no valid Loom program contains one. That is
faithful, not a gap.

### R4 — Termination: every measure is authored, and `List.size` is the one assumed base case

§2.5 requires a `fix` to carry a measure the oracle proves strictly decreasing.
For structural recursion over `List a`, that measure is the list's size — and
`List.size` is itself structurally recursive, so its measure is itself.
Circular. §2.5 gives no primitive structural‑subterm ordering to bottom out on.

**Decision.** `List.size` is a member of the assumed base (R5): its `terminates`
obligation is a documented **A0 assumption** (§6.1, §11), justified in one line
(recursion on a strictly smaller constructor field), and **every other recursive
seed definition's measure is `(ref #List.size)`**. One assumption buys the whole
list tranche.

**Rejected: an A0 `terminates` on every recursive definition.** Same soundness,
far worse auditing — §11's "how much of this system is faith?" query would return
a number that grows linearly with the corpus instead of staying at one.

**Rejected: giving the list tranche the `div` ability.** §2.5 sanctions it, but
`div` in the row is visible in every caller's type all the way up, so a
divergent `List.map` poisons the type of everything built on it. `div` is
reserved for definitions that genuinely are not structurally decreasing — of
which tranche 1–3 contain **none**, stated as a positive claim.

**This costs nothing today anyway**, and that is the decisive point: §3.2.1 says
verification‑condition generation for function bodies is future work, so *no*
`terminates` obligation in v0.1 can reach A3 by any route. Writing the honest
measure and recording A0 is strictly better than pretending, and it is exactly
what §3.2's "nothing is ever silently unverified" asks for.

### R5 — Tranche 1 is arithmetic‑free and branch‑free, because Loom v0.1 has neither

Two limits force this, both verified rather than assumed.

**No arithmetic.** There is no `+` term. §3.2.1's allowlist interprets a
*stored definition hash* as `+`, so arithmetic must arrive as §11 `extern`
definitions carrying mandatory A0 assumption evidence. The assumed base is
kept to five, all enumerable, all pinned:

| Assumed | Loom type | §3.2.1 interpretation |
|---|---|---|
| `I64.add` | `I64 -> I64 -> I64` | `+` |
| `I64.sub` | `I64 -> I64 -> I64` | `-` |
| `I64.eq` | `I64 -> I64 -> Bool` | `=` |
| `I64.lt` | `I64 -> I64 -> Bool` | `<` |
| `List.size` | `List I64 -> I64` | uninterpreted; the R4 measure primitive |

**No conditional.** §3.1.1 requires a `match` scrutinee to synthesize a nominal
`data` type, and `Bool` is a base type (§2.2). Loom v0.1 therefore has **no
elimination form for `Bool`**:

```text
definition.term.body: match scrutinee does not synthesize a nominal data type
```

Booleans can be produced (by `lit`, or by an assumed `I64.lt`) and consumed by
refinement predicates through §3.2.1's SMT translation, but **nothing can branch
on one**. `List.filter`, `takeWhile`, `dropWhile`, `List.contains`, `Nat.max`,
and `Bool.not` are all inexpressible. This was discovered by trying to place
`Bool.not` in the tranche, and it is exactly the kind of finding the corpus
exercise exists to surface.

**Consequence:** tranche 1 is the arithmetic‑free, branch‑free, recursion‑free
fragment — which is *why* it is 24 structural eliminators over `Maybe`, `Either`,
`Pair`, and `List` rather than a numeric library.

**Residue, not a decision here:** the cheapest unlock is a corpus data
declaration `Bool2 = False | True` plus one assumed bridge `Bool -> Bool2`, which
would restore branching without touching §2. It is *not* adopted: a second
boolean type in the corpus that a model then has priors over is a bad thing to
teach if §2 later grows a real `if`. Escalated below.

### R6 — Two validation tiers, declared per entry, never silently degraded

A seed definition passes as many of the prototype's layers as exist for the
nodes it contains. Two tiers, recorded in the manifest:

- **`checked`** — parse/canonicity, scope, references, **and** the type‑directed
  match layer. The whole implemented stack.
- **`structural`** — parse/canonicity, scope, references; the match layer is
  deferred **with a recorded reason**, because it has no typing rule for a node
  the definition needs. Today that is exactly two nodes: `fix` (tag 10) and `ref`
  (tag 1) both raise `type synthesis for term tag N is not implemented in the
  nominal match layer`.

The tier is data on the entry and the test asserts it **in both directions**: a
`checked` entry must pass the match layer, and a `structural` entry must *fail*
it and must carry a non‑empty reason. A layer growing a rule for `fix` therefore
turns a green test red, forcing the tier to be re‑declared rather than letting a
stale deferral outlive its cause.

**Rejected: holes for the undischargeable parts.** §2.6 confines a term
containing holes to the draft region (§5.4), where it "can never be the target of
a binding". A corpus of draft‑region definitions is not a corpus. The seed set is
hole‑free; what is deferred is *checking*, not *content*.

**Refinements and measures** follow §3.2's rule directly: every obligation gets
an entry, even when that entry is `assumption`. Tranche 1 generates only
`exhaustive-match` obligations (A3, discharged by the typechecker per §6.2) —
verified, since every fixture's match is checked exhaustive by the match layer.

### R7 — The corpus is `prototype/corpus/`, and its manifest is a meta‑object table

**Separate directory, not `examples/`.** `examples/` holds five hand‑authored
fixtures illustrating spec sections, and `test_roundtrip` pins their count at
exactly five; the corpus is an open, growing set with different provenance and a
different reason to exist. Mixing them would make that count meaningless and
would blur "illustrates a spec rule" with "supplies a prior".

**The manifest is `prototype/corpus_registry.py`** — corpus data declarations
with reproducible nominal keys, plus one entry per definition. An entry carries
`fixture`, `name_path`, `spec`, `source`, pinned `identity`, `tier`, `deferred`.
That is §5.2's meta object `[1, def-hash, name-path, spec-text, prov]` minus
provenance, which is the point: **the (spec‑text, canonical‑surface) pair a §8.4
few‑shot prompt needs is the meta object**, so no second format is invented.
`few_shot_pairs()` returns exactly that, in manifest order.

**Nominal keys** derive as `SHA-256("loom:v0.1:corpus:" || name)` — reproducible
like the §5.1.1 prelude rule, under a distinct prefix that cannot collide with a
builtin. The test asserts the disjointness rather than assuming it.

**Manifest order is dependency order**, and the test enforces the strong form:
no entry names a hash that is not already in the store. Tranche 1 uses no `ref`
at all, so the property holds vacuously and stays checkable when tranche 2
introduces `ref`.

### R8 — Hand‑transpiled first; a tool only after tranche 2

The seed set is ~24 definitions of three to five nodes each. A transpiler would
have to parse Unison, run its typechecker, monomorphize, desugar `cases`,
allocate de Bruijn indices, and synthesize measures — and every one of those
steps is a design decision this plan is making *by making it once, by hand*.
Hand transpilation is also what found R3 and R5; a tool written first would have
encoded the wrong assumptions and hidden them.

The tool becomes worthwhile at tranche 3, where the per‑definition cost stops
falling and volume starts mattering. What the seed set produces for it is a
regression corpus with pinned identities: a transpiler is correct exactly when it
reproduces these bytes.

## The first tranche

Layer 0 and layer 1 are not definitions; they precede everything.

**Layer 0 — data declarations** (§5.1.1; must be registered before any
definition naming them). Pinned hashes in `corpus_registry.HASHES`.

| # | Declaration | Unison source |
|---|---|---|
| D1 | `Maybe a = Nothing \| Just a` | `Optional a = None \| Some a` |
| D2 | `Either a b = Left a \| Right b` | `Either a b = Left a \| Right b` |
| D3 | `Pair a b = Pair a b` | the `(a, b)` tuple, un‑nested |
| D4 | `List a = Nil \| Cons a (List a)` | builtin `[a]`, re‑expressed (R2) |

**Layer 1 — assumed base** (R5; §11 externs, A0 assumption evidence). Five
entries, listed in R5's table. Not yet built: §11's `extern` has no object
encoding in the spec (§4.3's seven kinds do not include one), which is recorded
as residue.

**Layer 2 — tranche 1, 24 definitions.** Non‑recursive, `ref`‑free,
arithmetic‑free, branch‑free; all reach tier `checked`. Ordered so every
declaration a definition names precedes it. `★` marks the four built here.

| # | Definition | Type (at `I64`) | Unison source |
|---|---|---|---|
| 1 ★ | `maybe/isNothing` | `Maybe I64 -> Bool` | `Optional.isNone` |
| 2 | `maybe/isJust` | `Maybe I64 -> Bool` | `Optional.isSome` |
| 3 ★ | `maybe/getOrElse` | `I64 -> Maybe I64 -> I64` | `Optional.getOrElse` |
| 4 ★ | `maybe/map` | `(I64 -> I64) -> Maybe I64 -> Maybe I64` | `Optional.map` |
| 5 | `maybe/flatMap` | `(I64 -> Maybe I64) -> Maybe I64 -> Maybe I64` | `Optional.flatMap` |
| 6 | `maybe/orElse` | `Maybe I64 -> Maybe I64 -> Maybe I64` | `Optional.orElse` |
| 7 | `maybe/fold` | `I64 -> (I64 -> I64) -> Maybe I64 -> I64` | `Optional.fold` |
| 8 | `maybe/toList` | `Maybe I64 -> List I64` | `Optional.toList` |
| 9 | `either/isLeft` | `Either I64 I64 -> Bool` | `Either.isLeft` |
| 10 | `either/isRight` | `Either I64 I64 -> Bool` | `Either.isRight` |
| 11 | `either/mapRight` | `(I64 -> I64) -> Either I64 I64 -> Either I64 I64` | `Either.mapRight` |
| 12 | `either/mapLeft` | `(I64 -> I64) -> Either I64 I64 -> Either I64 I64` | `Either.mapLeft` |
| 13 | `either/fold` | `(I64 -> I64) -> (I64 -> I64) -> Either I64 I64 -> I64` | `Either.fold` |
| 14 | `either/swap` | `Either I64 I64 -> Either I64 I64` | `Either.swap` |
| 15 | `either/toMaybe` | `Either I64 I64 -> Maybe I64` | `Either.toOptional` |
| 16 | `pair/fst` | `Pair I64 I64 -> I64` | `at1` |
| 17 | `pair/snd` | `Pair I64 I64 -> I64` | `at2` |
| 18 | `pair/swap` | `Pair I64 I64 -> Pair I64 I64` | `Tuple.swap` |
| 19 | `pair/curry` | `(Pair I64 I64 -> I64) -> I64 -> I64 -> I64` | `curry` |
| 20 | `pair/uncurry` | `(I64 -> I64 -> I64) -> Pair I64 I64 -> I64` | `uncurry` |
| 21 | `list/singleton` | `I64 -> List I64` | `List.singleton` |
| 22 | `list/cons` | `I64 -> List I64 -> List I64` | `List.cons` |
| 23 | `list/isEmpty` | `List I64 -> Bool` | `List.isEmpty` |
| 24 ★ | `list/uncons` | `List I64 -> Maybe (Pair I64 (List I64))` | `List.uncons` |

**Tranche 2 (specified, not built)** — recursive, tier `structural` until the
match layer types `fix` and `ref`; measure `(ref #List.size)` throughout, no
`div`: `list/size` (assumed, layer 1), `list/append`, `list/reverse`,
`list/map`, `list/foldLeft`, `list/foldRight`, `list/concat`, `list/flatMap`.

**Tranche 3** — the effectful slice: Unison ability code against §2.4's eight
builtins, closed rows only, exercising `perform`, `handle`, and `cap`. This is
where Unison's advantage over every other candidate is actually spent.

**Tranche 4** — refinement‑carrying definitions from F\*, transpiled type‑first,
non‑dependent arrows only. The first tranche to generate `ensures` obligations
and therefore the first to exercise §3.2.1 end to end.

## Work

- [x] Choose the corpus and record the rejected alternatives with reasons (R1).
- [x] Enumerate the mapping losses (R2).
- [x] Establish, by construction rather than assertion, that polymorphic
  definitions, `Bool` branching, and typed recursion are unavailable (R3–R5).
- [x] Add `prototype/corpus_registry.py`: four data declarations with
  reproducible nominal keys, a registry over the §2.4 prelude, the manifest, and
  `few_shot_pairs()`.
- [x] Hand‑transpile four definitions into `prototype/corpus/*.loom.sexpr` with
  pinned identities.
- [x] Add `prototype/test_corpus.py`: declaration, canonicity/identity, tier,
  purity, few‑shot, and dependency‑order tests, plus three negative tests pinning
  the R3–R5 limits.
- [x] Wire `test_corpus` into `task prototype:test`.
- [x] Amend §13 open problem 1 to point at this plan. No other SPEC.md edit.
- [x] Add rows to `docs/plans/README.md` and `prototype/README.md`.
- [ ] Tranches 2–4 (specified above; not built by this plan).

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

Note: `task todo:lint` resolves `$HOME/python-tui-lib/scripts/todo-lint.py`, but
`task` itself resolves the Taskfile relative to the repository root, which from a
nested `.claude/worktrees/…` checkout is the worktree. The recorded run below
invokes the same linter by absolute path against this worktree's `TODO.md`; from
the main checkout the `task` form is equivalent.

## Completion criteria

- A primary corpus is chosen with the rejected alternatives and their reasons on
  the record, and the mapping losses are enumerated rather than implied.
- The first tranche is a concrete, ordered list in which no definition precedes a
  declaration it names.
- Every claim the tranche ordering rests on — no polymorphic definitions, no
  `Bool` elimination, no typed recursion yet — is asserted by a test, not by
  prose.
- Four definitions exist as canonical fixtures whose identities are pinned and
  whose declared validation tier is enforced in both directions.
- The storage shape is a §5.2 meta‑object table, and a §8.4 few‑shot prompt reads
  (spec‑text, canonical‑surface) pairs off it with no second format.
- §13 open problem 1 points at this plan; nothing else in SPEC.md moves.

## Residue and escalations

1. **No term‑level type abstraction (R3).** §2.3's rank‑1 `forall` is
   uninhabitable by any `lam`. Either §2 gains a `tylam`/`tyapp` pair — mask
   complexity paid forever — or §2.3.1 threads a definition type's `forall`
   depth into its term, or Loom is honestly monomorphic at the definition level
   and `forall` exists only for holes. **This is a language‑design call, not a
   corpus call.**
2. **No elimination form for `Bool` (R5).** There is no conditional. Whether to
   add one, make `Bool` nominal, or leave booleans as a proposition‑only type
   consumed by SMT is likewise a §2 decision.
3. **§11 `extern` has no object encoding.** §4.3 lists seven object kinds and
   none is an extern, so the R5 assumed base cannot yet be stored. Tranche 2
   needs this.
4. **Unison base licensing is unconfirmed** (R1). Blocking for scale, not for
   the seed set.

## Recorded verification

Run on 2026‑08‑13.

**Result: PASS**

1. `task prototype:test`

    ```text
    test_a_polymorphic_definition_is_unwritable (test_corpus.ExpressivenessLimitTest.test_a_polymorphic_definition_is_unwritable) ... ok
    test_bool_has_no_elimination_form (test_corpus.ExpressivenessLimitTest.test_bool_has_no_elimination_form) ... ok
    test_recursion_and_stored_references_stop_at_the_structural_tier (test_corpus.ExpressivenessLimitTest.test_recursion_and_stored_references_stop_at_the_structural_tier) ... ok

    ----------------------------------------------------------------------
    Ran 100 tests in 0.059s

    OK
    ```

    PASS (tail shown; 100 of 100 tests OK — 87 pre‑existing plus 13 new. The
    87‑test baseline was confirmed by running the same command with
    `test_corpus` omitted.)

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `task todo:lint` — run as
   `python3 ~/python-tui-lib/scripts/todo-lint.py TODO.md` (see the note above)

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
