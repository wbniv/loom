# Twin of ../experiment-solo/backend.tf for the second arm — its own state
# prefix, its own bucket (see variables.tf), so the two arms and T4's
# diversity-harvest run never share a single Terraform-managed resource.
# The only thing still shared across all of them is the account's GPU
# quota, which fails an apply cleanly rather than corrupting state.
terraform {
  backend "gcs" {
    bucket = "loom-tfstate-19b81040"
    prefix = "experiment-solo-b"
  }
}
