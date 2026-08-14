| Date | Change |
|------|--------|
| [2026-08-14](https://github.com/wbniv/loom/commit/447ef63) | Land condition 4: 773 draws, R5 scored, Phase B complete |
| [2026-08-14](https://github.com/wbniv/loom/commit/de317f2) | Bring plans and the source-code investigation current with Phase B events |
| [2026-08-14](https://github.com/wbniv/loom/commit/23b6c2f) | Record the condition-4 launch and close out the build-cache plan |
| [2026-08-14](https://github.com/wbniv/loom/commit/f8617b7) | Close out the Phase A run log; grace-poll the driver deadline |
| [2026-08-14](https://github.com/wbniv/loom/commit/4fe8157) | Land Phase A results: predictions scored, report preserved |
| [2026-08-14](https://github.com/wbniv/loom/commit/ff5f6ba) | Update plans: GPU attempt log, spot-vs-on-demand lesson, cache status |
| [2026-08-13](https://github.com/wbniv/loom/commit/1e3d765) | Record GPU-run restoration: 7B model, full seeds |
| [2026-08-13](https://github.com/wbniv/loom/commit/23bea9d) | Record smoke findings: truncation artifact, amended full-run config |
| [2026-08-13](https://github.com/wbniv/loom/commit/66edc80) | Record prompt-cache measurement deviation and KV-quant finding |
| [2026-08-13](https://github.com/wbniv/loom/commit/489f74c) | Amend model selection: 3B local after 7B OOM and K3 evaluation |
| [2026-08-13](https://github.com/wbniv/loom/commit/eac350c) | Record experiment model/hardware selection; promote the T5 |
| [2026-08-13](https://github.com/wbniv/loom/commit/c2fbc79) | Amend experiment plan: phases, resample baseline, budget rule, predictions |
| [2026-08-13](https://github.com/wbniv/loom/commit/d3a4df4) | Triage the auto-captured experiment-plan deferral |
| [2026-08-13](https://github.com/wbniv/loom/commit/d3f8789) | Record the masked-generation experiment plan; sequence store after |

<!--history-meta v1
447ef63	author	Will Norris
447ef63	added	24
447ef63	deleted	7
447ef63	files	1
447ef63	body	Masking weakly dominates rejection sampling (+70% no-example, +46%\nfew-shot, exact tie full-corpus and held-out) but misses plain\ngrammar's 1.452 corpus-rich bar. Scope failures 268 -> 17; typecheck\nthe 41% survivor; mask 10.4% of masked-draw latency (M1 does not\nfire). Predictions 4 and 5 scored; B2 promoted to Done.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
de317f2	author	Will Norris
de317f2	added	11
de317f2	deleted	0
de317f2	files	1
de317f2	body	Launch log through the us-east1 stockouts and zone hunt; M1 evidence\ncaveat (salvaged partial's mask numbers are defect symptoms, not the\nmeasurement); Phase A postscript on the english-as-source analysis.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
23b6c2f	author	Will Norris
23b6c2f	added	9
23b6c2f	deleted	0
23b6c2f	files	1
23b6c2f	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
f8617b7	author	Will Norris
f8617b7	added	45
f8617b7	deleted	7
f8617b7	files	1
f8617b7	body	Attempt 6 (us-east1-b, on-demand, cache hit) succeeded; the driver's\nexit-1 was the laptop suspending through the run's completion — the\npoll loop woke past its wall-clock deadline. One post-deadline grace\npoll fixes it. Store-shaping conclusions from Phase A recorded.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
4fe8157	author	Will Norris
4fe8157	added	20
4fe8157	deleted	0
4fe8157	files	1
4fe8157	body	2,335 draws on the L4. Corpus regime is the dominant lever (28.5%\nacceptance, 13 byte-identical semantic successes); typecheck is the\nPhase B gate layer; truncation persists under grammar; de Bruijn\nconfirmed at 0.978; rejection sampling adds nothing over grammar.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
ff5f6ba	author	Will Norris
ff5f6ba	added	15
ff5f6ba	deleted	0
ff5f6ba	files	1
ff5f6ba	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
1e3d765	author	Will Norris
1e3d765	added	7
1e3d765	deleted	0
1e3d765	files	1
1e3d765	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
23bea9d	author	Will Norris
23bea9d	added	15
23bea9d	deleted	0
23bea9d	files	1
23bea9d	body	All 25 grammar-constrained parse failures are truncations (the GBNF is\nsound in-sample); real checker signal is typecheck then scope; hashes\nhurt as token-budget damage. Full run: draw cap 512, seeds {1}.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
66edc80	author	Will Norris
66edc80	added	7
66edc80	deleted	0
66edc80	files	1
66edc80	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
489f74c	author	Will Norris
489f74c	added	26
489f74c	deleted	8
489f74c	files	1
489f74c	body	The 7B is unrunnable on this box (kernel OOM at the default KV\nallocation; 0.10 tok/s under memory pressure) and this llama.cpp\nbuild's CLI exits silently, so the backend is llama-server. Kimi K3\nwas evaluated at the operator's request: hosted APIs lack GBNF, so\nthe grammar conditions cannot run hosted; operator dropped it for\nthis experiment. History kept in the amendment record.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
eac350c	author	Will Norris
eac350c	added	11
eac350c	deleted	3
eac350c	files	1
eac350c	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
c2fbc79	author	Will Norris
c2fbc79	added	73
c2fbc79	deleted	13
c2fbc79	files	1
c2fbc79	body	Five approved amendments: two-phase execution with Phase A's failure\nprofile designing the Phase B masker; GBNF+rejection-sampling as the\nfourth condition (type-masking's economic rival); one fixed token\nbudget per task across conditions; semantic success operationalized\nnow (identity match / checked+type-exact plus rubric); six\npre-registered predictions scored in the results report. TODO items\nrescoped to the phase split.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
d3a4df4	author	Will Norris
d3a4df4	added	4
d3a4df4	deleted	0
d3a4df4	files	1
d3a4df4	body	The plan is design-only; its verification runs with the substrate item.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
d3f8789	author	Will Norris
d3f8789	added	130
d3f8789	deleted	0
d3f8789	files	1
d3f8789	body	The experiment tests §8.4's central hypothesis with three comparable\nconditions (unconstrained / GBNF / GBNF+type-masking) across four\ncorpus regimes, measured down the contract funnel plus semantics,\noverhead, diversity, and repair cost. Only a disposable store-shaped\nresolver is built; the real store follows, shaped by the evidence —\nespecially whether the hot path needs a compact indexed type service.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
-->
