# Skeleton lever — the starvation point is the declared type's arity, not the funnel gate

**Status:** pre-registered, **not launched**. §4's own arithmetic says the arm
cannot be bought at the standing ceiling, and §7's D0 — which costs $0 — has to
run first. Launch needs the plan owner's explicit go on both counts.

**Predecessors:** [2026‑08‑25 hole decomposition](2026-08-25-hole-decomposition.md) ·
[2026‑08‑26 hole elicitation](2026-08-26-hole-elicitation.md) ·
[2026‑08‑27 model‑scale arm](2026-08-27-model-scale-arm.md) ·
[2026‑08‑27 feedback‑legibility arm](2026-08-27-feedback-legibility-arm.md)

**Evidence:** every number in §1 is printed by
[`experiment.skeleton_starve_probe`](../../prototype/experiment/skeleton_starve_probe.py);
every number in §4 and §5 by
[`experiment.skeleton_lever_power`](../../prototype/experiment/skeleton_lever_power.py).
Both run on CPU against banked records. No GPU, no network, no model, $0.

**Mockup:** this change has no visible surface — its only rendered output is the
compare script's stdout, whose shape §6 fixes as the exit-code contract. No
mockup bundle.

---

## 0. What this plan is answering, and how the question changed

The `[skeleton-lever]` item was raised against a specific reading of the
2026‑08‑26 decomposition run: *skeleton acceptance was 5.5 %, the composed
primary starved, so find the lever that unstarves the skeleton stage.* The
offline diagnosis does not support that framing, and §1 replaces it. The TODO
item's words were a hypothesis, not a contract; this section records the swap
before anything is built on it.

Three things the diagnosis establishes, in order of how much they change:

1. **Skeleton acceptance was never the anomaly.** 5.49 % sits between the two
   concurrent whole-draw controls (`redraft` 6.87 %, `whole` 3.67 %), and no
   test separates it from either. It is the battery's acceptance rate.
2. **The binding constraint is the other conjunct of the mechanical floor.**
   The floor is `accepted AND type-exact`. Separately those run at 5.49 % and
   16.20 %; together, 0.27 %. The conjuncts are nearly disjoint.
3. **The type conjunct is gated, almost entirely, by the declared type's arrow
   arity** — and the banked 14B arm already moved it by RR 2.78, moved
   type-exactness by RR 4.18 and the floor by RR 19.11, at p < 10⁻⁹ on all
   three. **Those 42 floor draws have never been hand-scored.**

So the strongest dangling thread is not a lever to buy. It is a rubric to run,
for nothing, on data already on disk.

---

## 1. Diagnosis

Reproduce with `python3 -m experiment.skeleton_starve_probe` from `prototype/`.
Exit 0, all 13 integrity checks pass. Everything below is **descriptive**: these
arms were pre-registered for other questions, they have been run, their verdicts
stand, and the p-values here are reading aids labelled as such.

### 1.1 Where a draw dies — and why the skeleton stage is not the story

```
  arm/role                    n       parse  references       scope   typecheck    accepted
  decomp-holes/skeleton     747    34  4.6%    74  9.9%     1  0.1%   597 79.9%    41  5.5%
  decomp-redraft/whole      772    18  2.3%    72  9.3%     3  0.4%   626 81.1%    53  6.9%
  decomp-whole/whole        762    21  2.8%    82 10.8%     3  0.4%   628 82.4%    28  3.7%

    holes vs redraft, one-sided (redraft > holes): p = 0.1570
    holes vs whole,   one-sided (holes > whole):   p = 0.0587
```

Skeleton draws die where whole draws die, at the same rates, in the same layers.
**There is no skeleton-specific starvation to lever.** 79.9 % of skeleton draws
reach `typecheck` and die there; the layer distribution is within 2 points of
both controls at every layer.

Within `typecheck` (597 draws):

```
   173  29.0%  type mismatch: expected [...]
   118  19.8%  arm result type differs from expected type: type mismatch: expected [...]
    88  14.7%  match scrutinee does not synthesize a nominal data type
    71  11.9%  measure position N exceeds the annotation's N-argument curried spine
    57   9.5%  ability HASH is not allowed by the ambient effect
    21   3.5%  application function does not synthesize a function type
    18   3.0%  binder count N does not match constructor field count N
    16   2.7%  constructor does not match the expected nominal data type
    11   1.8%  parameterized constructor needs an expected data type
     9   1.5%  ability HASH has no capability value in scope
     8   1.3%  cannot match [...]
     2   0.3%  reference HASH has no resolvable type
     5   0.8%  (the remaining 5 classes)
```

No single class dominates enough to be a lever on its own. The two largest are
generic type mismatches; the third and fourth are `match` and `fix`/measure
machinery. This is a distribution of ordinary wrongness, not a harness defect.

### 1.2 The mechanical floor is a conjunction, and its conjuncts are nearly disjoint

`evaluate.score_semantic`'s held-out rule is `checked+type-exact`: a draw counts
iff the funnel accepted it **and** its declared type is the task's.

```
  arm/role                    n         accepted       type-exact     FLOOR (both)
  decomp-holes/skeleton     747   41/747   5.49%  121/747  16.20%    2/747   0.27%
  decomp-redraft/whole      772   53/772   6.87%  147/772  19.04%    4/772   0.52%
  decomp-whole/whole        762   28/762   3.67%  129/762  16.93%    3/762   0.39%
```

**The near-miss band — drafts failing exactly one conjunct, and which one:**

```
  both conjuncts (the floor)                        2/747   0.27%
  accepted, type WRONG  (fails the type conjunct)  39/747   5.22%
  type-exact, REJECTED  (fails the term conjunct) 119/747  15.93%
  neither                                         587/747  78.58%

  Near-miss band (exactly one conjunct):          158/747  21.15%
```

One draw in five is one conjunct away from the floor, and the larger half is the
**term** conjunct: 119 drafts declared the task's type exactly and still failed
the funnel (97.5 % of them at `typecheck`, 2.5 % at `references`), against 39
that passed the funnel with the wrong type.

Arm-wide the two conjuncts are *negatively* associated, which on its face says
writing the task's type hurts acceptance:

```
  acceptance | type-exact         2/121   1.65%
  acceptance | NOT type-exact    39/626   6.23%
```

