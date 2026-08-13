"""Compatibility imports for the former nominal-match checker module.

New code should import :mod:`typecheck`; this shim preserves existing prototype
callers. The module is not named ``typing`` because that would shadow Python's
standard-library module when tests run from this directory.
"""

from typecheck import (  # noqa: F401
    MatchChecker,
    TypingError,
    constructor_fields,
    instantiate_type,
    validate_source,
)

TypeDirectionError = TypingError
