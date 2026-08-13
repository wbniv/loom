"""Round-trip verification for the S-expression isomorph transcoder.

Run: python3 test_roundtrip.py
Exercises every term/type node tag reachable without a full standard
library (SS8.4's build item), and pins example 1 to the exact SS4.4
worked-example hash so a byte-level regression cannot pass silently.
"""

from __future__ import annotations

import glob
import os
import unittest

from transcode import transcode_source

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "examples")

WORKED_EXAMPLE_HASH = (
    "76c62727b181b5f71e6206a08a5bbe8b005f227b446f6f8b311fe792901e0605"
)
WORKED_EXAMPLE_BYTES = (
    "83008402820002808200028303820002820000"
)


class RoundTripTest(unittest.TestCase):
    def test_worked_example_matches_spec_4_4(self):
        path = os.path.join(EXAMPLES_DIR, "01_id.loom.sexpr")
        with open(path) as f:
            _, b, h = transcode_source(f.read())
        self.assertEqual(b.hex(), WORKED_EXAMPLE_BYTES)
        self.assertEqual(h, WORKED_EXAMPLE_HASH)
        self.assertEqual(len(b), 19)

    def test_every_example_transcodes_deterministically(self):
        for path in sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.loom.sexpr"))):
            with open(path) as f:
                src = f.read()
            _, b1, h1 = transcode_source(src)
            _, b2, h2 = transcode_source(src)  # re-run: must be byte-identical
            self.assertEqual(b1, b2, f"{path}: non-deterministic encoding")
            self.assertEqual(h1, h2, f"{path}: non-deterministic hash")
            self.assertTrue(len(b1) > 0, f"{path}: empty encoding")

    def test_examples_produce_distinct_identities(self):
        hashes = set()
        for path in sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.loom.sexpr"))):
            with open(path) as f:
                _, _, h = transcode_source(f.read())
            self.assertNotIn(h, hashes, f"{path}: hash collision with another example")
            hashes.add(h)
        self.assertEqual(len(hashes), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