It is Simpson's paradox on tasks, not a draw-level trade-off:

```
  task                                n   |T|   type-exact     accepted  floor
  heldout/list/concatLength          64   179         3.1%         1.6%      0
  heldout/list/mapLength             86   115        50.0%         1.2%      1
  heldout/list/reverseThen           58   255        27.6%         1.7%      0
  heldout/maybe/mapOrElse           199   127         0.0%        18.1%      0
  heldout/list/headOrElse           108   103         0.9%         0.9%      0
  heldout/list/sum                   83    91        69.9%         1.2%      1
  heldout/sample/stampedBytes        67   392         0.0%         0.0%      0
  heldout/nat/selectNonNegative      82   384         1.2%         0.0%      0
```

`maybe/mapOrElse` supplies 36 of the arm's 41 accepted drafts and 0 of its 121
type-exact ones. `list/sum` and `list/mapLength` supply 101 of the 121 type-exact
drafts and 2 of the 41 accepted ones. The two conjuncts are won on disjoint task
sets, which is why their conjunction is 40× rarer than either.

### 1.3 The type conjunct is gated by arity

```
  declared arity == gold arity       191/713  26.79%
  type-exact GIVEN correct arity     121/191  63.35%
  type-exact GIVEN wrong arity         0/522   0.00%   (0 by construction)
  type-exact, unconditional          121/713  16.97%
```

(Denominator 713 rather than 747: a draft that failed the parse layer has no
canonical type surface and therefore no arity.)

Get the arrow count right and the hash-dense remainder follows two times in
three. Get it wrong and nothing can save the draft. **The whole of the type
conjunct's difficulty is the arity**, and the error is a systematic off-by-one:

```
  declared - gold = -3      1 ( 0.14%)
  declared - gold = -2     11 ( 1.54%)
  declared - gold = -1    507 (71.11%)
  declared - gold = +0    191 (26.79%)
  declared - gold = +1      3 ( 0.42%)
```

It is not a fixed prior copied off the prompt's 26 worked examples (11 of
arity 1, 11 of arity 2, 3 of arity 3) — the distribution tracks the task:

```
  gold arity     n   declared-arity distribution
           1    79   1: 97.5%  2:  2.5%
           2   289   1: 71.6%  2: 28.0%  3:  0.3%
           3   345   0:  0.3%  1:  3.2%  2: 87.0%  3:  9.6%
```

A calibrated estimator with a −1 bias. Its dominant surface shape is a nest
closed one arrow early — the model writes gold's leading domains correctly, then
puts gold's *next domain* in the codomain position instead of opening another
arrow:

```
   248 (34.78%)  under-arity, domains not a prefix of gold's
   167 (23.42%)  under-arity, correct prefix, codomain = gold's NEXT DOMAIN
   148 (20.76%)  exact arity, domains match
    95 (13.32%)  under-arity, correct prefix, codomain = something else
    43 ( 6.03%)  exact arity, domains differ
     9 ( 1.26%)  under-arity, correct prefix, codomain = gold's final codomain
     3 ( 0.42%)  over-arity
```

