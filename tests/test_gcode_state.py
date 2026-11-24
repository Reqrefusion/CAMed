import unittest
from freecad.camed.gcode_state import ProgramState
from freecad.camed.gcode_syntax import CodeError


class ProgramStateTests(unittest.TestCase):
    def test_modes_and_feed_update_without_moving_the_tool(self):
        state = ProgramState()
        state.apply_modes({'F': 10}, [20, 91, 18, 99], 1)
        self.assertEqual(
            (state.scale, state.absolute, state.plane, state.retract_mode), (25.4, False, 18, 99)
        )
        self.assertEqual(state.feed, 254)
        self.assertEqual(state.position, dict(X=0, Y=0, Z=0))

    def test_motion_and_source_snapshots_remain_independent(self):
        state = ProgramState(tool=1, selected_tool=1)
        self.assertEqual(list(state.block('G1 X10 F100', 1)), ['G1 X10 F100'])
        snapshot = state.snapshot('G1 X10 F100', 1)
        self.assertEqual(list(state.block('Y5', 2)), ['G1 Y5 F100'])
        self.assertEqual(snapshot.position, (10, 0, 0))
        self.assertEqual(state.position, dict(X=10, Y=5, Z=0))

    def test_each_program_owns_its_mutable_state(self):
        first, second = ProgramState(), ProgramState()
        list(first.block('G0 X20', 1))
        first.cycle_parameters['Q'] = 2
        self.assertEqual(second.position, dict(X=0, Y=0, Z=0))
        self.assertEqual(second.cycle_parameters, {})
        self.assertEqual(second.notices, [])

    def test_tool_preselection_does_not_change_active_tool(self):
        state = ProgramState(tool=1, selected_tool=1, tool_numbers={1: 1, 7: 1})
        list(state.block('T7', 1))
        self.assertEqual((state.tool, state.selected_tool), (1, 7))
        list(state.block('M6', 2))
        self.assertEqual(state.tool, 7)

    def test_program_end_ignores_incomplete_trailing_code(self):
        state = ProgramState()
        list(state.block('M30', 1))
        self.assertEqual(list(state.block('G1 X(', 2)), ['(after program end)'])

    def test_invalid_modal_group_is_rejected_before_moving(self):
        state = ProgramState()
        with self.assertRaises(CodeError):
            list(state.block('G0 G1 X20', 1))
        self.assertFalse(state.moved)
        self.assertIsNone(state.motion)

    def test_program_end_on_dwell_stops_following_motion(self):
        from freecad.camed.validation import preview

        for end in ('M2', 'M30'):
            with self.subTest(end=end):
                result = preview(f'G0 X1 M3\nG4 P1 {end}\nG1 X30 F100')
                self.assertIsNone(result.error)
                self.assertEqual(
                    result.lines, ['G0 X1', '(dwell; geometry unchanged)', '(after program end)']
                )
                self.assertTrue(result.states[1].ended)
                self.assertEqual(result.states[1].spindle_mode, 5)
                self.assertEqual(result.states[-1].position, (1, 0, 0))
