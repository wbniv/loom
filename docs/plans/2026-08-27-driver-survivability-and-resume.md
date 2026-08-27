# Remote-driver survivability: durable log, run manifest, resume path

**Date:** 2026‑08‑27
**Script:** `scripts/run-remote-experiment-gcp.sh`
**TODO entry:** *(not filed by this agent — boundaries forbid touching `TODO.md`; see "Follow‑ups" below for the line to add)*

---

## 1. What happened

The `scale14` model-scale run (2026‑08‑26/27) finished perfectly on the remote side and
was lost on the local side: no fetch, no teardown, no local driver log.

| Time (local, ‑06:00) | Event | Evidence |
|---|---|---|
| 00:22:58 | first (Spot) driver killed with `kill -9` by the operator, deliberately | session JSONL `toolu_0177qRN34ZsRBodJHJHBfgus`, `2026-08-27T06:22:58.929Z` |
| 00:23:35 | on‑demand driver relaunched, `nohup … &`, `RUN_ID=20260827T062338Z` | session JSONL `toolu_01BqPiPhJgRkr9SGkq2Le7fw` |
| 00:24:15 | last `gcloud` invocation of apply 2/2 — the instance is up, driver enters the wait loop | `~/.config/gcloud/logs/2026.08.27/00.24.15.201588.log` |
| 00:29:08 | last event recorded in the session | session JSONL final record |
| 01:58 | session JSONL last written (no new record) | file mtime |
| **02:19:56** | **laptop suspends (s2idle) and never resumes in that boot** | `journalctl -b -1`, last line `PM: suspend entry (s2idle)` |
| 05:03:34 | remote runner writes `status/20260827T062338Z.txt` = `SUCCEEDED`, uploads everything | `gsutil ls -l gs://loom-diversity-artifacts-19b81040/status/` |
| 11:27:05 | **cold boot** — new boot id, no shutdown records anywhere in the previous boot | `journalctl --list-boots`, `journalctl -b -1 \| grep -c 'Reached target Shutdown'` → 0 |
| ~11:50 | results pulled by hand; instance found TERMINATED‑not‑deleted, 150 GB disk billing | operator |

**Root cause.** The driver was in its 60 s poll loop when the host suspended at
02:19:56 and lost power while suspended — a boot that ends mid‑`PM: suspend entry` with
zero shutdown records, followed by a *new* boot id nine hours later, is power removed from
a sleeping machine, not an orderly shutdown. Processes frozen by s2idle and then
annihilated by power loss receive no signal at all, so `bash` never ran the `EXIT` trap
that `push_cleanup teardown` hangs off. The remote run completed 2 h 44 min into the dead
window; the machine came back 6 h 23 min after that.

**Why the trap is the right thing to blame and the wrong thing to fix.** Measured, not
assumed — a probe against the real `cleanup-stack.sh`, now kept as block 4 of
`scripts/tests/test-driver-resume.sh` so the claim cannot rot:

```
SIGTERM  exit=143  trap_ran=1
SIGHUP   exit=129  trap_ran=1
SIGINT   exit=0    trap_ran=1
SIGKILL  exit=137  trap_ran=0
```

The EXIT trap already fires for every catchable death. Adding `trap … TERM HUP INT` would
change nothing. Only `SIGKILL` and host death skip it, and no trap can cover those. This
also *excludes* the "session exit sent SIGHUP/SIGTERM and killed the driver" story: had
that happened, `teardown()` would have run and the instance would have been gone. It was
not gone.

**Evidence boundary (stated plainly).** I cannot *prove* the driver was still alive at
02:19:56 — its stdout went to `/tmp/…/scratchpad/scale14-run2.log`, wiped by the reboot,
and the wait loop's `gsutil cat` leaves no on‑disk trace. Ruled out: OOM (`journalctl -b -1`
has no `oom-kill`/`Killed process` records) and the operator's `kill -9` (fired 37 s
*before* this driver started). Not ruled out: Claude Code `SIGKILL`ing background children
when the session ended around 01:58. That variant is immaterial to the outcome — the host
was dead from 02:20 to 11:27, so no fetch or teardown could have happened either way — and
it is in the same defect class: **the waiter dies with its parent or its host, and nothing
downstream is recoverable because nothing recorded what to recover.**

