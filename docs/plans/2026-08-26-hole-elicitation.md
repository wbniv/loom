# Plan — Hole elicitation: make the model write a hole before relaxing the gate

**Date:** 2026‑08‑26
**Status:** Design complete, pre-registered. **No GPU run launched, no harness code changed.**
§1's evidence is landed as a runnable script and its raw output is pasted below;
§4's arms and tests are fixed before any run.
**TODO entry:** `[decomp-elicit-rerun]`
**Parent:** [2026‑08‑25 hole-decomposition](2026-08-25-hole-decomposition.md) — its
§2 mechanism, §3 manipulation and §8 landed contract are inherited unchanged except
where §2 below says otherwise.
**Responds to:** [the decomposition report](../results/2026-08-26-decomposition-report.md),
whose §6 **row 4** fired: *primary null, accepted-draft rate < 20 % — the protocol was
starved, not refuted … re-run with the fill gate relaxed from `accepted` to `parses`
before drawing any conclusion about the lever.*

**Visible surface:** none. Prompt construction, a runner gate, config files and
experiment scripts only; per house rule, no mockup bundle.

**Evidence script:** [`experiment.hole_elicitation_probe`](../../prototype/experiment/hole_elicitation_probe.py)
— six sections, no GPU, run against the banked records and the real masker. Every
number in §1 is one of its lines.

---

## 0. Why this is a new pre-registration and not an amendment

The 2026‑08‑25 plan's §4.9 fixes the standard in one sentence:

> Amendment A1 is the precedent for changing any of it: an amendment is filed in
> this file, **before any draw exists**, with the defect stated and the repair
> measured — never quietly, and **never after data**.

Draws exist. All three arms ran to completion and are reported. Every change this
document proposes — the fill gate, the protocol block, the arm set, the baseline
rate, the power table — is a change made *knowing* how the banked run came out. An
amendment appended to that file would be exactly the after-data amendment its own
§4.9 forbids, and it would retroactively blur what was pre-registered before the
first draw from what was decided after the last one.

So: **the 2026‑08‑25 plan is closed as the record of what was pre-registered and
what happened.** This is a new pre-registration, and it inherits that plan by
citation rather than by edit. The one edit it does earn there is a two-line
back-pointer in that file's §6 row 4, filed as deliverable 8 below, saying which
document discharged the row.

This choice costs something and the cost is stated: a reader now needs two files to
see the whole arc. §1.5 below pays that back by listing exactly what the banked run
already answers, so nothing is re-derived and nothing is re-run.

---

## 1. What the banked run actually shows

The report's headline is right — the mechanism never ran. Its *causal chain* is
wrong in two places, and the corrections are what this design is built on.

### 1.1 §3's block did induce holes. It was ~20× too weak, which is a different problem

```
### Hole-bearing draw rate, all three banked arms

whole       1/762  = 0.131%
redraft     2/772  = 0.259%
holes      12/747  = 1.606%

one-sided Fisher, `holes` > `redraft`         p = 0.00528
one-sided Fisher, `holes` > pooled controls   p = 0.00023
```

The report reads this as *"the §3 block as written licenses holes but does not
induce them — 98.4 % of skeletons ignored it."* The concurrent controls say
otherwise: against `redraft`, which is the same arm minus the block and nothing
else, the block **multiplies the hole rate 6.2×, p = 0.005**. It is a working
manipulation of the right sign. What it is not is a manipulation of the right
*size*: 1.6 % of draws is roughly twenty times short of a rate the fill path can
live on.

That reframing matters because it changes what to build. "The block does nothing"
argues for abandoning prose and reaching for enforcement or seeding. "The block
works and is small" argues for making the same lever bigger first, and §1.4 says
exactly how.

### 1.2 The hole is not what fails. The structure the model committed to is

Every one of the twelve hole-bearing skeletons, with the funnel's own error path
resolved back to the node the checker was looking at when it failed:

```
task                          seed  funnel     failing node  verdict
heldout/list/headOrElse          6  references type          the DECLARED TYPE — not the hole
heldout/list/sum                 6  typecheck  tag 0         a committed sibling — not the hole
heldout/maybe/mapOrElse          2  typecheck  tag 1         a committed sibling — not the hole
heldout/maybe/mapOrElse          2  accepted   -             bare hole — §3 ends the round unfilled
heldout/maybe/mapOrElse          3  typecheck  tag 4         a committed sibling — not the hole
heldout/maybe/mapOrElse          4  accepted   -             bare hole — §3 ends the round unfilled
heldout/maybe/mapOrElse          4  typecheck  tag 7         a committed sibling — not the hole
heldout/nat/selectNonNegative    5  typecheck  tag 0         a committed sibling — not the hole
heldout/nat/selectNonNegative    6  typecheck  tag 0         a committed sibling — not the hole
heldout/nat/selectNonNegative    7  typecheck  hole          THE HOLE itself
heldout/sample/stampedBytes      1  typecheck  tag 4         a committed sibling — not the hole
heldout/sample/stampedBytes      7  typecheck  tag 6         a committed sibling — not the hole

   8  a committed sibling, not the hole
   2  accepted (bare hole, §3 ends the round)
   1  declared type, not the hole
   1  the hole itself
```

**Nine of the ten rejects failed away from the hole.** SPEC §2.6 is why: a hole
inhabits its goal type by fiat, so it cannot propagate an error — it can only fail
*at itself*, when its written goal disagrees with the position's expected type
(the one `selectNonNegative` seed 7 case, and that one is a bare hole under zero
lambdas). Everything else that killed these drafts was a sibling subterm the model
chose to commit to: a `let` bound to the wrong thing, a match arm returning the
wrong type, an argument at the wrong index.

The acceptance rates say the same thing from the other side:

```
hole-bearing accepted 2/12 = 16.7%
hole-free    accepted 39/735 = 5.3%
one-sided Fisher, hole-bearing > hole-free acceptance: p = 0.1370
```

Not significant at n = 12 — but the *direction* is the opposite of the report's
chain "the model writes holes rarely → hole-bearing drafts typecheck poorly". They
do not typecheck poorly. They typecheck at three times the rate of everything else
in the arm, which is what SPEC §2.6 predicts, because a hole is the one node that
cannot be wrong.

### 1.3 Row 4's remedy, priced on the banked draws: eight fill draws, zero composed definitions

```
### Funnel outcome, all 747 skeleton draws
  parse         34
  references    74
  scope          1
  typecheck    597
  accepted      41
reached the typecheck layer (parse+references+scope passed): 638/747 = 85.4%

### What each candidate gate admits to a fill, on the banked draws
  accepted (as run)            rounds reaching a fill:  0   cells:  0/64   (+0 rejected-but-bare …)
  well-scoped (the §4.2 gate)  rounds reaching a fill:  8   cells:  8/64   (+1 rejected-but-bare …)
  parses, literally            rounds reaching a fill:  8   cells:  8/64   (+2 rejected-but-bare …)
```

Relaxing the gate would have turned 0 fill draws into 8, in 8 of 64 cells. Now
combine that with §1.2: **all eight of those drafts fail at a sibling the fill does
not touch.** §2.2 step 6 re-checks the *assembly* with `run_funnel`, the sibling
error is still there, and every one of the eight is rolled back for exactly the
reason its draft was rejected.

So row 4's pre-committed remedy, taken alone, buys **mechanism exposure and
telemetry — not composed definitions.** That is worth having (the fill path has
literally never executed against real model output, so its behaviour is entirely
unmeasured) and it is nowhere near sufficient. This plan therefore discharges row 4
in full — §2.1 specifies the gate exactly — and does not pretend the gate is the
lever.

### 1.4 The mask is not the obstacle. The in-context prior is

```
### Admissible term heads at each task's body goal, under the real mask
task                              n  heads
heldout/list/concatLength        10  var ref lit app let match perform handle hole if
heldout/list/mapLength           10  var ref lit app let match perform handle hole if
heldout/list/reverseThen         10  var ref app let con match perform handle hole if
heldout/maybe/mapOrElse          10  var ref lit app let match perform handle hole if
heldout/list/headOrElse          10  var ref lit app let match perform handle hole if
heldout/list/sum                 10  var ref lit app let match perform handle hole if
heldout/sample/stampedBytes      10  var ref app let con match perform handle hole if
heldout/nat/selectNonNegative    10  var ref lit app let match perform handle hole if
```

Driven through the real `Masker` with the arms' pinned pruner set, `(hole ` is
admissible at **every** task's body goal, as one of ten heads. Neither the GBNF nor
the type mask nor `[mask-spine-refs]`'s spine machinery suppresses it (the spine
pruner filters `ref` candidates at an `app` head; it does not touch the head
choice). The parent plan's §1.2 already said the ability was "present and unused";
this is the decode-time confirmation at the exact positions that matter.

What *is* suppressing it:

```
corpus fixtures containing a `(hole ...)` node: 0 of 26
of the four pinned few-shot names (bool/not, maybe/map, list/append, clock/now): 0
```

