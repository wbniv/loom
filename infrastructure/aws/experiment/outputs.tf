output "artifacts_bucket" {
  description = "S3 bucket the driver uploads to and downloads from."
  value       = module.experiment_runner.artifacts_bucket
}

output "status_key" {
  description = "S3 key of the completion marker the driver polls for."
  value       = module.experiment_runner.status_key
}

output "results_prefix" {
  description = "S3 prefix the runner syncs runs/ into."
  value       = module.experiment_runner.results_prefix
}

output "instance_id" {
  description = "Runner instance id, empty until launch_runner is true."
  value       = module.experiment_runner.instance_id
}

output "ami_id" {
  description = "AMI the runner booted from."
  value       = module.experiment_runner.ami_id
}
