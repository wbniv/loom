# Why §6 row 4 fired — an offline probe of the feedback-legibility arm's reverse L1 result

**TODO entry:** `[legib-row4-probe]`.
**Plan under investigation:** [2026‑08‑27‑feedback-legibility-arm](../plans/2026-08-27-feedback-legibility-arm.md),
§6 row 4 and the Deliverable 7 verdict record.
**Authorisation:** the plan owner authorised an offline investigation at **$0** — no GPU,
no cloud spend, banked data only. Nothing here cost anything.
**Visible surface:** none. This is an analysis script and a document; there is no UI, no
rendered page and no CLI a user drives, so the plan-mockup rule does not apply.

Everything below is **exploratory and post-hoc**. The arm pre-registered exactly one test
(§2.5), it has been run, and its verdict stands unchanged. Every p‑value in this document
is a descriptive aid to reading an effect that already fired — none of them is
confirmatory, and none of them is offered as a new claim about the world.

---

## 0. Reproducing every number

All figures cited here come from one deterministic script:

```
$ cd prototype
$ python3 -m experiment.legib_row4_probe                    # or --runs-dir <path>
```

`runs/` is gitignored, so from a worktree checkout pass
`--runs-dir /home/will/loom/prototype/runs`. Sections are selectable
(`--section headline --section rivals`); the full run takes ≈ 61 s, and its output is
byte-identical across runs (verified by `diff` on two consecutive runs). Exit code 0 when
every integrity check passes, 1 when one fails.

The script imports L1's predicate from `experiment/legibility_endpoints.py` — it never
re-derives it — and re-uses `legibility_power.fit_beta_binomial` for §6's power table.

---

## 1. Headline finding

**The reverse effect is real, it is caused by the note, and it is three times larger than
the verdict says — because the verdict averages it over a majority of repair steps the
seam could not touch.**

The `narrowing_note_render` seam can only change a note that embeds a rendered type. A
note reading *"measure position 1 exceeds the annotation's 1‑argument curried spine"* is
byte-identical under both renders. Replaying every rejected draw under **both** renderings
(the same replay deliverable 2 gated the arm on) splits L1's denominator cleanly:

| | legible | repr |
|---|---|---|
| L1-eligible pairs | 683 | 658 |
| …**exposed** (note bytes actually differed) | 284 = 41.58 % | 269 = 40.88 % |
| …**unexposed** (both arms saw the identical note) | 399 | 389 |

The two arms' exposure shares agree to within 0.7 pts, so the split is not itself an arm
difference. Stratifying L1 on it:

| Stratum | legible | repr | diff | post-hoc p (repr > legible) |
|---|---|---|---|---|
| all L1-eligible (**the verdict**) | 258/683 = 37.77 % | 263/658 = 39.97 % | −2.20 pts | 0.0215 |
| **exposed** | 39/284 = 13.73 % | 55/269 = 20.45 % | **−6.71 pts** | **0.0026** |
| **unexposed** (internal placebo) | 219/399 = 54.89 % | 208/389 = 53.47 % | +1.42 pts | 0.8836 |

Risk ratio in the exposed stratum: **0.672**.

The unexposed stratum is an internal placebo of exactly the right shape. Both arms
received a byte-identical note there; they differ only in the trajectory that got them to
it. It carries every source of between-arm divergence except the treatment — different
drafts, different histories, different prompts — and it is null on L1 (+1.42 pts,
p = 0.88), on acceptance (9.52 % vs 9.51 %), and on every landing category
(same-path 18.5 % vs 19.0 %, ancestor 11.3 % vs 11.8 %, elsewhere 33.8 % vs 34.7 %). The
whole effect sits where the treatment was live.

Decomposed against the repr arm as base, the −2.20 pt headline is **−1.91 pts of
within-stratum behaviour and −0.23 pts of composition** — i.e. the arms did not earn
different *kinds* of note, they behaved differently on the same kind. The pre-registered
endpoint therefore **understates** the treated effect by roughly 3.1×.

One honest caveat: which stratum a step falls in is determined by the draft the model
wrote, so the split is post-treatment. Empirically that costs nothing here — the exposure
shares differ by 0.7 pts and the composition term is −0.23 pts — but the split is a
mediator, not a randomised covariate, and is reported as such.

---

## 2. Was this a harness bug? No.

The escalation brief asked to be told immediately if today's verdict rested on a defect.
It does not. Section 0 of the probe checks, and all of it passes:

- **C1 re-asserted from the records, not from the verdict record**: the `repr` arm
  reproduces `decomp-redraft` draw-for-draw by `identity` — `True`.
