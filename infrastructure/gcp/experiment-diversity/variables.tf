# Every variable this root takes. Defaults are the diversity-harvest plan's
# own values, so a `terraform plan` here with only --model-identity supplied
# describes exactly what the driver would do.

variable "project_id" {
  description = "GCP project id. The trial project created for loom."
  type        = string
  default     = "project-19b81040-83b3-4483-a0d"
}

variable "region" {
  description = "Region for the artifacts bucket and the runner. us-central1 is L4-rich and cheap."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zone for the runner. Must have L4 capacity; us-central1-a does."
  type        = string
  default     = "us-central1-a"
}

variable "artifacts_bucket" {
  description = <<-EOT
    GCS bucket for this root's own artifacts. Deliberately NOT
    loom-experiment-artifacts-19b81040: that bucket is created with
    force_destroy by ../experiment and ../experiment-pair, so sharing it would
    let another run's teardown delete this run's models and results. GCS names
    are a single global namespace, hence the project-derived suffix.
  EOT
  type        = string
  default     = "loom-diversity-artifacts-19b81040"
}

variable "instance_suffix" {
  description = <<-EOT
    Distinguishes this root's instance from every other runner in the project.
    Without it the instance is `loom-experiment-runner`, which is also what
    ../experiment names its one instance — two concurrent runs would then be
    two Terraform states managing one instance name.
  EOT
  type        = string
  default     = "diversity"
}

variable "run_id" {
  description = "Identifier for one experiment run. Namespaces the GCS keys and the completion marker."
  type        = string
}

variable "launch_runner" {
  description = "False on the first apply (bucket and IAM only, so the driver can upload), true on the second (launch the GPU). False again is how the driver takes the instance away without touching the bucket."
  type        = bool
  default     = true
}

variable "machine_type" {
  description = "GPU machine type. g2-standard-4 is one L4 24 GB with 4 vCPU."
  type        = string
  default     = "g2-standard-4"
}

variable "use_spot" {
  description = "Request a Spot VM rather than a standard on-demand one."
  type        = bool
  default     = true
}

variable "gguf_filename" {
  description = "Which uploaded GGUF to serve. Empty means the single .gguf found under models/."
  type        = string
  default     = ""
}

variable "model_identity" {
  description = "Recorded model identity — R2.1 requires it be recorded before the run, not reconstructed after."
  type        = string
}

variable "hardware" {
  description = "Recorded hardware string for the run manifest."
  type        = string
  default     = "g2-standard-4 L4 24GB"
}

variable "remote_output_dir" {
  description = "Output directory the runner passes to experiment.runner, relative to prototype/."
  type        = string
  default     = "runs/diverse-followup"
}

variable "runlist_key" {
  description = "Optional GCS key of a runlist JSON; see the module variable of the same name."
  type        = string
  default     = ""
}
