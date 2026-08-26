| Date | Change |
|------|--------|
| [2026-08-26](https://github.com/wbniv/loom/commit/e0073bd) | Design: hole-elicitation re-run, pre-registered as a new plan |

<!--history-meta v1
e0073bd	author	Will Norris
e0073bd	added	813
e0073bd	deleted	0
e0073bd	files	1
e0073bd	body	§6 row 4 of the 2026-08-25 plan pre-committed a re-run with the fill gate\nrelaxed from `accepted` to `parses`. The banked run's deeper finding — the\nmodel wrote a hole in 12 of 747 skeletons — means that remedy cannot help on\nits own, and the evidence now says why.\n\n`experiment.hole_elicitation_probe` (six CPU sections, no GPU) establishes:\n\n  - §3's protocol block DID induce holes: 12/747 vs `redraft`'s 2/772,\n    one-sided Fisher p = 0.005. It is a working manipulation ~20x too weak,\n    not an ignored one. Corrects the report's prose.\n  - Nine of the ten hole-bearing rejects failed at a node that is NOT the\n    hole — eight at a committed sibling, one at the declared type. Holes\n    cannot propagate an error (SPEC §2.6); hole-bearing drafts were accepted\n    at 16.7% vs 5.3% hole-free. Corrects the report's causal chain.\n  - The relaxed gate would have bought 8 fill draws and, on that blame\n    analysis, 0 composed definitions. Row 4's remedy buys mechanism\n    exposure, not the primary.\n  - `(hole ` is admissible under the real type mask at all 8 body goals, as\n    one of ten heads. The mask is not the obstacle; zero hole exemplars in\n    any of the 26 corpus fixtures is.\n\nThe plan is filed as a NEW pre-registration rather than an amendment: the\n2026-08-25 §4.9 standard forbids amending that file after data exists.\n\nIt specifies the well-scoped fill gate exactly (parse/references/scope still\nblock, with structural reasons; typecheck admits), four elicitation blocks,\nand a two-stage design whose $1.30 pilot is an option on the $4.55\nconfirmatory spend. Power is re-tabled at the measured A0 = 0.047, which is\nwhy Stage 1 runs 96 cells rather than 64.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01AqWeKNNAVguNfmda2TmpKY
-->
