| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/9a58037) | Specify the extern object encoding |
| [2026-08-13](https://github.com/wbniv/loom/commit/b5c7b9c) | Type fix and ref in the match layer |
| [2026-08-13](https://github.com/wbniv/loom/commit/3be2146) | Seed the bootstrap corpus for prior starvation |
| [2026-08-13](https://github.com/wbniv/loom/commit/a413e7e) | Add policy-object validation and satisfaction-checking prototype |
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
9a58037	author	Will Norris
9a58037	added	15
9a58037	deleted	2
9a58037	files	1
9a58037	body	§11 promised an `extern` — a foreign artifact pinned by content hash, wrapped\nin a Loom type with mandatory A0 evidence — and §5.3.1 already counted one\nagainst a namespace's assumption budget, but §4.3 had no kind tag for it, so\nnothing could be stored. That blocked tranche 2 of the bootstrap corpus:\nLoom v0.1 has no `+` term, so its five assumed-base definitions (I64.add/sub/\neq/lt, List.size) and every recursive list definition measured by List.size\nwere unwritable.\n\nKind tag 7, shape `[7, type, artifact, abi]`, specified in a new §5.1.3. The\ntype is closed and monomorphic; the declared effect row is itself the A0\nassumption, and every ability it names must be matched by a `cap` parameter so\n§2.4's blast-radius bound survives the boundary. There is no nominal key —\n`(artifact, abi)` is the discriminator, so two externs stating the same call\nare one object and share one review. Terms reference an extern through the\nexisting `ref`, which resolves to a type and stops. §3.2.1's interpretation\ntable admits extern hashes, which is what makes tranche-2 arithmetic provable\nat all, under the same empty-row and signature checks as any other reference.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
b5c7b9c	author	Will Norris
b5c7b9c	added	2
b5c7b9c	deleted	1
b5c7b9c	files	1
b5c7b9c	body	`fix` (tag 10) and `ref` (tag 1) passed scope and reference validation\nbut had no typing rule, capping every recursive corpus definition at the\nstructural tier (bootstrap-corpus finding 3).\n\n`fix T measure body` requires T to equal the expected type and to be a fn\ntype; the measure is checked at the current environment against\n`fn D () I64`, and the body against T with the recursive value at index\n0 under the unchanged ambient row. The `terminates` obligation is not\ndischarged here — §2.5/§6.2 termination stays oracle evidence.\n\n`ref h` resolves its type through an injected resolver threaded the way\nscope.py threads its ability-arity resolver, and refuses explicitly when\nno resolution exists rather than guessing. No def-object store invented.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
3be2146	author	Will Norris
3be2146	added	23
3be2146	deleted	0
3be2146	files	1
3be2146	body	SPEC.md §13 open problem 1 is the one input §8.4 cannot mask its way to:\nwithout a corpus, a masked model emits well-formed, type-plausible junk.\nThis lands a first tranche.\n\nUnison base is the primary source. F* matches Loom's type system better —\nrefinements match §3.2 and `decreases` is §2.5's measure already written\ndown — but almost every verified F* signature is a dependent arrow, and\n§2.3.1 has no dependent arrows. Dropping the dependency does not lose\ndecoration, it changes the proposition, which manufactures open problem 2\ninside the artifact whose whole purpose is to be exemplary. Unison instead\nmatches Loom's *term* language, which is what §8.4 needs priors over, and\nhas no typeclasses, so nothing is elaborated away.\n\nHand-transpiling the seed set established three limits of v0.1 by\nconstruction, each now pinned by a negative test:\n\n- A definition cannot be polymorphic. §2.3.1 binds `forall` inside the type\n  only and checks a definition's term at type depth 0, but `lam` is fully\n  annotated, so a rank-1 signature's own parameter annotation is out of\n  scope. `forall` is inhabitable by `hole`, never by `lam`.\n- `Bool` has no elimination form. §3.1.1 requires a nominal `data` scrutinee\n  and §2.2 makes `Bool` a base type, so there is no conditional and\n  filter/takeWhile/not are inexpressible.\n- `fix` and `ref` pass scope and reference checking but have no rule in the\n  match layer, so recursion stops at a structural tier.\n\nTranche 1 is therefore monomorphic, branch-free, and recursion-free.\nFixtures live in prototype/corpus/ rather than examples/, whose count\ntest_roundtrip pins at five and whose provenance is spec illustration.\nThe manifest is a §5.2 meta-object table, so the (spec-text,\ncanonical-surface) pairs a §8.4 few-shot prompt needs need no second\nformat. Each entry declares its validation tier and the test enforces it\nboth ways, so a deferral cannot outlive its cause.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
a413e7e	author	Will Norris
a413e7e	added	15
a413e7e	deleted	0
a413e7e	files	1
a413e7e	body	Close the namespace-policy plan's recorded residual risk that §5.3.1/§5.3.2\nhad no executable check: prototype/policies.py canonically validates policy\nobjects, checks E ⊒ R requirement satisfaction (§6.1.2) and domination\n(§5.3.2), and pins the default-policy hash plus the §12 worked example's\narithmetic as tests.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
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