**The model has never seen a hole written in this surface.** It is named once, in
the preamble's twelve-form grammar list, and described in three lines of prose by
§3's block. Every worked example in every prompt — four definitions, 1,838
characters of them — is a complete term. A 7B writing an alien hash-dense
S-expression surface is doing shape imitation, and there is no shape to imitate.
A 1.6 % emission rate against a 0.26 % unprompted base is what that predicts.

This is the design's single strongest lead, and it is cheap: the repair is bytes in
a prompt.

### 1.5 What the banked run already answers — cited, not re-run

| Fact | Value | How this plan uses it |
|---|---|---|
| `whole` composed-definition cell rate | **3/64 = 0.047** | The new planning baseline **A0 = 0.047**, replacing the 2026‑08‑25 §4.5 planning rate of 0.03. Costs ~11 points of power at every A1 (§4.5). |
| Two hand-scored semantic successes, verified by execution | `redraft` `list/mapLength`; `holes` `list/mapLength` | Existence proofs, already banked. **Not re-litigated and not re-scored.** `decomp_hand_score` is reused unchanged; the ≥ 5-successes threshold (2026‑08‑25 §4.6) carries over verbatim. |
| `redraft` nearly doubled draw-level acceptance (53 vs 28) | primary 3/64 vs 3/64, p = 0.66 | Exploratory when observed, so it stays a **secondary** here. `redraft` is kept in the arm set partly to see whether it replicates — reported, not tested. |
| Throughput and cost model | 3 arms, ≈ 10.7 h, ≈ $2.75 vs $3.07 estimated | The 2026‑08‑25 §5 model was ~12 % conservative. §5 below reuses it unchanged rather than re-deriving it. |
| §4.8 stub gate, all eight checks pass | — | Checks **2, 3, 4, 5, 6, 8** are cited, not re-run: nothing in this design touches the machinery they pin. Checks **1** and **7** are re-run (§4.7), because the block and the gate are exactly what changed. |
| Floor rule learns SPEC §5.4 (hole-free clause) | landed, regression-proven | Unchanged and load-bearing. Without it the `holes` arm's primary is gameable by construction. |
| `closed_subtask_type(declared_type_of(draft), …)` | `runner.py:719` | The closure reads the **draft's own** declared type, never the task's. No leak; this plan preserves it and pins it again in §4.7 check 1b. |

---

## 2. The mechanism changes

Three: a gate, a block, and — only if the pilot says so — a protocol enforcement.
Nothing else about the prompt, the store, the grammar, the mask, the address book,
the funnel or the scoring changes from the 2026‑08‑25 contract.

### 2.1 The fill gate, exactly — row 4's pre-commitment, discharged

Row 4 says `accepted` → `parses`. Taken literally, "parses" means the syntax layer
alone. The mechanically defensible reading is one layer looser than that, and the
two extra layers are excluded for structural reasons, not for convenience:

| Layer | Gate | Why |
|---|---|---|
| **parse** | **blocks** | No IR, so no obligations, no binder walk, no path. Non-negotiable. |
| **references** | **blocks** | `closed_subtask_type` reads the draft's declared type *surface*. A references failure means a hash in that surface is unresolvable — the closed sub-task would carry an unresolvable hash into a fill prompt that can never be accepted. (The one references-rejected hole-bearing draft failed at `definition.type.codomain`: the declared type itself was malformed.) |
| **scope** | **blocks** | A de Bruijn index out of range means the binder context folded into the closed type is not the context the term actually has. `splice_fill`'s alignment claim — "it peels exactly the \|Γ\| lambdas whose annotations *are* the hole's context" (2026‑08‑25 §8 d3) — is void, and the splice would silently mean something else. |
| **typecheck** | **admits** | This is the relaxation. 597 of 747 banked skeletons died here. |

So the gate is: **fill iff the draft reached the typecheck layer** — parse,
references and scope all passed — **and §3's bare-hole rule does not refuse it.**
Name it the **well-scoped gate**; `generation_protocol` config field
`fill_gate: "accepted" | "well-scoped"`, defaulting to `"accepted"` so every
existing config is byte-identical.

Four consequences, each pre-committed here:

1. **§3's bare-hole rule must be evaluated unconditionally.** `runner.py:828` reads
   `bare = funnel.accepted and _is_bare_hole(draft)`, so every rejected draft
   carries `False` whatever its shape. Under the relaxed gate that conjunct is a
   hole in the guard — and the banked data shows it firing: the one draft whose
   error *was* at the hole,
   `(def (fn Bool () (fn (refine I64 …) () (refine I64 …))) (hole Bool ()))`, is a
   bare hole under zero lambdas that a naive relaxation would send to a fill whose
   sub-task is the whole task. Drop the conjunct. This is the eta-degenerate case
   the 2026‑08‑25 §2.5 rejected, arriving through the back door, and §3's rule
   already closes it once it is allowed to run.
2. **Narrowing is unchanged.** Narrowing is a property of the skeleton
   (`runner.py:826`): the draft's own funnel error is still the next round's
   §8.3 note, whether or not a fill happened. A parse-only draft's errors are not
   consumed by the fill path; they go where they always went.
3. **The re-check stays the authority, at all four layers.** §2.2 step 6 is
   untouched. An assembly that still fails is rolled back with the assembly's own
   error as the fill's narrowing note — which, on an ill-typed draft, will usually
   be the draft's original sibling error restated. That is correct behaviour and it
   is also the telemetry that makes §1.3's prediction falsifiable.
4. **Relaxed-gate rounds are capped at one fill draw.** A draft that was *not*
   funnel-accepted gets `fills_per_round_max: 1` and `fill_attempts_per_hole: 1`;
   accepted drafts keep the 2026‑08‑25 §4.3.6 constants (6 and 2). Rationale, with
   the number: §1.2 says ≥ 90 % of relaxed-gate fills are expected to be rolled
   back, so an uncapped relaxed round is a purse leak that starves the accepted
   rounds sharing the same cell budget. One draw per round bounds it.

**A rule considered and rejected:** a *no-identity-fill* guard refusing any fill
whose closed sub-task type equals the draft's declared type. It looked like the
mechanical statement of §2.5's "its sub-task is the original task, so it decomposes
nothing" — and it is wrong. `corpus/bool/not` holed at its `then` branch is a
genuinely nested, structurally committed skeleton whose closed sub-task is
`(fn Bool () Bool)`, the declared type exactly, because the hole sits under the
single top-level lambda. Type identity does not imply task identity. §3's
*structural* bare-hole rule is the right test and covers every case the relaxed
gate newly reaches; the type test would have killed this plan's own best exemplar.

### 2.2 The elicitation candidates

Four blocks, of which **B0** is the banked one and serves as the pilot's reference.

**B0 — `§3-block`.** The 2026‑08‑25 §3 protocol block, verbatim. Banked value:
1.6 % of draws hole-bearing, 1.07 % reaching a fill under the §2.1 gate (8/747).

**B1 — `exemplar`.** B0's three lines, plus a worked hole exemplar and a shape
exemplar, both built out of corpus fixtures the prompt already shows complete.
Direct answer to §1.4. Built and driven end to end on CPU:

```
corpus/bool/not
  draft      chars=  78  funnel=accepted  holes=1 fillable=1
  sub-task   chars=  17  (derived from the draft's own declared type)
  fill       chars=  51  funnel=accepted
  assembled  funnel=accepted  identical-to-fixture=True
corpus/maybe/map
  draft      chars= 524  funnel=accepted  holes=1 fillable=1
  sub-task   chars= 191  (derived from the draft's own declared type)
  fill       chars= 383  funnel=accepted
  assembled  funnel=accepted  identical-to-fixture=True

  held-out gold TERM surfaces appearing in the block: 0 []
  held-out gold TYPE surfaces appearing in the block: 0 []
  hashes in the block not already in the four pinned few-shot definitions: 0
  block size: 847 characters of definition surface, ~565 tokens
```

`corpus/bool/not` is shown **worked** — draft, sub-task, fill — because it is 78
characters, carries no hash at all, and its round-trip is the entire protocol in
three lines, including the fill-draw shape, which has never been elicited from the
model even once. `corpus/maybe/map` is shown as **draft + sub-task only**: its fill
line would add 383 characters of hashes to teach a shape the worked exemplar
already taught. The leak story is unusually tight — **the block introduces zero new
store content**, only a new *form* of content already in every prompt — and §4.7
check 1c pins it mechanically.

Cost: ~565 prompt tokens against an 18.8k-token prompt, a ~3 % prompt increase and
**zero completion tokens**, so the matched purse (2026‑08‑25 §4.3.2) is unaffected.

Named risk, pre-registered as telemetry rather than waved away: the model copies the
exemplar's *goal type* (`(data 0x3ff2… (I64))`) into a held-out draft where it does
not belong. `hole_goal` is already recorded per fill draw; §4.6 adds the
hole-goal-vs-exemplar-goal distribution to the reported telemetry.

**B2 — `hole-required`.** Protocol enforcement, not persuasion. For the first
`hole_required_rounds: 3` rounds of a cell, a draft with no hole (or a bare-hole
body) has a **hole-demand note appended to** — never substituted for — its §8.3
narrowing note:

