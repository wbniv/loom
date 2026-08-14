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
  description = "Zone for the runner."
  type        = string
  default     = "us-central1-a"
}

variable "artifacts_bucket" {
  description = "GCS bucket name. Globally unique, so it carries the project-id suffix."
  type        = string
  default     = "loom-experiment-artifacts-19b81040"
}

variable "run_id" {
  description = "Identifier for one experiment run. The driver script passes a UTC timestamp."
  type        = string
}

variable "launch_runner" {
  description = "False on the first apply (bucket and IAM only), true on the second (launch the GPU)."
  type        = bool
  default     = true
}

variable "model_identity" {
  description = "Recorded model identity, e.g. \"Qwen2.5-Coder-7B-Instruct-Q5_K_M\". Passed straight through to the run manifest."
  type        = string
}

variable "gguf_filename" {
  description = "Which uploaded GGUF to serve. Empty means the single .gguf under models/."
  type        = string
  default     = ""
}

variable "hardware" {
  description = "Recorded hardware string."
  type        = string
  default     = "g2-standard-4 L4 24GB"
}

variable "machine_type" {
  description = "GPU machine type."
  type        = string
  default     = "g2-standard-4"
}

variable "use_spot" {
  description = "Request a Spot VM rather than on-demand."
  type        = bool
  default     = true
}

variable "remote_output_dir" {
  description = "Output directory under prototype/ that the runner writes and syncs back."
  type        = string
  default     = "runs/phase-a-full"
}
