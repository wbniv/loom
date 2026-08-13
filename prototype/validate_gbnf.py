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
    "(def (fn Bool () Bool) (lam Bool (if (var 0) (lit bool false) (lit bool true))))",
    "(def I64 (if (if (lit bool true) (lit bool false) (var 0)) (lit i64 1) (lit i64 0)))",
    # Two bootstrap-corpus tranche-2 fixtures (docs/plans/2026-08-13-corpus-
    # tranche-2.md): `fix`+`ref`+`match`+`con` together (list/append), and a
    # `fix` whose body itself `ref`s another corpus definition (list/flatMap) —
    # the surface `validate_gbnf.py.EXTRA_VALID` had not yet exercised a `ref`
    # nested inside a `fix` body rather than only as a measure. The corpus
    # directory itself is not globbed here (unlike `examples/`), so these are
    # copied in rather than read from disk.
    "(def (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) () (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) () (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)))) (fix (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) () (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) () (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)))) 0 (ref 0x4bd80df0fc10754098795f5fe2bd676a20f933192622f10455b7f55dff5ad5ae) (lam (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) (lam (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) (match (var 1) ((0 0 (var 0)) (1 2 (con 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba 1 ((var 1) (app (app (var 4) (var 0)) (var 2)))))))))))",
    "(def (fn (fn I64 () (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64))) () (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) () (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)))) (fix (fn (fn I64 () (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64))) () (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) () (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)))) 1 (ref 0x4bd80df0fc10754098795f5fe2bd676a20f933192622f10455b7f55dff5ad5ae) (lam (fn I64 () (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64))) (lam (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba (I64)) (match (var 0) ((0 0 (con 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba 0 ())) (1 2 (app (app (ref 0x32f5d833f0b7c42ea8252e7ec8810657e9e9d132d395d30a7259e683bc31f791) (app (var 3) (var 1))) (app (app (var 4) (var 3)) (var 0))))))))))",
    # Two bootstrap-corpus tranche-3 fixtures (docs/plans/2026-08-13-corpus-
    # tranche-3.md): a two-ability *closed* effect row with `cap` domains on
    # both arrows (sample/nowAndBytes) — the grammar's row production had only
    # ever been exercised at zero or one hash — and a `handle` whose operation
    # clause is a nested `match` over the continuation's result rather than a
    # bare `var` (rand/resample). Same reason as above: `corpus/` is not
    # globbed here, so these are copied in.
    "(def (fn (cap 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d) () (fn (cap 0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475) (0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d) (data 0x98c7ee8d97ddf2707f45d89ac56c68cd24d0d7c7d6b093241b1ab84c88de4d2a (I64 Bytes)))) (lam (cap 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d) (lam (cap 0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475) (con 0x98c7ee8d97ddf2707f45d89ac56c68cd24d0d7c7d6b093241b1ab84c88de4d2a 0 ((perform 0xe6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d 0 ()) (perform 0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475 0 ((lit i64 8))))))))",
    "(def (fn (cap 0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475) () (data 0x98c7ee8d97ddf2707f45d89ac56c68cd24d0d7c7d6b093241b1ab84c88de4d2a (Bytes Bytes))) (lam (cap 0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475) (handle 0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475 (perform 0x0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475 0 ((lit i64 2))) ((0 (match (app (var 0) (lit bytes 0x00)) ((0 2 (match (app (var 2) (lit bytes 0xff)) ((0 2 (con 0x98c7ee8d97ddf2707f45d89ac56c68cd24d0d7c7d6b093241b1ab84c88de4d2a 0 ((var 3) (var 0)))))))))) (1 (app (var 0) (lit i64 0)))) (con 0x98c7ee8d97ddf2707f45d89ac56c68cd24d0d7c7d6b093241b1ab84c88de4d2a 0 ((var 0) (var 0))))))",
    # Two bootstrap-corpus tranche-4 fixtures (docs/plans/2026-08-13-corpus-
    # tranche-4.md). `examples/03_refinement.loom.sexpr` already exercises
    # `refine` at the top of a definition type, but never as *both* halves of an
    # arrow (nat/widenPos) and never nested inside a `(data …)` type argument
    # (list/consNat) — the position where §3.2.1's refinement erasure has to
    # recurse. Same reason as above: `corpus/` is not globbed here.
    "(def (fn (refine I64 (app (app (ref 0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) (lit i64 0)) (var 0))) () (refine I64 (app (app (ref 0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) (lit i64 -1)) (var 0)))) (lam (refine I64 (app (app (ref 0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) (lit i64 0)) (var 0))) (var 0)))",
    "(def (fn (refine I64 (app (app (ref 0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) (lit i64 -1)) (var 0))) () (fn (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba ((refine I64 (app (app (ref 0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) (lit i64 -1)) (var 0))))) () (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba ((refine I64 (app (app (ref 0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) (lit i64 -1)) (var 0))))))) (lam (refine I64 (app (app (ref 0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) (lit i64 -1)) (var 0))) (lam (data 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba ((refine I64 (app (app (ref 0x0e2c1cacb65ffacb2219b4954360798ecebf7b4c43e6e5107f171acf3d562965) (lit i64 -1)) (var 0))))) (con 0x2ee931a3746132882cdbc63385ccaf7320a54372589b260deaa1c851a59e8dba 1 ((var 1) (var 0))))))",
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
    "(def I64 (if (lit bool true) (lit i64 1)))",
    "(def I64 (if (lit bool true) (lit i64 1) (lit i64 0) (lit i64 2)))",
    "(def I64 (if (lit bool true) then (lit i64 1) else (lit i64 0)))",
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