```
The previous answer had no `(hole GOALTYPE ())` in it. Write the same definition
again, but replace the one subterm you are least sure of with `(hole GOALTYPE ())`,
where GOALTYPE is the type that subterm must have.
```

The draft is still emitted, still funnel-checked, still scored as the round's
candidate — no primary is lost and no diagnostic is discarded. After round 3, note
selection reverts to §8.3 exactly. Precedent: the project already enforces §3's
prose rather than merely asking for it (the bare-hole rule), so this is the same
move applied to the block's first sentence.

**B3 — `checker-holed`, exploratory only.** When a skeleton is rejected at
typecheck, walk from the error path *up* to the nearest ancestor in checking
position whose goal is derivable from the **draft's own** declared type and the
annotations above it (`lam` body, `let` body, `if` branch, `match` arm body, `con`
argument under a known data type), replace that subtree with `(hole GOAL ())`, and
send the repaired draft straight to the fill path. A pure function in `prompts.py`
— `hole_at_error(source, error_path) -> str | None` — returning `None` when no such
ancestor exists, in which case the round falls back to plain §8.3 narrowing.
Sized by `--section blame`:

```
arm       rejected  raw-IR note  expected type
whole          734      271 37%        266 36%
redraft        719      297 41%        286 40%
holes          706      298 42%        291 41%
```

**41 % of the `holes` arm's rejections name an expected type at the failing node**, so
a checker-holed seed has something to write into the hole that often. (The same column
read the other way is §2.4's feedback-legibility defect.)

B3 is **barred from the primary family, by pre-commitment, for a reason that is not
about leakage.** The 2026‑08‑25 §2.1 states the property that makes this experiment
interpretable: *"The model proposes the skeleton; the checker types the sub-goals;
**the harness never chooses where to cut.** There is no decomposition oracle to
measure, because there is no decomposition oracle."* B3 makes the harness choose
where to cut. That is a different lever — checker-localized repair — and calling it
hole-directed decomposition would be a rename, not a result. It runs in the pilot as
a **diagnostic** separating "the model cannot place holes" from "the model cannot
write structure", and §6 says what its winning licenses (an escalation, not an
automatic Stage 1).

> **Notes filed with Deliverable 5 (2026‑08‑26, pre‑pilot — no data drawn under
> this plan).** (1) `typecheck.py:381‑382` rewrites an arm body's own type
> mismatch back onto the arm, erasing `.body` from the path — 385 of the 1,618
> banked check‑10 refusals arrive `arms[i]`‑shaped — so the landed
> `hole_at_error` stops at the `match` node rather than guess between a body
> mismatch, a binder‑count error, and a duplicate constructor. The arm‑body cut
> site named above is therefore live only for paths that reach deeper than the
> arm. Conservative direction: refusals, never oracle cuts. (2) The §1.2 blame
> walk's `STEP` table mapped `fix` "body" to IR index 3 — the *measure*; the
> body is 4. Corrected in the probe on 2026‑08‑26; a replay showed 0 of the 12
> banked blame paths traverse a fix‑body step, so every §1 pasted number stands
> as printed.

### 2.3 §2.5's rejection: respected

The 2026‑08‑25 §2.5 rejected a mechanically-derived skeleton on two grounds: (a) the
eta-skeleton's single hole's sub-task *is* the original task, and (b) it hands the
model the declared type the control has to guess.

**Neither B1 nor B2 comes near it** — both are prompt/feedback manipulations over
drafts the model writes itself. **B3 escapes it on its own terms**: the holed draft's
declared type is the model's own, from its own rejected draft, so ground (b) does not
apply; and §3's bare-hole rule refuses the result whenever holing collapses the draft
to eta, so ground (a) does not apply either. B3 is nonetheless barred from the primary
family for the §2.1 reason above, which §2.5 did not raise and which is the stronger
objection. **No part of this design needs to argue past §2.5, and none of it does.**

### 2.4 Designs rejected here

- **Relaxing the gate and re-running, per row 4's letter and nothing more.** §1.3
  prices it at 8 fill draws and 0 composed definitions on the banked draws. It would
  buy a second null at the same power and cost the same $3. Rejected; the gate ships
  as *part* of the design, never as the whole of it.
- **A grammar or mask change to cheapen `(hole `.** §1.4 shows nothing to fix: the
  head is admissible at all eight body goals. A mask change here would be a
  soundness risk in exchange for an effect that is not the bottleneck.
- **Improving the narrowing note.** 42 % of the banked arm's notes hand the model a
  raw Python `repr` of the type IR — `expected [0, 2], got [1, b'?\xf2\x10G…']` — in
  an encoding it has never seen in the surface (`--section blame`, and it is 37–42 %
  in all three arms, so it is not a `holes`-arm artefact). That is a genuine defect and
  probably a real lever, but it is a **feedback-legibility** lever that would move
  `redraft` and `holes` together and confound both. Filed for the plan owner as a
  separate item, not folded in here.
- **Re-running only `holes` against the banked controls, at full scale.** Cheaper by
  $3, and rejected on the 2026‑08‑25 §4.5 standard: *"The test is against the
  concurrent `whole` arm, so a harness change cannot masquerade as an effect"* — and
  this re-run changes the harness. It survives only as the pre-committed
  **stockout** degradation in §5, where the trade is named rather than hidden.

---

## 3. Two stages, because the pilot is an option on the spend

Elicitation is a **draw-level** property with n in the hundreds per arm; the primary
is a **cell-level** property with n = 64–96. So the question that has to be answered
first is also the one that is cheapest to answer, by roughly a factor of ten. The
banked run spent $2.75 to discover its treatment never engaged. Doing that twice
would be a choice.

- **Stage 0 — pilot.** Four blocks × 16 cells, ≈ 5.2 h, ≈ **$1.30**. Measures
  elicitation and, for the first time in project history, whether a fill draw
  can produce an assembly that passes all four layers. Its pre-committed decision
  rule either selects one block for Stage 1 or stops the spend.
- **Stage 1 — confirmatory.** Three arms × 96 cells, ≈ 18.2 h, ≈ **$4.55**. Only
  launches if Stage 0's gates clear. Its data is disjoint from Stage 0's and its
  test is the one §4.4 fixes.

Two instances, sequential, rather than one long runlist: the sequencing *is* the
value, and a 23 h single run doubles the preemption window for no gain. Total spot
exposure ≈ **$5.90**, at this project's ~$6 per-experiment ceiling and stated as
such.

---

## 4. Pre-registration

Everything in §4 is fixed before any GPU run. No mid-run peeking; no post-hoc test
selection. §4.8 restates the standard.

### 4.1 Hypotheses

**E1 (elicitation, Stage 0).** At least one candidate block raises the share of
skeleton draws that reach a fill under the §2.1 gate — well-scoped, non-bare, at
least one fillable hole — above the `§3-block` reference, to a rate whose one-sided
95 % lower bound is ≥ 10 %.

**E2 (assembly liveness, Stage 0).** At least one fill draw, anywhere in the pilot,
splices into an assembly that passes all four funnel layers. This is the direct test
of §1.3's prediction that sibling errors dominate, and it has never been observed:
across 747 skeleton draws the banked run executed **zero** fill draws.

**H1 (mechanism, Stage 1, primary).** Hole-directed decomposition, with the block
Stage 0 selected and the §2.1 gate, raises the share of held-out cells producing a
**composed definition** — hole-free, all four funnel layers, canonical type surface
equal to the task's `expected_type_surface` — above the concurrent `whole` control at
a matched completion-token purse. *(Inherited verbatim from 2026‑08‑25 §4.1 H1.)*

**H2 (attribution, Stage 1).** `holes` exceeds `redraft`, which is `holes` minus the
hole protocol and nothing else. *(Inherited verbatim.)*

**H3 (outcome, secondary).** Unchanged from 2026‑08‑25 §4.1, with its ≥ 5-successes
threshold and Clopper–Pearson reporting discipline intact.

### 4.2 Stage 0 — arms, metric, gates, selection rule

**Arms.** Four, `held_out` regime, condition `gbnf+typemask`, curated-only resolver,
`address_book: "full"`, `pruners` pinned to `["goal-type", "de-bruijn", "ref-hash"]`,
`generation_protocol: "holes"`, `fill_gate: "well-scoped"`, seeds `[1, 2]`, 8 tasks →
**16 cells per block**, purse 4,608 tok/cell.

| Block | Difference from `§3-block` |
|---|---|
| `§3-block` (B0) | — (reference) |
| `exemplar` (B1) | + the §2.2 exemplar block |
| `hole-required` (B2) | + the §2.2 hole-demand note, rounds 0–2 |
| `checker-holed` (B3) | + `hole_at_error` seeding on typecheck rejection |

**Primary pilot metric — fill-reaching draw rate.** A skeleton draw counts iff it
(a) reached the typecheck layer, (b) is not a bare-hole body under §3's rule
evaluated unconditionally, and (c) has ≥ 1 fillable hole. Mechanical, computed from
`records.jsonl`. Reference value from the banked arm: **8/747 = 1.07 %**.

