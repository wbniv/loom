# TODO — loom

**Status markers:** `[ ]` open · `[wip]` in progress · `[verify]` implemented, verification
not yet run+recorded (run the linked plan's steps, paste raw output + PASS/FAIL back into
the plan, then promote) · `[x]` done (`## Done` only).

**Delegation tier:** the bracket also carries a `T0`–`T5` rank, tier last — `[T4]`,
`[wip T2]`, `[verify T3]`. It says how much *thinking* the item needs, and `/next` uses it
to dispatch to the cheapest model that can do the work:

| Tier | Work | Goes to |
|---|---|---|
| `T0` | Mechanical lookup — grep, count, "which file defines X" | haiku, read-only |
| `T1` | Mechanical edit with a known recipe | sonnet @ medium |
| `T2` | Bounded implementation — one module, clear spec | sonnet @ high |
| `T3` | Multi-file work against a settled plan — **default when unranked** | opus @ medium |
| `T4` | Design *and* implementation; unknown root cause | opus @ high |
| `T5` | Do it yourself inline — or it needs a human, hardware, or a vendor console | *(no agent)* |

Ranking is itself `T5`: the orchestrator assigns tiers inline and never delegates that
step, at any scale. Only `## Open` carries tiers — Watch, Parked and Done items are not
dispatchable, and an item returning from Watch or Parked is ranked fresh. Full rubric:
`~/CLAUDE.md` — Delegation.

Plan-first: non-trivial work gets a `docs/plans/YYYY-MM-DD-<topic>.md` and an entry here.
Check conformance with `task todo:lint`.

## Open

- [wip T2] [legib-compare] <!-- agent:ae3006110e2588068 --> `experiment/legibility_compare.py` — L1/L2/C1 verdicts,
  exit codes per plan §6, sharing L1's predicate with `legibility_power.py`
  rather than carrying a second copy. T2: one script, spec settled.

- [T5] [legib-run] The GPU run itself: 2 arms × 64 cells, one instance, Spot
  first, ceiling $4.55, pre-committed degradation to 40 cells/arm (never fewer
  arms). Gated on legib-replay + legib-stub and an explicit launch go — and on
  [bucket-restore], since the driver uploads through that bucket. Use the new
  `--detach` driver mode. Report per plan D7.

- [wip T2] [render-values-derive] <!-- agent:a923d5e231b11289b --> `render-gcp-startup-script.py`'s representative-
  values dict is hand-maintained and went stale (missing `runlist_key` blocked
  the self-delete guard from rendering). Derive it from `variables.tf` defaults
  so a new template var can't go stale silently. T2: one script, clear goal,
  parsing judgment.

- [wip T2] [runner-log-survival] <!-- agent:aa3a86ccad6b9ca8b --> The scale14 startup/llama logs died with the
  bucket; a future incident shouldn't be diagnosed by code inspection alone.
  Make runner logs survive independent of the bucket's 7-day lifecycle —
  e.g. driver fetches logs on every exit path incl. resume, or a separate
  retention prefix. T2: one seam in driver/startup script, design settled by
  the incident.

## Watch

- Type-directed masking overhead at batch (SPEC.md §8.2, §13 open problem 3) —
  the single-stream question is **measured and closed** (3.15 ms/token warm,
  10.4 % of masked-draw latency; see
  [condition-4 results](docs/results/2026-08-14-phase-b-condition4-report.md)).
  What remains watched: the cost at served batch B ≫ 1, where the language
  plan's M1 trigger (≥ 25 % of decode) could still fire. Revisit when any
  serving-shaped workload exists.

- Lease fairness at scale (SPEC.md §5.3.3, §13 problem 4 — narrowed) — the
  protocol is **specified and approved** (fencing, state log, lazy expiry,
  per-namespace); watched residue: contention fairness (queues/sharding),
  the named `revoke` verb, and A0 possession-proof. Revisit on real
  agent-count data or when the store's namespaces increment starts.

- Extensional-equality memo layer for intensional identity (SPEC.md §4.1, §13 open
  problem 5) — semantically identical definitions currently duplicate evidence effort;
  revisit once the memo ledger (§6.4) has real usage data showing this actually costs
  something.

