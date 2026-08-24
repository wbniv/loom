# Identical to ../experiment/providers.tf. No credentials block and no
# service-account key file: the driver exports GOOGLE_OAUTH_ACCESS_TOKEN from
# `gcloud auth print-access-token` immediately before every terraform
# invocation, so the provider authenticates as the operator with a token that
# expires in an hour and is never written to disk.
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone

  default_labels = {
    project     = "loom"
    managed_by  = "terraform"
    environment = "dev"
  }
}
