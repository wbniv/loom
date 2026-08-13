# Plan — Namespace policy object

**Date:** 2026‑08‑13
**Status:** Implemented and verified locally
**Depends on:** SPEC.md §4.3 (object kinds), §5.3 (bindings, `policy-ref`), §6.1.2
(assurance order), §6.2 (obligations), §6.3 (monotone assurance), §11 (assumption
counting), §13 open problem 6(a)

## Objective

Close §13 open problem 6(a). `policy-ref` (§5.3), "the level the policy allows"
(§6.3), "policy-required properties" (§6.2), "namespaces may forbid transitive
`assumption` evidence above a count" (§11) and "redraw budget is a policy knob"
(§8.3) are all normative uses of an object the spec never defines. Nothing in the
store can be implemented against them: §6.3's monotone-rebind gate has no policy
to read, and §12's `stats/POLICY` names a thing with no contents.

Specify the **policy object** — its kind tag, its deterministic CBOR shape, how it
selects obligations, what a required-evidence entry is, how assumption budgets are
stated, how a `policy-ref` is resolved without circularity, and what happens to a
namespace when its policy is rebound.

Out of scope, deliberately: the lease acquisition/renewal/expiry **protocol**
(§13 open problem 4) — this change specifies lease-related *fields a policy states*
and nothing about how they are enforced; and generator comparability (open problem
6(b)).

No visible surface (normative spec text only), so this plan carries no mockups.

## Rules

### R1 — A policy is a new store object kind (tag 6), not a def object

Kinds are what make cross-kind hash collisions impossible by construction (§4.3),
and a policy is store-governance data, not a term: it never appears in a type, an
effect row, or the decoding mask (§8.2). **Rejected:** encoding a policy as a def
object of a prelude `Policy` data type. That would make reading a policy require
*evaluating* a Loom term inside the binding-admission gate, and would put a
governance schema into the mask table that §2 keeps deliberately closed.

Consequently §4.3's kind list gains `6 policy` and §5.1's "Six kinds" becomes
"Seven kinds".

### R2 — The body is a CBOR map with unsigned-integer keys; absent means unconstrained

