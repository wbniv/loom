| Date | Change |
|------|--------|
| [2026-08-26](https://github.com/wbniv/loom/commit/a879273) | Model-scale arm: plan the 14B step, with 32B gated on its result |

<!--history-meta v1
a879273	author	Will Norris
a879273	added	220
a879273	deleted	0
a879273	files	1
a879273	body	The obvious reading of section 6 row 1 is a 32B arm. Measured rather than\nassumed: every A100 SKU in this project has a quota of 0.0 in us-central1,\nand 32B at Q4_K_M is 19.85 GB of weights, which does not fit an L4's 24 GB\nalongside a 32k KV cache. 32B is not purchasable here today.\n\n14B is also the better first step on its own merits: it changes exactly one\nvariable (same family, same Q4_K_M quantization, same tokenizer, so the GBNF\ngrammar and per-token type mask carry over untouched), it fits the card we\nhave with ~17 GB of ~24 GB used, and it produces the 7B->14B slope that makes\na later 32B number interpretable instead of a lone data point.\n\nTwo blocks, not four: the reference and hole-required, which spanned the\npilot's whole observed range. Exemplar and checker-holed are dropped with\nreasons. Gates E1/E2 carry over unchanged; S1 is a new one-sided\ntwo-proportion test against the banked pilot-b2 record, and the plan states\nup front that S1 is a screen with power only against a roughly doubled rate.\n\nBudget ceiling $4.50, Spot first with the on-demand fallback the pilot proved.\n\nCo-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01AsFhorikXSngWTna5Hw2Bz
-->
