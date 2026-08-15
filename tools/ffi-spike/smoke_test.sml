(* Hand-written (not generated): exercises the generated LlamaFFI structure
   against the REAL pinned libllama.so, two ways --
     1. `Raw.llama_backend_init`/`llama_backend_free` are `_import`-declared
        entry points: calling them proves the generated `_import` syntax
        links and runs against the real shared library, not just that it
        typechecks.
     2. The `LlamaModelParams` accessors are exercised as a round-trip over
        a real malloc'd buffer: poke `n_gpu_layers` at its generated offset,
        peek it back, and check it matches. This does not touch llama.cpp's
        own struct-initialisation code (that would need `llama_model_default_params`,
        which is one of the struct-by-value entry points this spike does not
        `_import` -- see the generated file's header comment) but it does
        prove the generated offset arithmetic and MLton.Pointer accessor
        calls are internally consistent, end to end, under a real compile.

   Not a substitute for driving an actual model: that is what
   `prototype/experiment/llama_ffi.py` already does, and is out of scope for
   a one-day layout-generation spike. *)

val libc_malloc = _import "malloc" : Word64.word -> MLton.Pointer.t;
val libc_free = _import "free" : MLton.Pointer.t -> unit;

fun fail msg = (print ("smoke test: FAIL -- " ^ msg ^ "\n"); OS.Process.exit OS.Process.failure)

val () =
  let
    open LlamaFFI
  in
    Raw.llama_backend_init ();
    let
      val scratch = libc_malloc (Word64.fromInt (Word.toInt LlamaModelParams.size))
    in
      if scratch = MLton.Pointer.null then
        fail "malloc returned NULL"
      else
        let
          val () = LlamaModelParams.setNGpuLayers (scratch, ~1)
          val got = LlamaModelParams.getNGpuLayers scratch
        in
          libc_free scratch;
          if got = ~1 then
            print "smoke test: OK -- llama_backend_init/free ran against the real \
                  \libllama.so, and the generated n_gpu_layers accessor round-tripped \
                  \through a real buffer at the measured offset.\n"
          else
            fail "n_gpu_layers round-trip mismatch"
        end
    end;
    Raw.llama_backend_free ()
  end
