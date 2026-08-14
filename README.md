# Loom

A specification for an **agent-native programming language** — content
lives in [SPEC.md](SPEC.md). Loom is a thought experiment made precise:
what a language looks like when its only authors are LLM agents and human
ergonomics get zero design weight.

The canonical generation surface uses S-expressions, but Loom is not a Lisp
dialect; see [Is Loom a Lisp?](docs/loom-vs-lisp.md).

**Status: design specification with a working validation prototype and a
persistent object store.** The prototype (`prototype/`, Python) implements
canonical parsing/rendering, deterministic CBOR identity, scope and
nominal-reference validation, a builtin ability registry, and a partial
bidirectional type checker; it remains the validation oracle of record.
`store/` (Rust, binary `loom-store`) is SPEC §5's content-addressed store at
v0 — objects on disk named by the SHA-256 of their bytes, crash-safe writes,
admission gated by the Python oracle, and `fsck`. Loom still has no runtime,
namespaces or leases, complete type system, refinement solver, or evidence
oracle.

## The shape of it

- Programs are **canonical CBOR ASTs** — no concrete syntax, no parser,
  one byte sequence per program. Agents emit encodings under a decoding
  mask, so syntax errors are unsampleable.
- Definitions are **content-addressed** (SHA‑256, verifiable-by-hand
  worked example in [SPEC §4.4](SPEC.md)); editing is rebinding a name.
- Every arrow carries an **effect row**; every dangerous ability needs an
  unforgeable **capability** value — the static audit surface and the
  dynamic blast-radius bound for wrong generations.
- Every binding carries **evidence** per obligation on a four-level
  assurance lattice (assumption < property < exhaustive < proof), with
  **monotone assurance**: regeneration can never silently weaken what was
  already verified. Evidence is memoized by hash, forever.
- **Crisp on purpose.** All gradation is epistemic — the evidence lattice
  grades how well a claim is known, never how true it is. Fuzzy numbers,
  intervals, and distributions are ordinary library *data*; every checking
  judgment stays two-valued so the stochastic author always faces a fixed,
  ungameable referee ([SPEC §3.4](SPEC.md)).
- Names, specs, and provenance are **metadata, not identity** — kept
  because LLM competence is borrowed from natural-language priors, which
  is also why every projection remains human-auditable.

## Lineage

Grew out of two investigation docs, in order:

1. [Analysis of "programming languages will soon be unnecessary"](docs/investigations/2026-08-12-english-as-source-code-analysis.md)
   — why the essay's opaque endpoint doesn't follow.
2. [Loom design sketch](docs/investigations/2026-08-12-loom-agent-native-language-sketch.md)
   — design pressures P1–P6 and decisions D1–D7, derived from how LLM
   agents mechanically work.

Prior art the spec leans on:
[Unison](https://www.unison-lang.org/) (content-addressed code, abilities),
[RFC 8949](https://www.rfc-editor.org/rfc/rfc8949.html) deterministic CBOR,
[SMT-LIB](https://smt-lib.org/) decidable fragments,
[WASM](https://webassembly.org/) as the boundary/compile target.

## Results

The design's central bet — [SPEC §8.4](SPEC.md): does constraining decoding
to Loom's grammar and type discipline actually help an LLM write it — has a
first empirical answer. A masked-generation experiment ran 3,108 draws
across four generation conditions (unconstrained, GBNF syntax, GBNF plus
definition-level rejection sampling, GBNF plus per-token type-directed
masking) and four corpus regimes, on one Qwen2.5‑Coder‑7B‑Instruct Q4_K_M
model on one L4 GPU. Verdict: per-token masking weakly dominates rejection
sampling — it never loses, and wins large without examples in context —
but does not beat plain grammar sampling once the full corpus is
available. The corpus, not the sampling strategy, is the largest lever
measured; held-out compositional tasks scored ≈0 acceptance under every
condition. One model, one size — the write-up states what that does and
doesn't settle.

Write-up: [Constrained generation, results](docs/articles/2026-08-14-constrained-generation-results.md).
Raw reports: [Phase A](docs/results/2026-08-14-phase-a-report.md)
(conditions 1–3, 2,335 draws) and
[condition 4](docs/results/2026-08-14-phase-b-condition4-report.md)
(773 draws, the masker).

## Verdict carried over

Designing for agents does not produce the illegible language the essay
speculates about — it produces an **AI-first, human-auditable** one,
because the model's best working representation and the human's reading
representation converge on the same prior-rich, contract-saturated view.
