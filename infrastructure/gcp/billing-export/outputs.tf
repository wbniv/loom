output "dataset_id" {
  description = "BigQuery dataset id to select on the console's Billing export page."
  value       = google_bigquery_dataset.billing_export.dataset_id
}

output "dataset_location" {
  description = "Location the dataset was created in. The console's dataset picker must match this — BigQuery cannot move a dataset after creation."
  value       = google_bigquery_dataset.billing_export.location
}

output "self_link" {
  description = "Full dataset resource reference."
  value       = google_bigquery_dataset.billing_export.self_link
}
