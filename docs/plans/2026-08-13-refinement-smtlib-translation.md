# Plan — Refinement-to-SMT-LIB translation rules

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Nominal match validation](2026-08-13-nominal-match-validation.md)

## Objective

Close the §3.2 gap. `SPEC.md` §3.2 names the target fragment — quantifier-free
linear integer/real arithmetic plus datatypes and uninterpreted functions,
"roughly `QF_UFLIRA` + datatypes" — but says nothing about how a Loom refinement
term becomes an SMT-LIB term. Without those rules an `A3 proof` obligation
(§6.1) can only be *asserted*: there is no defined artifact a solver could take
as input, so the highest rung of the assurance lattice is unreachable by
construction and every refinement obligation silently falls back to A1 or A0.

Write the rules normatively, make them deterministic in the same sense §4.2
makes encodings deterministic — one canonical SMT-LIB script per verification
condition — and land a prototype translator that emits that script and refuses,
loudly and with a path, everything outside the fragment.

No visible surface (normative spec text plus a library module), so this plan
carries no mockups.

## Rules

- **The translation unit is a verification condition `(Γ, H, g)`** — a de Bruijn
  context of Loom types, Bool-typed hypotheses, and a Bool-typed goal. v0.1
  specifies exactly one producer: refinement subtyping (§3.3), where
  `{x:T|φ} <: {x:T|ψ}` is `Γ = [T]`, `H = [φ]`, `g = ψ`. Verification-condition
  generation for function bodies is explicitly deferred rather than invented
  here; inventing it would be a design decision this plan has no mandate for.
- **The refined value is `loom.x0`.** `Γ[i]` is `loom.xi`, matching §2.3.1's
  "refined value added as term index 0". Binders introduced *inside* a predicate
  (`let`, `match` arms) get fresh `loom.b<k>` symbols in translation order.
- **Refinements erase in sort position.** `refine T φ` has the sort of `T`,
  recursively, including inside data type arguments. An erased refinement is
  *not* silently assumed as a hypothesis — only `H` is asserted.
- **Base sorts.** `Bool → Bool`, `I64 → Int`, `Unit → Loom.Unit` (a one-nullary-
  constructor datatype), and `F64`, `Text`, `Bytes` → **uninterpreted sorts**.
  Opaque literals become constants named by the SHA-256 of their canonical
  payload, with one `distinct` assertion per sort holding two or more of them.
- **Applied data types are monomorphized**, keyed by `Loom.D` + SHA-256 of the
  canonical CBOR (§4.2) of the refinement-erased applied type. `self` resolves to
  the same applied type, so recursion closes; all reachable sorts go in one
  `declare-datatypes` group sorted bytewise, which handles mutual recursion. No
  parametric `declare-datatypes` is ever emitted.
- **Translatable terms** are `var`, `lit`, `ref`, saturated `app`, `let`, `con`
  (monomorphic declarations only), and `match` (exhaustive, duplicate-free,
  emitted in constructor-index order so arm order cannot change the bytes).
  `lam`, `perform`, `handle`, `fix`, `hole`, partial/higher-order application,
  and polymorphic `con` are rejected with the offending subterm's path.
- **References are uninterpreted by default and never guessed.** A `ref`'s type
  must be resolvable — the translator refuses rather than assume an arity, the
  same discipline §2.3.1 already imposes on handler clauses. Every arrow on the
  uncurried spine must carry the empty effect row. The default encoding is
  `declare-fun`, so v0.1 never unfolds a definition body into a proof.
- **Interpretation is a closed allowlist supplied by the toolchain**, mapping
  definition hashes to `not and or => = distinct ite + - * div mod abs < <= > >=`
  and nothing else. It is toolchain policy, never part of a term, so identity is
  untouched. Each application is checked against the SMT symbol's own signature
  as well as the reference's Loom type, `*` admits at most one non-numeral
  factor, and `div`/`mod` require a nonzero integer literal divisor — linearity
  is enforced at the call site, not hoped for.
- **Fixed script order**, one command per line, single trailing newline:
  `set-logic ALL`; opaque `declare-sort`s; the `declare-datatypes` group;
  context `declare-const`s then literal `declare-const`s; `declare-fun`s;
  `distinct` axioms; I64 domain axioms; hypotheses; `(assert (not g))`;
  `(check-sat)`; `(exit)`. `unsat` earns `A3 proof`; `sat` refutes; `unknown`,
  a timeout, or an out-of-fragment term leaves the obligation for weaker
  evidence.
- **The obligation name is not in the script**, so two differently named
  obligations with the same verification condition share one memo-ledger row
  (§6.4).

