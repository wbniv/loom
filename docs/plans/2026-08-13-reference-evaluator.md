# Plan — The reference evaluator

**Date:** 2026-08-13
**Status:** Implemented and verified locally
**Depends on:** [Type-directed `fix` and `ref`](2026-08-13-fix-ref-typing.md),
[Bootstrap corpus tranche 3: the effectful slice](2026-08-13-corpus-tranche-3.md),
[Boolean and comparison base externs](2026-08-13-boolean-base-externs.md)
**Enables:** [The obligation pipeline](2026-08-13-obligation-pipeline.md)'s reserved
countermodel-validation rule (§3.2.1); real semantic judging for the
[masked-generation experiment](2026-08-13-masked-generation-experiment.md)'s
held-out tasks.

## Objective

A definitional interpreter for the whole §2.1 term vocabulary — tags 0–12 — that
runs the bootstrap corpus. Until now every layer in `prototype/` decides whether a
term is *well formed*; none of them can say what it *means*. Three things become
possible at once:

1. **Operational meaning for handlers.** §13's residue records that the
   multi-shot handler in `corpus/rand/resample` is "operationally meaningless" in
   the prototype. It stops being so here: the fixture runs, its continuation is
   invoked twice, and both results are combined.
2. **Real semantic judging.** The experiment's held-out tasks are judged today by
   identity match against a corpus fixture. An evaluator lets a *different* term
   with the same behaviour be judged on behaviour.
3. **§3.2.1's reserved exactness rule.** "Substitute the model into the original
   Loom terms and evaluate under the real semantics" needs an evaluator, "which
   v0.1 does not specify". This plan supplies the evaluator. It deliberately does
   **not** implement the rule — that is a separate change to `obligations.py`,
   which this plan does not touch.

The measure of success is concrete: `corpus/list/foldRight` folds a real
three-element list to a real integer, and `corpus/math/abs` at `INT_MIN` returns a
*negative* number.

**Visible surface:** none. This is a library module plus tests; there is no UI,
rendered page, CLI screen, or generated document, so this plan carries no mockups.

## Rules

### R1 — Evaluation is call-by-value, left to right, in encoding order

§2 never states a reduction strategy, so this is a decision, not a reading. It is
forced almost completely by what §2 *does* say:

- The language is pure by default and effects are reachable only through
  `perform` (§2.4). Under call-by-name a `perform` inside an unused argument
  never happens, and one inside an argument used twice happens twice — so the
  *strategy* would decide which effects a program has, and §3.1.2's whole
  premise is that the **row** decides that statically. Call-by-value is the only
  strategy under which the audit surface says what actually occurs.
- `handle` (§3.1.2) checks its operation clauses' continuation at type
  `fn operation-result ambient-row R`. A continuation only has an argument to
  receive if the operation's result is *demanded* at the perform site, which is
  the call-by-value reading.
- §2.5's `terminates` obligation compares the measure of a recursive
  occurrence's argument `k` against the enclosing invocation's. That comparison
  presupposes the argument is a value at the call, not a suspended computation
  whose measure is not yet defined.

Argument order within a node is genuinely arbitrary and is settled the only way
canonical form can settle anything: **field order in the CBOR array**. `app` is
`[4, f, a]`, so the function is evaluated before the argument; `con` and
`perform` evaluate their argument arrays front to back. This is observable —
`corpus/sample/nowAndBytes` is `Pair (perform clock.wallMillis) (perform
rand.bytes 8)` and the rule says the clock ticks first — so the tests pin it.

*Rejected: call-by-need.* Sharing would make the number of effects depend on the
demand pattern rather than the term, which is exactly the property §2.4 sells.
*Rejected: leaving the order unspecified and testing only order-independent
programs.* That converts a decision into a silent trap for the first fixture that
performs twice in one node.

### R2 — Values are closed; five shapes, and no sixth

| Value | Introduced by | Notes |
|---|---|---|
| `Literal(kind, value)` | `lit` | `kind` is §2.2's literal kind, so `Literal(1, True)` and `Literal(2, 1)` can never be confused the way Python's `bool`/`int` can |
| `Constructor(data, index, fields)` | `con` | nominal; `fields` is a tuple in declaration order |
| `Closure(param_type, body, env)` | `lam` | captures its environment |
| `ExternValue(digest, arity, applied)` | `ref` to an extern | curried; calls the host implementation only when saturated |
| `Continuation(frames)` | `handle`, at a perform | §R5 |
| `Capability(ability, label)` | **the harness only** | §R8 |

