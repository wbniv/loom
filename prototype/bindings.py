"""Binding admission: SPEC.md §5.3.2's six rules, over already-decoded IR.

This module is the *semantic* half of `bind`. It decides whether a candidate
binding `[2, name-path, def-hash, evidence-set, policy-ref, seq]` (§5.3) may be
admitted, and it does so by **composing** `policies.py` — the `policies`
validation contract at 1.0 — rather than restating any of it. Every structural
judgement about a policy object, every `E ⊒ R` comparison, and every domination
test is `policies`' answer, unchanged:

===========================  ===========================================
`policies.validate_policy`   is this a well-formed policy object at all
`policies.policy_hash`       the 32 bytes a `policy-ref` must equal
`policies.dominates`         rules 2 and 6 (chain, descent, amendment)
`policies.matching_rules`    which of `G`'s rules bear on an obligation
`policies.satisfies`         rule 3, and §6.3's rule 5, both being `E ⊒ R`
`policies.decompose_obligation_id`  the closed obligation-kind registry
===========================  ===========================================

There is no store here and no JSON here. The caller (`store_admit.py`, the
oracle seam the Rust store runs) owns the wire format, decodes the JSON mirror
of every object into IR, and hands this module plain Python values. That keeps
the layering the same shape as `policies.py`'s own: a pure function of its
arguments, injectable and testable without a filesystem.

What v1 enforces, and what it does not
--------------------------------------

Rules 1, 2, 3, 5 and 6 are enforced. Rule 4 — assumption budgets (keys 2 and 3)
and A0 signers (key 4) — is **not computable in this increment**, so rather
than admit a governed binding with those keys silently unenforced this module
**refuses** it, naming the key. That is not an invention: §5.3.1 states exactly
this discipline for the lease keys ("a store that does not implement it must
*refuse* bindings governed by a policy stating either key rather than admit
them unenforced"), and applying it to the keys this increment cannot yet
compute is the only way for the gap to be loud rather than silent.

* Key 2 `max-assumptions` and key 3 `max-assumptions-by-ability` need the
  assumption set of the *transitive closure* of the bound definition, which
  needs a §6.4 evidence ledger the store does not have yet (out of scope by
  the namespaces plan's R4). A sound *lower* bound is computable; a *cap*
  check needs an upper bound, so a lower bound can only ever refuse, never
  admit. Half a budget check is worse than none.
* Key 4 `signers` compares the principal named by an A0 entry, and the A0
  payload format is SPEC §13's open question. This gap is the SPEC's, not
  this module's.

Rule 3's *completeness* half is narrowed and the narrowing is stated: the
obligations a policy **injects** (key 1) must be present in the candidate's
evidence set, and every entry present must satisfy every rule matching it. The
obligations §6.2 *generates* from the definition (one per refinement clause,
one per `fix`, one per `match`, one per reachable extern) are not re-derived
here, because deriving them means re-running the typechecker over the bound
definition inside admission — a second opinion about typing with no referee,
which is the exact thing `store_admit.py`'s seam exists to avoid.

Every refusal is a `BindingRefused` naming the rule number, so a caller can
tell "raced a policy rebind" (rule 1) from "assurance went backwards" (rule 5)
without parsing prose.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import policies

#: Reserved leaf name (§5.3.2). A binding whose leaf is this targets a policy
#: object; every other binding targets a def object.
POLICY_LEAF = "POLICY"

#: The keys v1 admission cannot compute, and therefore refuses rather than
#: admits unenforced. See the module docstring.
UNENFORCEABLE_KEYS = {
    2: "max-assumptions",
    3: "max-assumptions-by-ability",
    4: "signers",
}

#: Why each is unenforceable, in one line, so the refusal explains itself.
_UNENFORCEABLE_REASON = {
    2: "the assumption set needs a §6.4 evidence ledger over the transitive closure",
    3: "per-ability assumption counts need the same ledger plus effect rows",
    4: "the A0 payload names its principal, and that format is SPEC §13's open question",
}


class BindingRefused(Exception):
    """Admission said no, carrying the §5.3.2 rule that said it."""

    def __init__(self, rule: int, message: str):
        super().__init__(f"rule {rule}: {message}")
        self.rule = rule
        self.detail = message


def _refuse(rule: int, message: str):
    raise BindingRefused(rule, message)


# ---------------------------------------------------------------------------
# Name paths
# ---------------------------------------------------------------------------


def split_name_path(name_path: str) -> tuple[str, str]:
    """`"stats/median"` → `("stats", "median")`; `"root"` → `("", "root")`.

    The namespace is everything before the last separator, so the root
    namespace is the empty string. The Rust store is the gatekeeper for
    name-path syntax — it refuses a malformed path before the oracle is ever
    run — but this module re-derives the split rather than being told it,
    because rules 1 and 6 turn on which namespace a name is *in*.
    """
    if not isinstance(name_path, str) or not name_path:
        raise ValueError("name-path must be non-empty text")
    if name_path != unicodedata.normalize("NFC", name_path):
        raise ValueError("name-path must be NFC-normalized")
    segments = name_path.split("/")
    if any(not segment for segment in segments):
        raise ValueError(f"name-path {name_path!r} has an empty segment")
    return "/".join(segments[:-1]), segments[-1]


def is_ancestor_or_self(namespace: str, candidate: str) -> bool:
    """Whether `candidate` encloses `namespace` (or is it). Root encloses all."""
    if candidate == "":
        return True
    return namespace == candidate or namespace.startswith(candidate + "/")


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyBinding:
    """A namespace's current `POLICY` binding, as the store folded it out of
    that namespace's binding log."""

    namespace: str
    hash: bytes
    object: list