## 2. What the fix has to buy

1. The loss must be **cheap to undo**, because the class of cause (host death) cannot be
   engineered away on a laptop. Recovery must be one command, not nine remembered flags.
2. The driver must **record what recovery needs** — above all `RUN_ID`, which was
   auto‑generated and discoverable only from a log that did not survive.
3. The driver must be **diagnosable at all** after the fact: a durable local log from the
   first line.
4. The waiter should **survive its parent** where that is possible, since the one variant I
   could not exclude is exactly that.

## 3. Design

**Chosen: a re‑entry point in the same script, plus self‑documentation.**

- `--resume` skips phases 1–3 (bucket apply, uploads, launch) and enters the existing
  wait → fetch → teardown path unchanged. `--fetch-only` is `--resume` with
  `--timeout-seconds 0`: the deadline is already past, the loop runs zero iterations, and
  the post‑loop grace poll (already there since the 2026‑08‑14 suspend) reads the marker.
  No new fetch logic — the runlist walk stays the single copy it is today.
- `--resume-from FILE` reads a **run manifest** the driver writes at launch
  (`prototype/runs/logs/driver-<tag>.json`) and repopulates every setting resume needs, so
  recovery is `--resume-from prototype/runs/logs/driver-scale14.json`. Flags given after it
  override it.
- **Durable log**: `exec > >(tee -a "$DRIVER_LOG") 2>&1` immediately after argument
  parsing, landing in `prototype/runs/logs/driver-<tag>.log`, opening with a timestamped
  header carrying the full argv and the resolved `RUN_ID`. `--log-file` overrides.
- `--detach` re‑execs under `setsid nohup` with `--run-id` and `--log-file` pinned (so the
  child cannot mint a *different* timestamp `RUN_ID` than the parent announced), prints the
  pid and log path, and returns.

**Teardown safety in resume mode.** The driver did not launch this instance, so it may not
own it. `teardown()` is armed unconditionally in normal mode (unchanged) but in resume mode
only once the aggregate status marker has been read — i.e. only when the run is provably
over. `--teardown-anyway` forces it. Without this, `--fetch-only` against a run that is
still in flight would destroy a live GPU.

**Rejected: a separate `scripts/fetch-remote-results.sh`.** It would need its own copy of
the bucket layout, the per‑arm runlist walk and the teardown var set. Those are precisely
the three things that already drifted once: the comment above section 5 of
`run-remote-experiment-gcp.sh` records the 2026‑08‑25/26 bug where the fetch path read only
the aggregate prefix and silently downloaded nothing per arm, found by hand *twice*. A
second copy would re‑acquire that bug independently. One script, one re‑entry point.

**Rejected: trapping `TERM`/`HUP`/`INT` as well as `EXIT`.** Measured above — the EXIT trap
already fires for all three. It would be motion, not a fix.

**One seam added, reluctantly:** `LOOM_DRIVER_BIN_OVERRIDE`. The driver's second line
is `export PATH="$HOME/.local/bin:$PATH"`, an unconditional prepend that outranks anything
the caller put on `PATH` — so a test harness cannot substitute `terraform`, `gsutil` or
`gcloud` at all. That is not a testing inconvenience, it is a property worth naming: a
driver whose tool resolution cannot be redirected cannot be exercised offline, and the only
way to find out what it does is to let it do it to production. §7 is what that cost.

**Rejected: a systemd user unit for the driver.** It would genuinely survive session exit
and could restart on boot, but it does not survive the host being off during the run's whole
completion window either, and it moves the invocation contract off the command line the
plans are written in. The resume path covers the same loss for a fraction of the machinery.

## 4. Visible surface

The changed surface is the driver's terminal output; monospace terminal text is fully
representable in this document, so no HTML mockup bundle ships with this plan.

New header, every invocation:

```
2026-08-27T18:04:11Z driver log     : /home/will/loom/prototype/runs/logs/driver-scale14.log
2026-08-27T18:04:11Z argv           : --model-identity Qwen2.5-Coder-14B-Instruct GGUF Q4_K_M --runlist …
2026-08-27T18:04:11Z run id         : 20260827T180411Z
2026-08-27T18:04:11Z run manifest   : /home/will/loom/prototype/runs/logs/driver-scale14.json
```

