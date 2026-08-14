data "aws_region" "current" {}

# The AWS Deep Learning Base GPU AMI ships the NVIDIA driver and the full CUDA
# toolkit, so `cmake -DGGML_CUDA=ON` finds nvcc on first boot. On vanilla Ubuntu
# 24.04 the same build needs a driver install, a reboot and a CUDA toolkit
# download before it can even start compiling — roughly 15-20 minutes of a
# rented GPU's time, every run, for a dependency AWS already baked.
data "aws_ami" "runner" {
  most_recent = true
  owners      = [var.ami_owner]

  filter {
    name   = "name"
    values = [var.ami_name_filter]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "runner" {
  name        = "${var.project}-experiment-runner"
  description = "Egress-only for the ${var.project} experiment runner; the run needs no inbound access."
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "All egress: S3, the llama.cpp remote, apt."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Only present when the operator explicitly opens it to debug a run that
  # never produced a status object.
  dynamic "ingress" {
    for_each = var.ssh_ingress_cidr == "" ? [] : [var.ssh_ingress_cidr]
    content {
      description = "Debug SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  tags = {
    Name = "${var.project}-experiment-runner"
  }
}

locals {
  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    artifacts_bucket   = aws_s3_bucket.artifacts.id
    run_id             = var.run_id
    region             = data.aws_region.current.name
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

resource "aws_instance" "runner" {
  count = var.launch_runner ? 1 : 0

  ami                    = data.aws_ami.runner.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id == "" ? null : var.subnet_id
  vpc_security_group_ids = [aws_security_group.runner.id]
  iam_instance_profile   = aws_iam_instance_profile.runner.name
  key_name               = var.key_name == "" ? null : var.key_name

  # Belt to the user-data script's braces: the run ends with `shutdown -h`, and
  # a one-time spot instance that shuts itself down must terminate rather than
  # linger in `stopped` accruing EBS charges.
  instance_initiated_shutdown_behavior = "terminate"

  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        spot_instance_type             = "one-time"
        instance_interruption_behavior = "terminate"
        max_price                      = var.spot_max_price == "" ? null : var.spot_max_price
      }
    }
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    delete_on_termination = true
    encrypted             = true
  }

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  user_data                   = local.user_data
  user_data_replace_on_change = true

  tags = {
    Name  = "${var.project}-experiment-runner"
    RunId = var.run_id
  }

  depends_on = [
    aws_iam_role_policy_attachment.runner_artifacts,
    aws_s3_bucket_public_access_block.artifacts,
  ]
}
