# Implementation plans

| Date | Plan | Status |
|---|---|---|
| 2026-08-24 | [Corpus-size sweep: does acceptance track definition count, or content?](2026-08-24-corpus-size-sweep.md) | Complete; four arms run, §2.7 LR trend test p = 0.128 — no trend detected, underpowered, not refuted |
| 2026-08-23 | [A diversity-seeking harvest](2026-08-23-diversity-harvest.md) | Built and stub-verified; three structural gates cut 58 candidates to 15, GPU arms pending |
| 2026-08-14 | [Store namespaces v1](2026-08-14-store-namespaces.md) | Implemented; PASS (steps 1–7 recorded) |
| 2026-08-14 | [The namespace lease protocol](2026-08-14-lease-protocol.md) | Approved (D1–D4 + revoke amendment); SPEC §5.3.3 carries it |
| 2026-08-14 | [Closing the corpus loop](2026-08-14-corpus-loop.md) | Complete; recall +31 % stable, composition 0 after hand-scored rubric |
| 2026-08-14 | [Store v0: persistent content-addressed objects in Rust](2026-08-14-store-v0.md) | Built and verified; 47 objects seeded, `fsck` clean, prompt equivalence proven |
| 2026-08-14 | [The production implementation language](2026-08-14-production-language-decision.md) | Decided — Rust; migration deferred behind triggers M1–M4 |
| 2026-08-14 | [GPU build cache](2026-08-14-gpu-build-cache.md) | Complete; hit proven on two consecutive runs |
| 2026-08-14 | [GCP infrastructure for the Phase A experiment run](2026-08-14-gcp-experiment-infra.md) | Implemented; `fmt` + `validate` + `shellcheck` PASS, apply gated on the operator |
| 2026-08-13 | [GPU infrastructure for the Phase A experiment run](2026-08-13-gpu-experiment-infra.md) | Implemented; `fmt` + `validate` PASS, apply gated on operator credentials |
| 2026-08-13 | [The reference evaluator](2026-08-13-reference-evaluator.md) | Implemented; PASS |
| 2026-08-13 | [§3.3 subsumption in `typecheck.py`](2026-08-13-refinement-subsumption.md) | Implemented; PASS |
| 2026-08-13 | [Experiment Phase B: the incremental type-state masker](2026-08-13-experiment-phase-b.md) | Complete; condition 4 run (773 draws), R5 scored |
| 2026-08-13 | [The obligation pipeline, and what a `sat` verdict means](2026-08-13-obligation-pipeline.md) | Implemented; PASS |
| 2026-08-13 | [Masked-generation experiment, Phase A substrate and harness](2026-08-13-experiment-phase-a.md) | Implemented; PASS (live run gated on the T5 model item) |
| 2026-08-13 | [Masked-generation experiment](2026-08-13-masked-generation-experiment.md) | Complete; both phases run, six predictions scored |
| 2026-08-13 | [Boolean and comparison base externs](2026-08-13-boolean-base-externs.md) | Implemented; PASS |
| 2026-08-13 | [Versioned validation contracts](2026-08-13-validation-contracts.md) | Implemented; PASS |
| 2026-08-13 | [Bootstrap corpus tranche 4: the refinement slice](2026-08-13-corpus-tranche-4.md) | Implemented; PASS |
| 2026-08-13 | [Bootstrap corpus tranche 3: the effectful slice](2026-08-13-corpus-tranche-3.md) | Implemented; PASS |
| 2026-08-13 | [Bootstrap corpus tranche 2: the recursive slice](2026-08-13-corpus-tranche-2.md) | Implemented; PASS |
| 2026-08-13 | [Claude review remediation and tranche integration](2026-08-13-claude-review-remediation.md) | Implemented; PASS |
| 2026-08-13 | [Callback-extern consequence, stated normatively](2026-08-13-callback-extern-consequence.md) | Implemented; PASS |
| 2026-08-13 | [First-order `forall` instantiation](2026-08-13-forall-instantiation.md) | Implemented; PASS |
| 2026-08-13 | [Measure selection for curried recursion](2026-08-13-measure-selection.md) | Implemented; PASS |
| 2026-08-13 | [Definition-level polymorphism and the Bool elimination form](2026-08-13-polymorphism-and-bool-elimination.md) | Implemented; PASS |
| 2026-08-13 | [Extern object encoding](2026-08-13-extern-object-encoding.md) | Implemented; PASS |
| 2026-08-13 | [Type-directed `fix` and `ref`](2026-08-13-fix-ref-typing.md) | Implemented; PASS (corpus tier re-declared at merge) |
| 2026-08-13 | [Bootstrap corpus for prior starvation](2026-08-13-bootstrap-corpus.md) | Tranche 1 implemented; PASS |
| 2026-08-13 | [Policy-object validation prototype](2026-08-13-policy-validation-prototype.md) | Implemented; PASS |
| 2026-08-13 | [Effect-consistency review follow-ups](2026-08-13-effect-consistency-followups.md) | Implemented; PASS |
| 2026-08-13 | [Namespace policy object](2026-08-13-namespace-policy-object.md) | Implemented; PASS |
| 2026-08-13 | [Refinement-to-SMT-LIB translation rules](2026-08-13-refinement-smtlib-translation.md) | Implemented; PASS |
| 2026-08-13 | [Evidence confidence bounds](2026-08-13-evidence-confidence-bounds.md) | Implemented; PASS |
| 2026-08-13 | [Effect documentation and fixture consistency](2026-08-13-effect-documentation-fixture-consistency.md) | Implemented; PASS |
| 2026-08-13 | [Effect purity soundness](2026-08-13-effect-purity-soundness.md) | Implemented; PASS |
| 2026-08-13 | [Effect-directed typing](2026-08-13-effect-directed-typing.md) | Implemented; PASS |
| 2026-08-13 | [Nominal match validation](2026-08-13-nominal-match-validation.md) | Implemented; PASS |
| 2026-08-13 | [Builtin ability reference prelude](2026-08-13-builtin-ability-prelude.md) | Implemented; PASS |
| 2026-08-13 | [Declaration objects and reference validation](2026-08-13-declaration-objects-reference-validation.md) | Implemented; PASS |
| 2026-08-13 | [Stateful scope validation](2026-08-13-stateful-scope-validation.md) | Implemented; PASS |
| 2026-08-12 | [Canonical parser hardening](2026-08-12-canonical-parser-hardening.md) | Implemented; PASS |
