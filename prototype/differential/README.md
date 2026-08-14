# L0 — the differential harness

The prerequisite Track P names, belonging to no contract:
[`docs/plans/2026-08-14-production-language-decision.md`](../../docs/plans/2026-08-14-production-language-decision.md),
§R7. A JSON-lines export from this Python reference implementation, covering the
26 corpus fixtures, the 5 examples, and every rejection case the prototype's
tests exercise, so that a Rust port can be gated input by input against the
seven versioned contracts in [`../CONTRACTS.md`](../CONTRACTS.md).

It is Python-side output consumed by Rust. Nothing here ports anything.

```
task differential:export      # full — fixtures + the test-suite harvest (~100 s)
task differential:fixtures    # fast — fixtures only (~2 s)
```

Both write `prototype/differential/l0.jsonl` unless `--out`/`--stdout` says
otherwise. The file is **gitignored**: it is derived data that the generator
reproduces byte for byte from the tree, so the generator is what is
version-controlled.

## How cases are harvested

Cases are **observed, never restated.** Every entry point named in
[`contracts.py`](../contracts.py) is wrapped by a transparent proxy; the
prototype's own test suite is then run against the wrapped entry points, and
each call — its input, its accept/reject verdict, its error class, and whatever
canonical bytes and hashes the layer emits — becomes a record.

The tests are untouched. Not one assertion moved, and no test knows the harness
exists. That was the requirement, because the prototype expresses rejection in
at least five shapes — a table of `(source, message)` pairs, an inline
`assertRaises`, a per-class helper method, a `subTest` loop, a constructed IR
literal — and the only seam under all five is the layer boundary itself.

A **fixture pass** additionally drives the 26 corpus entries and the 5 examples
through every layer directly, so those 31 inputs are present whether or not a
test happens to reach them, along with the pinned prelude/corpus/extern
declarations, the corpus's verification conditions, and the default policy.

Wrapping cannot change a verdict: the wrapper calls the original and returns or
re-raises exactly what it returned or raised.
`test_differential.InstrumentationTransparencyTest` pins that.

## Determinism

Two exports of the same tree are byte-identical. No timestamp, no host name, no
absolute path, no dict-iteration order, no `set` order: every collection is
sorted before it is written, JSON is emitted with sorted keys and no
insignificant whitespace, and mappings with non-string keys become sorted pair
lists. `test_differential.ReproducibilityTest` checks it across two independent
processes; `LOOM_DIFFERENTIAL_FULL=1` extends the check to the full scope.

Records are ordered by **migration order** — `parser` first, `policies` last,
matching R7's gate table — then by entry point, then by case id.

One caveat, stated rather than hidden: three of the prototype's tests are
conditional on the local machine — an SMT solver on `PATH`, a seeded
`.loom-store`. If one of those runs it drives calls the others do not, so the
full export can differ *between machines* on the same tree. The header's
`suite.skipped` names exactly which were skipped, so the difference shows up as
a one-line diff instead of as an unexplained change in case counts.

## File layout

One JSON object per line.

| # | `record` | What |
|---|---|---|
| 1 | `header` | Schema version, the seven contract versions this export was cut against, fixture counts, per-layer verdict counts, and — in the full scope — a `suite` block naming the modules harvested, the test count, and any test that was **skipped** |
| 2… | `environment` | The declaration registries cases refer to, sorted by id — lifted out of cases because thousands share each one |
| … | `case` | One differential case |

### `case`

| Field | Meaning |
|---|---|
| `case_id` | SHA‑256 of the canonical `(layer, entry_point, input, environment)` key |
| `layer` | One of the seven contracts |
| `entry_point` | The `module.function` observed |
| `input` | Every contract-relevant argument, canonically encoded |
| `environment` | Id of the `environment` record holding the registry, or `null` |
| `verdict` | `accept` or `reject` |
| `error_class` | The declared error class on rejection, else `null` |
| `canonical_bytes_hex` | The layer's canonical byte output, else `null` |
| `identity_hash` | The hash derived from those bytes, else `null` |
| `extra` | Layer-specific gate surface (below) |
| `provenance` | Every `{origin, module, test}` that reached this case |

