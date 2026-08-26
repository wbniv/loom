# Plan — Hole-directed decomposition: commit the type, then fill the holes

**Date:** 2026-08-25
**Status:** Design complete, pre-registered, **no GPU run launched, no harness code changed.**
§1's diagnostic is landed as a runnable script and its raw output is pasted below;
§4's arms and tests are fixed before any run. Awaiting dispatch of deliverables 1–7,
then the single runlist instance in §5.
**TODO entry:** `[decomposition]`
**Parent:** [the next-lever plan](2026-08-24-next-lever.md) §2.2 (the sketch),
§4 + [Amendment A1](2026-08-24-next-lever.md#amendment-a1--addr-typed-leaves-the-holm-family-2026-08-25-pre-data)
(the pre-registration standard this plan has to meet), and
[the address-book report](../results/2026-08-25-address-book-report.md)'s §6 row 2 verdict:
*"The model can now reach the right definitions but cannot assemble them.
Addressing is solved as a mechanism … and composition is the residual."*
**Companion instrument:** `[mask-spine-refs]` — every hole is a checking-mode
position, which is where the spine-aware mask is strongest. §4.2 is designed to
run **with or without** it landing first.

**Visible surface:** none. Prompt construction, a runner protocol, config files
and experiment scripts only; per house rule, no mockup bundle.

---

## 1. What is known now, and the two facts §2.2 did not have

§2.2 sketched decomposition in five lines and named one design problem: *"whoever
writes the sub-goals is doing part of the composition, so unless the decomposition
is derived mechanically from the goal type the experiment measures the decomposer."*
That framing had a false premise — it assumed the sub-goals must come from
**outside** the model. They do not. And two measurements taken for this plan change
what the lever is aimed at.

Everything in §1 is reproduced by
[`prototype/experiment/decomposition_probe.py`](../../prototype/experiment/decomposition_probe.py)
(Deliverable 1, landed with this plan), run as `python3 -m experiment.decomposition_probe`
from `prototype/`. CPU only, no network, no model. Output pasted verbatim below.

### 1.1 The residual is a *conjunction*, and its two halves are each already reached

The mechanical floor is `accepted ∧ type-exact`. Over the three address-book arms:

```
### Acceptance and type-exactness are each common; their conjunction is not

addr-none   draws= 320  accepted=  8  type-exact= 57  FLOOR(both)=  0
addr-full   draws= 320  accepted=  4  type-exact= 60  FLOOR(both)=  1
addr-typed  draws= 320  accepted=  9  type-exact= 71  FLOOR(both)=  0
```

At the cell level (a cell is one task × one seed; 40 per arm) the gap is starker:

```
addr-full   funnel-accepted              cells  4/40 ( 10.0%)   draws   4/320
addr-full   type-exact                   cells 15/40 ( 37.5%)   draws  60/320
addr-full   PRIMARY composed-definition  cells  1/40 (  2.5%)   draws   1/320
addr-full   route-complete refs          cells  6/40 ( 15.0%)   draws  10/320
```

**In 37.5 % of cells the model writes the exactly-right declared type at some
point, and in 10 % it writes a definition the whole checker accepts — and in
2.5 % of cells it does both in the same draw.** The two halves are nearly
disjoint events, and the floor is their intersection. That is the residual, stated
as a quantity rather than as a mood.

This matters because it says what a lever has to do. It does not have to teach the
model a new fact — §1.2 of the parent plan settled that the compositions exist and
the addresses now reach the prompt. It has to let the model **hold one half fixed
while it works on the other.** Whole-term generation cannot: every draw re-rolls
the type and the term together, and a 320-draw arm gets 60 type-exact draws and
4 accepted ones and almost never the same draw twice.

Note also what the declared type costs to guess. It reaches the prompt for **2 of
8 tasks**, and only by accident — because that type happens to occur inside some
example definition's own surface:

```
### The declared type is in the prompt for 2 of 8 tasks

heldout/list/concatLength        type= 179ch  none=no   full=no   typed=no
heldout/list/mapLength           type= 115ch  none=no   full=no   typed=no
heldout/list/reverseThen         type= 255ch  none=YES  full=YES  typed=YES
heldout/maybe/mapOrElse          type= 127ch  none=no   full=no   typed=no
heldout/list/headOrElse          type= 103ch  none=no   full=no   typed=no
heldout/list/sum                 type=  91ch  none=YES  full=YES  typed=YES
heldout/sample/stampedBytes      type= 392ch  none=no   full=no   typed=no
heldout/nat/selectNonNegative    type= 384ch  none=no   full=no   typed=no

declared type reachable from the prompt: 2 of 8 tasks
```

`selectNonNegative`'s declared type is 384 characters of refinement predicate;
`stampedBytes`'s is 392 characters of capability types and a bytewise-sorted
two-ability row. The model reaches those anyway, in 37–55 % of cells. That is not
the bottleneck — **retaining** them across the draw that has to get the term right
is.

### 1.2 A hole-bearing draft is already a first-class, checkable object

SPEC §2.6: *"A term containing holes typechecks — the hole inhabits its goal type
by fiat — but is confined to the draft region of the store."* The prototype
implements it. The **eta-skeleton** of a task — every lambda the declared type
calls for, and one hole at the body goal — passes all four funnel layers for all
eight tasks, including the effectful one whose innermost arrow carries a
two-ability row:

```
### The eta-skeleton checks — and meets today's floor, which is the defect

heldout/list/concatLength        chars= 371  funnel=accepted  floor_today=True  floor_with_hole_free_clause=False
heldout/list/mapLength           chars= 243  funnel=accepted  floor_today=True  floor_with_hole_free_clause=False
heldout/list/reverseThen         chars= 523  funnel=accepted  floor_today=True  floor_with_hole_free_clause=False
heldout/maybe/mapOrElse          chars= 265  funnel=accepted  floor_today=True  floor_with_hole_free_clause=False
heldout/list/headOrElse          chars= 219  funnel=accepted  floor_today=True  floor_with_hole_free_clause=False
heldout/list/sum                 chars= 197  funnel=accepted  floor_today=True  floor_with_hole_free_clause=False
heldout/sample/stampedBytes      chars= 662  funnel=accepted  floor_today=True  floor_with_hole_free_clause=False
heldout/nat/selectNonNegative    chars= 779  funnel=accepted  floor_today=True  floor_with_hole_free_clause=False
```

That column reading `floor_today=True` is a **harness defect this plan must fix
before it can run**, and it is exactly the class of defect Amendment A1 was filed
over. `score_semantic`'s held-out rule is `checked+type-exact`; a definition that
is *nothing but a hole* is checked, and its type is exact by construction, so
today it scores as a mechanical-floor success. SPEC §5.4 says the opposite in one
line: a definition containing a hole lives in `draft/` and *can never be the target
of a binding*. The floor rule does not say so yet.

The archive shows the defect has never fired, and shows it is one type-guess away
from firing:

```
### Holes the model has already emitted, over every run directory on record

draws scanned                         10921
draws whose source contains a hole       62
…of those, meeting today's floor          0

funnel-accepted hole-bearing draws (the floor fix is one type-guess away from firing):
  heldout-powered-generated heldout/maybe/mapOrElse: (def (forall I64) (hole I64 ()))
```

**The model already emits holes unprompted, 62 times in 10,921 draws, and under
the type mask** (phase‑b, `addr-none` and the powered held-out runs are all
`gbnf+typemask`). So the treatment needs no grammar change, no mask change and no
new vocabulary: the ability is present and unused. What is absent is a protocol
that does anything with a hole once it is written.

### 1.3 The protocol can express every gold answer, and the nested case works end to end

The check Amendment A1 wished it had run before pre-registering `addr-typed`. Every
gold term splits into (eta-skeleton, body) and splices back byte-identically:

```
### Every gold term splits into (skeleton, body) and splices back exactly

heldout/list/concatLength        lams=2  gold= 537ch  skel= 371ch  body= 179ch  identical=True  funnel=accepted  floor=True
heldout/list/mapLength           lams=2  gold= 409ch  skel= 243ch  body= 179ch  identical=True  funnel=accepted  floor=True
heldout/list/reverseThen         lams=2  gold= 613ch  skel= 523ch  body= 179ch  identical=True  funnel=accepted  floor=True
heldout/maybe/mapOrElse          lams=3  gold= 445ch  skel= 265ch  body= 193ch  identical=True  funnel=accepted  floor=True
heldout/list/headOrElse          lams=2  gold= 594ch  skel= 219ch  body= 388ch  identical=True  funnel=accepted  floor=True
heldout/list/sum                 lams=1  gold= 367ch  skel= 197ch  body= 183ch  identical=True  funnel=accepted  floor=True
heldout/sample/stampedBytes      lams=3  gold= 831ch  skel= 662ch  body= 264ch  identical=True  funnel=accepted  floor=True
heldout/nat/selectNonNegative    lams=3  gold= 844ch  skel= 779ch  body= 193ch  identical=True  funnel=accepted  floor=True
```

The eta-skeleton case is the trivial one — its single hole's sub-task is the
original task again. The case that carries the mechanism is a hole **inside** the
body, where the sub-task is genuinely smaller:

```
### The nested case: draft -> closed sub-task -> fill -> splice -> re-check

draft            funnel=accepted  declared-type-preserved=True
closed sub-task  255ch, derived from the declared type alone
fill definition  funnel=accepted  chars=520
assembled        identical-to-gold=True  funnel=accepted  floor=True
```

Read in order, that is the whole protocol: a draft with a nested hole typechecks
and **keeps its declared type**; the hole's sub-task type is computed from the
draft's own declared type and the binders it sits under, with no term knowledge;
the fill definition typechecks standalone; the splice reproduces the gold term
exactly and meets the floor.

---

## 2. The mechanism, concretely

### 2.1 What a hole is, in this harness

A hole is a `(hole GOALTYPE ())` node in a draft the **model itself wrote**. It is
a checking-mode position by construction: the goal type is written into the node,
so no synthesis is needed to know what belongs there, and no oracle is needed to
decide where the uncertainty is. SPEC §8.3's authoring cycle is *draft → check →
narrow*, and its first clause is *"the agent emits a draft, placing `hole` nodes
wherever its uncertainty is high"*.

This is the answer to §2.2's design problem. **The model proposes the skeleton;
the checker types the sub-goals; the harness never chooses where to cut.** There
is no decomposition oracle to measure, because there is no decomposition oracle.

### 2.2 How a task is decomposed — one round, in six steps

A **round** produces exactly one candidate definition. A cell runs rounds until
its token purse is spent.

1. **Skeleton draw.** The ordinary held-out prompt (preamble, examples, address
   book, ask) plus one added block licensing holes, and the ordinary `(def TYPE
   TERM)` ask. The model writes the type and whatever structure it is sure of, and
   a `(hole T ())` wherever it is not. Same condition, same grammar, same mask, same
   per-draw cap as the control.
2. **Check.** `run_funnel` on the draft, unchanged. Only a **funnel-accepted**
   draft is filled — a blind test (funnel outcome and nothing else). A rejected
   draft ends the round and is scored as the round's candidate.
3. **Enumerate obligations.** `hole_obligations(source, resolver)` walks the
   draft's IR and returns, per hole, its path, its written goal type, and the
   types of the binders it sits under. A hole is **fillable** iff its binder
   context is derivable without synthesis — `lam` and `fix` carry their
   annotations, so those are; a hole under a `match` or `handle` binder is **not
   fillable in v1** and is recorded as such (its binder types need the scrutinee's
   synthesized type, which is the `[mask-spine-refs]` machinery, not this plan's).
4. **Close the sub-task.** The first fillable hole's context is folded back into a
   closed type: `Γ ⊢ T` becomes `(fn τ₀ R₀ (fn τ₁ R₁ … T))`, with the effect rows
   read off the draft's **own declared type**, peeled in parallel with the top-level
   lambdas. This is a pure function of two type surfaces.
5. **Fill draw.** An ordinary `(def CLOSED_TYPE TERM)` ask — same prompt shape,
   plus the draft the model just wrote and the hole being filled — so the existing
   masker, grammar, funnel and per-draw cap all apply **unchanged**. The fill's term
   must open with |Γ| lambdas in the same order; the harness peels them and splices
   the innermost body at the hole path. De Bruijn indices line up by construction,
   because the peeled lambdas bind the same context in the same order.
6. **Re-check, or roll back.** `run_funnel` on the assembled definition. If it
   still passes, the assembled definition replaces the draft and step 3 runs again
   (up to `fills_per_round_max`). If it does not, the splice is **rolled back**,
   the funnel error is fed back as the narrowing note for one retry of the same
   hole, and after `fill_attempts_per_hole` the round ends. The draft is therefore
   monotone: holes only ever disappear.

The round's candidate is the final draft. It is scored by the same
`run_funnel` + `score_semantic` every other arm's candidates are scored by.

**The closure in step 4 is a heuristic; the re-check in step 6 is the authority.**
Closing over the whole top-level context can be more permissive than the hole's
exact position (a fill may perform effects the position does not allow). That
cannot produce a false success, because nothing is scored until the *assembled*
definition has been through all four funnel layers.

### 2.3 How it composes with the address book

The address book is now standard — the address-book report's own verdict is that
*"the store's addresses belong in every future held-out prompt"*. Every arm here
runs `address_book: "full"`: the pre-registered, primary-significant, **route-complete**
book. `addr-typed` won its exploratory comparison but is route-incomplete for 5 of
8 tasks, so using it would handicap the battery; its lesson is being cashed at
decode time by `[mask-spine-refs]`, which is where it belongs.

One property falls out for free. `typed_address_rows(resolver, type_surface)` is
blind by signature, and a fill draw has a *type surface* of its own — the hole's
closed type. So a future `typed` variant of this experiment filters each fill's book
by that hole's goal with no new machinery and no new leak surface. Not an arm here;
noted because the design already admits it.

### 2.4 How it composes with `[mask-spine-refs]`, with or without it landing

Every hole is a checking-mode position with a written goal type — precisely where
the spine-aware `ref` filter is strongest, and precisely where today's
`GoalTypePruner` abstains. The two are complements: decomposition **creates**
checking positions, the spine-aware mask **exploits** them.

The experiment does not depend on it. `Config.pruners` is pinned explicitly in
every arm config to the address-book run's set — `["goal-type", "de-bruijn",
"ref-hash"]` — verified pinned in all three `addr-*` configs today. That pinning is
load-bearing here and not a formality: if `[mask-spine-refs]` lands a new pruner and
adds it to `PRUNER_NAMES`, **every config that omits `pruners` silently changes**,
including a control. With the set pinned, the arms are immune.

If `[mask-spine-refs]` has landed *and* passed its own soundness gate before
launch, one **exploratory** fourth arm is added: `holes+spine`, byte-identical to
`holes` except that the new pruner name is appended to its pinned list. It is
exploratory by pre-registration, it is never in the primary's family, and its
absence changes nothing else in this plan. If it has not landed, the three-arm
design runs exactly as written.

### 2.5 The design I rejected

**Prefix-primed term fills.** Instead of asking for a closed `(def …)`, prime the
masker with the draft's byte prefix up to the hole and let the model decode the
subterm alone. It is strictly better on tokens — the closed sub-task repeats the
declared type, which is 384–392 characters for the two worst tasks — and it is
what §8.3 means at token granularity. Rejected for v1 on two grounds: it needs a
new masker entry point (start mid-term at a goal with a binder depth), and
`masker.py` is under concurrent edit by `[mask-spine-refs]`. Filed as the natural
follow-up, owned by whoever holds the masker.

The cost of the rejection is charged honestly rather than hidden: matching the
arms on the **completion-token purse** (§4.3) makes the holes arm pay for its own
repeated type surfaces out of the same budget the control spends on whole terms.

**A mechanically-derived skeleton** (harness emits the eta-skeleton, model fills
the one hole) was rejected earlier and for a different reason: its single hole's
sub-task *is* the original task, so it decomposes nothing, and it hands the model
the declared type the control has to guess — a confound, not a lever.

---

## 3. What the manipulation is, concretely

Two blocks of text and one runner loop. Nothing else about the prompt, the store,
the grammar, the mask, the address book or the scoring changes.

**The protocol block** (skeleton draws, `holes` arm only), inserted where the
address block goes — after the examples, before any narrowing, so the
prefix-identity property `build_prompt` already documents survives:

```
Where a subterm is not yet clear, write `(hole GOALTYPE ())` in its place and
commit to the structure around it. Each hole is handed back to you on its own,
with its goal type, to fill in. Do not make the whole body a hole.
```

**The fill block** (fill draws, `holes` arm only), which carries the draft the
model just wrote, the hole being filled, and its goal — all three of them things
the model itself produced or the checker derived from them.

The last sentence of the protocol block is enforced, not merely asked for: a draft
whose body under the top-level lambdas is a **bare hole** gets no fills, is scored
as the round's candidate, and ends the round. That rule reads the draft alone.

---

## 4. Pre-registration

Everything in §4 is fixed before any GPU run. No mid-run peeking; no post-hoc test
selection. §4.9 restates the standard and Amendment A1's precedent for amending it.

### 4.1 Hypotheses

**H1 (mechanism, primary).** Hole-directed decomposition raises the share of
held-out *cells* that produce a **composed definition** — a hole-free definition
that passes all four funnel layers at exactly the task's declared type — above the
concurrent whole-term control, at a matched completion-token budget.

**H2 (attribution).** The rise is not explained by iteration-with-feedback alone:
`holes` exceeds `redraft`, which is `holes` minus the hole protocol and nothing
else.

**H3 (outcome, secondary).** Decomposition produces the project's first non-zero
hand-scored held-out semantic success.

H1 is primary because it is mechanical, needs no rubric, and is the quantity the
mechanism directly manipulates: the protocol's entire claim is that a type-exact
skeleton can be *carried across draws* while the term is worked on, and a composed
definition is the observable that claim predicts. H3 is what the project cares
about, is strictly downstream, and is reported with exact intervals rather than
leaned on — the same reading the address-book plan fixed in advance and then had
to honour.

### 4.2 Arms

Three arms, `held_out` regime only, condition `gbnf+typemask`, **curated-only
resolver** (26 definitions / 47 objects), `address_book: "full"`, `pruners`
pinned to `["goal-type", "de-bruijn", "ref-hash"]`. Store size, address book,
mask, grammar, temperature and seeds are held fixed across arms; the arms differ
only in the generation protocol.

| Arm | `generation_protocol` | Feedback on rejection | Holes | Prompt vs `whole` |
|---|---|---|---|---|
| `whole` | `whole` | none | no | identical, byte for byte |
| `redraft` | `redraft` | §8.3 narrowing note | no | identical on draw 0 of every cell |
| `holes` | `holes` | §8.3 narrowing note | yes | + the §3 protocol block |

`whole` is the honest baseline — today's protocol, re-run under §4.3's budget
rule, because the budget change makes the address-book arm's numbers
non-comparable.

`redraft` is not padding. Without it, a positive `holes` result is confounded
exactly the way §2.3 of the parent plan says worked derivations are confounded:
the holes arm hands the model **its own previous draft**, and the control's draws
are independent. `redraft` isolates that. **`holes` is `redraft` plus the hole
protocol**, so `holes − redraft` is the hole protocol and nothing else, and
`holes − whole` is the lever as §6 row 2 licensed it.

The three protocols degenerate into one another cleanly, which makes the
comparison conservative in the right direction: if the model declines to write a
hole, `holes` **is** `redraft`; if no draw is ever rejected, `redraft` **is**
`whole`.

### 4.3 Harness changes — applied identically to all arms

1. **The floor rule learns SPEC §5.4.** `score_semantic` returns `success=False`
   for a definition whose term contains a `hole` node, whatever its type. §1.2
   shows this is a no-op on every draw the project has recorded (0 of 62
   hole-bearing draws met the floor) and one type-guess away from firing. Landed
   with a fail-then-pass regression proof against the eight eta-skeletons, which
   today all score `success=True`. **Without this, every arm's primary is trivially
   gameable and the `holes` arm gameable by design.**
2. **The cell purse binds, not the draw count.** `token_budget_per_task: 4608`
   (6 × 768), `max_tokens_per_draw: 768` unchanged, `max_draws_per_task: 64`.
   The address-book run set `max_draws_per_task: 8` and every cell ran exactly 8
   draws at a mean 406 completion tokens — so the **draw cap** bound and each cell
   left ~2,900 tokens of its purse unspent. Under a protocol whose draws are
   deliberately shorter, a draw cap is not a shared budget at all. R2's rule is a
   token purse; this makes it one. The `whole` arm is thereby a *stronger* control
   than `addr-full` was (≈ 11 draws per cell for the same tokens, not 8).
3. `n_ctx: 32768` unchanged. The fill prompt adds the draft (≈ 400–850 characters)
   to an 18.8k‑token prompt; `context_required` is asserted for every arm,
   including a worst-case fill prompt, in the §4.8 gate.
4. `stop_on_semantic_success: false` unchanged — the mechanical floor produces
   false positives (the address-book run's `lam xs. (List.size xs)` is the latest),
   so a cell must never stop on one.
5. `seeds: [1,2,3,4,5,6,7,8]`, 8 tasks → **64 cells per arm**.
6. Protocol constants, fixed here: `fills_per_round_max: 6`,
   `fill_attempts_per_hole: 2`, bare-hole bodies unfilled (§3).

Truncation stays a genuine rejection. The truncated-draw fraction is reported per
arm; above 10 % the run is reported as censored and the primary is flagged, exactly
as §4.3 of the parent plan ruled.

### 4.4 Prerequisite: the protocol must be able to express every gold answer

The check Amendment A1 was written because nobody ran. Before any GPU spend, for
each of the eight tasks: take the gold term, blank one subterm to a hole, and drive
the full protocol — obligations, closure, fill definition, splice, re-check — and
require the result to be byte-identical to the gold term and to meet the floor.
§1.3 shows the eight eta-skeleton round-trips and the nested case for
`reverseThen`; Deliverable 5 runs the nested round-trip for **all eight** and
pastes the table.

**A task whose gold answer the protocol cannot express is dropped from the battery
before the run, with its reason recorded.** If the battery drops below six tasks,
this plan pauses and the battery is redesigned before any GPU spend — the parent
plan's §4.4 stopping condition, inherited unchanged.

Gold terms remain harness fixtures. They are never shown to the model, and the gate
asserts no gold surface appears in any built prompt — **skeleton or fill**.

### 4.5 Primary metric and test

**Metric — composed-definition rate, per cell.** A cell (one task × one seed)
counts as a success iff at least one of its **candidates** is a definition that

  (a) passes all four funnel layers, **and**
  (b) contains no `hole` node, **and**
  (c) whose canonical type surface equals the task's `expected_type_surface`.

A candidate is one complete `(def …)` offered for scoring: in `whole` and
`redraft`, every draw; in `holes`, every round's final draft. Mechanical, computed
from `records.jsonl` by regex and the harness's own funnel, no rubric, no human.

**The unit is the cell, and the budget is the shared purse.** That is R2's rule and
the only protocol-neutral choice available: a draw-level rate would compare a
whole-term draw against a fill draw, and a candidate-level rate would reward
whichever protocol makes fewer, better candidates. Both are reported as secondaries
with that caveat attached; neither is the primary.

**Baseline.** 1/40 cells in `addr-full`, 0/40 in `addr-none` and `addr-typed`
(§1.1). Planning rate **A0 = 0.03**, slightly above the measured 0.025 because
§4.3.2 gives the control ~11 draws per cell rather than 8. The *test* is against
the concurrent `whole` arm, so a harness change cannot masquerade as an effect.

**Test.** Fisher exact, **one-sided** (`holes` > `whole`), on the 2 × 2 cell-level
table, **α = 0.05, a single comparison, no Holm.** Amendment A1's lesson applied
in advance: α is not spent on comparisons that are exploratory or known to be
handicapped.

**Attribution gate (H2), pre-registered, distinct role.** Fisher exact, one-sided,
`holes` > `redraft`, α = 0.05. It cannot license the lever on its own — only the
primary can — and its only pre-committed function is to *remove* the attribution
when it fails. §6 fixes that reading in advance.

**Clustering sensitivity.** Cells within a task are not independent. Alongside the
primary, a **task-stratified permutation test** (10,000 permutations of arm labels
within task, statistic = difference in composed-definition rate) is reported. It is
a sensitivity analysis, not a second primary: a disagreement between it and the
Fisher primary is reported as an unresolved clustering caveat, and is **not**
resolved by picking the friendlier one.

### 4.6 Secondary metrics, recorded and reported, not leaned on

- **Hand-scored semantic success (R3 rubric)** per arm, with Clopper–Pearson 95 %
  intervals, over every candidate meeting the mechanical floor. Pre-registered
  comparison: `holes` vs `whole`, one-sided Fisher, α = 0.05 — **≥ 5 successes vs
  0 clears** (p = 0.02882 at n = 64; see §4.7). The rubric is the one the
  diversity-harvest, sweep and address-book reports used, unchanged.
- **Route-reference rate**, per cell and per draw, computed through the audit's own
  code path. Baselines: 1 / 6 / 8 of 40 cells and 1 / 10 / 21 of 320 draws for
  `addr-none` / `addr-full` / `addr-typed`. Addressing is solved; this is now a
  continuity measure, and a fall in it under decomposition would be a finding.
- **Funnel-acceptance rate** and **type-exactness rate**, per cell and per draw —
  the two halves of §1.1's conjunction, reported separately so the mechanism claim
  is checkable rather than asserted.
- **Protocol telemetry** (`holes` arm): drafts per cell, accepted-draft rate, holes
  per accepted draft, fillable fraction and the reason for each unfillable hole,
  fills attempted / spliced / rolled back with their funnel errors, final hole count
  per candidate, rounds per cell.
- **Overhead accounting:** total prompt tokens per arm and completion tokens per
  candidate. The purse is matched on completion tokens, which charges the holes arm
  nothing for its extra prompt evaluations — a real cost, so it is reported rather
  than netted away.
- Truncated-draw fraction, illegal-`ref` rate, funnel distribution, acc/1k tok.
  **acc/1k tok is not comparable across arms** — a protocol that emits partial terms
  changes what "accepted" counts — and is reported for continuity only.

### 4.7 Power — stated honestly, before any run

Simulated Fisher exact, one-sided, 6,000 replicates per cell, α = 0.05.
`decomposition_probe --section power`:

```
### Simulated power, one-sided Fisher at alpha=0.05, per-cell primary

n= 48/arm A0=0.02  A1=0.10:0.302  A1=0.15:0.639  A1=0.20:0.865  A1=0.25:0.958  A1=0.30:0.991
n= 48/arm A0=0.03  A1=0.10:0.217  A1=0.15:0.535  A1=0.20:0.796  A1=0.25:0.927  A1=0.30:0.983
n= 48/arm A0=0.05  A1=0.10:0.128  A1=0.15:0.356  A1=0.20:0.640  A1=0.25:0.830  A1=0.30:0.935
n= 64/arm A0=0.02  A1=0.10:0.446  A1=0.15:0.815  A1=0.20:0.959  A1=0.25:0.993  A1=0.30:0.999
n= 64/arm A0=0.03  A1=0.10:0.342  A1=0.15:0.719  A1=0.20:0.914  A1=0.25:0.981  A1=0.30:0.997
n= 64/arm A0=0.05  A1=0.10:0.181  A1=0.15:0.511  A1=0.20:0.801  A1=0.25:0.933  A1=0.30:0.984
n= 80/arm A0=0.02  A1=0.10:0.601  A1=0.15:0.899  A1=0.20:0.982  A1=0.25:0.998  A1=0.30:1.000
n= 80/arm A0=0.03  A1=0.10:0.450  A1=0.15:0.804  A1=0.20:0.956  A1=0.25:0.995  A1=0.30:1.000
n= 80/arm A0=0.05  A1=0.10:0.233  A1=0.15:0.592  A1=0.20:0.861  A1=0.25:0.974  A1=0.30:0.995

SECONDARY — k hand-scored successes in `holes` vs 0 in `whole`, one-sided Fisher:

n= 48  k=1:p=0.50000  k=2:p=0.24737  k=3:p=0.12105  k=4:p=0.05857  k=5:p=0.02801  k=6:p=0.01324
n= 64  k=1:p=0.50000  k=2:p=0.24803  k=3:p=0.12205  k=4:p=0.05956  k=5:p=0.02882  k=6:p=0.01382
n= 80  k=1:p=0.50000  k=2:p=0.24843  k=3:p=0.12264  k=4:p=0.06015  k=5:p=0.02930  k=6:p=0.01418
```

**Reading, fixed in advance.** At the chosen **n = 64 cells per arm** and the
planning A0 = 0.03, the primary has **91 % power against a 20 % composed-definition
rate, 72 % against 15 %, and 34 % against 10 %.** The design point is A1 ≈ 0.15–0.20,
and here is why that is the honest expectation rather than a hopeful one: the holes
arm's per-cell success factors as *(a cell produces a type-exact skeleton) × (its
holes all get well-typed fills)*. The first factor is **measured** at 0.375–0.55
(§1.1). The second is exactly what the experiment does not know, and A1 = 0.15
corresponds to it being ≈ 0.35.

A null primary at this power is evidence against a ≥ 20 % effect. **It is not
evidence against a 10 % one, and the report will say so in those words.** The
secondary needs ≥ 5 hand-scored successes to clear its threshold; below that it is
reported as a count with a Clopper–Pearson interval and explicitly **not** as a
significance claim — the exact discipline the address-book report had to apply to
its own zero.

### 4.8 Stub-backend dry-run — the gate on GPU spend, no GPU

Deliverable 5, run and pasted into this plan before any instance launches. Each
check prints an explicit PASS/FAIL and the script exits non-zero on any FAIL.

1. **Arms differ only by their block.** `redraft`'s draw‑0 prompt is byte-identical
   to `whole`'s for all 8 tasks; `holes`'s skeleton prompt with the §3 protocol
   block stripped is byte-identical to `whole`'s.
2. **Blindness, by signature and adversarially.** `hole_obligations(source,
   resolver)`, `closed_subtask_type(declared_type_surface, context)` and the fill
   prompt builder take **no `Task`**, so they cannot read `composes` or
   `expected_surface` even by accident — the pin `typed_address_rows` got, applied
   to every new surface. Adversarial test: two `Task`s with identical `spec` and
   `expected_type_surface` and *different* `composes` and `expected_surface`
   produce byte-identical prompts at every stage of every round.
3. **Expressibility (§4.4).** All eight tasks round-trip through the full protocol
   from a gold-derived nested draft to a byte-identical gold assembly meeting the
   floor. Any task that fails is dropped, with its reason, before launch.
4. **Floor-rule regression.** A hole-bearing definition never meets the floor:
   fail-then-pass against the eight eta-skeletons, which score `success=True` today.
5. **Context.** `context_required` ≤ `n_ctx − max_tokens_per_draw` for every arm,
   including the worst-case fill prompt built from the largest gold-derived draft.
6. **No gold leak.** No gold surface appears in any built prompt — skeleton or fill
   — for any arm and any task.
7. **Stub-backend end to end.** A scripted stub drives one cell of each arm and the
   check asserts: every draw's completion tokens are charged to the purse; the
   full-cap-or-no-draw rule holds; no cell exceeds `token_budget_per_task`; the
   accepted-draft path, the rejected-draft path, the bare-hole path, the
   unfillable-hole path and the assembly-rollback path are each exercised; and
   round/candidate bookkeeping is consistent with the records.
8. **Baseline reproduction.** Route-reference extraction over the recorded
   `addr-*` arms reproduces 1 / 10 / 21 draws exactly, through the audit's code
   path — so every arm number in the report shares a code path with the address-book
   report's.

### 4.9 No peeking, no test-shopping

The arms, the metric, the unit, the tests, the α and the thresholds are fixed above
before any of the runs launch. Whatever the three composed-definition numbers turn
out to be, §4.5's test is the one reported as primary, and §6's row is the one that
fires. Amendment A1 is the precedent for changing any of it: an amendment is filed
in this file, **before any draw exists**, with the defect stated and the repair
measured — never quietly, and never after data.

---

## 5. Cost

One `g2-standard-4` (1 × NVIDIA L4 24 GB, 4 vCPU), us‑central1, in **runlist mode**
— all three arms on one instance, self-deleting at the end, the shape landed in
`beed5a8` and exercised by the address-book run. Spot first, on-demand on stockout.

Sizing, from the address-book run's own measured throughput
(`decomposition_probe --section cells`): 23.4 completion tokens/s for the
18.8k‑token `addr-full` prompt. A fill draw amortizes the same prompt evaluation
over fewer completion tokens, so the `holes` arm is budgeted at ≈ 16.7 tok/s — a
1.4× wall-clock penalty for the same purse, which is the honest cost of the
rejected prefix-priming design (§2.5).

| Arm | Cells | Purse | Completion tokens | Rate | Hours |
|---|---|---|---|---|---|
| `whole` | 64 | 4,608 | 294,912 | 23.4 tok/s | 3.5 h |
| `redraft` | 64 | 4,608 | 294,912 | 23.4 tok/s | 3.5 h |
| `holes` | 64 | 4,608 | 294,912 | 16.7 tok/s | 4.9 h |
| boot, model load, build-cache restore | | | | | 0.3 h |
| **total** | | | | | **≈ 12.2 h** |

| Line | Unit price | Quantity | Cost |
|---|---|---|---|
| `g2-standard-4` Spot, us‑central1 | $0.25/h | 12.2 h | **$3.05** |
| `g2-standard-4` on-demand (stockout fallback) | $0.85/h | 12.2 h | **$10.37** |
| Artifacts bucket, standard storage | $0.020/GB‑month | ≈ 5 GB × 13 h | < $0.01 |
| Egress fetching results to the checkout | $0.12/GB | ≈ 0.15 GB | $0.02 |
| **Total, Spot** | | | **≈ $3.07** |
| **Total, on-demand worst case** | | | **≈ $10.39** |

**The on-demand figure is above this project's ~$6 per-experiment scale, so the
reduction is pre-committed rather than decided at run time:** if spot is
unavailable and the run must go on-demand, drop to **6 seeds / 48 cells per arm**
(9.2 h, ≈ $7.80 on-demand), and report the §4.7 power table's n = 48 row as the
one in force. Nothing else changes. The alternative — three parallel single-arm
instances, same GPU-hours, ~5 h wall clock — is the fallback if wall clock rather
than money is the binding constraint; it costs the same and cuts per-instance
preemption exposure, at the price of three runlist invocations instead of one.

Preemption is not hypothetical: the address-book run lost 31 minutes to a spot
preemption 31 minutes into its second arm and was rescued by per-arm incremental
upload plus a committed resume runlist. That shape is reused here, and this run is
2.4× longer, so it is *more* exposed, not less. **This plan's launch is gated on
`[runlist-partial-fetch]` landing** — the address-book run's arm results had to be
fetched by hand twice, and a 12‑hour three-arm run is not the place to repeat that.

**Teardown is part of the run, not after it.** The runlist instance self-deletes;
the bucket and the Terraform root are destroyed by the run's own task, and the
results are copied into `prototype/runs/` *before* the bucket goes. Any IAM binding
teardown needing a human is surfaced as an explicit ask.

---

## 6. What each outcome licenses

| Outcome | What it licenses next |
|---|---|
| Primary significant **and** `holes` > `redraft` (attribution gate passes) | Decomposition is the lever. The composition residual has a mechanism that moves it. Promote **prefix-primed term fills** (§2.5) to remove the repeated-type-surface tax, promote `[mask-spine-refs]` into the fill path (every hole is a checking position), and re-open **worked derivations** (parent §2.3) and **external import** (parent §2.1) on a battery that is finally live end to end. |
| Primary significant, attribution gate fails (`holes` ≈ `redraft`) | **Iteration with feedback is the lever, not decomposition.** A real and cheap finding: §8.3 narrowing at definition granularity was already implemented for `gbnf+rejection` and had never been run under the type mask. Report it as such, retire hole-directed decomposition as a *distinct* lever, and take `redraft` as the new standard protocol for every held-out arm. |
| Primary null, `holes` arm's accepted-draft rate ≥ 20 % | The protocol ran and did not help: the model can draft structure but cannot fill it at a smaller goal either. Composition is not a **decomposition** problem at this model scale. Put a model-scale arm (a larger or unquantized model on the same battery) on the table as an honest question, as parent §6 row 3 already contemplated. |
| Primary null, `holes` arm's accepted-draft rate < 20 % | The protocol was **starved**, not refuted: too few drafts survived the funnel to be filled. This is a harness/battery finding, not a result about composition. Report as inconclusive, and re-run with the fill gate relaxed from `accepted` to `parses` before drawing any conclusion about the lever. |
| `redraft` alone beats `whole`, `holes` does not | Feedback helps and holes hurt — most likely because the purse buys fewer complete candidates. Report the candidate-count accounting (§4.6) as the explanation and treat the per-candidate secondary as the diagnostic. |
| ≥ 5 hand-scored semantic successes in any arm | **The project's first held-out semantic success.** Whatever the primary says, this is the headline; hand-score every mechanical-floor candidate in every arm, and re-examine the type-collision recycling failure mode the powered held-out report documented before claiming any of them. |
| `holes+spine` (exploratory, only if `[mask-spine-refs]` landed) beats `holes` | The mask exploits checking positions the protocol creates — the two are complements, and the pair becomes the standard held-out configuration. |

---

## 7. Consequences for the results already on record

- The **address-book report**'s primary and its §6 row 2 verdict stand unchanged.
  Its mechanical-floor count (1 draw, hand-scored to zero) is unaffected by §4.3.1's
  floor fix: that draw was hole-free.
- **No archived number changes.** §4.3.1's hole-free clause is a no-op over all
  10,921 recorded draws (§1.2), and §4.3.2's budget change affects only future runs.
  The address-book arms remain the baseline this plan powers against, and their
  `max_draws_per_task: 8` is why they are quoted at 8 draws per cell rather than 11.
- The **corpus-size sweep** and **diversity-harvest** held-out halves are already
  carrying their correction addenda from the parent plan's §7 and are untouched here.

---

## 8. Deliverables

Suggested scope and tier only — the orchestrator ranks and files these; this plan
does not edit `TODO.md`.

1. **`prototype/experiment/decomposition_probe.py`** — §1's diagnostic as a runnable
   script: the conjunction gap, the declared-type reachability table, the
   eta-skeleton floor defect, the gold round-trips, the nested case, per-cell
   baselines and throughput, the hole census, the power tables. **Landed with this
   plan**; nothing to dispatch. *(T2 if it needs extending.)*
2. **Floor rule learns SPEC §5.4** — `score_semantic` refuses a hole-bearing
   definition, with a fail-then-pass regression proof against the eight
   eta-skeletons. Touches `prototype/experiment/evaluate.py` and
   `prototype/test_experiment.py` only. **This blocks everything else** — until it
   lands, the holes arm's primary is gameable by construction. *(T2, small and
   sharply specified.)*
3. **Hole machinery in `prompts.py`** — `hole_obligations`, `closed_subtask_type`,
   the §3 protocol block and the fill prompt, behind `generation_protocol` — plus
   the adversarial blindness tests of §4.8 check 2. *(T3: the spec is settled here,
   the leak discipline is the care required.)* **Landed.** Four implementation
   choices §2.2 left open, recorded here because a reader of §2.2 will hit them
   and none of them changes anything §4 pre-registers:

    * `closed_subtask_type(declared_type_surface, obligation)` rather than
      §4.8's spelling `(…, context)`. A `HoleObligation` **is** the hole's
      context — its binder type surfaces, its goal, and a path — so passing it
      whole keeps a caller from pairing a goal with the wrong binders. Still two
      type surfaces and no term; §4.8 check 2 is pinned against the signature.
    * **A binder deeper than the declared type has arrows** (an inner `lam`, or
      a `let`/`fix` binder) has no effect row to read — the term IR records
      none, only the declared type does. It closes at the empty row `()`: the
      restrictive choice, which can make a sub-task unsolvable but can never
      license a fill that performs an effect the position forbids. §2.2's
      re-check remains the authority.
    * **`let` binders are fillable**, on §2.2 step 3's stated rule (*"derivable
      without synthesis"*) rather than on its `lam`/`fix` list: a `let` writes
      its binding type into the term exactly as a `lam` does. So does a
      **zero-binder `match` arm**, which adds nothing to Γ at all — the
      unfillable case is an unknown *binder*, not a `match` node overhead.
    * **The splice is a pure function in `prompts.py`** (`splice_fill`), not
      inside deliverable 4's loop. That is what makes step 5's de Bruijn claim
      structural: it peels exactly the `|Γ|` lambdas whose annotations *are* the
      hole's context, refuses any fill whose prefix is not that, and relies on
      the fill being a closed definition to have no index left over to
      misalign. The runner drives the rounds and the rollback; it does not
      re-derive the alignment.
4. **Protocol-aware cell loop in `runner.py`** — the round/fill/splice/rollback loop
   of §2.2, `generation_protocol: "whole" | "redraft" | "holes"` defaulting to
   `whole` so every existing config is byte-identical, narrowing wired for
   `redraft`/`holes` under `gbnf+typemask`, and the per-draw `role` / round /
   assembly telemetry §4.6 reports. *(T3, or T4 if the budget accounting proves
   subtler than §4.3.2 reads.)*
5. **`prototype/experiment/decomposition_stub_check.py`** — §4.8's eight checks on
   CPU, output pasted back into this plan. **This is the gate on GPU spend.**
   *(T3 — check 3, the expressibility round-trip, is the one Amendment A1 taught
   us not to skip.)*
6. **Three configs (`decomp_whole`, `decomp_redraft`, `decomp_holes`) plus
   `decomposition-runlist.json`** — byte-copies of `addr-full.config.json` with only
   the §4.2/§4.3 fields changed, `pruners` pinned, all validating. *(T2.)*
7. **`docs/results/2026-08-2X-decomposition-report.md`** — arms, the §4.5 primary
   with its attribution gate and clustering sensitivity, hand-scored secondaries
   with intervals, the protocol telemetry, the §6 licensing row that actually fired,
   cost and teardown evidence. *(T3.)*

Deliverables 2–6 are CPU-only and gate the GPU spend. **Nothing launches until 5's
output is in this file** and `[runlist-partial-fetch]` has landed (§5).

---

## 9. What would change this plan

- **The protocol cannot express three or more tasks' gold answers** (§4.4). The
  battery, not the corpus, is then the problem; the stopping condition fires and the
  battery is redesigned before any GPU spend.
- **The stub check shows the arms differ by more than their block.** Fix the prompt
  builder; do not launch a run whose arms are not byte-comparable.
- **`[mask-spine-refs]` lands a pruner and some config is found not pinning
  `pruners`.** Then a control has silently drifted; re-verify every arm config
  before launch (§2.4).
- **Someone produces a held-out semantic success on the existing whole-term
  harness.** Then §1.1's conjunction framing has a counterexample and must be
  re-derived before this plan is worth running.
- **The `whole` arm under §4.3.2's purse produces composed definitions at ≫ 3 %.**
  Then the address-book run's draw cap, not composition, was the residual, and the
  primary's baseline assumption is wrong — report it, and re-power before reading
  anything into the treatment.
