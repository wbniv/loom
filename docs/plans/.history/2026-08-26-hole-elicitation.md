| Date | Change |
|------|--------|
| [2026-08-26](https://github.com/wbniv/loom/commit/cd30c1e) | Hole-elicitation deliverable 6: the stub-backend gate on GPU spend |
| [2026-08-26](https://github.com/wbniv/loom/commit/154c863) | B3 review notes: STEP fix-body correction (immaterial to §1, replay-verified) + arm-rewrite cut-site note |
| [2026-08-26](https://github.com/wbniv/loom/commit/2519e72) | Probe: size B3 and the feedback-legibility defect from the same column |
| [2026-08-26](https://github.com/wbniv/loom/commit/e0073bd) | Design: hole-elicitation re-run, pre-registered as a new plan |

<!--history-meta v1
cd30c1e	author	Will Norris
cd30c1e	added	300
cd30c1e	deleted	0
cd30c1e	files	1
cd30c1e	body	§4.7's checks on CPU, run and pasted back into the plan. Exit 0, every\ncheck PASS, so the gate is open and the pilot may launch.\n\nTwelve checks in one script, driving landed functions only:\n\n  1a  the four pilot arms differ from `whole` only by their block —\n      byte-level for B0/B1 (prompt-side), byte-identical for B2/B3\n      (runner-side mechanisms `prompts.py` does not implement)\n  1b  `closed_subtask_type` still reads `declared_type_of(draft)` —\n      pinned by signature AND by the runner's single call site\n  1c  no gold surface and no unseen hash in any block; the exemplar\n      block introduces zero new store content\n  1d  the seven shipped configs field by field, `pruners` pinned (§9),\n      and the Stage-1 `holes` config's `hole_block` still in its\n      PLACEHOLDER state — nothing has selected yet\n  2   blindness by signature on every surface this plan added\n  5   context, all seven configs; B1's block costs 566 tokens (+3.1 %)\n  6   no gold leak over four blocks x 8 tasks, skeleton and fill\n  7   a scripted stub cell per pilot arm: the §2.1 four-layer gate one\n      layer at a time (parse/references/scope block, typecheck admits),\n      a *rejected* bare hole refused now that the `funnel.accepted`\n      conjunct is gone, the relaxed round capped at one fill draw, B2's\n      note appearing inside its window and reverting after, B3's cut\n  7e  E1/E2 through `pilot_select`'s own functions, plus every branch of\n      §4.2's selection rule over constructed stats\n  9   both §2.2 exemplars round-trip byte-identically to their fixture\n  10  `hole_at_error` over all 1,851 banked typecheck-rejected drafts,\n      through the probe's `check_ten_verdict` — imported, not restated\n  11  §1's pasted numbers still reproduce from the banked records\n\nChecks 2, 5 and 6 run in extended form only; the 2026-08-25 §4.8\nversions are cited per §4.7 and stand unchanged. Check 11 is beyond\n§4.7's list, because that citation is only as good as §1's premises.\n\nSuite: 928 tests, OK (skipped=9) — unchanged.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01AqWeKNNAVguNfmda2TmpKY
154c863	author	Will Norris
154c863	added	13
154c863	deleted	0
154c863	files	1
154c863	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01AqWeKNNAVguNfmda2TmpKY
2519e72	author	Will Norris
2519e72	added	14
2519e72	deleted	3
2519e72	files	1
2519e72	body	`--section blame` now prints, per arm, how many rejections carry a raw-IR\nnarrowing note and how many name a recoverable expected type at the failing\nnode. 41% for the holes arm: that is what a checker-holed seed has to work\nwith, and the same 42% is the unreadable-feedback defect §2.4 files as a\nseparate lever. The plan cited the figure without a probe line behind it.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01AqWeKNNAVguNfmda2TmpKY
e0073bd	author	Will Norris
e0073bd	added	813
e0073bd	deleted	0
e0073bd	files	1
e0073bd	body	§6 row 4 of the 2026-08-25 plan pre-committed a re-run with the fill gate\nrelaxed from `accepted` to `parses`. The banked run's deeper finding — the\nmodel wrote a hole in 12 of 747 skeletons — means that remedy cannot help on\nits own, and the evidence now says why.\n\n`experiment.hole_elicitation_probe` (six CPU sections, no GPU) establishes:\n\n  - §3's protocol block DID induce holes: 12/747 vs `redraft`'s 2/772,\n    one-sided Fisher p = 0.005. It is a working manipulation ~20x too weak,\n    not an ignored one. Corrects the report's prose.\n  - Nine of the ten hole-bearing rejects failed at a node that is NOT the\n    hole — eight at a committed sibling, one at the declared type. Holes\n    cannot propagate an error (SPEC §2.6); hole-bearing drafts were accepted\n    at 16.7% vs 5.3% hole-free. Corrects the report's causal chain.\n  - The relaxed gate would have bought 8 fill draws and, on that blame\n    analysis, 0 composed definitions. Row 4's remedy buys mechanism\n    exposure, not the primary.\n  - `(hole ` is admissible under the real type mask at all 8 body goals, as\n    one of ten heads. The mask is not the obstacle; zero hole exemplars in\n    any of the 26 corpus fixtures is.\n\nThe plan is filed as a NEW pre-registration rather than an amendment: the\n2026-08-25 §4.9 standard forbids amending that file after data exists.\n\nIt specifies the well-scoped fill gate exactly (parse/references/scope still\nblock, with structural reasons; typecheck admits), four elicitation blocks,\nand a two-stage design whose $1.30 pilot is an option on the $4.55\nconfirmatory spend. Power is re-tabled at the measured A0 = 0.047, which is\nwhy Stage 1 runs 96 cells rather than 64.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01AqWeKNNAVguNfmda2TmpKY
-->
