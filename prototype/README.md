# Loom prototype — S-expression isomorph + canonical-CBOR transcoder

Implements the `TODO.md` item "Prototype the S-expression isomorph grammar
(SPEC.md SS8.4)": the emission surface an agent would actually decode under
a constrained-decoding harness, plus the deterministic transcoder from that
surface to the canonical CBOR bytes that carry identity (SS4.2–4.4).

**Status: working prototype, not a store.** No typechecker, no evidence
lattice, no oracle — just the one mechanism SS8.4 licenses to exist outside
canonical bytes: a total, deterministic isomorphism.

## Run it

```
cd prototype
python3 -m unittest test_roundtrip -v      # 3 tests, all pass
python3 transcode.py examples/01_id.loom.sexpr
```

## What's here

| File | Role |
|---|---|
| `cbor_canonical.py` | Encoder for RFC 8949 SS4.2.1's deterministic CBOR subset (definite lengths, minimal-length ints, sorted map keys, no tags/indefinite forms). Stdlib only. |
| `sexpr.py` | Trivial S-expression reader — nested lists of atoms, no semantics. |
| `transcode.py` | Maps the S-expression surface onto the exact node tag tables in SPEC.md SS2.1 (terms), SS2.3 (types), SS2.2 (literals), SS4.3 (def objects: `[0, type, term]`). `identity()` is sha256 over the encoded def object, matching SS4.3's definition verbatim. |
| `loom.gbnf` | llama.cpp-style grammar for the same surface — the artifact a real constrained-decoding harness would load. |
| `examples/*.loom.sexpr` | Four defs exercising every term/type tag reachable without a standard library. |
| `test_roundtrip.py` | Pins example 1 to the exact SS4.4 worked-example hash/bytes; checks every example transcodes deterministically and produces a distinct identity. |

## Verified against SPEC.md SS4.4

`examples/01_id.loom.sexpr` transcodes to the *exact* 19-byte encoding and
hash the spec's worked example gives by hand:

```
bytes = 83008402820002808200028303820002820000
hash  = #76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605
```

`test_roundtrip.py::test_worked_example_matches_spec_4_4` asserts this
byte-for-byte — a regression in the encoder cannot pass silently.

The other three examples exercise machinery SS4.4 doesn't touch:
non-empty effect rows + `perform`/`let` (02), `refine` + `hole` + `ref`/`app`
predicates (03), and a two-constructor `data` type with `match`/`con` (04).
Ability/data hashes there are prototype fixtures — `sha256("loom-proto:…")`
labels, not real store content, since no store exists yet.

## What this does and doesn't prove, re: SPEC.md SS8.4

**Confirms:**
- A prior-rich surface can be a real, total, deterministic isomorph of
  canonical CBOR — not just an SS8.4 assertion. Every example round-trips
  byte-identically on repeat transcoding (`test_every_example_transcodes_deterministically`).
- The grammar-level shape constraint (arity, keyword choice) is expressible
  as an ordinary CFG (`loom.gbnf`), consistent with SS8.4's claim that
  syntactic masking is commodity-tier.

**Does not confirm** (SS8.2's honest limits, unchanged by this prototype):
- Scope correctness (`var` index < binder depth) needs a stateful mask
  beyond what a CFG expresses — `loom.gbnf`'s header says so explicitly.
- Type-directed pruning, refinement checking, and evidence are not
  implemented here at all; `transcode.py` will happily encode a
  type-incorrect or unscoped term, exactly as a bare CBOR encoder would.
  This prototype is the SS8.1/SS8.4 layer only, not the SS3/SS6 oracle.

## One spec gap this surfaced

SPEC.md SS2.2 gives the literal node shape as `[2, k, v]` uniformly but
never says what `v` is for `unit` (kind 0), which has no natural payload.
This implementation encodes `(lit unit)` as the 2-element array `[2, 0]`
(`v` omitted rather than null-padded) — see `transcode.py`'s `term_to_ir`.
SPEC.md SS2.2 now carries a one-line note recording this as the canonical
form, found by trying to implement the encoder rather than by inspection.
