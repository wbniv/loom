# Bootstrap: create the S3 bucket and DynamoDB table for Terraform remote state.
#
# One-time setup with LOCAL state (chicken-and-egg: the state backend cannot
# store its own state). After applying, all other configs use these resources
# as their backend.
#
# Usage:
#   cd infrastructure/aws/bootstrap
#   terraform init
#   terraform apply

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.state_region
  profile = var.aws_profile
}

variable "project" {
  description = "Project name (short, lowercase, no spaces)"
  type        = string
  default     = "loom"
}

variable "state_region" {
  description = "AWS region for the Terraform state bucket (us-east-1 or us-west-2 recommended)"
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "AWS CLI profile for Terraform operations"
  type        = string
  default     = "loom-terraform"
}

data "aws_caller_identity" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  bucket_name = "${var.project}-terraform-state-${local.account_id}"
  lock_table  = "${var.project}-terraform-locks"
}

# --- S3 Bucket for Terraform State ---

resource "aws_s3_bucket" "terraform_state" {
  bucket = local.bucket_name

  tags = {
    project = var.project
    purpose = "terraform-remote-state"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    id     = "expire-old-state"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# --- DynamoDB Table for State Locking ---

resource "aws_dynamodb_table" "terraform_locks" {
  name         = local.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    project = var.project
    purpose = "terraform-state-locking"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# --- Outputs ---

output "state_bucket" {
  description = "S3 bucket name for Terraform state"
  value       = aws_s3_bucket.terraform_state.id
}

output "lock_table" {
  description = "DynamoDB table name for state locking"
  value       = aws_dynamodb_table.terraform_locks.name
}

output "backend_config" {
  description = "Paste this into other modules' terraform {} backend blocks"
  value       = <<-EOT
    backend "s3" {
      bucket         = "${local.bucket_name}"
      key            = "<module>/terraform.tfstate"
      region         = "${var.state_region}"
      dynamodb_table = "${local.lock_table}"
      encrypt        = true
      profile        = "${var.aws_profile}"
    }
  EOT
}
