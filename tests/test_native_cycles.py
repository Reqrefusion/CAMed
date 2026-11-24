"""Exercise the installed FreeCAD Python expander; only Path.Command is adapted.
Set FREECAD_CAM_ROOT to the distribution's Mod/CAM directory to enable.
"""

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
from freecad.camed.validation import preview
from freecad.camed.timeline import boundaries, block_step
from freecad.camed.info_state import readout

ROOT = os.environ.get('FREECAD_CAM_ROOT')


class Command:
    def __init__(self, name, parameters=None, annotations=None):
        self.Name = name
        self.Parameters = parameters or {}
        self.Annotations = annotations or {}

    def toGCode(self):
        return self.Name + ' ' + str(self.Parameters)


@unittest.skipUnless(ROOT, 'Set FREECAD_CAM_ROOT for native cycle integration tests')
class NativeCyclesTests(unittest.TestCase):
    def setUp(self):
        root = Path(ROOT)
        path = types.ModuleType('Path')
        path.Command = Command
        path.Log = Mock()
        path.Log.Level.INFO = 1
        path.Geom = types.SimpleNamespace(CmdMoveDrill=['G73', 'G81', 'G82', 'G83', 'G85'])
        modules = {
            'Path': path,
            'Path.Base': types.ModuleType('Path.Base'),
            'Path.Post': types.ModuleType('Path.Post'),
            'FreeCAD': types.ModuleType('FreeCAD'),
        }
        self.patch = patch.dict(sys.modules, modules)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        for name, rel in (
            ('Constants', 'Constants.py'),
            ('Path.Base.MachineState', 'Path/Base/MachineState.py'),
            ('Path.Post.CAMErrors', 'Path/Post/CAMErrors.py'),
            ('Path.Post.DrillCycleExpander', 'Path/Post/DrillCycleExpander.py'),
        ):
            spec = importlib.util.spec_from_file_location(name, root / rel)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)

    def parse(self, code):
        result = preview(code, {1: 1}, 1)
        self.assertIsNone(result.error, str(result.error))
        self.assertEqual(len(result.lines), len(result.states))
        self.assertEqual(len(result.lines), len(result.tools))
        return result

    def test_g81_modal_holes_keep_source_line_and_initial_plane(self):
        result = self.parse('G0 Z10\nG99 G81 X5 Y6 Z-4 R2 F100\nX20\nG98 X30\nG80\nG0 Z15')
        self.assertEqual(readout(result, 2).coordinates, 'X5 · Y6 · Z2 mm')
        self.assertEqual(readout(result, 3).coordinates, 'X20 · Y6 · Z2 mm')
        self.assertEqual(readout(result, 4).coordinates, 'X30 · Y6 · Z10 mm')
        self.assertEqual(result.states[-1].position, (30, 6, 15))
        self.assertGreater(sum(s.source_line == 2 for s in result.states), 1)

    def test_g83_pecks_are_native_and_timeline_is_per_source_line(self):
        result = self.parse('G0 Z5\nG83 X10 Z-5 R1 Q2 F100\nG80\nG0 X20')
        feeds = [s.position[2] for line, s in zip(result.lines, result.states) if line.startswith('G1 ')]
        self.assertEqual(feeds, [-1, -3, -5])
        ends, total = boundaries(result, 40, 10, {1: 6})
        self.assertEqual(len(ends), 4)
        self.assertEqual(ends[1], ends[2])
        self.assertEqual(block_step(ends, 4), total)
        self.assertEqual(readout(result, 4).coordinates, 'X20 · Y0 · Z5 mm')

    def test_g73_and_g82_dwell_are_supported(self):
        for cycle in ('G73 Z-4 R1 Q1', 'G82 Z-4 R1 P.2'):
            result = self.parse('G0 Z5\n' + cycle + ' F100\nG80')
            self.assertEqual(readout(result, 2).coordinates, 'X0 · Y0 · Z5 mm')
        self.assertIn('(dwell; geometry unchanged)', result.lines)

    def test_inches_are_normalized_before_native_expansion(self):
        result = self.parse('G20 G0 Z1\nG81 X1 Z-.2 R.1 F10\nG80')
        self.assertEqual(readout(result, 2).coordinates, 'X25.4 · Y0 · Z25.4 mm')
        self.assertTrue(any('Z-5.08' in line for line in result.lines))
        self.assertTrue(any('F254' in line for line in result.lines))

    def test_cycle_errors_never_publish_half_a_hole(self):
        for block in (
            'G83 Z-5 R1 Q0 F100',
            'G81 Z2 R1 F100',
            'G83 Z-5 R1 Q.000001 F100',
            'G81 Z-5 F100',
            'G18 G81 Z-5 R1 F100',
            'G91 G81 Z-5 R1 F100',
        ):
            result = preview('G0 Z5\n' + block + '\nG0 X999', {1: 1}, 1)
            self.assertIsNotNone(result.error, block)
            self.assertEqual(result.error.line, 2)
            self.assertEqual(result.lines, ['G0 Z5'])

    def test_g80_cancels_modal_drilling_and_program_end_stops(self):
        result = preview('G0 Z5\nG81 Z-5 R1 F100\nG80\nX10', {1: 1}, 1)
        self.assertEqual(result.error.line, 4)
        result = self.parse('G0 Z5\nG81 Z-5 R1 F100 M30\nX999')
        self.assertEqual(result.lines[-1], '(after program end)')