`--detach`:

```
2026-08-27T18:04:11Z detached: pid 481923, log /home/will/loom/prototype/runs/logs/driver-scale14.log
2026-08-27T18:04:11Z resume with: scripts/run-remote-experiment-gcp.sh --resume-from /home/will/loom/prototype/runs/logs/driver-scale14.json
```

`--fetch-only` recovering the incident:

```
2026-08-27T18:06:02Z resume mode: skipping bucket apply, uploads and launch
2026-08-27T18:06:03Z runner reported (post-deadline grace poll): SUCCEEDED
2026-08-27T18:06:03Z runlist mode: fetching each arm's results individually
2026-08-27T18:06:05Z   scale14-b0: runs/ found, downloading
2026-08-27T18:06:09Z   scale14-b2: runs/ found, downloading
2026-08-27T18:06:11Z per-arm status:
  scale14-b0: SUCCEEDED
  scale14-b2: SUCCEEDED
2026-08-27T18:06:11Z teardown: removing the runner instance, leaving the bucket standing
```

`--fetch-only` against a run still in flight (the guard):

```
2026-08-27T18:06:03Z resume: no aggregate status marker — the run may still be in flight
2026-08-27T18:06:05Z teardown: NOT armed (resume mode, run not known to be finished);
                     pass --teardown-anyway to remove the instance regardless
```

## 5. Regression guard

