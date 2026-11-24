import unittest
from freecad.camed.validation import preview
from freecad.camed.tool_backend import sections


class ToolSectionsTests(unittest.TestCase):
    def parse(self, source):
        return preview(source, {1: 1, 6: 1, 8: 1}, 1)

    def test_preselection_waits_for_m6(self):
        result = self.parse('G0 X10 Z5\nT6\nG1 Z-1 F100\nM6\nG1 X20')
        self.assertIsNone(result.error)
        self.assertEqual(result.tools, [1, 1, 1, 6, 6])
        chunks = sections(result)
        self.assertEqual([n for n, _ in chunks], [1, 6])
        self.assertEqual(chunks[1][1][0], 'G0 X10.000000000000 Y0.000000000000 Z-1.000000000000')

    def test_same_block_change_applies_before_motion(self):
        result = self.parse('T6 M6 G0 X10 Z5\nG1 Z-1 F100\nT8 M6 G1 X20')
        self.assertEqual(result.tools, [6, 6, 8])
        self.assertEqual([n for n, _ in sections(result)], [6, 8])

    def test_unknown_tool_keeps_entire_program_and_source_tool(self):
        result = self.parse('G0 Z10\nT99 M6\nG1 X50')
        self.assertIsNone(result.error)
        self.assertEqual(len(result.lines), 3)
        self.assertEqual(result.tools, [1, 99, 99])
        self.assertEqual(result.notices, ['T99 is not defined in this job (line 2).'])
        self.assertEqual([s.display_tool for s in result.states], [1, 1, 1])

    def test_tool_selected_without_motion_can_supply_geometry_to_unknown_tool(self):
        result = self.parse('T6 M6\nT99 M6\nG1 X50 F100')
        self.assertEqual(result.tools, [6, 99, 99])
        self.assertEqual([s.display_tool for s in result.states], [6, 6, 6])

    def test_unknown_first_tool_never_borrows_a_future_tool(self):
        result = preview('T99 M6\nG1 X10 F100\nT6 M6\nG1 X20', {6: 1}, None)
        self.assertIsNone(result.error)
        self.assertEqual([s.display_tool for s in result.states], [None, None, 6, 6])
        self.assertEqual(result.notices, ['T99 is not defined in this job (line 1).'])

    def test_no_initial_tool_keeps_motion(self):
        result = preview('G0 Z10\nG1 X20 F100', {}, None)
        self.assertIsNone(result.error)
        self.assertEqual(result.tools, [None, None])
        self.assertEqual(result.notices, ['No initial tool is defined for the move on line 1.'])

    def test_duplicate_number_does_not_guess(self):
        result = preview('T6 M6\nG0 X10', {1: 1, 6: 2}, 1)
        self.assertEqual(result.error.line, 1)
        self.assertEqual(result.lines, [])

    def test_preamble_and_empty_tool_sections_do_not_simulate(self):
        result = self.parse('%\nT6 M6\nT8 M6\nG0 Z10\nM30')
        self.assertEqual([n for n, _ in sections(result)], [8])

    def test_incremental_inches_remain_continuous_between_tools(self):
        result = self.parse('G20 G91\nG0 X1 Z1\nT6 M6\nG1 X1 F10')
        chunks = sections(result)
        self.assertEqual([n for n, _ in chunks], [1, 6])
        self.assertIn('X25.400000000000', chunks[1][1][0])
        self.assertEqual(chunks[1][1][-1], 'G1 X50.8 F254')

    def test_program_end_does_not_execute_later_tool_change(self):
        result = self.parse('G0 Z5\nM30\nT99 M6')
        self.assertIsNone(result.error)
        self.assertEqual(result.tools, [1, 1, 1])

    def test_repeated_tool_can_return_after_other_tool(self):
        result = self.parse('T6 M6\nG0 Z5\nT8 M6\nG1 X10 F100\nT6 M6\nG1 X20')
        self.assertEqual([n for n, _ in sections(result)], [6, 8, 6])
