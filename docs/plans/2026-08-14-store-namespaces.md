# Plan — Store namespaces v1: bindings, leases, and policy-gated admission

**Date:** 2026-08-14
**Status:** Built and verified — see [Run log](#run-log) and
[Recorded verification](#recorded-verification)
**Parent:** [Store v0](2026-08-14-store-v0.md) (built), the **approved**
[lease protocol](2026-08-14-lease-protocol.md) (SPEC §5.3.3), SPEC §5.3/§5.3.1/§5.3.2.

## Objective

Give the store its first names: binding records per SPEC §5.3, serialized per
namespace by the §5.3.3 lease protocol, admitted under the governing policy
via the Python oracle. This is the increment the lease design was approved
for; it turns the store from a content-addressed object bag into the thing
SPEC §5 actually describes.

## Rules

### R1 — The lease protocol is implemented exactly as approved

L1–L6 of the lease design, no reinterpretation: `state/leases/<ns>.jsonl`
append-only logs outside object identity; fence numbers strictly increasing
per namespace; `acquire`/`renew`/`release` verbs with lazy expiry, no queue,
refuse-not-clamp on TTL; policy keys 5/6 checked at acquire/renew against
the governing policy; no eviction on mid-lease rebind; `revoke` NOT built
(named future work). `fsck` grows the fourth invariant: logs parse, fences
strictly increase, cached current-lease equals the fold.

### R2 — Bindings are records in the store's state stratum, admitted by the oracle

A binding is SPEC §5.3's `[2, name-path, def-hash, evidence-set, policy-ref,
seq]`. Binding sequences live per namespace beside the lease log
(`state/bindings/<ns>.jsonl`, append-only, `seq` strictly increasing).
`bind` requires the namespace's current unexpired fence and runs §5.3.2's
admission through the Python oracle:

1. `policy-ref` equals the governing policy's hash (resolution per §5.3.2,
   default policy `901f33bd…` preloaded).
2. Chain domination — via `prototype/policies.py`, which already implements
   domination; the oracle entry point composes, it does not reimplement.
3–4. Obligation/assumption checks against the governing policy — via the
   existing policy machinery; v1 scope: what `policies.py` already checks.
5. §6.3 monotone assurance against the previous binding at the path — via
   the existing evidence comparison.
6. `POLICY`-leaf descent/amendment rules.

The Rust side verifies fence, seq monotonicity, and that `def-hash` /
`policy-ref` name objects the store holds (kind-checked: `POLICY` leaf →
kind 6, else kind 0); everything semantic stays with the oracle, mirroring
store v0's admission split.

### R3 — Read API

`resolve <name-path>` (current binding, and `--at-seq` for history),
`names [--ns N]` (enumerate), `history <name-path>` (the append-only truth),
`lease status <ns>`. One-line JSON, misses typed (exit 3), same protocol
discipline as v0.

### R4 — Out of scope

`revoke`; wait queues/fairness; A0 possession-proof (claimed principal-ids
per L6); evidence *object* storage beyond what bindings reference; GC
(bindings now create reachability — note it for the GC plan, don't build);
network service; any Track P validation port.

## Visible surface

CLI one-line JSON per R3; no mockup bundle (machine-consumed lines), noted
per house rule.

## Cost

$0 — local only.

## Work

- [x] Lease log + verbs + fence checks + fsck invariant 4 (R1).
- [x] Binding log + `bind` with oracle admission + kind checks (R2).
- [x] Oracle admission entry point extension in `prototype/` composing
  policies.py / evidence comparison (R2).
- [x] Read API (R3).
- [x] Run log + verification recorded here.

## Run log

### What was built

| path | what it owns |
|---|---|
| [`store/src/names.rs`](../../store/src/names.rs) | name-paths, namespaces, and the one spelling each has on disk |
| [`store/src/state.rs`](../../store/src/state.rs) | the lease and binding logs, the fold that is the truth, and fsck invariant 4 |
| [`store/src/store.rs`](../../store/src/store.rs) | the lease verbs, `bind`, the read API, and the two fsck checks that need the object store |
| [`store/src/oracle.rs`](../../store/src/oracle.rs) | `bind` / `lease` / `policy` over the same subprocess seam |
| [`store/src/main.rs`](../../store/src/main.rs) | `lease {acquire,renew,release,status}`, `bind`, `resolve`, `history`, `names`, `admit-policy` |
| [`prototype/bindings.py`](../../prototype/bindings.py) | §5.3.2's six rules and §5.3.3's keys 5/6, composing `policies.py` |
| [`prototype/store_admit.py`](../../prototype/store_admit.py) | the wire format, the `policy` kind, and the two new subcommands |
| [`prototype/test_bindings.py`](../../prototype/test_bindings.py) | 37 tests over admission, resolution, leases, and the wire format |
| [`store/tests/namespaces.rs`](../../store/tests/namespaces.rs) | 16 end-to-end tests: steps 3–6, plus a real concurrent-acquire race |

### The state stratum as built

```
<root>/state/
  leases/<ns>.jsonl      append-only lease events
  fences/<ns>/<fence>    an empty marker per issued fence
  current/<ns>.json      derived: the fold of the lease log
  bindings/<ns>.jsonl    append-only binding records, seq strictly increasing
  seqs/<ns>/<seq>        an empty marker per claimed binding seq
```

(`seqs/` was added by the seq-claim hardening addendum at the end of this
file; `bindings/<ns>.jsonl`'s row was "seq from 1, no gaps" until then.)

`<ns>` is the namespace percent-encoded into one filename stem (`%` → `%25`,
`/` → `%2F`, root → `%`), so one namespace is one file, enumeration is one
`read_dir`, and no namespace can be shadowed by a directory of the same name.
The alternative rejected was a nested directory tree mirroring the name-path:
it reads better in `ls`, but it makes "namespace `a`" and "namespace `a/b`"
compete for the same inode name, and it turns enumeration into a walk.

### Decisions taken inside the plan's shape

**Fences are issued by the filesystem, not by the fold.** §5.3.3 promises a
store "can never admit two writers". Folding the log and appending an acquire
is a read-then-write, and two processes that both see the same expired lease
both compute fence `n+1`. So a fence is *issued* by `open(…, O_CREAT|O_EXCL)`
on `state/fences/<ns>/<n+1>` — POSIX gives that to exactly one caller — and
only the winner appends. A crash between claim and append burns a fence, which
is harmless because §5.3.3 requires fences to increase *strictly*, not
contiguously. `store/tests/namespaces.rs::simultaneous_acquisitions_of_a_free_namespace_produce_exactly_one_holder`
is the test; with `create_new` swapped for `create` it fails with two holders
at fence 1, which is how we know the claim is load-bearing rather than
decorative. Rejected: an advisory lock file (needs stale-lock recovery after a
crash, and a timeout policy the design does not give) and an `flock` crate
(a dependency R6 caps).

**The oracle decides every policy question, including the lease's.** `acquire`
and `renew` do not read a policy object; they hand the oracle the enclosing
namespaces' current `POLICY` bindings and get back a cleared `policy_ref` or a
refusal naming §5.3.3's reason. The alternative — Rust reading keys 5 and 6 out
of the sidecar's JSON mirror — is one subprocess cheaper per acquire and puts
policy interpretation on both sides of the seam, which is the thing store v0's
R3 exists to prevent.

**Resolution is the oracle's; folding a log is the store's.** The store walks
the ancestor chain and reports "here is each enclosing namespace's current
`POLICY` binding, nearest first". Which of them *governs* — and the strictly-above
rule for a `POLICY` leaf — is §5.3.2 semantics, decided in `bindings.py`.

**Policy objects reach the store as a JSON mirror, hash-checked.** There is no
CBOR decoder in Python (and R6 forbids a CBOR crate in Rust), so `ir_to_json`
grew a map form, `{"m": [[key, value]…]}`, for the one object kind that has a
CBOR map. It is round-tripped and hash-checked at emission exactly as the
declaration mirror already is, so a mirror disagreeing with the encoder cannot
land silently.

**The default policy is preloaded by `init`, through the oracle.** §5.3.2's
resolution terminates at it, so a store without it cannot bind anything. The
bytes are a SPEC literal but the *sidecar* is the oracle's statement of record
like every other sidecar, so `init` asks for it rather than minting one and
inventing contract versions for an object Rust did not validate. `--bare` opts
out, for a store that will never bind. Consequence: a seeded store now holds 48
objects, not 47; the corpus is still 47.

**`export-resolver` filters policy objects out.** A policy is not resolvable as
a term or as a type, so it has no place in a *resolver* document. This is a
filter on which objects appear, not a projection of what each one carries —
store v0's "re-emits whole sidecars" stance is unchanged.

**A binding's evidence-set carries lattice points inline.** §5.3 does not fix
what an evidence-set element is, and R4 puts evidence-*object* storage out of
scope, so v1 stores `[[obligation-id, lattice-point]…]` directly. When the §6.4
ledger lands, the element becomes a hash and this field is where that change
goes.

**Rule 4 refuses rather than under-enforces.** Keys 2, 3 and 4 are not
computable in this increment (see the gap list below), so a binding whose
governing policy states any of them is **refused**, naming the key. §5.3.1
already prescribes exactly this for an unimplemented key — "must refuse …
rather than admit them unenforced" — and it is the only way the gap is loud
instead of silent.

### What §5.3.2 v1 enforces, honestly

| Rule | Status | Note |
|---|---|---|
| 1 policy-ref = governing policy | **full** | resolution incl. the `POLICY`-leaf strictly-above rule |
| 2 chain domination | **full** | `policies.dominates` over consecutive chain entries |
| 3 obligations complete + satisfy `G` | **partial** | injected obligations (key 1) must be present, and every entry present must satisfy every matching rule. Obligations §6.2 *generates* from the definition are not re-derived — that means re-running the typechecker inside admission, a second opinion with no referee |
| 4 assumption budgets + A0 signers | **refused, not enforced** | keys 2/3 need a §6.4 evidence ledger over the transitive closure (R4 out of scope); key 4 needs the A0 payload format (§13, open). A governing policy stating any of them refuses the binding |
| 5 §6.3 monotone assurance | **full** | `policies.satisfies` per shared obligation; distinguishes weaker from incomparable |
| 6 `POLICY` descent + amendment | **full** | including key 8 `relax` and the hash-vs-object check |

Two further narrowings, stated rather than discovered later: §5.4's "bindings
outside `draft/` may not reference a definition that transitively contains a
hole" is not checked (the store has no hole tracking); and NFC normalization of
a name-path is checked by the oracle at `bind`, not by the CLI, so a non-NFC
namespace can hold a *lease* that no binding will ever be admitted under.

## Verification

1. `task store:test` + `task store:lint` green; new lease/binding suites.
2. `task prototype:test` green (oracle extension tested).
3. Two-writer race test: holder A binds; B's acquire refused while held;
   after expiry B acquires with fence+1 and A's late bind is refused by
   fence.
4. Policy gate test: a namespace whose policy states keys 5/6 — acquire by
   a non-writer refused; over-bound TTL refused; a policy *without* those
   keys leases freely.
5. Rebind ladder: bind → policy rebind (dominating) → next bind must carry
   the new policy-ref (stale ref refused per rule 1); a non-dominating
   POLICY rebind refused.
6. `fsck` catches: a tampered lease log (fence regression), a binding whose
   def-hash is absent, a seq gap.
7. `task todo:lint`; `git diff --check`.

## Completion criteria

- The §5.3 sentence is true of this store: objects need no coordination;
  binding sequences are serialized per namespace by the lease.
- A store with no lease implementation refusing keys-5/6 policies is no
  longer this store: it enforces them.
- History is addressable: every previous binding of every name retrievable.

## Recorded verification

Run 2026‑08‑14 on the implementation branch. The numbered steps are the plan's
own, unchanged; raw output follows each.

### 1. `task store:test` + `task store:lint` green; new lease/binding suites

```
     Running unittests src/lib.rs (target/debug/deps/loom_store-20e38a0d1038dd78)

running 36 tests
… (22 v0 tests, unchanged) …
test names::tests::a_name_path_splits_into_a_namespace_and_a_leaf ... ok
test names::tests::the_reserved_leaf_is_recognized_at_every_depth ... ok
test names::tests::the_three_shapes_that_could_escape_a_directory_are_refused ... ok
test names::tests::encoding_is_injective_and_the_root_has_a_stem_nothing_else_can_take ... ok
test names::tests::ancestors_walk_from_the_namespace_up_to_root ... ok
test names::tests::enclosure_is_by_segment_not_by_prefix ... ok
test state::tests::a_binding_line_mirrors_the_spec_array_it_stands_for ... ok
test state::tests::an_empty_log_folds_to_no_lease_rather_than_to_a_default_one ... ok
test state::tests::lazy_expiry_is_a_comparison_and_nothing_else ... ok
test state::tests::the_fold_is_the_last_event_and_a_release_keeps_the_fence ... ok
test state::tests::a_fence_is_issued_to_exactly_one_claimant ... ok
test state::tests::a_hand_edited_fence_regression_is_caught_with_its_namespace_named ... ok
test error::tests::a_lease_refusal_is_its_own_code_and_keeps_the_fields_a_retry_needs ... ok
test error::tests::a_malformed_name_is_a_usage_error_about_a_value_like_a_malformed_hash ... ok

test result: ok. 36 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

     Running tests/integration.rs (target/debug/deps/integration-a43fb1f1eb388b35)

running 21 tests
… all v0 tests …
test result: ok. 21 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.37s

     Running tests/namespaces.rs (target/debug/deps/namespaces-7fd317f3e30d4a82)

running 16 tests
test a_fence_the_namespace_never_issued_cannot_be_forged_into_the_log ... ok
test a_stale_lease_cache_is_a_nuisance_that_reindex_repairs ... ok
test a_released_or_expired_holder_cannot_renew_or_bind_but_the_log_still_shows_it ... ok
test fsck_catches_a_binding_whose_def_hash_is_absent_and_a_seq_gap ... ok
test a_renewal_keeps_the_fence_because_holder_continuity_is_its_point ... ok
test a_policy_the_store_cannot_enforce_refuses_the_binding_rather_than_admitting_it ... ok
test fsck_catches_a_tampered_lease_log ... ok
test monotone_assurance_refuses_a_rebind_that_would_lower_it ... ok
test the_kinds_5_3_2_requires_are_checked_by_the_store_before_the_oracle_is_asked ... ok
test simultaneous_acquisitions_of_a_free_namespace_produce_exactly_one_holder ... ok
test descent_refuses_a_child_policy_that_does_not_dominate_its_ancestor ... ok
test a_policy_stating_keys_5_and_6_is_enforced_and_one_stating_neither_leases_freely ... ok
test the_read_api_answers_by_namespace_and_an_empty_namespace_is_data ... ok
test tightening_a_policy_mid_lease_does_not_evict_the_holder_but_binds_at_the_next_renew ... ok
test two_writers_are_serialized_by_the_fence_and_never_by_the_clock ... ok
test the_rebind_ladder_refuses_a_stale_policy_ref_and_a_non_dominating_amendment ... ok

test result: ok. 16 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 3.96s
```

```
    Checking loom-store v0.1.0 (…/store)
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 0.57s
store:lint exit=0
```

**PASS** — 73 Rust tests (43 before this increment, +30), 0 failures;
`cargo fmt --check` produced no diff and `cargo clippy --all-targets -- -D
warnings` no diagnostics.

### 2. `task prototype:test` green (oracle extension tested)

Run with the seeded store's export present, so the store-equivalence tests ran
against the real Rust-produced document rather than the oracle-synthesized
fallback.

```
----------------------------------------------------------------------
Ran 624 tests in 65.723s

OK (skipped=1)
```

**PASS** — 624 tests (587 before this increment, +37 from `test_bindings`), the
one pre-existing skip, no failures.

### 3. Two-writer race test: holder A binds; B's acquire refused while held; after expiry B acquires with fence+1 and A's late bind is refused by fence

```
running 4 tests
test a_released_or_expired_holder_cannot_renew_or_bind_but_the_log_still_shows_it ... ok
test a_renewal_keeps_the_fence_because_holder_continuity_is_its_point ... ok
test simultaneous_acquisitions_of_a_free_namespace_produce_exactly_one_holder ... ok
test two_writers_are_serialized_by_the_fence_and_never_by_the_clock ... ok

test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 12 filtered out; finished in 3.80s
```

`two_writers_are_serialized_by_the_fence_and_never_by_the_clock` is the step as
written: A acquires (fence 1) and binds `stats/median` at seq 1; B's acquire is
refused `lease_refused`/`held` naming A and A's expiry; A renews down to 150 ms
and the test sleeps past it; B acquires at **fence 2**; A's late bind is refused
`lease_refused`/`fence` reporting `fence: 2, presented_fence: 1`; and the
namespace still holds exactly A's one binding.

`simultaneous_acquisitions…` is the same guarantee under real concurrency —
four processes racing an unleased namespace, exactly one granted. It was
checked against its own negation: with `create_new` replaced by `create` in
`state::claim_fence`, it fails with **two** granted acquisitions at fence 1.

**PASS.**

### 4. Policy gate test: a namespace whose policy states keys 5/6 — acquire by a non-writer refused; over-bound TTL refused; a policy *without* those keys leases freely

```
running 2 tests
test a_policy_stating_keys_5_and_6_is_enforced_and_one_stating_neither_leases_freely ... ok
test tightening_a_policy_mid_lease_does_not_evict_the_holder_but_binds_at_the_next_renew ... ok

test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 14 filtered out; finished in 2.66s
```

The first test binds a root `POLICY` stating `writers: [ALICE]` and
`max-lease-millis: 5000`, then asserts: BOB's acquire → exit 7 reason `writer`;
ALICE at 5001 ms → exit 7 reason `bound`, with the message containing
"clamped" so the refuse-not-clamp rule is asserted and not merely implied;
ALICE at exactly 5000 ms → granted, recording the gating policy as its
`policy_ref`; and a separate store under the default policy granting a
9 999 999 ms lease to BOB. The second test is D2 — a mid-lease tightening does
not evict the holder, and binds at the next `renew`, which re-checks and
refuses `writer`.

**PASS.**

### 5. Rebind ladder: bind → policy rebind (dominating) → next bind must carry the new policy-ref (stale ref refused per rule 1); a non-dominating POLICY rebind refused

```
running 4 tests
test a_policy_the_store_cannot_enforce_refuses_the_binding_rather_than_admitting_it ... ok
test descent_refuses_a_child_policy_that_does_not_dominate_its_ancestor ... ok
test monotone_assurance_refuses_a_rebind_that_would_lower_it ... ok
test the_rebind_ladder_refuses_a_stale_policy_ref_and_a_non_dominating_amendment ... ok

test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 12 filtered out; finished in 5.14s
```

The ladder test walks the step exactly: bind under the default policy (seq 1) →
rebind `stats/POLICY` to a dominating policy (seq 2) → the same bind carrying
the stale ref is refused with `rule 1: policy-ref … is not the governing policy
…; retry against the policy now in force` → the retry under the new ref lands
at seq 3 → a *looser* `stats/POLICY` is refused with `rule 6: amendment: …`.
It then reads the history back: two bindings of `stats/median`, `--at-seq 1`
resolving to the old `policy_ref` and the bare `resolve` to the new one.

The three neighbouring tests cover what the ladder implies: rule 6 descent, rule
5 monotone assurance (an A3 → A0 rebind refused with `rule 5:` and nothing
appended), and rule 4's refuse-rather-than-under-enforce on key 2.

**PASS.**

### 6. `fsck` catches: a tampered lease log (fence regression), a binding whose def-hash is absent, a seq gap

```
running 4 tests
test a_fence_the_namespace_never_issued_cannot_be_forged_into_the_log ... ok
test a_stale_lease_cache_is_a_nuisance_that_reindex_repairs ... ok
test fsck_catches_a_binding_whose_def_hash_is_absent_and_a_seq_gap ... ok
test fsck_catches_a_tampered_lease_log ... ok

test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 12 filtered out; finished in 2.63s
```

All three named cases exit 4 with the problem kinds `lease_fence_regression`
(plus `lease_cache_diverged`, §5.3.3's own wording), `binding_object_missing`,
and `binding_seq_gap`. The binding test restores the log afterwards and asserts
`fsck` is clean again, so the two detections are not firing on something the
fixture always had wrong. Two further cases are covered beyond the step: a fence
forged into the log with no issuing marker behind it (`lease_fence_unissued`),
and a cache lost to a crash between the append and the write, which `reindex`
repairs.

A live transcript of the stratum a clean store writes:

```
.loom-store/state/leases/demo.jsonl
{"event":"acquire","fence":1,"principal":"a1a1…a1","policy_ref":"901f33bd…299c","at_millis":1786744052149,"expires_millis":1786744652149,"ttl_millis":600000}

.loom-store/state/current/demo.json
{"schema":1,"namespace":"demo","fence":1,"principal":"a1a1…a1","policy_ref":"901f33bd…299c","acquired_millis":1786744052149,"expires_millis":1786744652149,"released":false}

.loom-store/state/fences/demo/1

$ loom-store fsck
{"objects":48,"ok":true,"rows":48}
```

**PASS.**

### 7. `task todo:lint`; `git diff --check`

```
TODO.md: clean
todo:lint exit=0
git diff --check exit=0
```

**PASS** — both clean. `TODO.md` is untouched by this increment; promoting the
namespaces item to Done is the orchestrator's call, not this branch's.

### 8. Completion criterion — the default policy is the SPEC's three bytes

Not one of the seven numbered steps, recorded because R2 names the hash
explicitly and a preloaded constant that nobody re-derives is a constant nobody
checks.

```
$ printf '\x82\x06\xa0' | sha256sum
901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c  -

$ loom-store init --from-oracle
{"default_policy":"901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c",…}
```

Also asserted in Python by
`test_bindings.py::ResolutionTest::test_the_default_policy_is_the_three_bytes_the_spec_prints`
(which reproduces the `printf` recipe rather than quoting the constant) and by
`store_admit.default_policy_pair`, which refuses to emit anything else.

**PASS.**

## Addendum 2026-08-14 — claiming binding seq the same way as a fence

The gap this closes: `bind` computed `seq = records.len() + 1` by reading the
binding log, same as `lease_acquire` used to compute a fence from the fold
before the fence-claim marker existed. Two `bind` calls under one held
fence — the same holder, two threads or processes, nothing exotic — can both
read the log before either has appended and both propose the same `seq`.
`fsck`'s old `binding_seq_gap` check found the resulting duplicate after the
fact; it never stopped it from landing.

**The fix** mirrors `state::claim_fence` exactly: `state::claim_binding_seq`
issues a `seq` by `open(…, O_CREAT|O_EXCL)` on `state/seqs/<ns>/<seq>`, and
`Store::bind` (`store/src/store.rs`) claims it right before appending — after
the oracle has admitted the proposal and the fence has been re-checked, so a
refused or fence-losing proposal never burns a `seq`. A claim that loses the
race makes `bind` re-read the log and retry, up to `MAX_BIND_ATTEMPTS` (16,
the same bound `lease_acquire` uses and for the same reason).

**The tension, and the choice.** R2 above already says binding `seq` is
"strictly increasing" — it never said "no gaps". The "seq from 1, no gaps"
wording lived only in the state stratum's own ASCII diagram and doc comments
and in `fsck`'s `binding_seq_gap` check, which enforced contiguity R2 never
asked for. §5.3 itself says a rebind is "a new binding record with a higher
seq" — again "higher", not "next" — and nothing in §5.3 or §5.3.2 ties a
binding's admissibility, its resolution, or its ordering to the *count* of
prior bindings; `resolve`, `history`, and `--at-seq` all key off the `seq`
value itself, not off log position, so a store that skips a burned number
loses nothing SPEC promises. This is choice **(a)**: relax the
implementation (docs, module comments, and `fsck`) to match what R2 already
required, rather than choice (b) (making the claim-and-append atomic enough
that no number is ever burned). (b) was also considered and rejected for the
same reason an advisory lock was rejected for fences in the "Decisions taken"
section above: making claim-then-append atomic across a possible crash needs
either a cross-process transaction the filesystem does not give for free, or
recovery/rollback logic (delete an orphaned claim marker, but only if we can
prove the claimant is really dead) that the design does not otherwise need
anywhere else in this store. (a) costs nothing SPEC asks for; (b) would add
real machinery to buy back a guarantee no one requires.

`fsck` (`store/src/state.rs::check`) now runs the same two checks on binding
`seq` that it already ran on fences: `binding_seq_regression` (a record's
`seq` does not exceed the running highest — catches a duplicate or a
backward jump) and `binding_seq_unissued` (a record's `seq` has no claim
marker behind it — catches a hand-edited or otherwise never-claimed value).
`binding_seq_gap` is gone; a gap alone is no longer a problem.
`store/tests/namespaces.rs::fsck_catches_a_binding_whose_def_hash_is_absent_an_unissued_seq_and_a_seq_regression`
replaces the old gap-detection test with one hand-edit that trips
`binding_seq_unissued` (a renumbering to a `seq` never claimed) and a second
that trips `binding_seq_regression` (a renumbering that repeats an already-
claimed `seq`), and confirms neither check fires on the other's fixture.

**The concurrent-bind test.**
`store/tests/namespaces.rs::concurrent_binds_under_one_fence_never_share_a_seq`
acquires one namespace, then binds four different names under that one fence
from four threads at once. All four are expected to succeed (nothing about
this scenario is refusable — four first-time bindings under the default
policy), and the test asserts their returned `seq` values are exactly `{1,
2, 3, 4}` with no duplicates, then that `fsck` is clean afterward.
Non-vacuity, proved the way the fence test proved it: with the
`claim_binding_seq` call in `Store::bind` short-circuited to never claim
(`if false { continue; }` in place of the real check), the same test run
produces all four binds landing at `seq: 1` — `left: [1, 1, 1, 1], right:
[1, 2, 3, 4]` — confirming the claim is load-bearing, not decorative.

**Verification**, folded into the existing steps rather than re-run as new
numbered ones (nothing above them changed):

```
running 17 tests
...
test concurrent_binds_under_one_fence_never_share_a_seq ... ok
test fsck_catches_a_binding_whose_def_hash_is_absent_an_unissued_seq_and_a_seq_regression ... ok
...
test result: ok. 17 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 4.49s
```

`task store:test`: 77 Rust tests total (39 lib + 21 integration + 17
namespaces, up from 73), 0 failures. `task store:lint`: `cargo fmt --check`
clean, `cargo clippy --all-targets -- -D warnings` clean. `task
prototype:test`: 693 tests, `OK (skipped=3)` — the oracle is untouched by
this addendum, run anyway per the brief. `task todo:lint`: `TODO.md: clean`.
`git diff --check`: clean.

**PASS.**

**Least-certain call.** Whether `binding_seq_regression` can ever have a real
false positive under legitimate concurrency — i.e., whether two records
could ever land in the log out of `seq` order without any tampering, which
would make the regression check itself the bug. Reasoned through rather than
directly tested: `bind`'s candidate is always `records.len() + 1` at the
moment of a fresh log read, and a claim for candidate `n+1` cannot be
attempted until a read observes `n` records — which requires record `n`'s
append to already be durably on disk. So no `bind` can ever land a record
behind one that had not yet been appended when it computed its own
candidate; file order and `seq` order coincide by construction, for
successfully appended records, with or without contention. What this
argument does *not* cover is the same liveness question the fence claim
already carries and that this addendum deliberately leaves alone: a crash
between claiming a `seq` and appending its record permanently blocks that
exact number from ever being reused, and since the next candidate is always
`records.len() + 1` (not the highest *claimed* number), a namespace whose
last bind crashed mid-claim would retry the identical burned `seq` forever
rather than skipping past it. `lease_acquire`'s fence claim has this same
shape (`fence = held.fence + 1`, not `max(claimed) + 1`) and was accepted
that way; this addendum mirrors it rather than silently fixing a
pre-existing, out-of-scope liveness question for fences too. A real crash
mid-claim is colder than the races these tests exercise, and recovering
from it — deciding a claimant is truly dead rather than merely slow, and
only then treating its marker as reusable — is exactly the "recovery logic
the design does not otherwise need" that made choice (b) not worth its cost
above. Flagged here rather than fixed, for a future increment to pick up if
it turns out to matter in practice.

## Addendum 2026-08-14 (2) — the flagged livelock is closed, both kinds

The previous addendum's "least-certain call" is closed for fences and for
binding `seq`. Both had the identical shape: `committed + 1` (the fold's
fence, or the binding log's length, plus one) is recomputed fresh on every
retry, so a crash-burned number — claimed, never appended — is retried
identically forever, in every future call, not just within one call's
attempt budget. `state::next_after_claims` (`store/src/state.rs`) is the
fix: it proposes past whatever the claim-marker directory shows already
claimed, not just past what the log has committed, so a burn is skipped
instead of retried.

**The naive version of this — always consult the claim directory, on every
attempt, for both kinds — was tried and rejected**, not on style grounds but
because it reintroduces exactly the bug the fence claim exists to prevent.
The claim-marker directory can be *ahead* of the log: a marker exists the
instant `claim_fence`/`claim_binding_seq` returns, before the matching event
or record is appended. Proposing from it is therefore a guess about state
that has not landed yet, and for a fence that guess is unsafe: a caller who
has failed several rounds against a **live** (not burned) claimant for
`committed + 1` could leapfrog to a *different*, unclaimed fence while that
claimant is still mid-flight between its own claim and its own append. Both
would then successfully append distinct `Acquire` events — two holders,
which is precisely "can never admit two writers" (§5.3.3) violated. This is
not a corner of the design that was already fragile; it is the one property
the fence claim was built to guarantee, and it was reproducible on demand in
manual testing of the naive version (two threads racing a free namespace,
the second computing its candidate from the first's not-yet-appended
marker) before this addendum's version replaced it.

**Binding `seq` does not have this hazard**, because nothing about a binding
requires exactly one caller to win — `concurrent_binds_under_one_fence_never_share_a_seq`
(the earlier addendum) exists precisely because several concurrent binds
under one fence are *all* supposed to succeed. So `bind` escalates on
**every** attempt (`store/src/store.rs::bind`), fixing the livelock
immediately rather than only as a last resort. What this costs is the log's
file order no longer implying `seq` order under contention — two records can
land with the higher `seq` first — which would have broken
`state::heads`/`Store::resolve`/`Store::history`, all of which used to take
"last in the log" as "current". They now compare `seq` values directly
(`state::heads` is highest-`seq`-per-name-path; `resolve` is `max_by_key`
over eligible records; `history` sorts by `seq` before returning), so which
record the log happens to put last no longer matters to any of them.

**`lease_acquire` keeps the ordinary fold-based candidate for every attempt
but the last** (`store/src/store.rs::lease_acquire`), escalating to
`next_after_claims` only once the normal path has had every other attempt to
resolve on its own — which a live claimant, whose entire remaining work is
one JSON line and an `fsync`, essentially always does well inside that
budget. Immediately before appending an escalated (non-`committed + 1`)
fence, `lease_acquire` re-reads the lease log one more time and abandons the
attempt (burning its own claim, the same accepted trade a crash makes) if
the log has grown since its first read — the cheapest available guard
against exactly the leapfrog scenario above. `state::fold` also now treats a
higher fence as more authoritative than a lower one regardless of which line
the log puts first (with `Renew`/`Release` applying only when their fence
matches the one currently folded), as a second, independent layer: even if
the residual window below is ever hit, `fold` will not let a lower,
late-arriving fence look current over a higher one already folded.

**Tests** (`store/tests/namespaces.rs`):
`acquire_skips_a_fence_a_crash_burned_instead_of_livelocking` plants a
claimed-but-unappended fence-1 marker on a namespace that was never
acquired (exactly what a crash between claim and append leaves) and asserts
a single `acquire` call succeeds at fence 2, rather than exhausting
`MAX_ACQUIRE_ATTEMPTS` and returning `lease_refused`.
`bind_skips_a_seq_a_crash_burned_instead_of_livelocking` is its binding-seq
twin. Both also assert `fsck` is clean afterward — the burned, unreferenced
marker is the accepted crash residue, not the shape `lease_fence_unissued`/
`binding_seq_unissued` look for (those check *records naming an unclaimed
number*, never the reverse — a claim with no record is never inspected, by
construction, so this is not a special case carved out for the test, it
falls out of what the checks already do). Non-vacuity, proved the same way
as every other test in this file: reverting `lease_acquire`'s escalation to
the naive `committed + 1` makes `acquire_skips_a_fence_…` fail by exhausting
all 16 attempts and returning `lease_refused`/`held`; reverting `bind`'s
escalation the same way makes `bind_skips_a_seq_…` fail by exhausting all 16
and returning `lease_refused`/`contention`. Both reverts were run and both
failed exactly that way before being restored.
`simultaneous_acquisitions_of_a_free_namespace_produce_exactly_one_holder`
(the free-namespace race, unmodified) was re-run 15 times after this change
with no flake, as the check that escalation's last-attempt gating had not
quietly reopened the two-holder risk it exists to close.

```
running 19 tests
...
test acquire_skips_a_fence_a_crash_burned_instead_of_livelocking ... ok
test bind_skips_a_seq_a_crash_burned_instead_of_livelocking ... ok
...
test simultaneous_acquisitions_of_a_free_namespace_produce_exactly_one_holder ... ok
...
test result: ok. 19 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in ~5-6s
```

`task store:test`: 82 Rust tests total (39 lib + 21 integration + 17
namespaces at the previous addendum, now 42 lib + 21 integration + 19
namespaces = 82), 0 failures. `task store:lint`: `cargo fmt --check` and
`cargo clippy --all-targets -- -D warnings` both clean. `task
prototype:test`: 693 tests, `OK (skipped=3)` — unaffected, run anyway per
the brief. `task todo:lint`: `TODO.md: clean`. `git diff --check`: clean.

**PASS.**

**Least-certain call (updated).** The re-verify guard on `lease_acquire`'s
escalated path narrows the window in which two `Acquire`s could still land
out of order, but does not close it to zero: between the guard's read and
the actual `append_lease_event` write, a live claimant could still complete.
This residual is the same *order of magnitude* as the base claim-then-append
gap the whole design already accepts (a couple of local filesystem calls),
not a new, larger exposure — but it is not nothing, and `fold`'s
higher-fence-wins tie-break (above) is what keeps that rare outcome from
reading as two holders rather than preventing the outcome itself. Whether
this residual is worth closing fully — e.g., by having the escalated append
itself re-verify *and* claim atomically somehow, which is close to
reinventing the transaction this addendum's first version rejected —
is left for a future increment to judge against how often it is actually
observed, rather than solved speculatively here.
