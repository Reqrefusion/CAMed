"""Check plain-source preservation and failure-safe writes without FreeCAD/Qt."""

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class FileIOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = types.ModuleType("FreeCAD")
        with patch.dict(sys.modules, {"FreeCAD": cls.app}):
            sys.modules.pop("freecad.camed.file_io", None)
            cls.io = importlib.import_module("freecad.camed.file_io")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name) / "part.nc"
        self.operation = types.SimpleNamespace(
            LiveEditorManaged=True,
            LiveEditorSource="G1 X10 F100\nG0 Z",
            Gcode=["G1 X10 F100"],
            addProperty=Mock(),
        )
        self.panel = types.ModuleType("freecad.camed.panel")
        self.panel._panel = None
        # Relative imports may reuse a package attribute as well as sys.modules.
        self.package = importlib.import_module("freecad.camed")
        self.stock_import = Mock()
        stock_module = types.ModuleType("freecad.camed.program_stock")
        stock_module.apply_import_stock = self.stock_import
        self.context = patch.dict(
            sys.modules,
            {
                "freecad.camed.panel": self.panel,
                "freecad.camed.program_stock": stock_module,
            },
        )
        self.context.start()
        self.addCleanup(self.context.stop)
        self.attribute = patch.object(self.package, "panel", self.panel, create=True)
        self.attribute.start()
        self.addCleanup(self.attribute.stop)

    def test_save_preserves_full_source_after_incomplete_last_line(self):
        self.io.save_operation(self.operation, str(self.target))
        self.assertEqual(self.target.read_text(), "G1 X10 F100\nG0 Z")
        self.assertEqual(self.operation.CAMEditorGCodePath, str(self.target.resolve()))

    def test_save_reads_text_before_debounce_runs(self):
        self.panel._panel = types.SimpleNamespace(
            operation=self.operation,
            shutting_down=False,
            editor=Mock(toPlainText=Mock(return_value="G1 X25 F100")),
        )
        self.io.save_operation(self.operation, str(self.target))
        self.assertEqual(self.target.read_text(), "G1 X25 F100")

    def test_empty_source_does_not_restore_old_commands(self):
        self.operation.LiveEditorSource = ""
        self.io.save_operation(self.operation, str(self.target))
        self.assertEqual(self.target.read_bytes(), b"")

    def test_failed_replace_preserves_file_and_save_destination(self):
        self.target.write_text("original")
        self.operation.CAMEditorGCodePath = "previous.nc"
        with patch.object(self.io.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.io.save_operation(self.operation, str(self.target))
        self.assertEqual(self.target.read_text(), "original")
        self.assertEqual(self.operation.CAMEditorGCodePath, "previous.nc")
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_invalid_extension_cannot_overwrite_freecad_project(self):
        project = self.target.with_suffix(".FCStd")
        project.write_bytes(b"FCStd data")
        with self.assertRaises(ValueError):
            self.io.write_source(str(project), "G0 X0")
        self.assertEqual(project.read_bytes(), b"FCStd data")

    def test_export_is_copy_and_does_not_change_save_destination(self):
        self.operation.CAMEditorGCodePath = "original.nc"
        self.io.export([self.operation], str(self.target))
        self.assertEqual(self.target.read_text(), self.operation.LiveEditorSource)
        self.assertEqual(self.operation.CAMEditorGCodePath, "original.nc")

    def test_export_refuses_ambiguous_document(self):
        doc = types.SimpleNamespace(Objects=[self.operation, types.SimpleNamespace(LiveEditorManaged=True)])
        stock = types.SimpleNamespace(Document=doc)
        with self.assertRaises(ValueError):
            self.io.export([stock], str(self.target))
        self.assertFalse(self.target.exists())

    def test_export_follows_job_and_stock_in_a_multiple_program_document(self):
        other = types.SimpleNamespace(LiveEditorManaged=True, LiveEditorSource='M30')
        doc = types.SimpleNamespace(Objects=[other, self.operation])
        stock = types.SimpleNamespace(Document=doc)
        job = types.SimpleNamespace(
            CAMEditorSession=True,
            Stock=stock,
            Document=doc,
            Operations=types.SimpleNamespace(Group=[self.operation]),
        )
        stock.InList = [job]
        for selected in ([job], [stock], [job, stock, self.operation]):
            self.io.export(selected, str(self.target))
            self.assertEqual(self.target.read_text(), self.operation.LiveEditorSource)

    def test_unrelated_or_mixed_selection_does_not_overwrite_export(self):
        unrelated = types.SimpleNamespace(Document=types.SimpleNamespace(Objects=[self.operation]))
        self.target.write_text('previous')
        for selected in ([unrelated], [self.operation, unrelated]):
            with self.assertRaises(ValueError):
                self.io.export(selected, str(self.target))
            self.assertEqual(self.target.read_text(), 'previous')

    def test_save_cancel_does_not_write_or_bind(self):
        self.app.ActiveDocument = types.SimpleNamespace(Objects=[self.operation])
        qt = types.ModuleType("PySide")
        qt.QtWidgets = types.SimpleNamespace(
            QFileDialog=types.SimpleNamespace(getSaveFileName=Mock(return_value=("", "")))
        )
        gui = types.ModuleType("FreeCADGui")
        gui.getMainWindow = Mock()
        with patch.dict(sys.modules, {"PySide": qt, "FreeCADGui": gui}):
            self.assertFalse(self.io.save_active())
        self.assertFalse(hasattr(self.operation, "CAMEditorGCodePath"))
        self.assertFalse(self.target.exists())

    def test_default_extension_is_nc(self):
        self.app.ActiveDocument = types.SimpleNamespace(Objects=[self.operation])
        qt = types.ModuleType("PySide")
        qt.QtWidgets = types.SimpleNamespace(
            QFileDialog=types.SimpleNamespace(
                getSaveFileName=Mock(return_value=(str(self.target.with_suffix('')), ""))
            )
        )
        gui = types.ModuleType("FreeCADGui")
        gui.getMainWindow = Mock()
        with patch.dict(sys.modules, {"PySide": qt, "FreeCADGui": gui}):
            self.assertTrue(self.io.save_active())
        self.assertTrue(self.target.exists())

    def test_turkish_ansi_nc_file_is_decoded(self):
        source = "%1049\n(YÜZEY TIRAŞLAMA)\nG0X1\n"
        self.target.write_bytes(source.encode("cp1254"))
        self.assertEqual(self.io.read_source(self.target), source)

    def test_utf8_bom_and_utf16_files_are_decoded(self):
        for encoding in ("utf-8-sig", "utf-16"):
            source = "%\n(Çelik)\nG1X2\n"
            self.target.write_bytes(source.encode(encoding))
            self.assertEqual(self.io.read_source(self.target), source)

    def test_open_dialog_directs_nc_to_our_handler(self):
        qt = types.ModuleType("PySide")
        qt.QtWidgets = types.SimpleNamespace(
            QFileDialog=types.SimpleNamespace(getOpenFileName=Mock(return_value=(str(self.target), "")))
        )
        gui = types.ModuleType("FreeCADGui")
        gui.getMainWindow = Mock()
        with (
            patch.dict(sys.modules, {"PySide": qt, "FreeCADGui": gui}),
            patch.object(self.io, "active_operation", return_value=None),
            patch.object(self.io, "open") as opener,
        ):
            self.io.open_dialog()
        opener.assert_called_once_with(str(self.target))

    def test_open_dialog_preserves_native_freecad_open_for_fcstd(self):
        qt = types.ModuleType("PySide")
        filename = str(self.target.with_suffix(".FCStd"))
        qt.QtWidgets = types.SimpleNamespace(
            QFileDialog=types.SimpleNamespace(getOpenFileName=Mock(return_value=(filename, "")))
        )
        gui = types.ModuleType("FreeCADGui")
        gui.getMainWindow = Mock()
        gui.open = Mock()
        with (
            patch.dict(sys.modules, {"PySide": qt, "FreeCADGui": gui}),
            patch.object(self.io, "active_operation", return_value=None),
        ):
            self.io.open_dialog()
        gui.open.assert_called_once_with(filename)

    def test_import_loads_program_header_and_modal_source_into_editor(self):
        del self.operation.LiveEditorSource
        self.operation.Document = doc = types.SimpleNamespace(
            Name="Imported",
            Label="Existing project",
            HasPendingTransaction=False,
            openTransaction=Mock(),
            commitTransaction=Mock(),
            abortTransaction=Mock(),
        )
        source = "%1049\nG54\nT4M6\nG0X-20Y-20\nG1Z-3F1000\nX220"
        gui = types.ModuleType("FreeCADGui")
        gui.getMainWindow = Mock()
        gui.Control = types.SimpleNamespace(activeDialog=Mock(return_value=None))
        gui.Selection = Mock()
        gui.activateWorkbench = Mock()
        gui.activeDocument = Mock()
        sessions = types.ModuleType("freecad.camed.sessions")
        sessions.prepare_session = Mock(return_value=(self.operation, True))
        owner = types.SimpleNamespace(
            editor=Mock(),
            apply_text=Mock(),
            preview_error=None,
            status=Mock(text=Mock(return_value="preview ready")),
        )
        self.panel.show_panel = Mock(return_value=owner)
        self.app.setActiveDocument = Mock()
        self.app.Console = types.SimpleNamespace(PrintMessage=Mock())
        with patch.dict(sys.modules, {"FreeCADGui": gui, "freecad.camed.sessions": sessions}):
            self.io._load(str(self.target), doc, source)
        self.assertEqual(self.operation.LiveEditorSource, source)
        self.assertIn("G1 X220 F1000", self.operation.Gcode)
        self.stock_import.assert_called_once()
        self.assertIs(self.stock_import.call_args.args[0], self.operation)
        owner.editor.setPlainText.assert_called_once_with(source)
        owner.apply_text.assert_called_once()
        self.assertEqual(doc.Label, "Existing project")
        sessions.prepare_session.assert_called_once_with(new_program=True, transaction=False)
        self.panel.show_panel.assert_called_once_with(operation=self.operation)
        doc.commitTransaction.assert_called_once()
        doc.abortTransaction.assert_not_called()

    def test_insert_reports_view_failure_as_a_committed_import(self):
        self.target.write_text('G0 X5')
        doc = Mock(Name='Existing', Label='My project', HasPendingTransaction=False)
        operation = types.SimpleNamespace(Document=doc, addProperty=Mock())
        sessions = types.SimpleNamespace(prepare_session=Mock(return_value=(operation, True)))
        self.app.getDocument = Mock(return_value=doc)
        self.app.setActiveDocument = Mock()
        self.app.Console = Mock()
        gui = Mock()
        gui.Control.activeDialog.return_value = None
        qt = Mock()
        self.panel.show_panel = Mock(side_effect=RuntimeError('panel unavailable'))
        with (
            patch.dict(sys.modules, {'FreeCADGui': gui, 'PySide': qt, 'freecad.camed.sessions': sessions}),
            patch.object(self.io, 'show_open_error') as import_error,
        ):
            self.assertIs(self.io.insert(str(self.target), 'Existing'), doc)
        self.assertEqual(operation.LiveEditorSource, 'G0 X5')
        sessions.prepare_session.assert_called_once()
        doc.commitTransaction.assert_called_once()
        doc.abortTransaction.assert_not_called()
        import_error.assert_not_called()
        qt.QtWidgets.QMessageBox.warning.assert_called_once()
        self.assertIn('Imported part.nc into My project.', qt.QtWidgets.QMessageBox.warning.call_args.args[2])
        self.assertIn('panel unavailable', qt.QtWidgets.QMessageBox.warning.call_args.args[2])

    def test_open_failure_is_visible_and_no_document_is_created(self):
        qt = types.ModuleType("PySide")
        qt.QtWidgets = types.SimpleNamespace(QMessageBox=Mock())
        gui = types.ModuleType("FreeCADGui")
        gui.getMainWindow = Mock()
        self.app.Console = types.SimpleNamespace(PrintError=Mock())
        self.app.newDocument = Mock()
        with patch.dict(sys.modules, {"PySide": qt, "FreeCADGui": gui}):
            with self.assertRaises(FileNotFoundError):
                self.io.open(str(self.target))
        qt.QtWidgets.QMessageBox.warning.assert_called_once()
        self.app.newDocument.assert_not_called()

    def test_active_task_blocks_open_before_editor_close_or_document_creation(self):
        gui = types.ModuleType("FreeCADGui")
        gui.Control = types.SimpleNamespace(activeDialog=lambda: object())
        self.app.newDocument = Mock()
        with (
            patch.dict(sys.modules, {"FreeCADGui": gui}),
            patch.object(self.io, "read_source", return_value="G0 Z5"),
            patch.object(self.io, "_close_editor") as close,
        ):
            with self.assertRaises(ValueError):
                self.io._open("unused.nc")
        close.assert_not_called()
        self.app.newDocument.assert_not_called()

    def test_active_task_blocks_insert_before_closing_or_switching_document(self):
        gui = types.ModuleType("FreeCADGui")
        gui.Control = types.SimpleNamespace(activeDialog=lambda: object())
        self.app.setActiveDocument = Mock()
        with patch.dict(sys.modules, {"FreeCADGui": gui}), patch.object(self.io, "_close_editor") as close:
            with self.assertRaises(ValueError):
                self.io._load("unused.nc", types.SimpleNamespace(Name="Target"), "G0 Z5")
        close.assert_not_called()
        self.app.setActiveDocument.assert_not_called()

    def test_reusing_an_existing_program_is_refused_before_any_source_write(self):
        original = self.operation.LiveEditorSource
        doc = types.SimpleNamespace(
            Name="Existing",
            HasPendingTransaction=False,
            openTransaction=Mock(),
            commitTransaction=Mock(),
            abortTransaction=Mock(),
        )
        gui = types.ModuleType("FreeCADGui")
        gui.Control = types.SimpleNamespace(activeDialog=lambda: None)
        sessions = types.ModuleType("freecad.camed.sessions")
        sessions.prepare_session = Mock(return_value=(self.operation, False))
        self.app.setActiveDocument = Mock()
        with patch.dict(sys.modules, {"FreeCADGui": gui, "freecad.camed.sessions": sessions}):
            with self.assertRaises(ValueError):
                self.io._load("new.nc", doc, "G1 X99 F100")
        self.assertEqual(self.operation.LiveEditorSource, original)
        doc.abortTransaction.assert_called_once()
        doc.commitTransaction.assert_not_called()


if __name__ == "__main__":
    unittest.main()