`origin` is `fixture` (a named corpus entry or example), `test` (a prototype
test, with its `module` and `Class.method`), or `harness` (a module-import-time
call such as `prelude`'s hash table).

`extra`, per layer, is exactly what R7's gate table says that layer's gate
compares:

| Layer | `canonical_bytes_hex` / `identity_hash` | `extra` |
|---|---|---|
| `parser` | canonical CBOR definition object / 32‑byte identity | `rendered_surface` — the inverse direction the gate also compares — and `ir` |
| `declarations` | declaration bytes / declaration hash | — |
| `scope` | `null` | — (the gate is the verdict and `ScopeError`) |
| `references` | `null` | — |
| `typecheck` | `null` | — |
| `refinements` | the SMT‑LIB script text as UTF‑8 / its SHA‑256 | `smt_script`, the text itself |
| `policies` | policy bytes / policy hash | the predicate's `result` for `at_least`, `satisfies`, `dominates`, … |

A layer may reject with an **earlier** layer's error class —
`typecheck.validate_source` runs scope and references first — so a case's
`error_class` belongs to *some* contract, not necessarily to its own.

### Input encoding

The IR is nested lists of `int`, `bool`, `str`, and `bytes`. JSON has no
`bytes`, so tagged single-key objects carry what JSON cannot:

| Tag | Value |
|---|---|
| `{"$bytes": "…"}` | lowercase hex |
| `{"$f64": "…"}` | IEEE‑754 big-endian bit pattern, hex |
| `{"$map": [[k, v], …]}` | a mapping with non-string keys, sorted |
| `{"$trace": [{…}, …]}` | an injected resolver's observed call table |
| `{"$opaque": "…"}` | **not representable** — the header's `totals.opaque_inputs` counts these, and it is expected to be `0` |

`$trace` is how an injected resolver survives export. `CONTRACTS.md` makes the
resolver call convention — *including* its `None` and raising cases — part of
the contract, so the resolver is wrapped and every call it received during the
case is recorded as `{args, kwargs, returns|raises}`. A consumer replays the
case against that table instead of needing the closure. Because the trace
defines the resolver's behaviour, it is part of the case key: the same source
under two differently-answering resolvers is two cases, which is correct.

The diagnostic `path` argument is dropped. `CONTRACTS.md` states that path
strings are not covered by any version, so including one would split a single
input into two cases over a difference no port has to reproduce.

## Bounding the capture

Recursive entry points (`check_declaration_type` walks a type tree) record only
their **outermost** invocation — the call a differential consumer actually
drives — rather than one case per node. Nesting across *different* entry points
is kept, and is where much of the coverage comes from:
`typecheck.validate_source` reaches `parse_source`, `scope.check_definition`,
and `check_definition_references` on the way, so one call yields cases for four
layers.

`test_differential.EntryPointCoverageTest` fails if a `contracts.py` entry point
is neither captured by [`spec.py`](spec.py) nor listed in that test's
`UNCAPTURED` map with a reason — so the harness cannot quietly stop watching a
contract.

## Modules

| File | Role |
|---|---|
| [`jsonio.py`](jsonio.py) | Canonical, lossless encoding — the determinism guarantee |
| [`recorder.py`](recorder.py) | The case store; merges provenance, raises on a case with two outcomes |
| [`spec.py`](spec.py) | Which entry points are captured, and each one's env / traced / dropped parameters |
| [`instrument.py`](instrument.py) | The wrapping engine, provenance discovery, per-layer gate derivation |
| [`fixtures.py`](fixtures.py) | The 26 corpus entries, the 5 examples, the pinned declarations, obligations and policies |
| [`suite.py`](suite.py) | Runs the prototype's test modules under instrumentation |
| [`export.py`](export.py) | `python3 -m differential export` |
