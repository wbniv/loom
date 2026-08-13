| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/9a58037) | Specify the extern object encoding |

<!--history-meta v1
9a58037	author	Will Norris
9a58037	added	347
9a58037	deleted	0
9a58037	files	1
9a58037	body	§11 promised an `extern` — a foreign artifact pinned by content hash, wrapped\nin a Loom type with mandatory A0 evidence — and §5.3.1 already counted one\nagainst a namespace's assumption budget, but §4.3 had no kind tag for it, so\nnothing could be stored. That blocked tranche 2 of the bootstrap corpus:\nLoom v0.1 has no `+` term, so its five assumed-base definitions (I64.add/sub/\neq/lt, List.size) and every recursive list definition measured by List.size\nwere unwritable.\n\nKind tag 7, shape `[7, type, artifact, abi]`, specified in a new §5.1.3. The\ntype is closed and monomorphic; the declared effect row is itself the A0\nassumption, and every ability it names must be matched by a `cap` parameter so\n§2.4's blast-radius bound survives the boundary. There is no nominal key —\n`(artifact, abi)` is the discriminator, so two externs stating the same call\nare one object and share one review. Terms reference an extern through the\nexisting `ref`, which resolves to a type and stops. §3.2.1's interpretation\ntable admits extern hashes, which is what makes tranche-2 arithmetic provable\nat all, under the same empty-row and signature checks as any other reference.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
-->
