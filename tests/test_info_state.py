"""Actual parser snapshots/readout semantics, without FreeCAD or GUI stubs."""

import unittest
from freecad.camed.validation import preview
from freecad.camed.info_state import readout, diagnostic


class ReadoutTests(unittest.TestCase):
    def test_modal_coordinates_and_feed_use_the_same_normalizer(self):
        result = preview('G20 G0 X1\nG91 G1 X.5 Z-.1 F10\nY1\n; comment', {1: 1}, 1)
        self.assertEqual(len(result.states), len(result.lines))
        for actual, expected in zip(result.states[2].position, (38.1, 25.4, -2.54)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(result.states[2].feed, 254)
        block = readout(result, 3)
        self.assertEqual(block.heading, 'Line 3 · G1 · T1')
        self.assertEqual(block.coordinates, 'X38.1 · Y25.4 · Z-2.54 mm')
        self.assertEqual(block.cutting, 'F254 · S—')
        comment = readout(result, 4)
        self.assertEqual(comment.coordinates, block.coordinates)
        self.assertIn('Comment', comment.heading)

    def test_preselected_tool_does_not_replace_active_tool_until_m6(self):
        result = preview('T6\nS6000 M3\nG1 X10 F800\nM6', {1: 1, 6: 1}, 1)
        before = readout(result, 3)
        self.assertIn('T1', before.heading)
        self.assertIn('T6 is preselected', before.tooltip)
        self.assertEqual(before.cutting, 'F800 · S6000 · M3')
        self.assertIn('T6', readout(result, 4).heading)
        self.assertNotIn('ön seçili', readout(result, 4).tooltip)

    def test_spindle_state_and_feed_only_blocks_are_retained(self):
        result = preview('G1 F450\nS2000 M4\nG1 X10\nM5\nM3\nM30\nS9999')
        self.assertEqual(result.states[0].feed, 450)
        self.assertIn('S2000 · M4', readout(result, 3).cutting)
        self.assertIn('S2000 · Stopped', readout(result, 4).cutting)
        self.assertIn('S2000 · M3', readout(result, 5).cutting)
        self.assertIn('S2000 · Stopped', readout(result, 6).cutting)
        self.assertEqual(result.states[-1].spindle, 2000)
        self.assertEqual(result.states[-1].kind, 'Program end')

    def test_error_suffix_shows_last_valid_position_without_fake_values(self):
        result = preview('G0 Z5\nG1 X10 F500\nG1 X\nG1 X999', {1: 1}, 1)
        self.assertEqual(len(result.states), 2)
        block = readout(result, 4)
        self.assertIn('Line 4 · Last valid: 2', block.heading)
        self.assertEqual(block.coordinates, 'X10 · Y0 · Z5 mm')
        self.assertIn('Line 3:', block.error)
        first_error = readout(preview('G1 X'), 1)
        self.assertEqual(first_error.coordinates, 'X— · Y— · Z— mm')
        self.assertEqual(first_error.cutting, 'F— · S—')

    def test_valid_prefix_before_error_still_has_its_own_block_info(self):
        result = preview('G0 Z5\nG1 X')
        block = readout(result, 1)
        self.assertIn('G0', block.heading)
        self.assertNotIn('Last valid', block.heading)
        self.assertIn('Line 2:', block.error)  # Global diagnostic remains visible

    def test_arc_dwell_and_comment_record_end_position_without_reparsing(self):
        result = preview('G0 X0 Y0\nG3 X10 Y0 I5 J0 F300\nG4 P1\n(comment)')
        self.assertEqual(result.states[1].position, (10, 0, 0))
        self.assertIn('G3', readout(result, 2).heading)
        self.assertEqual(result.states[2].position, (10, 0, 0))
        self.assertIn('Dwell', readout(result, 3).heading)
        self.assertEqual(result.states[-1].feed, 300)

    def test_default_missing_values_are_not_invented(self):
        block = readout(preview('; header'), 1)
        self.assertIn('T—', block.heading)
        self.assertEqual(block.cutting, 'F— · S—')
        self.assertEqual(readout(None, 7).heading, 'Line 7 · —')

    def test_diagnostics_find_errors_after_open_file_prefix(self):
        text = 'Açıldı: part.nc\nSatır 3: Eksik sözcük.\nÖnceki hareketler gösteriliyor.'
        badge, short, details = diagnostic(text)
        self.assertEqual(badge, 'Error · Line 3')
        self.assertEqual(short, 'Satır 3: Eksik sözcük.')
        self.assertEqual(details, text)

    def test_save_message_does_not_hide_current_code_error(self):
        badge, short, details = diagnostic('G-code kaydedildi: part.nc', 'Satır 3: Eksik sözcük.')
        self.assertEqual(badge, 'Error · Line 3')
        self.assertIn(short, details)
        self.assertIn('kaydedildi', details)

    def test_notices_and_waiting_are_compact_but_keep_full_details(self):
        text = 'Canlı 3B yol güncel.\nG54 makine ofset tablosu uygulanmıyor.'
        self.assertEqual(diagnostic(text), ('Notes (1)', '', text))
        self.assertEqual(diagnostic('Kod değişti; yol güncelleniyor…')[0], 'Updating')
        self.assertEqual(diagnostic('Close the tool editor first.')[0], 'Waiting')
        self.assertEqual(diagnostic('G-code kaydedildi: part.nc')[0], 'Saved')
        self.assertEqual(diagnostic('GL görünümü açılamadı: unavailable')[0], 'Error')
