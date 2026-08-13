# Plan — Extern object encoding

**Date:** 2026‑08‑13
**Status:** Implemented and verified locally
**Depends on:** SPEC.md §2.4 (the `ffi` ability and the runtime ABI envelope),
§3.2.1 (SMT translation; references as uninterpreted functions), §4.3 (object
kinds), §5.1.1/§5.1.2 (how a declaration object is specified), §5.2 (names and
prose are metadata), §5.3.1 (obligation kinds, assumption budgets, signers), §6.1
(the assurance lattice; A0), §11 (the FFI boundary), §13 open problem 1

## Objective

§11 promises an `extern` definition — "a foreign artifact … with a Loom type, a
required capability set, and mandatory `A0 assumption` evidence" — and §5.3.1
already counts one against a namespace's assumption budget. But §4.3's kind list
had no tag for it, so nothing could be stored: the object had a specification in
prose and no encoding.

The concrete blocker is tranche 2 of the
[bootstrap-corpus plan](2026-08-13-bootstrap-corpus.md). Its R5 establishes that
Loom v0.1 has no `+` term, so arithmetic must arrive as externs, and pins the
assumed base at exactly five — `I64.add`, `I64.sub`, `I64.eq`, `I64.lt`,
`List.size`. All five are unstorable today, and with them the whole recursive
list tranche (`list/append`, `list/reverse`, `list/map`, `list/foldLeft`,
`list/foldRight`, `list/concat`, `list/flatMap`), whose measures are all
`(ref #List.size)`.

Specify the **extern object** — its kind tag, its deterministic CBOR shape, what
is in identity and what is metadata, how a term references it, what obligations it
carries, and whether §3.2.1's interpretation table may reach it.

Out of scope, deliberately: the A0 payload's own encoding (§13 open problem 6(a),
so "signed by a principal" still means a 32-byte principal id the spec does not
say how to prove possession of); the WASM adapter registry and its wire protocol
beyond §2.4's existing envelope; and any evaluator, since the prototype has none.

No visible surface (normative spec text plus a validation module), so this plan
carries no mockups.

## Rules

### R1 — An extern is a new store object kind (tag 7), not a def object

§4.3's kind tag is what makes cross-kind hash collisions impossible by
construction, and the six existing tags are all taken (policy took 6). An extern
is a def object with the term removed and an ABI identification added; overloading
kind 0 for it would make "does this def object have a body?" a shape question
inside the one object whose shape is `[0, type, term]` in every other case.

Consequently §4.3's list gains `7 extern` and §5.1's "Seven kinds" becomes "Eight
kinds". The normative shape lands as **§5.1.3**, beside the other two
declaration-shaped objects, and §11 points at it rather than restating it.

**Rejected: an extern as a def object whose term is a distinguished `hole`.**
§2.6 confines a hole-containing definition to `draft/`, where it "can never be the
target of a binding" — exactly backwards for the one object whose whole purpose is
to be bound and depended on.

**Rejected: a new term tag `extern`.** §2 says every tag added is decoding-mask
complexity paid forever. An extern needs no term-level form: `ref` already names a
store object by hash, and resolution is where the difference lives.

### R2 — The shape is `[7, type, artifact, abi]`, a fixed-arity array

Four fields, canonical order, no map — a map is right for the policy object
because a policy is mostly *optional* constraints (§5.3.1 R2), and an extern has
no optional field at all: every one is mandatory, so §5.1.1/§5.1.2's positional
array is the matching form.

- `type` — the extern's Loom signature, checked at term depth 0 and type depth 0.
- `artifact` — the 32-byte content hash pinning the foreign artifact, which is
  §11's own words ("pinned by its own content hash").
- `abi` — non-empty NFC text, the entry-point selector inside that artifact.

**Two texts were considered and merged into one.** An earlier draft carried
`adapter` and `entry` separately. §2.4 already says `ffi.call`'s `Text` "selects a
registered adapter", so one selector text that *is* that `Text` unifies §2.4 and
§11 with no second registry, and a host that wants sub-structure can put it in the
selector. Recorded as the alternative.

### R3 — The type is closed, monomorphic, and capability-honest

Checked at type depth 0 with no `self` arity — so `tyvar`, row variables, and the
§5.1.1 declaration-local `self` are all out of scope — and `forall` is rejected
outright. The reason is the corpus plan's R3, verified there rather than assumed:
v0.1 has no term-level type application, so a polymorphic extern could never be
used at an instance. A polymorphic extern would be an object nothing could call.

