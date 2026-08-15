# SML FFI generator spike

The measured half of batch 2's SML FFI amendment (A2): does deriving
`llama_model_params`/`llama_context_params`/`llama_batch` layouts from the
real, pinned `llama.h` at build time actually work, in both the C and the
SML direction? Verdict recorded in
[the batch-2 study](../../docs/investigations/2026-08-14-language-eval-batch-2.md#sml-ffi-generator-spike-addendum-a3).

Run it: `task ffi-spike` (or `./run.sh` directly).

## What's here

| File | What it is |
|---|---|
| `fields.py` | The manifest: which fields, of which three structs, and which llama.cpp entry points. The one thing declared by hand. |
| `generate.py` | Compiles+runs a C probe against the *real* pinned `llama.h`, measures every field's `offsetof`/`sizeof`, and emits `generated/offsets.json`, `generated/offsets_check.c` (the static_assert drift gate) and `generated/llama_ffi_generated.sml`. |
| `cross_check.py` | Compares the measured offsets against what `ctypes` itself computes for `prototype/experiment/llama_ffi.py`'s hand-written structs — an independent second oracle. |
| `smoke_test.sml` | Hand-written: calls the generated `_import`s against the real `libllama.so`, and round-trips a struct field through a generated accessor. |
| `ffi_spike.mlb` | The MLton project file tying the generated SML and the smoke test together. |
| `run.sh` | Runs all of the above in order, fetching a pinned MLton release into `~/.local` if it isn't already there. |
| `generated/` | Gitignored — reproduced byte-for-byte by `run.sh`, same convention as `prototype/`'s `differential:export`. |

## What this does not attempt

`llama_model_default_params`, `llama_context_default_params`,
`llama_model_load_from_file`, `llama_init_from_model`, `llama_batch_get_one`
and `llama_decode` all pass or return one of the three structs *by value*,
which MLton's `_import` cannot marshal directly (see
`generated/llama_ffi_generated.sml`'s header comment once generated, or
`ForeignFunctionInterfaceTypes` in the MLton docs). A real binding needs a
small generated C shim taking/returning these by pointer instead — itself
generatable from the same manifest, but out of scope for a one-day spike.
`llama_log_set` takes a C function pointer and would need `_export`, also
not attempted.
