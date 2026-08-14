# The runner's only privileges are the artifacts bucket and the right to delete
# itself. No logging sink, no Secret Manager, no other bucket — the log is a
# file synced to GCS like everything else.
#
# The identity is the project's default Compute Engine service account rather
# than a dedicated one. Creating a service account needs iam.serviceAccounts.create
# on the project, which the trial-project owner has but which would make this
# module fail for anyone running it with narrower credentials; the default SA
# already exists in every project with the Compute API on. The narrowing is done
# entirely by the bindings below, all of which are bucket- or instance-scoped.

data "google_compute_default_service_account" "runner" {
  project = var.project_id
}

# Read the experiment inputs and write the results back — on this bucket only.
resource "google_storage_bucket_iam_member" "runner_objects" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${data.google_compute_default_service_account.runner.email}"
}

# objectAdmin covers the objects but not `storage.buckets.get`, which gsutil
# calls before an rsync. legacyBucketReader is the smallest role that adds it,
# and it is scoped to this bucket like everything else here.
resource "google_storage_bucket_iam_member" "runner_bucket" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.legacyBucketReader"
  member = "serviceAccount:${data.google_compute_default_service_account.runner.email}"
}

# Belt to the driver's braces: the startup script deletes the instance when the
# run ends, so a driver that is killed outright still does not leave a GPU
# standing. The role is project-level because compute.instances.delete has no
# smaller attachment point, but the IAM condition pins it to this one instance
# name — the SA cannot touch any other VM in the project.
resource "google_project_iam_member" "runner_self_delete" {
  project = var.project_id
  role    = "roles/compute.instanceAdmin.v1"
  member  = "serviceAccount:${data.google_compute_default_service_account.runner.email}"

  condition {
    title       = "only-the-loom-experiment-runner"
    description = "Restricts this grant to the single instance this module creates."
    expression  = "resource.type == \"compute.googleapis.com/Instance\" && resource.name.endsWith(\"/instances/${local.instance_name}\")"
  }
}