@dataclass(frozen=True)
class Previous:
    """The binding this one replaces at the same name-path, or nothing."""

    def_hash: bytes
    evidence: list
    policy_ref: bytes
    seq: int
    #: The policy object, for a `POLICY` leaf — amendment (rule 6) compares
    #: the successor against it.
    object: list | None = None


@dataclass(frozen=True)
class Candidate:
    name_path: str
    def_hash: bytes
    evidence: list = field(default_factory=list)
    policy_ref: bytes = b""
    seq: int = 0
    #: The policy object, for a `POLICY` leaf.
    object: list | None = None


# ---------------------------------------------------------------------------
# Evidence sets
# ---------------------------------------------------------------------------


def validate_evidence_set(entries) -> dict:
    """A binding's evidence-set: `[(obligation-id, lattice-point)…]`, sorted by
    id and free of duplicates, every id decomposing under §5.3.1's closed kind
    registry and every point a lattice point.

    Sortedness and uniqueness are required for the same reason §5.3.1 requires
    them of every array-valued policy key: it is a *set*, and a set with two
    spellings has two hashes.
    """
    if not isinstance(entries, (list, tuple)):
        raise policies.PolicyError("evidence-set: expected an array")
    seen: list[str] = []
    out: dict[str, list] = {}
    for index, entry in enumerate(entries):
        path = f"evidence-set[{index}]"
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise policies.PolicyError(f"{path}: expected [obligation-id, point]")
        obligation_id, point = entry
        policies.decompose_obligation_id(obligation_id, path)
        policies.validate_point(point, f"{path}.point")
        if obligation_id in out:
            raise policies.PolicyError(f"{path}: duplicate obligation id {obligation_id!r}")
        seen.append(obligation_id)
        out[obligation_id] = list(point)
    if seen != sorted(seen):
        raise policies.PolicyError("evidence-set: entries must be sorted by obligation id")
    return out


# ---------------------------------------------------------------------------
# Resolution (§5.3.2)
# ---------------------------------------------------------------------------


def resolve(namespace: str, policy_leaf: bool, policy_bindings) -> list:
    """The governing policy chain for a name in `namespace`, nearest first,
    ending at the default policy.

    `policy_bindings` is every enclosing namespace's current `POLICY` binding
    (including `namespace`'s own and the root's), nearest first — the store
    supplies it, because folding a binding log is the store's job, and
    *interpreting* the fold is this module's.

    For a `POLICY` leaf resolution starts **strictly above** its own namespace,
    so a policy never governs itself. The chain always terminates: root has no
    enclosing namespace and is governed by the default policy, which is three
    bytes and preloaded.
    """
    usable = [
        binding
        for binding in policy_bindings
        if is_ancestor_or_self(namespace, binding.namespace)
        and not (policy_leaf and binding.namespace == namespace)
    ]
    # Nearest first: a deeper namespace is a longer string, and every entry
    # encloses `namespace`, so depth order is length order.
    usable.sort(key=lambda binding: len(binding.namespace), reverse=True)
    chain = [binding.object for binding in usable]
    chain.append(policies.DEFAULT_POLICY)
    return chain


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------


