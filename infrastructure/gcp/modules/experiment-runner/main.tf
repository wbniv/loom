# The Deep Learning VM image ships the NVIDIA driver (staged, installed on
# first boot from metadata) and the full CUDA toolkit under /usr/local/cuda, so
# `cmake -DGGML_CUDA=ON` finds nvcc without a multi-gigabyte download. On a
# vanilla Ubuntu 22.04 image the same build needs a driver install, a reboot and
# a toolkit fetch before it can start compiling — 15-20 minutes of a rented
# GPU's clock, every run, for a dependency Google already baked.
#
# Selected by family rather than a pinned image name, so the image tracks
# Google's patches. Both family and project are variables: if Google renames the
# family the fix is a -var, not a code change. The resolved image name is a
# module output, and therefore recorded in state for any run being reproduced.
data "google_compute_image" "runner" {
  family  = var.image_family
  project = var.image_project
}

locals {
  instance_name = var.instance_suffix == "" ? "${var.project}-experiment-runner" : "${var.project}-experiment-runner-${var.instance_suffix}"

  # The bucket this instantiation addresses — its own, when it manages one, or
  # the name of one created by a sibling instantiation in the same apply.
  bucket_name = var.manage_bucket ? google_storage_bucket.artifacts[0].name : var.artifacts_bucket

  startup_script = templatefile("${path.module}/startup-script.sh.tftpl", {
    artifacts_bucket   = var.artifacts_bucket
    run_id             = var.run_id
    zone               = var.zone
    instance_name      = "${var.project}-experiment-runner"
    llama_cpp_repo     = var.llama_cpp_repo
    llama_cpp_revision = var.llama_cpp_revision
    gguf_filename      = var.gguf_filename
    model_identity     = var.model_identity
    hardware           = var.hardware
    n_gpu_layers       = var.n_gpu_layers
    context_size       = var.context_size
    parallel_slots     = var.parallel_slots
    remote_config_key  = var.remote_config_key
    remote_output_dir  = var.remote_output_dir
  })
}

resource "google_compute_instance" "runner" {
  count = var.launch_runner ? 1 : 0

  name         = local.instance_name
  project      = var.project_id
  zone         = var.zone
  machine_type = var.machine_type

  # An L4 is a hardware attachment, so a live-migration maintenance event is
  # impossible; the VM must be terminated instead. Spot VMs require this anyway.
  scheduling {
    provisioning_model          = var.use_spot ? "SPOT" : "STANDARD"
    preemptible                 = var.use_spot
    automatic_restart           = false
    on_host_maintenance         = "TERMINATE"
    instance_termination_action = var.use_spot ? "DELETE" : null
  }

  # The G2 family carries its L4 implicitly, so this block is empty by default.
  # See guest_accelerator_type for when it is not.
  dynamic "guest_accelerator" {
    for_each = var.guest_accelerator_type == "" ? [] : [var.guest_accelerator_type]
    content {
      type  = guest_accelerator.value
      count = var.guest_accelerator_count
    }
  }

  boot_disk {
    auto_delete = true
    initialize_params {
      image  = data.google_compute_image.runner.self_link
      size   = var.boot_disk_gb
      type   = var.boot_disk_type
      labels = var.labels
    }
  }

  network_interface {
    network    = var.network
    subnetwork = var.subnetwork == "" ? null : var.subnetwork

    # An ephemeral external IP, because the build clones llama.cpp from GitHub.
    # Private Google Access would cover GCS but not that, and a Cloud NAT
    # gateway costs more per hour than the GPU saves.
    access_config {}
  }

  service_account {
    email  = data.google_compute_default_service_account.runner.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  metadata = {
    # The DLVM image stages the NVIDIA driver but installs it on first boot
    # only when asked. Without this the image has CUDA and no kernel module.
    install-nvidia-driver = "True"
    startup-script        = local.startup_script
  }

  labels = merge(var.labels, {
    run_id = lower(replace(var.run_id, "/[^a-zA-Z0-9_-]/", "-"))
  })

  # No inbound access is needed, so no firewall rule is created; the instance
  # relies on the network's own defaults and initiates every connection itself.
  allow_stopping_for_update = true

  depends_on = [
    google_storage_bucket_iam_member.runner_objects,
    google_storage_bucket_iam_member.runner_bucket,
    google_project_iam_member.runner_self_delete,
  ]
}
