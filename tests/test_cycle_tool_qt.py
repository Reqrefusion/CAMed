"""Modeless cycle insertion using real Qt cursors and the native drill generator."""

import os
import types
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(
    os.environ.get('CAMEDITOR_QT_TESTS') == '1', 'Run tests/run_qt_checks.py with FreeCAD Python'
)
class CycleToolQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        from PySide import QtWidgets
        from freecad.camed import cycle_tool

        self.tool = cycle_tool
        self.owner = QtWidgets.QWidget()
        self.owner.editor = QtWidgets.QPlainTextEdit(self.owner)
        layout = QtWidgets.QVBoxLayout(self.owner)
        layout.addWidget(self.owner.editor)
        self.owner.editor.setPlainText('G21 G90\nG1 X10 F100\nG1 X20 F200\nM30')
        self.owner.job = types.SimpleNamespace(Stock=None)
        self.owner.is_current = Mock(return_value=True)
        self.owner.shutting_down = False
        self.owner.show()
        self.errors = []
        import sys

        hook = patch.object(sys, 'excepthook', side_effect=lambda typ, error, tb: self.errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)

    def tearDown(self):
        dialog = getattr(self.owner, 'cycle_dialog', None)
        if dialog is not None:
            dialog.reject()
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()
        self.assertEqual(self.errors, [])

    def open_tool(self):
        from freecad.camed import panel

        with patch.object(panel, 'show_panel', return_value=self.owner):
            self.tool.show_cycle_tool()
        self.app.processEvents()
        return self.owner.cycle_dialog

    def move_to(self, line):
        from PySide import QtGui

        cursor = QtGui.QTextCursor(self.owner.editor.document().findBlockByNumber(line))
        self.owner.editor.setTextCursor(cursor)

    def test_form_allows_editor_keyboard_navigation_and_reuses_open_window(self):
        from PySide import QtCore, QtTest, QtWidgets

        dialog = self.open_tool()
        self.assertFalse(dialog.isModal())
        self.assertIsNone(QtWidgets.QApplication.activeModalWidget())
        self.owner.editor.setFocus()
        QtTest.QTest.keyClick(self.owner.editor, QtCore.Qt.Key_Down)
        self.assertEqual(self.owner.editor.textCursor().blockNumber(), 1)
        QtTest.QTest.qWait(180)
        self.assertEqual('Insert before line 2', dialog.location.text())
        self.assertIs(self.open_tool(), dialog)

    def test_insert_uses_latest_cursor_and_modal_context_as_one_undo(self):
        dialog = self.open_tool()
        self.move_to(3)
        source = self.owner.editor.toPlainText()
        dialog.accept()  # No wait: acceptance must read the current cursor itself.
        updated = self.owner.editor.toPlainText()
        self.assertTrue(updated.startswith(source.rsplit('M30', 1)[0] + '(Drilling cycle)'))
        self.assertTrue(updated.endswith('M30'))
        self.assertIn('F200', updated[updated.index('(Drilling cycle)') :])
        self.assertIsNone(self.owner.cycle_dialog)
        self.owner.editor.undo()
        self.assertEqual(self.owner.editor.toPlainText(), source)

    def test_optional_tool_change_is_previewed_and_inserted_before_drilling(self):
        from freecad.camed.validation import preview

        dialog = self.open_tool()
        self.move_to(3)
        self.assertNotIn(' M6', dialog.block)
        dialog.tool_number.setValue(7)
        dialog.refresh()
        lines = dialog.block.splitlines()
        change = lines.index('T7 M6')
        self.assertTrue(lines[change - 1].startswith('G0 Z'))
        self.assertLess(change, next(i for i, line in enumerate(lines) if line.startswith('G81')))
        self.assertEqual(dialog.code.toPlainText(), dialog.block)
        dialog.accept()
        result = preview(self.owner.editor.toPlainText(), {7: 1})
        self.assertIsNone(result.error)
        self.assertEqual(result.states[-1].tool, 7)

    def test_source_edits_while_open_are_preserved_and_rechecked(self):
        dialog = self.open_tool()
        source = '(yeni açıklama)\nG21 G90\nG1 X30 F350\nM30'
        self.owner.editor.setPlainText(source)
        self.move_to(3)
        dialog.accept()
        updated = self.owner.editor.toPlainText()
        self.assertTrue(updated.startswith(source.rsplit('M30', 1)[0]))
        self.assertIn('F350', updated[updated.index('(Drilling cycle)') :])

    def test_invalid_location_can_be_corrected_without_reopening_form(self):
        from PySide import QtTest

        self.owner.editor.setPlainText('G21 G90\nM30\n')
        self.move_to(2)
        dialog = self.open_tool()
        self.assertFalse(dialog.insert_button.isEnabled())
        self.move_to(1)
        QtTest.QTest.qWait(180)
        self.assertTrue(dialog.insert_button.isEnabled())
        dialog.accept()
        self.assertIn('(Drilling cycle)', self.owner.editor.toPlainText())

    def test_closed_or_inactive_owner_cannot_receive_cycle(self):
        dialog = self.open_tool()
        source = self.owner.editor.toPlainText()
        self.owner.is_current.return_value = False
        dialog.accept()
        self.assertFalse(dialog.insert_button.isEnabled())
        self.assertEqual(self.owner.editor.toPlainText(), source)
        dialog.reject()
        self.assertIsNone(self.owner.cycle_dialog)
