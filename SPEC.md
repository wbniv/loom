# Loom — Language Specification, v0.1

**Status:** Design specification with a working validation prototype — see
[README.md](README.md) for the implemented/missing boundary. Every rule below
is still written as if it were normative so that the design can be attacked
concretely. Derived from the six design pressures in
[the design sketch](docs/investigations/2026-08-12-loom-agent-native-language-sketch.md)
(P1–P6 are referenced throughout).
**Date:** 2026‑08‑12

---

## 1. Model and terminology

- **Store** — the only persistence layer. An append-only, content-addressed
  set of *objects*. There are no files and no builds.
- **Definition** — a typed, closed term. Identified by the hash of its
  canonical encoding (§4). Immutable.
- **Binding** — a mutable name-path ↦ definition-hash mapping, carrying
  evidence (§6). The only mutable thing in the system.
- **Projection** — a rendering of store content for a reader (human or
  model). One-way: no parser for any projection exists (§9).
- **Agent** — a stochastic author. Emits canonical encodings under a
  decoding mask (§8). Never edits text.
- **Oracle** — the deterministic toolchain: typechecker, SMT solver,
  evidence runner. The only source of ground truth in the loop (P5).
- **Principal** — a human or service accountable for a namespace's policy.

Hashes are SHA‑256 in v0.1 (ubiquitous, verifiable anywhere; a faster hash
is a v0.2 question, not a semantic one). A hash is written `#` + first
8 hex chars in projections, full 32 bytes in encodings.

## 2. Core calculus

A pure, total-by-default functional core with algebraic data, algebraic
effects and handlers, refinement types, and capability values. The node set
is deliberately small and closed — the decoding mask (§8) is a table over
these tags, and every tag added is mask complexity paid forever.

### 2.1 Terms

Every term is encoded as a CBOR array `[tag, …fields]`.

| Tag | Node | Shape | Notes |
|---|---|---|---|
| 0 | `var` | `[0, i]` | de Bruijn index — bound names do not exist in canonical form |
| 1 | `ref` | `[1, h]` | reference to a store definition by 32‑byte hash |
| 2 | `lit` | `[2, k, v]` | literal; kinds in §2.2 |
| 3 | `lam` | `[3, T, body]` | fully annotated — canonical form is the *elaborated* term |
| 4 | `app` | `[4, f, a]` | |
| 5 | `let` | `[5, T, bound, body]` | monomorphic let; polymorphic reuse goes through the store (§3.1.3) |
| 6 | `con` | `[6, d, i, [args]]` | constructor `i` of data type `d` |
| 7 | `match` | `[7, scrut, [arms]]` | arm = `[ctor-index, binder-count, body]`; must be exhaustive |
| 8 | `perform` | `[8, a, i, [args]]` | operation `i` of ability `a` |
| 9 | `handle` | `[9, a, term, [ops], ret]` | handler discharges ability `a` from the row |
| 10 | `fix` | `[10, T, measure, body]` | recursion **only** with a termination measure; see §2.5 |
| 11 | `hole` | `[11, T, [constraints]]` | typed hole; storable only in the draft region (§5.4) |
| 12 | `if` | `[12, c, t, e]` | the elimination form for `Bool` (§2.2); binds nothing (§3.1.4) |

There is no `anno` node and no syntax for comments: hashing operates on
elaborated terms, and prose lives in metadata (§5.2), never in the term.

### 2.2 Literals and base types

Literal kinds: `0` unit, `1` bool, `2` i64, `3` f64 (8 raw bytes,
IEEE‑754 big-endian byte string — NaNs canonicalized to a single quiet NaN),
`4` text (Unicode NFC), `5` bytes. `unit` has no payload: its node is the
2-element array `[2, 0]` — `v` is omitted, not null-padded — since kind 0 is
the only one with nothing to carry.

### 2.3 Types

| Tag | Node | Shape | Notes |
|---|---|---|---|
| 0 | `base` | `[0, c]` | `c`: 0 Unit, 1 Bool, 2 I64, 3 F64, 4 Text, 5 Bytes |
| 1 | `data` | `[1, h, [T…]]` | applied data type by hash |
| 2 | `fn` | `[2, dom, row, cod]` | effect row on every arrow |
| 3 | `refine` | `[3, T, φ]` | `{x : T \| φ}`; φ is a term of type Bool over the SMT fragment (§3.2) |
| 4 | `cap` | `[4, a]` | capability for ability `a` — a nominal, unforgeable value type |
| 5 | `tyvar` | `[5, i]` | de Bruijn at the type level |
| 6 | `forall` | `[6, T]` | rank‑1 polymorphism only |

An **effect row** is a CBOR array of ability hashes sorted bytewise
(deterministic by construction), optionally ending in a row variable
`[5, i]`. The empty row `[]` means pure.

### 2.3.1 Scope and binder order

Term and type variables use separate de Bruijn spaces; every `var i` requires
`i < term-depth`, and every `tyvar i` (including a row variable) requires
`i < type-depth`.

A closed definition's **type** is checked at term depth 0 and type depth 0. Its
**term** is checked at term depth 0 and type depth *p*, where *p* is the length
of that type's leading `forall` prefix: a definition typed `forall^p T` is
implicitly type-abstracted over those *p* variables and its term is checked
against `T` (§3.1.3). A definition type's quantifiers must be **prenex** —
after removing the leading `forall`s, no `forall` may occur in the remainder —
which is what makes *p* well defined and what turns §2.3's "rank-1 polymorphism
only" into a checked property rather than an assertion. Types written *inside* a
term (a `lam` annotation, a `hole` goal type) are not restricted this way.

Binder-producing nodes extend those depths as follows:

- `lam` adds one term binder in `body`.
- `let` checks `bound` at the current depth and adds one term binder only in
  `body`.
- Each `match` arm adds its encoded `binder-count` term binders in constructor
  field order; the last constructor field is index 0.
- `refine T φ` checks `T` at the current depths and checks `φ` with the refined
  value added as term index 0.
- Each `hole` constraint is checked with the prospective hole value added as
  term index 0.
- `forall T` adds one type binder throughout `T`.
- `fix T measure body` checks `T` and `measure` at the current depth, then adds
  the recursive value as term index 0 in `body`. A recursive function normally
  therefore has a `lam` body: inside that lambda its argument is index 0 and
  the recursive value is index 1.
- A `handle` return clause adds the handled computation's result as term index
  0. An operation clause obtains the selected operation's parameter count from
  the referenced ability definition, adds those parameters in signature order,
  then adds the resumption continuation as index 0; the last parameter is index
  1. A checker that cannot resolve the ability or operation signature must
  report an unresolved scope dependency, not guess an arity.

Types may contain refinement predicates referring to the surrounding term
context. Function codomains do not implicitly bind their domain value; Loom v0.1
does not have dependent function arrows.

### 2.4 Abilities and capabilities

