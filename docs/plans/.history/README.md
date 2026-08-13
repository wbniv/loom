| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/b5c7b9c) | Type fix and ref in the match layer |
| [2026-08-13](https://github.com/wbniv/loom/commit/3be2146) | Seed the bootstrap corpus for prior starvation |
| [2026-08-13](https://github.com/wbniv/loom/commit/a413e7e) | Add policy-object validation and satisfaction-checking prototype |
| [2026-08-13](https://github.com/wbniv/loom/commit/a19d194) | Close effect-consistency review follow-ups |
| [2026-08-13](https://github.com/wbniv/loom/commit/64e1cf8) | Specify the namespace policy object format |
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
b5c7b9c	author	Will Norris
b5c7b9c	added	1
b5c7b9c	deleted	0
b5c7b9c	files	1
b5c7b9c	body	`fix` (tag 10) and `ref` (tag 1) passed scope and reference validation\nbut had no typing rule, capping every recursive corpus definition at the\nstructural tier (bootstrap-corpus finding 3).\n\n`fix T measure body` requires T to equal the expected type and to be a fn\ntype; the measure is checked at the current environment against\n`fn D () I64`, and the body against T with the recursive value at index\n0 under the unchanged ambient row. The `terminates` obligation is not\ndischarged here — §2.5/§6.2 termination stays oracle evidence.\n\n`ref h` resolves its type through an injected resolver threaded the way\nscope.py threads its ability-arity resolver, and refuses explicitly when\nno resolution exists rather than guessing. No def-object store invented.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
3be2146	author	Will Norris
3be2146	added	1
3be2146	deleted	0
3be2146	files	1
3be2146	body	SPEC.md §13 open problem 1 is the one input §8.4 cannot mask its way to:\nwithout a corpus, a masked model emits well-formed, type-plausible junk.\nThis lands a first tranche.\n\nUnison base is the primary source. F* matches Loom's type system better —\nrefinements match §3.2 and `decreases` is §2.5's measure already written\ndown — but almost every verified F* signature is a dependent arrow, and\n§2.3.1 has no dependent arrows. Dropping the dependency does not lose\ndecoration, it changes the proposition, which manufactures open problem 2\ninside the artifact whose whole purpose is to be exemplary. Unison instead\nmatches Loom's *term* language, which is what §8.4 needs priors over, and\nhas no typeclasses, so nothing is elaborated away.\n\nHand-transpiling the seed set established three limits of v0.1 by\nconstruction, each now pinned by a negative test:\n\n- A definition cannot be polymorphic. §2.3.1 binds `forall` inside the type\n  only and checks a definition's term at type depth 0, but `lam` is fully\n  annotated, so a rank-1 signature's own parameter annotation is out of\n  scope. `forall` is inhabitable by `hole`, never by `lam`.\n- `Bool` has no elimination form. §3.1.1 requires a nominal `data` scrutinee\n  and §2.2 makes `Bool` a base type, so there is no conditional and\n  filter/takeWhile/not are inexpressible.\n- `fix` and `ref` pass scope and reference checking but have no rule in the\n  match layer, so recursion stops at a structural tier.\n\nTranche 1 is therefore monomorphic, branch-free, and recursion-free.\nFixtures live in prototype/corpus/ rather than examples/, whose count\ntest_roundtrip pins at five and whose provenance is spec illustration.\nThe manifest is a §5.2 meta-object table, so the (spec-text,\ncanonical-surface) pairs a §8.4 few-shot prompt needs need no second\nformat. Each entry declares its validation tier and the test enforces it\nboth ways, so a deferral cannot outlive its cause.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
a413e7e	author	Will Norris
a413e7e	added	1
a413e7e	deleted	0
a413e7e	files	1
a413e7e	body	Close the namespace-policy plan's recorded residual risk that §5.3.1/§5.3.2\nhad no executable check: prototype/policies.py canonically validates policy\nobjects, checks E ⊒ R requirement satisfaction (§6.1.2) and domination\n(§5.3.2), and pins the default-policy hash plus the §12 worked example's\narithmetic as tests.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
a19d194	author	Will Norris
a19d194	added	1
a19d194	deleted	0
a19d194	files	1
a19d194	body	Eight doc/test-level fixes from the 2026-08-13 effect-consistency change\nreview plus two later review notes: complete SPEC.md §3.1.2's expected-type\ncontext list, fix SPEC.md's stale status header, add a dedicated pinned test\nfor the direct-application effect rejection, correct the effect-purity\nchange review's resolution note (the rejection test actually already\nexisted, contrary to the later review's finding), document the GBNF\nvalidator build recipe, import the design sketch from outside the repo and\nrepair all broken ../docs/ references, reword §6.1.1's circular confidence\nclause, and record the F64 bitwise-equality design fork. No checker or\ntranslator behavior changed.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
64e1cf8	author	Will Norris
64e1cf8	added	1
64e1cf8	deleted	0
64e1cf8	files	1
64e1cf8	body	Close SPEC.md §13 open problem 6(a). `policy-ref` (§5.3), "the level the\npolicy allows" (§6.3), "policy-required properties" (§6.2), §11's assumption\ncount and §8.3's redraw budget were all normative uses of an object with no\nspecified format, which blocked any store implementation.\n\n- New object kind 6 `policy` (§4.3, §5.1), encoded `[6, policy-map]` — a\n  CBOR map with unsigned-integer keys where an absent key states no\n  constraint, and an unrecognized key rejects the object.\n- §5.3.1: ten keys; a closed obligation-kind registry; selectors as prefixes\n  of the (kind, detail) decomposition matching conjunctively with no\n  precedence; requirements as points in the §6.1.2 lattice with a mandatory\n  (bound, confidence, generator) triple at A1; injected `property.<name>`\n  obligations; global and per-ability assumption budgets.\n- §5.3.2: `POLICY` reserved as a leaf name; resolution walks strictly upward\n  and bottoms out at the pinned default policy `[6, {}]` = #901f33bd, so\n  nothing resolves in a circle; a descendant policy must dominate its\n  ancestor, so `policy-ref` is a complete audit record; policy amendment is\n  monotone unless the predecessor states `relax`, without which §6.3 is\n  defeatable in two individually-passing steps.\n- Surgical consistency edits to §3.4, §6.2, §6.3, §8.3, §9, §11 and §12,\n  which now shows `stats/POLICY`'s actual contents.\n- §13 open problem 6(a) narrowed to residue; the lease protocol stays open\n  problem 4 and generator comparability stays 6(b).\n\nPlan: docs/plans/2026-08-13-namespace-policy-object.md\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
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
