# Shared across both arms — same project, same model, same machine shape.
# Anything that must differ between the two runs (run id, config, output dir)
# is a per-arm variable below instead.

variable "project_id" {
  description = "GCP project id. The trial project created for loom."
  type        = string
  default     = "project-19b81040-83b3-4483-a0d"
}

variable "region" {
  description = "Region for the artifacts bucket and the runners. us-central1 is L4-rich and cheap."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zone for both runners. Both arms land in the same zone, so quota is checked once."
  type        = string
  default     = "us-central1-a"
}

variable "artifacts_bucket" {
  description = "GCS bucket name shared by both arms. Globally unique, so it carries the project-id suffix."
  type        = string
  default     = "loom-experiment-artifacts-19b81040"
}

variable "launch_runner" {
  description = "False on the first apply (bucket and IAM only, for both arms), true on the second (launch both GPUs)."
  type        = bool
  default     = true
}

variable "model_identity" {
  description = "Recorded model identity, shared by both arms — they differ only in which store definitions the arm's config admits, never in which model runs."
  type        = string
}

variable "gguf_filename" {
  description = "Which uploaded GGUF both arms serve. Empty means the single .gguf under models/."
  type        = string
  default     = ""
}

variable "hardware" {
  description = "Recorded hardware string, shared by both arms."
  type        = string
  default     = "g2-standard-4 L4 24GB"
}

variable "machine_type" {
  description = "GPU machine type, shared by both arms."
  type        = string
  default     = "g2-standard-4"
}

variable "use_spot" {
  description = "Request Spot VMs rather than on-demand, for both arms."
  type        = bool
  default     = true
}

# --- Per-arm ------------------------------------------------------------

variable "run_id_a" {
  description = "Run identifier for arm A (the bucket-owning arm)."
  type        = string
}

variable "remote_output_dir_a" {
  description = "Output directory under prototype/ that arm A's runner writes and syncs back."
  type        = string
}

variable "remote_config_key_a" {
  description = "GCS object name of arm A's run config."
  type        = string
  default     = "config/run-a.config.json"
}

variable "instance_suffix_a" {
  description = "Instance-name suffix for arm A."
  type        = string
  default     = "a"
}

variable "run_id_b" {
  description = "Run identifier for arm B."
  type        = string
}

variable "remote_output_dir_b" {
  description = "Output directory under prototype/ that arm B's runner writes and syncs back."
  type        = string
}

variable "remote_config_key_b" {
  description = "GCS object name of arm B's run config."
  type        = string
  default     = "config/run-b.config.json"
}

variable "instance_suffix_b" {
  description = "Instance-name suffix for arm B."
  type        = string
  default     = "b"
}