Abilities (effect interfaces, in the sense of
[Unison's abilities](https://www.unison-lang.org/docs/fundamentals/abilities/))
are declaration objects (§5.1.2). The v0.1 reference prelude contains these
canonical abilities; the listed order is the numeric operation index:

| Ability | Operations |
|---|---|
| `clock` | `0 wallMillis : () → I64`; `1 sleepMillis : I64 → Unit` |
| `rand` | `0 bytes : I64 → Bytes`; `1 i64 : () → I64` |
| `fsRead` | `0 read : Text → Bytes` |
| `fsWrite` | `0 write : (Text, Bytes) → Bytes` |
| `net` | `0 request : Bytes → Bytes` |
| `spawn` | `0 run : (Text, Bytes) → Bytes` |
| `div` | no operations; effect-row marker only (§2.5) |
| `ffi` | `0 call : (Text, Bytes) → Bytes` (§11) |

| Ability | Normative SHA-256 identity |
|---|---|
| `clock` | `e6eb1adefeb5a68998deb5f6840f95be2bd5540650fda7b31e79e7440ba2a51d` |
| `rand` | `0bd4b691815a14f9cc0cc96d38eb3a7d7e718b01ef0ef4dc6172b1e9f66d2475` |
| `fsRead` | `98e9d59d0eee7d7cdddf1f06b690d2dbcd0dd79e3dde97cf3e119281962e6772` |
| `fsWrite` | `078fa6902f2133ad6cf9c1c18835aad6ebd875006e99c184f4fe703194c73050` |
| `net` | `0a87ba35788ecab52716934cc1b3ae9c8a943ad543066d7e74af665f516cc65f` |
| `spawn` | `9f647c04e8191162b08c6575d0fd115d2823f4487a7fa76dd6551b8d3b0d1451` |
| `div` | `74d0a12b01b77d554d53344d6ef0565cbb622c3d1becd95560f8482ccf8ce269` |
| `ffi` | `a87de5c170b63c3e59d998253246b68e69da1070b785cd129783753e252c76fd` |

`wallMillis` returns signed Unix-epoch milliseconds. `sleepMillis n` returns
immediately when `n ≤ 0`. `rand.bytes n` returns exactly `max(n, 0)` bytes. The
remaining `Bytes` results are canonical runtime ABI envelopes. At the decoded
CBOR level the envelope is `[status, payload]`: success uses status `0` and a
byte-string payload; failure uses status `1` and an NFC-normalized diagnostic
text payload. `fsRead` succeeds with the file bytes; `fsWrite` succeeds with
empty bytes. `net.request` accepts canonical CBOR
`[method-text, url-text, [[header-text, value-text]], body-bytes]` and its success
payload is canonical CBOR `[status-i64, [[header-text, value-text]], body-bytes]`.
`spawn.run` takes an executable name plus canonical CBOR
`[[argument-text], [[env-name-text, env-value-text]], stdin-bytes]`; its success
payload is canonical CBOR `[exit-i64, stdout-bytes, stderr-bytes]`. `ffi.call`'s
text selects a registered adapter and its request/success payload bytes are the
canonical CBOR ABI declared by that adapter's mandatory extern metadata (§11).
This byte protocol keeps the core prelude usable before standard
`Result`, filesystem, network, process, and foreign-value data types exist.
Runtimes must reject noncanonical request envelopes with a failure envelope,
never trap the Loom evaluator.

The declarations producing these identities are executable in the reference
implementation (`prototype/prelude.py`); changing a nominal key or signature is
an ABI and identity change requiring a new language version.

A **capability** is a runtime value of type `cap a`, introduced only by the
runtime at a program entry point, never constructible in the language.
Performing an operation of ability `a` requires both `a` in the effect row
*and* a `cap a` value in scope. The row is the static audit surface; the
capability is the dynamic blast-radius bound: a definition whose type
mentions no `cap net` cannot exfiltrate regardless of how badly it was
generated.

### 2.5 Totality

Loom is total by default. `fix` requires a `measure`: a term mapping the
recursive argument to a natural number that the oracle proves strictly
decreasing (obligation `terminates`, §6.2). If no measure is provable, the
definition must instead take the `div` ability in its row — divergence is an
effect, visible in every caller's type, all the way up.

### 2.6 Holes

`hole` carries its goal type and a constraint list (equalities and
membership facts the fill must satisfy). A term containing holes typechecks
— the hole inhabits its goal type by fiat — but is confined to the draft
region of the store and can never be the target of a binding (§5.4). Holes
are the unit of the generation loop's narrowing step (§8.3).

## 3. Static semantics (highlights)

Full formal rules are out of scope for v0.1; the load-bearing choices:

### 3.1 Elaboration before identity

The hashed form is the *elaborated* term: all types explicit, all instances
resolved, all implicit machinery discharged. Two agents whose inference
engines differ in power still agree on the identity of any term they can
both elaborate — identity never depends on inference strength.

### 3.1.1 Nominal constructor and match typing

For a data declaration `[4, key, p, constructors]` referenced as
`data h [A₀…Aₚ₋₁]`, constructor field types are instantiated by replacing
declaration `tyvar i` with `Aᵢ` and declaration-local `self [B…]` with
`data h [B…]` after recursively applying the same substitution.

`con h i [args]` synthesizes `data h [A…]` when checked in a context fixing its
type arguments, constructor `i` exists, and its instantiated field types match
the arguments. A `match` scrutinee must synthesize a nominal `data h [A…]` type.
Its arms must contain every constructor index exactly once and no other index;
each arm's `binder-count` must equal that constructor's field count. Instantiated
field types enter the arm environment in declaration order, with the last field
at de Bruijn index 0 (§2.3.1). Every arm body must have one common result type.

### 3.1.2 Effect-directed typing

A lambda checked against `fn D row C` must carry annotation `D`; its body is
checked against `C` with exactly `row` as its ambient effect allowance. A closed
definition begins with no ambient effects. `perform a i args` resolves operation
`i` in ability `a`, checks arguments against its parameter types, and has its
declared result type. It is valid only when `a` occurs in the ambient effect row
and a value of type `cap a` is in the term environment. A lambda in synthesis
position is pure: its body is checked with the empty ambient allowance and its
synthesized type carries the empty row. Latent effects are expressible only by
checking against an annotated `fn` row. Expected types flow into a term from a
definition annotation, a checked lambda codomain, a constructor field, an
application parameter, an operation argument's declared parameter type, a
typed `let` binding, an expected match-arm result, or a handler clause result. Loom v0.1 has no type-ascription term. Consequently an
effectful lambda in a synthesis-only position, including as the direct callee
of an application, is rejected even when the surrounding ambient row permits
its effect; bind it through a typed `let` to supply its annotated function row.

Checking `handle a term ops ret` against result type `R` checks `term` with `a`
added to the ambient allowance and obtains handled result type `T`. The return
clause binds `T` at index 0 and checks against `R`. Each operation clause binds
the operation parameters in signature order, then a continuation at index 0 of
type `fn operation-result ambient-row R`; its body checks against `R`. Clauses
must cover every operation exactly once. The continuation's row is the outer
ambient row, so the handler discharges `a`; handling an ability already present
outside does not remove that outer allowance. An ability that declares no
operations (`div`) is an effect-row marker only and can never be the subject of
`handle` — divergence stays visible in every caller's row (§2.5). The v0.1 prototype's
type-directed layer requires closed rows—row-polymorphic effect checking remains
future work.

### 3.1.3 Definition-level polymorphism

Polymorphism is introduced at the **definition** boundary and nowhere else.
There is no term node that abstracts or applies a type: a definition typed
`forall^p T` *is* the type abstraction, and §2.3.1's depth rule is the whole
mechanism — its term is checked at type depth `p`, so a `lam` annotation inside
it may name `tyvar 0 … tyvar (p-1)`. `forall a. forall b. (a → b) → Maybe a →
Maybe b` is therefore an ordinary, storable, checkable definition, written with
the node vocabulary §2.1 already has.

Three properties make this the cheap form of the feature, and they are the
reason it is preferred to a `tylam`/`tyapp` pair:

- **No tag is added.** §2's cost model prices every node in permanent mask
  complexity. Elaborated form (§3.1) would additionally require a `tyapp` chain
  at *every use site of every polymorphic definition*, so that pair is paid
  forever at every call, not once at the binder.
- **The mask needs no lookahead.** A def object is `[0, type, term]` (§4.3), so
  the entire type precedes the first byte of the term: `p` counts bytes the
  decoder has already emitted. The stateful masker §8.4 describes initializes its
  existing type-depth register to `p` rather than 0, and gains no new state.
- **Parametricity is structural, not an added restriction.** No literal and no
  constructor inhabits `tyvar i`, so a value of type-variable type can only be
  received as a parameter and passed on; nothing observes it. §3.2.1 keeps
  `forall` and `tyvar` out of the SMT sort fragment, so no refinement predicate
  can see one either.

**Instantiation is not available in v0.1, and the omission is deliberate.** A
`ref h` whose stored type is `forall^p T` synthesizes that quantified type, and
the calculus has no rule that eliminates a `forall`. A polymorphic definition can
therefore be written, hashed, stored, and read, but is called only through a
monomorphic definition of its own — which is why a store holds both a generic
definition and its instances, each with its own identity and its own evidence
(§4.1). The intended future rule adds no node either: a quantified reference is
instantiated by *first-order matching* against an expected type, supplied exactly
where §3.1.2 already supplies an effectful lambda's row — by binding it through a
typed `let`. Matching a quantifier prefix against a concrete expected type is
syntactic and deterministic, so the resolved instance ends up written down in the
`let`'s annotation and identity never depends on inference strength (§3.1). Until
that rule exists, this section states the limit rather than implying the feature.

### 3.1.4 Bool elimination

`if c t e` (§2.1 tag 12) is the elimination form for `Bool`, and the only one.
Checked against result type `R` in ambient row `ρ`: `c` checks against `Bool`
under `ρ`, and `t` and `e` each check against `R` under `ρ`. In synthesis
position both branches are synthesized and must agree, and that common type is
the result. `if` binds nothing, so §2.3.1's depth rules are untouched and its
three subterms are checked at the current depths. Projections render it
`if c then t else e` (§9, §12).

`Bool` stays a base type. Literal kind 1 (§2.2), base code 1 (§2.3), `refine`'s
"φ is a term of type Bool" (§2.3 tag 3), and §3.2.1's mapping of `Bool` onto
SMT-LIB `Bool` are all unchanged — the last of these is load-bearing, since a
refutation script ends in `(assert (not <goal>))` and a goal of datatype sort
cannot be negated. Making `Bool` nominal would have taken the whole
refinement-to-SMT pipeline with it.

`if` is exhaustive by construction, so it generates no obligation: §5.3.1's
closed obligation-kind registry and §6.2's generation rule are untouched, and in
particular `exhaustive-match` remains one per `match`.

### 3.2 Refinements and obligations

Refinement predicates live in a decidable fragment: quantifier-free linear
integer/real arithmetic plus datatypes and uninterpreted functions (roughly
what [SMT-LIB](https://smt-lib.org/) `QF_UFLIRA` + datatypes gives). Each
`ensures`-style refinement on a binding generates a **named obligation**;
obligations the solver discharges get `proof`-level evidence automatically;
the rest must be covered by weaker evidence explicitly (§6). Nothing is ever
silently unverified — every obligation has an evidence entry, even if that
entry is `assumption`.

### 3.2.1 Translation to SMT-LIB

Naming the fragment is not enough to discharge an obligation: the oracle needs
a *deterministic* map from Loom terms to solver input. These rules define it.
One verification condition produces exactly one SMT-LIB script, byte for byte —
canonical form applies to the oracle's inputs as much as to the store's contents
(§4.2), and it is what makes the memo ledger (§6.4) able to key evidence on the
script rather than on the obligation's name.

**Verification condition.** The translation unit is a triple `(Γ, H, g)`: a
context `Γ` of Loom types indexed by de Bruijn index, a list `H` of Bool-typed
hypothesis terms, and a Bool-typed goal term `g`, all checked under `Γ`. v0.1
specifies one producer: refinement subtyping (§3.3). `{x:T|φ} <: {x:T|ψ}`
becomes `Γ = [T]`, `H = [φ]`, `g = ψ`, with any surrounding term context
appended to `Γ` after the refined value. Verification-condition generation for
function bodies is future work; until it exists, an `ensures` obligation over a
body reaches A3 only through a subtyping check the typechecker already emits.

**The refined value is index 0.** Consistent with §2.3.1, `Γ[0]` is the refined
value and translates to the symbol `loom.x0`; `Γ[i]` translates to `loom.xi`.
Binders introduced *inside* a predicate (`let`, and `match` arm binders) receive
fresh symbols `loom.b0`, `loom.b1`, … allocated in translation order.

**Sorts.** A type in sort position is first *refinement-erased*: `refine T φ`
becomes the sort of `T`, recursively, including inside data type arguments. A
refinement in an argument position therefore contributes no hypothesis — only
the obligation's own `H` is assumed.

| Loom type | SMT-LIB sort | Notes |
|---|---|---|
| `Unit` | `Loom.Unit` | datatype with the single nullary constructor `loom.unit` |
| `Bool` | `Bool` | Core |
| `I64` | `Int` | idealized; bounded by the domain axiom below |
| `F64` | `Loom.F64` | **uninterpreted**; no arithmetic, only equality |
| `Text` | `Loom.Text` | uninterpreted |
| `Bytes` | `Loom.Bytes` | uninterpreted |
| `data h [A…]` | `Loom.D<sha256-hex>` | datatype, monomorphized (below) |
| `fn`, `cap`, `tyvar`, `forall` | — | **out of fragment; rejected** |

`F64`, `Text`, and `Bytes` are deliberately opaque. Modelling `F64` as `Real` is
unsound for NaN, infinities, and rounding; modelling `Text` as SMT-LIB strings
leaves `QF_UFLIRA`. Values of these sorts may be passed to uninterpreted
functions and compared, and nothing more. Each distinct literal of an opaque
sort becomes a declared constant named `loom.f64.`, `loom.text.`, or
`loom.bytes.` followed by the SHA-256 hex of its canonical payload (the eight
IEEE-754 bytes, the NFC UTF-8 bytes, or the byte string). When a sort has two or
more such constants the script asserts one `distinct` over all of them — the
only fact the encoding claims about opaque literals. Keying the constant on
the literal's raw payload makes `F64` equality in the encoding **bitwise**,
not IEEE-754 numeric equality: `+0.0` and `-0.0` have different eight-byte
payloads, so two such literals are two different constants and are asserted
`distinct` even though `+0.0 = -0.0` under IEEE-754. This is a deliberate
consequence of §4.1's intensional identity, not an oversight — see the design
forks in [the refinement-to-SMT-LIB plan](docs/plans/2026-08-13-refinement-smtlib-translation.md)
for the alternative considered and rejected.

**Data declarations are monomorphized.** An applied data type is refinement-
erased, encoded with the canonical CBOR of §4.2, and named
`Loom.D` + SHA-256 hex of those bytes. `List I64` and `List Bool` are therefore
different sorts, and no parametric `declare-datatypes` is ever emitted. The sort
is declared from its declaration object (§5.1.1) with constructor `i` named
`<sort>.c<i>` and its field `j` named `<sort>.c<i>.f<j>`, both in declaration
order; `self` resolves to the same applied type, so a recursive declaration
closes on its own sort. All sorts reachable from the obligation are emitted in
a single `declare-datatypes` group, sorted bytewise by sort name, which handles
mutual recursion. A constructor field whose type has no sort puts the whole data
type out of fragment.

**Terms.** Only these nodes translate:

| Node | SMT-LIB |
|---|---|
| `var i` | the environment symbol at index `i` |
| `lit unit/bool/i64` | `loom.unit` / `true`,`false` / decimal, negatives as `(- n)` |
| `lit f64/text/bytes` | the opaque literal constant described above |
| `ref h` | `loom.f<hex>` — see interpretation below |
| `app` | a **saturated** application of a `ref` spine: `(loom.f<hex> a₁ … aₙ)` |
| `let T b e` | `(let ((loom.bk b)) e)` |
| `con h i args` | `(<sort>.c<i> args…)`, `h` monomorphic only |
| `match s arms` | SMT-LIB `match`, arms emitted in constructor-index order |
| `if c t e` | `(ite c t e)`; `c` of sort `Bool`, both branches of one common sort |

Every other term node — `lam`, `perform`, `handle`, `fix`, `hole` — is out of
fragment and must be rejected with the path of the offending subterm. So is a
partially applied or higher-order `app`: SMT-LIB has no partial application, and
the fragment is quantifier-free, so an application's head must be a `ref` and
its argument count must equal that reference's arity. A `con` whose declaration
takes type parameters is rejected because the translator synthesizes sorts
bottom-up and has no expected type there. Match arms must be exhaustive,
duplicate-free, and agree on one result sort; emitting them in constructor-index
order makes arm order irrelevant to the emitted bytes. `if` is the one term node
whose translation costs the trusted theory surface nothing: `ite` is already an
admitted interpreted symbol below, so a branching predicate adds no symbol the
allowlist did not already carry.

**References are uninterpreted unless the toolchain says otherwise.** A `ref`'s
Loom type must be resolvable — the translator never guesses one, exactly as the
scope layer never guesses an operation arity (§2.3.1). Its type is uncurried
along the `fn` spine into parameter sorts plus a result sort; **every arrow on
that spine must carry the empty effect row**, since an effectful function has no
meaning as a mathematical function. By default the reference becomes
`(declare-fun loom.f<hex> (<params>) <result>)`, an uninterpreted function: the
solver learns congruence and nothing else, so v0.1 never unfolds a definition
body into a proof.

The toolchain may supply an **interpretation table** mapping definition hashes
to SMT-LIB symbols; it is toolchain policy, never part of a term, so identity is
untouched. The admitted symbols are a closed allowlist — everything a store
could otherwise smuggle into the trusted theory surface stays out:

`not and or => = distinct ite` (Core), `+ - * div mod abs < <= > >=` (Ints).

Each application is checked against that symbol's own signature in addition to
the reference's Loom type, so a misregistered entry is a translation error, not
silent nonsense. Linearity is enforced at the call site: `*` admits at most one
non-numeral factor, and `div`/`mod` require a nonzero integer *literal* divisor.
The `LRA` half of `QF_UFLIRA` is unreachable in v0.1 — there is no `Real`-sorted
base type — and is reserved.

**Script shape.** Commands appear in exactly this order, each on one line, the
file ending in a single newline:

1. `(set-logic ALL)` — the *admitted* fragment is `QF_UFLIRA` + datatypes and is
   enforced by the translator, not by the logic name; no standard SMT-LIB logic
   names that combination, and `ALL` is accepted everywhere.
2. `declare-sort` for each opaque sort used, sorted bytewise.
3. one `declare-datatypes` group, if any datatype sort is used.
4. `declare-const` for `loom.x0…` in ascending index, then for opaque literal
   constants sorted bytewise.
5. `declare-fun` for uninterpreted references, sorted bytewise.
6. `assert (distinct …)` per opaque sort with ≥ 2 literals, by sort name.
7. the **I64 domain axiom** `(assert (and (<= (- 9223372036854775808) loom.xi) (<= loom.xi 9223372036854775807)))`
   for each `Int`-sorted context variable, in ascending index.
8. one `assert` per hypothesis, in order.
9. `(assert (not <goal>))`, then `(check-sat)`, then `(exit)`.

The script asks for a **refutation**: `unsat` means the goal is valid under the
hypotheses and the obligation earns `A3 proof` evidence (§6.1) whose payload
records the solver identity and the script's SHA-256; `sat` refutes the
obligation and the binding is rejected; `unknown`, a timeout, or a term outside
this fragment leaves the obligation undischarged, to be covered by weaker
evidence explicitly. The obligation's name never enters the script, so two
differently named obligations with the same verification condition share one
memo-ledger row (§6.4).

Two fidelity limits are stated rather than hidden. `Int` does not wrap, so a
proof that depends on 64-bit overflow is unsound — the domain axiom bounds
context variables but cannot bound the result of an uninterpreted function or a
datatype field, and a bit-precise encoding would leave the named fragment.
Unbounded intermediate values can also produce a spurious `sat`, which fails in
the safe direction: the obligation simply does not reach A3.

### 3.3 No subtyping surprises

Refinement subtyping (`{x:T|φ} <: T`, and `{x:T|φ} <: {x:T|ψ}` when
`φ ⇒ ψ` is solver-valid) is the only subtyping in the language. No
inheritance, no variance annotations, no coercions.

### 3.4 Crisp by design — where uncertainty lives

It may seem perverse that a language built for a *stochastic* author has no
fuzzy or probabilistic judgments anywhere — no graded truth in refinements,
no confidence-weighted typechecks, no fuzzy numerics in the base types. The
omission is the design's central bet applied consistently: **all gradation
in Loom is epistemic, never semantic.** The system grades how well a crisp
proposition is known (the evidence lattice, §6.1); it never grades the
proposition itself.

Three reasons, in decreasing order of importance:

1. **The referee must not leak a gradient.** The generating agent optimizes
   against the oracle's signal. A graded acceptance — "this checks to
   degree 0.94" — is a reward surface, and reward surfaces get climbed:
   specification gaming would be rediscovered inside the toolchain. A
   two-valued gate with monotone thresholds (§6.3) is the only acceptance
   shape that gives the optimizer nothing to climb at the margin. The
   crispness is not inherited from human-era languages; it is load-bearing
   *because* the author is a sampler — human languages could afford fuzzier
   tooling precisely because the human was the referee.
2. **Content addressing needs crisp equality.** Identity, the memo ledger,
   and replication all hang off byte equality (§4). Fuzzy *values* encode
   fine; fuzzy *equality of terms* has no canonical answer — at what
   similarity do two definitions share evidence? — and every possible
   answer destroys the cached-forever economics of §6.4.
3. **Degrees of truth don't compose canonically.** Fuzzy conjunction is a
   choice among t-norms with no privileged option, so monotone assurance
   across a dependency graph would need a theory the field doesn't agree
   on. Epistemic grading composes by weakest-link, which §6 already does.

Where uncertainty *does* live, deliberately — three sanctioned homes:

- **In the author:** generation is sampling, type-directed masking is soft
  pruning (§8.2), and holes are declared uncertainty (§2.6).
- **In the data:**
  [fuzzy numbers](https://en.wikipedia.org/wiki/Fuzzy_number), intervals,
  and probability distributions are ordinary library ADTs (§2.3) — a crisp
  host carries fuzzy mathematics as *values*, the same way a pure language
  carries effects as data. A measurement pipeline in Loom should absolutely
  compute with `Fuzzy F64`; the *typechecking of that pipeline* stays
  two-valued.
- **In the evidence:** A1 `property` evidence is a statistical claim, and it
  says so numerically — a failure-probability bound at a stated confidence,
  relative to a stated generator (§6.1.1). This is the epistemic dial turned
  up, not the referee turned fuzzy: the *bound* is graded, and the
  accept/refuse decision a policy makes against it stays two-valued, because
  comparing two exact rationals against a threshold is a boolean question. The
  policy object that states such thresholds is §5.3.1, and it is two-valued
  throughout: a requirement is a point in the same lattice, and satisfaction is
  the §6.1.2 comparison.

## 4. Canonical form and identity

### 4.1 Normalization

Before encoding: bound variables are de Bruijn (α-equivalent terms are
byte-identical); metadata is absent by construction (names and prose never
appear in terms); the term is elaborated (§3.1); floats are canonicalized
(§2.2). No β/η normalization — identity is *intensional*: two extensionally
equal implementations are different definitions, because evidence attaches
per implementation.

### 4.2 Deterministic encoding

The encoding is CBOR restricted to the deterministic core of
[RFC 8949 §4.2.1](https://www.rfc-editor.org/rfc/rfc8949.html#section-4.2.1):
definite lengths only, minimal-length integers, map keys sorted bytewise
(maps appear only in store objects, not terms), no tags, no indefinite
forms. One term, one byte sequence.

### 4.3 Identity

A **def object** is `[0, type, term]` (leading `0` is the object-kind tag;
kinds: 0 def, 1 meta, 2 binding, 3 evidence, 4 data declaration, 5 ability
declaration, 6 policy — the tag makes cross-kind hash collisions impossible by
construction). The definition's identity is
SHA‑256 over the def object's encoding.

### 4.4 Worked example (verifiable by hand)

The identity function at `I64` — projection `id : I64 -> I64 = λx. x`:

```
type  = [2, [0,2], [], [0,2]]        ; fn(I64) —{}→ I64
term  = [3, [0,2], [0,0]]            ; lam(I64, var 0)
def   = [0, type, term]

bytes = 83 00                        ; array(3), kind 0
        84 02 82 00 02 80 82 00 02   ; the fn type
        83 03 82 00 02 82 00 00      ; the lam term
```

19 bytes total. `sha256(bytes)` =
`76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605`, so this
definition is `#76c62727` in any projection, in every store, forever.
(Reproduce: `printf '\x83\x00\x84\x02\x82\x00\x02\x80\x82\x00\x02\x83\x03\x82\x00\x02\x82\x00\x00' | sha256sum`.)

## 5. The store

### 5.1 Objects

Append-only. Seven kinds (§4.3). Nothing is ever deleted or garbage
collected in v0.1 — history is the feature (P4), and definitions are small.

#### 5.1.1 Data declarations

A data declaration object is `[4, nominal-key, p, [constructors]]`, where
`nominal-key` is a 32-byte declaration seed, `p` is its type parameter count,
and each constructor is `[field-types]`. Constructor and field
names are metadata; array order defines the constructor index and field binder
order used by `con` and `match` (§2.1, §2.3.1).

Field types use the ordinary type encoding under type depth `p`, extended only
within this declaration by `self = [7, [type-arguments]]`. `self` denotes the
data declaration currently being hashed and must carry exactly `p` arguments.
It is forbidden in definitions, ability declarations, and every other object.
This local form permits recursive data without embedding the declaration's own
not-yet-computable hash. References to other data declarations continue to use
ordinary `data = [1, hash, [type-arguments]]`.

#### 5.1.2 Ability declarations

An ability declaration object is `[5, nominal-key, [operations]]`, where each
operation is `[[parameter-types], result-type]`. Operation and parameter names are metadata;
array order defines the operation index used by `perform` and `handle`.
Abilities are monomorphic in v0.1 because `cap` and effect rows carry an ability
hash without type arguments. Consequently, ability signature types are checked
at type depth 0 and may not contain `tyvar` or declaration-local `self`.

Both declaration kinds are identified by SHA-256 of their deterministic CBOR
encoding, exactly like definitions. A checker resolves nominal hashes to these
objects and must reject missing objects, wrong object kinds, out-of-range
indices, and constructor/operation argument-count mismatches. A `match` node
does not carry a data hash, so checking its constructor indices and
`binder-count` values requires the typechecker to infer the scrutinee's data
type; declaration lookup alone cannot perform that check.

The nominal key distinguishes declarations with identical structure: without
it, for example, equally shaped `spawn` and `ffi` abilities would share a hash
and their capabilities would be interchangeable. It is semantic identity, not
a display name. User/tool-created declarations generate a fresh 32-byte key;
the reference prelude derives reproducible keys as
`SHA-256("loom:v0.1:builtin:" || builtin-name)`.

### 5.2 Meta objects

`[1, def-hash, name-path, spec-text, prov]` — names and prose attach here,
outside identity. This is the D7 concession made structural: the
prior-carrying surface exists, is versioned, and is queryable, but can never
change what a term *is*.

### 5.3 Bindings and namespaces

A binding is `[2, name-path, def-hash, evidence-set, policy-ref, seq]`.
Name-paths live in **namespaces**, each owned by a single writer at a time
(a lease held by one agent or principal) — the store itself needs no
consensus because objects are content-addressed and commutative; only
binding sequences are serialized, per namespace (P6). `policy-ref` points at
the namespace policy the binding was cleared against — the 32-byte hash of a
policy object (§5.3.1), resolved from the name-path per §5.3.2. Where that
policy states an A1 threshold it is a `(bound, confidence, generator)` triple
compared per §6.1.2, not a run count. Rebinding is the
entire edit model: "changing" a function means appending a new definition
and a new binding record with a higher `seq`. Every previous state of every
namespace remains addressable.

#### 5.3.1 Namespace policy objects

A policy object is `[6, policy-map]`. Unlike data and ability declarations
(§5.1.1, §5.1.2) it carries no nominal key: two policies stating the same
constraints *are* the same policy, and should share one hash, one review, and one
domination result (§5.3.2).

`policy-map` is a CBOR map with unsigned-integer keys encoded under §4.2 — keys
sorted bytewise, which for the keys 0–9 below (single-byte encodings) is numeric
order. **An absent key states no constraint**, with one deliberate exception noted
at key 8. A checker that does not recognize a key **rejects the policy object**
rather than admitting it with that key ignored; this is §6.1.1's discipline for
method tags applied to governance.

| Key | Name | Value | Absent means |
|---|---|---|---|
| 0 | `rules` | `[[selector, requirement]…]` | no requirement on any obligation |
| 1 | `require` | `[[detail, statement]…]` | no injected obligations |
| 2 | `max-assumptions` | unsigned integer | no global assumption cap |
| 3 | `max-assumptions-by-ability` | `[[ability-hash, max]…]` | no per-ability cap |
| 4 | `signers` | `[principal-id…]` | A0 accepted from any principal |
| 5 | `writers` | `[principal-id…]` | any principal may hold the lease |
| 6 | `max-lease-millis` | unsigned integer ≥ 1 | no stated lease bound |
| 7 | `max-redraws` | unsigned integer | unbounded redraw budget (§8.3) |
| 8 | `relax` | `1` | **successors must dominate (§5.3.2)** |
| 9 | `statement` | NFC text | no prose statement |

A `principal-id` is a 32-byte string compared bytewise. How a principal proves
possession of one belongs to the A0 payload format, which v0.1 does not specify
(§13). Every array-valued key is non-empty when present, sorted bytewise by its
elements' encodings, and free of duplicate elements; `max-assumptions-by-ability`
additionally has no repeated ability hash, and `require` no repeated detail.

**Obligation ids and kinds.** An obligation id is NFC text (§2.2). It decomposes
at its first `.` (U+002E): the part before is the **kind name**, the part after —
which may itself contain dots — is the **detail**. An id with no `.` has a kind
name and no detail. Kind names form a closed registry:

| Tag | Kind name | Source | Detail |
|---|---|---|---|
| 0 | `ensures` | one per refinement clause (§3.2) | the clause name |
| 1 | `terminates` | one per `fix` (§2.5) | none in v0.1 |
| 2 | `exhaustive-match` | one per `match`; typechecker-discharged, always A3 | none in v0.1 |
| 3 | `property` | injected by a policy (key 1) | the property name |

An obligation whose kind name is outside this registry is rejected, as is a policy
naming a kind tag outside it.

**Selectors, and conjunctive matching.** A selector is `[]`, `[kind-tag]`, or
`[kind-tag, detail]` — a *prefix* of the `(kind, detail)` decomposition — and it
matches every obligation id it is a prefix of. `[]` matches everything, `[0]`
matches every `ensures`, `[0, "isMiddleOf"]` matches `ensures.isMiddleOf` alone.

**Every matching rule applies, conjunctively; there is no precedence and no
most-specific-wins.** An obligation matched by no rule is unconstrained beyond
§6.1's standing requirement that an entry exist — A0 suffices. Two consequences
are the reason for this choice: rule order cannot change meaning, so the canonical
bytewise sort costs nothing semantically; and adding a rule can only ever tighten
a policy, which is what makes domination (§5.3.2) a structural check rather than a
whole-lattice computation. A policy may state two requirements for one obligation;
if they are two A1 requirements over different generators, no single A1 payload
satisfies both (§6.1.2), so that obligation is satisfiable only at A2 or A3. That
is a legal policy, not an ill-formed one.

**Requirements.** A requirement is a point in the assurance lattice:

```
requirement = [level]                             ; level 0 = A0, 2 = A2, 3 = A3
            | [1, bound, confidence, generator]   ; A1
```

`bound` and `confidence` are canonical rationals and `generator` a 32-byte def
hash, exactly as in the A1 payload (§6.1.1). Evidence `E` **satisfies** a
requirement `R` iff `E ⊒ R` under the order of §6.1.2 — the same order §6.3 uses,
so this section introduces no new ordering. An A1 requirement is therefore met by
an A1 entry over the *same* generator with a bound no larger and a confidence no
smaller, or by any A2 or A3 entry; an A0 requirement is met by anything.

The A1 triple is mandatory. §6.1.2 orders A1 payloads only relative to a named
generator, so a bare "at least A1" is not a lattice point it can compare against
and would need an ad-hoc order of its own. A2 and A3 requirements are level-only
in v0.1: constraining an A2 domain would mean thresholding against the A2
payload's domain descriptor, whose format the spec has not given (§13). An
unrecognized level rejects the policy.

**Injected obligations (key 1).** Each entry is `[detail, statement]`, both
non-empty NFC text. It creates obligation `property.<detail>` on every binding the
policy governs, whether or not the definition's author stated anything — this is
what §6.2 calls a policy-required property. `statement` is the human-readable
proposition the evidence is about; the store never interprets it, and its wording
is part of the policy's identity, because the wording is what the principals
adopting the policy adopted. The level demanded is stated the ordinary way, by a
rule with selector `[3, detail]` or a broader prefix; an injected obligation with
no matching rule still needs an entry, and an `A0 assumption` supplies one.

**Assumption budgets (keys 2 and 3).** The **assumption set** of a candidate
binding is the set of `(def-hash, obligation-id)` pairs — over the bound
definition and every def object transitively reachable from it by `ref` (§2.1) —
for which no recorded evidence entry reaches A1 or above. ("Is there an entry
above A0?" stays decidable where A1 payloads over different generators have no
unique maximum.) Its cardinality must not exceed `max-assumptions`. A pair
additionally counts against ability `a` when `a` occurs in any effect row within
that def object's type, and each per-ability count must not exceed its stated
`max`. An `extern` (§11) carries mandatory A0 evidence, so each one contributes at
least one assumption; `max-assumptions: 0` is how a namespace forbids externs and
every other act of faith outright. This is the number §11 promises.

The global cap answers §11's question directly. The per-ability caps exist because
the spec's own axis of danger is the capability set (§2.4) — an unverified `ffi`
or `net` boundary is not the same risk as an unverified numeric routine, and one
global integer cannot say so. Rationing by *obligation kind* is deliberately not
offered: a kind says what proposition is unverified, not what its being wrong can
cost, and a kind-scoped limit is already expressible far more sharply as a rule (a
rule requiring ⊒ A1 on kind 0 forbids A0 on every `ensures` outright).

**Lease keys and the redraw budget.** Key 4 `signers` restricts whose A0 evidence
a governed binding may carry and is checked at admission. Keys 5 and 6 state who
may hold the namespace's write lease and for how long; the lease protocol itself
is open problem 4 (§13), so a store that does not implement leases must **refuse**
bindings governed by a policy stating either key rather than admit them
unenforced. Key 7 is the redraw budget §8.3 names: it constrains the generation
loop, not binding admission — a promoted binding carries no record of how many
redraws produced it — so it is advisory, and it is the only key in the table that
is.

**Example.** A policy requiring every `ensures` obligation to reach A1 with a
failure bound of at most 1/2000 at 99 % confidence under generator `#c1d0…`,
injecting a `no-panic` property that must be proved outright, and permitting no
assumptions anywhere in the transitive closure:

```
[6, {
  0: [ [[0],             [1, [1, 2000], [99, 100], #c1d0…]],
       [[3, "no-panic"], [3]] ],
  1: [ ["no-panic", "Evaluation neither traps nor aborts on any reachable input."] ],
  2: 0
}]
```

#### 5.3.2 Policy resolution, descent, and amendment

`POLICY` is a reserved leaf name in every namespace. A binding whose leaf segment
is `POLICY` targets a policy object (kind 6); every other binding targets a def
object (kind 0), and admission rejects the wrong kind — the object-kind tag makes
that check exact (§4.3). Policies are immutable like every other object, so
amending a namespace's policy means appending a new policy object and rebinding
`POLICY` at a higher `seq`. Policy change is a rebind, which is the same edit model
as everything else.

**Resolution.** The **governing policy** of a name-path is the policy bound at
`POLICY` in the nearest enclosing namespace that has one. For a `POLICY` leaf,
resolution starts **strictly above** its own namespace, so a policy never governs
itself: `stats/median` is governed by `stats/POLICY`, while `stats/POLICY` is
governed by root `POLICY`. Root `POLICY` has no enclosing namespace and is governed
by the **default policy** — the empty policy, which constrains nothing:

```
default = [6, {}]
bytes   = 82 06 a0        ; array(2), kind 6, map(0)
```

Three bytes; `sha256(bytes)` =
`901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c`. It is
preloaded in every store, like the §2.4 prelude. (Reproduce:
`printf '\x82\x06\xa0' | sha256sum`.) Policies therefore form a strict tree by
namespace depth over a concrete base case, and resolution never reads the object
it is admitting; nothing resolves in a circle.

**Admission.** A candidate binding at name-path `p` is admitted only when all of:

1. Its `policy-ref` equals the hash of `p`'s governing policy `G`. A mismatch
   refuses — a proposal that raced a policy rebind is retried against the new
   policy rather than silently cleared under stale rules. What serializes that
   race is the namespace lease (§5.3), whose protocol is open problem 4.
2. Every policy on the chain from `G` upward to the default dominates the policy
   governing it.
3. Its obligation set — those §6.2 generates, plus every obligation `G` injects —
   is complete, and each entry satisfies every rule of `G` matching its id.
4. Its assumption set is within `G`'s budgets, and every A0 entry names a
   principal `G` accepts.
5. It passes §6.3's monotone-assurance check against the previous binding at `p`.
6. If `p`'s leaf is `POLICY`, the descent and amendment rules below.

**Domination.** Policy `Q` **dominates** `P` when it is at least as strict on every
key:

| Key | `Q` dominates `P` when |
|---|---|
| 0 `rules` | for each rule `(s, r)` of `P`, some single rule `(s′, r′)` of `Q` has `s′` a prefix of `s` and `r′ ⊒ r` under §6.1.2 |
| 1 `require` | `Q` injects every detail `P` injects (statements may differ) |
| 2, 3, 6, 7 | wherever `P` states a maximum, `Q` states one no larger |
| 4, 5 | wherever `P` states a principal set, `Q` states a subset of it |
| 8 `relax` | `Q` omits `relax` whenever `P` does |
| 9 `statement` | always — prose is never load-bearing |

Domination is a pure function of two policy hashes, so it memoizes exactly like
§6.4. The `rules` test is **sound but incomplete**: a `Q` at least as strict only
through a *conjunction* of its rules is refused, because an exact test would need
a meet inside A1 across generators that §6.1.2 deliberately does not define.
Merging the rules into one, or stating a strictly higher level, always works, and
the incompleteness refuses in the safe direction.

**Descent.** A policy bound at `n/POLICY` must dominate the policy governing
`n/POLICY`. A descendant namespace can therefore only tighten what an ancestor
states, never escape it — and, more importantly, the object a binding's
`policy-ref` names is then a *complete* statement of everything that binding was
cleared against: one hash, valid forever, needing no replay of an ancestor's policy
history to interpret. The price is that a policy restates what it inherits; literal
inclusion of the ancestor's rules always satisfies the test. Because admission
re-checks the whole chain (step 2), tightening an ancestor that a descendant no
longer dominates **freezes** new bindings under that descendant until its policy is
amended. Nothing is invalidated retroactively, and the freeze is loud.

**Amendment.** A rebind of `n/POLICY` from `P` to `Q` is refused unless `Q`
dominates `P`, or `P` states `relax: 1`. Key 8 is the one key whose absent value is
the restrictive one, deliberately: if weakening were free by omission, §6.3's
guarantee would be defeatable in two individually-passing steps — rebind the policy
to `[6, {}]`, then rebind everything at A0. Since a `Q` omitting `relax` dominates
a `P` stating it, a namespace may ratchet from amendable to permanent but never
back.

A namespace can therefore ratchet itself into a policy nothing satisfies. That is
affordable here and would not be elsewhere: definitions are shared by hash, so
re-binding the same content under a fresh namespace copies nothing, and a fresh
namespace is a *visible fork* rather than a silent erosion of the name that already
exists — which is precisely what §6.3 protects.

**Effect on existing bindings: none.** Bindings are immutable records in an
append-only store, and each one's `policy-ref` records what it was cleared against
and stays true. A new policy governs future bindings only; combined with §6.3,
assurance on any given name then only ever rises, because the next rebind must both
satisfy the new policy and carry evidence ⊒ the old. A projection may render a
binding whose `policy-ref` is not the current governing policy as **stale** — a
review surface (§9), not a refusal.

### 5.4 The draft region

Definitions containing holes live under the reserved namespace `draft/`.
Bindings outside `draft/` may not reference any definition that transitively
contains a hole. Drafts are where the generation loop iterates (§8.3);
promotion out of draft is atomic with obligation checking.

## 6. Evidence

### 6.1 Kinds and the assurance lattice

An evidence object is `[3, obligation-id, kind, payload, result]`. Kinds:

| Level | Kind | Payload | Meaning |
|---|---|---|---|
| A3 | `proof` | checked derivation (solver certificate or proof term) | holds for all inputs |
| A2 | `exhaustive` | domain descriptor + enumeration digest | holds on the entire (finite) stated domain |
| A1 | `property` | sampling record + failure-probability bound (below) | fails with probability at most `p`, at confidence `c`, under generator `g` |
| A0 | `assumption` | principal signature + justification text | trusted, unverified |

Every obligation on a binding carries exactly one evidence entry; `A0` is
legal but loud (every projection renders assumptions in front of everything
else). The lattice grades *knowledge of* a crisp proposition, never the
proposition itself — this is the only kind of gradation the system permits
(§3.4).

#### 6.1.1 The A1 payload

The `property` payload is a seven-element array in canonical field order,
encoded under the deterministic CBOR rules of §4.2:

```
payload = [generator, seed, runs, failures, bound, confidence, method]
```

- `generator` — the 32-byte hash of the def object (§4.3) that produced the
  draws. It identifies the *distribution* the bound is relative to; the
  generator's own type fixes the sampled domain. Identity here is intensional
  (§4.1): two extensionally equal generators with different hashes are
  different generators, and evidence under one says nothing about the other.
- `seed` — unsigned integer, the seed the generator was driven with. Together
  with `generator` and `runs` it makes the run reproducible byte for byte.
- `runs` — unsigned integer `n ≥ 1`, the number of draws taken.
- `failures` — unsigned integer `k ≤ n`, the number of draws on which the
  property did not hold.
- `bound` — a canonical rational `[numerator, denominator]`: an upper bound on
  the per-draw failure probability under `generator`'s distribution.
- `confidence` — a canonical rational `[numerator, denominator]`: the
  confidence level at which `bound` holds (e.g. `[99, 100]`).
- `method` — unsigned integer naming the estimator family that relates
  `(runs, failures, confidence)` to `bound`. v0.1 defines exactly one:
  `0` = Clopper–Pearson exact binomial upper bound. All other values are
  reserved; a checker that does not recognize a method tag **rejects the
  evidence object** rather than admitting it at a degraded level.

A **canonical rational** is `[num, den]` with `den ≥ 1`, `0 ≤ num ≤ den`, and
`gcd(num, den) = 1`, each encoded as a minimal-length unsigned integer. Floats
never appear: payload bytes are hashed into the memo-ledger key (§6.4), so a
probability must have exactly one encoding per value.

Evidence supporting an obligation has `failures = 0` — obligations are crisp
propositions (§3.4), so a failing draw is a refutation, recorded with a false
`result`, not a weaker positive. For `method = 0` and `k = 0` the bound is

```
p ≤ 1 − (1 − c)^(1/n)
```

A checker recomputes the bound from `(method, runs, failures)` **at the
payload's recorded `confidence`** — confidence is an input to the
recomputation, not a separate quantity compared against it — and **rejects
any payload whose recorded `bound` is smaller than the bound recomputed at
that confidence.** Rounding the bound up is always sound and always
permitted, so a limited-precision implementation stays conservative rather
than becoming non-interoperable. The claim is therefore checkable arithmetic,
not an assertion the producer is trusted on.

`runs` and `seed` remain in the payload as the observation and its
reproduction data. They no longer *rank* evidence on their own: `bound`,
`confidence`, and `generator` do.

#### 6.1.2 Order

Across levels the order is total: `A0 ⊏ A1 ⊏ A2 ⊑ A3`. Within A1 it is
partial. For payloads `P` and `Q`:

```
A1(P) ⊑ A1(Q)  iff  Q.generator = P.generator
                and  Q.bound      ≤ P.bound
                and  Q.confidence ≥ P.confidence
```

with the two rational comparisons taken exactly (cross-multiplied integers, no
float rounding). `A1(Q)` is **strictly stronger** than `A1(P)` when `A1(P) ⊑
A1(Q)` and at least one of the two inequalities is strict. Payloads over
different generators are **incomparable** — neither ⊑ the other — and are never
ordered by run count, sample size, or any other tiebreak.

### 6.2 Obligations

Generated per binding: one per refinement clause (§3.2), one `terminates`
per `fix` (§2.5), one `exhaustive-match` per `match` (discharged by the
typechecker, always A3), plus any policy-required properties (e.g., a
namespace policy may demand a `property.no-panic` obligation on everything it
binds). Obligation ids decompose into a kind and a detail, and the governing
policy states which obligations it injects and what evidence level each
obligation must reach; both are specified in §5.3.1.

### 6.3 Monotone assurance

A rebind of name-path `p` is **refused** unless, for every obligation name
shared with the previous binding, the new evidence level ⊒ the old, using the
order of §6.1.2. New obligations may enter at any level the governing policy
allows — the policy resolved for `p` per §5.3.2, whose rules the new binding must
satisfy in any case (§5.3.1); assurance on what already existed never silently
decreases. This is the
store-level guarantee that regeneration churn cannot erode verification over
time. It is completed by §5.3.2's amendment rule: without a gate on policy
weakening, this check would be defeatable by first rebinding the namespace's
policy to one that demands nothing.

Because A1 is only partially ordered, "not ⊒" now covers two cases, and both
refuse:

- **Weaker.** Same generator, but a larger bound or a lower confidence.
- **Incomparable.** A different generator — including a regenerated generator
  that samples the same domain but hashes differently. The new evidence may be
  excellent; it simply is not a statement about the distribution the previous
  binding was cleared against, and the store will not silently substitute one
  for the other.

Both cases are escapable the same way, and only upward: supply an entry at a
strictly higher *level* (A2 or A3, which are comparable to every A1 payload),
or re-run the old generator to produce a comparable A1 payload alongside the
new one. The refusal is a two-valued gate on numeric inputs (§3.4): the bound
is graded, the decision is not.

### 6.4 The memo ledger

Evidence is keyed by `(def-hash, obligation-id, payload-hash)`. A result,
once recorded, is valid forever — content addressing makes cache
invalidation a non-problem, and in a regenerate-heavy workflow (P4) the
ledger converts verification cost from per-change to per-novel-definition.

## 7. Provenance

The `prov` field of a meta object: requesting principal, generating model
identifier, prompt hash, parent-definition hash (what this regeneration
replaced), timestamp. `why #9c31…` resolves intent without archaeology;
`lineage p` walks a name's rebind history with the spec text of each step.
Provenance is metadata: it can be wrong without making the term wrong, and
its trust level is exactly the signing principal's.

## 8. Generation protocol

### 8.1 Emission order

An agent emits a definition as the pre-order traversal of its canonical
encoding — i.e., it streams the CBOR bytes tag by tag. There is no textual
intermediate at any point. (§8.4 relaxes the *byte* part for current
models: the stored form is normative, the emission form is not.)

### 8.2 The mask

At each emission step the toolchain computes the set of admissible next
tokens and masks the rest of the vocabulary:

- **Syntactic masking (guaranteed):** only tags/values that can extend a
  well-formed encoding are admissible. Malformed CBOR and unknown tags are
  unsampleable. The class "syntax error" does not exist (P1).
- **Type-directed pruning (best effort):** the current goal type further
  prunes tags — a goal of function type admits `lam`/`ref`/`var`/`app`…;
  a `ref` position admits only hashes whose definitions inhabit the goal;
  a literal position admits only the goal's literal kind; an `if` condition is
  the one position in the language with a *constant* goal type (`Bool`, §3.1.4),
  and both of its branches inherit the `if`'s own goal. This is pruning,
  not a guarantee: full type-directed masking is undecidable with
  refinements, so refinement failures surface at check time, not decode
  time. The spec is honest about which side of the line each check is on.

### 8.3 The narrowing loop

The intended authoring cycle: **draft → check → narrow.** The agent emits a
draft, placing `hole` nodes wherever its uncertainty is high; the oracle
typechecks and returns, for the first failure, the *smallest unsatisfiable
constraint* localized to a subtree; the agent regenerates only that subtree
(a new draft def sharing every other node by hash). Redraw budget is a
policy knob (§5.3.1 key 7, advisory: it binds the loop, not the admission
gate). Promotion out of `draft/` runs the full obligation set (§6.2)
and is atomic.

### 8.4 Feasibility on 2026 decoders

Could an agent write valid Loom under constrained decoding *today*?
Mostly yes — each mechanism maps to a demonstrated technique — with one
honest amendment to §8.1.

- **Grammar masking is commodity.** The term/type grammar (§2) is a small
  pushdown grammar, the same class as the JSON-schema and CFG constraints
  that [llama.cpp GBNF](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md),
  [Outlines](https://github.com/dottxt-ai/outlines), and
  [XGrammar](https://github.com/mlc-ai/xgrammar) enforce token-by-token in
  production, and that hosted APIs expose as structured outputs. The
  "syntax errors are unsampleable" guarantee is buildable now.
- **Scope and arity need a stateful mask.** "`var` index < binder depth"
  is context-sensitive — beyond off-the-shelf CFG engines, but a small
  custom logit processor on any open-weight serving stack: the masker
  tracks the traversal stack and binder depth. Hosted APIs that expose
  only declarative grammars cannot express this today; open-weight
  serving can.
- **Type-directed pruning has research precedent at exactly this tier.**
  [Synchromesh](https://arxiv.org/abs/2201.11227) enforced semantic
  constraints incrementally during decoding, and
  [type-constrained decoding](https://arxiv.org/abs/2504.09246)
  (Mündler et al.) enforces well-typedness on generated TypeScript via
  prefix automata plus a search over inhabitable types, halving
  compilation errors on models past 30 B parameters. Loom's §8.2 pruning
  tier is this technique pointed at a smaller, closed grammar — easier,
  not harder. Refinement-aware masking at token cadence remains out of
  reach, as §8.2 already concedes.
- **`ref` selection is trie-constrained retrieval.** A 32‑byte hash spans
  many tokens; the mask restricts to a precomputed typed candidate set
  and forces the chosen hash's remaining bytes through a prefix trie —
  the [GENRE](https://arxiv.org/abs/2010.00904) technique for constrained
  entity decoding, with the store index as the entity catalogue.
- **The amendment: emission form ≠ stored form.** Raw CBOR bytes are the
  wrong surface for byte-fallback BPE models — a model emitting `83 03…`
  has near-zero priors over every choice, and priors are the performance
  budget (P3, D7). The relaxation: the agent emits any *deterministic
  isomorph* of the canonical encoding — in practice a canonical
  S-expression surface whose tokens are the prior-rich names and keywords
  of §9's projections — and the toolchain transcodes to canonical bytes.
  Every guarantee survives, because the transcoding is total and
  deterministic and the isomorph is itself mask-generated with zero
  stylistic freedom; no free-form text ever exists, and hashing and
  identity are untouched. The isomorph is not an engineering compromise;
  it is the prior-delivery mechanism D7 predicted the design would need.
- **What masking cannot buy: competence.** Constraint guarantees validity
  while measurably distorting output quality when the format is alien to
  the model ([format-constraint effects](https://arxiv.org/abs/2408.02442)),
  so a masked model with no Loom corpus produces well-formed, well-scoped,
  type-plausible junk. Validity today; fluency only after the bootstrap
  problem (§13.1) is paid down.

## 9. Projection

Projections render store content for a reader; the projection grammar used
in this spec's examples (and the sketch's `median`) is normative for
*rendering only*. Rules:

- Names come from meta objects; a def with no meta renders as its hash.
- `var` indices render as generated names scoped to the definition.
- Effect rows render as `{a, b}` after the arrow; empty row renders as
  nothing (purity is the unmarked case).
- Evidence renders as one line per obligation, level first, `A0` first of
  all — assumptions are never below the fold.
- **No projection is parseable.** There is no grammar for authoring Loom as
  text, by anyone. Humans participate by reading projections, writing
  policy (§5.3.1), signing assumptions (§6.1), and approving promotions —
  the review surface, not the authoring surface.

The same projection machinery serves generating models their context: the
interface-only view (types + contracts + specs of candidate `ref` targets,
bodies withheld — sketch D3) is a projection with a visibility rule. The
model's working view and the human's reading view are one mechanism (D7).

## 10. Multi-agent operation

Objects replicate freely (content-addressed, commutative — the store is a
grow-only set and needs no coordination). Binding writes serialize per
namespace via the lease (§5.3). Two agents wanting the same namespace is a
scheduling problem, not a merge problem; there are no merge conflicts
because there is no text. Cross-namespace atomicity (bind `p` and `q`
together or not at all) is provided by a binding-group record and is the
only transactional primitive.

## 11. The boundary (FFI)

An `extern` definition wraps a foreign artifact (a WASM component in v0.1,
pinned by its own content hash) with a Loom type, a required capability set,
and mandatory `A0 assumption` evidence signed by a principal — the language
does not pretend to verify what it didn't check. Policy can quarantine:
namespaces may forbid transitive `assumption` evidence above a count — a global
cap and per-ability caps, §5.3.1 keys 2 and 3 — which
makes "how much of this system is faith?" a query with a number for an
answer. Compilation of Loom itself targets
[WASM](https://webassembly.org/) through a pipeline that is, aspirationally,
verified — the bottom layer of the essay's stack, reached without ever
passing through unverifiable text.

## 12. Worked example — `median`, end to end

Projection of the bound state after promotion (definition `#9c31…` under
name `stats/median`, policy `stats/POLICY` requiring, on ensures, A1 evidence
with bound ≤ 5 × 10⁻⁴ at confidence ≥ 99 % under generator `#c1d0…`):

```
stats/median : (xs : List F64) -> {x : F64 | isMiddleOf x (sort xs)}
  spec  "Median of the sample; mean of the two middle values for even n."
  prov  principal wbnorris · model claude-fable-5 · prompt #e4a2… · replaces #77d1…
  obligations
    exhaustive-match   A3 proof        (typechecker)          memo #b02f…
    terminates         A3 proof        (measure: len xs)      memo #40aa…
    ensures.isMiddleOf A1 property     p ≤ 4.61e-4 @ 99%, gen #c1d0…  memo #77b0…
                                       (10_000 runs, 0 failures, seed 0x2f41)
= let s = sort xs in
  if odd (len s)
    then s ! (len s / 2)
    else (s ! (len s / 2 - 1) + s ! (len s / 2)) / 2
```

The branch is an `if` (§2.1 tag 12, §3.1.4), not a `match`: `Bool` is a base
type and only `if` eliminates it.

The policy this was cleared against is a policy object (§5.3.1) bound at the
reserved name `stats/POLICY`, and the binding's `policy-ref` is its hash:

```
[6, {0: [ [[0], [1, [1, 2000], [99, 100], #c1d0…]] ],
     2: 0}]
```

Every `ensures` obligation must reach A1 with a failure bound of at most 1/2000
at 99 % confidence under generator `#c1d0…` (key 0, selector `[0]`), and the
transitive assumption count must be zero (key 2) — which is why the assumption
line below is empty rather than merely short. `terminates` and
`exhaustive-match` match no rule, so the policy demands nothing of them beyond
§6.1's requirement that an entry exist; here both happen to be A3. `stats/POLICY`
itself is governed by the root policy, or by the default policy `#901f33bd` if
the root has none (§5.3.2).

What the store actually holds: one def object (term + type, hashed), one
meta object (name, spec, prov), one binding under `stats/` with three
evidence entries, three memo-ledger rows, and — bound once and shared by every
name in the namespace — the policy object above plus its own `stats/POLICY`
binding. The recorded bound is the
Clopper–Pearson value for 10⁴ zero-failure draws at 99 % (4.6041 × 10⁻⁴),
rounded up to the canonical rational `[461, 1000000]`; the payload's stored
form is `[#c1d0…, 0x2f41, 10000, 0, [461, 1000000], [99, 100], 0]`. A later
agent that regenerates `median` must supply evidence ⊒ this entry on
`ensures.isMiddleOf` — same generator with a bound no larger and a confidence
no smaller, or A2/A3 — or its rebind is refused (§6.3); a run under a
*different* generator, however large, is incomparable and also refused. A
human reviewing this sees every assumption the system is making about it —
here, none.

## 13. Non-goals and open problems

**Non-goals (v0.1):** human text authoring (permanently); macros/staging;
performance model and codegen quality; a standard library beyond builtins;
IDE affordances.

**Open problems, inherited from the sketch and not solved by rigor:**

1. **Prior starvation — bootstrap begun.** The mask guarantees
   well-formedness, not competence; until a corpus exists, models will inhabit
   these types poorly. The bootstrap plan (transpile verified existing code, keep
   D7's natural-language surface rich) now has a first tranche on disk: the
   [bootstrap-corpus plan](docs/plans/2026-08-13-bootstrap-corpus.md) selects
   Unison base as the primary source, states the mapping losses, and lands four
   hand-transpiled definitions as validated fixtures under `prototype/corpus/`,
   with the (spec-text, canonical-surface) pairs §8.4 needs read off a §5.2
   meta-object table. Transpiling the seed set surfaced three limits of v0.1 as
   residue for this spec rather than corpus problems; two are now answered by
   [the polymorphism and Bool-elimination plan](docs/plans/2026-08-13-polymorphism-and-bool-elimination.md).
   A *definition* is polymorphic after all: §2.3.1 checks its term at its type's
   `forall` depth (§3.1.3), which costs no tag — what stays open is
   **instantiating** a polymorphic reference, for which v0.1 has no rule, so a
   generic definition is called only through a monomorphic one. `Bool` gained an
   elimination form, `if` (§2.1 tag 12, §3.1.4), the one tag either decision
   spends. Still open: §11's `extern` has no object encoding among §4.3's seven
   kinds, so the arithmetic the corpus assumes cannot yet be stored. Fluency
   remains unmeasured — a seed set is not a result either.
2. **Oracle regress.** Refinements and properties must be authored;
   a wrong contract verifies a wrong program at level A3. Loom shrinks the
   trusted surface to contracts + policy and makes it enumerable
   (`assumption` counting, §11) — smaller and visible, never zero.
3. **Type-directed masking depth** (§8.2) — how much pruning is
   affordable per token is an empirical systems question.
4. **Lease granularity** (§5.3) under high agent counts.
5. **Intensional identity** (§4.1) means semantically identical
   definitions duplicate evidence effort; an extensional-equality memo
   layer is future work.
6. **Confidence-quantified evidence — partially resolved.** The A1 payload
   now carries an explicit bound, confidence, and generator (§6.1.1), ordered
   as a partial order (§6.1.2) that §6.3 refuses on both weakening *and*
   incomparability. What remains open: (a) the **namespace policy object** is
   now specified — its format in §5.3.1, its resolution, descent and amendment
   in §5.3.2 — and what that leaves open is narrower: the **A0 payload's own
   encoding**, so a policy's `signers` set compares 32-byte principal
   identifiers the spec never says how a principal proves possession of; the
   **A2 payload's domain descriptor**, which is why an A2 requirement is
   level-only; **obligation-id disambiguation** when one definition holds
   several `fix` or `match` nodes; the fact that policy **domination is a
   sound-but-incomplete** single-rule test that refuses some genuinely
   at-least-as-strict successors; and **atomic policy-plus-binding change**,
   which would need §10's binding-group record extended across a `POLICY` name.
   Policy keys 5 and 6 state what a policy demands of a lease but not how it is
   enforced — that stays open problem 4; (b) **generator
   comparability** — incomparability across generators is sound but blunt,
   and there is no way to say one generator dominates another (stochastically
   or by coverage) short of re-running the old one; (c) **method families
   beyond Clopper–Pearson**, notably bounds for non-i.i.d. or adaptive
   generators, and any sound way to *combine* independent runs into one
   payload; (d) **shrinking and counterexample locality** — a refutation
   records `failures > 0` but the spec says nothing about carrying the
   witness. None of these reopens §3.4: the bound is graded, the
   accept/refuse decision against policy stays two-valued.

---

*Companions:
[design sketch](docs/investigations/2026-08-12-loom-agent-native-language-sketch.md) ·
[essay analysis](docs/investigations/2026-08-12-english-as-source-code-analysis.md)*
