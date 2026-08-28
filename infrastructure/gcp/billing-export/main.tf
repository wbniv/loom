# Everything Terraform-able on this project's side of GCP billing export.
#
# The one piece Terraform (and the GCP API generally) cannot reach is turning
# the export itself on: Billing export configuration lives on the *billing
# account*, not the project, and Google exposes no API or Terraform resource
# for it — only the console page at
# https://console.cloud.google.com/billing/export. That is the single manual
# step this root cannot absorb; everything else (the dataset it needs to
# point at, the API it needs enabled) is created here so the console step is
# reduced to "pick this dataset".
#
# docs/plans/... : no plan file exists for this change — it was dispatched as
# a fully specified TODO item ([gcp-billing-export]), which is the settled
# contract here in place of a separate plan doc.

# Billing export writes via BigQuery, and this is a fresh-enough concept in
# this project that the API is not guaranteed on. Enabling it here (rather
# than assuming it) is what makes this root reproducible from a clean
# project. disable_on_destroy = false: a `terraform destroy` of this root
# should remove the dataset it created, not reach across and disable an API
# other roots (or manual `bq` use) might depend on.
resource "google_project_service" "bigquery" {
  project            = var.project_id
  service            = "bigquery.googleapis.com"
  disable_on_destroy = false
}

# The target dataset for the export. Table expiration is left unset
# (BigQuery's default: never expire) — billing history is exactly the data
# you don't want silently aged out, unlike the scratch datasets a TTL is
# usually protecting against.
resource "google_bigquery_dataset" "billing_export" {
  dataset_id    = var.dataset_id
  friendly_name = "GCP billing export"
  description   = "Cloud Billing BigQuery export target. Wired to the billing account manually at https://console.cloud.google.com/billing/export; see main.tf for why that step can't be Terraform."
  location      = var.dataset_location

  depends_on = [google_project_service.bigquery]
}

# No IAM resource here on purpose. When the console's Billing export page
# turns the export on against this dataset, Google grants the Cloud Billing
# service agent BigQuery Data Editor on the dataset automatically as part of
# that flow — this is documented behavior, not an assumption, and there is no
# principal Terraform could grant it to in advance (the service agent's
# identity is only realized when the export is enabled). If spend queries
# ever fail with a permissions error rather than "table not found", that is
# the thing to check in the console, not a grant to add here.