- **The replay is exact**: 744/744 legible and 719/719 repr rejected draws reproduce their
  banked `error_message` from `source` under their own arm's render. Deliverable 2's gate
  still holds on this arm's own data, not just the banked one.
- **L1's walk is well-defined**: L1 takes `rows[i-1]` after sorting by `round`, so it needs
  `round` unique and contiguous within a cell. Both arms: 0 duplicate `(task, seed, round)`
  keys, rounds `0..n-1` in every cell, every row `role='whole'`, `retried=False`, and 0
  round‑0 draws flagged `narrowed`.
- **The test is calibrated**: under a no-effect beta-binomial null at this arm's own cell
  sizes, P(either one-sided p < 0.05) = **0.1040** over 1,000 simulations. §6's decision
  rule reads both tails at α = 0.05, so the nominal rate is 0.10. Row 4 is not a broken
  test firing on a false positive at an inflated rate.

**No escalation is warranted on harness grounds.** One statistical note that is *not* a
defect but belongs in the record: because §6 reads both tails at α = 0.05, the arm's
effective two-tailed size is 0.10, and row 4's p = 0.0215 corresponds to a nominal
two-sided p ≈ 0.043. It clears, but not by much.

---

## 3. Rival explanations, quantified

### (a) Prompt-length / token-budget artefact — **REFUTED**

| | legible | repr |
|---|---|---|
| note length, exposed pairs | 194.2 chars | 228.1 chars |
| prompt tokens, exposed pairs | 18,939.3 | 18,947.8 |

The legible note is the **shorter** one, so a length penalty would have to run the wrong
way to explain the result. Within-arm dose response is flat — corr(note length, local) =
+0.0264 (legible) and +0.0873 (repr), with no monotone trend across note-length quartiles
in either arm. And the purse cannot be the channel: the probe verifies, rather than
assumes, that `tokens_remaining == budget − tokens_used` on every record and that
`tokens_used` is the running sum of `tokens_completion` — the purse is charged on
completion tokens only, so an 8‑token prompt difference buys or costs nothing.

### (b) Wording steer — the note invites restructuring — **REFUTED as the driver**

The hypothesis was that naming the expected type in prose the model can read invites it to
rewrite the type annotation instead of the body. It does not: annotation-rewrite rates are
arm-symmetric in both strata.

| | legible | repr |
|---|---|---|
| annotation rewritten, exposed | 196/284 = 69.01 % | 191/269 = 71.00 % |
| annotation rewritten, unexposed | 209/399 = 52.38 % | 208/389 = 53.47 % |
| body rewritten | ≈ 98 % | ≈ 98 % |

An annotation rewrite *is* strongly associated with a non-local landing pooled over both
arms (L1 33.08 % when the annotation changed against 47.49 % when it did not), but the
arms do it at the same rate, so it cannot carry a between-arm difference.

Direct note-copying is arm-specific but far too rare to be the mechanism: the note's named
`expected T` surface newly appears verbatim in the redraft on **10/193 = 5.18 %** of
legible exposed pairs and **0/188** of repr ones (a `b'…'` repr is not emittable under the
grammar mask), and only 1 of those 10 was local. At 5 % it cannot move a 20 % base rate by
6.7 pts.

### (c) Locality-metric artefact — **REFUTED as the cause, PARTIALLY SUPPORTED as a limit on what L1 licenses**

Three sub-checks, all arm-symmetric, so none of them explains the difference:

- **Structural degeneracy.** A noted path of depth ≤ 2 (`''`, `definition.term`) is local
  for *every* successor. That is 87/683 = 12.74 % of the legible denominator and
  83/658 = 12.61 % of the repr one — 33.7 % and 31.6 % of all L1 hits respectively. Large,
  and symmetric.
- **Depth composition.** Standardising the headline over noted-path depth gives a
  composition effect of **+1.18 pts** — the wrong sign to explain a −2.20 pt result — and a
  within-depth behaviour effect of **−3.27 pts**.
- **Redraft length.** A mechanically longer redraft would drift further from the noted
  node. The legible arm's redrafts are the **shorter** ones (+1.7 chars and 326.8 completion
  tokens against +3.5 and 339.3), again the wrong direction.

What *is* supported is a limitation on reading L1 as "the model can act on the note". L1
scores a draw that reproduces the **same failure at the same path** as a local repair — a
stuck model scores maximally local. Closing that loophole (`L1-strict`, identical in every
other respect) matters a great deal to how row 4 should be read:

