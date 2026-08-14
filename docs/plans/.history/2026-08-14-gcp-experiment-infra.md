| Date | Change |
|------|--------|
| [2026-08-13](https://github.com/wbniv/loom/commit/d163d64) | Add the GCP experiment runner |

<!--history-meta v1
d163d64	author	Will Norris
d163d64	added	468
d163d64	deleted	0
d163d64	files	1
d163d64	body	The AWS stack is waiting on an EC2 GPU allocation; the GCP trial project has\n$300 of credits, a granted L4 quota and Spot L4s at $0.25/h. This is its twin:\nsame artifact flow, same two-stage apply, same pinned llama.cpp, so a Phase A\nnumber from either cloud is comparable with the other.\n\nDecisions worth knowing:\n\n- Auth is a short-lived token from `gcloud auth print-access-token`, exported\n  as GOOGLE_OAUTH_ACCESS_TOKEN and refreshed before *every* terraform call.\n  Tokens live an hour and a run lasts two, so once at the top would be dead by\n  teardown. No application-default credentials, no key file on disk.\n- Deep Learning VM image (common-cu124-ubuntu-2204-py310), for the same reason\n  the AWS side uses the DL Base AMI: nvcc and the driver are already baked, so\n  the build starts immediately instead of paying 15-20 GPU-minutes per run.\n- No bootstrap/ root. GCS locks on the state object, so the backend is one\n  bucket, created idempotently by the driver's preflight.\n- No tf-safe-apply.sh. Its lock diagnosis is DynamoDB-specific and it requires\n  the aws CLI.\n- guest_accelerator is off by default: G2 carries its L4 implicitly, and\n  restating it is a known perpetual-diff source.\n- Quota preflight names GPUS_ALL_REGIONS and the regional L4 metric up front,\n  because a zero quota otherwise fails the apply minutes in with an opaque id.\n\nVerified offline: terraform fmt, validate (init -backend=false) on both\nconfigurations, bash -n + shellcheck on the driver and on the rendered startup\nscript, and the quota parser against canned payloads. No GCP API was called.\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015fUQnZN5JKnMMQTCsEwvxL
-->