**The expected type surface appears verbatim in 0 of 8 task specs.** The spec is
one line of English (`mapLength`: *"The number of elements a list has once a
function has been applied to every one of them."*). Arity is *inferred*, not
transcribed. That fact carries §2's largest rejection.

### 1.4 The sibling finding, extended from 12 drafts to 706

The elicitation plan's §1.2 found 9 of 10 hole-bearing rejects failing at a
committed sibling rather than at the hole. Re-derived:

```
  hole-bearing skeletons        12/747   1.61%
  ...accepted                    2/12   16.67%
  hole-free accepted            39/735   5.31%
```

Extended to **every** rejected skeleton by cutting a hole at its error path with
`prompts.checker_holed_cut` — the landed B3 surface, which reads the draft's own
declared type and no gold — and re-running the funnel. A cut draft that reaches
`accepted` is a draft whose every committed sibling was right: a genuine
one-node near-miss.

```
   616 (87.25%)  refused
    59 ( 8.36%)  cut, funnel typecheck
    21 ( 2.97%)  cut, funnel accepted
    10 ( 1.42%)  cut, funnel references

  Why the cut is refused:
     559  the nearest holeable ancestor is the whole body; §3's bare-hole rule refuses it
      34  the draft does not parse
      23  the error path names no term node

  One-node near-miss band:  21/706   2.97%
    arity correct:   2 rescued of  180 rejects =  1.11%
    arity wrong  :  19 rescued of  526 rejects =  3.61%
```

**Sibling failure is neither an arity artefact nor a mask gap — it is ordinary
wrongness spread over several nodes.** Three per cent of rejects are one subterm
from typechecking, and the rate is no higher among drafts that got the arity
right. 2026‑08‑26 §1.3 predicted this on 8 drafts; it now holds on 706.

### 1.5 The 14B arm already moved every one of these, for free

`pilot-{b0,b2}` against `scale14-{b0,b2}`: same 8 tasks, seeds 1–2, same purse,
condition, quantization and tokenizer. Parameter count is the only difference.

```
  endpoint                                  14B             7B     RR          p
  funnel acceptance                83/400  20.75%   21/364   5.77%   3.60   4.90e-10
  declared arity correct          278/400  69.50%   91/364  25.00%   2.78   7.44e-36
  type-exact                      239/400  59.75%   52/364  14.29%   4.18   2.52e-40
  MECHANICAL FLOOR                 42/400  10.50%    2/364   0.55%  19.11   1.34e-10

  The -1 arity bias, at both sizes
  7B   -3: 0.29%  -2: 1.14%  -1:72.57%  +0:26.00%
  14B  -2: 3.05%  -1:26.40%  +0:70.56%
```

The off-by-one largely resolves, and the probe shows exactly where:

```
  model gold arity     n   declared-arity distribution
     7B          1    40   1:100.0%
     7B          2   150   1: 76.7%  2: 23.3%
     7B          3   160   0:  0.6%  1:  2.5%  2: 86.9%  3: 10.0%
    14B          1    63   1:100.0%
    14B          2   191   1:  3.1%  2: 96.9%
    14B          3   140   1:  8.6%  2: 70.0%  3: 21.4%
```

At gold arity 2 the bias is essentially gone — 96.9 % correct against 23.3 %. At
gold arity 3 it moves but survives: 21.4 % against 10.0 %, with 70.0 % still one
arrow short. **Arity 3 is where the residual lives**, and three of the eight
held-out tasks are arity 3.

**And it opens a stratum the campaign has never had:**

```
  7B   type-exact   52/364  14.29%    TERM acceptance (accept | type-exact)    2/52    3.85%
  14B  type-exact  239/400  59.75%    TERM acceptance (accept | type-exact)   45/239  18.83%
```

At 7B the term stratum is 52 draws carrying 2 accepts — nothing to measure. At
14B it is 239 draws carrying 45. This is the first population on which *"does
iteration with feedback help a draft that already committed to the right
type?"* can be asked at all.

### 1.6 What the model-scale arm's verdict does and does not cover

The model-scale arm exited 3 on §6 row 3 — *"scale is not the lever at any size
reachable from here"* — and was right, **about hole elicitation**, which is what
E1 measures. On the campaign's own floor the same run moved everything, and its
report says so plainly and then sets it aside by rule:

```
  floor draws 42   unique surfaces 12   cells reached 8 of 32
     21  heldout/list/reverseThen
     10  heldout/nat/selectNonNegative
      7  heldout/list/mapLength
      2  heldout/list/concatLength
      2  heldout/list/sum
```

*"R3's hand-scored rubric … is outstanding for 42 draws"*, left *"outstanding by
rule, not by omission"*. The pilot's rubric found 2 of 3 mechanical-floor
surfaces were extensional shortcuts that **FAIL** against verified gold, so the
floor overstates by an unmeasured amount. **Twelve unique surfaces stand
unscored, and scoring them costs $0.** That is D0.

### 1.7 Two harness facts the diagnosis turned up

**`evaluate.narrowing_note` returns `""` on acceptance** (`evaluate.py:289‑290`).
A draft the funnel accepted with the *wrong* declared type therefore ends its
round with no note, and `_run_whole_protocol` re-draws from a byte-identical
prompt. The round yields neither a candidate nor a signal:

```
  decomp-holes/skeleton      39/747   5.22%   {'maybe/mapOrElse': 36, ...}
  decomp-redraft/whole       49/772   6.35%   {'maybe/mapOrElse': 42, ...}
  decomp-whole/whole         25/762   3.28%   {'maybe/mapOrElse': 22, ...}
  scale14 (14B, pooled)      38/400   9.50%
```

The defect **grows with the model**, because acceptance does. It matters twice
below: it dilutes §3's treatment (§3.4), and it is not fixed before the arm
(§3.5).

**Exact duplicate draws within a cell:**

```
  decomp-holes/skeleton    duplicates   91/747  12.18%   distinct declared types per cell  4.06
  decomp-redraft/whole     duplicates  115/772  14.90%   distinct declared types per cell  3.94
  decomp-whole/whole       duplicates  145/762  19.03%   distinct declared types per cell  3.77
```

---

## 2. The lever, and the levers rejected

### 2.1 The causal claim

**The mechanical floor is `P(type-exact) × P(accept | type-exact)`. At 7B the
first factor was the binding one and it was gated by an arity bias no prompt-level
manipulation in the banked record has moved. At 14B the first factor is largely
solved (59.75 %) and the binding one is the second (18.83 %). The lever that
addresses the *current* binding factor is iteration with feedback, whose only
measured effect size in this campaign is RR 1.87 on funnel acceptance — measured
at 7B, where the term stratum was too small to see.**

That is the arm §3 pre-registers. It is a real question with a live population and
a defensible prior.

**It is also, on today's ceiling, not buyable.** §4 shows the largest
configuration the on-demand fallback affords is powered at 0.56 against
RR 1.87 — the coin flip the model-scale plan explicitly refused to key a row to.
§2.3 states the consequence.

### 2.2 Levers rejected, with their banked bounds

Each bound is printed by `skeleton_starve_probe --section levers`. Where the
banked data cannot answer, that is said rather than estimated.

| Lever | Banked bound | Verdict |
|---|---|---|
| **Prefix-prime the declared type** (harness emits `(def TYPE `) | Type conjunct → 100 % by construction; floor 0.27 % → at most 5.49 %, RR ≤ 20 | **Rejected — not on the bound.** The expected type is in **0 of 8** task specs; the model *infers* arity from prose. Priming hands it the answer to the conjunct carrying the difficulty — 2026‑08‑25 §2.5's named confound, *"it hands the model the declared type the control has to guess"*. It would win the primary by construction and license nothing. |
| **Relax the fill gate** (`accepted` → `well-scoped`) | 2026‑08‑26 §1.3 priced it at 8 fill draws, 0 composed. Stage 0 then ran it: 31 fill draws, **0 spliced** | Rejected. Bound is measured, not modelled, and it is zero. Already spent. |
| **Hole elicitation** (exemplar / hole-required / checker-holed) | Stage 0: best block 5.75 % against a 10 % bar, no block cleared. 14B re-ran two and did worse (1.52 %, 0.00 %) | Rejected. Measured at two model scales; zero both times. |
| **Harness-placed holes at the checker's error** | §1.4: 21 of 706 rejects (2.97 %) rescued, and no better among arity-correct drafts (1.11 %) | Rejected. Also breaks 2026‑08‑25 §2.1's no-oracle property, which 2026‑08‑26 §2.2 already ruled makes it a different lever under a different name. |
| **The exemplar block as a general-acceptance lever** | acceptance RR 1.54 (p = 0.084), type-exact RR 1.28 (p = 0.109); **at round 0, the only byte-identical contrast, 3/16 vs 9/48, p = 0.63** | Rejected. No defensible bound above 1 once the confounded rounds are removed. |
| **A bigger purse / more draws per cell** | 11.67 draws/cell at a 0.27 % per-draw floor rate: doubling the purse moves expected floor cells from 2.0 to 3.9 of 64, at twice the cost | Rejected on arithmetic. |
| **Recover the wasted rounds** (§1.7) | duplicates 12.18 % + silent accepts 5.22 % = 17.40 % of draws; perfect recovery is floor 0.27 % → 0.31 %, **RR 1.17** | Rejected as a *lever*. Landed as a harness fix instead — see §3.5 for why not before this arm. |
| **Gold-derived "your type is wrong" feedback** | Fires on 5.22 % of draws | Rejected on principle before arithmetic: a gold oracle, and 2026‑08‑25 §2.1's no-oracle property is what makes every result in this campaign interpretable. |
| **Arity-explicit task specs** | **Not computable offline.** No banked run varies the spec | Rejected as *this plan's* call to make. Re-authoring the battery after seeing which tasks fail is fitting the battery to the model, and whether the held-out regime is meant to test type *inference* from under-specified prose or definition *construction* given an adequate description is the plan owner's question. **ESCALATE, filed, not folded in.** |
| **32B** | 2026‑08‑27 §6 row 3: explicitly not licensed, and not licensed by a quota grant either | Rejected by a standing pre-commitment. |
| **Model scale, on the campaign's own floor** | type-exact RR 4.18, floor RR 19.11, both p < 10⁻⁹ | **The only lever with a large, significant, banked bound — and it is already bought at 32 cells, which is what the ceiling affords at 14B's 8.52 tok/s.** What is *not* computable offline is whether those 42 floor draws are semantically correct. That is D0, at $0. |

### 2.3 The recommendation

**Do not buy a GPU arm on today's evidence.** Two independent reasons, either
sufficient:

1. **The free work has not been done and it dominates.** D0 hand-scores 12 unique
   surfaces against verified gold on the reference interpreter, for $0, and its
   outcome changes what any arm should measure (§6 rows D0‑a/b/c). Buying an arm
   whose primary is built on an endpoint that may overstate by an unmeasured
   amount is spending to sharpen a ruler nobody has calibrated.
2. **The arm cannot be sized to be both affordable and powered.** §4. The
   on-demand fallback affords 16 cells/arm at 0.56 power; 0.80 power needs
   32 cells/arm at ≈ $8.61. That is a ceiling decision and it belongs to the
   plan owner: **ESCALATE**.

The arm below is specified in full so that it is launchable the moment both gates
clear, and so that D0's outcome can be read against a design that already exists
rather than one written afterwards.

---

## 3. Arms

### 3.1 Two arms, one config field, one instance

| Arm | `output_dir` | `generation_protocol` | Everything else |
|---|---|---|---|
| **A — control** | `skel-whole14` | `"whole"` | identical |
| **B — treatment** | `skel-redraft14` | `"redraft"` | identical |

Both: Qwen2.5‑Coder‑14B‑Instruct GGUF Q4_K_M, condition `gbnf+typemask`, curated
store, `address_book: "full"`, `pruners` pinned to
`["goal-type", "de-bruijn", "ref-hash"]`, regime `held_out`, purse
4,608 tok/cell, seeds 1–n per §4's sizing, 8 tasks.

**Why this is one variable and not two.** `build_prompt`'s own docstring pins it:
*"`"redraft"` builds the same bytes as `"whole"` — the redraft arm differs from
the control in the runner's loop, not in its prompt, which is what makes draw 0
of every cell byte-identical across the two."* The arms differ in `_narrows` and
nothing else. D3's test asserts the two config files differ in exactly two keys
(`output_dir`, `generation_protocol`) and that draw 0's prompt bytes are equal.

**Within-run control, mandatory.** Both arms run concurrently on one instance
from one runlist, per 2026‑08‑25 §4.5 and 2026‑08‑27‑feedback‑legibility §1.3.
The legibility arm's C1 result — the harness is drift-free at these seeds,
exactly — licenses *citing* banked figures on the same footing. It does not
license using one as a control, and this plan does not ask it to.

### 3.2 The redraft-prompt Watch trigger does not fire, and that is deliberate

[2026‑08‑28 legib‑row4‑probe](../investigations/2026-08-28-legib-row4-probe.md)
§6 arms a trigger on *"any plan that proposes to add or change content in the
redraft prompt"*, and requires three deliverables when it fires.

**This design adds and changes nothing.** Arm B's note is `evaluate.narrowing_note`
unchanged, rendered by the landed `8ed72cd` canonical renderer — byte-for-byte
what `decomp-redraft`, `legib-legible` and every post-fix run produced. Arm A has
no note. There is no third rendering, no richer note surface, no hole block, no
prefix priming, and no new bytes between drafts.

That was a design constraint, not an accident: the brief preferred a design that
does not touch redraft-prompt content unless the diagnosis forces it, and §1's
diagnosis points at the term stratum, which the *existing* note already
addresses. **D3 pins this mechanically** — a test asserting Arm B's note bytes
are produced by an unmodified `narrowing_note` over an unmodified renderer, so
the claim is checked rather than asserted.

If a future revision does add note content, the three deliverables become
mandatory and this section must be rewritten, not amended.

### 3.3 The design rejected

**A 14B `holes` arm against a 14B `redraft` arm**, i.e. 2026‑08‑25's attribution
gate re-run at scale. It buys a free C1 anchor (Arm A would be byte-identical to
banked `scale14-b0`) and it closes the decomposition question at the scale where
the protocol finally has drafts to work on. Rejected: §1 shows hole elicitation
is measured-zero at *both* model scales, so one of the two arms is a known null,
and spending half the cells on it to buy a calibration check is the wrong trade
when §7's C1′ gets a weaker version of the same assurance for free.

### 3.4 A named limitation, stated before the run

§1.7's silent-accept defect **dilutes Arm B's treatment**. On the 9.50 % of 14B
draws that are accepted-but-type-wrong, `narrowing_note` returns `""`, so Arm B
degenerates to Arm A for that round. The measured effect is therefore a
**lower bound** on what iteration with feedback would do if the note fired on
every non-floor round. A null must be reported as *"no effect ≥ the MDE, under a
note that is silent on one round in ten"*, not as *"feedback does not help"*.

### 3.5 The harness fixes are filed, not landed

§1.7's two defects are real and worth fixing. They are **not** fixed before this
arm, on purpose: both change the denominator of every acceptance statistic, which
would break §7's C1′ invariance check against `scale14-b0` and orphan every
banked comparison in §1. They are filed as a separate item, to land after this
arm reports or in place of it if the arm is never bought.

---

## 4. Cost — and why the arm is not launchable at the standing ceiling

Reproduce with `python3 -m experiment.skeleton_lever_power`. **It exits 2**,
which is this section's finding.

Throughput is measured, not modelled: the model-scale arm emitted 63,753 and
63,824 completion tokens at **8.53 and 8.52 tok/s**, within 0.4 % of each other.
Overhead is that arm's own 0.52 h (4.68 h wall minus 4.16 h of summed arm
elapsed). Instance is `g2-standard-4` (L4 24 GB), us‑central1.