`f64` values keep their canonical 8 raw big-endian bytes rather than becoming a
Python `float`. Nothing in the assumed base operates on `F64`, so decoding would
buy nothing and would immediately raise the NaN-canonicalization question §2.2
answers at the *encoding* layer. Conservative where §2 is silent.

Every value is immutable (frozen dataclasses, tuples throughout). §R5 depends on
this.

### R3 — Environments mirror §2.3.1's binder order exactly, and nothing else

The environment is a tuple with de Bruijn index 0 at position 0. Every
binder-producing node extends it exactly as §2.3.1 dictates, and the two
non-obvious cases are the ones §2.3.1 spells out because they are non-obvious:

- **match arm:** fields enter in declaration order with the **last field at index
  0** — `env' = tuple(reversed(fields)) + env`.
- **handler operation clause:** parameters in signature order, then the
  continuation at index 0, so the last parameter is at index 1 —
  `env' = (k,) + tuple(reversed(params)) + env`.
- **handler return clause:** the handled result at index 0.
- **`fix`:** the recursive value at index 0 in `body` only; `T` and `measure` are
  *not* under the binder, and `measure` is never evaluated at all (§R9).

`if` binds nothing (§3.1.4). `let` binds only in `body`.

### R4 — The machine is a defunctionalized CEK-style machine over an immutable frame stack

This is the load-bearing decision, and it is made by the handler requirement
rather than by taste. Three candidate architectures:

1. **Direct-style recursive `eval` with a Python exception for `perform`.**
   Simplest by far. Impossible: raising unwinds the Python stack, so the
   computation between the perform and the handler is *gone* by the time the
   handler runs. One-shot at best, and not even that without re-execution.
   Rejected outright.
2. **CPS with Python closures as continuations.** Multi-shot works, because a
   Python closure is re-invocable. Rejected for one specific reason: it welds
   Loom's control depth to CPython's stack. A `foldRight` over a list of a few
   hundred elements exhausts the interpreter's recursion limit and raises
   `RecursionError` — an *incidental* failure that would fire before the fuel
   guard (§R9) ever did, defeating the one property the fuel guard exists to
   provide (a run always ends in a Loom-level diagnosis, never a hang and never a
   host crash).
3. **CEK-style machine: explicit `(control, environment, frame stack)` state,
   one Python loop, frames as a defunctionalized tuple.** Chosen.

What the choice buys, beyond a flat Python stack:

- **A continuation is a tuple slice.** Capturing is `stack[:i]`; invoking twice
  is pushing the same tuple twice. There is no state to copy, because there is no
  mutable state to copy (§R2). The task brief's "multi-shot means captured state
  must be immutable or copied" is discharged by the first disjunct, structurally.
- **Fuel is one counter incremented once per transition** (§R9), so "steps" means
  something precise rather than "Python calls, roughly".
- **Deep handler semantics is one line** (§R5).

The cost is ~13 frame kinds instead of ~13 recursive calls, which is the honest
price and is paid once.

### R5 — Deep handlers; the continuation is a first-class, multi-shot value

`handle a term ops ret` pushes a `_Handle` frame carrying the ability, the
clauses, the return clause, and the environment, then evaluates `term`.

- A value arriving at a `_Handle` frame runs the **return clause** with that
  value at index 0.
- A `perform a i args` with all arguments evaluated scans the frame stack from
  the top for the nearest `_Handle` on ability `a`. Innermost wins, so nested
  handlers on the same ability nest correctly.
- Splitting the stack at that frame, index `i`:
  - the **operation clause** runs on `stack[i+1:]` — the frames *outside* the
    handler. This is what discharges `a` from the row.
  - the **continuation** is `Continuation(stack[:i] + (handle_frame,))` — the
    frames between the perform and the handler, **with the handler frame put
    back**. That re-installation *is* deep-handler semantics: a `perform` in the
    resumed computation is caught by the same handler again.
