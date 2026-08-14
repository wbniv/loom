variable "project" {
  description = "Project slug — every resource this module creates is named loom-*."
  type        = string
  default     = "loom"
}

variable "artifacts_bucket" {
  description = "S3 bucket holding the repo tarball, the GGUF models, the run config and the returned runs/ output."
  type        = string
  default     = "loom-experiment-artifacts"
}

variable "run_id" {
  description = "Identifier for one experiment run. Namespaces the S3 keys and the completion marker."
  type        = string
}

variable "launch_runner" {
  description = <<-EOT
    Whether to launch the GPU instance. The driver script applies once with
    false (creating only the bucket and the instance role, so it has somewhere
    to upload the tarball and models), then again with true to launch.
  EOT
  type        = bool
  default     = true
}

variable "instance_type" {
  description = "GPU instance type. g6.xlarge is one L4 24 GB."
  type        = string
  default     = "g6.xlarge"
}

variable "use_spot" {
  description = "Request a one-time spot instance rather than on-demand."
  type        = bool
  default     = true
}

variable "spot_max_price" {
  description = "Spot bid ceiling in USD/hour. Empty string means the on-demand price."
  type        = string
  default     = ""
}

variable "root_volume_gb" {
  description = "Root gp3 volume size. The DL Base GPU AMI plus llama.cpp plus a couple of GGUFs fits in 100 GB."
  type        = number
  default     = 100
}

variable "ami_name_filter" {
  description = "Name filter for the AMI data source. Defaults to the AWS Deep Learning Base GPU AMI (drivers + CUDA toolkit preinstalled)."
  type        = string
  default     = "Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)*"
}

variable "ami_owner" {
  description = "Owner of the AMI matched by ami_name_filter."
  type        = string
  default     = "amazon"
}

variable "subnet_id" {
  description = "Subnet to launch into. Empty means a default-VPC subnet chosen by EC2."
  type        = string
  default     = ""
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to reach port 22, for debugging a run that will not start. Empty means no ingress at all, which is the normal case — the runner needs no inbound access."
  type        = string
  default     = ""
}

variable "key_name" {
  description = "EC2 key pair name for the debugging path. Empty means no key pair."
  type        = string
  default     = ""
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
  default     = "g6.xlarge L4 24GB"
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

variable "remote_config_key" {
  description = "S3 key of the run config the driver uploads. The runner patches its backend fields and passes it to experiment.runner."
  type        = string
  default     = "config/run.config.json"
}

variable "remote_output_dir" {
  description = "Output directory the runner passes to experiment.runner, relative to prototype/."
  type        = string
  default     = "runs/phase-a-full"
}
