"""Validated, immutable definition-type snapshots for injected `ref` typing."""

from __future__ import annotations

import copy
from collections.abc import Callable

from scope import check_definition
from transcode import transcode_source


class DefinitionTypeRegistry:
    """A small store-facing test adapter, not a Loom object registry.

    Only scope-validated definitions enter the mapping. Returned types are
    isolated copies so a checker cannot mutate the stored snapshot.
    """

    def __init__(self, ability_arity: Callable[[bytes, int], int] | None = None):
        self._ability_arity = ability_arity
        self._types: dict[bytes, list] = {}

    def add_source(self, source: str, expected_hash: bytes | None = None) -> bytes:
        ir, _, digest_hex = transcode_source(source)
        digest = bytes.fromhex(digest_hex)
        if expected_hash is not None and digest != expected_hash:
            raise ValueError(
                f"definition type registry: supplied hash {expected_hash.hex()} "
                f"does not match canonical hash {digest.hex()}"
            )
        check_definition(ir, self._ability_arity)
        self._types[digest] = copy.deepcopy(ir[1])
        return digest

    def reference_type(self, digest: bytes) -> list:
        try:
            return copy.deepcopy(self._types[digest])
        except KeyError as exc:
            raise LookupError(digest) from exc