- Invoking `k v` at a stack `S` yields the state `Apply(v, k.frames + S)`. The
  resumed computation therefore runs, reaches the re-installed handler, passes
  through the return clause, and *returns to the invocation site*. That is
  exactly the type §3.1.2 gives the continuation: `fn operation-result
  ambient-row R`, where `R` is the handler's result type — the continuation
  produces an `R`, not the handled term's `T`.

Worked against the acceptance fixture, `corpus/rand/resample`, whose clause body
is `match (k 0x00) { Pair a b -> match (k 0xff) { Pair c d -> Pair a d } }` over
a handler whose return clause is `\r -> Pair r r`:

| Step | Result |
|---|---|
| `k 0x00` | resumes the (empty) captured computation with `0x00`, hits the re-installed handler, return clause gives `Pair 0x00 0x00` |
| binds | `a = 0x00`, `b = 0x00` |
| `k 0xff` | second invocation of the *same* continuation → `Pair 0xff 0xff` |
| binds | `c = 0xff`, `d = 0xff` |
| result | `Pair a d` = **`Pair 0x00 0xff`** |

The mixed pair is the proof: `0x00` can only come from the first invocation and
`0xff` only from the second, so a one-shot or a re-executing implementation
cannot produce it. This is the plan's acceptance test.

*Rejected: shallow handlers* (do not re-install). §3.1.2 says "the continuation's
row is the outer ambient row, so the handler discharges `a`" — under shallow
semantics a second `perform` in the resumption would escape a handler the type
system has already discharged, which is unsound against the stated rule.
*Rejected: a captured meta-continuation / `callcc`-style whole-machine snapshot.*
Equivalent in power here and strictly heavier: it would capture the outer stack
too, so `k` would abandon its invocation site instead of returning to it, which
contradicts `k`'s function type.

### R6 — Runtime `I64` wraps, two's complement, and the corpus proves it hurts

§3.2.1 states the fidelity limit from the solver's side: "`Int` does not wrap, so
a proof that depends on 64-bit overflow is unsound." The runtime is the other
side of that sentence, and it honours the wrap: `I64.add` and `I64.sub` reduce
their result into `[-2^63, 2^63)` two's-complement.

The consequence is the point. `corpus/math/abs` is
`\x -> if I64.lt x 0 then I64.sub 0 x else x`, and its declared type is
`I64 -> {v : I64 | -1 < v}`. At `x = INT_MIN`:

- `I64.lt INT_MIN 0` is `true`;
- `I64.sub 0 INT_MIN` wraps to `INT_MIN` — **negative**;
- so `abs INT_MIN = INT_MIN`, which **violates the refinement its own type
  claims**.

That is not a bug to fix in the fixture. It is §3.2.1's fifth exactness condition
made executable: the SMT translation gives `I64` the sort `Int`, `-` is on the
list of symbols "whose `Int` meaning departs from `I64`'s wrapping meaning", and
a proof about this definition over `Int` is a proof about a function the hardware
does not implement. The obligation pipeline's reserved countermodel rule is
precisely the machinery that would notice; this evaluator is the half of it that
did not exist. The test carries that cross-reference in its docstring so the
connection is not left to be rediscovered.

*Rejected: raising on overflow.* It would make the evaluator disagree with every
target §11 could compile to, and it would hide exactly the case worth showing.
*Rejected: unbounded Python integers.* Same, and worse — it would silently agree
with the solver's idealization and make the demonstration impossible.

### R7 — The nine assumed-base externs are the evaluator's default table

