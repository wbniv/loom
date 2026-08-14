# The whole experiment stack is one module instantiation. This root exists to
# pin the backend, the provider and the tags; every decision worth reading
# lives in ../modules/experiment-runner.

module "experiment_runner" {
  source = "../modules/experiment-runner"

  project          = "loom"
  artifacts_bucket = "loom-experiment-artifacts"

  run_id            = var.run_id
  launch_runner     = var.launch_runner
  instance_type     = var.instance_type
  use_spot          = var.use_spot
  spot_max_price    = var.spot_max_price
  ssh_ingress_cidr  = var.ssh_ingress_cidr
  key_name          = var.key_name
  gguf_filename     = var.gguf_filename
  model_identity    = var.model_identity
  hardware          = var.hardware
  remote_output_dir = var.remote_output_dir
}
