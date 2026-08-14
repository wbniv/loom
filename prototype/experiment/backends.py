"""The model seam: one callable, prompt (+ optional grammar) to tokens.

Everything the harness knows about a model is `Backend.generate`. Three
implementations ship:

``StubBackend``          deterministic canned outputs; no model, no network.
``LlamaServerBackend``   llama.cpp's `/completion` endpoint. Preferred for a
                         live run, because the response carries exact
                         `tokens_predicted` / `tokens_evaluated` counts and R2's
                         budget rule is only as honest as its token accounting.
``LlamaCliBackend``      `llama-cli --grammar-file`, for a run with no server.
                         Token counts are scraped from llama.cpp's timing lines
                         and the backend refuses rather than estimating if the
                         scrape fails.

`loom.gbnf` is llama.cpp-format, so both live backends take the grammar as text
and hand it to llama.cpp unchanged — the harness never interprets it. For
conditions 1-3 there is no per-token hook anywhere in this file, by rule: Phase
A does not mask.

Phase B adds a second, *optional* seam — `generate_masked` — and one backend
that implements it live:

``LlamaCppBackend``      the pinned `libllama.so` driven in process through
                         `llama_ffi`, so condition 4 can see logits. Phase A's
                         `generate` is unaffected and unreachable from it.

`StubBackend` implements `generate_masked` too, over a scripted vocabulary and
scripted logits, so condition 4 runs end to end with no model at all: the mask
stack does the real work, only the model is fake (R4).
"""

from __future__ import annotations

import json
import math
import random
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .masker import StaticVocabulary

GRAMMAR_PATH = Path(__file__).resolve().parent.parent / "loom.gbnf"

#: Raised when the configured backend cannot be reached or was never chosen.
#: The runner turns this into the one-command entry point's failure message.


class BackendUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Generation:
    """One draw. `completion_tokens` is what the budget rule spends."""

    text: str
    completion_tokens: int
    prompt_tokens: int
    latency_s: float
    stop_reason: str
    backend: str


def grammar_text() -> str:
    """`loom.gbnf` as text. Read per run so an edit never needs a restart."""
    return GRAMMAR_PATH.read_text(encoding="utf-8")


