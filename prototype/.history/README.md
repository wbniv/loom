| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/a19d194) | Close effect-consistency review follow-ups |
| [2026-08-13](https://github.com/wbniv/loom/commit/749804c) | Define the refinement-to-SMT-LIB translation rules |
| [2026-08-13](https://github.com/wbniv/loom/commit/7776d05) | Align effect documentation and fixtures |
| [2026-08-13](https://github.com/wbniv/loom/commit/fcb34bf) | Fix effect purity soundness |
| [2026-08-13](https://github.com/wbniv/loom/commit/233b719) | Add effect-directed typing |
| [2026-08-13](https://github.com/wbniv/loom/commit/e9944dc) | Add nominal match validation |
| [2026-08-13](https://github.com/wbniv/loom/commit/92bebcb) | Define builtin ability prelude |
| [2026-08-13](https://github.com/wbniv/loom/commit/b442b6c) | Add declaration reference validation |
| [2026-08-13](https://github.com/wbniv/loom/commit/7df4ab8) | Add stateful scope validation |
| [2026-08-13](https://github.com/wbniv/loom/commit/3e91901) | Harden canonical Loom parser |
| [2026-08-12](https://github.com/wbniv/loom/commit/7474944) | Prototype Loom S-expression transcoder |

<!--history-meta v1
a19d194	author	Will Norris
a19d194	added	21
a19d194	deleted	0
a19d194	files	1
a19d194	body	Eight doc/test-level fixes from the 2026-08-13 effect-consistency change\nreview plus two later review notes: complete SPEC.md §3.1.2's expected-type\ncontext list, fix SPEC.md's stale status header, add a dedicated pinned test\nfor the direct-application effect rejection, correct the effect-purity\nchange review's resolution note (the rejection test actually already\nexisted, contrary to the later review's finding), document the GBNF\nvalidator build recipe, import the design sketch from outside the repo and\nrepair all broken ../docs/ references, reword §6.1.1's circular confidence\nclause, and record the F64 bitwise-equality design fork. No checker or\ntranslator behavior changed.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
749804c	author	Will Norris
749804c	added	18
749804c	deleted	0
749804c	files	1
749804c	body	SPEC.md §3.2 named the target fragment but not the encoding, so an A3\nproof obligation had no artifact a solver could take as input. Add\nnormative §3.2.1: one canonical SMT-LIB script per verification\ncondition (context, hypotheses, goal), refined value at loom.x0,\nrefinements erased in sort position, I64 as Int under a 64-bit domain\naxiom, F64/Text/Bytes as uninterpreted sorts with hash-named literals,\napplied data types monomorphized to Loom.D<sha256> datatypes, stored\nreferences uninterpreted unless a toolchain interpretation table maps\nthem onto a closed Core+Ints allowlist with call-site linearity checks,\nand a fixed command order ending in (assert (not goal)) (check-sat).\n\nprototype/refinements.py implements those rules with path-aware errors\nand explicit refusal of lam, perform, handle, fix, hole, partial\napplication, effectful references, function/capability sorts, and\npolymorphic constructors. No solver dependency: the module emits text\nand the tests validate it structurally through the existing sexpr\nreader.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
7776d05	author	Will Norris
7776d05	added	5
7776d05	deleted	2
7776d05	files	1
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
