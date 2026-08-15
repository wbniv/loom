| Date | Change |
|------|--------|
| [2026-08-14](https://github.com/wbniv/loom/commit/cf9b047) | Record turn 2 (plateau) and the stable 12-seed curated baseline |
| [2026-08-14](https://github.com/wbniv/loom/commit/ed2b6d7) | Record the A/B verdict: generated corpus lifts acceptance 31%, 3x held-out |
| [2026-08-14](https://github.com/wbniv/loom/commit/4b907cf) | Make the corpus-loop A/B differ in what the model sees |
| [2026-08-14](https://github.com/wbniv/loom/commit/705cda2) | Close the corpus loop: harvest accepted draws into the store |
| [2026-08-14](https://github.com/wbniv/loom/commit/8977f57) | Plan the corpus loop; queue it and the experiment write-up |

<!--history-meta v1
cf9b047	author	Will Norris
cf9b047	added	18
cf9b047	deleted	0
cf9b047	files	1
cf9b047	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
ed2b6d7	author	Will Norris
ed2b6d7	added	39
ed2b6d7	deleted	2
ed2b6d7	files	1
ed2b6d7	body	Curated arm exactly replicated phase-b; generated arm hit 1.803\nacc/1k tok (highest in the experiment, above gbnf's 1.452 bar) and\nmoved held_out for the first time (3 distinct accepted vs 1).\nHeld-out semantic remains 0 - recall improved, synthesis did not.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
4b907cf	author	Will Norris
4b907cf	added	202
4b907cf	deleted	48
4b907cf	files	1
4b907cf	body	Escalation resolved: an arm that only widens the hash universe tests the\nreferences layer, which Phase A measured as minor (75 of 664 rejections), while\nthe corpus in context was the largest lever it found. `_example_names` now reads\n`resolver.definitions()` instead of `corpus_registry.MANIFEST` for the two\nfull-corpus regimes, so the generated arm shows the model 60 definitions where\nthe curated arm shows 26.\n\nThe freeze's invariant is preserved and is what the equivalence tests prove:\nevery existing run path — no store, or a store under the curated policy — builds\nbyte-identical prompts, and all of test_store.py's equivalence suite plus the\n272-pair harvested-export test pass unmodified. Curated definitions still come\nfirst in manifest order because the reserved generated sequence band puts them\nthere; `few_shot` keeps its four pinned names; and leave-one-out now excludes the\ntask's answer by identity rather than by name, which is the complete rule once a\nstore can hold a generated definition whose bytes are the fixture. A definition\nwith no spec shows bare rather than under a borrowed one.\n\nContext sizing, because n_ctx has already killed one launch: the generated arm's\nlongest prompt is 22,817 chars = 15,110 tokens at the measured 1.51 chars/token,\n15,622 with a 512-token draw. Both arms get n_ctx 32768 (2.1x headroom, ~190\nfurther generated definitions of room); 16384 was rejected at a 4.6% margin, and\nboth arms carry the same value so the transport is not a confound.\n\nThe repo's `chars // 4` floor was optimistic by 2.6x on this surface — hash\nliterals tokenize densely — so it would have waved through 8192 against a real\n15,622-token prompt. `prompts.CHARS_PER_TOKEN` now carries the measured figure\nand the phase-b guard uses it; that config still passes with room.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
705cda2	author	Will Norris
705cda2	added	471
705cda2	deleted	7
705cda2	files	1
705cda2	body	`prototype/harvest.py` selects a run's `funnel_outcome == accepted` records,\nre-validates each through the oracle admit path (never trusting the run's\nverdict stale), and lands them via `loom-store put` as `origin: generated`.\nCounts admitted / exists / refused_on_readmission on one JSON line; the sum is\nasserted against the accepted-record count so the line cannot lose a draw.\n\nProvenance carries a `run` block (model identity, run id, condition, regime,\nseed, draw) and a separate `observation` block, so the run's `semantic_success`\nis structurally not evidence. Names are `generated/<task id>/<12 hex>`, a\nreserved prefix that cannot collide with `corpus/…`; `StoreResolver` refuses a\nname rebind out loud in case it ever could. `sequence` sits in a reserved band\nabove the curated corpus, and nothing in a sidecar depends on when or where the\nharvest ran, so re-harvesting is exactly idempotent.\n\nThe origin filter lives in `StoreResolver` construction: `curated` by default,\n`all` opt-in via `include_generated` on the run config. It filters prompts, the\ntype resolver and the masker's hash universe at once, and refuses an unknown\norigin rather than silently excluding it. `prompts.py` and `test_store.py` are\nuntouched; a new equivalence test builds 272 prompt pairs through a *harvested*\nexport and asserts byte equality.\n\nRust gains one field: `origin` on the index row, surfaced in `list`, so the\nguardrail is visible from the read API instead of only from a file read.\n\nAgainst phase-b's 773 records: 109 accepted, 38 distinct identities, 34 new\nobjects, 4 byte-identical to curated corpus entries, 0 refused on readmission.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
8977f57	author	Will Norris
8977f57	added	105
8977f57	deleted	0
8977f57	files	1
8977f57	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
-->
