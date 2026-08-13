| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/b5c7b9c) | Type fix and ref in the match layer |

<!--history-meta v1
b5c7b9c	author	Will Norris
b5c7b9c	added	204
b5c7b9c	deleted	0
b5c7b9c	files	1
b5c7b9c	body	`fix` (tag 10) and `ref` (tag 1) passed scope and reference validation\nbut had no typing rule, capping every recursive corpus definition at the\nstructural tier (bootstrap-corpus finding 3).\n\n`fix T measure body` requires T to equal the expected type and to be a fn\ntype; the measure is checked at the current environment against\n`fn D () I64`, and the body against T with the recursive value at index\n0 under the unchanged ambient row. The `terminates` obligation is not\ndischarged here — §2.5/§6.2 termination stays oracle evidence.\n\n`ref h` resolves its type through an injected resolver threaded the way\nscope.py threads its ability-arity resolver, and refuses explicitly when\nno resolution exists rather than guessing. No def-object store invented.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
-->
