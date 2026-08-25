"""Amendment A1's measurement: the demand-closure repair of §4.2 does not work.

The next-lever plan (docs/plans/2026-08-24-next-lever.md, §4.8 note + Amendment
A1) records that §4.2's body-goal filter drops route elements for 5 of 8
held-out tasks. The obvious repair is a demand-driven closure — seed the demand
set with the task's body goal; admit object `o` when some k-th codomain erases
to a demanded type (a bare `forall` is always admitted, as in §4.2); on
admission, propagate `o`'s first-k erased domain types into the demand set;
iterate to fixpoint. Same signature discipline as `typed_address_rows`: a
resolver and a declared type surface, nothing else.

This probe measures that repair against the landed filter over all eight tasks.
Verdict (pasted into Amendment A1, reproduced by running this module): the
closure recovers 4 of the 5 broken tasks but admits 28 of 35 rows — erasing
H3's small-book premise — and still misses `list/uncons` (polymorphic
instantiation is invisible to exact erased equality) and `clock/now` /
`rand/bytes` (effectful codomains never syntactically meet a demand). The
route (`Task.composes`) is consulted only here, to *verify* survival — never
by either filter.

Run from `prototype/`: `python3 -m experiment.closure_filter_probe`
"""

from experiment.addressability_audit import HELD_OUT_TASKS
from experiment.prompts import (
    CODOMAIN_DEPTHS,
    _erase,
    _kth_codomain,
    body_goal_of,
    ref_legal_objects,
    typed_address_rows,
)
from experiment.resolver import ExperimentResolver


def closure_admitted(resolver: ExperimentResolver, type_surface: str) -> dict:
    """Hex -> Resolved for every object the demand-closure filter admits."""
    objs = ref_legal_objects(resolver)
    demands = {repr(body_goal_of(type_surface))}
    admitted: dict = {}
    changed = True
    while changed:
        changed = False
        for found in objs:
            if found.hex in admitted:
                continue
            t = found.type_ir
            if t[0] == 6:  # bare forall: §4.2 admits unconditionally
                admitted[found.hex] = found
                changed = True
                continue
            for k in CODOMAIN_DEPTHS:
                cod = _kth_codomain(t, k)
                if cod is None:
                    continue
                if repr(_erase(cod)) in demands:
                    admitted[found.hex] = found
                    cur = t
                    for _ in range(k):
                        demands.add(repr(_erase(cur[1])))
                        cur = cur[3]
                    changed = True
                    break
    return admitted


def main() -> None:
    resolver = ExperimentResolver()
    print(
        f"{'task':<34}{'lit rows':>9}{'clo rows':>9}"
        "  lit-missing / clo-missing (route elements)"
    )
    lit_counts, clo_counts = [], []
    for task in HELD_OUT_TASKS:
        surface = task.expected_type_surface
        lit_hexes = {row.split()[0][2:] for row in typed_address_rows(resolver, surface)}
        clo = closure_admitted(resolver, surface)
        route_hexes = {resolver.digest_for(name).hex(): name for name in task.composes}
        lit_missing = [n for h, n in route_hexes.items() if h not in lit_hexes]
        clo_missing = [n for h, n in route_hexes.items() if h not in clo]
        lit_counts.append(len(lit_hexes))
        clo_counts.append(len(clo))
        print(
            f"{task.task_id:<34}{len(lit_hexes):>9}{len(clo):>9}  "
            f"{lit_missing or 'ok'} / {clo_missing or 'ok'}"
        )
    print(
        f"\nliteral range {min(lit_counts)}-{max(lit_counts)}, "
        f"closure range {min(clo_counts)}-{max(clo_counts)} "
        f"(full book = {len(ref_legal_objects(resolver))})"
    )


if __name__ == "__main__":
    main()
