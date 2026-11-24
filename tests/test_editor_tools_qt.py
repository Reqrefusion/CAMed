"""Real Qt tests for selection-scoped CNC text edits and a button-free editor."""

import os
import unittest
import test_inspection_qt as lifecycle


@unittest.skipUnless(
    os.environ.get('CAMEDITOR_QT_TESTS') == '1', 'Run tests/run_qt_checks.py with FreeCAD Python'
)
class EditorToolsQtTests(unittest.TestCase):
    setUpClass = classmethod(lifecycle.InspectionQtTests.setUpClass.__func__)
    setUp = lifecycle.InspectionQtTests.setUp
    tearDown = lifecycle.InspectionQtTests.tearDown

    def select(self, source, start, end):
        from PySide import QtGui

        self.panel.editor.setPlainText(source)
        cursor = self.panel.editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QtGui.QTextCursor.KeepAnchor)
        self.panel.editor.setTextCursor(cursor)

    def test_editor_has_no_operation_or_playback_buttons_and_always_follows_cursor(self):
        from PySide import QtWidgets

        panel = self.panel
        for name in ('sim_button', 'gl_button', 'follow_line', 'quality', 'cycle_button'):
            self.assertFalse(hasattr(panel, name), name)
        self.assertFalse(panel.findChildren(QtWidgets.QPushButton))
        self.select('G0 Z5\nG1 X10 F100', 6, 6)
        self.assertEqual(panel.selected_source_line(), 2)

    def test_program_check_command_shortcut_and_window_are_removed(self):
        from freecad.camed.editor_actions import ACTION_SPECS, ACTION_GROUPS
        from freecad.camed import program_inspection

        self.assertNotIn('Inspect', ACTION_SPECS)
        self.assertNotIn('Inspect', self.panel.editor_actions)
        self.assertFalse(any('Inspect' in names for _, names in ACTION_GROUPS))
        self.assertFalse(any(action.shortcut().toString() == 'F7' for action in self.panel.actions()))
        self.assertFalse(hasattr(self.tool, 'InspectionDialog'))
        self.assertFalse(hasattr(self.tool, 'show_inspection'))
        self.assertFalse(hasattr(program_inspection, 'inspect_program'))
        self.assertFalse(hasattr(program_inspection, 'compatibility'))

    def test_number_actions_live_in_header_and_editor_uses_standard_context_menu(self):
        from PySide import QtCore, QtWidgets

        panel = self.panel
        header = panel.widget().layout().itemAt(0).layout()
        button = panel.number_menu_button
        self.assertIs(header.itemAt(0).widget(), panel.program_title)
        self.assertIs(header.itemAt(header.count() - 1).widget(), button)
        self.assertFalse(button.isHidden())
        self.assertIsNone(button.menu())
        self.assertEqual(button.arrowType(), QtCore.Qt.NoArrow)
        button.click()
        menu = self.app.activePopupWidget()
        self.assertIsInstance(menu, QtWidgets.QMenu)
        menu.hide()
        self.assertEqual(
            menu.actions(), [panel.editor_actions['Renumber'], panel.editor_actions['RemoveNumbers']]
        )
        self.assertEqual(panel.editor.contextMenuPolicy(), QtCore.Qt.DefaultContextMenu)
        self.assertFalse(panel.sections_tab.isHidden())
        self.assertEqual(panel.editor_actions['Sections'].shortcut().toString(), 'Ctrl+Alt+O')

    def test_number_removal_respects_selected_lines_and_has_one_undo_step(self):
        source = '/1 N10 G0 Z5\nN20 G1 X10 F100\nN30 M30'
        self.select(source, len('/1 N10 G0 Z5\n'), len('/1 N10 G0 Z5\nN20 G1 X10 F100\n'))
        self.panel.editor_actions['RemoveNumbers'].trigger()
        self.assertEqual(self.panel.editor.toPlainText(), '/1 N10 G0 Z5\nG1 X10 F100\nN30 M30')
        self.panel.editor.undo()
        self.assertEqual(self.panel.editor.toPlainText(), source)
        self.select(source, 0, 0)
        self.panel.editor_actions['RemoveNumbers'].trigger()
        self.assertEqual(self.panel.editor.toPlainText(), '/1 G0 Z5\nG1 X10 F100\nM30')
        self.panel.editor_actions['Renumber'].trigger()
        self.assertEqual(self.panel.editor.toPlainText(), source)

    def test_search_tab_shortcuts_and_switching_between_side_panes(self):
        from PySide import QtCore, QtWidgets
        from freecad.camed.editor_actions import ACTION_SPECS, ACTION_GROUPS

        for name in ('Find', 'Replace', 'Comment', 'Duplicate', 'Goto', 'Compare'):
            self.assertNotIn(name, ACTION_SPECS)
            self.assertNotIn(name, self.panel.editor_actions)
            self.assertFalse(any(name in names for _, names in ACTION_GROUPS))
        source = "G1 X10 F100\nG1 X20\nG1 X10"
        self.select(source, 0, 0)
        self.main.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.panel)
        self.main.show()
        self.main.activateWindow()
        self.panel.show()
        self.panel.editor.setFocus()
        self.app.processEvents()
        self.QtTest.QTest.qWait(40)
        self.QtTest.QTest.keyClick(self.panel.editor, QtCore.Qt.Key_F, QtCore.Qt.ControlModifier)
        bar = self.panel.find_bar
        self.assertTrue(bar.isVisible())
        self.assertFalse(bar.isWindow())
        self.assertIs(bar.parentWidget(), self.panel.program_splitter)
        self.assertTrue(self.panel.search_tab.isChecked())
        self.assertTrue(bar.replacement.isVisible())
        self.assertTrue(bar.query.hasFocus())
        bar.query.setText('X10')
        self.QtTest.QTest.keyClick(bar.query, QtCore.Qt.Key_Return)
        self.assertEqual(self.panel.editor.textCursor().blockNumber(), 0)
        self.QtTest.QTest.keyClick(bar.query, QtCore.Qt.Key_Return)
        self.assertEqual(self.panel.editor.textCursor().blockNumber(), 2)
        self.QtTest.QTest.keyClick(bar.query, QtCore.Qt.Key_Return, QtCore.Qt.ShiftModifier)
        self.assertEqual(self.panel.editor.textCursor().blockNumber(), 0)
        self.QtTest.QTest.keyClick(bar.query, QtCore.Qt.Key_H, QtCore.Qt.ControlModifier)
        self.assertIs(self.panel.find_bar, bar)
        self.assertTrue(bar.replacement.hasFocus())
        self.QtTest.QTest.keyClick(bar.query, QtCore.Qt.Key_Escape)
        self.assertFalse(bar.isVisible())
        self.assertFalse(self.panel.search_tab.isChecked())
        self.panel.search_tab.click()
        self.assertTrue(bar.isVisible())
        self.panel.sections_tab.click()
        self.assertFalse(bar.isVisible())
        self.assertTrue(self.panel.sections_pane.isVisible())
        self.panel.search_tab.click()
        self.assertTrue(bar.isVisible())
        self.assertFalse(self.panel.sections_pane.isVisible())
        self.assertEqual(bar.query.text(), 'X10')
        self.panel.search_tab.click()
        self.assertFalse(bar.isVisible())
        self.assertFalse(self.panel.findChildren(QtWidgets.QDialog))

    def test_scoped_replace_handles_growing_and_shrinking_values_without_touching_other_blocks(self):
        from freecad.camed.editor_tools import FindPane

        for replacement in ('X200', 'X2'):
            source = 'G1 X10\nG1 X10\nG1 X10\nM30'
            self.select(source, 7, len('G1 X10\nG1 X10\nG1 X10'))
            dialog = FindPane(self.panel)
            dialog.capture_selection()
            self.assertTrue(dialog.scope.isChecked())
            dialog.query.setText('X10')
            dialog.replacement.setText(replacement)
            dialog.replace_all()
            self.assertEqual(
                self.panel.editor.toPlainText(), f'G1 X10\nG1 {replacement}\nG1 {replacement}\nM30'
            )
            self.assertIn('2 matches', dialog.message.text())
            self.panel.editor.undo()
            self.assertEqual(self.panel.editor.toPlainText(), source)
            dialog.close()

    def test_scoped_find_wraps_within_selection_and_single_replace_rejects_outside_match(self):
        from freecad.camed.editor_tools import FindPane

        source = 'G1 X10\nG1 X10\nG1 X10'
        self.select(source, 7, len(source))
        dialog = FindPane(self.panel)
        dialog.capture_selection()
        dialog.query.setText('X10')
        dialog.replacement.setText('X20')
        for backwards in (False, True, False, False):
            self.assertTrue(dialog.find(backwards))
            self.assertGreaterEqual(self.panel.editor.textCursor().selectionStart(), 7)
        from PySide import QtGui

        cursor = self.panel.editor.textCursor()
        cursor.setPosition(3)
        cursor.setPosition(6, QtGui.QTextCursor.KeepAnchor)
        self.panel.editor.setTextCursor(cursor)
        dialog.replace_one()
        self.assertEqual(self.panel.editor.toPlainText(), source)
        dialog.close()