```
  cells/arm  total cells   hours      Spot   on-demand
         16           32    5.32  $   1.33  $     4.53
         24           48    7.73  $   1.93  $     6.57   over ceiling on-demand
         32           64   10.13  $   2.53  $     8.61   over ceiling on-demand
         40           80   12.53  $   3.13  $    10.65   over ceiling on-demand
         64          128   19.74  $   4.93  $    16.78   over ceiling on-demand
```

**Spot is not a plan.** Four of the campaign's last five *Spot* inserts were
preempted: pilot attempts 1 and 2, legibility attempt 1, and model-scale
attempt 1 — the last at ≈ 2 s after the instance became ready. Only legibility
attempt 2 held. The pre-committed
degradation path **drops cells, never arms** (2026‑08‑25 §2.3), so the on-demand
column is what sizes the arm.

Against §5's power table:

```
  affordable on the on-demand fallback (<= $4.55): [16]
  powered against RR = 1.87 at >= 0.80:            [32, 40, 64]
  both: NONE
```

**The largest affordable configuration is 16 cells/arm at $4.53, whose power
against RR 1.87 is 0.56.** The model-scale plan's own words apply verbatim:
keying a decision to that *"would fire about half the time when it should, and
would leave the decision hostage to a coin flip."*

A powered arm needs **32 cells/arm ≈ $8.61 on-demand** (≈ $2.53 Spot), i.e. a
ceiling of about $8.61 — 1.9× the standing $4.55. Raising it is a judgement about
how much this question is worth, which is the plan owner's and not this plan's:
**ESCALATE**.