§4.2 already sanctions maps in store objects ("maps appear only in store objects,
not terms") and nothing has used one yet. A policy is mostly *optional
constraints*, and a map gives the exactly-right reading: **a constraint the policy
does not state is a constraint that does not apply**. It also makes the reviewer's
job (§9) local — what is not written is not enforced — and it makes the empty
policy `[6, {}]` a real, three-byte, hashable object rather than a special case.

**Rejected:** a fixed-arity array like every other kind. Nine mostly-optional
fields in a positional array forces either null padding (which §2.2 explicitly
refuses — "`v` is omitted, not null-padded") or arity overloading at nine
positions, and neither reads.

The object stays a kind-tagged *array* wrapping the map — `[6, policy-map]` — so
§4.3's tag discipline is uniform across all seven kinds.

**One key breaks the absent-means-unconstrained rule, on purpose:** key 8 `relax`
(R7). Making the safe configuration the one an author must remember to write would
let §6.3's whole guarantee be defeated by omission.

### R3 — Selectors are prefixes of an obligation id; matching rules conjoin

An obligation id is already, in §12's rendering, `kind` or `kind.detail`
(`terminates`, `ensures.isMiddleOf`). A policy selector is the array `[]`,
`[kind-tag]`, or `[kind-tag, detail]` — a **prefix** of that decomposition — and
it matches every obligation id it is a prefix of. Kinds are numeric tags over a
closed registry (`0 ensures`, `1 terminates`, `2 exhaustive-match`, `3 property`),
the same discipline as §6.1.1's method tags, and an unrecognized tag is rejected
rather than admitted at a degraded level.

**All matching rules apply, conjunctively.** There is no precedence table and no
most-specific-wins. Two consequences make this the right choice: rule order cannot
change meaning (so the bytewise-sorted canonical encoding costs nothing
semantically), and **adding a rule can only tighten a policy**, never loosen one —
which is what makes the domination test of R7 a simple structural check rather
than a whole-lattice computation.

**Rejected:** most-specific-wins. It needs a total specificity order, and it lets a
narrow rule *weaken* a broad one, which breaks monotonicity under rule addition.

**Rejected:** computing the least upper bound of the matching requirements. A lub
inside A1 does not exist in general — §6.1.2 makes payloads over different
generators incomparable — whereas plain conjunction ("satisfy every matching rule")
is always well-defined. A policy that states two A1 requirements under different
generators for one obligation is therefore satisfiable only by A2 or A3. That is a
legal, meaningful policy, not an error, and it needs no extra machinery to say so.

**Scoping decision:** this change does *not* respecify the obligation-id field of
the evidence object (§6.1) or the memo-ledger key (§6.4). It states only the
lexical decomposition §12 already renders, so the concurrent §3.2 work on
refinement obligations is untouched. Disambiguating several `terminates` or
`exhaustive-match` obligations within one definition stays open (R9).

### R4 — A requirement is a point in the §6.1.2 lattice, and A1 requirements must carry the full triple

`requirement = [level]` for A0/A2/A3, and `[1, bound, confidence, generator]` for
A1. Satisfaction is exactly `E ⊒ requirement` under §6.1.2 — no new order is
introduced anywhere in this change. That single reuse serves three jobs: rebind
monotonicity (§6.3), policy satisfaction (§5.3.1), and policy domination (§5.3.2).

The A1 triple is **mandatory**, not optional. §5.3 already fixed what an A1
threshold means — "a `(bound, confidence, generator)` triple compared per §6.1.2,
not a run count" — and a bare "at least A1" is not a point §6.1.2 can compare
against, since every A1 comparison starts by requiring generator equality. A
requirement that is not a lattice point would need its own ad-hoc order.

A2/A3 requirements are **level-only** in v0.1: constraining an A2 domain would mean
thresholding against the A2 payload's domain descriptor, whose format the spec has
never given (§6.1 says only "domain descriptor + enumeration digest"). Stated as
residue rather than invented here.

### R5 — Assumption budgets are a global cap plus per-ability caps

§11 wants one number ("how much of this system is faith?"), so key 2
`max-assumptions` is a global cap over the transitive `ref` closure. But the
spec's own axis of *danger* is the capability set (§2.4: "the dynamic blast-radius
bound"), so key 3 adds per-ability caps keyed by ability hash — an unverified
`ffi` or `net` extern is not the same risk as an unverified numeric routine, and a
single global number cannot say so.

An assumption is a `(def-hash, obligation-id)` pair for which **no** recorded
evidence entry reaches A1 or above. That phrasing is decidable even though A1
payloads under different generators have no unique maximum: "does any entry exceed
A0?" is a boolean question. A pair counts against ability `a` when `a` occurs in
any effect row of the def's type.

**Rejected:** per-obligation-kind caps. The obligation kind says *what* proposition
is unverified, not how much damage its being wrong can do — and a kind-scoped
limit is already expressible far more sharply as a rule (a rule requiring ⊒ A1 on
kind 0 forbids A0 on every `ensures` outright, rather than rationing it).

### R6 — `policy-ref` is a content hash; resolution walks strictly upward and bottoms out at a pinned default

`policy-ref` is the 32-byte SHA-256 of a policy object's encoding. Policies are
immutable; "changing a policy" is a rebind of the reserved leaf name `POLICY`,
exactly as changing a function is a rebind (§5.3). This is the content-addressing
answer and it needs no new mutability.

The governing policy of a name-path is the policy bound at `POLICY` in the
**nearest enclosing namespace that has one**. The circularity is cut by one rule:
for a `POLICY` leaf, resolution starts **strictly above** its own namespace. So
`stats/POLICY` is governed by root `POLICY`, and root `POLICY` is governed by the
**default policy** `[6, {}]` — a real object with a pinned hash
(`901f33bd…`, three bytes, reproducible by hand like §4.4), preloaded like the
§2.4 prelude. Policies therefore form a strict tree by namespace depth with a
concrete base case, and admission never reads the object it is admitting.

A candidate binding must carry the governing policy's hash in `policy-ref`, and
admission refuses on mismatch. That makes the check a compare-and-set: a proposal
that raced a policy rebind is refused loudly and retried against the new policy,
rather than being silently cleared under stale rules. What serializes the two is
the namespace lease (§5.3) whose protocol is open problem 4.

**Rejected:** letting each binding name its own policy with no name resolution.
Every binding could then pick its own lenient policy, and "this namespace is
governed by X" would be unstateable. The name-resolution rule is what makes policy
mandatory rather than self-selected.

**Rejected:** a mutable policy field on a namespace object. There are no namespace
objects — namespaces are implied by name-paths — and §1 puts all mutability in
bindings.

### R7 — Policy amendment is monotone; a descendant policy must dominate its ancestor

Both are the same test, applied on two axes.

**Why gate weakening at all:** if policy weakening were free, §6.3 is decorative.
Rebind `stats/POLICY` to `[6, {}]`, then rebind everything at A0, and every
assurance ratchet in the store is gone in two steps that each individually pass.
So a rebind of `n/POLICY` is refused unless the successor **dominates** the
predecessor — is at least as strict on every key — with the single escape being
key 8 `relax: 1`, declared in the *predecessor* itself. A namespace's owner
chooses the ratchet when they write the strict policy, and a reviewer reading a
policy sees whether it is a ratchet or a suggestion.

**The brick objection, and why it is affordable.** A namespace that ratchets itself
into an unsatisfiable policy is stuck. That is tolerable *here specifically*
because content addressing makes namespace abandonment nearly free: definitions are
shared by hash, so re-binding the same content under a new namespace copies
nothing. And it does not defeat the guarantee — the point of §6.3 is that the name
`stats/median` never silently loses assurance, not that the store forbids lax code
anywhere. A fresh namespace is a visible fork; a silent policy weakening is not.

**Descent.** A policy bound at `n/POLICY` must also dominate the policy governing
`n/POLICY`. This has no `relax` escape (relax is about time, not depth) and it buys
a property worth the cost: the object named by `policy-ref` is a **complete**
statement of what the binding was cleared against, forever, in one hash.

**Rejected:** conjunctive inheritance — computing the effective policy as the union
of every ancestor's rules at admission time. It removes the descent check and the
restatement burden, but it destroys the audit record: `policy-ref` would name only
the nearest policy, and reconstructing what a binding was actually cleared against
would require replaying every ancestor namespace's policy history to that instant.
Ancestors change; the audit must not. The restatement burden is mechanical anyway
— literal inclusion of the ancestor's rules always satisfies domination.

**Ancestor tightening freezes descendants; it does not invalidate them.** Because
domination is re-checked up the chain at admission, a root tightening that a
descendant policy no longer dominates blocks new bindings under that descendant
until its policy is amended. Domination is a pure function of two policy hashes, so
it memoizes exactly like §6.4. **Rejected:** scanning all descendants at
root-rebind time (expensive, and racy across independent leases), and letting the
inconsistency stand until the descendant's next policy rebind (silently applies a
weaker floor than the root states — the exact failure this section exists to
prevent).

