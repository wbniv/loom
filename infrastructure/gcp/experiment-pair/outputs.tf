output "artifacts_bucket" {
  description = "GCS bucket both arms share."
  value       = module.arm_a.artifacts_bucket
}

output "status_key_a" {
  description = "GCS object name of arm A's completion marker."
  value       = module.arm_a.status_key
}

output "results_prefix_a" {
  description = "GCS prefix arm A's runner syncs runs/ into."
  value       = module.arm_a.results_prefix
}

output "instance_name_a" {
  description = "Arm A's runner instance name, empty until launch_runner is true."
  value       = module.arm_a.instance_name
}

output "status_key_b" {
  description = "GCS object name of arm B's completion marker."
  value       = module.arm_b.status_key
}

output "results_prefix_b" {
  description = "GCS prefix arm B's runner syncs runs/ into."
  value       = module.arm_b.results_prefix
}

output "instance_name_b" {
  description = "Arm B's runner instance name, empty until launch_runner is true."
  value       = module.arm_b.instance_name
}

output "runner_service_account" {
  description = "Service account both runners run as (the project default SA, narrowed per-instance by IAM condition)."
  value       = module.arm_a.runner_service_account
}
