variable "project" {
  description = "Project slug — every resource this module creates is named loom-*."
  type        = string
  default     = "loom"
}

variable "project_id" {
  description = "GCP project id that owns every resource here."
  type        = string
}

variable "region" {
  description = "Region for the artifacts bucket."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zone for the runner. Must have L4 capacity; us-central1-a does."
  type        = string
  default     = "us-central1-a"
}

variable "artifacts_bucket" {
  description = "GCS bucket holding the repo tarball, the GGUF models, the run config and the returned runs/ output. GCS names are globally unique, so this carries a project-derived suffix."
  type        = string
}

variable "run_id" {
  description = "Identifier for one experiment run. Namespaces the GCS keys and the completion marker."
  type        = string
}

variable "instance_suffix" {
  description = <<-EOT
    Suffix appended to the runner instance name ("<project>-experiment-runner-<suffix>")
    and to its self-delete IAM condition, so more than one runner can coexist
    under one project without a name collision — the module is written for N
    concurrent runners, not one. Empty (the default) reproduces today's single
    name, "<project>-experiment-runner", unchanged.
  EOT
  type        = string
  default     = ""
}

variable "manage_bucket" {
  description = <<-EOT
    Whether this instantiation creates the artifacts bucket. Set false on every
    instantiation but one when several runners in the same apply share a single
    bucket (concurrent arms of the same experiment) — the bucket name is still
    required via artifacts_bucket so IAM bindings and the runner can address it
    either way.
  EOT
  type        = bool
  default     = true
}

variable "launch_runner" {
  description = <<-EOT
    Whether to launch the GPU instance. The driver script applies once with
    false (creating only the bucket and the IAM bindings, so it has somewhere
    to upload the tarball and models), then again with true to launch.
  EOT
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

variable "guest_accelerator_type" {
  description = <<-EOT
    Accelerator to attach explicitly. Empty is the correct default for the G2
    family, which carries its L4 implicitly in the machine type — naming it
    again is redundant and risks a perpetual diff. Set this (e.g. "nvidia-tesla-t4")
    only for general-purpose families where the GPU is an explicit attachment.
  EOT
  type        = string
  default     = ""
}

variable "guest_accelerator_count" {
  description = "Number of accelerators, used only when guest_accelerator_type is non-empty."
  type        = number
  default     = 1
}

variable "boot_disk_gb" {
  description = "Boot disk size. The Deep Learning VM image plus llama.cpp's build tree plus a couple of quantised GGUFs fits in 150 GB."
  type        = number
  default     = 150
}

variable "boot_disk_type" {
  description = "Boot disk type. pd-balanced is the cheap default that still sustains the build."
  type        = string
  default     = "pd-balanced"
}

variable "image_family" {
  description = "Image family for the runner. Defaults to the Deep Learning VM common CUDA 12.4 image (NVIDIA driver staged, CUDA toolkit preinstalled)."
  type        = string
  default     = "common-cu129-ubuntu-2404-nvidia-580"
}

variable "image_project" {
  description = "Project publishing image_family."
  type        = string
  default     = "deeplearning-platform-release"
}

variable "network" {
  description = "VPC network to attach to."
  type        = string
  default     = "default"
}

variable "subnetwork" {
  description = "Subnetwork to attach to. Empty means the auto-mode subnet for the region."
  type        = string
  default     = ""
}

variable "labels" {
  description = "Labels applied to the resources this module creates, on top of the provider's default_labels."
  type        = map(string)
  default     = {}
}

# --- What the runner does once it is up -------------------------------------

variable "llama_cpp_revision" {
  description = "Pinned llama.cpp commit. The experiment's grammar and server behaviour are recorded against this revision."
  type        = string
  default     = "1f368f354d9edcfea9fd6a1e0989b3e7335a050f"
}

variable "llama_cpp_repo" {
  description = "llama.cpp git remote."
  type        = string
  default     = "https://github.com/ggml-org/llama.cpp.git"
}

variable "gguf_filename" {
  description = "Which uploaded GGUF to serve. Empty means the single .gguf found under models/."
  type        = string
  default     = ""
}

variable "model_identity" {
  description = "Recorded model identity — R2.1 requires this be recorded before the run, not reconstructed after. The runner refuses a live backend without it."
  type        = string
}

variable "hardware" {
  description = "Recorded hardware string for the run manifest."
  type        = string
  default     = "g2-standard-4 L4 24GB"
}

variable "n_gpu_layers" {
  description = "llama-server -ngl. 99 offloads everything that fits."
  type        = number
  default     = 99
}

variable "context_size" {
  description = "llama-server -c."
  type        = number
  default     = 16384
}

variable "parallel_slots" {
  description = "llama-server --parallel. One slot keeps per-draw latency honest."
  type        = number
  default     = 1
}

variable "runlist_key" {
  description = "Optional GCS object name of a JSON array of {config_key, output_dir, run_id} entries. When non-empty the runner executes every entry sequentially (masked configs only) and self-deletes at the end, so one apply covers a whole sweep with no operator machine in the loop."
  type        = string
  default     = ""
}

variable "remote_config_key" {
  description = "GCS object name of the run config the driver uploads. The runner patches its backend fields and passes it to experiment.runner."
  type        = string
  default     = "config/run.config.json"
}

variable "remote_output_dir" {
  description = "Output directory the runner passes to experiment.runner, relative to prototype/."
  type        = string
  default     = "runs/phase-a-full"
}
