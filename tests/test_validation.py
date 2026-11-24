import unittest
from freecad.camed.validation import prepare, preview, CodeError


class ValidationTests(unittest.TestCase):
    def test_unfinished_last_line_retains_updated_prefix(self):
        result = preview("G21\nG90\nG1 X25 F300\nG0 Z")
        self.assertEqual(result.error.line, 4)
        self.assertEqual(result.lines[-1], "G1 X25 F300")
        self.assertTrue(result.has_motion)

    def test_invalid_middle_line_does_not_execute_later_lines(self):
        result = preview("G1 X5\nG41\nG1 X10")
        self.assertEqual(result.lines, ["G1 X5"])
        self.assertEqual(result.error.line, 2)

    def test_first_line_error_has_no_motion(self):
        result = preview("G0 Z")
        self.assertEqual(result.lines, [])
        self.assertFalse(result.has_motion)

    def test_completed_prefix_restores_full_program(self):
        result = preview("G1 X25 F300\nG0 Z5")
        self.assertIsNone(result.error)
        self.assertEqual(result.lines, prepare("G1 X25 F300\nG0 Z5"))

    def test_line_endings_preserve_motion_blank_lines_and_error_numbers(self):
        for end in ('\r', '\n', '\r\n'):
            result = preview(end.join(['G0 Z5', 'G1 X4 F80', '', '']))
            self.assertIsNone(result.error)
            self.assertEqual(result.lines[:2], ['G0 Z5', 'G1 X4 F80'])
            self.assertEqual([s.source_line for s in result.states], [1, 2, 3, 4])
        self.assertEqual(preview('G0 Z5\r\n\rG1 X').error.line, 3)

    def test_explicit_lines_and_comment_mapping(self):
        text = "G21\nG90\n; comment\nN10 G0 X0 Y0 Z5\nG1 Z-1 F100\n"
        result = prepare(text)
        self.assertEqual(len(result), 6)
        self.assertEqual(result[3], "G0 X0 Y0 Z5")
        self.assertEqual(result[4], "G1 Z-1 F100")

    def test_unknown_geometry_semantics_stop_the_prefix(self):
        for text in ("G18\nG2 X10 I5", "G41", "G83 X1 Y2 Z-5 R2 Q1", "G53 G0 X0", "G92 X0"):
            with self.subTest(text=text), self.assertRaises(CodeError):
                prepare(text)

    def test_partial_and_unknown_input_are_rejected(self):
        for text in ("G1 X", "G1 X1 X2", "G1 X1 !", "G1 X1 F0", "G90 G91", "G0 G1 X1", "M98 P100"):
            with self.subTest(text=text), self.assertRaises(CodeError):
                prepare(text)

    def test_valid_arc_and_full_circle(self):
        prepare("G0 X0 Y0\nG2 X10 Y0 I5 J0 F300")
        prepare("G0 X0 Y0\nG3 I5 J0 F300")

    def test_invalid_arc(self):
        for text in ("G2 X10 I2", "G2 X11 R5", "G2 R5", "G2 X1 I0 J0"):
            with self.subTest(text=text), self.assertRaises(CodeError):
                prepare(text)

    def test_user_facing_program_header_and_modal_raster(self):
        source = "%1049\n(MAKINE PARCASI ISI)\nG54(SOL ALT KOSE SIFIR)\nT4 M6\nS1200 M03\nG0 X-20 Y-20\nZ20\nG1 X-20 Y-20 Z-3 F1000\nX220\nY0\nX-20\nY20\nM30\nG0 X999"
        result = preview(source)
        self.assertIsNone(result.error)
        self.assertIn("G0 Z20", result.lines)
        self.assertIn("G1 X220 F1000", result.lines)
        self.assertIn("G1 Y0 F1000", result.lines)
        self.assertIn("G1 X-20 F1000", result.lines)
        self.assertFalse(any("X999" in line for line in result.lines))
        self.assertTrue(result.notices)

    def test_compact_words_multiple_modal_groups_and_incremental_positions(self):
        lines = prepare("N10G21G90G17G0X10Y20\nG91G1X5Y-5F200\nX2\nG90X0")
        self.assertEqual(lines, ["G0 X10 Y20", "G1 X15 Y15 F200", "G1 X17 F200", "G1 X0 F200"])

    def test_inch_coordinates_feed_and_modal_motion_are_normalized(self):
        lines = prepare("G20 G90 G0 X1\nG1 Z-.1 F10\nX2")
        self.assertEqual(lines, ["G0 X25.4", "G1 Z-2.54 F254", "G1 X50.8 F254"])

    def test_feed_only_block_and_program_number(self):
        lines = prepare("%\nO1049\nG1 F300\nX10\n%\nX20")
        self.assertEqual(lines[3], "G1 X10 F300")
        self.assertNotIn("G1 X20 F300", lines)

    def test_semicolon_inside_parenthesis_is_comment_text(self):
        self.assertEqual(prepare("G0 X1 (note; more note) ; tail"), ["G0 X1"])

    def test_line_number_only_comments_and_bom_are_accepted(self):
        result = preview("\ufeff%1049\nN10\n(comment)\nG0 X1")
        self.assertIsNone(result.error)
        self.assertEqual(len(result.lines), 4)

    def test_radius_arcs_and_helix(self):
        result = prepare("G0 X0 Y0\nG2 X10 R5 Z2")
        self.assertEqual(result[-1], "G2 X10 Z2 I5 J0")

    def test_radius_sign_selects_major_or_minor_arc(self):
        minor = prepare("G2 X10 R10")[-1]
        major = prepare("G2 X10 R-10")[-1]
        self.assertIn("J-", minor)
        self.assertNotIn("J-", major)

    def test_absolute_arc_center_is_converted_to_relative_ij(self):
        lines = prepare("G0 X10 Y0\nG90.1 G3 X20 I15 J0")
        self.assertEqual(lines[-1], "G3 X20 I5 J0")

    def test_work_offset_switch_is_not_silently_assumed_after_motion(self):
        result = preview("G54\nG0 X10\nG55\nX20")
        self.assertEqual(result.error.line, 3)
        self.assertFalse(any("X20" in line for line in result.lines))

    def test_header_lines_are_not_reported_as_a_zero_line_failure(self):
        result = preview("%1049\nG54\nT4 M6\nS1200 M03\nG0 X")
        self.assertEqual(result.error.line, 5)
        self.assertEqual(len(result.lines), 4)

    def test_modal_rapid_after_feed_has_no_cutting_feed_word(self):
        self.assertEqual(prepare("G1 X5 F100\nG0 Z10\nX0")[-1], "G0 X0")

    def test_non_xy_plane_does_not_block_linear_motion(self):
        self.assertEqual(prepare("G18\nG0 X10 Z2")[-1], "G0 X10 Z2")

    def test_implicit_work_offset_switch_after_motion_is_blocked(self):
        self.assertEqual(preview("G0 X10\nG55\nX20").error.line, 2)


if __name__ == "__main__":
    unittest.main()
