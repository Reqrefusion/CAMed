"""Run opt-in Qt checks using FreeCAD's Python; no real user documents needed."""

import FreeCAD  # noqa: F401 - initialize the embedded interpreter before other imports
import os
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from freecad_test_environment import configure_test_paths

root = configure_test_paths()

import PySide6

sys.modules.setdefault('PySide', PySide6)
os.environ['CAMEDITOR_QT_TESTS'] = '1'
suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test_*_qt.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
