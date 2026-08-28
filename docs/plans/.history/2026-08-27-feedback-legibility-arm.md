| Date | Change |
|------|--------|
| [2026-08-27](https://github.com/wbniv/loom/commit/5b0e7f2) | Legibility arm configs + CPU stub gate: ALL CHECKS PASS, GPU gate open |
| [2026-08-27](https://github.com/wbniv/loom/commit/5a4d622) | Legibility seam landed; replay gate clears at 2,159/2,159 |
| [2026-08-27](https://github.com/wbniv/loom/commit/b072b6e) | Pre-register the feedback-legibility arm; triage the driver follow-ups |

<!--history-meta v1
5b0e7f2	author	Will Norris
5b0e7f2	added	61
5b0e7f2	deleted	0
5b0e7f2	files	1
5b0e7f2	body	Deliverable 4: legib_legible / legib_repr configs and the runlist as\nbyte-copies of decomp-redraft differing only in output_dir and\nnarrowing_note_render, pinned by difference in test_legibility_arm.py\n(which also asserts the source carries no render key, so the diff cannot\nbe vacuous). The AddressBookTest allowlist gains both configs — the same\nguard the model-scale configs hit in 5f697dc.\n\nDeliverable 3: legibility_stub_check.py — hole_elicitation_stub_check\nregression re-run unchanged (PASS), C2 protocol invariance (whole/redraft\ninert to the seam, byte-identical prompts under both renders in a\nscripted whole cell), config-difference checks, and a scripted stub cell\nper shipped config with C3 classification invariance and the per-arm leak\nsignature. ALL CHECKS PASS — output pasted into the plan; gate re-run\nindependently before this commit. Suite 947 green.\n\nCo-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_013ycMbBKz71NDfdtCACWEub
5a4d622	author	Will Norris
5a4d622	added	39
5a4d622	deleted	0
5a4d622	files	1
5a4d622	body	narrowing_note_render: surface|repr as a contextvars seam in typecheck's\n_render/_render_row — "repr" reproduces what all nine _fail sites did\nbefore 8ed72cd, "surface" is byte-identical to today's path when unset.\nConfig field, validation and per-cell set-site in the runner.\n\nThe launch gate (plan §3 deliverable 2): all 2,159 banked rejected draws\n(734 whole + 719 redraft + 706 holes) reproduce their pre-fix\nerror_message byte-identically under "repr", 0.00% leak and 0\nclassification changes under "surface". Raw output pasted into the plan.\nSuite 943 green; the gate tests re-run independently before this commit.\n\nCo-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_013ycMbBKz71NDfdtCACWEub
b072b6e	author	Will Norris
b072b6e	added	452
b072b6e	deleted	0
b072b6e	files	1
b072b6e	body	The plan discharges the Watch entry the model-scale arm's §6 row 3 handed\nback to: two concurrent arms over a narrowing_note_render seam (surface vs\nrepr), redraft protocol, 64 cells/arm. Primary is L1 repair locality (MDE\nRR 1.20, power 0.93 at 1.25x); draw-level funnel acceptance is demoted to\ndescriptive with its impossibility stated (MDE RR 1.75 at this budget).\nThe banked decomp baseline is proven cleanly pre-fix but kept only as a\ncalibration anchor — concurrency buys the real control for ~$1.00.\nCeiling $4.55, degradation is fewer cells never fewer arms.\n\nTODO: feedback-legibility-arm and driver-fetch-loss to Done; the legib\ndeliverables ranked into Open (T1/T2, run T5-gated), the driver plan's\nauto-captured deferrals triaged into runner-self-delete and\naws-driver-port, and bucket-restore opened as T5 pending Will's go.\n\nCo-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_013ycMbBKz71NDfdtCACWEub
-->