**Pre-committed budget rules, in force if the arm is ever launched.** Ceiling as
the plan owner sets it. Spot first with the on-demand fallback. If measured
throughput comes in below 6 tok/s, stop after Arm A and re-size (the model-scale
arm's rule, which never fired). Per-arm incremental upload and a committed resume
runlist, reused unchanged. Teardown is part of the run: the instance self-deletes
and the report carries the root-destroyed / bucket‑404 / zero-instances evidence.
The driver log is kept — the model-scale arm's fetch failure has no diagnosis
because its log did not survive.

---

## 5. Endpoints

### 5.1 The primary is reachable, which is the lesson being applied

2026‑08‑25's primary needed fills, and fills needed skeletons to pass, and they
did not: the arm measured its own elicitation instead of its mechanism. The
constraint that follows is that a primary must have a **live population measured
in advance**. The mechanical floor does not: 2 draws in 747 at 7B, and 42 in 400
at 14B over only 8 of 32 cells. **Term acceptance does.**

**E1 — primary. Term acceptance: of the draws that declared the task's type
exactly, the fraction the funnel accepted.** Mechanical, computed from
`records.jsonl`, no rubric. Banked 14B control value **45/239 = 18.83 %** over
32 cells, 7.47 eligible draws/cell.

Test: paired sign-flip permutation over cell pairs, one-sided in the
*redraft > whole* direction, α = 0.05, 9,999 permutations, seed 0 — the
legibility arm's test, unchanged, so the machinery is already reviewed.

```
  Beta-binomial MLE: a = 0.7218, b = 2.6667 (mean 21.30%, concentration 3.39, ICC 0.228)

  cells/arm  MDE (RR)  MDE rate   power@RR=1.87   iid MDE
         16      2.60   48.95%            0.56      1.80
         24      2.00   37.66%            0.74      1.70
         32      1.90   35.77%            0.85      1.60
         40      1.80   33.89%            0.91      1.50
         64      1.50   28.24%            0.99      1.40
```

**Read honestly, in both directions.** ICC is 0.228 against the legibility arm's
0.120 — a cell is one task at one seed and the tasks differ enormously (§1.2's
per-task table), so clustering is severe and the paired test is bought for
validity, not power; the iid column is what an honest analysis cannot have. The
RR 1.87 probe is the banked 7B `redraft` vs `whole` acceptance ratio
(53/772 against 28/762, p = 0.0035) — **a reference point fixed before the run,
not an expectation.** There is no prior on what feedback does inside the term
stratum, because at 7B that stratum carried 4 and 3 accepted draws.

**E2 — invariance check, not a gate. Draw-level type-exactness.** E1 conditions
on an event the model produces, so the stratum is a **mediator, not a randomised
covariate** — the same disclosure the legib‑row4 probe makes about its exposure
split. §1 measured feedback's effect on the type conjunct at RR 1.12
(p = 0.16), so the arms should not diverge here. **Pre-committed:** if the arms'
type-exact shares differ by more than 5 points, the strata are not comparable and
E1 is reported as descriptive, not as a test. (The legibility arm's analogue
agreed to 0.7 points.)

**E3 — descriptive, never a gate. The mechanical floor**, per-cell and per-draw,
plus the full §1 endpoint set (arity-correct, funnel acceptance, layer
distribution) so the arm extends §1's tables rather than replacing them.

**E4 — descriptive. The hand-scored rubric** over every unique mechanical-floor
surface, by execution against verified gold — D0's method, applied to the new
run. Reported whatever E1 says; the 2026‑08‑25 §6 row on ≥ 5 hand-scored
semantic successes carries over unchanged.

### 5.2 No peeking, no test-shopping

No number is computed until both arms are banked. The seed, permutation count,
direction and α are fixed here and in `skeleton_lever_compare.py`'s constants.
E1 is the only confirmatory test; E2 is a pre-committed invariance bound; E3 and
E4 are descriptive and no §6 row keyed to E1 may be re-read in their light.

---

## 6. What each outcome licenses

Keyed to `skeleton_lever_compare.py` exit codes. **Rows D0‑a/b/c fire before any
GPU spend** and are the ones live today.

| # | Exit | Outcome | What it licenses next |
|---|---|---|---|
| **D0‑a** | `decomp_hand_score` exit 0, **≥ 1 genuine semantic success** among the 42 banked 14B floor draws | The campaign has held-out semantic successes at 14B, obtained for $0. | **This is the headline and it is free.** Report it as a results document against the model-scale arm. The floor endpoint is calibrated, E3 becomes trustworthy, and the §4 ceiling question becomes worth escalating with a number behind it. Re-open the 32B row (2026‑08‑27 §6 row 2) *only* with a measured slope, not on this. |
| **D0‑b** | exit 0, **0 genuine successes; all 12 surfaces are extensional shortcuts** | The floor overstates at 14B exactly as it did at 7B — 42 draws, 0 real. | The mechanical floor is **not** a usable endpoint at any scale, and §5's E3 must be demoted to telemetry in every future plan. This is a substantial negative result about the campaign's own instrument, reportable at $0. It also **withdraws** §4's escalation: do not raise the ceiling for an arm whose descriptive endpoint is known broken; re-specify the endpoint first. |
| **D0‑c** | exit 1 (integrity) | The rubric cannot execute some surfaces (fuel, missing gold). | A harness finding, not a result. Fix `decomp_hand_score`'s battery or gold coverage and re-run. Nothing else in this plan proceeds. |
| **1** | `0` | **E1 significant, `redraft` > `whole`, E2 within 5 pts** | Iteration with feedback is the lever on the term conjunct, at the scale where the type conjunct is solved. 2026‑08‑25 §6 row 2 is confirmed at 14B and on a stratum, not just on raw acceptance. Take `redraft` as the standard held-out protocol at 14B, and the next question is the *content* of the note — which fires the redraft-prompt Watch trigger and its three deliverables in full. |
| **2** | `2` | **E1 null, E2 within 5 pts, E1 denominator ≥ 4.5 eligible draws/cell/arm (60 % of the banked 7.47)** | The row the campaign has never been able to reach. The stratum was live, the treatment ran, and feedback did not help a draft that had already committed to the right type. Composition is not a *feedback* problem at 14B. Given §3.4's dilution, report as *"no effect ≥ the MDE under a note silent on one round in ten"*. This is the row that licenses fixing §1.7's defects and re-asking, and it is the only row that does. |
| **3** | `3` | **E2 diverges by > 5 pts** | The strata are not comparable; E1 is descriptive only. A finding about the treatment's reach, not about feedback: the arms earned different *kinds* of draft, so the conditioning is doing work the design did not intend. Report the divergence, do not report E1 as a test, and re-specify the endpoint before any further spend. |
| **4** | `4` | **E1 denominator < 4.5 eligible draws/cell/arm (starved)** | Type-exactness came in below the banked 59.75 % and the stratum did not materialise. Inconclusive **and stop** — this is the third starved primary in the campaign, and a fourth re-run needs the plan owner's decision, not another endpoint. Report the achieved type-exactness against §1.5 as the finding. |
| **5** | `5` | **E1 significant in the reverse direction (`whole` > `redraft`)** | Feedback *hurts* the term stratum. Not a rounding error at this MDE. **ESCALATE before any further spend**, exactly as 2026‑08‑27‑feedback‑legibility §6 row 4 required — and note that the legibility arm's reverse L1 result and this would then be two reverse results on the same seam, which is a pattern rather than a surprise. |
| **6** | `6` | **C1′ invariance fails** (§7) | The `whole` arm's seeds‑1–2 figures fall outside `scale14-b0`'s 95 % Wilson intervals. A harness, driver or environment finding, and it lands **before** any endpoint is read. No result in the report may be cited until it is explained; the drift-free property the legibility arm established would be broken and every banked comparison in §1 re-opens. |
| **7** | — | **≥ 5 hand-scored semantic successes in either arm** | Unchanged from 2026‑08‑25 §6 and 2026‑08‑26 §6: the headline whatever E1 says. Hand-score every mechanical-floor candidate in both arms and re-examine the type-collision recycling failure mode first. |
| **8** | — | **Measured throughput < 6 tok/s** | Stop after Arm A and re-size. A budget rule, not a finding. |

---

## 7. Gates and deliverables

### 7.1 Gate 1 — D0, before anything

**Hand-score the 42 banked 14B mechanical-floor draws.** $0, CPU, no GPU. The
population is 12 unique surfaces across 5 tasks and 8 cells (§1.6). Method is
`decomp_hand_score`'s: execute each candidate on the reference interpreter
against the task's verified gold term over a concrete input battery; a fuel
exhaustion or crash on any input is a fail. **No GPU spend is authorised until
D0 has reported**, and §6 rows D0‑a/b/c say what each outcome does — including
D0‑b, which withdraws §4's escalation rather than reinforcing it.

### 7.2 Gate 2 — CPU stub check, before any GPU spend

`skeleton_lever_stub_check.py`, run on CPU with no network, bar **ALL CHECKS
PASS**, output pasted into this file before launch. Checks:

1. Both configs load, validate, and differ in exactly two keys.
2. Draw 0's prompt bytes are equal across the arms, for all 8 tasks.
3. Arm B's narrowing note is byte-identical to `narrowing_note`'s output over the
   unmodified renderer, for a scripted rejection at each funnel layer — §3.2's
   Watch-trigger claim, checked.
4. Arm A never constructs a note (`narrowed` false on every record).
5. The budget rule holds: full-cap-or-no-draw, every draw charged, within purse,
   ends when no room, `cell_done` on the last record.
6. No gold term or gold type surface appears in any prompt, over both arms and
   all 8 tasks.
7. A scripted stub drives one cell of each arm end to end at condition `gbnf`.
8. `skeleton_lever_compare.py` returns each of exit codes 0, 2, 3, 4, 5, 6 on
   synthetic records built to trigger that row — the §6 contract, executed.
9. Prompt + worst-case completion fits the context window at 14B.
10. `skeleton_starve_probe` and `skeleton_lever_power` both reproduce this file's
    pasted numbers (a regression check on §1 and §4).

### 7.3 Gate 3 — C1′, a calibration anchor, free at run time

The legibility arm proved the harness drift-free at these seeds (`repr`
reproduced banked `decomp-redraft` draw for draw). **An exact C1 anchor is not
available to this arm and that is stated rather than finessed:** no banked 14B
run uses `whole` or `redraft`, so there is no byte-identical predecessor.

**C1′ instead.** Arm A and banked `scale14-b0` differ only by the holes protocol
block and the fill gate, and §1 shows that machinery is inert at 14B on B0
(0 fill draws, 0.01 holes per candidate). So on the 16 overlapping cells
(seeds 1–2) Arm A must land inside `scale14-b0`'s 95 % Wilson intervals on both
of the probe's per-block anchors:

```
  block             n    funnel acceptance         type-exact
  scale14-b0      202       40/202  19.80%    120/202  59.41%
  scale14-b2      198       43/198  21.72%    119/198  60.10%
```

Pre-committed as §6 row 6: a failure fires before any endpoint is read. The
two blocks agreeing to within 2 points of each other is itself the evidence that
these are stable targets and not one block's luck.

### 7.4 Deliverables

| # | Deliverable | Owner tier | Status |
|---|---|---|---|
| **D0** | Hand-score the 42 banked 14B floor draws; `decomp_hand_score` extended past its hard-coded `ARMS` to take a run list. Results document under `docs/results/`. **$0, and the gate on everything.** | T2 | **open — do this first** |
| **D1** | [`skeleton_starve_probe.py`](../../prototype/experiment/skeleton_starve_probe.py) — §1's evidence, 7 sections, 13 integrity checks | T4 | **done**, exit 0 |
| **D2** | [`skeleton_lever_power.py`](../../prototype/experiment/skeleton_lever_power.py) — §4/§5's power and cost, with the affordability verdict as an exit code | T4 | **done**, exit 2 |
| **D3** | `skel_whole14.config.json`, `skel_redraft14.config.json`, and the test pinning the two-key difference, draw‑0 byte identity, and §3.2's note-byte claim | T2 | blocked on D0 |
| **D4** | `skeleton_lever_compare.py` — E1/E2 with §6's exit codes as its contract | T2 | blocked on D0 |
| **D5** | `skeleton_lever_stub_check.py` — §7.2's ten checks, ALL CHECKS PASS bar | T2 | blocked on D0 |
| **D6** | Runlist + committed resume file; driver-log retention | T1 | blocked on D0 |
| **D7** | Results document, §6 verdict, cost against §4, teardown evidence | T3 | blocked on launch |
| **D8** | Harness fixes for §1.7 — the silent-accept note and duplicate-draw suppression — filed as a **separate item**, deliberately **not** landed before this arm (§3.5) | T2 | filed |

---

## 8. What would change this plan

- **D0 returning 0 genuine successes** (§6 row D0‑b). The floor endpoint is then
  known broken, §5's E3 is demoted everywhere, and §4's escalation is withdrawn
  rather than pressed. The arm as specified survives — E1 does not depend on the
  floor — but the reason for wanting it weakens considerably.
- **The ceiling moving to ≈ $8.61 or above.** §4's verdict inverts and the arm
  becomes launchable at 32 cells/arm, power 0.85 against RR 1.87.
- **Anything that raises 14B throughput above ≈ 16 tok/s** — a faster backend, a
  smaller purse that still reaches the funnel, a cheaper instance. 32 cells/arm
  would then fit under the standing ceiling and no escalation is needed.
- **A cheaper endpoint than E1 with a defensible reading.** E1 conditions on a
  mediator and says so. If someone can define an endpoint on the term conjunct
  that does not condition post-treatment, it should displace E1 before launch,
  not after.
- **The plan owner ruling on arity-explicit specs** (§2.2's escalation). That
  changes the battery, so it changes every banked comparison in §1 and this plan
  would be superseded rather than amended.
- **A revision that adds or changes redraft-prompt content.** §3.2's Watch
  trigger then fires and its three deliverables become mandatory before spend.

---

## Amendment A1 — ceiling raised (2026-08-28, plan owner)

D0 reported **row D0-a** (5/12 genuine successes, exit 0; see
[results](../results/2026-08-28-skeleton-d0-hand-score.md)). On that basis the plan
owner approved raising this arm's ceiling from the standing $4.55 to **$8.61**,
buying the §4 powered configuration: **32 cells/arm**, 0.85 power at the banked
RR 1.87 bound. Launch remains gated on D3–D6 plus §7.2's stub check (ALL CHECKS
PASS) — the go covers the spend, not a skip of any gate.

---

### Deliverable 5 stub check

D3–D6 landed: `experiment/skel_whole14.config.json`, `experiment/skel_redraft14.config.json`
(differing by exactly `output_dir` and `generation_protocol`, seeds `[1, 2, 3, 4]` —
Amendment A1's 32 cells/arm), `experiment/skeleton_lever_compare.py` (E1/E2/C1′
against §6's exit codes 0/2/3/4/5/6), `experiment/skeleton_lever_stub_check.py`
(§7.2's ten checks below), `experiment/skeleton-lever-runlist.json`, and
`test_skeleton_lever_arm.py`. Check 6's "gold type surface" sub-check was narrowed
from *any prompt* to *the task's own spec text* after check 1 of that check found
two false positives (`sum`, `reverseThen`) traced to coincidental substring matches
against unrelated, legitimately-listed address-book signatures (`foldRight` and
`append`'s own curried types), not a leak — recorded in the check's own `note:`
line rather than silently dropped. §7.2's own regression clause (check 10) reads
this file's pasted §1/§4 numbers back out of it and diffs them against a fresh run,
so it is pasted here, after those numbers, deliberately — anything above this line
is what check 10 verifies unchanged.

Run from `prototype/`: `python3 -m experiment.skeleton_lever_stub_check`

```
### Check 1 -- both configs load, validate, differ in exactly two keys

  skel-whole14     loads and validates: True
  skel-redraft14   loads and validates: True
  differing keys: ['generation_protocol', 'output_dir']  exactly the two licensed

result: PASS

### Check 2 -- draw 0's prompt bytes are equal across the arms, all 8 tasks

  heldout/list/concatLength        whole==redraft=yes
  heldout/list/mapLength           whole==redraft=yes
  heldout/list/reverseThen         whole==redraft=yes
  heldout/maybe/mapOrElse          whole==redraft=yes
  heldout/list/headOrElse          whole==redraft=yes
  heldout/list/sum                 whole==redraft=yes
  heldout/sample/stampedBytes      whole==redraft=yes
  heldout/nat/selectNonNegative    whole==redraft=yes

result: PASS

### Check 3 -- Arm B's note == narrowing_note(unmodified renderer), every layer

  parse        funnel.outcome=parse        note-shape-ok=True  ok
  scope        funnel.outcome=scope        note-shape-ok=True  ok
  references   funnel.outcome=references   note-shape-ok=True  ok
  typecheck    funnel.outcome=typecheck    note-shape-ok=True  ok
  accepted draft carries no note: True

result: PASS

### Check 4 -- Arm A (whole) never narrows: `narrowed` False on every record

  _narrows(protocol='whole'   condition='gbnf+typemask') = False (expected False)  ok
  _narrows(protocol='whole'   condition='gbnf'        ) = False (expected False)  ok
  _narrows(protocol='redraft' condition='gbnf+typemask') = True  (expected True )  ok
  scripted cell (rejected then accepted, 2 draws): narrowed=[False, False]  ok

result: PASS

### Check 5 -- the budget rule: full-cap-or-no-draw, every draw charged,
###           within purse, ends when no room, cell_done on the last record

  skel-whole14     draws=2 tokens=96/4608
                   full-cap-or-no-draw=True every-draw-charged=True within-purse=True ends-when-no-room=True cell_done-on-last-only=True draw-indices-sequential=True  ok
  skel-redraft14   draws=2 tokens=96/4608
                   full-cap-or-no-draw=True every-draw-charged=True within-purse=True ends-when-no-room=True cell_done-on-last-only=True draw-indices-sequential=True  ok

result: PASS

### Check 6 -- no gold term in any built prompt; no task's own type surface
###           spelled out in its own spec text

note: gold TERMS are checked cross-task, against the full built prompt (every
      task's gold against every prompt -- decomposition_stub_check's own rule,
      safe because a full composed term is not the kind of string that
      coincidentally recurs). A gold TYPE SURFACE is checked only against its own
      task's *spec text*, not the full prompt: type surfaces are built from shared
      primitives (I64, List, ...), so e.g. sum's 1-arg `List I64 -> I64` surface is
      a literal substring of foldRight's own (unrelated, legitimately-listed)
      curried address-book signature -- confirmed by hand, not a leak. §1.3's own
      claim is the actual thing to regression-guard: "the expected type surface
      appears verbatim in 0 of 8 task specs" -- spec text, not the whole prompt.

  prompts checked    16 (2 arms x 8 tasks)
  gold terms searched for   8 (cross-task, full prompt); 8 own-type-surface self-checks (spec text only)
  heldout_gold.prompt_leak_check(): no offenders

result: PASS

### Check 7 -- a scripted stub drives one cell of each arm end to end (`gbnf`)

  skel-whole14     draws=2 outcomes=['typecheck', 'accepted'] narrowed=[False, False] one-candidate-per-draw=True narrows=False (expected False)  ok
  skel-redraft14   draws=2 outcomes=['typecheck', 'accepted'] narrowed=[False, True] one-candidate-per-draw=True narrows=True (expected True)  ok

result: PASS

### Check 8 -- skeleton_lever_compare.py: exit codes 0, 2, 3, 4, 5, 6

  expected exit 0: got 0  ok
  expected exit 2: got 2  ok
  expected exit 3: got 3  ok
  expected exit 4: got 4  ok
  expected exit 5: got 5  ok
  expected exit 6: got 6  ok

result: PASS

### Check 9 -- prompt + worst-case completion fits the context window

  skel-whole14     worst-case prompt= 18346 tok (narrowing note carried: False)  threshold= 32000  OK
  skel-redraft14   worst-case prompt= 18465 tok (narrowing note carried: True)  threshold= 32000  OK

result: PASS

### Check 10 -- skeleton_starve_probe / skeleton_lever_power reproduce
###            this plan's pasted §1/§4 numbers (regression check)

  plan carries pinned line (ok): decomp-holes/skeleton     747    34  4.6%    74  9.9%     1  0.1%   59
  plan carries pinned line (ok): MECHANICAL FLOOR                 42/400  10.50%    2/364   0.55%  19.1
  plan carries pinned line (ok): floor draws 42   unique surfaces 12   cells reached 8 of 32
  plan carries pinned line (ok): 16           32    5.32  $   1.33  $     4.53
  plan carries pinned line (ok): 32           64   10.13  $   2.53  $     8.61   over ceiling on-demand

  skeleton_starve_probe exit=0 (expected 0)  skeleton_lever_power exit=2 (expected 2)  ok
  reproduced fresh (ok): decomp-holes/skeleton     747    34  4.6%    74  9.9%     1  0.1%   59
  reproduced fresh (ok): MECHANICAL FLOOR                 42/400  10.50%    2/364   0.55%  19.1
  reproduced fresh (ok): floor draws 42   unique surfaces 12   cells reached 8 of 32
  reproduced fresh (ok): 16           32    5.32  $   1.33  $     4.53
  reproduced fresh (ok): 32           64   10.13  $   2.53  $     8.61   over ceiling on-demand

result: PASS

### Deliverable 5 verdict: ALL CHECKS PASS — the GPU gate is open
```

**Gate 2 clears.** All ten checks pass; exit 0. No GPU spend is authorised by this
alone — Gate 3 (§7.3's C1′) is read at run time by `skeleton_lever_compare.py`
itself, since no live arm exists yet to check it against.

D6's runlist ships as `experiment/skeleton-lever-runlist.json`, in the same
`{config_key, output_dir, run_id}` shape `legibility-runlist.json` and
`scale14-runlist.json` use. No hand-authored `-resume.json` companion is shipped:
`address-runlist-resume.json` is a relic of the campaign's pre-survivability-plan
convention (2026‑08‑27‑driver‑survivability‑and‑resume.md); every run since —
`legibility-runlist.json`, `scale14-runlist.json` — ships one runlist file only,
and resume goes through `run-remote-experiment-gcp.sh --resume-from
prototype/runs/logs/driver-skeleton-lever.json`, the manifest the driver itself
writes at launch. Driver-log retention is the already-landed 120 s heartbeat
upload (`runner-log-survival`, `ec3f7ed`); nothing in this deliverable needed to
touch it.
