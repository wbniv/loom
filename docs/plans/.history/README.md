| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/749804c) | Define the refinement-to-SMT-LIB translation rules |
| [2026-08-13](https://github.com/wbniv/loom/commit/42ffcdd) | Add confidence-bound fields to A1 property evidence |
| [2026-08-13](https://github.com/wbniv/loom/commit/7776d05) | Align effect documentation and fixtures |
| [2026-08-13](https://github.com/wbniv/loom/commit/fcb34bf) | Fix effect purity soundness |
| [2026-08-13](https://github.com/wbniv/loom/commit/233b719) | Add effect-directed typing |
| [2026-08-13](https://github.com/wbniv/loom/commit/e9944dc) | Add nominal match validation |
| [2026-08-13](https://github.com/wbniv/loom/commit/92bebcb) | Define builtin ability prelude |
| [2026-08-13](https://github.com/wbniv/loom/commit/b442b6c) | Add declaration reference validation |
| [2026-08-13](https://github.com/wbniv/loom/commit/e22627a) | Record scope validation verification |

<!--history-meta v1
749804c	author	Will Norris
749804c	added	1
749804c	deleted	0
749804c	files	1
749804c	body	SPEC.md §3.2 named the target fragment but not the encoding, so an A3\nproof obligation had no artifact a solver could take as input. Add\nnormative §3.2.1: one canonical SMT-LIB script per verification\ncondition (context, hypotheses, goal), refined value at loom.x0,\nrefinements erased in sort position, I64 as Int under a 64-bit domain\naxiom, F64/Text/Bytes as uninterpreted sorts with hash-named literals,\napplied data types monomorphized to Loom.D<sha256> datatypes, stored\nreferences uninterpreted unless a toolchain interpretation table maps\nthem onto a closed Core+Ints allowlist with call-site linearity checks,\nand a fixed command order ending in (assert (not goal)) (check-sat).\n\nprototype/refinements.py implements those rules with path-aware errors\nand explicit refusal of lam, perform, handle, fix, hole, partial\napplication, effectful references, function/capability sorts, and\npolymorphic constructors. No solver dependency: the module emits text\nand the tests validate it structurally through the existing sexpr\nreader.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
42ffcdd	author	Will Norris
42ffcdd	added	1
42ffcdd	deleted	0
42ffcdd	files	1
42ffcdd	body	A1 evidence flattened a statistical claim to a run count, so 10^6 draws\nfrom a narrow generator outranked 10^3 from an adversarial one by\narithmetic on n alone. Specify the property payload as a deterministic\nCBOR array carrying a failure-probability bound, its confidence, and the\ngenerator the bound is relative to, with probabilities as canonical\nrationals so payload bytes stay memo-ledger stable.\n\nOrder A1 as a partial order over (generator, bound, confidence); monotone\nassurance now refuses both weakening and incomparability. The accept/\nrefuse decision stays two-valued -- only the threshold inputs are\nnumeric. Narrow open problem 6 to the policy object format, generator\ncomparability, further method families, and counterexample locality.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
7776d05	author	Will Norris
7776d05	added	1
7776d05	deleted	0
7776d05	files	1
fcb34bf	author	Will Norris
fcb34bf	added	1
fcb34bf	deleted	0
fcb34bf	files	1
fcb34bf	body	Synthesized lambdas checked their body against the current ambient row\nwhile claiming an empty row, letting an effectful closure escape a\nhandler typed as pure. Bodies now synthesize under the empty allowance;\nlatent effects require an annotated row. Also reject handling\noperation-less abilities (div stays a row marker per SPEC §2.5), key\narm-mismatch rewrapping on the arm body path, and drop a redundant\ndeep copy in operation_signature.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
233b719	author	Will Norris
233b719	added	1
233b719	deleted	0
233b719	files	1
e9944dc	author	Will Norris
e9944dc	added	1
e9944dc	deleted	0
e9944dc	files	1
92bebcb	author	Will Norris
92bebcb	added	1
92bebcb	deleted	0
92bebcb	files	1
b442b6c	author	Will Norris
b442b6c	added	1
b442b6c	deleted	0
b442b6c	files	1
e22627a	author	Will Norris
e22627a	added	6
e22627a	deleted	0
e22627a	files	1
-->
