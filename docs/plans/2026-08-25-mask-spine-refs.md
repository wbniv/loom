# Plan — `spine-goal`: the sound codomain filter at `app`-spine head positions

**Date:** 2026-08-25
**Status:** Design + implementation, landed in one pass.
**TODO entry:** `[mask-spine-refs]` (T4)
**Parent:** [the next-lever plan](2026-08-24-next-lever.md) §2.4 and Amendment A1;
[the address-book report](../results/2026-08-25-address-book-report.md) §6 row 5.

**Visible surface:** none. One new pruner in `experiment/masker.py`, its tests, and a
CPU diagnostic script whose only output is a table in this document. Per house rule, no
mockup bundle.

---

## 1. What §2.4 asked for, and what the brief asked for — they are not the same rule

§2.4 states the lever as:

> a `ref` at the head of a *k*-ary application spine checked against goal *G* must
> resolve to a type whose *k*-th codomain erases to *G*

and tabulates `47 → 7 / 13 / 13` on three held-out tasks. Those two things do not
agree. Recomputing both candidate rules against the live resolver (`rule_check`, §5.3
below) reproduces the plan's table — including its **named** survivor lists, byte for
byte — only under the *weaker* reading:

| rule at the body position | reverseThen | sum | mapOrElse |
|---|---:|---:|---:|
| **∃k ≥ 0**, some *k*-th codomain erases to *G* | **7/47** | **13/47** | **13/47** |
| **exact k**, the *k*-th codomain erases to *G* | 6/47 | 4/47 | 5/47 |

The tell is `corpus/list/reverse` in §2.4's own reverseThen list. `list/reverse` is
`List → List`: it has a 1st codomain matching `G`, and no 2nd one at all. The spine it
heads in the gold term is `k = 2`, so the exact rule refuses it and the plan's list
keeps it. Likewise §2.4's `sum` list names `clock/now`, `List.size` and `I64.add`,
none of which has a 3rd codomain — `sum`'s spine is `(app (app (app (ref foldLeft) …)))`,
`k = 3`.

So **§2.4's inline figures are an estimate of the wrong quantity** — the set of digests
reachable *anywhere* in a spine rooted at that position, not the set legal at the head
of the spine actually being written. That is the same class of correction §4.3's margin
and A1's filter both needed, and it is recorded here rather than quietly fixed.

**Decision: implement the exact-k rule.** It is what the TODO item and the dispatch
brief specify, it is strictly sharper, and — critically — it is the one that is *sound
at a decode-time position*, because at the moment the head's digest is being written
the open `(app` parentheses have already fixed `k`. The ∃k set is not a position; it
has no byte at which to fire.

Both numbers are reported in §5. Neither is a failure of the lever: the corrected
figures are **better** than the plan's.

## 2. Where the spine context comes from

`TypeState` already carries a stack of `Frame`s, and `_open` stamps every frame with
`goal_in` — the goal of the position that frame fills — *whether or not* the checker is
in checking mode there. For `app` the goal never descends (`part_goal` returns `b""`
for both parts, which is why the layer abstains today), but the frame chain is intact.

So the spine context is a walk up the stack from the frame holding the `ref`:

```
(app (app (ref 0x…) a) b)          stack while the digest is written
  └────┴──────┴── app(part=1) ─ app(part=1) ─ ref(part=1)
```

`spine_context(stack, index)` counts consecutive ancestors with `kind == "app" and
part == 1` — `part == 1` is the *function* position, `part == 2` is the argument — and
returns `(k, goal)` where `goal` is the **outermost** such frame's `goal_in`. `k = 0`,
or an empty goal, is an abstention. An argument position breaks the chain immediately
and yields `k = 0`, which is why `(app (ref widenPos) (var 1))` sitting in
`selectNonNegative`'s argument slot is silently passed over.

## 3. The proof, and every place it stops

