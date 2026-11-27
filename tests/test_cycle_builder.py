import unittest
from dataclasses import replace
from freecad.camed.cycle_builder import CycleSpec, build_block, insertion_context


class CycleBuilderTests(unittest.TestCase):
    def test_defaults_and_all_supported_cycles(self):
        for cycle in (73, 81, 82, 83):
            replace(CycleSpec(), cycle=cycle).validate()

    def test_bad_dimensions_and_feed_are_rejected(self):
        for values in (
            {'depth': 2},
            {'clearance': 1},
            {'feed': 0},
            {'feed': float('nan')},
            {'holes': ()},
            {'holes': ((float('inf'), 0),)},
            {'cycle': 84},
            {'return_mode': 0},
            {'tool_number': -1},
            {'tool_number': 2.5},
            {'tool_number': 10001},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(CycleSpec(), **values).validate()

    def test_peck_and_dwell_checks_apply_to_their_cycle(self):
        for values in (
            {'cycle': 83, 'peck': 0},
            {'cycle': 73, 'peck': 0.000001},
            {'cycle': 82, 'dwell': 0},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(CycleSpec(), **values).validate()
        replace(CycleSpec(), cycle=81, peck=0, dwell=0).validate()

    def test_values_that_become_invalid_at_output_precision_are_rejected(self):
        for spec, message in (
            (replace(CycleSpec(), depth=1.9999), "Hole bottom"),
            (replace(CycleSpec(), feed=0.0001), "Feed rate"),
            (replace(CycleSpec(), cycle=82, dwell=0.0001), "Dwell"),
        ):
            with self.subTest(spec=spec), self.assertRaisesRegex(ValueError, message):
                build_block(spec)

    def test_prefix_modes_are_captured_for_restoring_following_program(self):
        text = 'G20 G91 G18 G99\nG1 X1 F10\nY1\nM30'
        start, context = insertion_context(text, text.index('Y1') + 1)
        self.assertEqual(start, text.index('Y1'))
        self.assertEqual(context.scale, 25.4)
        self.assertFalse(context.absolute)
        self.assertEqual(context.plane, 18)
        self.assertEqual(context.retract_mode, 99)
        self.assertEqual(context.modal_motion, 1)
        self.assertEqual(context.feed, 254)
        self.assertEqual(context.position, (25.4, 0, 0))

    def test_insertion_before_program_end_is_allowed_but_after_is_not(self):
        text = 'G0 Z5\nM30\n'
        self.assertEqual(insertion_context(text, text.index('M30'))[0], text.index('M30'))
        with self.assertRaises(ValueError):
            insertion_context(text, len(text))
        with self.assertRaises(ValueError):
            insertion_context('%\nG0 Z5\n%\n', 12)

    def test_error_before_insertion_is_refused_but_error_after_is_untouched(self):
        with self.assertRaises(ValueError):
            insertion_context('G1 X\nG0 Z5', 6)
        self.assertEqual(insertion_context('G1 X\nG0 Z5', 0)[0], 0)

    def test_empty_and_unicode_sources_insert_at_whole_line_boundary(self):
        self.assertEqual(insertion_context('', 0)[0], 0)
        text = '(🛠 ölçü)\nG0 Z5\nM30'
        start, context = insertion_context(text, text.index('G0') + 3)
        self.assertEqual(start, text.index('G0'))
        self.assertEqual(context.position, (0, 0, 0))
