"""Session workflow checks with native CAM factories stubbed."""

import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


def native_object(**kwargs):
    return types.SimpleNamespace(**kwargs)


class SessionTests(unittest.TestCase):
    def make_job(self, name):
        return native_object(
            Name=name,
            Label=name,
            Proxy=object(),
            CAMEditorSession=True,
            Tools=native_object(Group=[self.controller]),
            Operations=native_object(Group=[]),
            ViewObject=Mock(),
            addExtension=Mock(),
        )

    def setUp(self):
        names = (
            "FreeCAD",
            "FreeCADGui",
            "PySide",
            "Path",
            "Path.Main",
            "Path.Main.Job",
            "Path.Main.Gui",
            "Path.Main.Gui.Job",
            "PathScripts",
        )
        self.modules = {name: types.ModuleType(name) for name in names}
        m = self.modules
        self.doc = Mock()
        self.doc.Objects = []
        self.app = m["FreeCAD"]
        self.app.ActiveDocument = self.doc
        self.app.newDocument = Mock(side_effect=lambda *a: setattr(self.app, "ActiveDocument", self.doc))
        self.gui = m["FreeCADGui"]
        self.gui.Selection = Mock()
        self.gui.Selection.getSelection.return_value = []
        self.gui.getMainWindow = Mock()
        self.picker = Mock(return_value=("", False))
        m["PySide"].QtWidgets = native_object(QInputDialog=native_object(getItem=self.picker))
        m["PathScripts"].PathUtils = native_object(findParentJob=Mock(return_value=None))
        self.controller = native_object(Tool=object())
        self.job = self.make_job("Job")
        self.op = native_object(
            Proxy=None, ToolController=None, ViewObject=Mock(), addProperty=Mock(), Gcode=[]
        )
        self.create_op = Mock(return_value=self.op)
        m["Path.Main"].Job = m["Path.Main.Job"]
        m["Path.Main.Gui.Job"].ViewProvider = Mock()
        self.patcher = patch.dict(sys.modules, m)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.doc.addObject.return_value = self.job
        self.native_constructor = Mock(return_value=object())
        m["Path.Main.Job"].ObjectJob = self.native_constructor
        self.job.addProperty = Mock()
        self.job.Stock = types.SimpleNamespace(Visibility=False)
        self.job.Document = self.doc
        self.stock_clear = Mock(side_effect=lambda job, **kwargs: setattr(job, "Stock", None))
        backend = types.ModuleType("freecad.camed.stock_backend")
        backend.clear_stock = self.stock_clear
        native = types.ModuleType("freecad.camed.native_program")
        native.create = self.create_op
        extra = patch.dict(
            sys.modules,
            {
                "freecad.camed.stock_backend": backend,
                "freecad.camed.native_program": native,
            },
        )
        extra.start()
        self.addCleanup(extra.stop)
        sys.modules.pop("freecad.camed.sessions", None)
        self.sessions = importlib.import_module("freecad.camed.sessions")

    def test_new_session_has_no_code_stock_or_dummy_model(self):
        op, created = self.sessions.prepare_session()
        self.assertTrue(created)
        self.assertIs(op, self.op)
        self.doc.addObject.assert_called_once_with("Path::FeaturePython", "JobCAMed")
        self.native_constructor.assert_called_once_with(self.job, [])
        self.assertTrue(self.job.CAMEditorSession)
        self.assertEqual(op.Gcode, [])
        self.assertIsNone(self.job.Stock)
        self.stock_clear.assert_called_once_with(self.job, transaction=False)
        self.doc.commitTransaction.assert_called_once()

    def test_existing_program_keeps_code_and_stock_visibility(self):
        self.op.LiveEditorManaged = True
        self.op.Gcode = ["G1 X99"]
        self.doc.Objects = [self.op]
        self.modules["PathScripts"].PathUtils.findParentJob.return_value = self.job
        op, created = self.sessions.prepare_session()
        self.assertIs(op, self.op)
        self.assertFalse(created)
        self.assertEqual(op.Gcode, ["G1 X99"])
        self.assertFalse(self.job.Stock.Visibility)
        self.native_constructor.assert_not_called()
        self.doc.openTransaction.assert_not_called()

    def test_unsupported_project_is_not_migrated_or_modified(self):
        self.op.LiveEditorManaged = True
        self.doc.Objects = [self.op]
        self.job.CAMEditorSession = False
        self.modules['PathScripts'].PathUtils.findParentJob.return_value = self.job
        with self.assertRaisesRegex(ValueError, 'program format is not supported'):
            self.sessions.prepare_session()
        self.doc.openTransaction.assert_not_called()
        self.job.addProperty.assert_not_called()

    def test_existing_session_is_reused(self):
        self.op.LiveEditorManaged = True
        self.doc.Objects = [self.op]
        self.job.CAMEditorSession = True
        self.modules["PathScripts"].PathUtils.findParentJob.return_value = self.job
        self.sessions.prepare_session()
        self.create_op.assert_not_called()
        self.doc.openTransaction.assert_not_called()

    def test_native_stock_cleanup_failure_aborts_entire_session(self):
        self.stock_clear.side_effect = ValueError("stock failed")
        with self.assertRaisesRegex(ValueError, "stock failed"):
            self.sessions.prepare_session()
        self.doc.abortTransaction.assert_called_once()
        self.doc.commitTransaction.assert_not_called()

    def test_fresh_program_mode_skips_existing_program_and_selection(self):
        old = types.SimpleNamespace(
            LiveEditorManaged=True, Gcode=["G1 X99"], LiveEditorSource="keep", Name="Old"
        )
        self.doc.Objects = [old]
        self.modules["FreeCADGui"].Selection.getSelection.return_value = [old]
        op, created = self.sessions.prepare_session(new_program=True, transaction=False)
        self.assertTrue(created)
        self.assertIs(op, self.op)
        self.create_op.assert_called_once()
        self.assertEqual(old.LiveEditorSource, "keep")
        self.assertEqual(old.Gcode, ["G1 X99"])
        self.doc.openTransaction.assert_not_called()
        self.doc.commitTransaction.assert_not_called()


if __name__ == "__main__":
    unittest.main()
