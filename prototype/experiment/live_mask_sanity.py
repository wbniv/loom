"""A live sanity for Phase B's transport: real tokenizer, real logits, real mask.

Deliberately *not* part of `task prototype:test`. It loads a GGUF through
`llama_ffi`, and a test suite that dlopens a shared library and mmaps a
gigabyte of weights is a test suite that fails for reasons unrelated to the
code under test. Run it by hand::

    python3 -m experiment.live_mask_sanity --model ~/loom-tools/models/....gguf

Three checks, in increasing cost:

1. **Tokenizer boundary** — `LlamaModel` refuses to construct unless
   detokenization is concatenation of token pieces. That is the assumption the
   whole byte-level mask rests on; if it fails here, the mask is unsound on this
   model and Phase B needs re-shaping, not patching.
2. **Soundness against the model's own tokenizer** — every corpus fixture is
   tokenized by the model and walked through the mask. This is the same R4
   property `test_masker.py` proves against scripted tokenizations, now against
   the tokenization that will actually occur.
3. **One masked generation** at temperature 0, which is the end-to-end proof
   that logits, mask and decode loop compose.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import corpus_registry

from .backends import BackendUnavailable, LlamaCppBackend
from .masker import build_masker
from .resolver import ExperimentResolver

DEFAULT_MODEL = Path.home() / "loom-tools/models/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m experiment.live_mask_sanity",
        description="Load the pinned llama.cpp in process and sanity-check the mask.")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="path to a GGUF")
    parser.add_argument("--lib", default="", help="path to libllama.so (default: the pinned build)")
    parser.add_argument("--n-ctx", type=int, default=2048)
    parser.add_argument("--n-threads", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=16)
    parser.add_argument("--fixtures", type=int, default=6,
                        help="how many corpus fixtures to walk (0 = all)")
    arguments = parser.parse_args(argv)

    backend = LlamaCppBackend(
        arguments.model, lib_path=arguments.lib,
        n_ctx=arguments.n_ctx, n_threads=arguments.n_threads)
    resolver = ExperimentResolver()

    started = time.monotonic()
    try:
        vocabulary = backend.mask_vocabulary()
    except BackendUnavailable as error:
        print("NOT RUN — the transport could not start:", file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 2
    model = backend.model
    print(f"model            : {arguments.model}")
    print(f"vocabulary       : {len(vocabulary)} tokens, "
          f"{vocabulary.trie_nodes} trie nodes, "
          f"loaded in {time.monotonic() - started:.1f} s")
    print("tokenizer        : detokenize == concat(pieces)  [checked at load]")

    masker = build_masker(vocabulary, resolver)

    fixtures = list(corpus_registry.MANIFEST)
    if arguments.fixtures:
        fixtures = fixtures[: arguments.fixtures]
    started = time.monotonic()
    failures = 0
    steps = 0
    for entry in fixtures:
        surface = entry.source_text().rstrip("\n")
        tokens = model.tokenize(surface)
        joined = b"".join(model.piece(token) for token in tokens)
        if joined != surface.encode("utf-8"):  # pragma: no cover - guarded at load
            print(f"  !! {entry.name_path}: tokenization is not concatenative")
            failures += 1
            continue
        masker.reset()
        for index, token in enumerate(tokens):
            step = masker.step()
            steps += 1
            if token not in step.allowed:
                failures += 1
                print(f"  !! {entry.name_path}: mask excluded token {index} "
                      f"{model.piece(token)!r} after {masker.text[-60:]!r}; "
                      f"pruned {step.pruned}")
                break
            masker.accept_token(token)
        else:
            if not masker.can_end:
                failures += 1
                print(f"  !! {entry.name_path}: walk did not reach a complete state")
    elapsed = time.monotonic() - started
    print(f"soundness        : {len(fixtures) - failures}/{len(fixtures)} fixtures, "
          f"{steps} mask steps, {failures} violations, {elapsed:.1f} s")

    masker.reset_stats()
    prompt = (
        "Write one canonical Loom definition. Answer with the definition only.\n"
        "Example: " + resolver.surface(resolver.digest_for("corpus/bool/not")) + "\n"
        "Now write a definition of type Bool:\n")
    started = time.monotonic()
    generation = backend.generate_masked(
        prompt, masker=masker, max_tokens=arguments.max_tokens, seed=1, temperature=0.0)
    print(f"masked draw      : {generation.completion_tokens} tokens in "
          f"{time.monotonic() - started:.1f} s, stop={generation.stop_reason}")
    print(f"  text           : {generation.text!r}")
    print("  stats          : " + json.dumps(masker.stats(), sort_keys=True))
    backend.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
