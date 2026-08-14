# The state bucket is created by the driver's preflight (`gcloud storage
# buckets create`, idempotent) rather than by a bootstrap Terraform root: it is
# one bucket with versioning on, and a whole root plus its own local state is
# more machinery than one `gsutil mb` deserves. See the driver's
# ensure_state_bucket().
#
# The gcs backend reads the same GOOGLE_OAUTH_ACCESS_TOKEN the provider does,
# so no credentials live here either.
terraform {
  backend "gcs" {
    bucket = "loom-tfstate-19b81040"
    prefix = "experiment"
  }
}
