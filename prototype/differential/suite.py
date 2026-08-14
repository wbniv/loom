"""Running the prototype's own test suite with the entry points wrapped.

The tests are the corpus of rejection cases. They are run exactly as they are —
same modules, same order, same assertions — and the harness reads what they
drive through the layers. Nothing here inspects, rewrites, or re-states a test.

Module discovery is a sorted glob rather than the Taskfile's hand-written list,
so a new `test_*.py` is harvested the day it lands instead of the day someone
remembers to add it in two places. Sorted, so the run order — and therefore the
export — does not depend on the filesystem.
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path

PROTOTYPE_DIR = Path(__file__).resolve().parent.parent


def modules() -> list[str]:
    return sorted(path.stem for path in PROTOTYPE_DIR.glob("test_*.py"))


def run(recorder, verbosity: int = 0) -> unittest.TestResult:
    """Run every test module under instrumentation and return the result."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromNames(modules()))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=verbosity).run(suite)
    recorder.provenance = None
    return result