class StubBackend:
    """A deterministic model stand-in — the whole harness, minus the model.

    Two scripts rather than one, because the point of a grammar is that
    syntactically invalid draws become impossible: with a grammar the stub draws
    from `grammar_outputs` (all of which parse), without one it draws from
    `outputs`. That is exactly the behaviour condition 2 buys from llama.cpp, so
    a stub run exercises the same branches a live run does.

    Draws cycle through the script in order and depend on nothing but the draw
    counter, so a stub run is byte-reproducible.
    """

    name = "stub"

    def __init__(self, outputs, grammar_outputs=None, masked_outputs=None):
        if not outputs:
            raise ValueError("StubBackend needs at least one output")
        self.outputs = tuple(outputs)
        self.grammar_outputs = tuple(grammar_outputs) if grammar_outputs else self.outputs
        self.masked_outputs = tuple(masked_outputs) if masked_outputs else self.grammar_outputs
        self.draws = 0
        self.prompts: list[str] = []
        self.masked_draws = 0

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        script = self.grammar_outputs if grammar else self.outputs
        text = script[self.draws % len(script)]
        self.draws += 1
        self.prompts.append(prompt)
        # A stable, documented stand-in for a tokenizer: four characters per
        # token. Clipped at `max_tokens` so the budget rule is exercised, and
        # never zero so the runner's loop cannot stall.
        natural = max(1, len(text) // 4)
        used = min(natural, max_tokens)
        return Generation(
            text=text,
            completion_tokens=used,
            prompt_tokens=max(1, len(prompt) // 4),
            latency_s=0.0,
            stop_reason="length" if used < natural else "stop",
            backend=self.name,
        )

    # -- condition 4, with no model ------------------------------------

    def mask_vocabulary(self):
        """A scripted tokenizer over the corpus surfaces and this stub's script.

        Built from the corpus rather than only from the scripted targets so the
        mask has a realistic amount to prune: several thousand tokens, most of
        them illegal at any given position.
        """
        import corpus_registry

        surfaces = [entry.source_text().rstrip("\n") for entry in corpus_registry.MANIFEST]
        return scripted_vocabulary(tuple(surfaces) + tuple(self.masked_outputs))

    def generate_masked(self, prompt, *, masker, max_tokens=256, seed=0, temperature=0.0):
        """Decode token by token against a real mask and scripted logits.

        The script is adversarial on purpose. At every step the *decoys* score
        above the token the target surface actually wants, so the intended token
        can only win if the mask removed them. Three decoys, one per thing that
        has to work:

        ``DECOY_SYNTAX``    bytes no Loom surface ever contains — the syntax
                            layer's job, and it must never reach `allowed`.
        ``DECOY_INDEX``     `9)` offered right after `(var ` / `(tyvar `, which
                            is perfectly grammatical and out of scope — only the
                            de Bruijn pruner removes it.
        ``DECOY_HASH``      `dead` offered right after a hash atom's `0x`, which
                            is perfectly grammatical hex that extends no known
                            digest — only the reference-hash pruner removes it.

        So a passing end-to-end stub run is evidence about the mask, not about
        the script: switch a pruner off and the run visibly diverges into the
        failure that pruner exists to prevent.
        """
        target = self.masked_outputs[self.masked_draws % len(self.masked_outputs)]
        self.masked_draws += 1
        self.draws += 1
        self.prompts.append(prompt)
        vocabulary = masker.vocabulary
        masker.reset()
        started = time.monotonic()
        emitted = 0
        stop_reason = "length"
        while emitted < max_tokens:
            step = masker.step()
            if not step.allowed:
                stop_reason = "dead"
                break
            scores = self._scripted_scores(masker, target, step)
            choice = max(step.allowed, key=lambda token: (scores.get(token, 1.0), -token))
            emitted += 1
            if choice in vocabulary.eos_ids:
                stop_reason = "stop"
                break
            masker.accept_token(choice)
            if masker.dead:  # pragma: no cover - the mask forbids it
                stop_reason = "dead"
                break
        return Generation(
            text=masker.text,
            completion_tokens=max(1, emitted),
            prompt_tokens=max(1, len(prompt) // 4),
            latency_s=time.monotonic() - started,
            stop_reason=stop_reason,
            backend=self.name,
        )

    @staticmethod
    def _scripted_scores(masker, target, step):
        vocabulary = masker.vocabulary
        text = masker.emitted
        scores: dict[int, float] = {}
        remaining = b""
        target_bytes = target.encode("utf-8")
        if target_bytes.startswith(bytes(text)):
            remaining = target_bytes[len(text):]
        if not remaining and step.can_end:
            for token in vocabulary.eos_ids:
                scores[token] = 5.0
        best, best_len = None, 0
        for token in step.allowed:
            if token in vocabulary.eos_ids:
                continue
            piece = vocabulary.piece(token)
            if remaining.startswith(piece) and len(piece) > best_len:
                best, best_len = token, len(piece)
        if best is not None:
            scores[best] = 2.0
        for piece in _decoy_pieces(masker):
            token = vocabulary.lookup(piece)
            if token is not None:
                scores[token] = 3.0
        return scores


#: Bytes no canonical Loom surface contains — the syntax layer must remove it.
DECOY_SYNTAX = b"?!"
#: Out-of-scope indices, offered as whichever *suffix* of the pattern the
#: current token boundary happens to land on. A decoy of a fixed length would
#: only ever be offered when the boundary fell exactly right, which makes the
#: test a test of the tokenization rather than of the pruner.
INDEX_PATTERNS = (b"(var 9)", b"(tyvar 9)")
#: Hex that extends no digest the resolver holds (asserted in the tests).
HASH_PATTERN = b"0xdead"

#: The suffixes offered when a token boundary lands right at the atom — the
#: shapes the docstring above describes, and what the tests probe with.
DECOY_INDEX = b"9)"
DECOY_HASH = b"dead"


def _suffix_for(text: bytes, pattern: bytes):
    """The longest suffix of `pattern` whose run-up `text` already ends with."""
    for cut in range(1, len(pattern) + 1):
        if text.endswith(pattern[: len(pattern) - cut]):
            return pattern[len(pattern) - cut:]
    return None  # pragma: no cover - the empty run-up always matches


DECOYS = (
    DECOY_SYNTAX,
    *(pattern[index:] for pattern in INDEX_PATTERNS for index in range(len(pattern))),
    *(HASH_PATTERN[index:] for index in range(len(HASH_PATTERN))),
)


def _decoy_pieces(masker):
    """The decoys worth offering at this position, in mask-layer order."""
    text = bytes(masker.emitted)
    offered = [DECOY_SYNTAX]
    for pattern in INDEX_PATTERNS:
        suffix = _suffix_for(text, pattern)
        if suffix:
            offered.append(suffix)
    # Gated on being *inside a hash atom* so the decoy is never offered inside
    # an `f64` or `bytes` literal, where `dead` is legal hex and the
    # reference pruner correctly has no opinion.
    if masker.tstate.atom_kind in ("hash", "row-elem"):
        suffix = _suffix_for(text, HASH_PATTERN)
        if suffix:
            offered.append(suffix)
    return offered


def scripted_vocabulary(surfaces, max_piece=4, decoys=DECOYS):
    """A deterministic stand-in tokenizer built from the corpus surfaces.

    Every 1- to `max_piece`-byte substring of every surface becomes a token, so
    the pieces straddle grammar atoms exactly the way a BPE vocabulary does — a
    token can end mid-hash, mid-index, or across a `) (` boundary, which is the
    tokenizer-boundary case the mask has to get right. Printable ASCII is added
    as single bytes so the vocabulary also contains tokens the grammar will
    never allow, and one EOS.
    """
    pieces: set[bytes] = {bytes((byte,)) for byte in range(0x20, 0x7F)}
    for surface in surfaces:
        data = surface.encode("utf-8")
        for length in range(1, max_piece + 1):
            for start in range(len(data) - length + 1):
                pieces.add(data[start:start + length])
    pieces.update(decoys)
    ordered = sorted(pieces)
    ordered.append(b"<|eos|>")
    return StaticVocabulary(ordered, eos_ids=(len(ordered) - 1,))


class LlamaServerBackend:
    """llama.cpp's HTTP server. Exact token counts, grammar passed inline."""

    name = "llama-server"

    def __init__(self, url, *, timeout=600.0, extra=None):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.extra = dict(extra or {})

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        payload = {
            "prompt": prompt,
            "n_predict": int(max_tokens),
            "seed": int(seed),
            "temperature": float(temperature),
            "cache_prompt": False,
            **self.extra,
        }
        if grammar:
            payload["grammar"] = grammar
        request = urllib.request.Request(
            f"{self.url}/completion",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as error:
            raise BackendUnavailable(f"llama.cpp server at {self.url} did not answer: {error}") from error
        elapsed = time.monotonic() - started
        if "tokens_predicted" not in body:
            raise BackendUnavailable(
                f"llama.cpp server response carried no token counts: {sorted(body)}"
            )
        return Generation(
            text=body.get("content", ""),
            completion_tokens=int(body["tokens_predicted"]),
            prompt_tokens=int(body.get("tokens_evaluated", 0)),
            latency_s=elapsed,
            stop_reason=str(body.get("stop_type", "")),
            backend=self.name,
        )


_EVAL_TOKENS = re.compile(r"^\s*(llama_perf_context_print:\s*)?\s*eval time\s*=.*?/\s*(\d+)\s+(runs|tokens)", re.MULTILINE)
_PROMPT_TOKENS = re.compile(r"prompt eval time\s*=.*?/\s*(\d+)\s+tokens", re.MULTILINE)


class LlamaCliBackend:
    """`llama-cli` with `--grammar-file`, for a run without a server."""

    name = "llama-cli"

    def __init__(self, binary, model, *, timeout=900.0, extra_args=()):
        self.binary = binary
        self.model = model
        self.timeout = timeout
        self.extra_args = list(extra_args)

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        command = [
            self.binary,
            "-m", str(self.model),
            "-p", prompt,
            "-n", str(int(max_tokens)),
            "--seed", str(int(seed)),
            "--temp", str(float(temperature)),
            "--no-display-prompt",
            "-no-cnv",
            *self.extra_args,
        ]
        grammar_file = None
        try:
            if grammar:
                grammar_file = tempfile.NamedTemporaryFile(
                    "w", suffix=".gbnf", encoding="utf-8", delete=False)
                grammar_file.write(grammar)
                grammar_file.close()
                command += ["--grammar-file", grammar_file.name]
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    command, check=False, capture_output=True, text=True, timeout=self.timeout)
            except FileNotFoundError as error:
                raise BackendUnavailable(f"llama.cpp binary {self.binary!r} not found") from error
            except subprocess.TimeoutExpired as error:
                raise BackendUnavailable(f"llama.cpp CLI timed out after {self.timeout}s") from error
            elapsed = time.monotonic() - started
        finally:
            if grammar_file is not None:
                Path(grammar_file.name).unlink(missing_ok=True)
        if completed.returncode != 0:
            raise BackendUnavailable(
                f"llama.cpp CLI exited {completed.returncode}:\n{completed.stderr[-2000:]}")
        eval_match = _EVAL_TOKENS.search(completed.stderr)
        if eval_match is None:
            raise BackendUnavailable(
                "could not read a completion-token count from llama.cpp's timing output; "
                "the budget rule needs a real count, so this backend refuses to estimate.\n"
                f"stderr tail:\n{completed.stderr[-2000:]}")
        prompt_match = _PROMPT_TOKENS.search(completed.stderr)
        return Generation(
            text=completed.stdout,
            completion_tokens=int(eval_match.group(2)),
            prompt_tokens=int(prompt_match.group(1)) if prompt_match else 0,
            latency_s=elapsed,
            stop_reason="",
            backend=self.name,
        )


def select_token(allowed, logits, temperature, rng):
    """Sample one token id from `allowed` under `logits`.

    Sampling happens over the *allowed* subset, never over the vocabulary: that
    is the whole point of a mask, and it also means a 151k-wide softmax never
    runs. Temperature 0 is argmax with the lowest id breaking ties, so a masked
    draw at temperature 0 is bit-reproducible.
    """
    if not allowed:
        raise ValueError("select_token called with an empty mask")
    if temperature <= 0.0:
        best = allowed[0]
        best_score = logits[best]
        for token in allowed[1:]:
            score = logits[token]
            if score > best_score:
                best, best_score = token, score
        return best
    scaled = [logits[token] / temperature for token in allowed]
    ceiling = max(scaled)
    weights = [math.exp(value - ceiling) for value in scaled]
    total = sum(weights)
    point = rng.random() * total
    for token, weight in zip(allowed, weights):
        point -= weight
        if point <= 0:
            return token
    return allowed[-1]  # pragma: no cover - float drift only


class LlamaCppBackend:
    """R1's chosen transport: the pinned `libllama.so`, in process.

    Only `generate_masked` is implemented. `generate` refuses on purpose:
    conditions 1-3 are Phase A's and run on `llama-server`, and quietly letting
    them run here would put two transports inside one latency column, which is
    exactly the comparability boundary R1 asks the plan to state.
    """

    name = "llama-cpp"

    def __init__(self, model_path, *, lib_path="", n_ctx=4096, n_threads=0):
        self.model_path = model_path
        self.lib_path = lib_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self._model = None

    def _ensure(self):
        if self._model is None:
            from .llama_ffi import FfiUnavailable, LlamaModel

            try:
                self._model = LlamaModel(
                    self.model_path,
                    lib_path=self.lib_path or None,
                    n_ctx=self.n_ctx,
                    n_threads=self.n_threads,
                )
            except FfiUnavailable as error:
                raise BackendUnavailable(str(error)) from error
        return self._model

    @property
    def model(self):
        """The loaded `LlamaModel`, loading it on first use."""
        return self._ensure()

    def mask_vocabulary(self):
        model = self._ensure()
        return StaticVocabulary(model.pieces(), eos_ids={model.eos, model.eot})

    def generate(self, prompt, *, grammar=None, max_tokens=256, seed=0, temperature=0.0):
        raise BackendUnavailable(
            "the llama-cpp backend implements condition 4 only. Conditions 1-3 "
            "run on llama-server so their latency column stays one transport "
            "wide (R1's comparability boundary).")

    def generate_masked(self, prompt, *, masker, max_tokens=256, seed=0, temperature=0.0):
        model = self._ensure()
        model.reset()
        tokens = model.tokenize(prompt)
        if len(tokens) + max_tokens > model.n_ctx:
            raise BackendUnavailable(
                f"prompt is {len(tokens)} tokens and the draw wants {max_tokens} more, "
                f"but n_ctx is {model.n_ctx}; raise \"n_ctx\" in the run config")
        started = time.monotonic()
        model.decode(tokens)
        masker.reset()
        rng = random.Random(seed)
        emitted = 0
        stop_reason = "length"
        while emitted < max_tokens:
            step = masker.step()
            if not step.allowed:
                stop_reason = "dead"
                break
            choice = select_token(step.allowed, model.logits(), temperature, rng)
            emitted += 1
            if choice in masker.vocabulary.eos_ids:
                stop_reason = "stop"
                break
            masker.accept_token(choice)
            model.decode([choice])
        return Generation(
            text=masker.text,
            completion_tokens=max(1, emitted),
            prompt_tokens=len(tokens),
            latency_s=time.monotonic() - started,
            stop_reason=stop_reason,
            backend=self.name,
        )

    def close(self):
        if self._model is not None:
            self._model.close()
            self._model = None


#: The message the runner prints when condition 4 is asked of a backend that
#: cannot expose logits. Named backends, not an abstract complaint.
NO_MASK_BACKEND_MESSAGE = """\
Condition 'gbnf+typemask' needs a backend that exposes a tokenizer and per-token
logits, and backend {backend!r} exposes neither.

Set "backend" in the config file to one of:

  "llama-cpp"  and set "model_path" (a local GGUF), optionally "llama_lib",
               "n_ctx" and "n_threads". This drives the pinned llama.cpp build
               in process through ctypes — the same engine Phase A serves with.
  "stub"       the deterministic no-model path; the mask stack runs for real
               against a scripted vocabulary and scripted logits, which is what
               the B1 tests use.

llama-server exposes no per-token logit callback (R1), so conditions 1-3's
backend cannot run condition 4 — that is why the transport is separate.
"""

#: The message the one-command entry point prints when no model is configured.
#: It names the blocking TODO item rather than describing the problem abstractly.
NO_BACKEND_MESSAGE = """\
No model backend is configured, so Phase A cannot run.

Phase A's model and hardware selection is a T5 item — it needs the operator, not
an agent, and the plan requires the choice to be *recorded before running*:

    docs/plans/2026-08-13-masked-generation-experiment.md, Work / Phase A:
    "Model/hardware selection recorded before running (T5 — needs the operator:
     local GGUF under llama.cpp is the natural path since `loom.gbnf` is
     llama.cpp-format)."

Set `backend` in the config file to one of:

  "llama-server"  and set "server_url" (llama.cpp `llama-server`); token counts
                  come back exact, which is what R2's budget rule wants.
  "llama-cli"     and set "binary" and "model_path" (a local GGUF).
  "llama-cpp"     and set "model_path"; Phase B's in-process transport, which
                  runs condition 4 ('gbnf+typemask') and nothing else.
  "stub"          the deterministic no-model backend; exercises the harness,
                  produces no evidence about a model.

Config file read: {path}
"""


def make_backend(config):
    """Build the configured backend, or refuse with `NO_BACKEND_MESSAGE`."""
    kind = config.backend
    if not kind or kind == "none":
        raise BackendUnavailable(NO_BACKEND_MESSAGE.format(path=config.source_path or "<inline>"))
    if kind == "stub":
        if not config.stub_outputs:
            raise BackendUnavailable('backend "stub" needs "stub_outputs" in the config')
        return StubBackend(
            config.stub_outputs,
            config.stub_grammar_outputs,
            getattr(config, "stub_masked_outputs", None),
        )
    if kind == "llama-cpp":
        if not config.model_path:
            raise BackendUnavailable('backend "llama-cpp" needs "model_path" in the config')
        return LlamaCppBackend(
            config.model_path,
            lib_path=getattr(config, "llama_lib", ""),
            n_ctx=getattr(config, "n_ctx", 4096),
            n_threads=getattr(config, "n_threads", 0),
        )
    if kind == "llama-server":
        if not config.server_url:
            raise BackendUnavailable('backend "llama-server" needs "server_url" in the config')
        return LlamaServerBackend(config.server_url, timeout=config.timeout, extra=config.backend_extra)
    if kind == "llama-cli":
        if not config.model_path:
            raise BackendUnavailable('backend "llama-cli" needs "model_path" in the config')
        return LlamaCliBackend(
            config.binary or "llama-cli",
            config.model_path,
            timeout=config.timeout,
            extra_args=config.extra_args,
        )
    raise BackendUnavailable(
        f'unknown backend {kind!r}; known backends: stub, llama-server, llama-cli, llama-cpp')
