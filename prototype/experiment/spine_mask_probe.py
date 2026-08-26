"""`spine-goal`'s evidence, reproducible on a CPU with no model loaded.

Three sections, matching `docs/plans/2026-08-25-mask-spine-refs.md` §5:

* **soundness** — every corpus fixture *and* every gold term walked through
  the real `Masker` with `spine-goal` enabled, under three tokenizations, with
  one assertion at every step: the fixture's own next token is in the mask.
  A violation is what R4 forbids, and this prints the count rather than
  arguing about it.
* **precision** — the admissible-ref universe at the `app`-spine head of each
  gold term, under both readings of §2.4 (see the plan's §1 for why they
  differ and why the exact one is what landed).
* **overhead** — `mask_seconds_per_token` with the layer on and off, over the
  same walk, single stream.

Run from `prototype/`::

    python3 -m experiment.spine_mask_probe
"""

from __future__ import annotations

import argparse
import json
import sys

import corpus_registry
import sexpr
import transcode
from typecheck import _erase_refinements

from .backends import scripted_vocabulary
from .heldout_gold import GOLD_TERMS
from .masker import (
    KNOWN_PRUNER_NAMES,
    PRUNER_NAMES,
    TypeState,
    build_masker,
    peel_codomain,
    spine_context,
)
from .resolver import ExperimentResolver

#: The layer under test, in the position a config would name it.
SPINE_PRUNERS = ("goal-type", "spine-goal", "de-bruijn", "ref-hash")


# --------------------------------------------------------------------------
# Corpus under test
# --------------------------------------------------------------------------


def surfaces() -> list[tuple[str, str]]:
    """`(name, surface)` for every corpus fixture, then every gold term.

    The gold terms are the reason this probe exists: they are accepted
    definitions built entirely out of `app` spines, which is exactly the
    position no fixture in `corpus/` exercises at `k = 3`.
    """
    rows = [(entry.name_path, entry.source_text().rstrip("\n"))
            for entry in corpus_registry.MANIFEST]
    rows.extend(sorted(GOLD_TERMS.items()))
    return rows


def chunk(data: bytes, size: int) -> list[bytes]:
    return [data[index:index + size] for index in range(0, len(data), size)]


def greedy(data: bytes, vocabulary, longest: int = 8) -> list[bytes]:
    pieces, index = [], 0
    while index < len(data):
        for length in range(min(longest, len(data) - index), 0, -1):
            if vocabulary.lookup(data[index:index + length]) is not None:
                pieces.append(data[index:index + length])
                index += length
                break
        else:  # pragma: no cover - the vocabulary holds every single byte
            raise AssertionError(f"no token covers {data[index:index + 4]!r}")
    return pieces


# --------------------------------------------------------------------------
# Soundness
# --------------------------------------------------------------------------


def walk(masker, vocabulary, pieces) -> list[dict]:
    """Every step of one definition. Returns the violations, which must be []."""
    violations = []
    masker.reset()
    for index, piece in enumerate(pieces):
        token = vocabulary.lookup(piece)
        step = masker.step()
        if token not in step.allowed:
            violations.append({
                "token": index,
                "piece": piece.decode("utf-8", "replace"),
                "after": masker.text[-60:],
                "pruned": step.pruned,
                "atom": f"{masker.tstate.atom_kind} {masker.tstate.atom!r}",
            })
        masker.accept_token(token)
    return violations


def soundness(resolver, corpus) -> dict:
    vocabulary = scripted_vocabulary([surface for _, surface in corpus], max_piece=4)
    report: dict = {"definitions": len(corpus), "walks": 0, "violations": [],
                    "fallbacks": 0}
    for names in (SPINE_PRUNERS, PRUNER_NAMES):
        masker = build_masker(vocabulary, resolver, names=list(names))
        for name, surface in corpus:
            data = surface.encode("utf-8")
            for label, pieces in (("1 byte", chunk(data, 1)),
                                  ("3 bytes", chunk(data, 3)),
                                  ("greedy", greedy(data, vocabulary))):
                report["walks"] += 1
                for violation in walk(masker, vocabulary, pieces):
                    report["violations"].append(
                        {"pruners": list(names), "definition": name,
                         "tokenization": label, **violation})
        if list(names) == list(SPINE_PRUNERS):
            report["fallbacks"] = masker.fallbacks
    return report


# --------------------------------------------------------------------------
# Precision
# --------------------------------------------------------------------------


def spine_head_positions(surface: str) -> list[dict]:
    """Every `(ref ` byte offset that heads a spine with a known goal.

    Found by replaying the definition's own bytes through `TypeState` — the
    same scanner the mask runs — rather than by parsing, so what is reported
    is what the pruner would actually see.
    """
    found = []
    state = TypeState()
    data = surface.encode("utf-8")
    for offset, byte in enumerate(data):
        state = state.advance(byte)
        frame = state.top
        if frame.kind == "ref" and frame.part == 1 and state.atom == b"" and not frame.goal:
            k, goal = spine_context(state.stack, len(state.stack) - 1)
            if k and goal:
                found.append({"offset": offset, "k": k,
                              "goal": goal.decode("utf-8")})
    return found


def _type_ir(surface: str):
    return transcode.type_to_ir(sexpr.parse_all(surface)[0])


