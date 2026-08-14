# The runner's only AWS privilege is the artifacts bucket. No SSM, no
# CloudWatch, no other bucket — the log is a file synced to S3 like everything
# else.

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "runner" {
  name               = "${var.project}-experiment-runner"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

data "aws_iam_policy_document" "runner_artifacts" {
  statement {
    sid       = "ListArtifactsBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid = "ReadWriteArtifacts"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]
  }
}

resource "aws_iam_policy" "runner_artifacts" {
  name        = "${var.project}-experiment-runner-artifacts"
  description = "Read the experiment inputs and write the results back, and nothing else."
  policy      = data.aws_iam_policy_document.runner_artifacts.json
}

resource "aws_iam_role_policy_attachment" "runner_artifacts" {
  role       = aws_iam_role.runner.name
  policy_arn = aws_iam_policy.runner_artifacts.arn
}

resource "aws_iam_instance_profile" "runner" {
  name = "${var.project}-experiment-runner"
  role = aws_iam_role.runner.name
}
