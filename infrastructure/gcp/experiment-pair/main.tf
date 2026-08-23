# Two arms of the same experiment, launched together instead of one after
# the other. The two instantiations are identical in shape to
# ../experiment's single one — every decision about the runner itself lives
# in ../modules/experiment-runner — and differ only in the per-arm variables
# above (run id, config, output dir, instance suffix) plus manage_bucket,
# which is true on exactly one of the two so the shared bucket is created
# once, not fought over. Everything else (labels, model, hardware, machine
# type, spot/on-demand) is identical by construction, since both come from
# the same shared variables.

module "arm_a" {
  source = "../modules/experiment-runner"

  project          = "loom"
  project_id       = var.project_id
  region           = var.region
  zone             = var.zone
  artifacts_bucket = var.artifacts_bucket
  manage_bucket    = true
  instance_suffix  = var.instance_suffix_a

  run_id            = var.run_id_a
  launch_runner     = var.launch_runner
  machine_type      = var.machine_type
  use_spot          = var.use_spot
  gguf_filename     = var.gguf_filename
  model_identity    = var.model_identity
  hardware          = var.hardware
  remote_config_key = var.remote_config_key_a
  remote_output_dir = var.remote_output_dir_a

  labels = {
    project     = "loom"
    managed_by  = "terraform"
    environment = "dev"
    arm         = "a"
  }
}

module "arm_b" {
  source = "../modules/experiment-runner"

  project          = "loom"
  project_id       = var.project_id
  region           = var.region
  zone             = var.zone
  artifacts_bucket = var.artifacts_bucket
  manage_bucket    = false
  instance_suffix  = var.instance_suffix_b

  run_id            = var.run_id_b
  launch_runner     = var.launch_runner
  machine_type      = var.machine_type
  use_spot          = var.use_spot
  gguf_filename     = var.gguf_filename
  model_identity    = var.model_identity
  hardware          = var.hardware
  remote_config_key = var.remote_config_key_b
  remote_output_dir = var.remote_output_dir_b

  labels = {
    project     = "loom"
    managed_by  = "terraform"
    environment = "dev"
    arm         = "b"
  }

  # arm_b addresses the bucket arm_a creates; it must exist first so arm_b's
  # IAM bindings (and, once launched, its runner) have somewhere to read and
  # write.
  depends_on = [module.arm_a]
}
