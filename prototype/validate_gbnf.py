"""Validate loom.gbnf with llama.cpp's model-free GBNF validator."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRAMMAR = HERE / "loom.gbnf"
VALID_MARKER = "Input string is valid according to the grammar."
INVALID_MARKER = "Input string is invalid according to the grammar."
HASH = "0x" + "11" * 32

EXTRA_VALID = [
    "(def Bytes (lit bytes 0x))",
    "(def Bytes (lit bytes 0x00ff))",
    "(def F64 (lit f64 0x7ff8000000000000))",
    '(def Text (lit text "a;b \\\"quoted\\\" café"))',
    f"(def (forall (fn (tyvar 0) ({HASH} (tyvar 1)) (tyvar 0))) (hole (forall (fn (tyvar 0) ({HASH} (tyvar 1)) (tyvar 0))) ()))",
    f"(def I64 (handle {HASH} (perform {HASH} 0 ()) ((0 (var 0))) (var 0)))",
    "(def I64 (fix (fn I64 () I64) 0 (lam I64 (var 0)) (lam I64 (var 0))))",
    "(def I64 (fix (fn Bool () (fn I64 () I64)) 1 (lam I64 (var 0)) (lam Bool (lam I64 (var 0)))))",
]

INVALID = [
    " (def Unit (lit unit))",
    "(def  Unit (lit unit))",
    "(def Unit (lit unit)) ; comment",
    "(def (base I64) (lit i64 1))",
    "(def I64 (lit i64 01))",
    "(def I64 (var -1))",
    "(def Bool (lit bool truthy))",
    "(def F64 (lit f64 0x7ff800000000000))",
    "(def Bytes (lit bytes 0x0))",
    f"(def I64 (ref {'0x' + 'AA' * 32}))",
    "(def Unit\n(lit unit))",
    # The pre-position `fix` surface: the measure now needs its selector first.
    "(def I64 (fix (fn I64 () I64) (lam I64 (var 0)) (lam I64 (var 0))))",
    "(def I64 (fix (fn I64 () I64) -1 (lam I64 (var 0)) (lam I64 (var 0))))",
]


def resolve_validator(argument: str | None) -> str:
    candidates = [argument] if argument else ["test-gbnf-validator", "llama-gbnf-validator"]
    for candidate in candidates:
        if candidate and (resolved := shutil.which(candidate)) is not None:
            return resolved
    raise SystemExit(
        "GBNF validator not found. Pass its path as the first argument or set "
        "LOOM_GBNF_VALIDATOR for `task grammar:test`."
    )


def accepts(validator: str, source: str) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as source_file:
        source_file.write(source)
        source_file.flush()
        result = subprocess.run(
            [validator, str(GRAMMAR), source_file.name],
            check=False,
            capture_output=True,
            text=True,
        )
    output = result.stdout + result.stderr
    if VALID_MARKER in output:
        return True, output
    if INVALID_MARKER in output:
        return False, output
    raise RuntimeError(f"validator could not load or evaluate the grammar:\n{output}")


def main() -> int:
    validator = resolve_validator(sys.argv[1] if len(sys.argv) > 1 else None)
    valid_cases = [path.read_text(encoding="utf-8") for path in sorted((HERE / "examples").glob("*.loom.sexpr"))]
    valid_cases.extend(EXTRA_VALID)

    for number, source in enumerate(valid_cases, 1):
        accepted, output = accepts(validator, source)
        if not accepted:
            print(f"expected valid case {number} to be accepted:\n{source}\n{output}", file=sys.stderr)
            return 1
    for number, source in enumerate(INVALID, 1):
        accepted, output = accepts(validator, source)
        if accepted:
            print(f"expected invalid case {number} to be rejected:\n{source}\n{output}", file=sys.stderr)
            return 1

    print(f"GBNF PASS: {len(valid_cases)} valid cases accepted; {len(INVALID)} invalid cases rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
