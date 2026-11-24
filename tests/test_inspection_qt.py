"""Opt-in real Qt lifecycle regression checks, with a FreeCADGui adapter."""

import os
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(
    os.environ.get('CAMEDITOR_QT_TESTS') == '1', 'Run tests/run_qt_checks.py with FreeCAD Python'
)
class InspectionQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import FreeCAD as App
        from PySide import QtWidgets, QtTest

        cls.App = App
        cls.QtTest = QtTest
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.main = QtWidgets.QMainWindow()

    def setUp(self):
        import sys
        import types

        self.gui = types.ModuleType('FreeCADGui')
        self.gui.getMainWindow = lambda: self.main
        self.gui.Control = types.SimpleNamespace(activeDialog=lambda: None)
        self.gui.Selection = Mock()
        scripts = types.ModuleType('PathScripts')
        scripts.PathUtils = types.SimpleNamespace(findParentJob=lambda op: None)
        self.modules = patch.dict(sys.modules, {'FreeCADGui': self.gui, 'PathScripts': scripts})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        from freecad.camed import panel as panel_module

        binding = patch.multiple(panel_module, Gui=self.gui, PathUtils=scripts.PathUtils)
        binding.start()
        self.addCleanup(binding.stop)
        from freecad.camed.panel import LivePanel

        class TestPanel(LivePanel):
            def ensure_simulation(self, *args, **kwargs):
                pass

            def attach_observer(self):
                pass

        self.doc = self.App.newDocument('InspectionLifecycleTest')
        self.addCleanup(self.App.closeDocument, self.doc.Name)
        op = self.doc.addObject('App::FeaturePython', 'Program')
        op.addProperty('App::PropertyStringList', 'Gcode')
        op.addProperty('App::PropertyString', 'LiveEditorSource')
        op.LiveEditorSource = '(SECTION A)\nG1 X10 F100'
        self.panel = TestPanel(op)
        from freecad.camed import inspection_tool

        self.tool = inspection_tool

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.main.hide()

    def open_sections(self):
        from PySide import QtCore

        self.main.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.panel)
        self.main.resize(540, 720)
        self.main.show()
        self.panel.show()
        self.app.processEvents()
        self.tool.toggle_sections(self.panel)
        self.app.processEvents()
        return self.panel.sections_pane

    def test_close_and_reopen_restores_selection_without_duplicate_registration(self):
        panel = self.panel
        self.assertTrue(panel.path_selection.attached)
        self.gui.Selection.addObserver.assert_called_once_with(panel.path_selection)
        panel.close()
        self.assertFalse(panel.path_selection.attached)
        panel.show()
        panel.set_active(True)
        panel.set_active(True)
        self.assertTrue(panel.path_selection.attached)
        self.assertEqual(self.gui.Selection.addObserver.call_count, 2)

    def test_workbench_deactivation_detaches_and_reactivation_restores_selection(self):
        panel = self.panel
        panel.set_active(False)
        panel.set_active(False)
        self.assertFalse(panel.path_selection.attached)
        self.gui.Selection.removeObserver.assert_called_once_with(panel.path_selection)
        panel.set_active(True)
        self.assertTrue(panel.path_selection.attached)
        self.assertEqual(self.gui.Selection.addObserver.call_count, 2)

    def test_inactive_editor_rejects_even_a_queued_selection_callback(self):
        panel = self.panel
        panel.set_active(False)
        panel.timer.stop()
        panel.path_selection.source = panel.editor.toPlainText()
        panel.path_selection.mapping = {panel.operation.Name: {1: 2}}
        with patch.object(self.tool, 'goto_line') as goto:
            panel.path_selection.addSelection(self.doc.Name, panel.operation.Name, '1 G1 X10', None)
        goto.assert_not_called()

    def test_closed_sections_do_not_scan_on_edits_and_refresh_when_reopened(self):
        dialog = self.open_sections()
        dialog.close()
        with patch.object(self.tool, 'sections', wraps=self.tool.sections) as scan:
            self.panel.editor.setPlainText('(SECTION B)\nG1 X20 F100')
            self.QtTest.QTest.qWait(250)
            scan.assert_not_called()
            self.assertFalse(dialog.timer.isActive())
            dialog.show()
            self.app.processEvents()
            self.assertEqual(scan.call_count, 1)
        self.assertIn('SECTION B', dialog.items.topLevelItem(0).text(0))
        dialog.close()

    def test_hiding_sections_cancels_a_pending_scan(self):
        dialog = self.open_sections()
        with patch.object(self.tool, 'sections', wraps=self.tool.sections) as scan:
            self.panel.editor.insertPlainText('; EDIT\n')
            self.assertTrue(dialog.timer.isActive())
            dialog.hide()
            self.assertFalse(dialog.timer.isActive())
            self.QtTest.QTest.qWait(250)
            scan.assert_not_called()

    def test_visible_sections_update_and_workbench_deactivation_closes_them(self):
        dialog = self.open_sections()
        self.panel.editor.setPlainText('(SECTION C)\nG1 X30 F100')
        self.QtTest.QTest.qWait(250)
        self.assertIn('SECTION C', dialog.items.topLevelItem(0).text(0))
        self.panel.set_active(False)
        self.assertFalse(dialog.isVisible())
        self.assertFalse(dialog.timer.isActive())

    def test_sections_stay_inside_editor_and_toggle_without_changing_source(self):
        from PySide import QtCore, QtWidgets

        source = self.panel.editor.toPlainText()
        pane = self.open_sections()
        self.assertFalse(pane.isWindow())
        self.assertIs(pane.parentWidget(), self.panel.program_splitter)
        self.assertEqual(self.panel.program_splitter.orientation(), QtCore.Qt.Horizontal)
        self.assertEqual(self.panel.program_splitter.indexOf(pane), 0)
        self.assertEqual(self.panel.program_splitter.indexOf(self.panel.code_area), 1)
        self.assertTrue(self.panel.editor_actions['Sections'].isChecked())
        self.assertTrue(self.panel.sections_tab.isChecked())
        self.QtTest.QTest.mouseClick(self.panel.sections_tab, QtCore.Qt.LeftButton)
        self.assertFalse(pane.isVisible())
        self.assertFalse(self.panel.editor_actions['Sections'].isChecked())
        self.assertFalse(self.panel.sections_tab.isChecked())
        self.assertTrue(self.panel.sections_tab.isVisible())
        self.QtTest.QTest.keyClick(self.panel.sections_tab, QtCore.Qt.Key_Space)
        self.assertIs(self.panel.sections_pane, pane)
        self.assertTrue(pane.isVisible())
        self.assertTrue(self.panel.sections_tab.isChecked())
        self.assertTrue(self.panel.editor_actions['Sections'].isChecked())
        self.assertEqual(self.panel.editor.toPlainText(), source)
        self.assertFalse(self.panel.findChildren(QtWidgets.QDialog))

    def test_cursor_highlight_and_single_click_navigation_use_real_source_lines(self):
        from PySide import QtCore

        self.panel.editor.setPlainText('(HAZIRLIK)\nG0 Z5\n(KABA)\nG1 X10 F100\n(FİNİŞ)\nG1 X20')
        pane = self.open_sections()
        self.tool.goto_line(self.panel, 6)
        self.assertEqual(pane.items.currentItem().text(0), 'FİNİŞ')
        with patch.object(self.tool, 'sections', wraps=self.tool.sections) as scan:
            pane.filter.setText('kaba')
            scan.assert_not_called()
        self.assertIsNone(pane.items.currentItem())
        item = pane.items.topLevelItem(0)
        rect = pane.items.visualItemRect(item)
        self.QtTest.QTest.mouseClick(
            pane.items.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center()
        )
        self.assertEqual(self.panel.editor.textCursor().blockNumber(), 2)
        self.assertEqual(pane.items.currentItem().data(0, QtCore.Qt.UserRole), 3)
        self.assertEqual(self.panel.editor.toPlainText().splitlines()[2], '(KABA)')