def admit(candidate: Candidate, policy_bindings, previous: Previous | None = None) -> dict:
    """Run SPEC.md §5.3.2's admission rules. Returns a record of what was
    checked; raises `BindingRefused` naming the rule that refused."""
    namespace, leaf = split_name_path(candidate.name_path)
    policy_leaf = leaf == POLICY_LEAF

    for binding in policy_bindings:
        policies.validate_policy(binding.object, f"policy at {binding.namespace or '<root>'}/POLICY")
        actual = policies.policy_hash(binding.object)
        if actual != binding.hash:
            _refuse(
                1,
                f"the policy object bound at {binding.namespace or '<root>'}/POLICY mirrors to "
                f"{actual.hex()}, not to {binding.hash.hex()}",
            )

    chain = resolve(namespace, policy_leaf, policy_bindings)
    governing = chain[0]
    governing_hash = policies.policy_hash(governing)
    governing_map = governing[1]

    # -- rule 1: the proposal carries the governing policy's hash -------------
    if candidate.policy_ref != governing_hash:
        _refuse(
            1,
            f"policy-ref {candidate.policy_ref.hex()} is not the governing policy "
            f"{governing_hash.hex()}; retry against the policy now in force",
        )

    # -- rule 2: every policy on the chain dominates the one governing it -----
    for lower, upper in zip(chain, chain[1:]):
        if not policies.dominates(lower, upper):
            _refuse(
                2,
                f"policy {policies.policy_hash(lower).hex()} does not dominate the policy "
                f"{policies.policy_hash(upper).hex()} governing it; the namespace is frozen "
                "until its policy is amended",
            )

    # -- rule 4, as far as v1 can go: refuse rather than under-enforce --------
    for key in sorted(UNENFORCEABLE_KEYS):
        if key in governing_map:
            _refuse(
                4,
                f"the governing policy states key {key} ({UNENFORCEABLE_KEYS[key]}), which this "
                f"store cannot enforce — {_UNENFORCEABLE_REASON[key]}. Refusing rather than "
                "admitting it unenforced (§5.3.1's own discipline for an unimplemented key)",
            )

    # -- rule 3: obligations complete, and every entry satisfies every rule ---
    evidence = validate_evidence_set(candidate.evidence)
    injected = [detail for detail, _statement in governing_map.get(1, [])]
    for detail in injected:
        obligation_id = f"property.{detail}"
        if obligation_id not in evidence:
            _refuse(
                3,
                f"the governing policy injects {obligation_id} and the binding carries no entry "
                "for it; §6.1 requires an entry to exist, and an A0 assumption supplies one",
            )
    checked = 0
    for obligation_id, point in evidence.items():
        for _selector, requirement in policies.matching_rules(governing_map, obligation_id):
            checked += 1
            if not policies.satisfies(point, requirement):
                _refuse(
                    3,
                    f"evidence for {obligation_id} does not satisfy a rule of the governing "
                    f"policy: {_point(point)} is not ⊒ {_point(requirement)}",
                )

    # -- rule 5: §6.3 monotone assurance against the previous binding ---------
    regressions = []
    if previous is not None:
        before = validate_evidence_set(previous.evidence)
        for obligation_id, old in before.items():
            new = evidence.get(obligation_id)
            if new is None:
                continue
            if not policies.satisfies(new, old):
                regressions.append((obligation_id, old, new))
    if regressions:
        obligation_id, old, new = regressions[0]
        reason = (
            "incomparable — a different generator, so it is not a statement about the "
            "distribution the previous binding was cleared against"
            if old[0] == 1 and new[0] == 1 and old[3] != new[3]
            else "weaker"
        )
        _refuse(
            5,
            f"assurance on {obligation_id} would decrease: {_point(new)} is not ⊒ "
            f"{_point(old)} ({reason})",
        )

    # -- rule 6: POLICY descent and amendment ---------------------------------
    if policy_leaf:
        if candidate.object is None:
            _refuse(6, "a POLICY leaf must carry the policy object it binds")
        successor = policies.validate_policy(candidate.object, "successor")
        actual = policies.policy_hash(successor)
        if actual != candidate.def_hash:
            _refuse(
                6,
                f"the policy object mirrors to {actual.hex()}, not to the bound def-hash "
                f"{candidate.def_hash.hex()}",
            )
        if not policies.dominates(successor, governing):
            _refuse(
                6,
                f"descent: the policy bound at {candidate.name_path} must dominate the policy "
                f"{governing_hash.hex()} governing it",
            )
        if previous is not None:
            if previous.object is None:
                _refuse(6, "amending a POLICY binding needs the policy object it replaces")
            predecessor = policies.validate_policy(previous.object, "predecessor")
            if not policies.dominates(successor, predecessor) and predecessor[1].get(8) != 1:
                _refuse(
                    6,
                    "amendment: the successor policy neither dominates the policy it replaces "
                    "nor is that policy `relax: 1`; a namespace ratchets toward strictness only",
                )

    return {
        "admitted": True,
        "name_path": candidate.name_path,
        "namespace": namespace,
        "leaf": leaf,
        "policy_leaf": policy_leaf,
        "seq": candidate.seq,
        "governing_policy": governing_hash.hex(),
        "chain": [policies.policy_hash(policy).hex() for policy in chain],
        "obligations": sorted(evidence),
        "injected": sorted(injected),
        "rules_applied": checked,
        "monotone_checked": previous is not None,
        "contracts": {"policies": _policies_version()},
    }


