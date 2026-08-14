"""R1's transport: the pinned `libllama.so`, driven in process through ctypes.

Why this and not `llama-cpp-python`
-----------------------------------
R1's criteria are *exact token-id-level masking*, *measurable per-token
overhead*, and *the same GGUF and sampling parameters as Phase A*. The decision
and the rejected alternatives are recorded in the plan; the load-bearing fact is
that `llama-cpp-python` publishes **source distributions only** (checked across
0.3.27-0.3.34), so adopting it means building a *second, differently pinned*
copy of llama.cpp — which is precisely the engine-identity that the
comparability criterion asks us to hold fixed. Binding the build Phase A already
uses costs one module and keeps the engine identical.

What it needs, and what it does not
-----------------------------------
It needs about fifteen entry points — load, tokenize, decode one token, read
logits, detokenize — because the mask does **not** use llama.cpp's grammar
engine: `gbnf.Grammar` is the syntax layer, so no sampler chain, no grammar
handle, and no sampler ABI is involved. Nothing in this module is imported
unless a run configures the `llama-cpp` backend, so `task prototype:test` never
loads a shared library.

Two guards, because a hand-written ABI transcription can be wrong in ways that
segfault rather than raise:

* `_check_abi` asserts the documented defaults come back from
  `llama_model_default_params` / `llama_context_default_params`. A struct
  transcribed against the wrong llama.cpp will fail this instead of corrupting
  memory later.
* `LlamaModel.__init__` asserts that **detokenization is concatenation** —
  `detokenize(ts) == b"".join(piece(t))`. The whole mask rests on treating a
  token as its bytes; a tokenizer where that is false would make the mask
  unsound at the token boundary, and this refuses to run rather than mask
  unsoundly.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

#: Where the pinned build lives. Overridable per run; the plan records the pin.
DEFAULT_LIB = Path.home() / "loom-tools/llama.cpp/build/bin/libllama.so"


class FfiUnavailable(RuntimeError):
    """The library is missing, unloadable, or does not match the ABI here."""


# --------------------------------------------------------------------------
# ABI
# --------------------------------------------------------------------------


class _ModelParams(ctypes.Structure):
    _fields_ = [
        ("devices", ctypes.c_void_p),
        ("tensor_buft_overrides", ctypes.c_void_p),
        ("n_gpu_layers", ctypes.c_int32),
        ("split_mode", ctypes.c_int),
        ("load_mode", ctypes.c_int),
        ("main_gpu", ctypes.c_int32),
        ("tensor_split", ctypes.c_void_p),
        ("progress_callback", ctypes.c_void_p),
        ("progress_callback_user_data", ctypes.c_void_p),
        ("kv_overrides", ctypes.c_void_p),
        ("vocab_only", ctypes.c_bool),
        ("check_tensors", ctypes.c_bool),
        ("use_extra_bufts", ctypes.c_bool),
        ("no_host", ctypes.c_bool),
        ("no_alloc", ctypes.c_bool),
        ("load_mtp", ctypes.c_bool),
    ]


class _ContextParams(ctypes.Structure):
    _fields_ = [
        ("n_ctx", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint32),
        ("n_ubatch", ctypes.c_uint32),
        ("n_seq_max", ctypes.c_uint32),
        ("n_rs_seq", ctypes.c_uint32),
        ("n_outputs_max", ctypes.c_uint32),
        ("n_outputs_max_per_seq", ctypes.c_uint32),
        ("n_threads", ctypes.c_int32),
        ("n_threads_batch", ctypes.c_int32),
        ("ctx_type", ctypes.c_int),
        ("rope_scaling_type", ctypes.c_int),
        ("pooling_type", ctypes.c_int),
        ("attention_type", ctypes.c_int),
        ("flash_attn_type", ctypes.c_int),
        ("rope_freq_base", ctypes.c_float),
        ("rope_freq_scale", ctypes.c_float),
        ("yarn_ext_factor", ctypes.c_float),
        ("yarn_attn_factor", ctypes.c_float),
        ("yarn_beta_fast", ctypes.c_float),
        ("yarn_beta_slow", ctypes.c_float),
        ("yarn_orig_ctx", ctypes.c_uint32),
        ("defrag_thold", ctypes.c_float),
        ("cb_eval", ctypes.c_void_p),
        ("cb_eval_user_data", ctypes.c_void_p),
        ("type_k", ctypes.c_int),
        ("type_v", ctypes.c_int),
        ("abort_callback", ctypes.c_void_p),
        ("abort_callback_data", ctypes.c_void_p),
        ("embeddings", ctypes.c_bool),
        ("offload_kqv", ctypes.c_bool),
        ("no_perf", ctypes.c_bool),
        ("op_offload", ctypes.c_bool),
        ("swa_full", ctypes.c_bool),
        ("kv_unified", ctypes.c_bool),
        ("samplers", ctypes.c_void_p),
        ("n_samplers", ctypes.c_size_t),
        ("ctx_other", ctypes.c_void_p),
    ]


class _Batch(ctypes.Structure):
    _fields_ = [
        ("n_tokens", ctypes.c_int32),
        ("token", ctypes.POINTER(ctypes.c_int32)),
        ("embd", ctypes.POINTER(ctypes.c_float)),
        ("pos", ctypes.POINTER(ctypes.c_int32)),
        ("n_seq_id", ctypes.POINTER(ctypes.c_int32)),
        ("seq_id", ctypes.POINTER(ctypes.POINTER(ctypes.c_int32))),
        ("logits", ctypes.POINTER(ctypes.c_int8)),
    ]


_LOG_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)


def _silence(level, text, user_data):  # pragma: no cover - called from C
    return None


_SILENCER = _LOG_CALLBACK(_silence)

_LIBRARIES: dict[str, ctypes.CDLL] = {}


def load_library(path=None) -> ctypes.CDLL:
    """Open `libllama.so` once per path and declare every signature used."""
    location = Path(path or os.environ.get("LOOM_LLAMA_LIB") or DEFAULT_LIB)
    key = str(location)
    if key in _LIBRARIES:
        return _LIBRARIES[key]
    if not location.exists():
        raise FfiUnavailable(
            f"llama.cpp shared library not found at {location}.\n"
            "Set \"llama_lib\" in the run config (or LOOM_LLAMA_LIB) to the "
            "`libllama.so` of the pinned build recorded in the parent plan.")
    try:
        library = ctypes.CDLL(str(location))
    except OSError as error:
        raise FfiUnavailable(f"could not load {location}: {error}") from error

    def declare(name, restype, argtypes):
        try:
            function = getattr(library, name)
        except AttributeError as error:
            raise FfiUnavailable(
                f"{location} exports no {name}; this build is not the pinned "
                "llama.cpp the transport was written against") from error
        function.restype = restype
        function.argtypes = argtypes
        return function

    declare("llama_backend_init", None, [])
    declare("llama_backend_free", None, [])
    declare("llama_log_set", None, [_LOG_CALLBACK, ctypes.c_void_p])
    declare("llama_model_default_params", _ModelParams, [])
    declare("llama_context_default_params", _ContextParams, [])
    declare("llama_model_load_from_file", ctypes.c_void_p, [ctypes.c_char_p, _ModelParams])
    declare("llama_model_free", None, [ctypes.c_void_p])
    declare("llama_init_from_model", ctypes.c_void_p, [ctypes.c_void_p, _ContextParams])
    declare("llama_free", None, [ctypes.c_void_p])
    declare("llama_set_n_threads", None, [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32])
    declare("llama_model_get_vocab", ctypes.c_void_p, [ctypes.c_void_p])
    declare("llama_vocab_n_tokens", ctypes.c_int32, [ctypes.c_void_p])
    declare("llama_vocab_eos", ctypes.c_int32, [ctypes.c_void_p])
    declare("llama_vocab_eot", ctypes.c_int32, [ctypes.c_void_p])
    declare("llama_tokenize", ctypes.c_int32, [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32), ctypes.c_int32, ctypes.c_bool, ctypes.c_bool])
    declare("llama_token_to_piece", ctypes.c_int32, [
        ctypes.c_void_p, ctypes.c_int32, ctypes.c_char_p, ctypes.c_int32,
        ctypes.c_int32, ctypes.c_bool])
    declare("llama_detokenize", ctypes.c_int32, [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32), ctypes.c_int32,
        ctypes.c_char_p, ctypes.c_int32, ctypes.c_bool, ctypes.c_bool])
    declare("llama_batch_get_one", _Batch, [ctypes.POINTER(ctypes.c_int32), ctypes.c_int32])
    declare("llama_decode", ctypes.c_int32, [ctypes.c_void_p, _Batch])
    # The *effective* batch sizes, read back rather than assumed: llama.cpp
    # clamps them at context creation
    # (`cparams.n_batch = min(n_ctx, params.n_batch)` for causal attention), and
    # `llama_decode`'s assert compares against the clamped value. Computing it
    # here instead of asking would be the same class of guess that aborted a run.
    declare("llama_n_batch", ctypes.c_uint32, [ctypes.c_void_p])
    declare("llama_n_ubatch", ctypes.c_uint32, [ctypes.c_void_p])
    declare("llama_get_logits_ith", ctypes.POINTER(ctypes.c_float), [
        ctypes.c_void_p, ctypes.c_int32])

    _check_abi(library, location)
    library.llama_log_set(_SILENCER, None)
    library.llama_backend_init()
    _LIBRARIES[key] = library
    return library


def _check_abi(library, location) -> None:
    """Fail loudly on a mis-transcribed struct instead of quietly corrupting.

    The assertions are *plausibility* checks over fields whose defaults llama.cpp
    has held stable, not exact-value checks: `n_gpu_layers` in particular has
    defaulted to `-1` ("all layers, falling back where there is no device")
    since the offload rework, and pinning it to `0` here produced a false
    positive on the very build this transport targets. What a misaligned struct
    actually looks like is garbage in the pointer and count fields, so those are
    what get checked.
    """
    model = library.llama_model_default_params()
    context = library.llama_context_default_params()
    problems = []
    if not (-1 <= model.n_gpu_layers <= 1024) or model.main_gpu != 0 or model.devices:
        problems.append(
            f"llama_model_default_params looks wrong "
            f"(n_gpu_layers={model.n_gpu_layers}, main_gpu={model.main_gpu}, "
            f"devices={model.devices})")
    if model.vocab_only or model.no_alloc or model.check_tensors:
        problems.append(
            f"llama_model_default_params booleans look wrong "
            f"(vocab_only={model.vocab_only}, no_alloc={model.no_alloc}, "
            f"check_tensors={model.check_tensors})")
    if context.n_ctx != 512 or context.n_seq_max < 1 or context.n_threads < 1:
        problems.append(
            f"llama_context_default_params looks wrong "
            f"(n_ctx={context.n_ctx}, n_seq_max={context.n_seq_max}, "
            f"n_threads={context.n_threads})")
    if context.samplers or context.n_samplers or context.embeddings:
        problems.append(
            f"llama_context_default_params tail looks wrong "
            f"(samplers={context.samplers}, n_samplers={context.n_samplers}, "
            f"embeddings={context.embeddings})")
    if problems:
        raise FfiUnavailable(
            f"{location} does not match the ABI this transport was written "
            "against; refusing rather than reading a mis-shaped struct.\n  "
            + "\n  ".join(problems))


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------


class LlamaModel:
    """One loaded GGUF plus one context: tokenize, decode, read logits."""

    #: llama.cpp's own default for `n_gpu_layers`: every layer offloaded, falling
    #: back to CPU where there is no device. Correct on a CPU-only laptop *and*
    #: on the L4 the matrix runs on, which is the point — it was hardcoded to `0`
    #: ("this box is CPU-only, by the plan") while Phase B was developed here,
    #: and that would have silently run the whole condition-4 matrix on the
    #: instance's four vCPUs while a 24 GB L4 sat idle.
    ALL_LAYERS = -1

    #: Batch sizes are *not* tied to `n_ctx`. Prompt eval happens in chunks, and
    #: sizing the compute buffer for a 16k context allocates for a 16k-token
    #: micro-batch that is never used. These are llama.cpp's own defaults.
    DEFAULT_N_BATCH = 2048
    DEFAULT_N_UBATCH = 512

    def __init__(self, model_path, *, lib_path=None, n_ctx=4096, n_threads=0,
                 n_batch=0, n_ubatch=0, n_gpu_layers=ALL_LAYERS) -> None:
        path = Path(model_path)
        if not path.exists():
            raise FfiUnavailable(f"GGUF not found: {path}")
        self.library = load_library(lib_path)
        self.model_path = str(path)

        params = self.library.llama_model_default_params()
        params.n_gpu_layers = int(n_gpu_layers)
        self.n_gpu_layers = int(n_gpu_layers)
        self.model = self.library.llama_model_load_from_file(str(path).encode("utf-8"), params)
        if not self.model:
            raise FfiUnavailable(f"llama.cpp could not load {path}")
        self.vocab = self.library.llama_model_get_vocab(self.model)
        self.n_vocab = int(self.library.llama_vocab_n_tokens(self.vocab))
        self.eos = int(self.library.llama_vocab_eos(self.vocab))
        self.eot = int(self.library.llama_vocab_eot(self.vocab))

        context_params = self.library.llama_context_default_params()
        context_params.n_ctx = int(n_ctx)
        self.n_batch = int(n_batch or min(self.DEFAULT_N_BATCH, n_ctx))
        self.n_ubatch = int(n_ubatch or min(self.DEFAULT_N_UBATCH, self.n_batch))
        context_params.n_batch = self.n_batch
        context_params.n_ubatch = self.n_ubatch
        # The parent plan's amendment record is explicit: KV-cache quantization
        # cut prompt eval to ~12 tok/s on this CPU, so the defaults stand.
        if n_threads:
            context_params.n_threads = int(n_threads)
            context_params.n_threads_batch = int(n_threads)
        # Kept so `_recreate` rebuilds the *same* context once per draw. It used
        # to construct fresh defaults, which quietly dropped `n_threads` and
        # re-tied the batch to `n_ctx` after the very first draw.
        self._context_params = context_params
        self.n_ctx = int(n_ctx)
        self.context = None
        try:
            self._bind_context()
        except FfiUnavailable:
            self.close()
            raise
        self._check_tokenizer()

    def _bind_context(self) -> None:
        """Create the context and read the batch sizes llama.cpp actually chose.

        `cparams.n_batch = min(n_ctx, params.n_batch)` under causal attention, so
        the effective batch can be smaller than the one requested — and it is the
        effective one that `llama_decode`'s `GGML_ASSERT(n_tokens_all <=
        cparams.n_batch)` compares against. Reading it back makes `decode`'s
        chunking correct by construction rather than by matching arithmetic to a
        clamping rule that could change under a version bump.
        """
        self.context = self.library.llama_init_from_model(
            self.model, self._context_params)
        if not self.context:
            raise FfiUnavailable("llama.cpp could not create a context")
        self.n_batch = int(self.library.llama_n_batch(self.context))
        self.n_ubatch = int(self.library.llama_n_ubatch(self.context))
        self._position = 0

    # -- tokenizer -------------------------------------------------------

    def tokenize(self, text: str, *, add_special=False, parse_special=True) -> list[int]:
        data = text.encode("utf-8")
        size = len(data) + 16
        buffer = (ctypes.c_int32 * size)()
        count = self.library.llama_tokenize(
            self.vocab, data, len(data), buffer, size, add_special, parse_special)
        if count < 0:
            size = -count
            buffer = (ctypes.c_int32 * size)()
            count = self.library.llama_tokenize(
                self.vocab, data, len(data), buffer, size, add_special, parse_special)
        if count < 0:  # pragma: no cover - the retry above is the documented path
            raise FfiUnavailable("llama_tokenize refused twice")
        return [int(buffer[i]) for i in range(count)]

    def piece(self, token: int) -> bytes:
        buffer = ctypes.create_string_buffer(64)
        count = self.library.llama_token_to_piece(self.vocab, token, buffer, 64, 0, False)
        if count < 0:
            buffer = ctypes.create_string_buffer(-count)
            count = self.library.llama_token_to_piece(self.vocab, token, buffer, -count, 0, False)
        return buffer.raw[:max(0, count)]

    def pieces(self) -> list[bytes]:
        return [self.piece(token) for token in range(self.n_vocab)]

    def detokenize(self, tokens) -> bytes:
        array = (ctypes.c_int32 * len(tokens))(*tokens)
        size = 16 * len(tokens) + 64
        buffer = ctypes.create_string_buffer(size)
        count = self.library.llama_detokenize(
            self.vocab, array, len(tokens), buffer, size, False, False)
        if count < 0:
            buffer = ctypes.create_string_buffer(-count)
            count = self.library.llama_detokenize(
                self.vocab, array, len(tokens), buffer, -count, False, False)
        return buffer.raw[:max(0, count)]

    def _check_tokenizer(self) -> None:
        """The mask treats a token as its bytes; prove the tokenizer agrees.

        If `detokenize` is not concatenation of pieces, the byte stream the mask
        scores is not the byte stream the model produces, and every soundness
        argument in `masker` is void. That is an escalation, not a warning, so
        it refuses here.
        """
        probes = [
            "(def Bool (lit bool true))",
            "(def (fn Bool () Bool) (lam Bool (var 0)))",
            "(ref 0x3ff2104702aeeb53b4dfbc5a09c0441df19f12883e6cf66e21a3bd85420b4e2f)",
        ]
        for probe in probes:
            tokens = self.tokenize(probe)
            joined = b"".join(self.piece(token) for token in tokens)
            if joined != probe.encode("utf-8"):
                raise FfiUnavailable(
                    "this tokenizer does not detokenize by concatenating token "
                    "pieces, so a byte-level mask over token pieces would be "
                    "unsound at the token boundary.\n"
                    f"  probe : {probe!r}\n  joined: {joined!r}")

    # -- decoding --------------------------------------------------------

    def reset(self) -> None:
        """Start a fresh sequence. The context is recreated, not reused.

        The memory API moved between llama.cpp releases; recreating a context is
        two lines that cannot rot, and condition 4 pays it once per draw.
        """
        if self.context:
            self.library.llama_free(self.context)
            self.context = None
        self._bind_context()

    def decode(self, tokens) -> None:
        """Evaluate `tokens`, in `n_batch`-sized slices.

        `llama_decode` asserts `n_tokens_all <= cparams.n_batch` and **aborts the
        process** when it does not hold — it is a `GGML_ASSERT`, not a return
        code, so there is nothing to catch. A full-corpus prompt is ~11.9k tokens
        against a 2048-token batch, so prefill has to be chunked; tying the batch
        to `n_ctx` instead would put the compute and logits buffers back at
        multi-gigabyte size, which is what sizing them down was for.

        Chunking is safe on both of the things that could silently corrupt a
        generation, and both are read off the pinned build rather than assumed:

        * **Positions.** `llama_batch_get_one` leaves `pos` null, and
          `llama_batch_allocr::init` then assigns positions from
          `memory->seq_pos_max(s) + 1` — i.e. continuing from what is already in
          the KV cache. Sequential calls chain, which is the same property the
          prompt-then-one-token-at-a-time loop already relied on.
        * **Logits.** A null `logits` with `output_all` false marks only the
          final token of each batch for output, so the last chunk's last token is
          what `llama_get_logits_ith(ctx, -1)` reads. Earlier chunks compute one
          unused row each, which is the whole cost of chunking.
        """
        if not tokens:
            return
        size = max(1, self.n_batch)
        for start in range(0, len(tokens), size):
            chunk = tokens[start:start + size]
            array = (ctypes.c_int32 * len(chunk))(*chunk)
            batch = self.library.llama_batch_get_one(array, len(chunk))
            status = self.library.llama_decode(self.context, batch)
            if status != 0:
                raise FfiUnavailable(
                    f"llama_decode returned {status} on tokens "
                    f"{start}..{start + len(chunk)} of {len(tokens)}")
            self._position += len(chunk)

    def logits(self):
        """The last position's logits as a ctypes float array view."""
        pointer = self.library.llama_get_logits_ith(self.context, -1)
        if not pointer:
            raise FfiUnavailable("llama_get_logits_ith returned NULL")
        return ctypes.cast(
            pointer, ctypes.POINTER(ctypes.c_float * self.n_vocab)).contents

    def close(self) -> None:
        if getattr(self, "context", None):
            self.library.llama_free(self.context)
            self.context = None
        if getattr(self, "model", None):
            self.library.llama_model_free(self.model)
            self.model = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
