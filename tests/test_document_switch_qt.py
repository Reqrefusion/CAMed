"""Real Qt/FreeCAD document handoffs; no interaction with the user's FreeCAD."""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import test_inspection_qt as lifecycle


@unittest.skipUnless(
    os.environ.get('CAMEDITOR_QT_TESTS') == '1', 'Run tests/run_qt_checks.py with FreeCAD Python'
)
class DocumentSwitchQtTests(unittest.TestCase):
    setUpClass = classmethod(lifecycle.InspectionQtTests.setUpClass.__func__)

    def setUp(self):
        from freecad.camed import panel, editor_documents

        self.module, self.documents = panel, editor_documents
        self.names = []
        self.errors = []
        gui = types.ModuleType('FreeCADGui')
        gui.getMainWindow = lambda: self.main
        gui.Control = types.SimpleNamespace(activeDialog=lambda: None)
        gui.Selection = Mock()
        gui.Selection.getSelection.return_value = []
        scripts = types.ModuleType('PathScripts')
        scripts.PathUtils = types.SimpleNamespace(findParentJob=lambda op: None)
        self.patches = [
            patch.dict(sys.modules, {'FreeCADGui': gui, 'PathScripts': scripts}),
            patch.object(panel, 'Gui', gui),
            patch.object(panel, 'PathUtils', scripts.PathUtils),
            patch.object(sys, 'excepthook', side_effect=lambda typ, value, tb: self.errors.append(value)),
        ]
        base = panel.LivePanel

        class TestPanel(base):
            def ensure_simulation(self, *args, **kwargs):
                pass

        self.patches.append(patch.object(panel, 'LivePanel', TestPanel))
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        panel._panel = None
        self.main.show()

    def tearDown(self):
        tracker = self.documents._tracker
        if tracker is not None:
            tracker.timer.stop()
            tracker.dispose()
            tracker.timer.deleteLater()
        owner = self.module._panel
        if owner is not None:
            owner.close()
            owner.deleteLater()
        self.module._panel = None
        self.app.processEvents()
        for name in self.names:
            if name in self.App.listDocuments():
                self.App.closeDocument(name)
        self.app.processEvents()
        self.main.hide()
        self.assertEqual(self.errors, [])

    def program(self, label, source):
        doc = self.App.newDocument(label)
        self.names.append(doc.Name)
        return doc, self.add_program(doc, source)

    def add_program(self, doc, source):
        op = doc.addObject('App::FeaturePython', 'Program')
        op.addProperty('App::PropertyStringList', 'Gcode')
        op.addProperty('App::PropertyString', 'LiveEditorSource')
        op.addProperty('App::PropertyBool', 'LiveEditorManaged')
        op.LiveEditorManaged = True
        op.LiveEditorSource = source
        return op

    def settle(self):
        self.QtTest.QTest.qWait(70)

    def test_open_uses_selected_program_in_same_document(self):
        doc, first = self.program('TwoPrograms', 'G0 X1')
        second = self.add_program(doc, 'G0 X2')
        owner = self.module.show_panel(operation=first)
        owner.editor.setPlainText('G0 X10')
        self.module.Gui.Selection.getSelection.return_value = [second]
        # This fixture uses standalone operations. Stand in for native Job
        # validation when the editor takes its normal session-opening path.
        sessions = types.ModuleType('freecad.camed.sessions')
        sessions.prepare_session = lambda: (second, False)
        with patch.dict(sys.modules, {sessions.__name__: sessions}):
            opened = self.module.show_panel()
        self.assertIs(opened.operation, second)
        self.assertEqual(opened.editor.toPlainText(), 'G0 X2')
        self.assertEqual(first.LiveEditorSource, 'G0 X10')
        self.module.Gui.Selection.getSelection.return_value = []
        self.assertIs(self.module.show_panel(), opened)

    def test_save_and_export_after_close_read_the_document(self):
        from freecad.camed import file_io

        doc, op = self.program('ClosedPanel', 'G0 X1')
        owner = self.module.show_panel(operation=op)
        self.assertTrue(owner.close())
        with tempfile.TemporaryDirectory() as folder:
            for name, source in [('updated', 'G0 X2'), ('empty', '')]:
                with self.subTest(name=name):
                    op.LiveEditorSource = source
                    saved = Path(folder) / (name + '.nc')
                    exported = Path(folder) / (name + '-export.nc')
                    file_io.save_operation(op, saved)
                    file_io.export([op], exported)
                    self.assertEqual(saved.read_text(), source)
                    self.assertEqual(exported.read_text(), source)

    def test_repeated_tab_switches_preserve_each_source_and_pending_edits(self):
        first, op1 = self.program('FirstNC', 'G1 X11 F100')
        owner1 = self.module.show_panel(operation=op1)
        owner1.editor.setPlainText('G1 X111 F100')
        second, op2 = self.program('SecondNC', 'G1 X22 F100')
        self.settle()
        self.assertIs(self.module._panel.operation, op2)
        self.assertEqual(op1.LiveEditorSource, 'G1 X111 F100')
        self.module._panel.editor.setPlainText('G1 X222 F100')
        for index in range(8):
            doc, op, source = (
                (first, op1, 'G1 X111 F100') if index % 2 == 0 else (second, op2, 'G1 X222 F100')
            )
            self.App.setActiveDocument(doc.Name)
            self.settle()
            self.assertIs(self.module._panel.operation, op)
            self.assertEqual(self.module._panel.editor.toPlainText(), source)
        self.assertTrue(owner1.shutting_down)

    def test_closed_document_and_old_queued_callbacks_do_not_read_deleted_objects(self):
        first, op1 = self.program('ClosedNC', 'G1 X11 F100')
        old = self.module.show_panel(operation=op1)
        second, op2 = self.program('SurvivingNC', 'G1 X22 F100')
        self.App.closeDocument(first.Name)
        old.update_info()
        self.App.setActiveDocument(second.Name)
        self.settle()
        self.assertIs(self.module._panel.operation, op2)
        for _ in range(4):
            old.update_info()
            old.sync_scene()
            old.apply_text()
        self.QtTest.QTest.qWait(300)
        self.assertTrue(old.shutting_down)
        self.assertEqual(self.module._panel.editor.toPlainText(), 'G1 X22 F100')

    def test_deleted_program_retires_editor_without_creating_a_replacement(self):
        doc, op = self.program('DeletedProgramNC', 'G1 X11 F100')
        old = self.module.show_panel(operation=op)
        doc.removeObject(op.Name)
        old.update_info()
        self.assertTrue(old.shutting_down)
        self.QtTest.QTest.qWait(350)
        self.assertTrue(old.shutting_down)
        self.assertIsNone(self.module._panel)
        self.assertEqual(list(doc.Objects), [])
        old.update_info()
        old.sync_scene()
        old.apply_text()

    def test_non_nc_tab_hides_editor_and_manual_close_stays_closed(self):
        first, op = self.program('NCWithOtherDoc', 'G1 X11 F100')
        owner = self.module.show_panel(operation=op)
        other = self.App.newDocument('PlainCAD')
        self.names.append(other.Name)
        self.settle()
        self.assertFalse(owner.isVisible())
        self.assertFalse(owner.watch_timer.isActive())
        self.App.setActiveDocument(first.Name)
        self.settle()
        self.assertIs(self.module._panel, owner)
        self.assertTrue(owner.isVisible())
        owner.close()
        self.App.setActiveDocument(other.Name)
        self.App.setActiveDocument(first.Name)
        self.settle()
        self.assertFalse(owner.isVisible())
        op.LiveEditorSource = 'G1 X99 F100'
        fresh = self.module.show_panel(operation=op)
        self.assertIsNot(fresh, owner)
        self.assertEqual(fresh.editor.toPlainText(), 'G1 X99 F100')

    def test_native_resource_edit_defers_handoff_until_it_finishes(self):
        first, op1 = self.program('BusyNC', 'G1 X11 F100')
        owner = self.module.show_panel(operation=op1)
        owner.resource_depth = 1
        second, op2 = self.program('WaitingNC', 'G1 X22 F100')
        self.settle()
        self.assertIs(self.module._panel, owner)
        owner.resource_depth = 0
        self.documents.request()
        self.settle()
        self.assertIs(self.module._panel.operation, op2)

    def test_deleting_program_closes_modeless_cycle_and_stops_its_callbacks(self):
        from freecad.camed.cycle_tool import show_cycle_tool

        doc, op = self.program('CycleOwnerNC', 'G21 G90\nG1 X11 F100')
        owner = self.module.show_panel(operation=op)
        show_cycle_tool()
        dialog = owner.cycle_dialog
        self.assertTrue(dialog.isVisible())
        doc.removeObject(op.Name)
        owner.update_info()
        self.assertIsNone(owner.cycle_dialog)
        self.assertFalse(dialog.timer.isActive())
        self.assertFalse(dialog.isVisible())
        self.settle()
