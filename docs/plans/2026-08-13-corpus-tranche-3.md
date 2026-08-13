# Plan — Bootstrap corpus tranche 3: the effectful slice

**Date:** 2026‑08‑13
**Status:** Implemented and verified locally
**Depends on:** [Bootstrap corpus for prior starvation](2026-08-13-bootstrap-corpus.md)
(R1 source and licence, R2 mapping losses — row polymorphism dropped, R6 tiers,
R7 manifest conventions, R8 the tool threshold),
[Bootstrap corpus tranche 2](2026-08-13-corpus-tranche-2.md) (integration-record
format), [Builtin ability prelude](2026-08-13-builtin-ability-prelude.md),
`SPEC.md` §2.4 (the eight builtin abilities and their operation signatures),
§3.1.2 (effect‑directed typing), §5.1.3 (externs, capability honesty)

## Objective

Build tranche 3 of the bootstrap corpus: ability code against §2.4's builtins,
closed rows only, exercising `perform`, `handle`, and `cap` at tier `checked`.
This is the tranche the R1 corpus choice was made for — Unison is the one
candidate whose *term* language has algebraic abilities, so it is the one
candidate from which effectful definitions transpile without inventing a
semantics — and it is the first tranche whose fixtures are not pure.

It is also where R8 promised an answer on the transpiler tool, since "the
per‑definition cost stops falling here". That verdict is recorded below, with
its reasoning, rather than deferred again.

No visible surface (fixtures and normative text only), so this plan carries no
mockups.

## Rules

### R1 — Selection is by *shape*, not volume

The bootstrap plan named the shape of this tranche and left the list open. Seven
definitions were chosen so that each one is the smallest definition exhibiting a
distinct piece of §2.4/§3.1.2, and no two are the same piece at different sizes.
The alternative — twenty `perform` wrappers over the remaining six abilities —
would add bytes to the corpus and nothing to the priors, because §2.4's `fsRead`,
`fsWrite`, `net`, `spawn`, and `ffi` all have the *same* Loom shape (`Text`
and/or `Bytes` in, `Bytes` envelope out); their interesting content is the
envelope protocol, which is runtime ABI, not term structure. `div` declares no
operations and can never be `perform`ed or `handle`d at all (§3.1.2). So the
tranche is over `clock` and `rand`, the two abilities whose signatures actually
differ from one another (nullary and unary operations, `I64` and `Bytes`
results), and R2's arithmetic loss is what stops the others from producing a
definition that does anything with the bytes it receives.

