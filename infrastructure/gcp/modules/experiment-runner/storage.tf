# The artifacts bucket is the only channel between the operator's laptop and
# the runner: repo tarball and GGUFs go in, runs/ and the log come back, and a
# status object under status/ is what tells the driver the run is over. It is
# created on the first (launch_runner = false) apply so the driver has
# somewhere to upload before the instance exists.
#
# GCS bucket names are a single global namespace, so this one carries a
# project-derived suffix; the AWS sibling could use the bare name because S3
# names are global but that one was already taken by us.
#
# Gated on manage_bucket: when several runners share one apply (concurrent
# arms of the same experiment), exactly one instantiation should own this
# resource — the rest reference the same name via var.artifacts_bucket without
# creating it a second time, which GCS would refuse anyway (bucket names are
# globally unique) and which would otherwise make two Terraform resources
# fight over the same bucket's lifecycle.

resource "google_storage_bucket" "artifacts" {
  count = var.manage_bucket ? 1 : 0

  name     = var.artifacts_bucket
  project  = var.project_id
  location = upper(var.region)

  # The bucket is torn down with the rest of the run; force_destroy lets that
  # happen with the tarball, models and results still in it.
  force_destroy = true

  # ACLs off: every grant in this stack is an IAM binding, and a uniform bucket
  # is the only way that statement stays true.
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # A leftover bucket after an interrupted run costs storage for the models
  # until someone notices. Expire everything after a week as a backstop; a run
  # lasts about two hours.
  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 1
    }
    action {
      type = "Delete"
    }
  }

  labels = var.labels
}