`MatchChecker.check` does not special-case tag 4, so `check(spine, G)` is
`synth(spine)` followed by one of three acceptances. `synth` tag 4 is
`copy.deepcopy(function_type[3])` after `function_type[0] != 2` → `_fail`, and the
innermost `synth` of a `ref` is `_resolve_reference`, **verbatim, uninstantiated**
(`check`'s own comment: *"Synthesis position … never reaches here and stays
uninstantiated"*). So the synthesized type of a *k*-ary spine headed by `(ref d)` is
*exactly* the *k*-th codomain of `d`'s resolved type, `C_k`, and acceptance requires

1. `C_k == G`, or
2. `C_k[0] == 6` and `_instantiate(C_k, G)` succeeds, or
3. `_subsume(C_k, G)`, whose own precondition is
   `_erase_refinements(C_k) == _erase_refinements(G)`.

(1) and (3) both imply erasure equality. Therefore: **if `C_k[0] != 6` and
`erase(C_k) != erase(G)`, no accepted definition contains this digest here** — a veto
under proof, the same shape as veto 5's k=0 argument.

Abstentions, each one a place the proof does not reach:

| position | why |
|---|---|
| `k = 0` | not a spine; `GoalTypePruner` veto 5 already owns it |
| goal unknown | argument slot, `let` bound term, `match` scrutinee, `con` field |
| resolved type is `forall` | §3.1.3 instantiation — `_instantiate` is not re-implemented here |
| a `forall` met while peeling | same |
| a `refine` met while peeling | a refined function type; the checker rejects it (`function_type[0] != 2`) but the veto is not worth betting on one literal line |
| `C_k` is `forall` | the instantiation path (2) above is live |
| resolved type carries a free `tyvar` outside a `forall` | defensive: not reachable from a well-formed store, and an abstention costs nothing |

One thing that is **not** an abstention, and the brief expected it to be: an
**effectful head**. `synth` tag 4 returns the codomain regardless of the call row; the
row only feeds `_require_allowed`, which can make the application fail but never makes
it succeed with a different type. So `corpus/clock/now :
(fn (cap C) (C) I64)` at `k = 1, G = I64` is **admitted, precisely and soundly** — and
the effectful positions A1 flagged (`stampedBytes`) abstain for an unrelated reason:
they sit in `con` field slots, which have no goal. §6.2 pins both.

A veto that is sound but deliberately **not** taken: for `k ≥ 1` the head must
synthesize a `fn`, so a `forall`-typed head fails outright at
`function_type[0] != 2`, and `lit`/`con` heads are infeasible at any spine position.
Taking those would widen the soundness surface for precision the lever does not need.
Recorded as a follow-up, not landed.

## 4. Shape: a separate, opt-in pruner

`spine-goal` is a new `Pruner`, **not** a flag on `GoalTypePruner`. Pruners in this
codebase are named, individually toggleable (`Masker.enable`) and individually timed
(`_Timed`), and every config lists them explicitly:

```json
"pruners": ["goal-type", "de-bruijn", "ref-hash"],
```

A sub-flag would be none of those things. `PRUNER_NAMES` — the default — is left
**unchanged**, so every existing config is byte-identical with the pruner absent;
`KNOWN_PRUNER_NAMES` adds it for `build_pruners` and `runner.MaskConfig`'s validator.
Opting in is one word in a config:

```json
"pruners": ["goal-type", "spine-goal", "de-bruijn", "ref-hash"],
```

placed after `goal-type` so `mask_pruned_by_layer` attribution keeps reading in Phase
A's profile order.

Two vetoes:

* **the digest** — a hash atom under a `ref` frame whose own goal is empty, at a spine
  with known `(k, G)`: refuse any byte leaving the spine-admissible digest trie.
* **the `ref` head** — when that trie is *empty*, refuse the head itself. Without this
  the mask walks into a hash position where it must refuse every digit, empties, and
  takes the R4 liveness fallback — which discards the whole step's mask and counts as a
  fallback. This is the same reason `_ref_possible`/`ref_ok` exists for `k = 0`. Only
  `ref` is refused; every other head stays feasible.

## 5. Verification

Numbered steps, raw output pasted below each. **Do not reorganise or summarise these
steps** — they are the spec.

1. `task prototype:test` — green, and the count has grown by the new tests only.
2. Soundness, pruner ON: every corpus fixture **and every gold term** walked byte by
   byte, in atom-straddling chunks, and under longest-match tokenization, asserting
   the fixture's own next token is in the mask at every step; violations must be **0**
   and `mask_fallbacks` must be **0**.
3. Precision: reproduce §2.4's table under both readings, at the real spine-head
   positions of the gold terms.
4. Overhead: `mask_seconds_per_token` with the pruner on vs off, single stream, CPU.
5. Byte-identity: an existing config's pruner list is unchanged and a masker built
   from it produces the same mask as before.

### 5.1 `task prototype:test`

```
Ran 786 tests in 122.192s

OK (skipped=9)
```

**PASS.** Baseline was 762; the 24 new tests are the ones listed in §6. Nothing
existing changed verdict. Run twice at this commit, both `OK (skipped=9)`.

**Not this plan's, recorded for whoever owns it.** A later run of the same command on
the shared tree reports `FAILED (failures=1)`:
`test_experiment.AddressBookTest.test_every_shipped_config_declares_its_registered_arm`
— `AssertionError: 'full' != 'none' : decomp-holes.config.json`. Introduced by
`e04adb2` ("Add decomposition experiment arm configs and runlist"), which lands three
byte-copies of `addr-full.config.json` declaring `"address_book": "full"` without
registering them as arms. Attributed by running that one test in a detached worktree at
this plan's own commit `d2019ac`, where the decomp configs do not exist and it passes.
Nothing in this plan touches a config file.

### 5.2 Soundness

`python3 -m experiment.spine_mask_probe` (its `soundness` section), and
`test_masker.MaskSoundnessTest` — the same walk, as an assertion.

```
## Soundness — every fixture and gold term, `spine-goal` ON

definitions: 34   walks: 204   liveness fallbacks: 0
VIOLATIONS: 0
```

**PASS.** 34 definitions = the 26 corpus fixtures + the 8 gold terms, each walked
under three tokenizations (byte, 3‑byte atom‑straddling, longest‑match) with the layer
on and again with it off: 204 walks, **0 excluded continuations**, **0 liveness
fallbacks**. Phase‑b1's property survives.

The gold terms are the load-bearing addition. `corpus/` reaches a binary spine at best,
so walking it alone would have "proved" the layer sound over positions it never fires
at; the gold terms are `k = 1 … 3` throughout and are funnel-accepted definitions
(`heldout_gold.verify`), which is the only property a soundness fixture needs.

### 5.3 Precision

```
## Precision — admissible refs at each `app`-spine head

task                              k   exact  exists-k  goal
heldout/list/concatLength         1   6/47     13/47   I64
heldout/list/headOrElse           2   5/47     13/47   I64
heldout/list/mapLength            1   6/47     13/47   I64
heldout/list/reverseThen          2   6/47      7/47   (data 0x2ee931a3746132882cdbc63385ccaf7320a5
heldout/list/sum                  3   4/47     13/47   I64
heldout/maybe/mapOrElse           2   5/47     13/47   I64
heldout/nat/selectNonNegative     3   4/47     13/47   (refine I64 (app (app (ref 0x0e2c1cacb65ffac

### §2.4's three tabulated tasks, both readings

heldout/list/reverseThen  k=2
   exists-k (7/47): corpus/list/append, corpus/list/concat, corpus/list/consNat, corpus/list/flatMap, corpus/list/map, corpus/list/reverse, corpus/maybe/mapPoly
   exact-k  (6/47): corpus/list/append, corpus/list/concat, corpus/list/consNat, corpus/list/flatMap, corpus/list/map, corpus/maybe/mapPoly
heldout/list/sum  k=3
   exists-k (13/47): corpus/clock/now, corpus/list/foldLeft, corpus/list/foldRight, corpus/list/lengthNat, corpus/math/abs, corpus/maybe/getOrElse, corpus/maybe/mapPoly, corpus/nat/applyPos, corpus/nat/select, corpus/nat/widenPos, extern/23d1e0, extern/4bd80d, extern/d3914e
   exact-k  (4/47): corpus/list/foldLeft, corpus/list/foldRight, corpus/maybe/mapPoly, corpus/nat/select
heldout/maybe/mapOrElse  k=2
   exists-k (13/47): corpus/clock/now, corpus/list/foldLeft, corpus/list/foldRight, corpus/list/lengthNat, corpus/math/abs, corpus/maybe/getOrElse, corpus/maybe/mapPoly, corpus/nat/applyPos, corpus/nat/select, corpus/nat/widenPos, extern/23d1e0, extern/4bd80d, extern/d3914e
   exact-k  (5/47): corpus/maybe/getOrElse, corpus/maybe/mapPoly, corpus/nat/applyPos, extern/23d1e0, extern/d3914e
```

**PASS, with §2.4's figures corrected.** The `exists-k` column reproduces §2.4's
`7 / 13 / 13` **exactly, including the plan's own named survivor lists** — that is the
proof of §1's claim about what the plan actually measured. The rule that landed is the
`exact-k` column: **47 → 6 / 4 / 5**, sharper than the plan's estimate on every one of
the three, and **the route element survives in all three cases** (`list/append`,
`list/foldLeft`, `maybe/getOrElse`), which is the property §2.4 asked for.

Two rows worth naming:

* `heldout/sample/stampedBytes` **does not appear**. Both its spines sit in `con` field
  arguments, which carry no goal, so the layer abstains on the whole definition —
  Amendment A1's effectful case, abstaining for a reason that has nothing to do with
  effects. Pinned by `test_an_effectful_spine_in_a_con_field_abstains`.
* `corpus/maybe/mapPoly` survives every row. It is the store's one polymorphic
  definition and the layer abstains on every `forall`, so the filter is never a
  precision claim against polymorphism.

### 5.4 Overhead

```
## Overhead — mask_seconds_per_token

spine-goal off  steps=  5020  s/token=0.000752438  uncached=0.000904652  hit-rate=0.1701  fallbacks=0
spine-goal on   steps=  5020  s/token=0.000810866  uncached=0.000975130  hit-rate=0.1701  fallbacks=0
ratio on/off: 1.078x   spine-goal layer seconds: 0.131960   tokens it pruned: 551756
```

**PASS.** Single stream, CPU, 5,020 mask steps over the same 34 definitions.
`mask_seconds_per_token` goes 0.000752 s → 0.000811 s, **+7.8 %**; uncached
0.000905 s → 0.000975 s, **+7.8 %**. The layer's own charged time is 0.13 s of the
4.07 s total, and it removes 551,756 token-subtrees. Run-to-run this figure moves by a
few percent (three runs: 1.055×, 1.078×, 1.088×) — it is a Python-level marginal cost
on a shared box, not a benchmark, and it is nowhere near decode time.

`mask_cache_hit_rate` is identical on and off (0.1701), which says the extra layer is
not thrashing either bounded cache.

### 5.5 Byte-identity when off

`test_the_default_pruner_set_is_unchanged` and
`test_every_shipped_config_runs_the_default_set`: `PRUNER_NAMES` is still
`("goal-type", "de-bruijn", "ref-hash")`, and every `*.config.json` on record names a
subset of it. No config gains the layer by taking a default.

## 6. Tests added to `test_masker.py`

1. `SpineContextTest` — the stack walk: `k = 1, 2, 3`; an argument slot breaks the
   chain; a `let`/`match`/`con` position yields no goal.
2. `SpineGoalPrunerTest` — a `k`-th-codomain match survives digit by digit; a
   mismatch dies early; a **polymorphic head abstains**; an **effectful head is
   admitted**; a head with too few arrows is refused; the empty-set head veto fires and
   refuses only `ref`; the blind pruner (no `reference_type`) abstains everywhere.
3. `MaskSoundnessTest` extended — the gold terms join the fixture corpus, and every
   walk is repeated with `spine-goal` enabled.
4. `SpinePrunerRegistrationTest` — `PRUNER_NAMES` does not contain `spine-goal`, every
   shipped config's list is a subset of it, `runner.Config` accepts the opt-in and
   still refuses a typo, and `Masker.enable` toggles the layer.

24 tests, 762 → 786.

## 7. What this does not license, and what is left

* **The lever is a veto, and §2.4's own one-liner still stands**: it removes wrong
  choices, it cannot supply an address the model has never seen. This is the follow-up
  to addressing, not a substitute for it. Nothing here has been run against a model.
* **Precision left on the table, deliberately.** A `forall`-typed head at `k ≥ 1` is in
  fact rejected by the checker (`synth` tag 4 fails on `function_type[0] != 2` before
  `_instantiate` is ever reached), and `lit`/`con` heads are infeasible at any spine
  position. Both are sound vetoes and neither landed: the brief's instruction is to
  abstain on polymorphism, and head-tag feasibility is an independent lever with its
  own soundness surface.
* **The abstention list is not shrinking on its own.** Argument slots, `let` bound
  terms, `match` scrutinees and `con` fields still carry no goal, which is why
  `stampedBytes` gets nothing. Propagating a `con` field's declared type would be the
  next real widening — and it would need the declaration registry inside `part_goal`,
  which this layer deliberately does not consult.
* **`mask_seconds_per_token` is measured on CPU against a scripted vocabulary**, not
  against the 151k-token model vocabulary under a live decode. The ratio is the honest
  number; the absolute is not.