**The domination test is sound but incomplete, and refuses in the safe direction.**
Each of the predecessor's rules must be dominated by a *single* successor rule
whose selector is a prefix of it. A successor that is genuinely at least as strict
via a *conjunction* of rules is refused; the amender merges the rules or uses
`relax`. The exact test would need a meet inside A1 across generators, which
§6.1.2 deliberately does not define.

### R8 — Existing bindings are untouched by a policy rebind; the ratchet is per-name and forward-only

Bindings are immutable records in an append-only store (§5.1); `policy-ref` records
what each one was cleared against and stays true. A stricter policy applies to
future bindings only. Combined with §6.3, assurance on any given name then only
ever rises: the next rebind of that name must satisfy the *new* policy and carry
evidence ⊒ the old. A projection may mark bindings whose `policy-ref` is not the
current governing policy as **stale** — a review surface, not a refusal.

### R9 — Unenforceable keys refuse; one key is honestly advisory

§6.1.1 already set the discipline: a checker that does not recognize a method tag
"rejects the evidence object rather than admitting it at a degraded level". The
same applies to a policy — an unrecognized map key, obligation-kind tag, or
requirement level rejects the *policy object*, and a store that cannot enforce the
lease keys (4 `signers` is enforceable, 5 `writers` and 6 `max-lease-millis` are
not, absent open problem 4) must refuse bindings governed by a policy that states
them rather than admit them unenforced.

