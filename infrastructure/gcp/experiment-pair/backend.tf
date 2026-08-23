# Same state bucket as ../experiment (see that root's backend.tf for why
# there is no bootstrap/ root), a different prefix — so a pair-of-arms apply
# never touches ../experiment's state, and the two roots can never contend for
# the same lock.
terraform {
  backend "gcs" {
    bucket = "loom-tfstate-19b81040"
    prefix = "experiment-pair"
  }
}
