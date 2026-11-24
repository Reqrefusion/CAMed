"""Run from the FreeCAD distribution's python.exe (no GUI or user files needed)."""

import FreeCAD  # noqa: F401 - initialize the embedded interpreter before other imports
import os
import unittest

from freecad_test_environment import configure_test_paths

root = configure_test_paths()

os.environ['CAMEDITOR_FREECAD_TESTS'] = '1'
suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test_freecad_runtime.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
