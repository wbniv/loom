output "artifacts_bucket" {
  description = "S3 bucket the driver uploads to and downloads from."
  value       = aws_s3_bucket.artifacts.id
}

output "run_id" {
  description = "Run identifier, echoed back for the driver's S3 key construction."
  value       = var.run_id
}

output "status_key" {
  description = "S3 key of the completion marker the driver polls for."
  value       = "status/${var.run_id}.txt"
}

output "results_prefix" {
  description = "S3 prefix the runner syncs runs/ into."
  value       = "results/${var.run_id}/"
}

output "instance_id" {
  description = "Runner instance id, or empty when launch_runner is false."
  value       = try(aws_instance.runner[0].id, "")
}

output "ami_id" {
  description = "AMI the runner booted from."
  value       = data.aws_ami.runner.id
}

output "instance_role_arn" {
  description = "IAM role the runner assumes."
  value       = aws_iam_role.runner.arn
}
