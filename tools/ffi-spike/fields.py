"""The single source of truth for the FFI spike: which fields of which
structs, and which llama.cpp entry points, this generator derives layouts
and bindings for.

Every field listed here is transcribed from `prototype/experiment/llama_ffi.py`'s
`_ModelParams`, `_ContextParams` and `_Batch` — the hand-mirrored `ctypes`
shim that is both the comparison target and the cross-check oracle for this
spike (see `cross_check.py`). Field *order* and *kind* are declared by hand
here (parsing C struct syntax generally is out of scope for a day's work);
what makes this a real drift check rather than a restatement of the same
assumption is that `generate.py` measures every field's `offsetof`/`sizeof`
by compiling and running a C program against the REAL pinned `llama.h` — if
a field here doesn't exist, or the header's layout disagrees with what a
consumer (Python's ctypes shim, or the generated SML) assumes, that shows up
as a measurement/compile failure, not as a silently-accepted guess.

Kind vocabulary (byte width in KIND_WIDTH), matching the `ctypes` types the
Python shim declares field-for-field:
    ptr     -> void* / T* / T**            (c_void_p, POINTER(...))  8 bytes
    i32     -> int32_t, or an enum (== int) c_int32 / c_int          4 bytes
    u32     -> uint32_t                     c_uint32                 4 bytes
    bool    -> C `_Bool`                    c_bool                   1 byte
    f32     -> float                        c_float                  4 bytes
    size_t  -> size_t                       c_size_t                 8 bytes
"""

from __future__ import annotations

KIND_WIDTH = {"ptr": 8, "i32": 4, "u32": 4, "bool": 1, "f32": 4, "size_t": 8}

STRUCTS: dict[str, dict] = {
    "llama_model_params": {
        "ctype": "struct llama_model_params",
        # Mirrors prototype/experiment/llama_ffi.py:_ModelParams._fields_
        "fields": [
            ("devices", "ptr"),
            ("tensor_buft_overrides", "ptr"),
            ("n_gpu_layers", "i32"),
            ("split_mode", "i32"),
            ("load_mode", "i32"),
            ("main_gpu", "i32"),
            ("tensor_split", "ptr"),
            ("progress_callback", "ptr"),
            ("progress_callback_user_data", "ptr"),
            ("kv_overrides", "ptr"),
            ("vocab_only", "bool"),
            ("check_tensors", "bool"),
            ("use_extra_bufts", "bool"),
            ("no_host", "bool"),
            ("no_alloc", "bool"),
            ("load_mtp", "bool"),
        ],
    },
    "llama_context_params": {
        "ctype": "struct llama_context_params",
        # Mirrors prototype/experiment/llama_ffi.py:_ContextParams._fields_
        "fields": [
            ("n_ctx", "u32"),
            ("n_batch", "u32"),
            ("n_ubatch", "u32"),
            ("n_seq_max", "u32"),
            ("n_rs_seq", "u32"),
            ("n_outputs_max", "u32"),
            ("n_outputs_max_per_seq", "u32"),
            ("n_threads", "i32"),
            ("n_threads_batch", "i32"),
            ("ctx_type", "i32"),
            ("rope_scaling_type", "i32"),
            ("pooling_type", "i32"),
            ("attention_type", "i32"),
            ("flash_attn_type", "i32"),
            ("rope_freq_base", "f32"),
            ("rope_freq_scale", "f32"),
            ("yarn_ext_factor", "f32"),
            ("yarn_attn_factor", "f32"),
            ("yarn_beta_fast", "f32"),
            ("yarn_beta_slow", "f32"),
            ("yarn_orig_ctx", "u32"),
            ("defrag_thold", "f32"),
            ("cb_eval", "ptr"),
            ("cb_eval_user_data", "ptr"),
            ("type_k", "i32"),
            ("type_v", "i32"),
            ("abort_callback", "ptr"),
            ("abort_callback_data", "ptr"),
            ("embeddings", "bool"),
            ("offload_kqv", "bool"),
            ("no_perf", "bool"),
            ("op_offload", "bool"),
            ("swa_full", "bool"),
            ("kv_unified", "bool"),
            ("samplers", "ptr"),
            ("n_samplers", "size_t"),
            ("ctx_other", "ptr"),
        ],
    },
    "llama_batch": {
        "ctype": "struct llama_batch",
        # Mirrors prototype/experiment/llama_ffi.py:_Batch._fields_
        "fields": [
            ("n_tokens", "i32"),
            ("token", "ptr"),
            ("embd", "ptr"),
            ("pos", "ptr"),
            ("n_seq_id", "ptr"),
            ("seq_id", "ptr"),
            ("logits", "ptr"),
        ],
    },
}

#: The subset of llama_ffi.py's declared entry points whose C signature is
#: scalar-only (no struct passed or returned by value). MLton's `_import`
#: has no struct-by-value marshalling (see ForeignFunctionInterfaceTypes:
#: only bool/char/int/real/word/MLton.Pointer.t and arrays/vectors thereof
#: cross the boundary) so these are the ones `generate.py` emits `_import`
#: declarations for. Kind vocabulary adds "unit" (void) and "str" (a
#: read-only `const char *`, passed as an SML `string` — safe here because
#: every string argument below carries an explicit length and does not rely
#: on NUL termination).
ENTRY_POINTS: list[tuple[str, list[str], str]] = [
    ("llama_backend_init", [], "unit"),
    ("llama_backend_free", [], "unit"),
    ("llama_model_free", ["ptr"], "unit"),
    ("llama_free", ["ptr"], "unit"),
    ("llama_set_n_threads", ["ptr", "i32", "i32"], "unit"),
    ("llama_model_get_vocab", ["ptr"], "ptr"),
    ("llama_vocab_n_tokens", ["ptr"], "i32"),
    ("llama_vocab_eos", ["ptr"], "i32"),
    ("llama_vocab_eot", ["ptr"], "i32"),
    # vocab, text, text_len, tokens-out, n_tokens_max, add_special, parse_special
    ("llama_tokenize", ["ptr", "str", "i32", "ptr", "i32", "i32", "i32"], "i32"),
    # vocab, token, buf-out, length, lstrip, special
    ("llama_token_to_piece", ["ptr", "i32", "ptr", "i32", "i32", "i32"], "i32"),
    # vocab, tokens, n_tokens, text-out, text_len_max, remove_special, unparse_special
    ("llama_detokenize", ["ptr", "ptr", "i32", "ptr", "i32", "i32", "i32"], "i32"),
    ("llama_n_batch", ["ptr"], "u32"),
    ("llama_n_ubatch", ["ptr"], "u32"),
    ("llama_get_logits_ith", ["ptr", "i32"], "ptr"),
]

#: What the Python shim declares that this generator deliberately does NOT
#: `_import` directly, and why. Recorded here so the omission is a decision,
#: not an oversight; see the SML file's header comment for the consequence.
STRUCT_VALUE_ENTRY_POINTS: list[tuple[str, str]] = [
    ("llama_model_default_params", "returns struct llama_model_params by value"),
    ("llama_context_default_params", "returns struct llama_context_params by value"),
    ("llama_model_load_from_file", "takes struct llama_model_params by value"),
    ("llama_init_from_model", "takes struct llama_context_params by value"),
    ("llama_batch_get_one", "returns struct llama_batch by value"),
    ("llama_decode", "takes struct llama_batch by value"),
    ("llama_log_set", "takes a C function pointer (callback) — needs _export, not attempted"),
]