The exception is key 7 `max-redraws`. §8.3 says outright that redraw budget is a
policy knob, so it belongs here, but it constrains the *generation loop*, not
binding admission — a promoted binding carries no evidence of how many redraws
produced it. It is specified as advisory and labelled as such, rather than left
dangling in §8.3 with no home.

## Work

- [x] Add object kind 6 to §4.3 and change §5.1's "Six kinds" to "Seven kinds".
- [x] Rewrite §5.3's `policy-ref` sentences to point at the new subsections, and
  reserve the leaf name `POLICY`.
- [x] Add §5.3.1 — the policy object: CBOR shape, the ten keys, the obligation-kind
  registry, selectors and conjunctive matching, requirement encoding and
  satisfaction, assumption counting, the worked default-policy constant with its
  pinned hash and reproduce line, and a worked example policy.
- [x] Add §5.3.2 — resolution, descent, amendment, domination, and what a policy
  rebind does to existing bindings.
- [x] Surgical §6.2 edit: point "policy-required properties" at §5.3.1 and give the
  injected obligation its `property.<name>` id form. No restructuring.
- [x] Surgical §6.3 edit: say which policy the gate reads and how new obligations
  are levelled, and cross-reference §5.3.2 for policy rebinds.
- [x] One-parenthetical edits to §3.4 (the policy object is no longer open), §8.3
  (redraw budget's home), §9 (policy authoring points at §5.3.1), §11 (assumption
  count's home).
- [x] Give §12's `stats/POLICY` its actual contents, consistent with the recorded
  evidence and with the example's "here, none" assumption line.
- [x] Narrow §13 open problem 6(a) to the residue and list it.
- [x] Add this plan's row to `docs/plans/README.md`.

## Verification

```sh
task prototype:test
task todo:lint
git diff --check
```

Plus, by hand, the pinned default-policy constant:

```sh
printf '\x82\x06\xa0' | sha256sum
```

Note: `task todo:lint` resolves `../python-tui-lib/scripts/todo-lint.py` relative to
the Taskfile directory, which does not exist from a nested `.claude/worktrees/…`
checkout. The recorded run below invokes the same linter by absolute path; from the
main checkout the `task` form is equivalent.

## Completion criteria

- §4.3 and §5.1 agree on seven object kinds, with `6 policy` among them.
- §5.3.1 states the policy object as a deterministic CBOR shape with a canonical
  key order, a closed obligation-kind registry, and an exactly-specified
  requirement encoding reusing §6.1.2's order.
- §5.3.1 states the assumption budget concretely enough to compute the number §11
  promises.
- §5.3.2 resolves `policy-ref` without circularity and pins a base-case default
  policy whose hash is reproducible from the spec text.
- §5.3.2 says what a policy rebind does to existing bindings and gates weakening.
- §6.2 and §6.3's normative uses of "policy" resolve to §5.3.1/§5.3.2.
- §12's `stats/POLICY` contents are consistent with the `ensures.isMiddleOf`
  evidence recorded in the same example and with its zero-assumption claim.
- §13 open problem 6(a) lists only the residue, and open problem 4 is still open.

## Recorded verification

Run on 2026‑08‑13.

**Result: PASS**

1. `task prototype:test`

    ```text
    test_synthesized_lambda_is_pure_and_cannot_escape_a_handler (test_effects.EffectTypingTest.test_synthesized_lambda_is_pure_and_cannot_escape_a_handler) ... ok

    ----------------------------------------------------------------------
    Ran 65 tests in 0.045s

    OK
    ```

    PASS (tail shown; 65 of 65 tests OK).

2. `task todo:lint` — run as
   `python3 ~/python-tui-lib/scripts/todo-lint.py TODO.md` (see the note above)

    ```text
    /home/will/loom/.claude/worktrees/agent-a549fbbe783ffe3df/TODO.md: clean
    exit=0
    ```

    PASS.

3. `git diff --check`

    ```text
    (no output; exit 0)
    ```

    PASS.

4. `printf '\x82\x06\xa0' | sha256sum`

    ```text
    901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c  -
    ```

    PASS — matches the default policy hash pinned in §5.3.2.
