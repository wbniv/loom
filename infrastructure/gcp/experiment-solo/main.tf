# The whole experiment stack is one module instantiation. This root exists to
# pin the backend, the provider and the labels; every decision worth reading
# lives in ../modules/experiment-runner. Sibling of infrastructure/aws/experiment.

module "experiment_runner" {
  source = "../modules/experiment-runner"

  project          = "loom"
  project_id       = var.project_id
  region           = var.region
  zone             = var.zone
  artifacts_bucket = var.artifacts_bucket

  run_id            = var.run_id
  instance_suffix   = "curated"
  launch_runner     = var.launch_runner
  machine_type      = var.machine_type
  use_spot          = var.use_spot
  gguf_filename     = var.gguf_filename
  model_identity    = var.model_identity
  hardware          = var.hardware
  remote_output_dir = var.remote_output_dir

  # default_labels covers everything the provider creates, but the module also
  # stamps the boot disk and the instance explicitly, which needs them by value.
  labels = {
    project     = "loom"
    managed_by  = "terraform"
    environment = "dev"
  }
}