**The declared effect row is the assumption, and the empty row is the loudest
one.** `I64.add : I64 -> I64 -> I64` with empty rows throughout claims the foreign
artifact is pure, total, and deterministic. That claim is unverifiable by
construction — which is exactly what the mandatory A0 evidence (R5) is signed for,
and it is also what makes the extern usable in a refinement predicate at all,
since §3.2.1 requires every arrow on a translated reference's spine to carry the
empty row.

**Capability honesty.** For every ability `a` occurring in any row of the type,
the type must take a `cap a` parameter in some domain position. Without this rule
§2.4's blast-radius bound leaks: applying an extern is not a `perform`, so nothing
else in the language would demand the capability, and an extern typed
`Bytes -{ffi}> Bytes` would let a definition reach the outside world while its
type mentions no `cap`. The five assumed-base externs are pure-typed and take no
capability, so the rule costs the corpus nothing.

**Rejected: leaving the capability requirement to the call site.** It is
recoverable in principle — the caller's ambient row must permit `a` — but it moves
the one guarantee §2.4 states in absolute terms ("a definition whose type mentions
no `cap net` cannot exfiltrate") from a property of a type into a property of a
whole-program analysis. The conservative option is the one that keeps the type
sufficient.

### R4 — There is no nominal key; `(artifact, abi)` is the discriminator

§5.1.1 and §5.1.2 carry a 32-byte nominal key because two structurally identical
declarations must be distinguishable and nothing else in the object distinguishes
them. An extern already carries something that does: `abi` is the byte string the
host resolves, so `I64.add` and `I64.sub` — byte-identical in type, same artifact —
differ by precisely the thing that makes them different at runtime.

The converse is the policy object's argument (§5.3.1): two externs agreeing on
type, artifact, and ABI *are* the same extern, and should share one hash, one
review, and one A0 entry. A nominal key would let one namespace's `I64.add` and
another's be different objects with duplicated assumptions, which is the outcome
the assumption budget exists to make visible.

**Names stay out of identity.** `I64.add` and `List.size` are §5.2 meta objects.
The corpus's ABI selectors are deliberately spelled differently from the names
(`i64.add`, `list.size`) so the separation is visible in the fixture rather than
merely asserted, and `test_externs` pins it.

**Recorded alternative:** a nominal key *plus* the ABI pair, giving a namespace
the ability to fork an extern's identity without changing what it calls. Rejected
as strictly worse for the auditing story §11 sells.

### R5 — Referencing is the existing `ref`; the obligation is `extern`, always A0

An extern is referenced by `[1, h]` (§2.1). A `ref` resolves to a def object *or*
an extern object; when it resolves to an extern its type is that object's `type`
field and there is no body, so it is never unfolded, never evaluated, never the
subject of a `handle`. A checker that cannot resolve the target reports an
unresolved dependency rather than guessing, which is §2.3.1's existing discipline
for operation arities.

**Evidence.** §5.3.1's obligation-kind registry gains tag **4 `extern`**, no
detail in v0.1. Every extern carries one A0 `assumption` entry whose justification
states what is trusted: the signature, the declared row, and any §3.2.1
interpretation claimed for it. Nothing in the spec can raise that entry above A0,
which makes the knob sharp in both directions: `max-assumptions: 0` (key 2)
forbids externs by budget, and a rule `[[4], [1, …]]` or higher forbids them by
level. Per-ability budgets (key 3) apply through the extern's own rows, so an
`ffi`-carrying extern counts against `ffi`.

**Rejected: reusing `property.<detail>`.** Key 1 injected obligations are a
*policy's* statement about bindings it governs; an extern's assumption is the
object's own, present whether or not any policy mentions it.

The assumption set in §5.3.1 was defined over "every def object transitively
reachable by `ref`". That is amended to include extern objects — without it the
number §11 promises would omit precisely the objects §11 is about.

### R6 — §3.2.1's interpretation table admits extern hashes, and that is its point

Decided rather than left open: the toolchain interpretation table may map an
**extern** hash onto the closed allowlist, and this is its principal use. A def
object has a body some future version could unfold; an extern has none, so an
interpretation is the only route by which its reference will ever be more than an
uninterpreted symbol — and it is what makes tranche-2 arithmetic provable at all.

Nothing is relaxed for it. The extern's type must resolve, every arrow on the
spine must carry the empty row (so an `ffi`-carrying extern is out of fragment
entirely, interpreted or not), each application is still checked against the
symbol's own signature, and linearity is still enforced at the call site. The
table remains toolchain policy and never enters an object, so identity is
untouched.

**The honesty clause, stated in the spec:** mapping `I64.add` onto `+` is a claim
about a foreign artifact, exactly as strong as that extern's A0 justification, and
it inherits §3.2.1's existing `Int`-does-not-wrap limit. A proof built on it is A3
*relative to* an A0 assumption, and the assumption count is where that shows up.

`List.size` is deliberately **not** in the reference interpretation table: it is
R4-of-the-corpus's measure primitive, and an uninterpreted function with
congruence is all the corpus needs from it.

### R7 — The assumed base is corpus manifest data, one artifact and five selectors

The five live in `corpus_registry.py` beside the corpus data declarations,
because that is the module tranche 2 will read them from. They are host
primitives, not a WASM component, so their pinned artifact is the host adapter's
published ABI identity, derived reproducibly as `SHA-256("loom:v0.1:corpus:host")`
under the same prefix discipline as the corpus nominal keys. One artifact, five
ABI selectors — which is also what the object shape is *for*.

**Stated rather than hidden:** the spec permits a host with no artifact bytes to
pin a published 32-byte ABI identity instead of a content hash. That is a weaker
pin than a WASM component's, and it is the honest description of what a host
primitive is.

## Steps

- [x] SPEC.md §4.3: add kind `7 extern` to the tag list.
- [x] SPEC.md §5.1: "Seven kinds" → "Eight kinds".
- [x] SPEC.md §5.1.3 (new): the object shape, field semantics, the no-nominal-key
  argument, the effect-row-is-the-assumption rule, capability honesty, how a `ref`
  resolves, the evidence obligation, and a byte-level worked example with pinned
  hashes for `I64.add` and `I64.sub`.
- [x] Surgical §2.4 edit: `ffi.call`'s text is an extern's `abi` selector.
- [x] Surgical §3.2.1 edits: a `ref`'s type may resolve from an extern object; a
  paragraph admitting extern hashes into the interpretation table with the
  empty-row and A0-honesty conditions.
- [x] Surgical §5.3.1 edits: obligation-kind tag 4 `extern`; the assumption set
  ranges over extern objects too.
- [x] Surgical §6.2 edit: one `extern` obligation per extern object referenced.
- [x] §11: point at §5.1.3, summarize what is in identity, and say what the
  assumption count now counts.
- [x] §13 open problem 1: mark the extern-encoding residue closed, leaving the
  other two corpus findings open.
- [x] `prototype/declarations.py`: additive `check_extern_type`,
  `check_extern_definition`, kind-7 branch in `declaration_bytes`, `ExternInfo`,
  and registry `extern` / `extern_object` / `reference_type` accessors.
- [x] `prototype/policies.py`: obligation-kind registry gains tag 4.
- [x] `prototype/corpus_registry.py`: `HOST_ARTIFACT`, the five externs,
  `EXTERN_HASHES` / `EXTERN_HASH_HEX`, `SMT_INTERPRETATION`, `extern(name)`, and
  extern registration in `registry()`.
- [x] `prototype/test_externs.py` (new, 29 tests) and its Taskfile wiring.
- [x] Rows in `docs/plans/README.md` and `prototype/README.md`.

## Verification

```sh
task prototype:test
python3 -m py_compile prototype/*.py
task todo:lint
git diff --check
```

Plus, by hand, the pinned `I64.add` extern:

```sh
printf '\x84\x07\x84\x02\x82\x00\x02\x80\x84\x02\x82\x00\x02\x80\x82\x00\x02\x58\x20\xce\x43\x33\x7f\xac\xff\x58\xa0\xc1\x00\x63\xb9\x90\x81\xd0\xe4\xc6\x37\xeb\x89\x36\xbb\x78\x38\x34\x33\x95\x55\xab\x83\x39\xf7\x67\x69\x36\x34\x2e\x61\x64\x64' | sha256sum
```

Note: `task todo:lint` resolves `../python-tui-lib/scripts/todo-lint.py` relative
to the Taskfile directory, which does not exist from a nested
`.claude/worktrees/…` checkout. The recorded run below invokes the same linter by
absolute path; from the main checkout the `task` form is equivalent.

## Completion criteria

- §4.3 and §5.1 agree on eight object kinds, with `7 extern` among them.
- §5.1.3 states a deterministic CBOR shape with a canonical field order, says what
  is in identity and what is §5.2 metadata, and pins a reproducible worked example.
- The encoding is shown sufficient for exactly the five tranche-2 externs, each
  with a pinned hash under test.
- §3.2.1 decides the interpretation-table question explicitly, in a direction that
  makes tranche-2 arithmetic provable without weakening the fragment.
- §5.3.1's assumption set and obligation registry account for externs, so §11's
  "how much of this system is faith?" query returns a number that includes them.
- §13 open problem 1 no longer lists the extern encoding as residue.

## Recorded verification

Run on 2026‑08‑13.

**Result: PASS**

1. `task prototype:test`

    ```text
    test_the_interpretation_table_maps_an_extern_hash_onto_the_allowlist (test_externs.ExternSmtInterpretationTest.test_the_interpretation_table_maps_an_extern_hash_onto_the_allowlist) ... ok

    ----------------------------------------------------------------------
    Ran 184 tests in 0.073s

    OK
    ```

    PASS (tail shown; 184 of 184 tests OK, of which 29 are the new
    `test_externs` suite).

2. `python3 -m py_compile prototype/*.py`

    ```text
    (no output; exit 0)
    ```

    PASS.

3. `task todo:lint` — run as
   `python3 ~/python-tui-lib/scripts/todo-lint.py TODO.md` (see the note above)

    ```text
    /home/will/loom/.claude/worktrees/agent-acd6df31962cc59f2/TODO.md: clean
    exit=0
    ```

    PASS.

4. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.

5. The pinned `I64.add` extern bytes

    ```text
    23d1e0891aef622110302fe247b7148de5eb61a09f30138cfe7bd09d6cf7e6d7  -
    ```

    PASS — matches the hash pinned in §5.1.3 and in
    `corpus_registry.EXTERN_HASH_HEX["I64.add"]`.

## The five pinned externs

| Name (§5.2 metadata) | Type | `abi` | Identity |
|---|---|---|---|
| `I64.add` | `I64 -> I64 -> I64` | `i64.add` | `23d1e089…6cf7e6d7` |
| `I64.sub` | `I64 -> I64 -> I64` | `i64.sub` | `d3914e25…322f00b5` |
| `I64.eq` | `I64 -> I64 -> Bool` | `i64.eq` | `4fb7cc71…d1dea41d` |
| `I64.lt` | `I64 -> I64 -> Bool` | `i64.lt` | `0e2c1cac…3d562965` |
| `List.size` | `List I64 -> I64` | `list.size` | `4bd80df0…ff5ad5ae` |

Artifact for all five:
`ce43337facff58a0c10063b99081d0e4c637eb8936bb783834339555ab8339f7`
(`SHA-256("loom:v0.1:corpus:host")`). Interpretation table: `+`, `-`, `=`, `<` for
the first four; `List.size` uninterpreted.

## Residue

- **The A0 payload is still unencoded** (§13 open problem 6(a)). "Signed by a
  principal" therefore remains a 32-byte identifier with no possession proof, so
  §5.3.1 key 4 `signers` can be *checked* against an extern's A0 entry only once
  that format exists. Unchanged by this plan, and the reason the prototype
  validates extern *objects* and not extern *evidence*.
- **No evaluator, so the ABI is unexercised.** The prototype validates and hashes
  extern objects; nothing calls one. §2.4's envelope rules stay untested here.
- **Tranche 2 itself is not built.** This plan supplies the encoding the corpus
  plan's layer 1 was blocked on and pins the five identities; the eight recursive
  definitions that consume them remain a corpus task, and they will stay at the
  `structural` tier until the match layer grows typing rules for `fix` and `ref`.
- **Obligation-id disambiguation.** With no detail in v0.1, a definition holding
  two externs has two `(object-hash, "extern")` pairs — distinct because the
  object hashes differ — but a *policy rule* cannot single one out. Same shape as
  the open `fix`/`match` disambiguation problem in §13 6(a).
