| Date | Change |
|------|--------|
| [2026-08-25](https://github.com/wbniv/loom/commit/2e1cacc) | Plan: hole-directed decomposition, pre-registered (next-lever §2.2) |

<!--history-meta v1
2e1cacc	author	Will Norris
2e1cacc	added	730
2e1cacc	deleted	0
2e1cacc	files	1
2e1cacc	body	The address-book run's §6 row 2 licensed decomposition as the next lever.\n§2.2's design problem — "whoever writes the sub-goals is doing part of the\ncomposition" — dissolves once the *model* writes them: it drafts `(hole T ())`\nwhere it is unsure (SPEC §2.6/§8.3), the checker types each hole from the draft\nalone, and the harness fills, splices and re-checks. Nothing proposing or\nvalidating a hole ever sees `composes` or a gold term; pinned by signature the\nway §4.2/§4.8 pinned the typed address filter.\n\nThree arms at matched completion-token purse: `whole` (control), `redraft`\n(feedback, no holes) and `holes` (= redraft + the hole protocol), so\nholes−redraft is the protocol and nothing else. Primary: per-cell\ncomposed-definition rate, one-sided Fisher at α=0.05, single comparison.\n\nThe probe lands the diagnostic and turns up two facts §2.2 did not have:\nacceptance (10% of cells) and type-exactness (37.5%) are each reached and\nalmost never together (2.5%) — the residual is a conjunction the protocol\ndecouples; and `score_semantic` scores a definition that is *nothing but a\nhole* as a mechanical-floor success, which §4.3.1 fixes before any arm runs.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01AqWeKNNAVguNfmda2TmpKY
-->
