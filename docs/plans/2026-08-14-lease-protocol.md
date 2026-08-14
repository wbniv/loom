# Design — The namespace lease protocol (open problem 4)

**Date:** 2026-08-14
**Status:** Draft for operator review — four decisions below need sign-off
before this touches SPEC §5.3 or the store
**Parent:** SPEC §5.3 / §13 open problem 4; the
[store v0 plan](2026-08-14-store-v0.md)'s "what a future increment touches
first" notes

## What the SPEC already fixes, and this design must fit

- A namespace has **a single writer at a time**; objects need no
  coordination (content-addressed, commutative); **only binding sequences
  are serialized, per namespace** (§5.3, P6).
- Policy key 5 (`writers`) says who may hold the lease; key 6
  (`max-lease-millis`) bounds how long. A store without leases must
  **refuse** bindings governed by a policy stating either key (§5.3.1).
- The race the lease exists to serialize is named in admission rule 1:
  a binding proposal racing a `POLICY` rebind (§5.3.2).
- Principal possession-proof is deliberately unspecified (the A0 payload,
  §13) — the lease design must not smuggle in an authentication scheme.

## The design

### L1 — A lease is store *state*, not store *content*

Everything Loom knows is immutable and content-addressed; a lease is
neither — it expires. Rather than cosplay immutability, the lease lives in
a distinct stratum: `state/leases/<namespace>.jsonl`, an **append-only
per-namespace log** of lease events, outside `objects/` and outside object
identity. "Every previous state of every namespace remains addressable"
(§5.3) is a claim about *bindings*; the lease log is operational
coordination with an audit trail, not addressable knowledge. The current
lease is the fold of the log (last event wins); `fsck` grows a fourth
invariant: every log parses, fences are strictly increasing, and any cached
current-lease state equals the fold.

### L2 — Correctness comes from fencing, not clocks

Every successful `acquire` on a namespace issues a **fence number** —
strictly increasing per namespace, starting at 1. Binding admission (and
`POLICY` rebinds, which are just bindings) requires the proposal to carry
the namespace's **current, unexpired fence**. A holder whose lease expired
or was superseded fails the fence check no matter what it believes about
time. Clocks matter only at the single arbiter — the store — which judges
expiry by its own clock at admission time. Writer-side clock skew is
therefore harmless; store-side clock jumps can shorten or lengthen a lease
in wall terms but can never admit two writers (the fence is the guarantee;
the TTL is only liveness). This is deliberately the boring, proven shape
(fencing tokens), because §5.3 already promises "no consensus needed."

### L3 — Four verbs, lazy expiry, no queue

- `acquire(namespace, principal, ttl-millis)` → `granted{fence, expires}`
  or `refused{reason}` (held: names holder + expiry; policy: principal not
  in key 5, or ttl exceeds key 6; ttl is *refused* over-bound, not
  silently clamped).
- `renew(namespace, fence, ttl-millis)` → extends expiry, **same fence**
  (holder continuity is the point of renewal), re-checked against the
  *current* governing policy.
- `release(namespace, fence)` → ends the lease immediately.
- Expiry is **lazy**: no reaper; an expired lease is simply acquirable,
  and the next grant increments the fence. Contention is poll-based in
  v1 — no wait queue, no callbacks. (Fairness under contention is the part
  of problem 4 this design *leaves* open, stated below.)

### L4 — Policy integration, including the mid-lease rebind question

`acquire` and `renew` check the namespace's governing policy (resolved per
§5.3.2) and record its hash in the lease event, mirroring a binding's
`policy-ref`. A `POLICY` rebind that tightens `writers` or
`max-lease-millis` mid-lease does **not** evict the current holder: the
lease was cleared under the policy in force at grant, eviction-by-rebind
would make every policy amendment a potential availability weapon, and the
new policy binds at the next `acquire`/`renew` anyway (renewals re-check).
The admission-rule-1 race stays solved exactly as §5.3.2 states: the
binding's `policy-ref` mismatch refuses, and the *lease* is what guarantees
the retry isn't racing a second writer too.

### L5 — Granularity: one lease per namespace, not per subtree

A lease on `stats/` covers bindings whose parent is `stats/` — including
`stats/POLICY` — and says nothing about `stats/inner/`, which has its own
lease. Cross-level interference (a policy rebind above affecting admission
below) is already handled by rule 1's policy-ref check, so subtree-spanning
leases buy nothing correctness-wise and would concentrate contention.
What this does *not* solve — and records as the residue of problem 4 —
is fairness and throughput when many agents contend for one namespace:
hierarchical sharding, wait queues, and lease splitting are future work
gated on real agent-count data, per the existing Watch item.

### L6 — The principal gap, stated not solved

`writers` compares 32-byte principal-ids; how a caller proves possession is
the A0 open question and stays open. In v1 the store records the claimed
principal-id unverified — the same trust stance §5.3.1 already takes for A0
signers. The lease log is therefore an *accountability* record, not an
*authentication* one, and the design keeps a clean seam: when the A0 payload
format lands, `acquire` grows a proof argument with no other change.

## The four decisions needing operator sign-off

| # | Decision | The alternative it rejects |
|---|---|---|
| D1 | Lease = append-only state log outside object identity (L1) | A mutable holder-file (simpler, loses audit + fsck-ability), or content-addressed lease objects (fights expiry) |
| D2 | No eviction on mid-lease policy rebind (L4) | Immediate eviction — stricter, but weaponizable and race-prone |
| D3 | Claimed principal-ids, unverified until A0 lands (L6) | Blocking leases on solving authentication first |
| D4 | Per-namespace granularity, poll-based contention, no queue (L3/L5) | Subtree leases or wait queues now, ahead of any agent-count data |

## What lands where, once approved

- SPEC §5.3 gains a short "lease protocol" subsection (verbs, fencing,
  lazy expiry, the granularity rule) and §13 problem 4 narrows to the
  fairness/scale residue.
- The store's namespaces increment implements L1–L6 (`state/` stratum,
  fence checks in a future `bind` path, fourth `fsck` invariant); nothing
  in store v0 changes until then.
- The policy checker's refuse-on-keys-5/6 behavior flips to enforce once
  the protocol exists.

## Cost

$0 — design only. No implementation is dispatched from this document.
