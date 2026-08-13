| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/489f74c) | Amend model selection: 3B local after 7B OOM and K3 evaluation |
| [2026-08-13](https://github.com/wbniv/loom/commit/eac350c) | Record experiment model/hardware selection; promote the T5 |
| [2026-08-13](https://github.com/wbniv/loom/commit/c2fbc79) | Amend experiment plan: phases, resample baseline, budget rule, predictions |
| [2026-08-13](https://github.com/wbniv/loom/commit/d3a4df4) | Triage the auto-captured experiment-plan deferral |
| [2026-08-13](https://github.com/wbniv/loom/commit/d3f8789) | Record the masked-generation experiment plan; sequence store after |

<!--history-meta v1
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
