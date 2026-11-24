import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from freecad.camed.tool_parameters import edit_parameters


class ToolParameterTests(unittest.TestCase):
    def setUp(self):
        self.proxy = types.SimpleNamespace(
            _shape_type='Drill', _tool_bit_shape=object(), to_dict=lambda: {'name': 'Drill'}
        )
        self.tool = types.SimpleNamespace(
            Proxy=self.proxy, State=[], Diameter=6, BitBody='native-body', Label='Drill'
        )
        self.tool.getPropertyByName = lambda name: getattr(self.tool, name)
        data = {'Diameter': 8, 'BitBody': None, 'Label': 'Updated drill'}
        self.edited = types.SimpleNamespace(
            _shape_type='Drill',
            _tool_bit_shape=object(),
            obj=types.SimpleNamespace(PropertiesList=list(data), getPropertyByName=lambda name: data[name]),
        )
        self.clone = Mock(return_value=self.edited)
        self.tc = types.SimpleNamespace(Tool=self.tool)
        self.document = Mock()
        self.owner = types.SimpleNamespace(
            document=self.document,
            job=types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[self.tc])),
            pending_code=False,
            shutting_down=False,
            is_current=lambda: True,
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
        self.editor = Mock(spec_set=['show', 'form', 'feeds_tab_idx', 'deleteLater'])
        self.editor.show.return_value = 1
        self.editor.feeds_tab_idx = 2
        self.set_presets = Mock(side_effect=lambda obj, presets: setattr(obj, "_presets", presets))
        self.factory = Mock(return_value=self.editor)
        self.units = types.SimpleNamespace(getSchema=lambda: 7, setSchema=Mock())
        self.modules = {
            'FreeCAD': types.SimpleNamespace(Units=self.units),
            'FreeCADGui': types.SimpleNamespace(Control=types.SimpleNamespace(activeDialog=lambda: None)),
            'PySide': types.SimpleNamespace(
                QtWidgets=types.SimpleNamespace(QDialog=types.SimpleNamespace(Accepted=1))
            ),
            'Path.Tool.toolbit.ui.editor': types.SimpleNamespace(ToolBitEditor=self.factory),
            'Path.Tool.toolbit': types.SimpleNamespace(ToolBit=types.SimpleNamespace(from_dict=self.clone)),
            'Path.Tool.FeedsSpeeds': types.SimpleNamespace(
                get_presets=lambda obj: getattr(obj, '_presets', []), set_presets=self.set_presets
            ),
        }

    def test_opens_full_native_parameter_dialog_and_commits_accepted_edits(self):
        with patch.dict(sys.modules, self.modules):
            self.assertTrue(edit_parameters(self.owner, self.tc, None))
        self.factory.assert_called_once_with(self.edited, parent=None)
        self.assertEqual(self.tool.Diameter, 8)
        self.assertEqual(self.tool.BitBody, 'native-body')
        self.assertEqual(self.tool.Label, 'Updated drill')
        self.document.commitTransaction.assert_called_once()
        self.document.abortTransaction.assert_not_called()
        self.assertTrue(self.owner.pending_code)
        self.units.setSchema.assert_not_called()
        self.assertEqual(self.owner.resource_depth, 0)

    def test_cancel_aborts_changes_and_cleans_native_dialog(self):
        self.editor.show.return_value = 0
        with patch.dict(sys.modules, self.modules):
            self.assertFalse(edit_parameters(self.owner, self.tc, None))
        self.document.openTransaction.assert_not_called()
        self.document.commitTransaction.assert_not_called()
        self.assertEqual(self.tool.Diameter, 6)
        self.assertFalse(self.owner.pending_code)
        self.editor.form.deleteLater.assert_called_once()
        self.editor.deleteLater.assert_called_once()
        self.units.setSchema.assert_not_called()

    def test_constructor_failure_restores_schema_before_dialog_can_open(self):
        self.units.getSchema = Mock(side_effect=[7, 1])
        self.factory.side_effect = RuntimeError('editor failed')
        with patch.dict(sys.modules, self.modules), self.assertRaises(RuntimeError):
            edit_parameters(self.owner, self.tc, None)
        self.document.openTransaction.assert_not_called()
        self.units.setSchema.assert_called_once_with(7)
        self.assertEqual(self.owner.resource_depth, 0)

    def test_foreign_controller_is_rejected_before_editing(self):
        self.owner.job.Tools.Group = []
        with patch.dict(sys.modules, self.modules), self.assertRaises(ValueError):
            edit_parameters(self.owner, self.tc, None)
        self.factory.assert_not_called()
        self.document.openTransaction.assert_not_called()

    def test_document_failure_aborts_parameter_update(self):
        self.document.recompute.side_effect = RuntimeError('recompute failed')
        with patch.dict(sys.modules, self.modules), self.assertRaises(RuntimeError):
            edit_parameters(self.owner, self.tc, None)
        self.document.abortTransaction.assert_called_once()
        self.assertFalse(self.owner.pending_code)

    def test_feeds_speeds_opens_the_toolbit_editors_native_preset_tab(self):
        self.editor.show.return_value = 0
        with patch.dict(sys.modules, self.modules):
            self.assertFalse(edit_parameters(self.owner, self.tc, None, feeds_speeds=True))
        self.editor.form.tabWidget.setCurrentIndex.assert_called_once_with(2)
        self.document.openTransaction.assert_not_called()

    def test_first_native_preset_is_saved_even_when_original_has_no_preset_property(self):
        self.edited.obj._presets = [{'name': 'Steel'}]
        with patch.dict(sys.modules, self.modules):
            edit_parameters(self.owner, self.tc, None, feeds_speeds=True)
        self.set_presets.assert_called_once_with(self.tool, [{'name': 'Steel'}])
        self.assertEqual(self.tool._presets, [{'name': 'Steel'}])

    def test_cancelled_preset_changes_do_not_reach_the_job_tool(self):
        self.editor.show.return_value = 0
        self.edited.obj._presets = [{'name': 'Cancelled'}]
        with patch.dict(sys.modules, self.modules):
            edit_parameters(self.owner, self.tc, None, feeds_speeds=True)
        self.set_presets.assert_not_called()
        self.assertFalse(hasattr(self.tool, '_presets'))
