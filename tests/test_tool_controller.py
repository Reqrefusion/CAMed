import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from freecad.camed.tool_controller import edit_number, remove_from_job


class ToolNumberTests(unittest.TestCase):
    def setUp(self):
        self.tc = types.SimpleNamespace(ToolNumber=3)
        self.other = types.SimpleNamespace(ToolNumber=7)
        self.owner = types.SimpleNamespace(
            document=Mock(),
            job=types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[self.tc, self.other])),
            shutting_down=False,
            is_current=Mock(return_value=True),
            pending_code=False,
            resource_depth=0,
        )

        @contextmanager
        def scope():
            self.owner.resource_depth += 1
            try:
                yield
            finally:
                self.owner.resource_depth -= 1

        self.owner.resource_update = scope
        self.input = Mock(return_value=(5, True))
        self.warning = Mock()
        self.parent = object()
        self.modules = {
            'FreeCADGui': types.SimpleNamespace(Control=types.SimpleNamespace(activeDialog=lambda: None)),
            'PySide': types.SimpleNamespace(
                QtWidgets=types.SimpleNamespace(
                    QInputDialog=types.SimpleNamespace(getInt=self.input),
                    QMessageBox=types.SimpleNamespace(warning=self.warning),
                )
            ),
        }

    def test_initial_tool_change_has_its_own_undo_step(self):
        from freecad.camed.tool_controller import set_initial_tool

        self.owner.operation = types.SimpleNamespace(addProperty=Mock())
        with patch.dict(sys.modules, self.modules):
            self.assertTrue(set_initial_tool(self.owner, self.tc))
            self.assertFalse(set_initial_tool(self.owner, self.tc))
        self.assertIs(self.owner.operation.CAMEditorInitialTool, self.tc)
        self.owner.document.openTransaction.assert_called_once_with('Set initial tool')
        self.owner.document.commitTransaction.assert_called_once()
        self.assertTrue(self.owner.pending_code)

    def test_pending_document_transaction_blocks_initial_tool_change(self):
        from freecad.camed.tool_controller import set_initial_tool

        self.owner.operation = types.SimpleNamespace(CAMEditorInitialTool=self.other)
        self.owner.document.HasPendingTransaction = True
        with patch.dict(sys.modules, self.modules), self.assertRaises(ValueError):
            set_initial_tool(self.owner, self.tc)
        self.assertIs(self.owner.operation.CAMEditorInitialTool, self.other)
        self.owner.document.openTransaction.assert_not_called()
        self.owner.document.commitTransaction.assert_not_called()
        self.owner.document.abortTransaction.assert_not_called()
        self.assertFalse(self.owner.pending_code)

    def run_edit(self):
        with patch.dict(sys.modules, self.modules):
            return edit_number(self.owner, self.tc, self.parent)

    def test_accepted_number_changes_only_native_number_and_commits(self):
        self.assertTrue(self.run_edit())
        self.assertEqual(vars(self.tc), {'ToolNumber': 5})
        self.input.assert_called_once_with(self.parent, 'Edit tool number', 'Tool number (T):', 3, 0, 10000)
        self.owner.document.commitTransaction.assert_called_once()
        self.owner.document.abortTransaction.assert_not_called()
        self.assertTrue(self.owner.pending_code)
        self.assertEqual(self.owner.resource_depth, 0)

    def test_cancel_does_not_change_number_or_open_transaction(self):
        self.input.return_value = (8, False)
        self.assertFalse(self.run_edit())
        self.assertEqual(self.tc.ToolNumber, 3)
        self.owner.document.openTransaction.assert_not_called()
        self.assertFalse(self.owner.pending_code)

    def test_unchanged_number_does_not_open_transaction(self):
        self.input.return_value = (3, True)
        self.assertFalse(self.run_edit())
        self.owner.document.openTransaction.assert_not_called()

    def test_duplicate_number_reprompts_and_cancel_preserves_original(self):
        self.input.side_effect = [(7, True), (7, False)]
        self.assertFalse(self.run_edit())
        self.warning.assert_called_once()
        self.assertEqual(self.tc.ToolNumber, 3)
        self.owner.document.openTransaction.assert_not_called()

    def test_recompute_error_aborts_and_releases_lock(self):
        self.owner.document.recompute.side_effect = RuntimeError('native failed')
        with self.assertRaises(RuntimeError):
            self.run_edit()
        self.owner.document.abortTransaction.assert_called_once()
        self.assertEqual(self.owner.resource_depth, 0)
        self.assertFalse(self.owner.pending_code)

    def test_foreign_controller_is_not_edited(self):
        self.owner.job.Tools.Group = []
        with self.assertRaises(ValueError):
            self.run_edit()
        self.input.assert_not_called()
        self.owner.document.openTransaction.assert_not_called()

    def removal_case(self):
        self.owner.operation = types.SimpleNamespace(LiveEditorSource='T3 M6\nG1 X10 F100')
        self.owner.job.Operations = types.SimpleNamespace(Group=[self.owner.operation])
        self.tc.Name = 'TC3'
        self.tc.InList = [self.owner.job.Tools, self.owner.operation]
        self.hook = Mock(return_value=True)
        self.tc.ViewObject = types.SimpleNamespace(Proxy=types.SimpleNamespace(onDelete=self.hook))

    def test_removal_reuses_native_hook_and_commits_without_rewriting_source(self):
        self.removal_case()
        with patch.dict(sys.modules, self.modules):
            self.assertTrue(remove_from_job(self.owner, self.tc))
        self.hook.assert_called_once_with(self.tc.ViewObject, None)
        self.owner.document.removeObject.assert_called_once_with('TC3')
        self.owner.document.commitTransaction.assert_called_once()
        self.assertEqual(self.owner.operation.LiveEditorSource, 'T3 M6\nG1 X10 F100')
        self.assertTrue(self.owner.pending_code)
        self.assertEqual(self.owner.resource_depth, 0)

    def test_controller_used_elsewhere_is_not_removed(self):
        self.removal_case()
        self.tc.InList.append(object())
        with patch.dict(sys.modules, self.modules), self.assertRaises(ValueError):
            remove_from_job(self.owner, self.tc)
        self.hook.assert_not_called()
        self.owner.document.openTransaction.assert_not_called()

    def test_native_delete_error_aborts_and_releases_lock(self):
        self.removal_case()
        self.hook.side_effect = RuntimeError('native delete failed')
        with patch.dict(sys.modules, self.modules), self.assertRaises(RuntimeError):
            remove_from_job(self.owner, self.tc)
        self.owner.document.abortTransaction.assert_called_once()
        self.owner.document.commitTransaction.assert_not_called()
        self.assertFalse(self.owner.pending_code)
        self.assertEqual(self.owner.resource_depth, 0)
