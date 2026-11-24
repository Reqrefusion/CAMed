"""Native library creation is guarded; only accepted bits enter the Job."""

import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from freecad.camed import tool_creation


class ToolCreationTests(unittest.TestCase):
    def setUp(self):
        self.gui = types.SimpleNamespace(Control=types.SimpleNamespace(activeDialog=lambda: None))
        self.prompt = Mock(return_value=(3, True))
        self.qt = types.SimpleNamespace(
            QtWidgets=types.SimpleNamespace(QInputDialog=types.SimpleNamespace(getInt=self.prompt))
        )
        self.modules = {'FreeCADGui': self.gui, 'PySide': self.qt}
        self.doc = Mock()
        self.job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[]), Proxy=Mock())
        self.job.Proxy.nextToolNumber.return_value = 3
        self.owner = types.SimpleNamespace(
            document=self.doc,
            job=self.job,
            shutting_down=False,
            is_current=Mock(return_value=True),
            pending_code=False,
            resource_depth=0,
        )

        @contextmanager
        def resources():
            self.owner.resource_depth += 1
            try:
                yield
            finally:
                self.owner.resource_depth -= 1

        self.owner.resource_update = resources
        self.detached = object()
        self.tool = object()
        self.bit = types.SimpleNamespace(
            obj=self.detached, label='New drill', attach_to_doc=Mock(return_value=self.tool)
        )
        self.tc = types.SimpleNamespace(ToolNumber=3)
        self.factory = Mock(return_value=self.tc)
        self.modules['Path.Tool.Gui.Controller'] = types.SimpleNamespace(Create=self.factory)

    def test_native_library_new_bit_button_is_used_and_widgets_are_cleaned_up(self):
        library = Mock()
        old = types.SimpleNamespace(get_id=lambda: 'old')
        new = types.SimpleNamespace(get_id=lambda: 'new')
        library.browser.get_selected_bits.side_effect = [[old], [new]]
        library.browser.get_tool_no_from_current_library.return_value = 7
        with patch.dict(
            sys.modules,
            {
                'Path.Tool.library.ui.editor': types.SimpleNamespace(
                    LibraryEditor=Mock(return_value=library)
                )
            },
        ):
            self.assertEqual(tool_creation._create_bit(None), (new, 7))
        library._on_add_toolbit_requested.assert_called_once()
        library.form.deleteLater.assert_called_once()
        library.deleteLater.assert_called_once()

    def test_cancelled_native_creation_does_not_reuse_previously_selected_bit(self):
        library = Mock()
        old = types.SimpleNamespace(get_id=lambda: 'old')
        library.browser.get_selected_bits.return_value = [old]
        with patch.dict(
            sys.modules,
            {'Path.Tool.library.ui.editor': types.SimpleNamespace(LibraryEditor=lambda **kwargs: library)},
        ):
            self.assertEqual(tool_creation._create_bit(None), (None, None))

    def test_cancellation_never_creates_a_default_tool(self):
        with (
            patch.dict(sys.modules, self.modules),
            patch.object(tool_creation, '_create_bit', return_value=(None, None)),
        ):
            self.assertIsNone(tool_creation.create_from_library(self.owner, None))
        self.factory.assert_not_called()
        self.doc.openTransaction.assert_not_called()
        self.assertFalse(self.owner.pending_code)
        self.assertEqual(self.owner.resource_depth, 0)

    def test_accepted_native_bit_uses_native_controller_and_defers_preview(self):
        def create_bit(parent):
            self.assertEqual(self.owner.resource_depth, 1)
            return self.bit, 3

        with (
            patch.dict(sys.modules, self.modules),
            patch.object(tool_creation, '_create_bit', side_effect=create_bit),
        ):
            self.assertIs(tool_creation.create_from_library(self.owner, None), self.tc)
        self.bit.attach_to_doc.assert_called_once_with(self.doc)
        self.factory.assert_called_once_with('TC: New drill', self.tool, 3)
        self.job.Proxy.addToolController.assert_called_once_with(self.tc)
        self.doc.commitTransaction.assert_called_once()
        self.assertTrue(self.owner.pending_code)
        self.assertEqual(self.owner.resource_depth, 0)

    def test_conflicting_library_number_requires_a_free_job_number(self):
        self.job.Tools.Group = [types.SimpleNamespace(ToolNumber=3)]
        self.prompt.side_effect = [(3, True), (8, True)]
        with patch.dict(sys.modules, self.modules):
            self.assertEqual(tool_creation._choose_number(self.job, 3, None), 8)
        self.assertEqual(self.prompt.call_count, 2)

    def test_out_of_range_preference_prompts_with_native_bounds_and_free_suggestion(self):
        self.job.Tools.Group = [types.SimpleNamespace(ToolNumber=n) for n in (1, 10000)]
        self.job.Proxy.nextToolNumber.return_value = 10001
        self.prompt.return_value = (0, True)
        with patch.dict(sys.modules, self.modules):
            self.assertEqual(tool_creation._choose_number(self.job, 10001, None), 0)
        self.assertEqual(self.prompt.call_args.args[-3:], (2, 0, 10000))

    def test_free_boundary_numbers_need_no_prompt(self):
        with patch.dict(sys.modules, self.modules):
            for number in (0, 10000):
                self.assertEqual(tool_creation._choose_number(self.job, number, None), number)
        self.prompt.assert_not_called()

    def test_no_available_number_never_opens_an_unusable_prompt(self):
        self.job.Tools.Group = [types.SimpleNamespace(ToolNumber=n) for n in range(10001)]
        self.job.Proxy.nextToolNumber.return_value = 10001
        with patch.dict(sys.modules, self.modules), self.assertRaisesRegex(ValueError, 'in use'):
            tool_creation._choose_number(self.job, None, None)
        self.prompt.assert_not_called()

    def test_cancelled_number_prompt_leaves_job_untouched(self):
        self.job.Tools.Group = [types.SimpleNamespace(ToolNumber=3)]
        self.prompt.return_value = (3, False)
        with (
            patch.dict(sys.modules, self.modules),
            patch.object(tool_creation, '_create_bit', return_value=(self.bit, 3)),
        ):
            self.assertIsNone(tool_creation.create_from_library(self.owner, None))
        self.factory.assert_not_called()
        self.doc.openTransaction.assert_not_called()

    def test_native_controller_failure_rolls_back_job_and_restores_detached_bit(self):
        def attach(doc):
            self.bit.obj = self.tool
            return self.tool

        self.bit.attach_to_doc.side_effect = attach
        self.factory.side_effect = RuntimeError('native controller failed')
        with (
            patch.dict(sys.modules, self.modules),
            patch.object(tool_creation, '_create_bit', return_value=(self.bit, 3)),
        ):
            with self.assertRaises(RuntimeError):
                tool_creation.create_from_library(self.owner, None)
        self.doc.abortTransaction.assert_called_once()
        self.doc.commitTransaction.assert_not_called()
        self.assertIs(self.bit.obj, self.detached)
        self.assertEqual(self.owner.resource_depth, 0)
        self.assertFalse(self.owner.pending_code)

    def test_owner_changed_while_native_dialog_was_open_never_receives_a_tool(self):
        self.owner.is_current.side_effect = [True, False]
        with (
            patch.dict(sys.modules, self.modules),
            patch.object(tool_creation, '_create_bit', return_value=(self.bit, 3)),
        ):
            with self.assertRaises(ValueError):
                tool_creation.create_from_library(self.owner, None)
        self.factory.assert_not_called()
        self.doc.openTransaction.assert_not_called()

    def test_existing_task_panel_blocks_the_native_creation_flow(self):
        self.gui.Control.activeDialog = lambda: object()
        with patch.dict(sys.modules, self.modules), patch.object(tool_creation, '_create_bit') as create:
            with self.assertRaises(ValueError):
                tool_creation.create_from_library(self.owner, None)
        create.assert_not_called()
