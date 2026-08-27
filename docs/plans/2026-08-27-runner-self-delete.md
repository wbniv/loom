# Runner self-delete: diagnosis and fix

## Incident

On 2026‑08‑27, the diversity‑harvest GPU runner's self-delete was refused at the end of its run. The startup script's `finish()` trap fell back to `shutdown -h now` (`infrastructure/gcp/modules/experiment-runner/startup-script.sh.tftpl:78-82`), which leaves the instance `TERMINATED` rather than deleted. A `TERMINATED` Spot VM still bills for its boot disk — 150 GB — and this one sat that way overnight, ~4.7 h, until torn down by hand. This doc diagnoses the refusal and fixes it at the module, so it flows to every root that instantiates `../modules/experiment-runner`.

The instance and its serial console log are gone (torn down before this investigation started), and the startup-script log for the scale14 run was lost with the bucket, so the proof below is entirely from static code inspection, not a captured error message. That gap is stated explicitly rather than papered over.

## Proven cause

`infrastructure/gcp/modules/experiment-runner/main.tf` computes two different instance names and uses one of them inconsistently.

The instance's *real* name, used everywhere else in the module — the resource itself, and the self-delete IAM condition's scope — is `local.instance_name`, which includes the caller's `instance_suffix`:

```
# main.tf:18
instance_name = var.instance_suffix == "" ? "${var.project}-experiment-runner" : "${var.project}-experiment-runner-${var.instance_suffix}"
```

```
# iam.tf — google_project_iam_member.runner_self_delete
condition {
  title       = "only-${local.instance_name}"
  expression  = "resource.type == \"compute.googleapis.com/Instance\" && resource.name.endsWith(\"/instances/${local.instance_name}\")"
}
```

```
# main.tf — google_compute_instance.runner
resource "google_compute_instance" "runner" {
  name = local.instance_name
  ...
```

But the value baked into the startup script — the name the script's own `gcloud compute instances delete "$INSTANCE_NAME"` call targets — was a **literal, unsuffixed** string, at `main.tf:28` (before this fix):

```
instance_name      = "${var.project}-experiment-runner"
```

Every root that instantiates this module sets a non-empty `instance_suffix`:

| Root | `instance_suffix` |
|---|---|
| `experiment-diversity` | `var.instance_suffix`, default `"diversity"` (`experiment-diversity/variables.tf:35-43`) |
| `experiment-pair` (arm A / arm B) | `var.instance_suffix_a` / `var.instance_suffix_b` (`experiment-pair/main.tf:20,49`) |
| `experiment-solo` | `"curated"` (hardcoded, `experiment-solo/main.tf:15`) |
| `experiment-solo-b` | `"generated"` (hardcoded, `experiment-solo-b/main.tf:15`) |
| `experiment` | uses the module's own default (empty) — the one case that was *not* affected |

So in every deployment that carries a suffix — which is every named/concurrent run, including the 2026‑08‑27 diversity-harvest run — the real instance was named e.g. `loom-experiment-runner-diversity`, while its own startup script's `$INSTANCE_NAME` held `loom-experiment-runner`: an identity with no matching instance under that name, and one the self-delete IAM condition (correctly scoped to `loom-experiment-runner-diversity`) would have denied regardless. Either way, `gcloud compute instances delete "loom-experiment-runner" --zone ...` fails — as a 403 from the IAM condition mismatch, or a 404 if GCP resolves the name lookup first — and the script's own log line reads exactly as reported: `"finish: self-delete refused, halting instead"`.

This fully explains the incident without needing the lost serial log: it is a name-derivation bug in the Terraform that renders the script, not a runtime failure on the instance.

### Candidates ruled out