def admissible(resolver, k: int, goal: str) -> dict:
    """Both readings of §2.4 at one `(k, goal)`, as sorted name lists."""
    erased_goal = _erase_refinements(_type_ir(goal))
    exact, existential = [], []
    for digest in resolver.digests():
        try:
            resolved = resolver.reference_type(digest)
        except Exception:       # noqa: BLE001
            continue
        if not isinstance(resolved, list) or not resolved:
            continue
        try:
            name = resolver.entry(digest).name_path
        except Exception:       # noqa: BLE001
            name = "extern/" + digest.hex()[:6]
        if resolved[0] == 6:
            exact.append(name)
            existential.append(name)
            continue
        verdict, codomain = peel_codomain(resolved, k)
        if verdict == "abstain" or (
                verdict == "peeled" and _erase_refinements(codomain) == erased_goal):
            exact.append(name)
        node, depth = resolved, 0
        while True:
            if _erase_refinements(node) == erased_goal:
                existential.append(name)
                break
            if not (isinstance(node, list) and node and node[0] == 2) or depth > 8:
                break
            node, depth = node[3], depth + 1
    return {"universe": len(resolver.digests()),
            "exact": sorted(exact), "existential": sorted(existential)}


def precision(resolver) -> list[dict]:
    rows = []
    for task, surface in sorted(GOLD_TERMS.items()):
        for position in spine_head_positions(surface):
            counts = admissible(resolver, position["k"], position["goal"])
            rows.append({"task": task, **position, **counts})
    return rows


# --------------------------------------------------------------------------
# Overhead
# --------------------------------------------------------------------------


def overhead(resolver, corpus) -> dict:
    vocabulary = scripted_vocabulary([surface for _, surface in corpus], max_piece=4)
    result = {}
    for label, names in (("off", PRUNER_NAMES), ("on", SPINE_PRUNERS)):
        masker = build_masker(vocabulary, resolver, names=list(names))
        for _, surface in corpus:
            walk(masker, vocabulary, greedy(surface.encode("utf-8"), vocabulary))
        stats = masker.stats()
        result[label] = {
            "pruners": list(names),
            "mask_steps": stats["mask_steps"],
            "mask_seconds_per_token": stats["mask_seconds_per_token"],
            "mask_seconds_per_token_uncached": stats["mask_seconds_per_token_uncached"],
            "mask_cache_hit_rate": stats["mask_cache_hit_rate"],
            "mask_fallbacks": stats["mask_fallbacks"],
            "spine_goal_seconds": stats["mask_seconds_by_layer"].get("spine-goal", 0.0),
            "spine_goal_pruned": stats["mask_pruned_by_layer"].get("spine-goal", 0),
        }
    return result


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def render(report: dict) -> str:
    lines = ["## Soundness — every fixture and gold term, `spine-goal` ON\n"]
    sound = report["soundness"]
    lines.append(f"definitions: {sound['definitions']}   "
                 f"walks: {sound['walks']}   "
                 f"liveness fallbacks: {sound['fallbacks']}")
    lines.append(f"VIOLATIONS: {len(sound['violations'])}")
    for violation in sound["violations"][:10]:
        lines.append(f"  {violation}")

    lines.append("\n## Precision — admissible refs at each `app`-spine head\n")
    lines.append(f"{'task':32s} {'k':>2s} {'exact':>7s} {'exists-k':>9s}  goal")
    for row in report["precision"]:
        lines.append(
            f"{row['task']:32s} {row['k']:2d} "
            f"{len(row['exact']):3d}/{row['universe']:<3d} "
            f"{len(row['existential']):5d}/{row['universe']:<3d}  "
            f"{row['goal'][:44]}")

    lines.append("\n### §2.4's three tabulated tasks, both readings\n")
    for row in report["precision"]:
        if row["task"] in ("heldout/list/reverseThen", "heldout/list/sum",
                           "heldout/maybe/mapOrElse"):
            lines.append(f"{row['task']}  k={row['k']}")
            lines.append(f"   exists-k ({len(row['existential'])}/{row['universe']}): "
                         f"{', '.join(row['existential'])}")
            lines.append(f"   exact-k  ({len(row['exact'])}/{row['universe']}): "
                         f"{', '.join(row['exact'])}")

    lines.append("\n## Overhead — mask_seconds_per_token\n")
    for label in ("off", "on"):
        row = report["overhead"][label]
        lines.append(
            f"spine-goal {label:3s}  steps={row['mask_steps']:6d}  "
            f"s/token={row['mask_seconds_per_token']:.9f}  "
            f"uncached={row['mask_seconds_per_token_uncached']:.9f}  "
            f"hit-rate={row['mask_cache_hit_rate']:.4f}  "
            f"fallbacks={row['mask_fallbacks']}")
    on, off = report["overhead"]["on"], report["overhead"]["off"]
    if off["mask_seconds_per_token"]:
        ratio = on["mask_seconds_per_token"] / off["mask_seconds_per_token"]
        lines.append(f"ratio on/off: {ratio:.3f}x   "
                     f"spine-goal layer seconds: {on['spine_goal_seconds']:.6f}   "
                     f"tokens it pruned: {on['spine_goal_pruned']}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m experiment.spine_mask_probe",
        description="Soundness, precision and overhead for the `spine-goal` pruner.")
    parser.add_argument("--json", action="store_true", help="emit the raw record")
    arguments = parser.parse_args(argv)

    assert "spine-goal" in KNOWN_PRUNER_NAMES
    assert "spine-goal" not in PRUNER_NAMES, "the default set must stay unchanged"

    resolver = ExperimentResolver()
    corpus = surfaces()
    report = {
        "soundness": soundness(resolver, corpus),
        "precision": precision(resolver),
        "overhead": overhead(resolver, corpus),
    }
    if arguments.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    return 1 if report["soundness"]["violations"] else 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
