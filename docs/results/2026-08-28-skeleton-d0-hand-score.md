# Skeleton lever, D0 — hand-scored mechanical floor (14B, $0)

**Plan:** [2026‑08‑28‑skeleton‑lever](../plans/2026-08-28-skeleton-lever.md) §7.1 (Gate 1, before anything)
**Population:** the 42 banked 14B mechanical-floor draws named in the plan's §1.6 —
`prototype/runs/scale14-b0/records.jsonl` and `prototype/runs/scale14-b2/records.jsonl`,
the two blocks of the [2026‑08‑27‑model‑scale‑arm](../plans/2026-08-27-model-scale-arm.md).
**Method:** [`experiment.decomp_hand_score`](../../prototype/experiment/decomp_hand_score.py),
extended past its hard-coded arm tuple to take a run list. $0, CPU, no GPU, no network.
**Command:** `python3 -m experiment.decomp_hand_score scale14-b0 scale14-b2` (from `prototype/`).
**Exit code: 0.**

## What "hand-scored" means here

Mechanized, not eyeballed. Every candidate the funnel accepted with the task's
exact declared type (`semantic_success` in `records.jsonl`, rule
`checked+type-exact`) is evaluated on the reference interpreter and run
against the task's verified gold term (`experiment.heldout_gold.GOLD_TERMS`)
over a concrete input battery, one battery per task, three inputs each. A
fuel exhaustion or crash on any battery input is a fail on that surface. Every
candidate with byte-identical `(task, source)` to one already scored is
printed as a duplicate rather than re-evaluated — the module's docstring
explains why this is safe without any role-aware filtering: under the `holes`
generation protocol each round emits a paired `skeleton` record and a
`candidate` record, and when the round needed no fill (true of every floor
draw in this population — confirmed below) the two are byte-identical, so the
existing dedup collapses the pair into one verdict on its own.

## Population accounting, checked against the plan before scoring

```
raw semantic_success lines read (both blocks, both roles)   84
  = 42 floor draws x 2 roles (skeleton + candidate), paired per round
per-round pairing check: for all 42 rounds, skeleton.source == candidate.source   42/42
unique (task, source) surfaces after dedup                                       12
```

Per task, counting distinct successful rounds (role `candidate`, the harness's
own denominator for this figure per `decomposition_analysis.candidates_of`):

```
  heldout/list/reverseThen          21
  heldout/nat/selectNonNegative     10
  heldout/list/mapLength             7
  heldout/list/concatLength          2
  heldout/list/sum                   2
  ------------------------------------
  total                             42
```

This reproduces the plan's §1.6 table exactly (5 tasks, 42 draws) and its "12
unique surfaces" count. Cells touched (task, seed): `concatLength`/seed 1,
`mapLength`/seed 1, `mapLength`/seed 2, `reverseThen`/seed 1,
`reverseThen`/seed 2, `sum`/seed 2, `selectNonNegative`/seed 1,
`selectNonNegative`/seed 2 — **8 of 32**, matching §1.6.

No integrity failure occurred: every one of the 5 tasks in this population
had a `BATTERY` entry and a `GOLD_TERMS` entry (the existing three — `sum`,
`reverseThen`, `mapLength` — plus `concatLength` and `selectNonNegative`,
added to `decomp_hand_score.BATTERY` for this run), every gold term
evaluated without error, and no candidate's own evaluation crashed. §6 row
D0‑c does not fire.

## Per-surface verdicts

