| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/fcb34bf) | Fix effect purity soundness |
| [2026-08-13](https://github.com/wbniv/loom/commit/233b719) | Add effect-directed typing |
| [2026-08-13](https://github.com/wbniv/loom/commit/e9944dc) | Add nominal match validation |
| [2026-08-13](https://github.com/wbniv/loom/commit/92bebcb) | Define builtin ability prelude |
| [2026-08-13](https://github.com/wbniv/loom/commit/b442b6c) | Add declaration reference validation |
| [2026-08-13](https://github.com/wbniv/loom/commit/7df4ab8) | Add stateful scope validation |
| [2026-08-13](https://github.com/wbniv/loom/commit/3e91901) | Harden canonical Loom parser |
| [2026-08-12](https://github.com/wbniv/loom/commit/7474944) | Prototype Loom S-expression transcoder |

<!--history-meta v1
fcb34bf	author	Will Norris
fcb34bf	added	5
fcb34bf	deleted	3
fcb34bf	files	1
fcb34bf	body	Synthesized lambdas checked their body against the current ambient row\nwhile claiming an empty row, letting an effectful closure escape a\nhandler typed as pure. Bodies now synthesize under the empty allowance;\nlatent effects require an annotated row. Also reject handling\noperation-less abilities (div stays a row marker per SPEC §2.5), key\narm-mismatch rewrapping on the arm body path, and drop a redundant\ndeep copy in operation_signature.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
233b719	author	Will Norris
233b719	added	13
233b719	deleted	11
233b719	files	1
e9944dc	author	Will Norris
e9944dc	added	7
e9944dc	deleted	0
e9944dc	files	1
92bebcb	author	Will Norris
92bebcb	added	2
92bebcb	deleted	0
92bebcb	files	1
b442b6c	author	Will Norris
b442b6c	added	9
b442b6c	deleted	4
b442b6c	files	1
7df4ab8	author	Will Norris
7df4ab8	added	14
7df4ab8	deleted	5
7df4ab8	files	1
3e91901	author	Will Norris
3e91901	added	75
3e91901	deleted	56
3e91901	files	1
7474944	author	Will Norris
7474944	added	75
7474944	deleted	0
7474944	files	1
-->
