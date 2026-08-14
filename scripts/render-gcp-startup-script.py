#!/usr/bin/env python3
"""Render the GCP runner's startup-script template for linting.

The template is consumed by Terraform's `templatefile()`, so the two failure
modes worth catching before an instance is ever launched are a reference to a
variable the module does not pass (a plan-time error, discovered only when
someone is paying for a run) and bash that does not parse. This renders the
template with representative values, refuses any unknown interpolation, and
writes the result where `bash -n` and `shellcheck` can read it.

Usage: python3 scripts/render-gcp-startup-script.py [OUTPUT]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "infrastructure/gcp/modules/experiment-runner/startup-script.sh.tftpl"

#: Representative values, one per variable the module's `templatefile()` passes.
VALUES = {
    "artifacts_bucket": "loom-experiment-artifacts",
    "run_id": "20260814-000000",
    "zone": "us-central1-a",
    "instance_name": "loom-experiment-runner",
    "llama_cpp_repo": "https://github.com/ggml-org/llama.cpp",
    "llama_cpp_revision": "1f368f354d9edcfea9fd6a1e0989b3e7335a050f",
    "gguf_filename": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
    "model_identity": "Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M",
    "hardware": "g2-standard-4 L4 24GB",
    "n_gpu_layers": "99",
    "context_size": "16384",
    "parallel_slots": "1",
    "remote_config_key": "config/run.config.json",
    "remote_output_dir": "runs/phase-b",
}

#: A single `${name}` that Terraform interpolates. `$${name}` is an escaped
#: literal and belongs to bash, so it must not match.
INTERPOLATION = re.compile(r"(?<!\$)\$\{(\w+)\}")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    text = TEMPLATE.read_text(encoding="utf-8")
    unknown = sorted(set(INTERPOLATION.findall(text)) - set(VALUES))
    if unknown:
        print(f"template references variables the module does not pass: "
              f"{', '.join(unknown)}", file=sys.stderr)
        return 1
    rendered = INTERPOLATION.sub(lambda m: VALUES[m.group(1)], text)
    rendered = rendered.replace("$${", "${")
    destination = Path(argv[0]) if argv else None
    if destination is None:
        sys.stdout.write(rendered)
    else:
        destination.write_text(rendered, encoding="utf-8")
        print(f"rendered ok, no unknown interpolation: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