**Gate E1 — eligibility.** A block is eligible for Stage 1 iff its fill-reaching draw
rate has a **one-sided 95 % Wilson lower bound ≥ 10 %**. At the pilot's ≈ 184 draws
per block that means an observed rate of ≈ 15 % or better:

```
  n= 180 draws:  obs=10%->lo=6.9%  obs=15%->lo=11.1%  obs=20%->lo=15.6%  obs=30%->lo=24.7%  obs=50%->lo=43.9%
```

The bar is stated on the lower bound, not the point estimate, so a lucky pilot cannot
promote a block. Why 10 %: the banked `holes` arm ran **11.67 draws per cell**
measured (747 draws ÷ 64 cells, 349.8 mean completion tokens against the 4,608 purse),
so a 10 % fill-reaching draw rate gives ≈ 1.2 fill-reaching rounds per cell — one shot
per cell, the minimum at which a 15 % per-cell composed rate is arithmetically
reachable at all. The same figure sizes the pilot at ≈ 187 draws per block.

**Gate E2 — assembly liveness.** Stage 1 launches only if ≥ 1 fill draw across the
whole pilot splices into a four-layer-accepted assembly. If E1 clears and E2 does not,
§1.3's prediction is confirmed and the finding is that **decomposition cannot repair a
draft whose committed structure is wrong** — which is a result, reportable at $1.30,
and Stage 1 is not launched.

**Selection rule, pre-committed.** Among blocks passing E1 and excluding B3
(§2.2), take the highest fill-reaching **cell** rate; ties broken by draw rate, then
by the order B1 < B2. If B1 and B2 both fail E1 and B3 passes, the lever has changed
identity and that is an **escalation to the plan owner**, not an automatic Stage 1
(§6). If no block passes E1, Stage 1 does not launch.

Stage 0's records are **not pooled into any Stage 1 test.** This is a standard
two-stage pick-the-winner design and it is honest only because the arms, the metric,
the bars and the tie-breaks are all written here, before the pilot runs.

### 4.3 Stage 1 — arms and harness settings

Three arms, everything as 2026‑08‑25 §4.2/§4.3 except the two changes named:

| Arm | `generation_protocol` | `fill_gate` | Prompt vs `whole` |
|---|---|---|---|
| `whole` | `whole` | n/a | identical, byte for byte |
| `redraft` | `redraft` | n/a | identical on draw 0 of every cell |
| `holes` | `holes` | **`well-scoped`** | + the block Stage 0 selected |

- `seeds: [1…12]`, 8 tasks → **96 cells per arm** (§4.5 says why 96, not 64).
- `token_budget_per_task: 4608`, `max_tokens_per_draw: 768`,
  `max_draws_per_task: 64`, `n_ctx: 32768`, `stop_on_semantic_success: false` —
  all unchanged.
- `fills_per_round_max: 6` / `fill_attempts_per_hole: 2` on accepted drafts;
  `1` / `1` on relaxed-gate drafts (§2.1 consequence 4).
- Truncation stays a genuine rejection; above 10 % the run is reported as censored
  and the primary flagged, exactly as before. (Banked `holes` truncation: 4.6 %.)

`whole` and `redraft` are **re-run concurrently**, not reused. The harness changed;
2026‑08‑25 §4.5's standard is that the control is concurrent so a harness change
cannot masquerade as an effect. The $2.30 that costs is the cheapest credibility in
this plan.

### 4.4 Primary metrics, tests, α

**Metric.** Composed-definition rate per cell, defined exactly as 2026‑08‑25 §4.5
(a) ∧ (b) ∧ (c). Unchanged, deliberately: a re-run that also moves its metric is not
a re-run.

**Test.** Fisher exact, **one-sided** (`holes` > `whole`), on the 2 × 2 cell-level
table, **α = 0.05**.

**Attribution gate (H2).** Fisher exact, one-sided, `holes` > `redraft`, α = 0.05.
As before it cannot license the lever on its own; its only function is to *remove*
the attribution when it fails.

**α accounting — fixed-sequence gatekeeping, no correction.** Stage 0's gates E1/E2
are **gates, not tests**: they are thresholds on point estimates and interval bounds,
they spend no α, and no p-value from Stage 0 is reported as inferential. H1 is the
single α = 0.05 comparison in the confirmatory family. H2 follows it in a fixed
sequence and is read only if H1 rejects, which preserves the family-wise error rate at
0.05 with no Holm correction — the same reasoning 2026‑08‑25 §4.5 used and Amendment
A1 established.

**Clustering sensitivity.** Task-stratified permutation test, 10,000 permutations of
arm labels within task, statistic = difference in composed-definition rate. A
sensitivity analysis, not a second primary; a disagreement with the Fisher is reported
as an unresolved clustering caveat and is **not** resolved by picking the friendlier
one. *(Inherited; it agreed with the Fisher on the banked run.)*

### 4.5 Power — stated honestly, before any run

```
### P2 power, one-sided Fisher at alpha=0.05, per-cell composed-definition
A0 = 0.047 — the MEASURED `whole` rate (3/64), not the 0.03 the 2026-08-25 plan
planned against. The baseline moved up, which costs power at every A1.

  A0=0.047
    n=  64/arm  A1=0.10:0.206  A1=0.15:0.545  A1=0.20:0.806  A1=0.25:0.948  A1=0.30:0.988
    n=  96/arm  A1=0.10:0.301  A1=0.15:0.715  A1=0.20:0.937  A1=0.25:0.993  A1=0.30:0.999
    n= 128/arm  A1=0.10:0.386  A1=0.15:0.837  A1=0.20:0.982  A1=0.25:0.999  A1=0.30:1.000
    n= 160/arm  A1=0.10:0.496  A1=0.15:0.910  A1=0.20:0.995  A1=0.25:1.000  A1=0.30:1.000

  A0=0.03
    n=  64/arm  A1=0.10:0.347  A1=0.15:0.716  A1=0.20:0.919  A1=0.25:0.981  A1=0.30:0.997
    n=  96/arm  A1=0.10:0.507  A1=0.15:0.877  A1=0.20:0.986  A1=0.25:0.999  A1=0.30:1.000
```

**Reading, fixed in advance.** The banked run did not only fail to move the primary —
it moved the *baseline*, from a planned 0.03 to a measured 0.047. At the 2026‑08‑25
design point of n = 64 that costs 17 points of power against A1 = 0.15 (0.716 → 0.545)
and 11 points against A1 = 0.20 (0.919 → 0.806). **n = 96 restores it**: 0.715 against
0.15 and 0.937 against 0.20, i.e. back to what the last plan believed it was buying.
That is the whole argument for 12 seeds, and the extra $1.50 it costs (12.2 h → 18.2 h
of Stage-1 spot).

The design point remains A1 ≈ 0.15–0.20, and the factoring is unchanged from
2026‑08‑25 §4.7 — per-cell success is *(a cell produces a well-scoped skeleton with a
fillable hole) × (its holes get well-typed fills)*. What has changed is that the first
factor is no longer measured at 0.375–0.55; it is measured at **0.125 (8/64 cells)**
under the §2.1 gate with the banked block, and E1's bar exists to move it. The second
factor is still exactly what the experiment does not know, and E2 exists because on
§1.2's evidence it may be near zero.

**A null primary at this power is evidence against a ≥ 20 % effect. It is not
evidence against a 10 % one, and the report will say so in those words.**

### 4.6 Secondaries and telemetry

All 2026‑08‑25 §4.6 secondaries carry over unchanged — hand-scored semantic success
with Clopper–Pearson intervals, route-reference rate, funnel-acceptance and
type-exactness, overhead accounting, truncation, illegal-`ref` rate, acc/1k tok with
its non-comparability caveat. Added, because they are what this design is about:

- **Elicitation:** hole-bearing draw rate and fill-reaching draw rate per arm, with
  the banked `holes` arm quoted alongside as a historical reference (labelled as such,
  never tested against).
- **Fill-draw behaviour, first measurement ever:** fill draws attempted, their funnel
  outcome distribution, splice outcomes (`spliced` / `rolled_back` / `SpliceError` /
  monotonicity refusal), and for every rollback whether the assembly's error path
  resolves to the filled hole or to a sibling — `hole_elicitation_probe --section blame`
  run over the new records, which is the direct falsification test for §1.2.
- **Gate accounting:** fills reached from accepted drafts vs from relaxed-gate drafts,
  separately, with composed definitions attributed to each. This is what tells the
  next reader whether row 4's remedy did anything.
- **Exemplar-copying (B1 risk, §2.2):** the distribution of `hole_goal` surfaces
  against the two exemplar goal types, per task.

### 4.7 Stub-backend gate on GPU spend — what is re-run and what is cited

Deliverable 6, run and pasted into this file before either instance launches. From
2026‑08‑25 §4.8, checks **2, 3, 4, 5, 6, 8** are **cited, not re-run**: the blindness
signatures, the eight gold round-trips, the floor-rule regression, the context budget,
the no-gold-surface assertion and the route-reference extraction all pin machinery this
design does not touch. Re-run and extended:

