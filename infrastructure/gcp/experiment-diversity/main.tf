# The diversity-harvest arms' runner — one instantiation of
# ../modules/experiment-runner that owns **every** resource it touches.
#
# docs/plans/2026-08-23-diversity-harvest.md is the experiment; this root is the
# blast-radius decision that came out of the 2026-08-23 collision described in
# backend.tf.
#
# `manage_bucket = true` with an artifacts bucket of this root's *own* is the
# load-bearing line. The obvious alternative — point at
# `loom-experiment-artifacts-19b81040` with `manage_bucket = false`, the way
# ../experiment-pair's arm B points at arm A's — was rejected: that bucket is
# created and destroyed by another root, with `force_destroy = true`, so a
# concurrent run finishing first would delete the models and results out from
# under this one. Sharing it also means sharing its two IAM members, which are
# additive grants for the same default service account: whichever root destroys
# first revokes the other runner's ability to write its results. Neither failure
# announces itself until the results are already gone.
#
# The cost of not sharing is one extra upload of a 4.7 GB GGUF, once, kept
# across this plan's runs by the driver's --keep-bucket. That is the right
# trade against silently losing a run.
#
# What this root can destroy, in full: one bucket that only these arms use, two
# IAM members on that bucket, one project IAM member pinned by condition to this
# root's own instance name, and one instance. There is no resource here that
# another run depends on, so even a blanket `terraform destroy` — the thing a
# crashed driver's EXIT trap might reach — cannot reach anything shared.

module "experiment_runner" {
  source = "../modules/experiment-runner"

  project          = "loom"
  project_id       = var.project_id
  region           = var.region
  zone             = var.zone
  artifacts_bucket = var.artifacts_bucket
  manage_bucket    = true
  instance_suffix  = var.instance_suffix

  run_id            = var.run_id
  launch_runner     = var.launch_runner
  machine_type      = var.machine_type
  use_spot          = var.use_spot
  gguf_filename     = var.gguf_filename
  model_identity    = var.model_identity
  hardware          = var.hardware
  remote_output_dir = var.remote_output_dir

  labels = {
    project     = "loom"
    managed_by  = "terraform"
    environment = "dev"
    experiment  = "diversity-harvest"
  }
}
