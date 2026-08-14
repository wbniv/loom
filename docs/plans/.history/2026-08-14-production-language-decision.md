| Date | Change |
|------|--------|
| [2026-08-14](https://github.com/wbniv/loom/commit/1c4b585) | Decide the production implementation language: Rust, migration deferred |

<!--history-meta v1
1c4b585	author	Will Norris
1c4b585	added	587
1c4b585	deleted	0
1c4b585	files	1
1c4b585	body	Scored Rust, Zig, and Go in full against the TODO's eight criteria plus the\nmeasured workload, with OCaml screened for type-system fit. Rust wins 114/130\nagainst Zig 86, Go 83, OCaml 79, status-quo Python 71, and wins all three\nadversarial re-weightings.\n\nThe measured datum reframes the schedule: B1's masker is 0.19 ms/token warm\nagainst ~700 ms CPU decode (0.03%) and ~1% against GPU decode. Trigger (d)'s\n25% threshold is missed by 25x in every single-stream configuration; only\nbatch serving reaches it, and whether it does turns on a T_step(B) slope\nthis study cannot measure. So the verdict splits: Rust decided now, migration\ngated on M1-M4, with free-threaded CPython as the correct first response to\nM1 rather than a port.\n\nMigration sequenced in contract terms: L0 differential harness, then parser\n(the only byte-output layer), declarations promoted ahead of references,\nscope, references, typecheck 1.1, refinements, policies. The store is\ngreenfield Rust and costs no migration debt.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
-->
