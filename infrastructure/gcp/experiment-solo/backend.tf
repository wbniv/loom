# Same state bucket as ../experiment (see that root's backend.tf), a
# different prefix — full per-consumer state isolation. This root exists
# because the shared "experiment" prefix was clobbered once already
# (2026-08-23: a second worktree applied against it concurrently and
# overwrote its outputs) and because it now also runs alongside the T4
# diversity-harvest worktree's own GPU runs. "experiment-solo" is this
# arm's own state, its own artifacts bucket (see variables.tf), and shares
# nothing with any other consumer — the only thing still shared with any
# other run in this project is the account's GPU quota itself, which fails
# cleanly (a quota error) rather than corrupting state if two runs actually
# overlap.
terraform {
  backend "gcs" {
    bucket = "loom-tfstate-19b81040"
    prefix = "experiment-solo"
  }
}