| | all L1-eligible | exposed | unexposed |
|---|---|---|---|
| L1 as pre-registered | −2.20 pts, p = 0.0215 | −6.71 pts, p = 0.0026 | +1.42 pts, p = 0.8836 |
| L1-strict | −0.93 pts, **p = 0.1852** | −4.52 pts, p = 0.0177 | +1.89 pts, p = 0.9580 |

**The pre-registered headline does not survive closing the churn loophole; the
exposed-stratum effect does.** That is the single most load-bearing sensitivity in this
document. Row 4 as written is partly a statement that the repr arm churns in place more
often (96/658 same-path repeats against 91/683), which L1 credits as repair.

### (d) Heterogeneity — **REFUTED; the effect is broad**

6 of 8 tasks show a negative difference, ranging −7.17 pts (`nat/selectNonNegative`) to
+4.00 pts (`list/sum`). Per cell pair: 23 negative, 11 positive, 30 exactly zero (cells
whose arms never diverged within the shorter arm's draws), mean −2.36 pts, median 0.00.
Across draw-index bands the difference is negative in all four (−2.40, −0.75, −4.46,
−2.53 pts). No single cell or task carries it.

---

## 4. The conservatism reading's scorecard

§6 row 4's own hypothesis: *an unreadable note makes the model conservative about touching
the noted region, so it repairs locally because it cannot read enough to justify a broader
rewrite.* Read as a claim about **edit magnitude**, it fails on every measure. Read as a
claim about **where the failure ends up**, it holds.

| Prediction of the conservatism reading | Measurement (exposed stratum) | Verdict |
|---|---|---|
| `repr` makes smaller edits | similarity to predecessor 0.6518 (repr) vs 0.6526 (legible) | **fails** — indistinguishable |
| more of the predecessor survives under `repr` | draft reproduced verbatim: 4 (repr) vs 5 (legible) | **fails** |
| `repr` writes shorter, more cautious redrafts | length delta **+17.1** chars (repr) vs +6.7 (legible); completion 345.9 vs 325.6 tok | **fails, and reverses** — `repr` writes *more* |
| `repr` keeps the next failure near the noted node | same-path 8.2 % vs 6.0 %; descendant 7.8 % vs 4.6 %; ancestor 25.3 % vs 27.8 %; elsewhere 54.3 % vs 58.5 % | **holds** |
| the locality gain is a genuine gain | acceptance 4.46 % (repr) vs 3.17 % (legible) on the same draws | **holds** — L1 and acceptance move together, so L1 is not simply penalising progress |

So the conclusion of the conservatism reading survives and its stated mechanism does not.
A better-fitting description: **the repr note is inert and the legible note is active.**
The repr rendering embeds tokens the model has never seen and cannot emit under the
grammar mask, so the model regenerates from a prior anchored on its own previous draft and
its failure tends to stay in the same subtree. The legible rendering embeds the program's
own vocabulary, perturbs the distribution, and moves the failure out of the noted region —
up the tree (ancestor 27.8 % vs 25.3 %) or sideways (elsewhere 58.5 % vs 54.3 %) — without
buying acceptance. At 7B the readable note is a perturbation, not a repair signal.

### The matched-predecessor sub-experiment

Both arms share `draw_seed` and every other field, so a cell's draws stay byte-identical
until the first draw whose note differed — and the probe confirms that divergence and
note-difference coincide on all 56 matched points, exactly as determinism requires. At
that draw the two arms have the *same* predecessor draft, the same error, the same noted
path, and differ by one bit. It is the cleanest contrast the arm contains:

```
legib-legible  L1 at the matched draw   7/56   = 12.50%
legib-repr     L1 at the matched draw  12/56   = 21.43%
McNemar table: both local 5, legible only 2, repr only 7, neither 42
exact two-sided binomial on the 9 discordant pairs: p = 0.1797
```

Same direction, larger gap (−8.9 pts), **and not significant** — one draw per cell is 9
discordant pairs. It is reported for its cleanliness and its direction, not its p‑value.
It also reconfirms (a): the prompt-token difference at these matched draws is
**−8.0 tokens** on an 18.9 k‑token prompt, mean, with a range of [−32, +2].

---

## 5. What this probe cannot settle

The exposed/unexposed contrast establishes that **the note text causes the effect**. It
does not separate two readings of *why*:

1. **Content steering** — the legible note names a type the model can act on, and acting
   on it moves the failure elsewhere.
2. **Emittable-token perturbation** — *any* change to the note that swaps unemittable
   bytes for program vocabulary reroutes the sample, and the direction of the L1 cost has
   nothing to do with the note being *correct*.

Two pieces of evidence lean against (1) as a full account. The effect does not scale with
how actionable the named type is: splitting the exposed stratum on whether the surface
type is hash-free (a copyable `I64`, `Bool`, `(fn I64 () Bool)`) or hash-bearing
(`(data 0x…)`) gives −5.45 pts and −6.84 pts respectively — the *less* actionable half has
the *larger* gap. And verbatim uptake of the named type is 5.18 %, too rare to carry the
effect. But neither observation is decisive, and no replay can settle it: distinguishing
them needs a third rendering that is well-formed and emittable but semantically wrong,
which means re-sampling the model.

A second limit: the exposed-stratum effect is measured at **0.672 power** for its own
observed size (§10 of the probe: beta-binomial fitted to the control's exposed cells,
61 cell pairs, 4.4–4.7 draws/cell, 500 simulations). An effect detected by a
0.67‑power design sits on the favourable side of the sampling distribution, so
**−6.71 pts should be read as an upper bound**, not a point estimate to plan against.

---

## 6. Recommendation

### DEFER — nothing to build.

The arm asked whether the campaign's next investment should go into the feedback surface.
This probe answers it more firmly than an L1 null would have: at 7B, on this protocol, a
readable narrowing note **does** change what the model writes, and the change is not
useful. On the steps where the seam was live, acceptance was 3.17 % against the repr arm's
4.46 % and repair locality 13.73 % against 20.45 %. There is no version of this result in
which the feedback surface is the lever to build on next.

Three reasons not to spend on the follow-up now, despite row 4's ESCALATE:

- **The outcome that matters did not move.** Arm-wide L2 was 6.42 % vs 6.87 % (RR 0.93,
  §2.2 measured its power against a 1.25× effect at 0.23). Even taking the exposed-stratum
  effect at face value, it is 1.3 pts of acceptance on 41 % of repair steps. Nothing
  downstream of the campaign changes on that.
- **A replication is a coin flip.** At this arm's shape the probability of reproducing
  significance, *given the observed effect is exactly true*, is 0.672. A follow-up sized
  like this arm buys a 1-in-3 chance of a null that means nothing.
- **The remaining question is mechanism, not leverage.** Separating "content steering"
  from "emittable-token perturbation" (§5) would label the effect. It would not produce a
  lever at 7B either way, because both readings say the same thing about what to build:
  not this.

`8ed72cd` stands, unchanged and unreverted, for the reason §6 row 4 already gives: it is a
correctness fix independent of this arm. §6 row 3's disposition applies to the track —
keep the fix as a standing improvement carried by every future arm, not as a lever.

### The trigger that reopens this

**Any plan that proposes to add or change content in the redraft prompt** — prefix-primed
repair (2026‑08‑26 §2.5), a richer note surface, a hole block reaching `redraft`, extra
addressability material between drafts. This probe shows that a 200‑character change to
what the model reads between drafts moves repair locality by ~6.7 pts on the steps it
touches, with no acceptance gain and no dependence on the change being *correct*. Such a
change is therefore **not** a free addition, and a plan that treats it as one is
mis-specified.

When the trigger fires, three things must be in that plan before its GPU spend, all of
them cheap and two of them already built:

1. **An inert-control arm.** A third `narrowing_note_render` — a well-formed, emittable,
   *semantically wrong* type surface (the correct surface with its data hash permuted is
   the obvious construction: same syntax class, same length class, no information). The
   `legible − scramble` contrast isolates content; `scramble − repr` isolates
   emittability. It is one config field on the existing seam, and the runlist, stub gate
   and compare script all carry over. Order-of-magnitude: one extra 64-cell block ≈ 4 h ≈
   $1.00 Spot / $3.40 on-demand at §4's measured 21.3 tok/s — but see (3).
2. **The exposed-stratum endpoint as the primary, in `L1-strict` form.** Both are
   implemented here (`legib_row4_probe.exposure_map`, `strict_repair`) and would move into
   `legibility_endpoints.py`. §3(c) shows the pre-registered L1 does not survive closing
   its churn loophole, so a follow-up that re-uses it unchanged would be pre-registering an
   endpoint this probe has already shown to be fragile.
3. **A power run on the exposed stratum**, not the full denominator. §2.2's MDE table was
   fitted to all 64 cells at a 40 % base rate; the live stratum is ~61 cells at a 20 % base
   rate with 4.4–4.7 draws/cell, and §10's table (power 0.94 / 0.81 / 0.44 / 0.23 at
   RR 0.50 / 0.60 / 0.75 / 0.85) says a decisive arm is roughly twice this one's cells, not
   the same size. Deliverable 5's script needs re-pointing, not rewriting.

Until something asks to put new content in front of the model between drafts, none of that
is worth building.