### Design forks taken conservatively

Three points the spec could not settle. Each took the conservative branch; the
alternative is recorded here rather than lost.

1. **`F64` is an uninterpreted sort, not `Real`.** `Real` is unsound for NaN,
   infinities, and rounding, and would let a solver "prove" float obligations
   that fail at runtime. `QF_FP` would be faithful but leaves the fragment §3.2
   names. Consequence: §12's `isMiddleOf` refinement translates structurally
   (uninterpreted predicate over opaque values) but proves nothing — exactly why
   that example carries A1 `property` evidence, not A3.
2. **`I64` is `Int` with a domain axiom, not a 64-bit bitvector.** §3.2 names
   LIA, so `Int` it is; the axiom bounds each `Int`-sorted *context* variable to
   the signed 64-bit range. It cannot bound an uninterpreted function's result
   or a datatype field. A proof depending on wraparound is therefore unsound,
   and an unbounded intermediate can produce a spurious `sat` — which fails
   safe, leaving the obligation undischarged. The bit-precise alternative is
   `QF_UFBVDT`, a fragment change requiring a spec amendment.
3. **`(set-logic ALL)`.** No standard SMT-LIB logic name covers QF + UF + LIA +
   datatypes; `QF_UFDTLIA` is not an official logic and is rejected by some
   solvers. The admitted fragment is enforced by the translator, which is the
   honest place for it. Alternative considered and rejected: emit a
   non-standard logic name and rely on solver leniency.
4. **Opaque-literal equality is bitwise, not IEEE-754 numeric equality.**
   Each `F64` literal becomes a constant named by the SHA-256 of its raw
   eight-byte payload, and a script with two or more such constants asserts
   one `distinct` over all of them (§3.2.1). Keying on the payload rather than
   the numeric value means `+0.0` and `-0.0` — IEEE-754-equal, byte-distinct —
   are asserted `distinct`. The alternative, an interpretation that treats
   IEEE-754-equal `F64` payloads as one constant, was rejected: it would need
   a numeric equality theory over `F64` to define "IEEE-754-equal" in the
   first place, which is exactly the `QF_FP` fragment §3.2 declines to admit,
   and it would silently disagree with Loom's own intensional identity
   (§4.1), under which two extensionally equal values with different
   canonical bytes are different values. Bitwise equality is therefore the
   only choice consistent with treating `F64` as opaque at all.

A fifth, smaller call: sort and symbol names carry the **full** 64-hex SHA-256,
not §1's 8-character projection prefix. A script is an encoding, not a
projection, and truncation would let two store definitions collide into one
uninterpreted symbol. The cost is long lines.

## Work

- [x] Add normative `SPEC.md` §3.2.1 covering sorts, terms, references, the
  interpretation allowlist, script order, and the two stated fidelity limits.
- [x] `prototype/refinements.py`: `ObligationTranslator`, `obligation_script`,
  `subtype_script`, `check_translatable`, `script_hash`, path-aware `SmtError`.
- [x] Reuse `matches.instantiate_type` for constructor field instantiation and
  `cbor_canonical.encode` for sort keys rather than reimplementing either.
- [x] `prototype/test_refinements.py`: golden script bytes, sort coverage,
  datatype monomorphization and recursion, determinism under arm reordering,
  and an explicit refusal case for every out-of-fragment construct.
- [x] Structural validation of every emitted script by re-parsing it with the
  existing `sexpr` reader and checking command shape and ordering.
- [x] Wire `test_refinements` into `task prototype:test`.
- [x] Update `prototype/README.md` files table and boundary narrative, and add
  this plan's row to `docs/plans/README.md`.
- [x] No solver dependency: `which z3` found nothing on this machine, so no
  `LOOM_SMT_SOLVER`-gated conformance step was added.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

## Completion criteria

- One canonical script per verification condition: identical input gives
  identical bytes, and reordering `match` arms does not change them.
- Every out-of-fragment construct named in the Rules section is rejected with a
  path, not approximated.
- All prior tests pass unchanged and the golden definition hash in
  `test_roundtrip` is untouched.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

1. `task prototype:test`

    ```text
    Ran 87 tests in 0.045s

    OK
    ```

    PASS.

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `task todo:lint`

    ```text
    /home/will/loom/.claude/worktrees/agent-a86c35d715653127a/TODO.md: clean
    ```

    PASS. Run as `python3 ~/python-tui-lib/scripts/todo-lint.py TODO.md`: the
    Taskfile entry resolves the linter through `../python-tui-lib`, which does
    not exist from inside a `.claude/worktrees/` checkout. Same script, same
    file, absolute path.

4. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.
