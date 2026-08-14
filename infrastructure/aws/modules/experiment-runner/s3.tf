# The artifacts bucket is the only channel between the operator's laptop and
# the runner: repo tarball and GGUFs go in, runs/ and the log come back, and a
# status object under status/ is what tells the driver the run is over. It is
# created on the first (launch_runner = false) apply so the driver has
# somewhere to upload before the instance exists.

resource "aws_s3_bucket" "artifacts" {
  bucket = var.artifacts_bucket

  # The bucket is torn down with the rest of the run; force_destroy lets that
  # happen with the tarball, models and results still in it.
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# A leftover bucket after an interrupted run costs storage for the models until
# someone notices. Expire everything after a week as a backstop; a run lasts
# about two hours.
resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "expire-experiment-artifacts"
    status = "Enabled"

    filter {}

    expiration {
      days = 7
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
