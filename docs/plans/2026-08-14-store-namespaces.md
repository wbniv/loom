# Plan — Store namespaces v1: bindings, leases, and policy-gated admission

**Date:** 2026-08-14
**Status:** Designed; not yet built
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

- [ ] Lease log + verbs + fence checks + fsck invariant 4 (R1).
- [ ] Binding log + `bind` with oracle admission + kind checks (R2).
- [ ] Oracle admission entry point extension in `prototype/` composing
  policies.py / evidence comparison (R2).
- [ ] Read API (R3).
- [ ] Run log + verification recorded here.

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
