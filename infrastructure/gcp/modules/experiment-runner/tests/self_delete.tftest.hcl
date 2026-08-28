# Regression guard for the 2026-08-27 scale14 incident: a runner's self-delete
# was refused and it fell back to `shutdown -h now`, leaving a TERMINATED
# instance with a 150 GB disk billing overnight until torn down by hand.
#
# Root cause (proved by inspection, not reproduced live — the instance and its
# serial log are gone): `local.startup_script` passed the template a *literal*
# `instance_name = "${var.project}-experiment-runner"`, ignoring
# `var.instance_suffix`, while the actual `google_compute_instance` resource
# and the self-delete IAM condition were both keyed off `local.instance_name`
# (which *does* include the suffix). Every root that instantiates this module
# sets a non-empty suffix (../experiment-diversity: "diversity", ../experiment-pair:
# per-arm, ../experiment-solo(-b): "curated"/"generated"), so in every real
# deployment the startup script's `$INSTANCE_NAME` named an instance that did
# not exist under that identity — `gcloud compute instances delete` had
# nothing matching to act on (and the IAM condition, scoped to the *real* name,
# would have refused it even if it had) — hence "self-delete refused".
#
# This cannot be exercised by actually launching an instance and killing its
# driver (no live GPU boot in CI, and the whole point is to catch this before
# a launch costs money), so the guard instead asserts, statically and offline,
# that the two names Terraform computes can never drift again: the instance
# Terraform creates, and the instance name baked into the startup script that
# instance boots with. `mock_provider` makes this a real `terraform plan`
# against the actual module — no credentials, no network, no GCP resource
# created — rather than a hand-rolled re-implementation of the same logic that
# could carry the same bug twice.
#
# Run with: terraform test   (from this module directory, after `terraform init`)

mock_provider "google" {}

variables {
  project_id       = "test-project"
  run_id           = "20260827-000000"
  artifacts_bucket = "test-bucket"
  model_identity   = "test-model"
  instance_suffix  = "diversity"
}

run "instance_name_matches_startup_script" {
  command = plan

  # The name Terraform actually gives the instance.
  assert {
    condition     = google_compute_instance.runner[0].name == "loom-experiment-runner-diversity"
    error_message = "planned instance name drifted from local.instance_name — update this test's expectation only if the naming scheme itself changed"
  }

  # The name the startup script's self-delete call targets. These two must
  # always agree, or `gcloud compute instances delete "$INSTANCE_NAME"` names
  # an instance that does not exist under that identity.
  assert {
    condition     = strcontains(google_compute_instance.runner[0].metadata["startup-script"], "INSTANCE_NAME=\"loom-experiment-runner-diversity\"")
    error_message = "startup script's INSTANCE_NAME does not match the instance Terraform creates — self-delete would be refused (2026-08-27 scale14 regression)"
  }

  # The self-delete IAM condition is scoped to the same real name, not the
  # unsuffixed one — otherwise a correct INSTANCE_NAME would still be denied.
  assert {
    condition     = strcontains(google_project_iam_member.runner_self_delete.condition[0].expression, "/instances/loom-experiment-runner-diversity")
    error_message = "self-delete IAM condition is not scoped to the instance this apply actually creates"
  }

  # roles/compute.instanceAdmin.v1 is the role bound; its permission set
  # includes compute.instances.delete (verified 2026-08-27 via
  # `gcloud iam roles describe roles/compute.instanceAdmin.v1`, documented in
  # docs/plans/2026-08-27-runner-self-delete.md). This assertion only guards
  # against the *binding* silently changing to a different role, not against
  # that role's own permission set changing upstream.
  assert {
    condition     = google_project_iam_member.runner_self_delete.role == "roles/compute.instanceAdmin.v1"
    error_message = "self-delete role changed — re-verify it still includes compute.instances.delete before landing"
  }
}

run "empty_suffix_still_matches" {
  command = plan

  variables {
    instance_suffix = ""
  }

  assert {
    condition     = google_compute_instance.runner[0].name == "loom-experiment-runner"
    error_message = "unsuffixed instance name should reproduce the pre-suffix scheme unchanged"
  }

  assert {
    condition     = strcontains(google_compute_instance.runner[0].metadata["startup-script"], "INSTANCE_NAME=\"loom-experiment-runner\"")
    error_message = "startup script's INSTANCE_NAME drifted from the instance name even in the no-suffix case"
  }
}
