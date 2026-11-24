import math
import unittest
from freecad.camed.validation import preview
from freecad.camed.timeline import boundaries, block_step


class TimelineTests(unittest.TestCase):
    def timeline(self, source, quality=10, dimension=40, diameters=None):
        result = preview(source, {1: 1, 6: 1}, 1)
        return boundaries(result, dimension, quality, diameters or {1: 6, 6: 20})

    def test_weights_distances_not_number_of_lines(self):
        ends, total = self.timeline('G0 Z0\nG1 X1\nG1 X10\n; comment')
        self.assertEqual(ends, [1, 3, 21, 21])
        self.assertEqual(total, 21)
        self.assertEqual(block_step(ends, 2) / total, 3 / 21)

    def test_comments_metadata_and_error_keep_last_valid_motion(self):
        ends, total = self.timeline('%\nG0 Z0\nG1 X10\nT6 M6\n; note\nG1 X\nG1 X100')
        self.assertEqual(ends, [0, 1, 21, 21, 21])
        self.assertEqual(block_step(ends, 6), total)
        self.assertEqual(block_step(ends, 99), total)
        self.assertEqual(block_step(ends, 0), 0)
        self.assertEqual(block_step([], 5), 0)

    def test_quality_and_stock_dimension_match_native_resolution(self):
        self.assertEqual(self.timeline('G0 X0\nG1 X10', quality=3, dimension=120)[1], 6)
        self.assertEqual(self.timeline('G0 X0\nG1 X10', quality=10, dimension=120)[1], 17)

    def test_large_radius_arc_and_small_radius_tool_use_native_steps(self):
        source = 'G0 X10 Y0\nG3 X0 Y10 I-10 J0'
        self.assertEqual(self.timeline(source)[1], 20 + int((math.pi / 2) / (math.pi / 90)) + 2)
        self.assertEqual(self.timeline('T6 M6\n' + source)[1], 25)
        self.assertEqual(self.timeline('T6 M6\n' + source, quality=3)[1], 17)

    def test_full_circle_and_zero_length_motion(self):
        self.assertEqual(self.timeline('G0 X10 Y0\nG2 I-10 J0')[1], 202)
        self.assertEqual(self.timeline('G0 X0\nG1 X0')[1], 2)
