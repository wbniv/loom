# Every variable this root takes. Defaults describe exactly what
# `terraform plan` produces with no -var overrides.

variable "project_id" {
  description = "GCP project id. The trial project created for loom."
  type        = string
  default     = "project-19b81040-83b3-4483-a0d"
}

variable "region" {
  description = "Region the provider defaults to for anything region-scoped. Not the dataset's location — see dataset_location."
  type        = string
  default     = "us-central1"
}

variable "dataset_id" {
  description = <<-EOT
    BigQuery dataset id the billing export writes into. This must match, byte
    for byte, whatever dataset is selected in the console's Billing export
    page (https://console.cloud.google.com/billing/export) — Terraform can
    create the empty dataset but cannot flip the export on, so the two sides
    only agree if the id matches.
  EOT
  type        = string
  default     = "billing_export"
}

variable "dataset_location" {
  description = <<-EOT
    BigQuery dataset location. Billing export tables can land in any
    BigQuery-supported location, but Google's own docs and console default to
    the "US" multi-region, and a multi-region avoids having to predict which
    single region the export's storage backend prefers. Keep this in sync
    with whatever location the console shows when creating/selecting the
    dataset — BigQuery cannot move a dataset between locations after creation.
  EOT
  type        = string
  default     = "US"
}