- **Check 1 — the arms differ only by their block.** As before, byte-comparing built
  prompts, now over four blocks rather than one. **1b:** assert
  `closed_subtask_type` is still called with `declared_type_of(draft)` and never with
  the task's type surface — pinned against the signature, the way check 2 pins the
  others. **1c:** assert every hash in each block already appears in the four pinned
  few-shot definitions, and that no held-out `expected_surface` or
  `expected_type_surface` appears in any block. *(Both already pass — see the
  `exemplars` output in §2.2.)*
- **Check 7 — a scripted stub drives one cell of each arm**, extended to the
  relaxed gate: a scripted draft that fails at **each** of parse / references /
  scope / typecheck, asserting the gate blocks the first three and admits the fourth;
  a rejected **bare-hole** draft, asserting §3's rule refuses it now that the
  `funnel.accepted` conjunct is gone; and a relaxed-gate round, asserting it takes
  exactly one fill draw.
- **Check 9 (new) — exemplar round-trip.** Both §2.2 exemplars: skeleton
  funnel-accepted, fill funnel-accepted, splice byte-identical to the corpus fixture,
  assembly funnel-accepted. *(Already passing; §2.2 pastes the output.)*
- **Check 10 (new) — `hole_at_error` refuses rather than guesses.** Over every banked
  typecheck-rejected skeleton, `hole_at_error` either returns a draft that parses,
  keeps its declared type, and is not a bare hole, or returns `None`. Never anything
  else. *(Only needed if B3 is implemented; see §8.)*

**Nothing launches until check 1, 7 and 9's output is in this file**, and Stage 1
launches only on Stage 0's gates.

#### Deliverable 6 — run and pasted, 2026‑08‑26

Run on CPU with the stub backend, no GPU and no network:
`python3 -m experiment.hole_elicitation_stub_check` from `prototype/`, exit code
**0**. The script is
[`prototype/experiment/hole_elicitation_stub_check.py`](../../prototype/experiment/hole_elicitation_stub_check.py).
Checks **2, 5** and **6** appear in *extended* form — the 2026‑08‑25 §4.8 versions
are cited above and stand unchanged; what runs here is their re-run over the four
pilot blocks and the surfaces this plan added. Check **11** is beyond §4.7's list
and is here because §4.7's citation argument rests on §1's pasted numbers: if
those stopped reproducing from the banked records, the premises would have moved
and the gate should not open on them.

**Every check passes. The gate on GPU spend is open** — check 1, 7 and 9's output
is now in this file, as §4.7 requires. Stage 1 still launches only on Stage 0's
gates, via deliverable 7's selector.