Entries here are plain bullets: what to check, how often, and the trigger that
promotes it back to Open.

## Parked

_Nothing parked. Entries here are plain bullets — intentionally shelved work, with the
condition that would unpark it._

## Done

- ✅ 2026-08-27 — [legib-stub] `legibility_stub_check.py`: regression + C2 inertness + config-diff + scripted cells all PASS, pasted into the plan; GPU gate open. Suite 947 green.
- ✅ 2026-08-27 — [legib-configs] Both arm configs + runlist as byte-copies (2 fields differ), pinned by difference in `test_legibility_arm.py`; AddressBook allowlist updated per 5f697dc precedent.
- ✅ 2026-08-27 — [selfdelete-taskfile] `task infra:test-self-delete` wired, absorbed inline with the AWS-port commit.
- ✅ 2026-08-27 — [aws-driver-port] Durable log, manifest, `--resume`/`--fetch-only`/`--detach`, marker-gated teardown + grace poll ported to the AWS driver; 5-block offline guard passes; no self-delete drift analogue on AWS. Commit pending in same tree.
- ✅ 2026-08-27 — [legib-replay] Gate clears: 2,159/2,159 banked draws byte-identical under `repr`, 0.00% leak / 0 reclassifications under `surface`; raw output pasted into the plan. Commit 5a4d622.
- ✅ 2026-08-27 — [legib-seam] `narrowing_note_render: surface|repr` contextvars seam in typecheck + Config + per-cell set-site; default pinned byte-identical; suite 943 green. Commit 5a4d622.
- ✅ 2026-08-27 — [runner-self-delete] Proven: template got unsuffixed `instance_name` while instance+IAM used `local.instance_name` — every suffixed root's delete hit a nonexistent name. 1-line fix in the shared module + mocked-provider drift guard, fail-then-pass. See [plan](docs/plans/2026-08-27-runner-self-delete.md).
- ✅ 2026-08-27 — [bucket-restore] `loom-diversity-artifacts` recreated from the reviewed plan: 3 added (bucket + 2 IAM members), 0 changed, 0 destroyed; state back to 6 resources. Unblocks [legib-run]'s upload path.
- ✅ 2026-08-27 — [feedback-legibility-arm] Pre-registered the repr-fix isolation arm: 2 concurrent arms via a render seam, L1 repair-locality primary (MDE RR 1.20 @ 64 cells), $4.55 ceiling; banked baseline kept as anchor only. See [plan](docs/plans/2026-08-27-feedback-legibility-arm.md).
- ✅ 2026-08-27 — [driver-fetch-loss] Root cause proven from the journal: host suspended mid-poll and lost power, no signal ever reached the trap. Driver gains durable log, manifest, `--resume`/`--fetch-only`/`--detach`; 24-check offline guard. Commit 7df1f93.
- ✅ 2026-08-27 — [scale14-run] Both blocks ran (Spot preempted at once, on-demand fallback, ≈$3.97 of $4.50): no block clears E1, E2 NOT CLEAR, §6 row 3 fired — scale track stops, 32B unlicensed. See [report](docs/results/2026-08-27-model-scale-arm-report.md).
- ✅ 2026-08-27 — [scale14-fetch] 14B GGUF fetched (8,988,110,272 bytes, exact) and the compatibility gate PASSES: banked telemetry, 7B and 14B all report n_vocab 152,064, so the mask indexes the same space. See [plan](docs/plans/2026-08-27-model-scale-arm.md).
- ✅ 2026-08-27 — [scale14-compare] `scale_compare.py` (§6 rows executed, exit codes) + `scale14_power.py`; measured S1 power at a doubled rate = 0.54, which corrected the plan's §2.1 claim and re-keyed §6 row 2 to a descriptive threshold. See [plan](docs/plans/2026-08-27-model-scale-arm.md).
- ✅ 2026-08-27 — [scale14-configs] Two configs + runlist as byte-copies (one line differs each), validated; CPU stub gate re-run unchanged, 12/12 PASS, pasted into the plan with check 1d's coverage gap stated. See [plan](docs/plans/2026-08-27-model-scale-arm.md).
- ✅ 2026-08-27 — [elicit-pilot-run] Stage 0 ran, 4/4 arms SUCCEEDED: no block clears E1 (best 3.47% vs 10% bar), 31 fill draws 0 spliced; §6 row 1 — Stage 1 not launched, $4.55 unspent. See [report](docs/results/2026-08-27-hole-elicitation-pilot-report.md).
- ✅ 2026-08-26 — [elicit-stub] All 12 gate checks PASS (incl. check 10 over 1,851 banked rejections and §1 reproduction); output pasted into the plan; pilot GPU gate open. Commit cd30c1e.
- ✅ 2026-08-26 — [elicit-configs] 4 pilot + 3 stage-1 configs + 2 runlists + pilot_select.py (E1/E2, B3 bar, --apply placeholder resolution), all validated, 16 tests; suite 928 green. Commit aaa19f9.
- ✅ 2026-08-26 — [elicit-block-b3] `hole_at_error`/checker-holed landed, 4 fences, check 10 PASS (0 violations/1,851 banked rejections), 26 tests; probe STEP bug found+fixed (immaterial, replay-proven). Commits cd0f717, 154c863.
- ✅ 2026-08-26 — [elicit-block-b2] `hole_required_rounds` append-only demand note landed, inert at default, gate-composition verified, 13 tests; suite 889 green. Commit f603922.
- ✅ 2026-08-26 — [narrowing-legibility] Repr leak was typecheck.py's nine _fail sites; 37/41/42% → 0% on banked replay, 0 reclassifications, 4 tests; suite 880 green. Commit 8ed72cd.
- ✅ 2026-08-26 — [elicit-gate] `fill_gate: accepted|well-scoped` landed, bare-hole conjunct bug fixed with fail-then-pass on banked data, 12 tests; suite 876 green. Commit 1b8086b.
- ✅ 2026-08-26 — [elicit-block-b1] `exemplar` block landed behind `hole_block`, byte-identity pinned, 15 tests in new test_elicitation.py, probe imports it back; suite 864 green. Commits 4f7b450, 0eae0ae.
- ✅ 2026-08-26 — [elicit-backpointers] Row-4-fired pointer on the 08-25 plan + correction addendum on the 08-26 report, append-only. Commit 5c7dbe8.
- ✅ 2026-08-26 — [decomp-elicit-rerun] New pre-registration (2-stage: $1.30 pilot → $4.55 @ 96 cells): block induces at p=0.005 but 20× weak (prior, not mask); 9/10 rejects failed at siblings — gate alone buys 0. See [plan](docs/plans/2026-08-26-hole-elicitation.md).
- ✅ 2026-08-26 — [decomp-run] Primary NULL but starved (§6 row 4: 5.5% skeleton acceptance, 0 fills); **first 2 genuine held-out semantic successes** incl. first real composition, verified by execution; ≈$2.75. See [report](docs/results/2026-08-26-decomposition-report.md).
- ✅ 2026-08-26 — [decomp-stub] All 8 gate checks PASS (8/8 gold expressible via nested round-trip, no leaks, purse rules hold); output pasted into the plan; GPU gate open. Commit a6eadc5.
- ✅ 2026-08-26 — [decomp-runner] Round loop landed: protocol-neutral purse (§4.3 intact), monotonicity enforced vs hole-bearing fills, crash-safe rounds, 3 configs validate, suite 849 green. Commit faeb0c7.
- ✅ 2026-08-26 — [decomp-prompts] Hole machinery landed: obligations/closure/splice/fill+protocol blocks, whole pinned byte-identical (720 prompts vs HEAD~1), 33 tests, suite 821 green. Commit 7ad7dda.
- ✅ 2026-08-26 — [decomp-floor-fix] Floor refuses hole-bearing defs (§5.4): 8 eta-skeletons fail-then-pass, archive replay 0 changes, decomp configs registered; suite 788 green. Commits bf0f053, 66d6481.
- ✅ 2026-08-26 — [mask-spine-refs] `spine-goal` pruner landed: 204 soundness walks 0 exclusions, 47→6/4/5 exact (plan's 7/13/13 was the ∃k reading), +7.8% overhead, 24 tests. See [plan](docs/plans/2026-08-25-mask-spine-refs.md).
- ✅ 2026-08-26 — [decomp-configs] Three decomp arm configs + runlist, byte-copies of addr-full with only plan fields changed; `generation_protocol` validation deferred to decomp-runner. Commit e04adb2.
- ✅ 2026-08-26 — [decomposition] Designed + pre-registered hole-directed decomposition (3 arms, composed-definition primary, 91% power @ 0.20); probe found the residual is a retention conjunction AND a floor defect. See [plan](docs/plans/2026-08-25-hole-decomposition.md).
- ✅ 2026-08-26 — [runlist-partial-fetch] Driver now fetches every runlist entry's per-arm prefix on all exit paths, with per-arm verdict summary; simulated-partial-run tested. Commit ac7094e.
- ✅ 2026-08-26 — [next-lever-run] Primary SIGNIFICANT: addr-full 10/320 vs none 1/320, p=0.0055; semantic 0 after rubric; typed 21/320 despite handicap; ≈$1.31. See [report](docs/results/2026-08-25-address-book-report.md).
- ✅ 2026-08-25 — [next-lever-stub] §4.8 dry-run (as amended by A1): all 5 checks PASS, output pasted into the plan; GPU gate open. See [plan](docs/plans/2026-08-24-next-lever.md).
- ✅ 2026-08-25 — [next-lever-gold] All 8 gold terms verified (funnel+mechfloor, real tokenizer), none dropped; worst case 662 tok < 768 cap; §4.3's stale 447/72% corrected. See [plan](docs/plans/2026-08-24-next-lever.md).
- ✅ 2026-08-25 — [budget-regression] §4.3 budget fix landed (T2 escalation: it was never implemented) + guard with fail-then-pass proof; full-cap-or-no-draw for any config. See [plan](docs/plans/2026-08-24-next-lever.md).
- ✅ 2026-08-25 — [next-lever-configs] Three arm configs + `address-runlist.json` as byte-copies of `followup_curated` with only §4.2/§4.3 fields changed; all validate. See [plan](docs/plans/2026-08-24-next-lever.md).
- ✅ 2026-08-25 — [heldout-addendum] Correction addendum appended to both 2026-08-24 reports, pointing at next-lever §1; `full_corpus` halves stand. See [plan](docs/plans/2026-08-24-next-lever.md).
- ✅ 2026-08-25 — [next-lever-prompt] Address book behind `address_book: none|full|typed` + blind codomain filter, 21 leak-pinning tests; escalation resolved by plan Amendment A1 (addr-typed → exploratory). See [plan](docs/plans/2026-08-24-next-lever.md).
- ✅ 2026-08-24 — [next-lever-audit] §1 diagnostics recomputed independently from repo data; every pasted block reproduces exactly (4,135-draw universe). See [plan](docs/plans/2026-08-24-next-lever.md).
- ✅ 2026-08-24 — [next-lever] Premise falsified: 7/8 held-out tasks unsolvable (addresses withheld) + 100% cell censoring; lever = address book, pre-registered 3-arm run. See [plan](docs/plans/2026-08-24-next-lever.md).
- ✅ 2026-08-24 — [corpus-size-sweep] Mass-vs-quality still open: monotone acc/1k tok across 0/8/15/25/41 defs but LR p=0.128 at ≈38% power — underpowered, not refuted. See [report](docs/results/2026-08-24-corpus-size-sweep-report.md).
- ✅ 2026-08-24 — [diversity-harvest] Negative on both counts: acceptance tracks corpus mass, not quality (diverse 1.477 vs sizematch 1.402, p=0.82; held-out 5/96); no selection rule can buy composition the pool lacks. See [report](docs/results/2026-08-24-diversity-harvest-report.md).
- ✅ 2026-08-24 — [heldout-powered] Acceptance advantage decisive at n=952/arm (91 vs 46, Fisher p≈8.4e-5, OR 2.08); composition 0 — all 21 candidates vacuous, 19 via type-collision recycling. See [report](docs/results/2026-08-23-heldout-powered-report.md).
- ✅ 2026-08-15 — [claim-liveness] Burned fence/seq markers skipped, not retried forever; asymmetric escalation (bind free, lease last-attempt+guard) after the agent proved uniform escalation unsafe. See [plan](docs/plans/2026-08-14-store-namespaces.md).
- ✅ 2026-08-15 — [ffi-spike] Built the offset generator: 60/60 fields match ctypes, MLton smoke test links real libllama; FFI=3 measured. See [study](docs/investigations/2026-08-14-language-eval-batch-2.md) A3.
- ✅ 2026-08-15 — [seq-claims] Concurrent same-holder binds prevented via O_EXCL seq markers; fsck invariant relaxed to strictly-increasing per SPEC's own wording. See [plan](docs/plans/2026-08-14-store-namespaces.md).
- ✅ 2026-08-14 — [track-p-l0] Built the differential harness: 3,681 cases via transparent entry-point instrumentation, byte-reproducible, zero test changes. See [language plan](docs/plans/2026-08-14-production-language-decision.md) Track P.
- ✅ 2026-08-14 — [language-batch-2] Scored SML/Haskell/Clojure/Perl/Ruby on the fixed rubric: Haskell 94 nearest, none approach Rust's 114; decision stands. See [study](docs/investigations/2026-08-14-language-eval-batch-2.md).
- ✅ 2026-08-14 — [store-namespaces] Built bindings+leases per §5.3.3: O_EXCL fences (race-proven), oracle-owned policy admission, rules enforced-or-refused. See [plan](docs/plans/2026-08-14-store-namespaces.md).
- ✅ 2026-08-14 — [corpus-loop] Closed the loop: 34 generated defs harvested with provenance, resolver-driven examples, chars/token floor fixed 2.6×; A/B one launch away. See [plan](docs/plans/2026-08-14-corpus-loop.md).
- ✅ 2026-08-14 — [experiment-writeup] Published the constrained-generation article (12-point number audit) + README results section. See [article](docs/articles/2026-08-14-constrained-generation-results.md).
- ✅ 2026-08-14 — [store-v0] Built the Rust store: 47 corpus objects seeded, fsck 3-invariant, 172-prompt resolver equivalence proven; first Track G code. See [plan](docs/plans/2026-08-14-store-v0.md).
- ✅ 2026-08-14 — [phase-b2] Condition-4 matrix complete (773 draws): masking ≥ rejection everywhere, +70% no-example; typecheck 41% survivor. See [plan](docs/plans/2026-08-13-experiment-phase-b.md).
- ✅ 2026-08-14 — [language-decision] Rust when migration fires (114/130 vs Zig 86,
  Go 83, OCaml 79); migration deferred — masker is 25x under trigger (d) in every
  single-stream config. See [plan](docs/plans/2026-08-14-production-language-decision.md).
- ✅ 2026-08-14 — [gcp-experiment-infra] Built the GCP mirror: L4 spot module with
  triple self-deletion, token-per-invocation auth, quota preflight; ~$0.61/run.
  See [plan](docs/plans/2026-08-14-gcp-experiment-infra.md).
- ✅ 2026-08-13 — [gpu-experiment-infra] Built loom-* Terraform: bootstrap, self-
  narrowing IAM, g6.xlarge spot experiment-runner module, one-command driver;
  ~$0.78/run. See [plan](docs/plans/2026-08-13-gpu-experiment-infra.md).
- ✅ 2026-08-13 — [reference-evaluator] Built the CEK-machine interpreter: all 26
  fixtures execute, multi-shot handlers proven, abs(INT_MIN) negative on hardware
  semantics. See [plan](docs/plans/2026-08-13-reference-evaluator.md).
- ✅ 2026-08-13 — [runner-hardening] Made the experiment runner crash-safe: per-draw
  persistence, partial-run artifacts, resume, one retry. See
  [plan](docs/plans/2026-08-13-experiment-phase-a.md) hardening amendment.
- ✅ 2026-08-13 — [phase-b1] Built the masker core: ctypes transport over the pinned
  libllama, byte-oracle mask with proof-or-abstain soundness (0 violations, 26
  fixtures x 151k vocab), 0.03% warm overhead. See
  [plan](docs/plans/2026-08-13-experiment-phase-b.md).
- ✅ 2026-08-13 — [experiment-model] Selected Qwen2.5-Coder-7B Q4_K_M under
  llama-cli @ pinned llama.cpp on CPU-only i7-1185G7; recorded in the plan.
  See [plan](docs/plans/2026-08-13-masked-generation-experiment.md).
- ✅ 2026-08-13 — [refinement-subsumption] Typing subsumes refine types via emitted
  VCs behind an opt-in sink; three fixtures re-tiered checked; typecheck 1.1.
  See [plan](docs/plans/2026-08-13-refinement-subsumption.md).
- ✅ 2026-08-13 — [experiment-phase-a] Built the Phase A harness: resolver, four
  regimes, 8 proven held-out tasks, 3 conditions, stub-tested funnel and report.
  See [plan](docs/plans/2026-08-13-experiment-phase-a.md).
- ✅ 2026-08-13 — [obligation-pipeline] Typing emits obligations, never calls a
  solver; three-way sat semantics with a two-part exactness rule; nat/select's
  diagnosis corrected. See [plan](docs/plans/2026-08-13-obligation-pipeline.md).
- ✅ 2026-08-13 — [boolean-externs] Added Bool.and/or/not and I64.le to the assumed
  base (nine externs) with a deterministic conjunction-translation demonstration.
  See [plan](docs/plans/2026-08-13-boolean-base-externs.md).
- ✅ 2026-08-13 — [validation-contracts] Versioned seven per-layer contracts at 1.0
  with MAJOR/MINOR bump rules validated against history; Watch trigger (a) met.
  See [plan](docs/plans/2026-08-13-validation-contracts.md).
- ✅ 2026-08-13 — [corpus-tranche-4] Built six refinement fixtures with pinned VC
  scripts and solver-produced verdicts (3 unsat / 3 sat mapping the fragment edge).
  See [plan](docs/plans/2026-08-13-corpus-tranche-4.md).
- ✅ 2026-08-13 — [corpus-tranche-3] Built seven effectful fixtures at tier checked
  spanning perform/handle/cap shapes; purity test reworked; R8 verdict: no tool yet.
  See [plan](docs/plans/2026-08-13-corpus-tranche-3.md).
- ✅ 2026-08-13 — [corpus-tranche-2] Built six recursive fixtures at tier checked with
  the corpus's first ref dependency chain; concat's monomorphic wall recorded.
  See [plan](docs/plans/2026-08-13-corpus-tranche-2.md).
- ✅ 2026-08-13 — [callback-extern] Stated the callback-extern consequence in §5.1.3
  with the accepted/rejected test pair pinning the per-arrow rule's reach.
  See [plan](docs/plans/2026-08-13-callback-extern-consequence.md).
- ✅ 2026-08-13 — [claude-review-remediation] Hardened extern capability order,
  reconciled monomorphic ABIs with forall instantiation, added validated
  definition-type resolution and provenance enforcement, and renamed the
  expanded checker. See
  [plan](docs/plans/2026-08-13-claude-review-remediation.md).
- ✅ 2026-08-13 — [forall-instantiation] Implemented first-order instantiation of
  quantified refs in checking position; mapPoly-at-I64 proof definition validates.
  See [plan](docs/plans/2026-08-13-forall-instantiation.md).
- ✅ 2026-08-13 — [measure-selection] Added the `fix` position field `[10, T, k, m, b]`
  selecting the decreasing argument; `list/foldRight` reaches `checked` at k=2.
  See [plan](docs/plans/2026-08-13-measure-selection.md).
- ✅ 2026-08-13 — [poly-and-bool] Threaded `forall` depth into term checking (zero
  tags, prenex rank-1 enforced) and added `if` as tag 12; both corpus limits lifted.
  See [plan](docs/plans/2026-08-13-polymorphism-and-bool-elimination.md).
- ✅ 2026-08-13 — [extern-encoding] Specified kind-7 extern objects (§5.1.3) with
  capability-honest rows, five pinned corpus externs, and 29 tests; tranche 2 unblocked.
  See [plan](docs/plans/2026-08-13-extern-object-encoding.md).
- ✅ 2026-08-13 — [corpus-license] Re-sourced corpus attributions to the MIT-licensed
  unisonweb/unison main repo (metadata only, no identity change); scaling unblocked.
  See [plan](docs/plans/2026-08-13-bootstrap-corpus.md).
- ✅ 2026-08-13 — [fix-ref-typing] Added `fix` typing with measure-shape checking and
  resolver-backed `ref` typing (20 tests); corpus tier re-declared at merge.
  See [plan](docs/plans/2026-08-13-fix-ref-typing.md).
- ✅ 2026-08-13 — [bootstrap-corpus] Chose Unison base, transpiled and validated 4 seed
  definitions, pinned 3 expressiveness limits as tests, specified tranches 2–4.
  See [plan](docs/plans/2026-08-13-bootstrap-corpus.md).
- ✅ 2026-08-13 — [policy-prototype] Implemented policy validation, satisfaction, and
  domination with 54 tests pinning the default hash and §12 arithmetic executable.
  See [plan](docs/plans/2026-08-13-policy-validation-prototype.md).
- ✅ 2026-08-13 — [effect-followups] Closed all eight review follow-ups: spec wording,
  status header, pinned tests, GBNF build recipe, imported sketch, fixed links.
  See [plan](docs/plans/2026-08-13-effect-consistency-followups.md).
- ✅ 2026-08-13 — [policy-object] Specified §5.3.1–§5.3.2 policy objects: rules and
  selectors, budgets, upward resolution over a pinned default, monotone amendment.
  See [plan](docs/plans/2026-08-13-namespace-policy-object.md).
- ✅ 2026-08-13 — [smtlib-rules] Specified §3.2.1 deterministic VC-to-SMT-LIB scripts
  and implemented the translator with 22 tests and explicit out-of-fragment refusal.
  See [plan](docs/plans/2026-08-13-refinement-smtlib-translation.md).
- ✅ 2026-08-13 — [evidence-bounds] Specified the A1 payload with generator, exact
  rational bound/confidence, Clopper–Pearson method, and partial-order rebind rules.
  See [plan](docs/plans/2026-08-13-evidence-confidence-bounds.md).
- ✅ 2026-08-13 — [effect-consistency] Specified contextual effectful-lambda
  checking, aligned effect plans, and promoted the clock-handler documentation
  sample to a round-trip and type-checked fixture. See
  [plan](docs/plans/2026-08-13-effect-documentation-fixture-consistency.md).
- ✅ 2026-08-13 — [effect-purity] Fixed effectful-closure escape (synthesized lambdas
  are now pure), banned handling operation-less abilities, with regression tests. See
  [plan](docs/plans/2026-08-13-effect-purity-soundness.md).
- ✅ 2026-08-13 — [effect-typing] Added closed-row effect-directed checking for
  function calls, operation signatures/capabilities, and exhaustive handlers
  with typed continuations. See
  [plan](docs/plans/2026-08-13-effect-directed-typing.md).
- ✅ 2026-08-13 — [nominal-match] Added parameterized constructor checking and
  exhaustive nominal match validation with verified binder types/order. See
  [plan](docs/plans/2026-08-13-nominal-match-validation.md).
- ✅ 2026-08-13 — [builtin-prelude] Pinned eight nominal builtin ability
  declarations, operation ABIs, hashes, and a preloaded verified registry. See
  [plan](docs/plans/2026-08-13-builtin-ability-prelude.md).
- ✅ 2026-08-13 — [declaration-objects] Added hashed data/ability declarations,
  recursive self types, a verified registry, and nominal bounds/arity checks. See
  [plan](docs/plans/2026-08-13-declaration-objects-reference-validation.md).
- ✅ 2026-08-13 — [stateful-scope] Specified every binder convention and added
  path-aware term/type de Bruijn validation with resolved handler arities. See
  [plan](docs/plans/2026-08-13-stateful-scope-validation.md).
- ✅ 2026-08-12 — [sexpr-grammar] Prototyped S-expr isomorph + canonical-CBOR
  transcoder; matches SPEC.md §4.4 worked-example hash exactly. See [prototype/](prototype/).


## Inbox — auto-captured plan deferrals

_Auto-added from plan "Out of scope"/"Deferred" sections at commit time. Triage each into M1/M2/etc. and delete it here — it will not come back._

<!-- BEGIN auto-captured-deferrals (managed by audit-plan-deferrals.sh — triage these into the curated sections above; the fingerprint ledger means a deleted item is NOT re-added) -->
<!-- END auto-captured-deferrals -->