§5.1.3: an extern has "no body, so it is never unfolded, never evaluated by the
Loom evaluator". The evaluator therefore never *evaluates* an extern; it calls a
host implementation supplied in a table keyed by extern hash. The nine
assumed-base externs ship as `DEFAULT_EXTERNS`, semantics matching
`corpus_registry.SMT_INTERPRETATION`'s claims about them (`+ - = < <= and or
not`), with R6's wrap on the two arithmetic ones. `List.size` is deliberately
uninterpreted for SMT and perfectly ordinary here: it walks the `Cons` spine.

The table is keyed off `corpus_registry.EXTERN_HASHES` by import rather than by a
hand-copied hash list in `interp.py`. Copying pinned hashes creates a second
source of truth that drifts silently on any re-pin; importing cannot. The same
import supplies the `List` data hash `List.size` checks its argument against, so
`List.size` applied to a non-`List` constructor is a path-aware error rather than
a wrong answer. A test asserts the table's key set *equals* `EXTERN_HASHES`'s, in
both directions, so neither a new assumed-base extern nor a removed one can slip
past.

An extern reference's **arity** is read off its declared type's curried `fn`
spine, so partial application works and a saturated call is unambiguous.

### R8 — The evaluator has no ambient authority whatsoever

§2.4: a capability "is introduced only by the runtime at a program entry point,
never constructible in the language". Two consequences, both enforced:

- **Capabilities are minted only by the harness**, through
  `Interpreter.mint_capability(ability)`. No term evaluates to one. A `cap`-typed
  parameter can only ever receive one that the caller passed in.
- **`perform` has no default behaviour.** With no dynamic handler and no entry in
  the caller-supplied `builtins` table, a `perform` is an `UnhandledOperation`
  error naming the ability, the operation and the path — never a silent default,
  never a real clock, never a real socket. The evaluator ships no clock and no
  entropy.

What it *does* ship is stubs the caller must opt into: `scripted_clock`
(a fixed sequence of `wallMillis` answers, `sleepMillis` returning `unit`) and
`seeded_rand` (a seeded byte stream, `bytes n` returning exactly `max(n, 0)`
bytes per §2.4), plus `abi_success` / `abi_failure` constructing §2.4's canonical
`[status, payload]` envelope through `cbor_canonical`. Shipping them in the
module rather than in the test file keeps §2.4's signature and ABI knowledge next
to the rest of the §2 implementation; requiring the caller to pass them in keeps
the authority claim true.

**The capability is not re-checked at runtime.** `perform` carries no capability
operand, so there is nothing to check against; §3.1.2 enforces "a value of type
`cap a` is in the term environment" statically, and R12 is the contract that lets
the evaluator rely on it. Recorded here rather than invented as a dynamic rule.

### R9 — `fix` runs; `measure` is never consulted; fuel bounds every run

§2.5 makes totality an *oracle* obligation, not an evaluation-time one, and
§3.1.5 says the typing rule "discharges no `terminates` obligation". So the
evaluator runs `fix` directly — it binds the recursive value at index 0 and never
looks at `k` or `measure`. `k` names a position for the oracle; evaluation has no
use for it.

That leaves the evaluator exposed to two term shapes it must not hang on: a
`div`-carrying definition (legitimately non-terminating), and a definition whose
claimed measure is wrong. Both are bounded by **fuel**: a caller-set step limit,
one step per machine transition, raising `FuelExhausted` with the path of the
term under evaluation when it runs out. The default is generous
(1 000 000 steps) and every test that expects divergence sets it low. A test
suite must fail, never hang.

The recursive binding is tied with a **write-once cell**: the cell is placed in
the environment, `body` is evaluated, the cell is filled with the result. Since
`body` is a `lam` in every well-formed case (§2.3.1 notes the recursive value is
`k + 1` binders in), the cell is filled before anything can read it; a `fix` whose
body demands the recursive value immediately gets a clean "recursive value used
before it is bound" error rather than a Python `RecursionError`.

### R10 — `ref` evaluates to its definition's value; instantiation is erased

`ref h` resolves in two steps: if `h` is a registered extern, it becomes an
`ExternValue` (§R7); otherwise an injected `reference_term(h)` supplies the
definition's **term**, which is evaluated in the empty environment. This extends
the existing injection pattern — `scope.py` injects an ability arity,
`typecheck.py` injects a reference *type*, and this layer injects a reference
*body* — rather than inventing a store. `DefinitionTermRegistry` mirrors
`definition_types.DefinitionTypeRegistry`: scope-validated on entry, isolated
copies out.

Resolution is **cached per interpreter** and evaluated on the same machine and
the same fuel budget, via a frame rather than a re-entrant call. A definition is
closed and (§3.1.2) "begins with no ambient effects", so its value cannot depend
on where it was referenced from and caching it is sound. A reference cycle is
detected by an in-progress set and reported as `ReferenceCycle`, rather than
being left for the fuel guard to notice slowly. Content addressing makes a real
cycle unconstructible — a body cannot contain its own hash — so that check is
defence against a resolver that lies, and it is tested as such.

One re-entrancy case is real and is handled: §5.1.3 provides for **callback
externs**, so a host implementation may call back into the machine while an outer
run is mid-resolution. The in-progress set is cleared only at the *outermost*
entry, and a nested run gets its own fuel budget — the honest reading, since it
was the host and not Loom that started a second computation.

**Instantiation adds no node (§3.1.3), so it adds no runtime step.** A definition
typed `forall^p T` *is* its type abstraction; there is no `tylam`/`tyapp` pair to
erase because the vocabulary never had one. The value of a quantified `ref` is
simply its body's value. `corpus/maybe/mapPoly` and `corpus/maybe/map` therefore
have literally the same runtime behaviour, and a test asserts that on a real
`Maybe`.

### R11 — Holes are refused with a path

§2.6 lets a term containing holes typecheck and confines it to `draft/`. An
evaluator has no such option: a hole "inhabits its goal type by fiat", which is a
statement about typing with no operational content. `hole` raises
`HoleRefused` naming the path. This is the evaluator's half of §5.4 — draft terms
are the ones you cannot run.

### R12 — Evaluation assumes a checked term, and says so

The evaluator's precondition is that its input passed `typecheck.validate_source`
(and therefore parse, scope and reference validation). It does not re-derive
types, does not re-check exhaustiveness, does not re-check arities, and does not
re-check the capability requirement (§R8). Where a checked term could not reach a
state, the evaluator still refuses rather than guessing — a missing match arm, a
non-function in application position, a wrong-shaped extern argument each raise a
path-aware `EvaluationError` — so a bug in an upstream layer surfaces as a
diagnosis instead of a wrong answer. That is defence in depth, not a second
checker.

*Rejected: re-typechecking inside `evaluate`.* It would double every layer's work
on every run and put a second, weaker implementation of §3 in the tree.

### R13 — The evaluator is not a versioned validation contract

`contracts.py` versions *validation* layers: things with "a public accept/reject
decision and pinned canonical output". The evaluator has neither. Its acceptance
set is "whatever `typecheck` accepted" (R12) and it emits values, not canonical
bytes. Adding it to `CONTRACTS` would make the version number mean something
different for one entry than for the other seven. Left out deliberately, recorded
here so the omission is visibly a decision; if a future differential-testing need
appears, an `evaluator` contract pinning *observable results per fixture* is the
shape to reach for, and it is a separate change with its own bump-rule argument.

### R14 — The mutation budget is two write-once caches, and that is the whole list

Multi-shot resumption is only correct if a captured continuation cannot observe a
different world on its second invocation. The machine's entire mutable surface
is: the recursive-`fix` cell (R9) and the definition-value cache (R10). Both are
**write-once and monotone** — a filled cell never changes, a cached definition
value never changes — so re-running a captured frame tuple is observationally
identical to running it the first time. Environments, values, frames and the
stack are immutable. This is stated as a rule because it is the invariant that
would be quietly broken by, say, adding a mutable counter to the machine for
convenience.

## Deliberate boundary

- The reserved §3.2.1 countermodel-validation rule is **enabled, not
  implemented**. `obligations.py` is untouched.
- No row-polymorphic anything; §3.1.2 already says the prototype requires closed
  rows.
- No real `fsRead`/`fsWrite`/`net`/`spawn`/`ffi` behaviour. §2.4's envelope
  constructors ship; the effects themselves are the caller's to supply, and the
  corpus exercises none of them.
- No tail-call *optimisation* claim beyond what the machine gives for free: the
  frame stack grows with non-tail control, which is correct and bounded by fuel.
- `F64` values are opaque canonical bytes; no floating-point operations exist to
  need them decoded.
- **Runtime paths are bounded.** A path grows as the machine descends and, in a
  tail-recursive loop, never shrinks — so an uncapped path would grow with the
  *step count* rather than with the term, and a long run would spend more memory
  on diagnostics than on values. Past 240 characters the prefix is kept and an
  ellipsis marks the truncation. `contracts.py` already excludes "the path
  strings carried inside errors" from what a version covers, so this costs no
  conformance claim.

## Work

- [x] `prototype/interp.py`: values, environments, the CEK machine, all thirteen
      term tags, deep multi-shot handlers, fuel, path-aware errors.
- [x] The nine assumed-base extern implementations with §R6 wrapping, keyed off
      `corpus_registry.EXTERN_HASHES`.
- [x] `DefinitionTermRegistry` and the `corpus_interpreter()` factory.
- [x] Harness-only capability minting, the scripted `clock`/`rand` behaviours, and
      §2.4's ABI envelope constructors.
- [x] `prototype/test_interp.py` and its wiring into `task prototype:test`.
- [x] `prototype/README.md` rows plus a "Running Loom" narrative section;
      `docs/plans/README.md` row.

## Verification

```sh
task prototype:test
cd prototype && python3 -m py_compile *.py
task todo:lint
git diff --check
```

## Completion criteria

- Every corpus fixture that can be run *is* run, against expected results
  computed by hand, including `foldRight`/`foldLeft`/`append`/`reverse`/`map`/
  `concat`/`flatMap` on concrete lists.
- `corpus/rand/resample` produces `Pair 0x00 0xff`, which is only reachable by
  invoking one continuation twice.
- `corpus/math/abs` at `INT_MIN` returns `INT_MIN`, and the test says why.
- Fuel exhaustion, hole refusal and unhandled `perform` each raise their own
  path-carrying error.
- The default extern table's key set equals `corpus_registry.EXTERN_HASHES`'s.
- Golden identity and every pinned hash still pass; no canonical bytes move.

## Recorded verification

Run on 2026-08-13.

**Result: PASS**

### 1. `task prototype:test`

```text
----------------------------------------------------------------------
Ran 505 tests in 13.763s