```
### Check 1a — the four pilot arms differ from `whole` only by their block

Byte-level where the mechanism is prompt-side, byte-*identical* where it is
runner-side. `whole` is the reference the 2026-08-25 §4.8 check 1 used, so the
chain is the same one: strip the arm's added block and what is left must be the
control's prompt, byte for byte.

heldout/list/concatLength        minus-block==whole: §3-block=ok exemplar=ok hole-required=ok checker-holed=ok  B2/B3==B0=yes  B1==B0+exemplar=yes
heldout/list/mapLength           minus-block==whole: §3-block=ok exemplar=ok hole-required=ok checker-holed=ok  B2/B3==B0=yes  B1==B0+exemplar=yes
heldout/list/reverseThen         minus-block==whole: §3-block=ok exemplar=ok hole-required=ok checker-holed=ok  B2/B3==B0=yes  B1==B0+exemplar=yes
heldout/maybe/mapOrElse          minus-block==whole: §3-block=ok exemplar=ok hole-required=ok checker-holed=ok  B2/B3==B0=yes  B1==B0+exemplar=yes
heldout/list/headOrElse          minus-block==whole: §3-block=ok exemplar=ok hole-required=ok checker-holed=ok  B2/B3==B0=yes  B1==B0+exemplar=yes
heldout/list/sum                 minus-block==whole: §3-block=ok exemplar=ok hole-required=ok checker-holed=ok  B2/B3==B0=yes  B1==B0+exemplar=yes
heldout/sample/stampedBytes      minus-block==whole: §3-block=ok exemplar=ok hole-required=ok checker-holed=ok  B2/B3==B0=yes  B1==B0+exemplar=yes
heldout/nat/selectNonNegative    minus-block==whole: §3-block=ok exemplar=ok hole-required=ok checker-holed=ok  B2/B3==B0=yes  B1==B0+exemplar=yes

  §3-block         adds  223 B of block (~149 tokens)
  exemplar         adds 1072 B of block (~715 tokens)
  hole-required    adds  223 B of block (~149 tokens)
  checker-holed    adds  223 B of block (~149 tokens)

result: PASS — 8 tasks x 4 blocks

### Check 1b — the closure still reads the DRAFT's own declared type

Pinned two ways: against the signature, the way 2026-08-25 §4.8 check 2 pins the
other fill-path surfaces; and against the runner's single call site, which must
pass `declared_type_of(draft)` and must never mention a task's type surface.

closed_subtask_type('declared_type_surface', 'obligation')  as landed  no Task
runner.py call sites (1): ['closed = closed_subtask_type(declared_type_of(draft), obligation)']
lines naming both the closure and a task's type surface: 0
draft (def (fn Bool () Bool) (lam Bool (… -> closed sub-task (fn Bool () Bool) (the task's own type is (fn (data 0x2ee931a3746132882cdbc6…)

result: PASS

### Check 1c — no gold surface and no unseen hash in any block

The exemplar block is the only block with bytes to leak. It introduces zero new
store content (§2.2) — only a new *form* of content already in every prompt — and
that is what this pins: every hash in it is already in the four pinned few-shot
definitions, and no held-out gold term or type surface appears in it.

§3-block          223B  hashes=0  unseen=0  gold-term-leaks=0  gold-type-leaks=0  clean
exemplar         1072B  hashes=1  unseen=0  gold-term-leaks=0  gold-type-leaks=0  clean
hole-required     223B  hashes=0  unseen=0  gold-term-leaks=0  gold-type-leaks=0  clean
checker-holed     223B  hashes=0  unseen=0  gold-term-leaks=0  gold-type-leaks=0  clean

heldout_gold.prompt_leak_check(): no offenders
result: PASS

### Check 1d — the seven shipped configs, field by field

§9 names an unpinned config as a thing that would change this plan, so the pins
are asserted rather than assumed. The Stage-1 `holes` config's `hole_block` is
checked to be still in its PLACEHOLDER state (`§3-block`, the banked block and
the field's default): Stage 0 has not run, so nothing may have selected yet, and
`pilot_select --apply` is the only thing licensed to write that field.

pilot_b0         hole_block=§3-block       hole_required_rounds=0  beyond-exceptions=[]  unpinned=[]  ok
pilot_b1         hole_block=exemplar       hole_required_rounds=0  beyond-exceptions=[]  unpinned=[]  ok
pilot_b2         hole_block=hole-required  hole_required_rounds=3  beyond-exceptions=[]  unpinned=[]  ok
pilot_b3         hole_block=checker-holed  hole_required_rounds=0  beyond-exceptions=[]  unpinned=[]  ok

decomp2_whole    protocol=whole    fill_gate=accepted     hole_block=§3-block   seeds=12  beyond-exceptions=[]  ok
decomp2_redraft  protocol=redraft  fill_gate=accepted     hole_block=§3-block   seeds=12  beyond-exceptions=[]  ok
decomp2_holes    protocol=holes    fill_gate=well-scoped  hole_block=§3-block   seeds=12  beyond-exceptions=[]  ok

Stage-1 `holes` hole_block placeholder intact ('§3-block', nothing selected yet): True

elicitation-pilot-runlist.json       4 entries  points at the shipped configs
elicitation-stage1-runlist.json      3 entries  points at the shipped configs

result: PASS

### Check 2 (extended) — the new surfaces take no Task, by signature

note: 2026-08-25 §4.8 check 2 pins `hole_obligations` / `closed_subtask_type` /
      `fill_term_skeleton` / `splice_fill` / `build_fill_prompt` and is cited, not
      re-run (§4.7). These are the surfaces this plan added. `build_prompt` and
      `context_required` do take a `Task` and always have — they are the ask —
      so the new `hole_block` argument is checked below to be a plain string in
      the pinned vocabulary rather than anything that reads one.

prompts.hole_exemplar_block      ['resolver']  as landed  no Task
prompts.checker_holed_cut        ['draft_source', 'error_path', 'resolver']  as landed  no Task
prompts.hole_at_error            ['draft_source', 'error_path', 'resolver']  as landed  no Task
runner._fill_admitted           ['config', 'funnel', 'bare']  as landed  no Task
runner._with_hole_required_note ['narrowing', 'round_index', 'draft', 'census', 'config']  as landed  no Task
runner._checker_holed_seed      ['config', 'draft', 'funnel', 'resolver']  as landed  no Task
probe.check_ten_verdict('draft_source', 'error_path', 'resolver')  as landed  no Task
build_prompt(hole_block=…) default='§3-block'  the banked block, so pre-plan configs are byte-identical
context_required(hole_block=…) default='§3-block'  the banked block, so pre-plan configs are byte-identical
HOLE_BLOCKS=['§3-block', 'exemplar', 'hole-required', 'checker-holed']  the four §4.2 blocks
hole_exemplar_block(resolver) stable across calls: True

result: PASS

### Check 5 (extended) — context_required <= n_ctx - max_tokens_per_draw

note: extended to all seven configs this plan ships, because B1's exemplar block
      is ~565 tokens of prompt the 2026-08-25 figure did not carry. The worst-case
      *fill* prompt is built from the largest gold-derived nested draft — the same
      fixture the 2026-08-25 check 5 used, imported from `decomposition_stub_check`
      rather than rebuilt, so the two gates cannot drift. A fill prompt carries no
      block, so its figure is block-independent by construction.

pilot_b0         block=§3-block       skeleton= 18496 tok  worst-case fill= 19795 tok  threshold= 32000  OK
pilot_b1         block=exemplar       skeleton= 19062 tok  worst-case fill= 19795 tok  threshold= 32000  OK
pilot_b2         block=hole-required  skeleton= 18496 tok  worst-case fill= 19795 tok  threshold= 32000  OK
pilot_b3         block=checker-holed  skeleton= 18496 tok  worst-case fill= 19795 tok  threshold= 32000  OK
decomp2_whole    block=§3-block       skeleton= 18346 tok  worst-case fill= 19795 tok  threshold= 32000  OK
decomp2_redraft  block=§3-block       skeleton= 18346 tok  worst-case fill= 19795 tok  threshold= 32000  OK
decomp2_holes    block=§3-block       skeleton= 18496 tok  worst-case fill= 19795 tok  threshold= 32000  OK

exemplar block costs 566 prompt tokens on the longest held-out prompt (18496 -> 19062, +3.1%)
worst-case draft: heldout/sample/stampedBytes (906 chars), carried with a narrowing note
result: PASS

### Check 6 (extended) — no gold surface appears in any pilot prompt

note: extended over the four blocks rather than the one banked block. Fill prompts
      are built from two draft shapes, as in 2026-08-25 §4.8 check 6: a
      model-writable one (the eta-skeleton, gold-free by construction) and the
      gold-derived nested draft. The harness adds nothing beyond the draft it is
      handed, and a fill prompt carries no block, so B1 adds no fill-side surface.

skeleton prompts checked    32 (4 blocks x 8 tasks)
fill prompts checked        64
gold surfaces searched for   8 (every task's, in every prompt)

result: PASS

### Check 7 — a scripted stub drives one cell of each pilot arm

note: the cell runs at condition `gbnf` (the mask needs a real vocabulary); the
      purse, the caps, the gate and the block are the arm's own. Rounds 2-6 are
      the §2.1 four-layer gate, one layer each; round 1 is the accepted path and
      Gate E2's event; round 3 is the relaxation, capped at one fill draw by §2.1
      consequence 4. B2's window is read out of the NEXT round's prompt bytes,
      not out of the record field that claims the note was added.

§3-block         records= 126 draws= 64 rounds= 62 fills= 2 tokens=  815/4608
                 budget: full-cap-or-no-draw=True every-draw-charged=True within-purse=True ends-when-no-room=True one-cell_done=True
                 §2.1 four-layer gate:
                   round 2  funnel=typecheck   bare=True  fill-draws=0  expected=block  ok   bare hole — §3's rule refuses it
                   round 3  funnel=typecheck   bare=False fill-draws=1  expected=admit  ok   the relaxation: reached the typecheck layer
                   round 4  funnel=scope       bare=False fill-draws=0  expected=block  ok   blocked — the binder context folded into the closed type is wrong
                   round 5  funnel=references  bare=False fill-draws=0  expected=block  ok   blocked — an unresolvable hash in the declared type surface
                   round 6  funnel=parse       bare=False fill-draws=0  expected=block  ok   blocked — no IR, so no obligations and no path
                 §2.1 consequence 4: accepted round fill-draws=1 (caps 6/2)  relaxed round fill-draws=1 (capped at 1)  ok
                 splice outcomes: spliced=1 rolled-back=1 — the same good fill, two outcomes, decided by the draft (§1.3)  ok
                 §3's rule, unconditional: round 2 funnel=typecheck bare_hole_body=True, fill-draws=0  ok
                 B2: no hole-demand note anywhere (hole_required_rounds=0)  ok
                 B3: no `hole_at_error` seeding (this arm is not B3)  ok
exemplar         records= 126 draws= 64 rounds= 62 fills= 2 tokens=  815/4608
                 budget: full-cap-or-no-draw=True every-draw-charged=True within-purse=True ends-when-no-room=True one-cell_done=True
                 §2.1 four-layer gate:
                   round 2  funnel=typecheck   bare=True  fill-draws=0  expected=block  ok   bare hole — §3's rule refuses it
                   round 3  funnel=typecheck   bare=False fill-draws=1  expected=admit  ok   the relaxation: reached the typecheck layer
                   round 4  funnel=scope       bare=False fill-draws=0  expected=block  ok   blocked — the binder context folded into the closed type is wrong
                   round 5  funnel=references  bare=False fill-draws=0  expected=block  ok   blocked — an unresolvable hash in the declared type surface
                   round 6  funnel=parse       bare=False fill-draws=0  expected=block  ok   blocked — no IR, so no obligations and no path
                 §2.1 consequence 4: accepted round fill-draws=1 (caps 6/2)  relaxed round fill-draws=1 (capped at 1)  ok
                 splice outcomes: spliced=1 rolled-back=1 — the same good fill, two outcomes, decided by the draft (§1.3)  ok
                 §3's rule, unconditional: round 2 funnel=typecheck bare_hole_body=True, fill-draws=0  ok
                 B2: no hole-demand note anywhere (hole_required_rounds=0)  ok
                 B3: no `hole_at_error` seeding (this arm is not B3)  ok
hole-required    records= 126 draws= 64 rounds= 62 fills= 2 tokens=  815/4608
                 budget: full-cap-or-no-draw=True every-draw-charged=True within-purse=True ends-when-no-room=True one-cell_done=True
                 §2.1 four-layer gate:
                   round 2  funnel=typecheck   bare=True  fill-draws=0  expected=block  ok   bare hole — §3's rule refuses it
                   round 3  funnel=typecheck   bare=False fill-draws=1  expected=admit  ok   the relaxation: reached the typecheck layer
                   round 4  funnel=scope       bare=False fill-draws=0  expected=block  ok   blocked — the binder context folded into the closed type is wrong
                   round 5  funnel=references  bare=False fill-draws=0  expected=block  ok   blocked — an unresolvable hash in the declared type surface
                   round 6  funnel=parse       bare=False fill-draws=0  expected=block  ok   blocked — no IR, so no obligations and no path
                 §2.1 consequence 4: accepted round fill-draws=1 (caps 6/2)  relaxed round fill-draws=1 (capped at 1)  ok
                 splice outcomes: spliced=1 rolled-back=1 — the same good fill, two outcomes, decided by the draft (§1.3)  ok
                 §3's rule, unconditional: round 2 funnel=typecheck bare_hole_body=True, fill-draws=0  ok
                 B2: note in rounds [1, 3] prompts, none after (window=3 rounds)  ok
                 B3: no `hole_at_error` seeding (this arm is not B3)  ok
checker-holed    records= 126 draws= 64 rounds= 62 fills= 2 tokens=  815/4608
                 budget: full-cap-or-no-draw=True every-draw-charged=True within-purse=True ends-when-no-room=True one-cell_done=True
                 §2.1 four-layer gate:
                   round 2  funnel=typecheck   bare=True  fill-draws=0  expected=block  ok   bare hole — §3's rule refuses it
                   round 3  funnel=typecheck   bare=False fill-draws=1  expected=admit  ok   the relaxation: reached the typecheck layer
                   round 4  funnel=scope       bare=False fill-draws=0  expected=block  ok   blocked — the binder context folded into the closed type is wrong
                   round 5  funnel=references  bare=False fill-draws=0  expected=block  ok   blocked — an unresolvable hash in the declared type surface
                   round 6  funnel=parse       bare=False fill-draws=0  expected=block  ok   blocked — no IR, so no obligations and no path
                 §2.1 consequence 4: accepted round fill-draws=1 (caps 6/2)  relaxed round fill-draws=1 (capped at 1)  ok
                 splice outcomes: spliced=2 rolled-back=0 — B3 cut the sibling error out, so the assembly the other arms roll back is accepted here  ok
                 §3's rule, unconditional: round 2 funnel=typecheck bare_hole_body=True, fill-draws=0  ok
                 B2: no hole-demand note anywhere (hole_required_rounds=0)  ok
                 B3: eligible=2 cut=1 refused=1; round 3 cut at '2.2.3' goal='Bool'; round 2 refused: the nearest holeable ancestor is the whole body; §3's bare-hole rule refuses it  ok

result: PASS

### Check 7e — the E1/E2 computation path, through `pilot_select` itself

The pilot's selection is executed by a committed script, not judged (§4.8), so the
script's own functions are what compute here — `block_stats`, `assembly_liveness`,
`selection_verdict` — over check 7's stub records. This is a check of the
MECHANICS, not a result: one scripted cell per block, identical by construction,
so the verdict below is arithmetic on a fixture and says nothing about any model.

block                         draws  qualify  draw_rate  wilson_lo   cells  cell_rate    E1
§3-block (B0, reference)         62        2     3.23%      1.07%   1/1      100.00%  fail
exemplar (B1)                    62        2     3.23%      1.07%   1/1      100.00%  fail
hole-required (B2)               62        2     3.23%      1.07%   1/1      100.00%  fail
checker-holed (B3, diagnostic)     62        2     3.23%      1.07%   1/1      100.00%  fail

Gate E2 (assembly liveness, pooled): CLEAR — 5 fill draw(s) spliced into a four-layer-accepted assembly
selection_verdict kind='no_launch_e1' block='-'
  No block clears Gate E1 (§6 row 1). Hole-directed decomposition is not elicitable at this scale under prompt or feedback pressure. Stage 1 is not launched.
  (a fixture, not a result: 3.2 % against a 10 % bar, so `no_launch_e1`
   is the correct answer and any other would mean the bar had moved)  ok

§4.2's selection rule itself, over constructed stats — every branch:

  no block clears E1                           -> kind=no_launch_e1   block=-              ok
  only B3 clears E1 (§6 row 3)                 -> kind=escalate       block=-              ok
  B1 and B2 clear, E2 does not (§6 row 2)      -> kind=no_launch_e2   block=-              ok
  B1 and B2 tie -> the fixed order B1 < B2     -> kind=select         block=exemplar       ok
  B2 strictly higher cell rate -> B2           -> kind=select         block=hole-required  ok

result: PASS

### Check 9 — both §2.2 exemplars round-trip to their corpus fixture

Driven through the landed constants in `prompts.py` — the single source of the
block's bytes — and the landed protocol functions, never a second copy. The
`maybe/map` fill is not in the block (§2.2 shows that exemplar as draft +
sub-task only); it is reconstructed here from `fill_term_skeleton` so the
round-trip can be checked end to end all the same.

corpus/bool/not
  draft      chars=  78  funnel=accepted  holes=1 fillable=1
  sub-task   chars=  17  (derived from the draft's own declared type)
  fill       chars=  51  funnel=accepted
  assembled  funnel=accepted  identical-to-fixture=True
corpus/maybe/map
  draft      chars= 524  funnel=accepted  holes=1 fillable=1
  sub-task   chars= 191  (derived from the draft's own declared type)
  fill       chars= 383  funnel=accepted
  assembled  funnel=accepted  identical-to-fixture=True

block size: 847 characters of definition surface, ~565 tokens
result: PASS

### Check 10 — `hole_at_error` refuses rather than guesses

Over every banked typecheck-rejected skeleton in all three arms, through the
probe's own `check_ten_rows` / `check_ten_verdict` / `CHECK_TEN_ALLOWED` —
imported, not restated, so this gate and the probe cannot answer differently.
A verdict outside the allowed two is a violation and is printed with the draft.

whole     typecheck-rejected  628   cut   91   refused  537   violations 0
redraft   typecheck-rejected  626   cut   70   refused  556   violations 0
holes     typecheck-rejected  597   cut   72   refused  525   violations 0

total     cut  233   refused 1618   violations 0

result: PASS

### Check 11 (new) — §1's pasted numbers still reproduce

§4.7's argument is that checks 2-6 and 8 can be *cited* because the machinery they
pin is untouched. That citation is only as good as §1's numbers, which are the
premises the whole design rests on. Each line below is a substring the plan pastes
in §1, matched against today's output of the probe section that produced it.

--section census    7 pinned lines  all reproduce
--section gate      9 pinned lines  all reproduce
--section mask      2 pinned lines  all reproduce

result: PASS

### Deliverable 6 verdict: ALL CHECKS PASS — the GPU gate is open
```

