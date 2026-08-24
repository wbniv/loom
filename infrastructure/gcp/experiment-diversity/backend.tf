# Same state bucket as ../experiment and ../experiment-pair (see ../experiment
# for why there is no bootstrap root), a **different prefix**, and that is the
# whole point of this root existing.
#
# On 2026-08-23 the diversity-harvest driver applied against ../experiment's
# state while the powered held-out A/B was mid-flight in the same state. Nothing
# was destroyed — the instance had not been created yet — but the apply
# overwrote the other run's `results_prefix` and `status_key` outputs, and one
# more minute would have had two drivers fighting over a single
# `loom-experiment-runner` instance name and a single GPU. Two roots that share
# a state prefix are one lock and one set of outputs, however carefully their
# variables differ.
#
# This root therefore contends with nothing: its own prefix, its own lock, its
# own bucket, its own instance name.
terraform {
  backend "gcs" {
    bucket = "loom-tfstate-19b81040"
    prefix = "experiment-diversity"
  }
}
