# Same state bucket as every other root (see ../experiment/backend.tf for why
# there is no bootstrap root), own prefix so this root's lock and outputs
# never collide with a running experiment.
terraform {
  backend "gcs" {
    bucket = "loom-tfstate-19b81040"
    prefix = "billing-export"
  }
}