---

### 4.8 No peeking, no test-shopping

The blocks, the gates, the bars, the tie-breaks, the arms, the metric, the unit, the
tests, the α and the thresholds are fixed above before either run launches. Stage 0's
selection is executed from its records by a committed script, not by reading the pilot
and deciding. Whatever the three Stage-1 composed-definition numbers turn out to be,
§4.4's test is the one reported as primary and §6's row is the one that fires. Any
change to any of it is filed here, before the corresponding stage's first draw, with
the defect stated and the repair measured.

---

## 5. Cost

Reusing the 2026‑08‑25 §5 throughput model unchanged (it came in ~12 % conservative:
≈ 10.7 h actual against 12.2 h estimated). `g2-standard-4`, us‑central1, spot first,
runlist mode, self-deleting, teardown part of the run.

**Stage 0 — pilot**

| Block | Cells | Purse | Completion tokens | Rate | Hours |
|---|---|---|---|---|---|
| `§3-block`, `exemplar`, `hole-required`, `checker-holed` | 16 each | 4,608 | 73,728 each | 16.7 tok/s | 1.23 h each |
| boot, model load, build-cache restore | | | | | 0.3 h |
| **total** | **64** | | **294,912** | | **≈ 5.2 h** |

**Stage 1 — confirmatory**

| Arm | Cells | Purse | Completion tokens | Rate | Hours |
|---|---|---|---|---|---|
| `whole` | 96 | 4,608 | 442,368 | 23.4 tok/s | 5.25 h |
| `redraft` | 96 | 4,608 | 442,368 | 23.4 tok/s | 5.25 h |
| `holes` | 96 | 4,608 | 442,368 | 16.7 tok/s | 7.35 h |
| boot, model load, build-cache restore | | | | | 0.3 h |
| **total** | **288** | | **1,327,104** | | **≈ 18.2 h** |

| Line | Unit price | Quantity | Cost |
|---|---|---|---|
| Stage 0, `g2-standard-4` Spot | $0.25/h | 5.2 h | **$1.30** |
| Stage 1, `g2-standard-4` Spot | $0.25/h | 18.2 h | **$4.55** |
| Artifacts bucket + egress, both stages | — | — | < $0.05 |
| **Total, Spot** | | | **≈ $5.90** |
| Stage 1 on-demand, no reduction | $0.85/h | 18.2 h | $15.47 |

**$15.47 is far above this project's ~$6 per-experiment scale, so the reduction is
pre-committed rather than decided at run time.** On spot stockout for Stage 1:
drop to **8 seeds / 64 cells** and run **`holes` only**, using the banked `whole` and
`redraft` arms — same seeds 1–8, same configs, same instance type, same store — as
**historical** controls. 4.9 h, ≈ $4.17 on-demand. The trade is named here rather than
hidden: historical controls forfeit 2026‑08‑25 §4.5's concurrency guarantee, the
n = 64 power row is the one in force (0.806 against A1 = 0.20, 0.545 against 0.15), and
the report must say both in those words. Stage 0 is small enough to run on-demand
unreduced ($4.42) if it comes to that.

Preemption: two instances of 5.2 h and 18.2 h rather than one of 23.4 h. The
address-book run was preempted; the decomposition run lost a spot instance 8 minutes
in and then held 10.7 h. Per-arm incremental upload and the resume runlist
(`[runlist-partial-fetch]`, commit `ac7094e`) have landed and brought every arm home
first try, so the 18.2 h leg is covered by machinery that has now been exercised.

---

## 6. What each outcome licenses

| Outcome | What it licenses next |
|---|---|
| **Stage 0:** no block clears E1 | The model will not write holes at any usable rate under prompt or feedback pressure, at this scale. Hole-directed decomposition is **not elicitable**, which is a finding about the model and the surface, not about decomposition. Stage 1 is not launched; ≈ $4.55 is not spent. Put the model-scale arm (2026‑08‑25 §6 row 3) on the table, and hand the plan owner the feedback-legibility lever (§2.4) as the cheaper alternative. |
| **Stage 0:** E1 clears, E2 does not (fills happen, no assembly ever passes) | §1.2's finding confirmed under treatment: **decomposition cannot repair a draft whose committed structure is wrong**, and a hole does not make the surrounding structure any righter. Report at $1.30. Stage 1 is not launched. The residual is structure, not decomposition, and the next lever should target structure. |
| **Stage 0:** only `checker-holed` (B3) clears E1 | The model cannot *place* a hole but the checker can place one for it. That is checker-localized repair, and it breaks 2026‑08‑25 §2.1's no-oracle property. **ESCALATE to the plan owner**: the lever has changed identity and the H1/H2 framing must be re-decided before any confirmatory spend. Report the pilot as the diagnostic it is. |
| **Stage 1 primary significant and `holes` > `redraft`** | Decomposition is the lever, and elicitation was what stood between the protocol and its mechanism. Everything 2026‑08‑25 §6 row 1 licensed now fires: promote prefix-primed term fills (§2.5), promote `[mask-spine-refs]` into the fill path, re-open worked derivations and external import. |
| **Stage 1 primary significant, attribution gate fails** | Iteration with feedback is the lever, not decomposition — 2026‑08‑25 §6 row 2, unchanged. Take `redraft` as the standard held-out protocol and retire hole-directed decomposition as a distinct lever. |
| **Stage 1 primary null, with E1 and E2 both cleared** | This is the row the banked run could not reach. The protocol **ran** — holes were written, fills were drawn, assemblies passed — and did not help. Composition is not a decomposition problem at this model scale. Unlike 2026‑08‑25 row 4, this null is informative, and it is the one that puts a model-scale arm on the critical path rather than the wish list. |
| **Stage 1 primary null, fill-reaching cell rate < 25 %** | Starved again, at a bar that was set in advance to prevent exactly that. Report as inconclusive **and stop**: two starved runs is a battery/model finding, and a third re-run needs the plan owner's decision, not another gate relaxation. |
| **≥ 5 hand-scored semantic successes in any arm** | Unchanged from 2026‑08‑25 §6: the headline whatever the primary says, hand-score every mechanical-floor candidate in every arm, and re-examine the type-collision recycling failure mode first. |
| **Relaxed-gate fills contribute ≥ 1 composed definition** | Row 4's remedy did something on its own, against §1.3's explicit prediction that it would not. Report the gate accounting (§4.6) as the finding and re-read §1.2's blame analysis, which would then be wrong about the population under treatment. |