`scripts/tests/test-driver-resume.sh` — no GCP, no network. It puts shims for `gsutil`,
`gcloud` and `terraform` on `PATH` (via `LOOM_DRIVER_BIN_OVERRIDE`, since a plain `PATH`
prepend loses to the driver's own) in front of a directory that *is* the bucket.

Two independent safety properties, because one of them failed once already (§7): the shims
must win — asserted up front, with the harness refusing to start if `terraform` resolves
anywhere else — **and** `--tf-dir` points at an empty throwaway directory, never a real
root, so that even a total shim bypass finds no backend, no state and no resources.

Then:

1. **Reproduces the bug.** Starts the driver in normal mode against the mock, waits until
   it is in the poll loop, `kill -9`s it, and asserts (a) no `launch_runner=false` apply was
   ever recorded — the EXIT trap was skipped, exactly as on 2026‑08‑27 — and (b) the
   durable log exists with the header in it, which is the part that did not exist before.
2. **Proves the recovery.** Writes the arms' results and the status markers into the mock
   bucket (the state the real bucket was in at 05:03), runs
   `--resume-from <manifest> --fetch-only`, and asserts both arms' files landed in `--dest`
   and that teardown applied `launch_runner=false` exactly once.
3. **Proves the guard.** Removes the aggregate marker, re‑runs `--fetch-only`, and asserts
   teardown did *not* run and the exit status is non‑zero.
4. **Proves the trap claim.** Runs the signal probe from §1 and asserts
   `TERM`/`HUP`/`INT` do fire the cleanup stack while `KILL` does not — so if a future bash
   changes that, the design note above fails loudly instead of rotting.
5. **Proves `--detach` detaches.** Asserts the parent returns at once naming the child's
   pid and the exact resume command, that the child kept the *announced* run id instead of
   minting a fresh timestamp, and — the property the flag exists for — that the child's
   session id differs from the caller's, so a process-group kill aimed at the caller cannot
   reach it.

## 6. Verification

1. `bash -n scripts/run-remote-experiment-gcp.sh && shellcheck scripts/run-remote-experiment-gcp.sh`

    ```
    SYNTAX OK

    In scripts/run-remote-experiment-gcp.sh line 326:
            --keep-bucket) KEEP_BUCKET=true; TEARDOWN_SCOPE="instance"; shift ;;
                           ^---------^ SC2034 (warning): KEEP_BUCKET appears unused.
    driver shellcheck rc=1
    ```

    PASS — syntax clean; the one shellcheck warning is pre‑existing, identical on
    `git show HEAD:scripts/run-remote-experiment-gcp.sh`. Delta introduced by this change: zero.

2. `bash scripts/run-remote-experiment-gcp.sh -h` — exits 0, no GCP call, documents the new flags

    ```
    help rc=0
      --fetch-only            --resume with a zero-length wait: read the marker
                              once, fetch whatever is in the bucket, tear down.
      --resume-from FILE      Read a run manifest written by an earlier invocation
                              (prototype/runs/logs/driver-<tag>.json) and restore
                              every setting from it. Flags placed AFTER this one
      --teardown-anyway       In resume mode, tear the instance down even though no
                              aggregate status marker says the run finished. Off by
    ```

    PASS

3. `bash scripts/run-remote-experiment-gcp.sh --dry-run …` — unchanged behaviour, plus the new header

    ```
    2026-08-27T19:11:04Z driver log     : …/dryrun-logs/driver-scale14.log
    2026-08-27T19:11:04Z argv           : --dry-run --model-identity Qwen2.5-Coder-14B-Instruct GGUF Q4_K_M …
    2026-08-27T19:11:04Z mode            : launch
    2026-08-27T19:11:04Z run id          : 20260827T191104Z
    2026-08-27T19:11:04Z run manifest    : …/dryrun-logs/driver-scale14.json
    2026-08-27T19:11:04Z project/zone    : project-19b81040-83b3-4483-a0d / us-central1-a
    2026-08-27T19:11:04Z machine type    : g2-standard-4 (spot=true)
    2026-08-27T19:11:04Z model identity  : Qwen2.5-Coder-14B-Instruct GGUF Q4_K_M
    2026-08-27T19:11:04Z dry run: stopping before any GCP call
    --- log file written ---
    -rw-rw-r-- 1 will will 1380 Aug 27 13:11 driver-scale14.log
    ```

    PASS — dry run still touches no GCP resource, and now leaves a log behind that proves it ran.

4. `bash scripts/tests/test-driver-resume.sh` — all four blocks pass

    ```
    1. SIGKILL mid-poll skips the EXIT trap (the 2026-08-27 failure)
      PASS driver reached the poll loop
      PASS SIGKILL ran no teardown apply — the EXIT trap was skipped, as in the incident
      PASS the instance had been launched, so it was left standing
      PASS durable driver log survives the kill and names the run id
      PASS run manifest survives the kill and carries the run id

    2. --resume-from … --fetch-only recovers everything the kill left behind
      PASS resume exited 0
      PASS scale14-b0 results and logs landed in --dest
      PASS scale14-b2 results and logs landed in --dest
      PASS aggregate startup-script log fetched
      PASS per-arm verdicts printed
      PASS teardown applied launch_runner=false exactly once
      PASS resume uploaded nothing new

    3. --fetch-only refuses to tear down a run that may still be in flight
      PASS exited non-zero (1) with no aggregate marker
      PASS no teardown apply — a live GPU would have survived this
      PASS said plainly that teardown was not armed
      PASS still fetched what the bucket did have

    4. cleanup-stack's EXIT trap fires on TERM/HUP/INT, not on KILL
      PASS SIGTERM runs the cleanup stack (so no extra trap is needed for it)
      PASS SIGHUP runs the cleanup stack (so no extra trap is needed for it)
      PASS SIGINT runs the cleanup stack (so no extra trap is needed for it)
      PASS SIGKILL does not run the cleanup stack — which is why --resume exists

    5. --detach puts the waiter in its own session, with the run id it announced
      PASS parent returned immediately and named the child's pid and log
      PASS parent printed the exact resume command for this run
      PASS child kept the announced run id rather than minting its own
      PASS child session 105333 differs from this shell's 101339 — a process-group kill here cannot reach it

    all checks passed
    ```

    PASS — 24/24. `shellcheck scripts/tests/test-driver-resume.sh` is clean (rc=0).

5. `task experiment:remote-gcp:test` — the Taskfile entry runs the same suite

    ```
    * experiment:remote-gcp:              Run Phase A on a rented g2-standard-4 (L4) …
    * experiment:remote-gcp:resume:       Re-enter a GCP run whose driver died: fetch every arm's results …
    * experiment:remote-gcp:test:         Offline regression guard for the remote driver's kill/resume path …
    ```

    PASS — both entries parse and are listed.

6. Read‑only proof the recovery target was real:
   `gsutil ls -l gs://loom-diversity-artifacts-19b81040/status/`

    ```
            10  2026-08-27T11:03:34Z  gs://…/status/20260827T062338Z.txt
            10  2026-08-27T08:58:28Z  gs://…/status/scale14-b0.txt
            10  2026-08-27T11:03:30Z  gs://…/status/scale14-b2.txt
    ```

    PASS **at the time it was run**, and it is what proved the aggregate marker
    (`20260827T062338Z`) is written in runlist mode — so the wait loop was correct and only
    the driver's survival was at fault. **This command no longer succeeds**: see §7.

## 7. Incident caused while building this — bucket destroyed

An earlier draft of the harness pointed `--tf-dir` at the real
`infrastructure/gcp/experiment-diversity` root and relied on a `PATH` prepend to shim
`terraform`. The driver's own `export PATH="$HOME/.local/bin:$PATH"` outranked it, so the
**real** terraform ran against the **real** GCS-backed state with the test's
`--bucket test-artifacts-bucket`, and applied:

```
Plan: 3 to add, 0 to change, 3 to destroy.
module.experiment_runner.google_storage_bucket_iam_member.runner_objects: Destruction complete after 9s
module.experiment_runner.google_storage_bucket_iam_member.runner_bucket: Destruction complete after 9s
module.experiment_runner.google_storage_bucket.artifacts[0]: Destroying... [id=loom-diversity-artifacts-19b81040]
module.experiment_runner.google_storage_bucket.artifacts[0]: Destruction complete after 2s
Error: googleapi: Error 409: The requested bucket name is not available…
```

**State now:** `gs://loom-diversity-artifacts-19b81040` does not exist
(`BucketNotFoundException: 404`). `terraform state list` holds only the two data sources and
`google_project_iam_member.runner_self_delete`; the bucket and both bucket IAM members are
gone from state as well as from GCP. No instance existed, so nothing is billing.

**What was actually lost.** The bucket was transit storage with a 7‑day lifecycle rule.
Checked, file by file:

- `scale14-b0` and `scale14-b2` `records.jsonl`, `report.md`, `summary.json` — **safe**, in
  `prototype/runs/scale14-b{0,2}/`, pulled by hand at 11:51 today.
- the 14B GGUF — **safe**, `~/loom-tools/models/qwen2.5-coder-14b-instruct-q4_k_m.gguf`.
- the repo tarball, uploaded configs, runlist, status markers — **regenerable**.
- **Lost:** the scale14 arms' `logs/startup-script.log` and `logs/llama-server.log`. They
  were never fetched locally (`prototype/runs/scale14-b*/` has no `logs/`), and they are the
  one thing in that bucket with no other copy. Every other run in `prototype/runs/` has its
  logs; scale14 now does not.

**Restoring the bucket is a `terraform apply`, i.e. creating a GCP resource — outside this
agent's boundary. Not run. Escalated.** The command, for whoever approves it:

```
GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)" \
terraform -chdir=infrastructure/gcp/experiment-diversity apply \
  -var run_id=restore -var model_identity=restore -var launch_runner=false
```

(GCS may hold the deleted name for a period before it can be recreated.)

**What now makes this impossible in the harness:** the throwaway `--tf-dir`, the
`LOOM_DRIVER_BIN_OVERRIDE` seam, and a start-up assertion that refuses to run unless
`terraform` resolves to the shim. Any one of the three would have prevented it.

## 8. Follow-ups (untiered — for the orchestrator to rank)

- The runner's self‑delete was refused on 2026‑08‑27 and it fell back to `shutdown -h now`
  (`infrastructure/gcp/modules/experiment-runner/startup-script.sh.tftpl:79‑81`), which is
  why a 150 GB disk kept billing. Worth finding out *why* it was refused — the instance role
  is conditioned on the instance's own name — because a working self‑delete removes the
  driver from the cost‑safety path entirely.
- `jq` is a hard dependency of runlist mode but is absent from the `command -v` preflight
  block. Added by this change; the sibling `scripts/run-remote-experiment.sh` (AWS) should
  be checked for the same gap.
- The AWS sibling `scripts/run-remote-experiment.sh` has the same
  wait‑loop‑then‑fetch‑then‑trap shape and the same exposure. It has not been touched here.
