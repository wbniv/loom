| Date | Change |
|------|--------|
| [2026-08-14](https://github.com/wbniv/loom/commit/1995b67) | Add public write-up of the masked-generation experiment |
| [2026-08-14](https://github.com/wbniv/loom/commit/a4d241e) | Record store v0's run log and verification |
| [2026-08-13](https://github.com/wbniv/loom/commit/a19d194) | Close effect-consistency review follow-ups |
| [2026-08-13](https://github.com/wbniv/loom/commit/7776d05) | Align effect documentation and fixtures |
| [2026-08-13](https://github.com/wbniv/loom/commit/72736d0) | Add Loom-vs-Lisp doc; ignore session transcripts |
| [2026-08-12](https://github.com/wbniv/loom/commit/c624690) | Import Loom v0.1 spec and overview from ~/docs |

<!--history-meta v1
1995b67	author	Will Norris
1995b67	added	22
1995b67	deleted	0
1995b67	files	1
1995b67	body	Self-contained article covering method, R5 results, funnel movement,\nmask cost, and the prediction scoring for both experiment phases, plus\na README Results section linking the article and the two raw reports.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
a4d241e	author	Will Norris
a4d241e	added	10
a4d241e	deleted	5
a4d241e	files	1
a4d241e	body	All seven of the plan's numbered verification steps, run as written with raw\noutput recorded below each, plus the two completion criteria that are not\nnumbered steps (fsck catching an edited sidecar; a re-seeded store being\nbyte-identical under diff -r).\n\nResults: 43 Rust tests green, clippy + fmt clean, 47 objects seeded and\nfsck exit 0, 587 Python tests green (555 before, +32 from test_store), a\ncorrupted object refused with exit 4 naming both hashes, an absent hash\nrefused with exit 3 on stdout, todo:lint and git diff --check clean.\n\nThe run log also records the design decisions taken inside the plan's shape\nand the alternatives rejected — notably why declarations travel as a JSON\nmirror of their IR rather than through a new Python CBOR decoder, and why\nthe index carries a sidecar digest.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
a19d194	author	Will Norris
a19d194	added	2
a19d194	deleted	2
a19d194	files	1
a19d194	body	Eight doc/test-level fixes from the 2026-08-13 effect-consistency change\nreview plus two later review notes: complete SPEC.md §3.1.2's expected-type\ncontext list, fix SPEC.md's stale status header, add a dedicated pinned test\nfor the direct-application effect rejection, correct the effect-purity\nchange review's resolution note (the rejection test actually already\nexisted, contrary to the later review's finding), document the GBNF\nvalidator build recipe, import the design sketch from outside the repo and\nrepair all broken ../docs/ references, reword §6.1.1's circular confidence\nclause, and record the F64 bitwise-equality design fork. No checker or\ntranslator behavior changed.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
7776d05	author	Will Norris
7776d05	added	5
7776d05	deleted	3
7776d05	files	1
72736d0	author	Will Norris
72736d0	added	3
72736d0	deleted	0
72736d0	files	1
72736d0	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
c624690	author	Will Norris
c624690	added	56
c624690	deleted	0
c624690	files	1
c624690	body	Moved from ~/docs/loom/ (history there up to docs@9c48965).\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01XibQUXov4cMPMW2uNBzJsi
-->
