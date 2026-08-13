| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/8e85730) | Re-source corpus attributions to MIT-licensed unisonweb/unison |
| [2026-08-13](https://github.com/wbniv/loom/commit/3be2146) | Seed the bootstrap corpus for prior starvation |

<!--history-meta v1
8e85730	author	Will Norris
8e85730	added	17
8e85730	deleted	11
8e85730	files	1
8e85730	body	The standalone unisonweb/base mirror carries no license file; the main\nrepository the definitions originate from is plain MIT. Attribution is\n§5.2 metadata and never enters identity, so this is a citation-only\nchange: no fixture bytes or pinned hashes move. Closes the licensing\nhold on scaling the corpus.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
3be2146	author	Will Norris
3be2146	added	464
3be2146	deleted	0
3be2146	files	1
3be2146	body	SPEC.md §13 open problem 1 is the one input §8.4 cannot mask its way to:\nwithout a corpus, a masked model emits well-formed, type-plausible junk.\nThis lands a first tranche.\n\nUnison base is the primary source. F* matches Loom's type system better —\nrefinements match §3.2 and `decreases` is §2.5's measure already written\ndown — but almost every verified F* signature is a dependent arrow, and\n§2.3.1 has no dependent arrows. Dropping the dependency does not lose\ndecoration, it changes the proposition, which manufactures open problem 2\ninside the artifact whose whole purpose is to be exemplary. Unison instead\nmatches Loom's *term* language, which is what §8.4 needs priors over, and\nhas no typeclasses, so nothing is elaborated away.\n\nHand-transpiling the seed set established three limits of v0.1 by\nconstruction, each now pinned by a negative test:\n\n- A definition cannot be polymorphic. §2.3.1 binds `forall` inside the type\n  only and checks a definition's term at type depth 0, but `lam` is fully\n  annotated, so a rank-1 signature's own parameter annotation is out of\n  scope. `forall` is inhabitable by `hole`, never by `lam`.\n- `Bool` has no elimination form. §3.1.1 requires a nominal `data` scrutinee\n  and §2.2 makes `Bool` a base type, so there is no conditional and\n  filter/takeWhile/not are inexpressible.\n- `fix` and `ref` pass scope and reference checking but have no rule in the\n  match layer, so recursion stops at a structural tier.\n\nTranche 1 is therefore monomorphic, branch-free, and recursion-free.\nFixtures live in prototype/corpus/ rather than examples/, whose count\ntest_roundtrip pins at five and whose provenance is spec illustration.\nThe manifest is a §5.2 meta-object table, so the (spec-text,\ncanonical-surface) pairs a §8.4 few-shot prompt needs need no second\nformat. Each entry declares its validation tier and the test enforces it\nboth ways, so a deferral cannot outlive its cause.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
-->
