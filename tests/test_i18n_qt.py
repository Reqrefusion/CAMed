"""Exercise the compiled Qt catalog through FreeCAD.Qt.translate."""

import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get('CAMEDITOR_QT_TESTS') == '1', 'Run tests/run_qt_checks.py with FreeCAD Python'
)
class TranslationQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_qt_catalog_translates_labels_errors_and_preserves_generated_code(self):
        from PySide import QtCore
        from freecad.camed.i18n import tr
        from freecad.camed.cycle_builder import build_block, CycleSpec
        from freecad.camed.validation import preview
        from freecad.camed.info_state import diagnostic, readout
        from test_cycle_tool_qt import CycleToolQtTests

        source = build_block(CycleSpec())
        self.assertEqual(tr('Insert code'), 'Insert code')
        translator = QtCore.QTranslator()
        catalog = (
            Path(__file__).resolve().parents[1]
            / 'freecad/camed/resources/translations/CAMed_tr.qm'
        )
        self.assertTrue(translator.load(str(catalog)))
        self.app.installTranslator(translator)
        try:
            self.assertEqual(tr('Insert code'), 'Kodu ekle')
            self.assertEqual(tr('Toolpath updated.'), 'Takım yolu güncellendi.')
            self.assertEqual(build_block(CycleSpec()), source)
            result = preview('G1 X')
            self.assertTrue(str(result.error).startswith('Satır 1:'))
            self.assertEqual(diagnostic(str(result.error))[0], 'Hata · Satır 1')
            self.assertEqual(diagnostic('Takım yolu güncelleniyor…')[0], 'Güncelleniyor')
            self.assertEqual(diagnostic('G-code kaydedildi: a.nc')[0], 'Kaydedildi')
            from freecad.camed.info_panel import InfoPanel

            panel = InfoPanel()
            source = 'T4\nM6 G0 Z5\nT4 M6\nG1 X1 F100'
            result = preview(source, {1: 1}, 1)
            self.assertTrue(result.can_simulate)
            self.assertEqual(result.notices, ['T4 takımı bu işte tanımlı değil (satır 1).'])
            panel.set_block(readout(result, 1), result.notices)
            panel.setText(tr('Simulation updated.'))
            self.assertEqual(panel.details_button.text(), 'Uyarılar')
            self.assertIn(result.notices[0], panel.details_label.text())
            configured = preview(source, {1: 1, 4: 1}, 1)
            panel.set_block(readout(configured, 1), configured.notices)
            self.assertNotIn('T4', panel.details_label.text())
            self.assertNotEqual(panel.details_button.text(), 'Uyarılar')
            # Build a real form while the Turkish translator is active.
            fixture = CycleToolQtTests()
            fixture.app = self.app
            fixture.setUp()
            try:
                dialog = fixture.open_tool()
                self.app.processEvents()
                self.assertEqual(dialog.insert_button.text(), 'Kodu ekle')
                self.assertEqual(dialog.location.text(), '1. satırın önüne ekle')
                dialog.preview_toggle.setChecked(True)
                self.assertEqual(dialog.code.toPlainText(), dialog.block)
            finally:
                fixture.tearDown()
                fixture.doCleanups()
        finally:
            self.app.removeTranslator(translator)
        self.assertEqual(tr('Insert code'), 'Insert code')
        self.assertTrue(str(preview('G1 X').error).startswith('Line 1:'))

    def test_registration_uses_freecad_language_path(self):
        from freecad.camed.i18n import register_translations

        calls = []
        gui = types.ModuleType('FreeCADGui')
        gui.addLanguagePath = lambda path: calls.append(('path', Path(path)))
        gui.updateLocale = lambda: calls.append(('update', None))
        with patch.dict(sys.modules, {'FreeCADGui': gui}):
            register_translations()
        self.assertTrue((calls[0][1] / 'CAMed_tr.qm').is_file())
        self.assertEqual(calls[1], ('update', None))
