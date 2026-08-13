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
and hand it to llama.cpp unchanged — the harness never interprets it. There is
no per-token hook anywhere in this file, by rule: Phase A does not mask.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

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

    def __init__(self, outputs, grammar_outputs=None):
        if not outputs:
            raise ValueError("StubBackend needs at least one output")
        self.outputs = tuple(outputs)
        self.grammar_outputs = tuple(grammar_outputs) if grammar_outputs else self.outputs
        self.draws = 0
        self.prompts: list[str] = []

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
        return StubBackend(config.stub_outputs, config.stub_grammar_outputs)
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
        f'unknown backend {kind!r}; known backends: stub, llama-server, llama-cli')
