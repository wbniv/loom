#!/usr/bin/env python3
"""Render the GCP runner's startup-script template for linting.

The template is consumed by Terraform's `templatefile()`, so the two failure
modes worth catching before an instance is ever launched are a reference to a
variable the module does not pass (a plan-time error, discovered only when
someone is paying for a run) and bash that does not parse. This renders the
template with representative values, refuses any unknown interpolation, and
writes the result where `bash -n` and `shellcheck` can read it.

The set of covered template variables is *derived* from the module's
variables.tf rather than hand-copied into a dict here — a dict drifts out of
sync silently (this happened for real: `runlist_key` was added to the
template and to variables.tf but not to the old hand-maintained VALUES dict,
which blocked the self-delete guard from even rendering — see commit
d063460). variables.tf's own defaults are the completeness floor; OVERRIDES
supplies values for variables that have no default (required) or whose
default is empty/unrepresentative for a lint render, and LOCAL_VALUES covers
the handful of template placeholders that come from a Terraform `local`
rather than a module variable at all, so variables.tf cannot describe them.
Anything the template references that none of the three sources cover is a
hard failure — that is the exact bug class this replaces.

Usage: python3 scripts/render-gcp-startup-script.py [OUTPUT]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_DIR = ROOT / "infrastructure/gcp/modules/experiment-runner"
TEMPLATE = MODULE_DIR / "startup-script.sh.tftpl"
VARIABLES_TF = MODULE_DIR / "variables.tf"

#: Template placeholders that templatefile() receives from a Terraform
#: `local`, not a module variable — main.tf computes `instance_name` from
#: `var.project` and `var.instance_suffix`, so it has no variables.tf entry
#: to derive from and must be listed here by hand.
LOCAL_VALUES = {
    "instance_name": "loom-experiment-runner",
}

#: Hand-tuned values, keyed by variables.tf variable name. A variable lands
#: here for one of two reasons: it has no default at all (required — the
#: deriver has nothing to offer), or its default is empty/generic in a way
#: that would make a poor lint-render example (e.g. gguf_filename defaults to
#: "" meaning "autodetect the sole .gguf"). This is a value source, not a
#: completeness mechanism: a variable *without* an entry here still renders
#: fine as long as variables.tf gives it a non-empty default (see
#: `_template_values`) — that's what makes a newly-added optional variable
#: safe by construction instead of by remembering to update this file.
OVERRIDES = {
    "artifacts_bucket": "loom-experiment-artifacts",              # required, no default
    "run_id": "20260814-000000",                                  # required, no default
    "model_identity": "Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M",     # required, no default
    "gguf_filename": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",      # default "" means autodetect
    "llama_cpp_repo": "https://github.com/ggml-org/llama.cpp",     # default carries a trailing .git
    "remote_output_dir": "runs/phase-b",                          # default names an earlier phase
}

#: A single `${name}` that Terraform interpolates. `$${name}` is an escaped
#: literal and belongs to bash, so it must not match.
INTERPOLATION = re.compile(r"(?<!\$)\$\{(\w+)\}")

_VARIABLE_BLOCK = re.compile(r'variable\s+"([^"]+)"\s*\{')
_DEFAULT_LINE = re.compile(r"^\s*default\s*=\s*(.+?)\s*$", re.MULTILINE)


def _extract_block(text: str, open_brace_pos: int) -> str:
    """Return the contents between the braces of the block starting at
    `text[open_brace_pos] == '{'`, tracking nesting depth."""
    depth = 0
    for i in range(open_brace_pos, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_pos + 1 : i]
    raise ValueError("unbalanced braces in variables.tf")


def _parse_default(raw: str) -> str | None:
    """Convert one `default = <raw>` right-hand side to its template string
    form, or None if it is not a scalar (e.g. `{}` / `[]`) — no template
    variable so far is ever a map or list, so those are simply not offered
    as derived defaults."""
    raw = raw.strip()
    if raw in ("{}", "[]"):
        return None
    if raw in ("true", "false"):
        return raw
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if re.fullmatch(r"-?\d+(\.\d+)?", raw):
        return raw
    raise ValueError(f"variables.tf: don't know how to parse default value: {raw!r}")


def _module_variables(text: str) -> dict[str, str | None]:
    """Parse variables.tf into {name: default-as-template-string}, with None
    for a variable that declares no default (required)."""
    variables: dict[str, str | None] = {}
    for match in _VARIABLE_BLOCK.finditer(text):
        name = match.group(1)
        block = _extract_block(text, match.end() - 1)
        default_match = _DEFAULT_LINE.search(block)
        variables[name] = None if default_match is None else _parse_default(default_match.group(1))
    return variables


def _template_values() -> dict[str, str]:
    """Build the full set of values available to render the template:
    variables.tf's own non-empty defaults, topped up by OVERRIDES and
    LOCAL_VALUES."""
    module_vars = _module_variables(VARIABLES_TF.read_text(encoding="utf-8"))

    stale_overrides = sorted(set(OVERRIDES) - set(module_vars))
    if stale_overrides:
        raise SystemExit(
            "OVERRIDES names a variable variables.tf no longer declares "
            f"(renamed or removed?): {', '.join(stale_overrides)}"
        )

    derived = {name: default for name, default in module_vars.items() if default is not None}
    return {**derived, **OVERRIDES, **LOCAL_VALUES}


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    text = TEMPLATE.read_text(encoding="utf-8")
    values = _template_values()
    unknown = sorted(set(INTERPOLATION.findall(text)) - set(values))
    if unknown:
        print(
            "template references variables no value is available for: "
            f"{', '.join(unknown)}\n"
            "add a default in variables.tf, or an OVERRIDES/LOCAL_VALUES "
            f"entry in {Path(__file__).name}.",
            file=sys.stderr,
        )
        return 1
    rendered = INTERPOLATION.sub(lambda m: values[m.group(1)], text)
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
