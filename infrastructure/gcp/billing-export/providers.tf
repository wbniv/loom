# Identical to every other root's providers.tf. No credentials block and no
# service-account key file: whoever runs terraform here exports
# GOOGLE_OAUTH_ACCESS_TOKEN from `gcloud auth print-access-token` immediately
# before the invocation, so the provider authenticates as the operator with a
# token that expires in an hour and is never written to disk.
provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = {
    project     = "loom"
    managed_by  = "terraform"
    environment = "dev"
  }
}
