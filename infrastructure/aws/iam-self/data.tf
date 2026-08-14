data "aws_caller_identity" "current" {}

data "aws_iam_user" "self" {
  user_name = "loom-terraform"
}
