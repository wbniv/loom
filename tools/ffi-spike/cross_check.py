#!/usr/bin/env python3
"""Cross-check: do `ctypes`'s own computed offsets for `llama_ffi.py`'s
hand-mirrored `_ModelParams`, `_ContextParams` and `_Batch` agree with the
offsets `generate.py` measured directly against the real pinned `llama.h`?

`ctypes` never reads a C header — a `ctypes.Structure` subclass's field
offsets are computed purely from the platform ABI's alignment rules applied
to the declared `_fields_`. So this is a genuine independent check: two
different mechanisms (a real C compiler vs. ctypes' own struct layout
algorithm) computing the same numbers from two different descriptions of
the same fields (the manifest in `fields.py`, and `llama_ffi.py`'s
hand-written `_fields_` lists) should land on identical offsets. A mismatch
here is not a bug in this spike to be quietly fixed — it is a FINDING about
the Python shim: it would mean `llama_ffi.py`'s struct declarations do not
actually match `libllama.so`'s real ABI on this machine, i.e. the exact
`_check_abi` defect class the shim's own docstring warns about, just not
yet caught by `_check_abi`'s coarser plausibility checks.

Usage: `python3 cross_check.py [--offsets generated/offsets.json]`
Exits 0 if every measured field matches ctypes exactly, 1 otherwise.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
LLAMA_FFI_PATH = REPO_ROOT / "prototype" / "experiment" / "llama_ffi.py"

#: Maps a struct name (as used in fields.py / offsets.json) to the class
#: name `llama_ffi.py` declares it under. These are "private" (leading
#: underscore) in that module, which is expected here: this script's whole
#: job is to reach into the shim's internals and check them, not to use the
#: module's public API.
CTYPES_CLASS_NAMES = {
    "llama_model_params": "_ModelParams",
    "llama_context_params": "_ContextParams",
    "llama_batch": "_Batch",
}


def load_llama_ffi_module():
    """Import llama_ffi.py by path, without needing prototype/ on sys.path
    and without triggering any of its (library-load-time) side effects --
    importing the module only defines classes and functions."""
    spec = importlib.util.spec_from_file_location("llama_ffi", LLAMA_FFI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ctypes_offsets(struct_cls) -> dict[str, dict]:
    offsets = {}
    for field_name, _ctype in struct_cls._fields_:
        field = getattr(struct_cls, field_name)
        offsets[field_name] = {"offset": field.offset, "size": field.size}
    return offsets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offsets", type=Path, default=HERE / "generated" / "offsets.json",
                         help="offsets.json written by generate.py")
    args = parser.parse_args(argv)

    if not args.offsets.is_file():
        print(f"error: {args.offsets} not found -- run generate.py first", file=sys.stderr)
        return 1
    if not LLAMA_FFI_PATH.is_file():
        print(f"error: {LLAMA_FFI_PATH} not found", file=sys.stderr)
        return 1

    measured = json.loads(args.offsets.read_text())["structs"]
    llama_ffi = load_llama_ffi_module()

    mismatches = []
    checked = 0
    for struct_name, class_name in CTYPES_CLASS_NAMES.items():
        struct_cls = getattr(llama_ffi, class_name)
        ct = ctypes_offsets(struct_cls)
        c = measured[struct_name]["fields"]

        ct_field_names = {name for name, _ in struct_cls._fields_}
        c_field_names = set(c)
        if ct_field_names != c_field_names:
            mismatches.append(
                f"{struct_name}: field sets differ -- ctypes has "
                f"{sorted(ct_field_names)}, the real header has {sorted(c_field_names)}")
            continue

        for field_name in ct_field_names:
            checked += 1
            if ct[field_name] != c[field_name]:
                mismatches.append(
                    f"{struct_name}.{field_name}: ctypes says "
                    f"offset={ct[field_name]['offset']} size={ct[field_name]['size']}, "
                    f"the real header says "
                    f"offset={c[field_name]['offset']} size={c[field_name]['size']}")

        ct_total = ctypes.sizeof(struct_cls)
        c_total = measured[struct_name]["sizeof"]
        if ct_total != c_total:
            mismatches.append(
                f"{struct_name}: ctypes.sizeof = {ct_total}, "
                f"the real header's sizeof = {c_total}")

    if mismatches:
        print(f"FINDING: {len(mismatches)} mismatch(es) between ctypes and the real "
              "llama.h -- the Python shim's ABI assumptions do not hold on this machine:",
              file=sys.stderr)
        for m in mismatches:
            print(f"  - {m}", file=sys.stderr)
        return 1

    print(f"cross-check clean: {checked} fields across {len(CTYPES_CLASS_NAMES)} structs, "
          "ctypes and the real llama.h agree on every offset, size and field set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
