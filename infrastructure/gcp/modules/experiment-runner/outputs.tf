output "artifacts_bucket" {
  description = "GCS bucket the driver uploads to and downloads from."
  value       = google_storage_bucket.artifacts.name
}

output "run_id" {
  description = "Run identifier, echoed back for the driver's object-name construction."
  value       = var.run_id
}

output "status_key" {
  description = "GCS object name of the completion marker the driver polls for."
  value       = "status/${var.run_id}.txt"
}

output "results_prefix" {
  description = "GCS prefix the runner syncs runs/ into."
  value       = "results/${var.run_id}/"
}

output "instance_name" {
  description = "Runner instance name, or empty when launch_runner is false."
  value       = try(google_compute_instance.runner[0].name, "")
}

output "instance_zone" {
  description = "Zone the runner was launched into."
  value       = var.zone
}

output "image" {
  description = "Resolved image the runner booted from."
  value       = data.google_compute_image.runner.self_link
}

output "runner_service_account" {
  description = "Service account the runner runs as."
  value       = data.google_compute_default_service_account.runner.email
}