# ---------------------------------------------------------------------------
# Lease admission (§5.3.3 policy integration)
# ---------------------------------------------------------------------------

#: §5.3.1 key 5 — who may hold the namespace's write lease.
KEY_WRITERS = 5
#: §5.3.1 key 6 — how long, in milliseconds.
KEY_MAX_LEASE = 6


class LeaseRefused(Exception):
    """`acquire` or `renew` said no, carrying §5.3.3's own refusal vocabulary:
    `writer` (the principal is not in key 5) or `bound` (the TTL exceeds key
    6). The third reason §5.3.3 names — `held` — is the store's to give, not a
    policy question, so it never reaches this module."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def check_lease(namespace: str, principal: bytes, ttl_millis: int, policy_bindings) -> dict:
    """Resolve the policy governing `namespace`'s lease and apply keys 5 and 6.

    The governing policy of a namespace's lease is the one governing bindings
    *in* that namespace — §5.3.3 says the lease on `stats/` covers everything
    whose parent is `stats/`, `stats/POLICY` included, so one policy governs the
    whole namespace's lease and it is resolved as for an ordinary leaf.

    The TTL is **refused** when over-bound, never silently clamped (§5.3.3): a
    holder that asked for ten minutes and was quietly given one would act on a
    lease it does not have.
    """
    if not isinstance(principal, bytes) or len(principal) != 32:
        raise ValueError("principal must be a 32-byte principal-id")
    if not isinstance(ttl_millis, int) or isinstance(ttl_millis, bool) or ttl_millis < 1:
        raise ValueError("ttl-millis must be a positive integer")

    for binding in policy_bindings:
        policies.validate_policy(binding.object, f"policy at {binding.namespace or '<root>'}/POLICY")
        actual = policies.policy_hash(binding.object)
        if actual != binding.hash:
            raise ValueError(
                f"the policy object bound at {binding.namespace or '<root>'}/POLICY mirrors to "
                f"{actual.hex()}, not to {binding.hash.hex()}"
            )

    chain = resolve(namespace, False, policy_bindings)
    governing = chain[0]
    governing_map = governing[1]

    writers = governing_map.get(KEY_WRITERS)
    if writers is not None and principal not in set(writers):
        raise LeaseRefused(
            "writer",
            f"principal {principal.hex()} is not in the governing policy's writers set",
        )
    maximum = governing_map.get(KEY_MAX_LEASE)
    if maximum is not None and ttl_millis > maximum:
        raise LeaseRefused(
            "bound",
            f"a {ttl_millis} ms lease exceeds the governing policy's max-lease-millis "
            f"of {maximum}; refused rather than clamped",
        )
    return {
        "cleared": True,
        "namespace": namespace,
        "policy_ref": policies.policy_hash(governing).hex(),
        "ttl_millis": ttl_millis,
        "writers_stated": writers is not None,
        "max_lease_millis": maximum,
        "contracts": {"policies": _policies_version()},
    }


def _policies_version() -> str:
    import contracts

    return contracts.version("policies")


def _point(point) -> str:
    """A lattice point, spelled the way a refusal should read."""
    if point[0] != 1:
        return f"A{point[0]}"
    bound, confidence, generator = point[1], point[2], point[3]
    return (
        f"A1(bound {bound[0]}/{bound[1]}, confidence {confidence[0]}/{confidence[1]}, "
        f"generator {generator.hex()[:8]}…)"
    )
