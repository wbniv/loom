| Date | Change |
|------|--------|
| [2026-08-14](https://github.com/wbniv/loom/commit/de317f2) | Bring plans and the source-code investigation current with Phase B events |
| [2026-08-14](https://github.com/wbniv/loom/commit/7e68eb7) | Give the masked transport a context and a GPU, and stop it re-tying batch to n_ctx |
| [2026-08-14](https://github.com/wbniv/loom/commit/a3ebdf3) | Record the condition-4 OOM incident and its fix in the Phase B plan |
| [2026-08-14](https://github.com/wbniv/loom/commit/a0f7137) | Plumb n_gpu_layers through the in-process transport |
| [2026-08-14](https://github.com/wbniv/loom/commit/23b6c2f) | Record the condition-4 launch and close out the build-cache plan |
| [2026-08-14](https://github.com/wbniv/loom/commit/475999a) | Fix a brittle anchor and a split path in the Phase B plan |
| [2026-08-14](https://github.com/wbniv/loom/commit/55a5e7c) | Add the type-goal pruner, Phase B2's profile-directed layer |
| [2026-08-13](https://github.com/wbniv/loom/commit/a416e60) | Build Phase B B1: the profile-independent masker core |
| [2026-08-13](https://github.com/wbniv/loom/commit/9d0a155) | Triage Phase B plan deferral |
| [2026-08-13](https://github.com/wbniv/loom/commit/d9a5368) | Plan experiment Phase B with a B1/B2 split |

<!--history-meta v1
de317f2	author	Will Norris
de317f2	added	7
de317f2	deleted	1
de317f2	files	1
de317f2	body	Launch log through the us-east1 stockouts and zone hunt; M1 evidence\ncaveat (salvaged partial's mask numbers are defect symptoms, not the\nmeasurement); Phase A postscript on the english-as-source analysis.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
7e68eb7	author	Will Norris
7e68eb7	added	35
7e68eb7	deleted	0
7e68eb7	files	1
7e68eb7	body	Two landmines sitting just past the point attempt 1 died, both found while\nfixing the OOM and both fatal to a relaunch.\n\nn_ctx was far too small. Measured with the real tokenizer, the longest prompt\nper regime is none 279, few_shot 1,843, full_corpus 11,906, held_out 11,959\ntokens; phase_b.config.json shipped n_ctx 4096. LlamaCppBackend does refuse a\nprompt that will not fit, naming the config key, so this would have stopped the\nrun rather than corrupted it -- but it would have stopped it at the third\nregime, after paying for the first two. Raised to 16384, matching what Phase A\nserved with, and a test now computes the requirement from the prompts so the\nconfig cannot drift back under it.\n\nThe masked transport was pinned to CPU in committed code: llama_ffi carried\n`params.n_gpu_layers = 0` with the comment "this box is CPU-only, by the plan",\nwhich was true on the laptop it was written on and catastrophic on the run host\n-- a relaunch from committed code would have run the entire matrix on four vCPUs\nwith a 24 GB L4 idle. Now a config knob defaulting to -1, llama.cpp's own "all\nlayers, falling back where there is no device", which is correct on both.\nAttempt 1 reportedly ran at 99-100% SM, which committed code cannot do, so the\nbox was carrying a local patch; attempt 2 should run from committed code.\n\nAlso: _recreate runs once per draw and was building fresh context params, so it\nsilently dropped n_threads and re-tied the batch to n_ctx after the very first\ndraw. It now reuses the params built at load. And batch sizes no longer track\nn_ctx (2048/512, llama.cpp's defaults) -- sizing a compute buffer for a 16k\nmicro-batch that never occurs is pure allocation.\n\nVerified: 549 tests pass; live mask-sanity is byte-for-byte unchanged (26/26\nfixtures, 0 violations, same definition reproduced, same per-layer prune counts),\nso none of this moves the mask.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
a3ebdf3	author	Will Norris
a3ebdf3	added	111
a3ebdf3	deleted	5
a3ebdf3	files	1
a3ebdf3	body	Attempt 1's run log: what the salvaged records showed (mask cost spiky rather\nthan monotone, concentrated in the five draws that contain a text literal), the\nmeasured cause, the before/after table, the two-part fix, the regression guard,\nand the attribution -- the defect is B1-substrate, not B2, since the transition\ncount at a literal is identical with syntax only, with B1's pruners and with\nB2's.\n\nAlso records what the incident did not turn up: the run's 81 liveness fallbacks\nare the documented goal-layer behaviour, not a defect.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
a0f7137	author	Will Norris
a0f7137	added	13
a0f7137	deleted	0
a0f7137	files	1
a0f7137	body	llama_ffi hardcoded n_gpu_layers=0 from its CPU-laptop origin, so the\nfirst condition-4 launch decoded the 7B on 4 vCPUs with the L4 idle\n(caught at 68 records: dmon flat-zero, 37s/record vs ~6s expected).\nConfig -> RunConfig -> make_backend -> LlamaCppBackend -> LlamaModel,\nand the GCP startup script injects the instance's NGL on the masked\npath. Run killed and relaunched; CPU records discarded as incomparable.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
23b6c2f	author	Will Norris
23b6c2f	added	10
23b6c2f	deleted	3
23b6c2f	files	1
23b6c2f	body	Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
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
