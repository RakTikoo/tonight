#!/usr/bin/env python3
"""Run the tonight test suite (stdlib unittest, no extra dependencies)."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

if __name__ == "__main__":
    suite = unittest.TestLoader().discover(
        os.path.join(ROOT, "tests"), top_level_dir=ROOT
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