1. **IAM member lacks `compute.instances.delete`, or wrong scope.** Ruled out. `roles/compute.instanceAdmin.v1` is bound project-level with a per-instance condition (`iam.tf`), and its permission set includes `compute.instances.delete`, confirmed directly:

   ```
   $ gcloud iam roles describe roles/compute.instanceAdmin.v1 --format="value(includedPermissions)" | tr ';' '\n' | grep -i "instances.delete"
   compute.instances.delete
   compute.instances.deleteAccessConfig
   compute.instances.deleteNetworkInterface
   compute.instances.deleteTagBinding
   ```

   Source: [Compute Engine predefined roles — `roles/compute.instanceAdmin.v1`](https://cloud.google.com/iam/docs/roles-permissions/compute#compute.instanceAdmin.v1). The role and its condition are correct; what was wrong is which name the script asked to delete.

2. **Instance's service account scopes block it regardless of IAM.** Ruled out. `main.tf`'s `service_account` block requests the broadest available OAuth scope:

   ```
   scopes = ["https://www.googleapis.com/auth/cloud-platform"]
   ```

   which defers entirely to IAM and imposes no narrower ceiling. Not the cause.

3. **The delete call itself is malformed (zone/name derivation in the startup script).** **This is the cause** — see above. It's a derivation bug in the Terraform that *feeds* the script, not in the script's own zone/name handling (`ZONE="${zone}"` and `INSTANCE_NAME="${instance_name}"` are simple, correct interpolations of whatever `main.tf` passes them).

4. **IAM propagation timing on first boot.** Not credible for this run: the incident was reported 4.7 h into the run, and `google_project_iam_member.runner_self_delete` is listed in `depends_on` for the instance (`main.tf`), so the binding exists before the instance is even created — there is no token-refresh path where a boot-time token could predate it by hours. Not investigated further; ruled out by timing alone.

## Fix

One line, in the module all five roots share (`experiment`, `experiment-pair` ×2, `experiment-diversity`, `experiment-solo`, `experiment-solo-b`):

```diff
--- a/infrastructure/gcp/modules/experiment-runner/main.tf
+++ b/infrastructure/gcp/modules/experiment-runner/main.tf
@@ -25,7 +25,7 @@ locals {
     artifacts_bucket   = var.artifacts_bucket
     run_id             = var.run_id
     zone               = var.zone
-    instance_name      = "${var.project}-experiment-runner"
+    instance_name      = local.instance_name
     llama_cpp_repo     = var.llama_cpp_repo
     llama_cpp_revision = var.llama_cpp_revision
     gguf_filename      = var.gguf_filename
```

`infrastructure/gcp/modules/experiment-runner/main.tf:28`. The startup script's `$INSTANCE_NAME` now always equals the name Terraform actually gives the instance (with or without a suffix), matching the self-delete IAM condition's scope. No other file needed a code change — `experiment`, `experiment-pair`, `experiment-diversity`, `experiment-solo`, `experiment-solo-b` all source this one module and inherit the fix automatically; none of them carries its own copy of the template or the instance-name logic.

Incidental fix along the way: `scripts/render-gcp-startup-script.py`'s representative-values dict was missing `runlist_key` (added to the template on 2026‑08‑24 for the sweep-runlist feature, never added here), which made the renderer — and therefore the new guard below — fail before it could even check anything. One line added (`scripts/render-gcp-startup-script.py`): `"runlist_key": "",`. Unrelated to the self-delete bug itself, but a hard blocker for verifying it.

## Regression guard

Honestly scoped, as instance self-delete cannot be integration-tested offline (no live GPU boot, no real IAM decision without credentials). Two provable halves, both exercised by `scripts/tests/test-runner-self-delete.sh` (new):

**(a) The rendered startup script is well-formed.** Renders the template via the existing `scripts/render-gcp-startup-script.py`, then runs `bash -n` and `shellcheck -S warning` on the result. This does not target this specific bug (a passing/failing name string is not a shell syntax error), but it is the honest half of "well-formed... correct metadata-derived zone/name" the incident report asked for, and it catches unknown-interpolation and syntax regressions in the same file.

**(b) The instance name and the startup script's `$INSTANCE_NAME` can never drift apart again.** This is the check that actually targets the bug. `infrastructure/gcp/modules/experiment-runner/tests/self_delete.tftest.hcl` (new) uses Terraform's native test framework with `mock_provider "google" {}` — a real `terraform plan` against the real module, zero credentials, zero network calls beyond a local provider plugin cache, zero GCP resource created — and asserts, for both a suffixed (`"diversity"`) and unsuffixed (`""`) `instance_suffix`:

- `google_compute_instance.runner[0].name` equals the expected `loom-experiment-runner[-suffix]`.
- The planned `metadata["startup-script"]` contains `INSTANCE_NAME="loom-experiment-runner[-suffix]"` — the same string.
- `google_project_iam_member.runner_self_delete`'s condition expression is scoped to that same real name.
- The bound role is still `roles/compute.instanceAdmin.v1` (a change here would need re-verifying against the permission list documented above before landing).

This is a real `terraform plan` against the actual HCL, not a hand-rolled re-implementation of the naming logic that could carry the same bug a second time.

### Follow-ups (untiered — these are for the operator to rank, not decided here)

- Wire `scripts/tests/test-runner-self-delete.sh` into `Taskfile.yml` (e.g. alongside `experiment:remote-gcp:test`) so it runs the same way the driver-resume guard does. Left undone here: `Taskfile.yml` was out of this task's scope (`infrastructure/`, `scripts/tests/`, and this plan doc only).
- Consider whether `scripts/render-gcp-startup-script.py`'s `VALUES` dict should instead be derived from the module's `variables.tf` defaults programmatically, so a future new template variable can't silently go stale there again the way `runlist_key` did.
- No serial-log or startup-script-log capture currently survives instance teardown by default; consider always `gsutil cp`-ing the startup log to a location that outlives the run bucket's lifecycle rule, so a future incident like this one doesn't have to be diagnosed by code inspection alone.

## Verification

**1. `terraform test` catches the actual bug (fails against the buggy code, passes against the fix).**

Against the code as it stood before this fix (module copied to a scratch dir, one line reverted):

```
$ bash scripts/tests/test-runner-self-delete.sh   # with main.tf's fix stashed out
...
2. terraform test: instance name == startup script INSTANCE_NAME
  PASS terraform init (mock provider, no credentials)
  FAIL terraform test found a name mismatch — see infrastructure/gcp/modules/experiment-runner/tests/self_delete.tftest.hcl: ...
  run "instance_name_matches_startup_script"... fail
  Error: Test assertion failed
    google_compute_instance.runner[0].metadata["startup-script"] contains INSTANCE_NAME="loom-experiment-runner" (not "-diversity")
  startup script's INSTANCE_NAME does not match the instance Terraform creates
  — self-delete would be refused (2026-08-27 scale14 regression)
  run "empty_suffix_still_matches"... pass
Failure! 1 passed, 1 failed.
1 check(s) failed
```

PASS (as a *failing* run against the pre-fix code, which is the correct behavior for a regression guard) — confirms the guard would have caught this before it shipped.

**2. Full guard passes against the fixed code.**

```
$ bash scripts/tests/test-runner-self-delete.sh

1. startup script well-formed (bash -n, shellcheck)
  PASS renders with no unknown template interpolation
  PASS bash -n parses the rendered script
  PASS shellcheck clean (warning severity and above)

2. terraform test: instance name == startup script INSTANCE_NAME
  PASS terraform init (mock provider, no credentials)
  PASS terraform test: instance name and startup script agree, in both the suffixed and unsuffixed cases

all checks passed
```

PASS.

**3. The role bound by `google_project_iam_member.runner_self_delete` includes `compute.instances.delete`.**

```
$ gcloud iam roles describe roles/compute.instanceAdmin.v1 --format="value(includedPermissions)" | tr ';' '\n' | grep -i "instances.delete"
compute.instances.delete
compute.instances.deleteAccessConfig
compute.instances.deleteNetworkInterface
compute.instances.deleteTagBinding
```

PASS — read-only `gcloud` inspection, no resources touched. Source: [Compute Engine predefined roles — `roles/compute.instanceAdmin.v1`](https://cloud.google.com/iam/docs/roles-permissions/compute#compute.instanceAdmin.v1).

**4. `terraform fmt` is clean on the touched file** (part of this repo's `task infra:validate`; run standalone here to avoid the multi-root scratch dance for a one-line change):

```
$ ~/.local/bin/terraform fmt -check infrastructure/gcp/modules/experiment-runner/main.tf
$ echo "exit=$?"
exit=0
```

PASS.

No live `terraform plan`/`apply` was run against a real root, and no GCP resource was created, modified, or destroyed, per this task's hard boundary.
