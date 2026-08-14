| Date | Change |
|------|--------|
| [2026-08-14](https://github.com/wbniv/loom/commit/475999a) | Fix a brittle anchor and a split path in the Phase B plan |
| [2026-08-14](https://github.com/wbniv/loom/commit/55a5e7c) | Add the type-goal pruner, Phase B2's profile-directed layer |
| [2026-08-13](https://github.com/wbniv/loom/commit/a416e60) | Build Phase B B1: the profile-independent masker core |
| [2026-08-13](https://github.com/wbniv/loom/commit/9d0a155) | Triage Phase B plan deferral |
| [2026-08-13](https://github.com/wbniv/loom/commit/d9a5368) | Plan experiment Phase B with a B1/B2 split |

<!--history-meta v1
475999a	author	Will Norris
475999a	added	8
475999a	deleted	5
475999a	files	1
475999a	body	The B2 decisions heading carried a U+2011 date, so the anchor pointing at it\nwas not the one a renderer generates; and the startup-script path was broken\nacross a line inside a code span, which renders with a space in the middle.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
55a5e7c	author	Will Norris
55a5e7c	added	333
55a5e7c	deleted	5
55a5e7c	files	1
55a5e7c	body	Phase A's gate put typecheck at the top of the failure distribution (590 of\n1,671 grammar-constrained draws, against parse 523, scope 268, references 115),\nlocalized at definition.term (x330). This is the pruner that row asks for.\n\nTwo facts make it possible. `root ::= "(def " type " " term ")"` finishes a\ndefinition's declared type before its term begins, so the checker's goal at\ndefinition.term is knowable from a byte prefix; and `transcode.parse_source`\nrefuses a non-canonical surface, so an accepted definition's bytes *are* the\ncanonical rendering of its IR - which makes a byte-equality veto a proof rather\nthan a guess. Five vetoes follow, each mirroring a rule in typecheck.py: forced\n`lam`/`fix` annotations, head feasibility, literal kind words, `con` data\nhashes, and a `ref` digest universe filtered by goal type. Comparisons are on\nrefinement erasure, so no proof depends on whether a caller wires the\nsubsumption collector.\n\nPRUNER_NAMES is reordered to the profile: goal-type, de-bruijn, ref-hash.\n_veto_layer credits the first refusing layer, so this makes mask_pruned_by_layer\nread as what the dominant checker layer removed.\n\nCompletion pressure is ruled out, with reasons recorded rather than skipped: the\nonly sound token bound is min_bytes/max_piece_len (~24x too loose to steer), it\nwould put remaining budget in the mask cache key, and closing early relabels a\ntruncation as a typecheck failure rather than creating an acceptance.\n\nAlso: R5 is now produced by the run report from a config-recorded baseline\nsummary, with predictions 4 and 5 scored on the page; and the GCP startup script\nreads its transport out of the operator's config, because condition 4 needs the\nin-process llama-cpp backend and the script hardcoded llama-server.\n\nVerified: 541 tests pass; 26/26 corpus fixtures walk under four tokenizations\nwith the goal layer active, zero violations and zero liveness fallbacks; live\nsanity over the real 151,936-token vocabulary reproduces corpus/bool/not\nbyte-identically in 29 tokens, with goal-type pruning 19,529 tokens against\nde Bruijn's 902.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
a416e60	author	Will Norris
a416e60	added	306
a416e60	deleted	11
a416e60	files	1
a416e60	body	Condition 4 (`gbnf+typemask`) masks logits at every decoding step, so syntax\nerrors and the pruned classes of type error become unreachable rather than\nrejected after the fact.\n\nTwo layers, both byte oracles, composed into one memoized transition and walked\nonce per step over a trie of the token pieces:\n\n  experiment/gbnf.py     an incremental prefix automaton over `loom.gbnf`,\n                         compiled from the file at run time.\n  experiment/masker.py   the incremental type state (atom kind, de Bruijn term\n                         and type depths, prenex forall count) plus pluggable,\n                         individually toggled and individually timed pruners:\n                         `ref-hash` and `de-bruijn`.\n\nThe syntax layer is ours rather than llama.cpp's so R4's soundness suite runs\nwith no model on every `task prototype:test`, and so the type layer can share\nthe same byte feed. Soundness is the rule everything else is subordinate to: a\npruner may veto a byte only where it can prove no completion of the current atom\nreaches an accepted definition, and where it cannot prove — a `handle` operation\nbody, whose binder count needs ability resolution a byte prefix does not carry —\nit abstains and the fact is recorded. If the type layer would empty a non-empty\nsyntax mask the step falls back to syntax alone and counts the fallback.\n\nTransport: R1's candidate 3, `experiment/llama_ffi.py`, ctypes over the pinned\nllama.cpp build's `libllama.so` — the same engine Phase A serves with. The\nexpected winner, `llama-cpp-python`, ships source-only (checked 0.3.27-0.3.34),\nso it would mean building a second differently pinned copy of llama.cpp, which\nis the engine identity R1's comparability criterion holds fixed. Its "most work"\nobjection evaporated once the mask stopped needing llama.cpp's grammar engine.\nIt refuses any tokenizer whose detokenization is not concatenation of token\npieces, because that is what the byte-level mask rests on.\n\nVerification, recorded in the plan: `task prototype:test` 407 tests OK; the\nsoundness suite walks all 26 corpus fixtures under four tokenizations with the\nfixture's own next token never masked and zero fallbacks; the live in-process\nsanity walks all 26 under Qwen2.5-Coder's own 151,936-token vocabulary with zero\nviolations over 11,341 mask steps, and one 16-token masked draw at temperature 0\nput mask overhead at ~0.19 ms/token warm against ~700 ms/token of CPU decode.\n\nPhase A is untouched: conditions 1-3 keep their records, summary and report\nbyte-for-byte, and the masking block and report section appear only when\ncondition 4 ran. B2 remains gated on Phase A's failure distribution.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
9d0a155	author	Will Norris
9d0a155	added	3
9d0a155	deleted	0
9d0a155	files	1
9d0a155	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
d9a5368	author	Will Norris
d9a5368	added	120
d9a5368	deleted	0
d9a5368	files	1
d9a5368	body	B1 (profile-independent masker core) is dispatchable now; B2 (pruner\npriority and the condition-4 run) stays gated on Phase A's failure\ndistribution.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
-->
