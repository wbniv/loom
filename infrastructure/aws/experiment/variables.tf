variable "run_id" {
  description = "Identifier for one experiment run. The driver script passes a UTC timestamp."
  type        = string
}

variable "launch_runner" {
  description = "False on the first apply (bucket and role only), true on the second (launch the GPU)."
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
  default     = "g6.xlarge L4 24GB"
}

variable "instance_type" {
  description = "GPU instance type."
  type        = string
  default     = "g6.xlarge"
}

variable "use_spot" {
  description = "Request spot rather than on-demand."
  type        = bool
  default     = true
}

variable "spot_max_price" {
  description = "Spot bid ceiling in USD/hour. Empty means the on-demand price."
  type        = string
  default     = ""
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed on port 22 for debugging. Empty means no inbound access."
  type        = string
  default     = ""
}

variable "key_name" {
  description = "EC2 key pair name for the debugging path. Empty means none."
  type        = string
  default     = ""
}

variable "remote_output_dir" {
  description = "Output directory under prototype/ that the runner writes and syncs back."
  type        = string
  default     = "runs/phase-a-full"
}