Draw counts below are the number of the 42 floor draws that collapsed onto
each unique `(task, source)` surface — computed from the full dedup (not
eyeballed off adjacent print lines: a duplicate can point back to a primary
printed many lines earlier, across a block boundary, so counting was done
programmatically over the scorer's own dedup key).

| task | draws | block(s) | cell(s) | verdict | per-input | note |
|---|---|---|---|---|---|---|
| `list/concatLength` | 2 | b0, b2 | seed 1 | **PASS** | match, match, match | `List.size(append(xs, ys))` — the composition `HAND_SOLVED` itself uses |
| `list/mapLength` | 5 | b0, b2 | seed 1, seed 2 | **PASS** | match, match, match | `λf. λxs. List.size xs` (eta-expanded) — `f` is never applied |
| `list/mapLength` | 2 | b0, b2 | seed 1 | **PASS** | match, match, match | `λf. List.size` (point-free) — the same shortcut, syntactically distinct |
| `nat/selectNonNegative` | 10 | b0, b2 | seed 1, seed 2 | **PASS** | match, match, match | native `if var2 then widenPos(var1) else var0` — bypasses `corpus/nat/select` entirely, uses the language's own conditional |
| `list/sum` | 1 | b2 | seed 2 | **PASS** | match, match, match | `foldRight(I64.add, 0, xs)` — gold uses `foldLeft`; equivalent since `+` is associative/commutative |
| `list/reverseThen` | 6 | b0, b2 | seed 1, seed 2 | FAIL | MISMATCH, match, MISMATCH | |
| `list/reverseThen` | 10 | b0, b2 | seed 1, seed 2 | FAIL | MISMATCH, match, MISMATCH | |
| `list/reverseThen` | 2 | b0 | seed 1 | FAIL | MISMATCH, match, match | |
| `list/sum` | 1 | b0 | seed 2 | FAIL | match, MISMATCH, MISMATCH | |
| `list/reverseThen` | 1 | b2 | seed 1 | FAIL | MISMATCH, match, MISMATCH | |
| `list/reverseThen` | 1 | b2 | seed 1 | FAIL | MISMATCH, match, MISMATCH | |
| `list/reverseThen` | 1 | b2 | seed 2 | FAIL | ERROR:FuelExhausted, ERROR:FuelExhausted, MISMATCH | fuel exhaustion counted as fail per the module's own rule, not an integrity error |

12 rows, matching the 12 unique surfaces, and the draw column sums to 42
(21 `reverseThen` + 10 `selectNonNegative` + 7 `mapLength` + 2 `concatLength`
+ 2 `sum`), reproducing §1.6's per-task table exactly. Full per-draw detail
(arm/seed/draw tags, raw verdict lines) is in `decomp_hand_score`'s own
stdout, reproduced by the command above.

**Tally: 5 PASS surfaces (20 of the 42 draws), 7 FAIL surfaces (22 of the 42
draws), 0 integrity failures.** Worth noting since it is not visible from the
surface count alone: `reverseThen`'s two largest FAIL surfaces alone account
for 16 of its 21 draws — most of the task's floor mass is two recurring wrong
programs, not 21 independent near-misses.

## Reading the two shapes of PASS

Two of the five passing surfaces are worth flagging as not what they look
like at first read, though neither is disqualified by it:

- **`mapLength`'s `List.size` shortcut** never calls `map` and never applies
  its function argument `f`. It still passes the *entire* input domain, not
  just this battery — `length(map(f, xs)) == length(xs)` for every `f` and
  `xs`, because `map` cannot change a list's length. This is the identical
  surface the 7B pilot found and scored **PASS** for the same reason
  ([2026‑08‑27 pilot report](2026-08-27-hole-elicitation-pilot-report.md)
  §"Hand rubric"). It is extensionally correct, not a composition — a
  distinction worth keeping for anyone citing this as evidence about
  compositional ability specifically.
- **`selectNonNegative`'s native `if`** never calls `corpus/nat/select`
  either. It reimplements the choice with the language's own conditional
  over the two widened arguments — `if b then widenPos(pos) else nat` — which
  is a correct, general, and different route from the one `composes` names in
  `prompts.py` (`corpus/nat/widenPos`, `corpus/nat/select`). This one *is* a
  genuine composition, just not the anticipated route.

Neither is the failure mode §1.6 flagged as the open risk on the floor
endpoint — an extensional shortcut that **fails** — but this population has
one of those too, and it is the *same* surface the 7B pilot found: the
`list/sum` FAIL above (b0, seed 2) is `λxs. List.size(xs)`, identical in
shape to the 7B pilot's `list/sum`-as-`List.size` shortcut (see the
[2026‑08‑27 pilot report](2026-08-27-hole-elicitation-pilot-report.md)). It
matches gold on the empty-list input (length and sum both 0 there) and
mismatches on `[1, 2, 3]` (length 3 ≠ sum 6) and `[5, -2]` (length 2 ≠ sum
3) — exactly the failure the shortcut predicts. **This is the case §1.6
warns the floor can overstate:** a draw that reached `semantic_success`
(accepted, type-exact) and is not, behaviorally, the task.

## Verdict — §6 row D0‑a fires

**Exit 0, 5 genuine semantic successes among the 42 banked 14B floor draws
(≥ 1 required).** Per the plan's §6:

> The campaign has held-out semantic successes at 14B, obtained for $0
> … The floor endpoint is calibrated, E3 becomes trustworthy, and the §4
> ceiling question becomes worth escalating with a number behind it.

What this licenses, precisely: reporting these five as a results document
(this one) against the model-scale arm — done; treating §5's E3 (the
descriptive mechanical-floor endpoint) as trustworthy in any future arm run
under this plan; and reopening the §4 ceiling escalation ($4.55 → ≈ $8.61)
with a measured floor behind it rather than an untested one. It does **not**
by itself relicense the 32B row (2026‑08‑27 §6 row 2) — the plan is explicit
that row needs "a measured slope, not this."

## Cost

$0. CPU only, no GPU, no network, no model — the interpreter runs the banked
`source`/`raw` text already on disk against `heldout_gold.GOLD_TERMS`, itself
$0 (verified, CPU-only, no model at generation time — see its own module
docstring).