@unittest.skipUnless(os.environ.get('CAMEDITOR_QT_TESTS') == '1', 'Requires Qt')
class EditorSelectionQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        from PySide import QtWidgets

        self.owner = QtWidgets.QWidget()
        self.owner.program_area = self.owner
        layout = QtWidgets.QVBoxLayout(self.owner)
        splitter = self.owner.program_splitter = QtWidgets.QSplitter(self.owner)
        self.owner.search_tab = QtWidgets.QToolButton(self.owner)
        self.editor = self.owner.editor = self.owner.code_area = QtWidgets.QPlainTextEdit()
        splitter.addWidget(self.editor)
        layout.addWidget(splitter)
        self.owner.resize(640, 260)
        self.owner.show()
        self.app.processEvents()
        self.addCleanup(self.owner.deleteLater)
        self.addCleanup(self.owner.close)

    def test_reopening_search_uses_new_selection_and_clears_obsolete_scope(self):
        from PySide import QtGui
        from freecad.camed.editor_tools import open_search

        self.editor.setPlainText('G1 X1\nG1 X2\nM30')
        cursor = self.editor.textCursor()
        cursor.setPosition(11, QtGui.QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        open_search(self.owner)
        pane = self.owner.find_bar
        pane.query.setText('G1')
        self.assertTrue(pane.scope.isChecked())
        self.assertTrue(pane.find())
        open_search(self.owner, replace=True)
        self.assertEqual(pane.bounds(), (0, 11))
        pane.dismiss()
        cursor.setPosition(12)
        cursor.setPosition(15, QtGui.QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        open_search(self.owner)
        self.assertEqual(pane.query.text(), 'M30')
        self.assertFalse(pane.scope.isChecked())
        self.assertTrue(pane.find())
        pane.dismiss()
        cursor.clearSelection()
        self.editor.setTextCursor(cursor)
        open_search(self.owner)
        self.assertTrue(pane.scope.isHidden())
        self.assertEqual(pane.bounds(), (0, 15))

    def test_hover_after_non_bmp_comment_uses_the_word_under_the_pointer(self):
        from PySide import QtCore, QtGui, QtWidgets
        from unittest.mock import patch
        from freecad.camed.inspection_tool import HoverHelp

        self.editor.setPlainText('(🔧🔧) G1 X5')
        cursor = self.editor.textCursor()
        cursor.setPosition(7)  # UTF-16 offset of G, after two surrogate pairs.
        viewport = self.editor.viewport()
        pos = self.editor.cursorRect(cursor).topLeft()
        event = QtGui.QHelpEvent(QtCore.QEvent.ToolTip, pos, viewport.mapToGlobal(pos))
        observer = HoverHelp(self.owner)
        with patch.object(QtWidgets.QToolTip, 'showText') as show:
            self.app.sendEvent(viewport, event)
        self.assertTrue(show.call_args.args[1].startswith('G1:'))