| # | Definition | Type | Shape it exercises |
|---|---|---|---|
| 1 | `clock/now` | `cap clock -{clock}> I64` | The minimum: `perform` of a nullary operation, with the ability in the definition's own row and the capability as its parameter |
| 2 | `rand/bytes` | `cap rand -> I64 -{rand}> Bytes` | `perform` with an argument, and a **latent** effect — the outer arrow is pure, the row sits on the inner one (§3.1.2's "latent effects are expressible only by checking against an annotated `fn` row") |
| 3 | `clock/stamped` | `cap clock -> (Unit -{clock}> I64) -{clock}> Pair I64 I64` | An *effectful function argument*, applied under the ambient allowance — `_require_allowed` at an application site rather than at a `perform` |
| 4 | `rand/withStub` | `cap rand -> Bytes` | A `handle` that discharges its ability locally and leaves the definition **pure to callers**: the row is empty, the `cap` is not |
| 5 | `clock/nowPair` | `cap clock -{clock}> Pair I64 I64` | A capability threaded as an ordinary value into a `ref` whose own type carries a row (§3.1.5's last paragraph, "no special case for references") |
| 6 | `sample/nowAndBytes` | `cap clock -> cap rand -{rand,clock}> Pair I64 Bytes` | A two‑ability closed row, sorted bytewise, with two capabilities in scope at once |
| 7 | `rand/resample` | `cap rand -> Pair Bytes Bytes` | A `handle` whose operation clause invokes the continuation **twice** and destructures both results — the multi‑shot shape that makes algebraic effects more than sugar for a monad |

All seven reach tier `checked` on the first attempt; no fixture in this tranche
needed a `structural` deferral, and neither `typecheck.py`, `declarations.py`,
`scope.py`, `transcode.py`, `loom.gbnf`, nor `SPEC.md` was touched.

Manifest order is dependency order (R7): `clock/now` precedes `clock/nowPair`,
which is the tranche's only `ref` and its only cross‑definition dependency.

### R2 — Every capability is a parameter, because it cannot be anything else

§2.4: a capability is "introduced only by the runtime at a program entry point,
never constructible in the language". There is no term node that produces a
`cap a` — so in a closed definition, the *only* way one reaches the environment
is as a lambda parameter whose annotation is `(cap …)`. Every fixture here
therefore opens with `(lam (cap …) …)`, and that is not a stylistic convention
but the single available shape.

Two consequences worth having in the corpus as priors:

- **`handle` discharges the row, not the capability.** `rand/withStub` has an
  empty row and still takes `cap rand`, because the `perform` inside the handled
  computation needs a capability in scope regardless of who answers it. A model
  that learns "no row ⟹ no `cap` parameter" would be learning something false.
- **Passing a capability is an ordinary application.** `clock/nowPair` applies
  `(ref #clock/now)` to `(var 0)` twice. The cap is a value of a nominal,
  unforgeable *type*; nothing in the term language distinguishes handing it over
  from handing over an `I64`. The unforgeability lives in the introduction rule,
  not in the use sites.

### R3 — Closed rows only, and the tranche is what makes that visible

The bootstrap plan's R2 dropped Unison's row polymorphism: `{g}`‑style
ability‑polymorphic signatures have no checkable form here, because
`typecheck._closed_row` refuses a row containing a `tyvar` and §3.1.2 states
outright that "the v0.1 prototype's type‑directed layer requires closed rows".
Until this tranche that was a claim about definitions nobody had written. Now it
is a property of seven fixtures, asserted directly by
`test_corpus.CorpusFixtureTest.test_every_fixture_row_is_closed_and_names_only_builtin_abilities`:
every row item is a hash (never a row variable), every ability named by a row or
a `cap` is one of §2.4's eight builtins, and every row is sorted bytewise.

The cost, stated the way R3 of the bootstrap plan states its own: a model
trained on this corpus sees no ability‑polymorphic function, because no valid
v0.1 Loom program contains one. Unison's `List.map : (a ->{g} b) -> [a] ->{g}
[b]` — the single most characteristic signature in its base library — is
**not transpilable**, at all, in any instantiation that keeps its generality.
`clock/stamped` is the honest residue of that: a wrapper taking an effectful
function argument, with the callee's row written out concretely as `{clock}`
rather than quantified.

### R4 — Provenance is honest about the `{IO}` mismatch

R1 of the bootstrap plan requires the `Unison (unisonweb/unison, MIT) …` form,
and `test_corpus.CorpusFixtureTest.test_external_fixture_provenance_names_repository_and_license`
enforces it. But Unison's ability structure does not line up with §2.4's, and
saying so is part of the attribution:

- Unison's `{IO}` is **one broad ability** covering clock, randomness,
  filesystem, network, and process. §2.4 has eight narrow ones. A Unison
  `'{IO} Int` clock read maps onto `clock` specifically — a *narrowing*, which
  loses nothing about the term but is a different type, so the manifest says
  "narrowed from the broad `{IO}` ability" instead of implying a 1:1 port.
- Unison has **no capability values**. The `cap clock` parameter is added by us;
  no Unison original has a counterpart for it, and the manifest says so.
- Two entries have **no single Unison original at all**. `rand/bytes` (no base
  definition returns a requested count of bytes) and `rand/resample` (base ships
  no multi‑shot handler) record that the *shape* rather than a named function is
  what was transpiled. Inventing a plausible‑looking `Random.bytes` citation
  would have been the failure mode the corpus exists to avoid — a fake original
  is exactly §13 open problem 2 in miniature, in the artifact whose whole job is
  to be trusted as exemplary.
- `rand/withStub` drops generator state, because carrying an LCG or splitmix
  seed forward needs arithmetic Loom v0.1 does not have (bootstrap R2). The
  handler answers with a constant. That is a weakened definition, and the
  manifest entry says which axis it was weakened on.

### R5 — The purity test, reworked rather than weakened

`test_corpus.CorpusFixtureTest.test_every_fixture_is_pure_and_capability_free`
iterated the whole manifest and asserted that no arrow carried a row and no type
was a `cap`. Tranche 3 violates it by construction, and there were three ways to
respond. Deleting it loses a real invariant over tranches 1–2. Restricting it to
a hard‑coded list of tranche‑1/2 names makes the manifest and the test drift
apart the moment either changes. What was done instead:

`CorpusEntry` gains an `effect_free: bool = True` field — the entry's declared
position on §2.4, exactly as `tier` is its declared position on R6 — and the one
test becomes two, **enforced in both directions like the tier test**:

- `test_every_effect_free_fixture_is_pure_and_capability_free` — for entries
  declaring `effect_free=True`, the original assertion, unchanged in strength.
- `test_every_effectful_fixture_carries_the_effects_it_declares` — for entries
  declaring `effect_free=False`, the type must actually name an ability, in a
  row or a `cap` or both.

That second test is what keeps the rework from being a weakening: the flag is a
claim that fails if it is wrong in *either* direction, so it can never be
flipped to silence a failure. Flipping `effect_free` on a pure fixture turns the
suite red just as surely as smuggling an effect into a pure one does. A third
test (R3 above) then constrains what the effectful entries may say.

**Why scanning the definition *type* is sufficient, and not a weaker check than
scanning the term.** Both the old test and the new ones read the definition's
type, never its term — and for effects that is exact rather than approximate.
§2.4 makes a capability unforgeable and no term node constructs one, so the only
route by which a `cap a` enters a closed definition's environment is its type;
§3.1.2 makes `perform` require a capability in scope. A definition whose type
carries no row and no `cap` therefore cannot perform anything, whatever its term
contains and however many `handle`s are nested inside it. The type is the whole
audit surface, which is precisely what §2.4 claims when it calls the row "the
static audit surface" and the capability "the dynamic blast‑radius bound". The
argument is written into the helper's docstring so the next reader does not have
to re‑derive it.

### R6 — Grammar surfaces

`corpus/` is not globbed by `validate_gbnf.py` the way `examples/` is, so
surfaces are copied into `EXTRA_VALID` deliberately. Two were added, for the two
grammar productions this tranche is the first to stress:

- `sample/nowAndBytes` — an effect row containing **two** hashes. Every prior
  valid case had a row of zero or one, so the row production's separator had
  never been exercised at all.
- `rand/resample` — a `handle` whose operation clause body is a nested `match`
  over the continuation's result rather than a bare `var`. The existing handler
  case (`(handle … ((0 (var 0))) (var 0))`) is minimal by design.

## Work

- [x] Select seven definitions by shape, recording what each one exercises (R1).
- [x] Build `clock/now` (`perform`, nullary, own row) and pin its identity.
- [x] Build `rand/bytes` (`perform` with an argument; latent row on the inner
  arrow) and pin its identity.
- [x] Build `clock/stamped` (effectful function argument applied under the
  ambient allowance) and pin its identity.
- [x] Build `rand/withStub` (`handle` discharging into a pure result) and pin
  its identity.
- [x] Build `clock/nowPair` (capability threaded into a `ref` with a nonempty
  row) and pin its identity.
- [x] Build `sample/nowAndBytes` (two‑ability closed row) and pin its identity.
- [x] Build `rand/resample` (multi‑shot continuation) and pin its identity.
- [x] Add the seven manifest entries in dependency order, with `effect_free=False`
  and honest `{IO}`‑mismatch provenance (R4).
- [x] Rework the purity test into a two‑direction pair keyed on `effect_free`,
  plus a closed‑row/builtin‑ability test (R3, R5).
- [x] Add two new surfaces to `validate_gbnf.py`'s `EXTRA_VALID` (R6).
- [x] Update `prototype/README.md`'s corpus narrative paragraph.
- [x] Add this plan's row to `docs/plans/README.md`.
- [x] Re-declare tranche 3 as built in the bootstrap-corpus plan
  (strike-through style) and amend its R8 with the verdict below.
- [x] Answer R8: transpiler tool, or not (below).

## R8 — The tool threshold, answered: **still no transpiler**

The bootstrap plan predicted the tool "becomes worthwhile at tranche 3, where
the per‑definition cost stops falling and volume starts mattering". Half of that
came true and the half that did is not the half that matters. The per‑definition
cost did stop falling — tranche 3's definitions took longer each than tranche
2's, not less. But the cost is not *transcription*, and a transpiler only
automates transcription. Every expensive minute in this tranche went to
decisions no parser can make: which of §2.4's eight narrow abilities a Unison
`{IO}` signature becomes; where the capability parameter goes in the curried
spine and whether the row belongs on the outer or the inner arrow (the whole
substance of `rand/bytes` versus `clock/now`); what a handler should answer with
once R2's arithmetic loss has removed the generator state it was supposed to
thread; and whether a Unison original exists at all or the honest record is "the
shape, not a named function". A tool fed Unison source would have to be *told*
each of those answers per definition, which is the work, and the tool would then
add a second place for them to be wrong. The regression value R8 anticipated —
pinned identities as a transpiler's correctness oracle — is real and is now 20
definitions strong; it costs nothing to keep accruing and does not require the
tool to exist yet.

**Revised trigger, stated as a test rather than a tranche number:** build the
tool when a tranche is (a) ≥ 30 definitions, (b) drawn from a *single* Unison
namespace whose signatures share one shape, and (c) mapping onto Loom with no
per‑definition decision left open — i.e. when the ability narrowing, the
capability placement, and the measure are all determined by a rule already
written down. Tranche 4 (F\* refinement carriers, transpiled type‑first) will
not meet (c) either: choosing which refinement survives the drop to
non‑dependent arrows is the same class of judgment. The honest expectation is
that the corpus reaches useful size by hand and the tool arrives, if ever, to
*scale a solved mapping*, not to discover one.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
LOOM_GBNF_VALIDATOR=/path/to/test-gbnf-validator task grammar:test
task todo:lint
git diff --check
```

## Completion criteria

- Seven new fixtures exist in `prototype/corpus/`, each canonical,
  identity‑pinned, and at tier `checked`.
- Each exercises a distinct §2.4/§3.1.2 shape, recorded in R1's table.
- Rows are closed, sorted, and name only §2.4 builtins — asserted by a test.
- The purity test is reworked into a two‑direction claim keyed on manifest data,
  not deleted and not scoped to a hand‑maintained name list.
- Provenance records the `{IO}` narrowing, the added capability parameter, and
  the two entries with no single Unison original, rather than implying 1:1 ports.
- R8 is answered with a verdict and a revised trigger.
- `typecheck.py`, `declarations.py`, `scope.py`, `transcode.py`, `loom.gbnf`,
  and `SPEC.md` are untouched.

## Recorded verification

Run on 2026‑08‑13.

**Result: PASS**

1. `task prototype:test`

    ```text
    ----------------------------------------------------------------------
    Ran 241 tests in 0.447s

    OK
    ```

    PASS (241 of 241 OK — 223 outside `test_corpus` plus 18 in it. `test_corpus`
    held 16 before this plan: one purity test was replaced by three, and the
    seven new manifest entries are covered automatically by the
    manifest‑iterating tests in `CorpusFixtureTest` with no further test
    changes.)

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `LOOM_GBNF_VALIDATOR=/tmp/loom-llama-cpp/build/bin/test-gbnf-validator task grammar:test`

    ```text
    GBNF PASS: 19 valid cases accepted; 16 invalid cases rejected
    ```

    PASS (17 valid cases before this plan; 19 after — the `sample/nowAndBytes`
    and `rand/resample` surfaces added to `EXTRA_VALID`).

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

### Pinned identities added

| Name path | Fixture | Tier | Identity (SHA-256) |
|---|---|---|---|
| `corpus/clock/now` | `clock_now.loom.sexpr` | `checked` | `1d76cfea633059e7e0523b04b2a25f1bd7681266c2ad9c107fe63ed94b96aabe` |
| `corpus/rand/bytes` | `rand_bytes.loom.sexpr` | `checked` | `f403bb626c6758e31f4d6ffe69b657f210dd40ad1b972249788bfb4c6e4d6181` |
| `corpus/clock/stamped` | `clock_stamped.loom.sexpr` | `checked` | `1b34eac0d6170e358d640f3361f66fdf85f10605542755b4560bc527f6dc5fce` |
| `corpus/rand/withStub` | `rand_with_stub.loom.sexpr` | `checked` | `f0f11f45a58849efad599470a01968334bd98c8c9338bd463ceba51933204dc7` |
| `corpus/clock/nowPair` | `clock_now_pair.loom.sexpr` | `checked` | `39256387522338400d5fd3181c328882c76356d9c50ca40465be88b219c0d642` |
| `corpus/sample/nowAndBytes` | `sample_now_and_bytes.loom.sexpr` | `checked` | `8671c61e79cc536d0a4e00ecad9c838547797cdfa5342a876e00285159717105` |
| `corpus/rand/resample` | `rand_resample.loom.sexpr` | `checked` | `13926e2d25d36dc321a19973fc64a11255751426863707efa2ed164e9a794db0` |

The bootstrap corpus now carries **20 fixtures** total (6 from tranche 1's built
subset, 7 from tranche 2, and these 7), all at tier `checked`.

### Findings, recorded rather than fixed

1. **No `structural`‑tier record was needed.** Every shape selected typechecked
   as written. That is a result about §3.1.2's implementation, not luck: the
   effect layer is complete for closed rows, including multi‑shot continuations
   and capability values passed through references.
2. **The multi‑shot handler types fine and means nothing operationally yet.**
   `rand/resample` invokes its continuation twice and the checker is content,
   because §3.1.2 types a continuation as an ordinary function value. Loom has
   no evaluator in this prototype, so nothing pins what invoking it twice *does*
   — that is future work, not a defect here, and it is recorded because a corpus
   fixture teaching a shape the runtime has not yet defined is worth flagging.
3. **`div` is unreachable from this tranche.** §3.1.2 forbids handling an
   ability with no operations and there is no `perform` for it, so `div` can
   appear in a row and nowhere else. No fixture carries it; tranches 1–3 remain
   `div`‑free as the bootstrap plan's R4 claims positively.
