"""Wrapping the contract entry points so a case is *observed*, never restated.

This is the harvesting seam. The alternative — copying every rejection case out
of the ~20 test modules into a second table — was rejected because the copy
drifts silently the moment a test changes, and because the prototype's tests
express rejection in at least five different shapes (a table of `(source,
message)` pairs, an inline `assertRaises`, a helper method, a `subTest` loop, a
constructed IR literal). A seam under all five is the layer boundary itself, not
the tests.

So: every entry point named in `spec.py` is replaced by a wrapper that calls the
original, returns or re-raises exactly what the original returned or raised, and
on the way past records what happened. Installing the harness therefore cannot
change a verdict — the wrapper's only effect on the wrapped call is that it
happens inside a `try`.

Two rules keep the capture bounded and honest:

*Outermost only.* A recursive entry point (`check_declaration_type` walks a type
tree; `check_type` walks a type) would otherwise record one case per node. The
wrapper records only the outermost invocation of each entry point, which is the
call a differential consumer actually drives.

*Inputs before, traces after.* Argument values are encoded before the call,
because a layer may legitimately mutate one (`typecheck.validate_source`'s
`obligations` collector is filled in place). Resolver traces can only be encoded
after, because they are what the call did.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import sys
import unittest
from pathlib import Path

from . import jsonio
from .recorder import Case, Recorder
from .spec import ENTRY_POINTS, METHOD_ENTRY_POINTS, EntryPoint

PROTOTYPE_DIR = Path(__file__).resolve().parent.parent

#: Trace marker. A traced parameter's encoded input is the table of calls its
#: resolver received, not the closure — that is what a consumer can replay.
TRACE_TAG = "$trace"

_installed: list[tuple[object, str, object]] = []
_active: set[str] = set()


# ── provenance ──────────────────────────────────────────────────────────────
def current_provenance() -> tuple[str, str, str] | None:
    """The test currently on the stack, if any.

    Found by walking frames for a `unittest.TestCase` bound as `self`, which
    works for every shape the prototype's tests use — helper assertion methods,
    inline `assertRaises`, `subTest` loops — without any test needing to know
    the harness exists.
    """
    frame = inspect.currentframe()
    try:
        while frame is not None:
            candidate = frame.f_locals.get("self")
            if isinstance(candidate, unittest.TestCase):
                identifier = candidate.id()
                module, _, rest = identifier.partition(".")
                return ("test", module, rest or identifier)
            frame = frame.f_back
    finally:
        del frame
    return None


# ── derivation of the per-layer gate outputs ────────────────────────────────
def _derive(entry: EntryPoint, result):
    """Return `(canonical_bytes_hex, identity_hash, extra)` for an accepted call.

    The gate table in `docs/plans/2026-08-14-production-language-decision.md`
    names what each layer's gate compares; this is that, and nothing more.
    """
    import transcode

    extra: dict = {}
    name = entry.name

    if name == "transcode.parse_source":
        encoded = transcode.cbor_canonical.encode(result)
        extra["rendered_surface"] = transcode.def_to_surface(result)
        extra["ir"] = jsonio.encode(result)
        return encoded.hex(), hashlib.sha256(encoded).hexdigest(), extra
    if name == "transcode.transcode_source":
        ir, encoded, digest = result
        extra["rendered_surface"] = transcode.def_to_surface(ir)
        extra["ir"] = jsonio.encode(ir)
        return encoded.hex(), digest, extra
    if name in ("transcode.def_object_bytes", "declarations.declaration_bytes", "policies.policy_bytes"):
        return result.hex(), hashlib.sha256(result).hexdigest(), extra
    if name == "transcode.identity":
        return None, result, extra
    if name in ("declarations.declaration_hash", "policies.policy_hash", "declarations.DeclarationRegistry.add"):
        return None, result.hex(), extra
    if name in ("refinements.obligation_script", "refinements.subtype_script"):
        extra["smt_script"] = result
        return result.encode("utf-8").hex(), hashlib.sha256(result.encode("utf-8")).hexdigest(), extra

    if entry.result is not None:
        extra[entry.result] = jsonio.encode(result)
    return None, None, extra


# ── environments and resolver traces ────────────────────────────────────────
def _environment_id(recorder: Recorder, registry) -> str | None:
    """Lift a `DeclarationRegistry` out of the input into a shared document."""
    if registry is None:
        return None
    objects = getattr(registry, "_objects", None)
    if objects is None:
        return recorder.environment("opaque", {"type": type(registry).__name__})
    payload = [[digest, obj] for digest, obj in objects.items()]
    payload.sort(key=lambda pair: pair[0])
    return recorder.environment("declaration_registry", payload)


class _TracedResolver:
    """A transparent proxy that remembers every call it was asked to answer."""

    __slots__ = ("_inner", "calls")

    def __init__(self, inner):
        self._inner = inner
        self.calls: list = []

    def __call__(self, *args, **kwargs):
        try:
            result = self._inner(*args, **kwargs)
        except BaseException as error:
            self.calls.append((args, kwargs, ("raises", type(error).__name__)))
            raise
        self.calls.append((args, kwargs, ("returns", result)))
        return result

    def encoded(self) -> dict:
        rows = []
        for args, kwargs, (kind, payload) in self.calls:
            rows.append(
                {
                    "args": jsonio.encode(list(args)),
                    "kwargs": jsonio.encode(kwargs),
                    kind: jsonio.encode(payload) if kind == "returns" else payload,
                }
            )
        unique = {jsonio.canonical(row): row for row in rows}
        return {TRACE_TAG: [row for _, row in sorted(unique.items())]}


def _wrap(recorder: Recorder, entry: EntryPoint, original):
    signature = inspect.signature(original)

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        if not recorder.enabled or entry.name in _active:
            return original(*args, **kwargs)

        try:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
        except TypeError:
            # A malformed call is the caller's problem, not a differential case.
            return original(*args, **kwargs)

        arguments = dict(bound.arguments)
        arguments.pop("self", None)
        environment = None
        if entry.env is not None:
            environment = _environment_id(recorder, arguments.pop(entry.env, None))

        traced: dict[str, _TracedResolver] = {}
        for parameter in entry.trace:
            value = arguments.get(parameter)
            if callable(value):
                proxy = _TracedResolver(value)
                traced[parameter] = proxy
                bound.arguments[parameter] = proxy

        encoded_input = {
            key: jsonio.encode(value)
            for key, value in arguments.items()
            if key not in entry.drop and key not in traced
        }

        outer = recorder.provenance
        # A test on the stack wins; otherwise inherit whatever the caller
        # declared (the fixture pass sets it directly); otherwise this is a
        # module-import-time call, such as `prelude`'s hash table.
        recorder.provenance = current_provenance() or outer or ("harness", "<module-import>", "")
        _active.add(entry.name)
        try:
            try:
                result = original(*bound.args, **bound.kwargs)
            except BaseException as error:
                _capture(recorder, entry, encoded_input, traced, environment, error=error)
                raise
            _capture(recorder, entry, encoded_input, traced, environment, result=result)
            return result
        finally:
            _active.discard(entry.name)
            recorder.provenance = outer

    wrapper.__wrapped_entry_point__ = entry.name  # type: ignore[attr-defined]
    return wrapper


_SENTINEL = object()


def _capture(recorder, entry, encoded_input, traced, environment, *, result=_SENTINEL, error=None):
    """Build and merge one case. Never raises into the wrapped caller."""
    encoded_input = dict(encoded_input)
    for parameter, proxy in traced.items():
        encoded_input[parameter] = proxy.encoded()

    if error is not None:
        case = Case(
            layer=entry.layer,
            entry_point=entry.name,
            encoded_input=encoded_input,
            environment=environment,
            verdict="reject",
            error_class=type(error).__name__,
            canonical_bytes_hex=None,
            identity_hash=None,
        )
    else:
        try:
            canonical_bytes, identity, extra = _derive(entry, result)
        except Exception as derivation_error:  # pragma: no cover - harness bug guard
            canonical_bytes, identity = None, None
            extra = {"derivation_error": type(derivation_error).__name__}
        case = Case(
            layer=entry.layer,
            entry_point=entry.name,
            encoded_input=encoded_input,
            environment=environment,
            verdict="accept",
            error_class=None,
            canonical_bytes_hex=canonical_bytes,
            identity_hash=identity,
            extra=extra,
        )
    recorder.merge(case)


# ── installation ────────────────────────────────────────────────────────────
def _rebind(original, wrapper) -> None:
    """Repoint every `from x import y` alias in the prototype at the wrapper.

    The layer modules import each other's entry points by name, so patching the
    defining module alone would leave `typecheck`'s own `check_definition`
    pointing at the unwrapped `scope.check_definition` and the nested case would
    be lost.
    """
    for module in list(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename or Path(filename).resolve().parent != PROTOTYPE_DIR:
            continue
        for name, value in list(vars(module).items()):
            if value is original:
                setattr(module, name, wrapper)


def is_installed() -> bool:
    """True when this process already has the entry points wrapped."""
    return bool(_installed)


def install(recorder: Recorder) -> None:
    """Wrap every captured entry point. Idempotent within a process.

    A second `install` is a no-op rather than an error, but the second caller's
    recorder receives nothing — check `is_installed` first if that matters, and
    do not `uninstall` instrumentation another caller owns.
    """
    if _installed:
        return
    import importlib

    for entry in ENTRY_POINTS:
        module = importlib.import_module(entry.module)
        original = getattr(module, entry.attribute)
        wrapper = _wrap(recorder, entry, original)
        _installed.append((module, entry.attribute, original))
        setattr(module, entry.attribute, wrapper)
        _rebind(original, wrapper)

    for entry, class_name in METHOD_ENTRY_POINTS:
        module = importlib.import_module(entry.module)
        owner = getattr(module, class_name)
        method = entry.attribute.split(".", 1)[1]
        original = getattr(owner, method)
        wrapper = _wrap(recorder, entry, original)
        _installed.append((owner, method, original))
        setattr(owner, method, wrapper)


def uninstall() -> None:
    """Restore the originals. Used by the tests, not by the export."""
    while _installed:
        owner, attribute, original = _installed.pop()
        setattr(owner, attribute, original)
    _active.clear()
