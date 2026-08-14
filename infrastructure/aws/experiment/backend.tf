terraform {
  backend "s3" {
    bucket       = "loom-terraform-state-353144603271"
    key          = "experiment/terraform.tfstate"
    region       = "us-east-2"
    profile      = "loom-terraform"
    use_lockfile = true
    encrypt      = true
  }
}