OK (skipped=1)
```

`test_interp` contributes 97 of those. The pre-existing suites run 408 and are
unchanged:

```text
$ python3 -m unittest test_roundtrip test_scope test_references test_prelude \
    test_matches test_effects test_fix_ref test_refinements test_obligations \
    test_subsumption test_policies test_externs test_corpus test_instantiation \
    test_contracts test_experiment test_masker
Ran 408 tests in 13.471s

OK (skipped=1)

$ python3 -m unittest test_interp
Ran 97 tests in 0.105s

OK
```

The one skip is pre-existing (the optional solver run in `test_corpus`), not
introduced here. Golden identity and every pinned hash are inside that 408 and
still pass; this change moves no canonical bytes.

### 2. `cd prototype && python3 -m py_compile *.py`

```text
py_compile exit: 0
```

### 3. `task todo:lint`

```text
TODO.md: clean
todo:lint exit: 0
```

### 4. `git diff --check`

```text
diff --check exit: 0
```

### Selected results, for the record

What the corpus actually computes, read off a live interpreter:

```text
corpus/list/foldRight  (\a b -> a - b) 0 [1,2,3]     = 2
corpus/list/foldLeft   (\a b -> a - b) 0 [1,2,3]     = -6
corpus/list/append     [1,2] ++ [3,4]                = [1, 2, 3, 4]
corpus/list/reverse    [1,2,3]                       = [3, 2, 1]
corpus/list/map        (+10) [1,2,3]                 = [11, 12, 13]
corpus/list/concat     [1,2] [3]                     = [1, 2, 3]
corpus/list/flatMap    (\x -> [x,x]) [1,2]           = [1, 1, 2, 2]
corpus/list/lengthNat  [1,2,3]                       = 3
corpus/list/uncons     [7,8]                         = Just (Pair 7 [8])
corpus/rand/resample   under a handler               = Pair 0x00 0xff
corpus/math/abs        -9223372036854775808          = -9223372036854775808
```

The last two lines are the plan's two acceptance criteria: `Pair 0x00 0xff` is
unreachable without invoking one continuation twice, and `abs INT_MIN` being
negative is a definition provable over SMT-LIB `Int` and false on hardware.

### SPEC.md edits

**None.** §2 turned out to be sufficient on every operational point this plan
needed, including the two that looked most likely to be underdetermined:
§3.1.2's continuation type settles deep-vs-shallow handling, and §2.3.1 states
both non-obvious binder orders (match arm, operation clause) explicitly. The one
genuinely unspecified point — argument evaluation *order* — is a decision rather
than an ambiguity, and R1 records it here with the reasoning, in the plan, as
instructed.
