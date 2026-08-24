output "artifacts_bucket" {
  description = "GCS bucket this root owns outright."
  value       = module.experiment_runner.artifacts_bucket
}

output "status_key" {
  description = "GCS object name of the completion marker the driver polls."
  value       = module.experiment_runner.status_key
}

output "results_prefix" {
  description = "GCS prefix the runner syncs runs/ into."
  value       = module.experiment_runner.results_prefix
}

output "instance_name" {
  description = "Runner instance name, empty until launch_runner is true."
  value       = module.experiment_runner.instance_name
}

output "runner_service_account" {
  description = "Service account the runner runs as (the project default SA, narrowed to this root's instance by IAM condition)."
  value       = module.experiment_runner.runner_service_account
}