---

## 7. Consequences for the results already on record

- **The 2026‑08‑26 decomposition report's primary, its two hand-scored successes and
  its §6 row-4 verdict all stand unchanged.** §1.1 and §1.2 here correct two
  *interpretive* claims in its prose — that the block did not induce holes, and that
  hole-bearing drafts typecheck poorly — without touching a single recorded number.
  Deliverable 8 files those two corrections as a short addendum in the report itself,
  because a reader of the report should not have to find this plan to learn them.
- **No archived number changes.** The gate, the block and the seeds affect only future
  runs. The banked arms remain quotable as historical reference and are the stockout
  fallback's controls.
- **The 2026‑08‑25 plan is closed**, not amended (§0). Its §6 row 4 gets a back-pointer
  to this file and nothing else.
- The address-book report, the corpus-size sweep and the diversity-harvest held-out
  halves are untouched.

---

## 8. Deliverables

Suggested scope and tier only — the orchestrator ranks and files these; this plan does
not edit `TODO.md`.

1. **`prototype/experiment/hole_elicitation_probe.py`** — §1's evidence as a runnable
   script: the block-effect census, the blame analysis, the gate arithmetic, the mask
   reachability walk, the exemplar round-trip with its leak checks, and the power
   tables. **Landed with this plan**; nothing to dispatch. *(T2 if it needs extending
   — §4.6 wants its `blame` section re-run over the new records.)*
2. **The well-scoped fill gate** — `fill_gate: "accepted" | "well-scoped"` on `Config`
   defaulting to `"accepted"`, the §2.1 layer rule, the unconditional bare-hole
   evaluation (`runner.py:828`), and the relaxed-round fill caps. Touches
   `runner.py` and its config plumbing only. Ships with the regression test that
   would have caught the `funnel.accepted and _is_bare_hole(…)` conjunct: a rejected
   bare-hole draft must not reach a fill under either gate. *(T2 — sharply specified,
   one file, and the guard bug is already localized.)*
3. **The `exemplar` block (B1)** — the §2.2 block text pinned in `prompts.py` beside
   `HOLE_PROTOCOL_BLOCK`, built from corpus fixtures, behind a block selector so all
   four pilot blocks are config-selectable. Plus §4.7 checks 1b/1c/9. *(T2 — the text
   and its checks are fully specified above and already verified on CPU.)*
4. **The `hole-required` block (B2)** — `hole_required_rounds` config field, the
   hole-demand note appended to the §8.3 note for the first K rounds, reverting
   exactly afterwards. Touches `runner.py`'s note selection only. *(T2.)*
5. **`hole_at_error` and the `checker-holed` block (B3)** — the §2.2 pure function in
   `prompts.py`, the runner path that seeds a round from it, and §4.7 check 10.
   **The largest new surface in this plan and the only optional one.** If it does not
   land, the pilot runs three blocks and §4.2's selection rule is unaffected (B3 was
   already barred from selection). *(T3 — the checking-mode ancestor walk is where the
   care is, and returning `None` must be the default rather than the fallback.)*
6. **`prototype/experiment/hole_elicitation_stub_check.py`** — §4.7's checks on CPU,
   output pasted back into this file. **This is the gate on GPU spend.** *(T3 — check
   7's four-layer gate cases are the ones not to hand-wave.)*
7. **Pilot and Stage-1 configs plus two runlists** — four `pilot_*.config.json`, three
   `decomp2_*.config.json`, `hole-elicitation-pilot-runlist.json` and
   `hole-elicitation-runlist.json`; byte-copies of the banked `decomp-*` configs with
   only the §4.2/§4.3 fields changed, `pruners` pinned, all validating. Plus
   **`experiment/pilot_select.py`**, which reads Stage 0's records and prints the E1/E2
   verdicts and the selected block per §4.2's rule — so the selection is executed, not
   judged. *(T2 for the configs; the selector is T2 and its rule is fully written.)*
8. **Two back-pointers** — two lines in 2026‑08‑25 §6 row 4 naming this file as the
   document that discharged the row, and a short addendum in the 2026‑08‑26 report
   recording §1.1's and §1.2's corrections to its prose (no number changes). *(T1 —
   mechanical, and the text is written above.)*
9. **`docs/results/2026-08-2X-hole-elicitation-report.md`** — the pilot's gate verdicts
   and, if it launches, Stage 1's arms, primary with attribution gate and clustering
   sensitivity, hand-scored secondaries with intervals, the §4.6 telemetry including
   the gate accounting, the §6 row that fired, cost and teardown evidence. *(T3.)*

Deliverables 2–7 are CPU-only and gate the GPU spend. **Nothing launches until 6's
output is in this file.** Stage 1 launches only on Stage 0's gates, via 7's selector.

---

## 9. What would change this plan

- **No block clears E1** (§6 row 1). Elicitation is the finding; Stage 1 is not
  launched and the lever goes back to the plan owner.
- **E1 clears and E2 does not.** The mechanism is confirmed dead on structure rather
  than on elicitation; Stage 1 is not launched.
- **Only B3 clears E1.** The lever has changed identity — escalate rather than
  proceed (§6 row 3).
- **The exemplar block is found to leak.** §4.7 check 1c fails, or the Stage-0
  telemetry shows the exemplar's goal types copied into held-out drafts at a rate that
  makes the arm a memorization test. Fix the block or drop B1; do not launch Stage 1
  on a block whose blindness is not pinned.
- **`[mask-spine-refs]` lands a pruner and some config is found not pinning
  `pruners`.** A control has silently drifted; re-verify every config in both stages
  before launch. *(Inherited from 2026‑08‑25 §9, unchanged and still live.)*
- **The `whole` arm produces composed definitions at ≫ 4.7 %** under §4.3's settings.
  Then the banked baseline was not stable and the primary's baseline assumption is
  wrong; report it and re-power before reading anything into the treatment.
- **Someone produces a held-out semantic success on the whole-term harness at a
  *rate*, not as an existence proof.** Then the composition residual has moved
  underneath this plan and §1 must be re-derived before Stage 1 is worth running.

---

## 10. Stage 0 outcome — appended 2026‑08‑27, after the run

Stage 0 ran in full on 2026‑08‑26/27: four blocks × 16 cells, all four arms
`SUCCEEDED`. **No block clears Gate E1; §6 row 1 fires; Stage 1 is not launched.**
`pilot_select.py` exited 2. Full verdicts, §4.6 telemetry, and teardown evidence:
[2026‑08‑27 hole-elicitation pilot report](../results/2026-08-27-hole-elicitation-pilot-report.md).

Three things this file said in advance, checked against what happened:

- **§9 row 1 fired, not row 2.** E2 is not independently informative here: 31 fill
  draws were attempted and **none** was spliced, so the assembly stage E2 evaluates
  was never reached. §1.2's blame test has an empty population under treatment and is
  **not** discharged by this run.
- **§1.3's prediction held.** The relaxed `well-scoped` gate reached fills in all
  four blocks where `accepted` would have reached none, and contributed **zero**
  composed definitions. Row 4's remedy buys mechanism exposure only, as written.
- **§9's exemplar-leak row did not fire.** Neither exemplar goal type (`Bool`,
  `Maybe`) appears in any B1 hole; n = 6, so this is weak evidence of absence rather
  than a clean bill.

### Deviation filed under §4.8 — Spot → on-demand, ≈ $3.45 against ≈ $1.30

Two launch attempts (21:20:30Z, 23:47:05Z) applied cleanly but returned
`instance_name = ""` — no preemptible L4 capacity in us‑central1‑a. The third
(23:52:42Z) used `--on-demand` and got an instance. Cost was ≈ $3.45 rather than the
pre-registered ≈ $1.30, at $0.85/h for ≈ 4.0 h. **Cost only, not validity**: same
`g2-standard-4 L4 24GB` hardware string, same model identity, no §4.2 quantity
touched. Filed here as well as in the deliverable-9 report, per §4.8.
