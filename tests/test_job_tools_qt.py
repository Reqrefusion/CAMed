"""Job tools show T numbers; creation delegates to the library's native flow."""

import os
import importlib
import types
import unittest
from unittest.mock import Mock, patch
import test_inspection_qt as lifecycle


@unittest.skipUnless(
    os.environ.get('CAMEDITOR_QT_TESTS') == '1', 'Run tests/run_qt_checks.py with FreeCAD Python'
)
class JobToolsQtTests(unittest.TestCase):
    setUpClass = classmethod(lifecycle.InspectionQtTests.setUpClass.__func__)
    setUp = lifecycle.InspectionQtTests.setUp
    tearDown = lifecycle.InspectionQtTests.tearDown

    def make_controller(self, number, label):
        return types.SimpleNamespace(
            Name='TC' + str(number),
            ToolNumber=number,
            Label=label,
            Tool=types.SimpleNamespace(ToolType='Drill', Diameter='6 mm', CuttingEdgeHeight='30 mm'),
        )

    def test_list_shows_only_job_tools_with_visible_T_numbers(self):
        from freecad.camed import tool_panel
        from PySide import QtWidgets

        self.panel.job = types.SimpleNamespace(
            Tools=types.SimpleNamespace(
                Group=[self.make_controller(7, 'Drill'), self.make_controller(2, 'Endmill')]
            )
        )
        with patch.object(tool_panel, 'fingerprint', return_value=('test',)):
            dialog = tool_panel.ToolsDialog(self.panel)
        self.assertEqual([dialog.table.item(row, 0).text() for row in range(2)], ['T2', 'T7'])
        self.assertFalse(dialog.table.isColumnHidden(0))
        labels = [b.text() for b in dialog.findChildren(QtWidgets.QPushButton)]
        self.assertIn('New toolbit…', labels)
        self.assertNotIn('Kütüphaneden ekle', labels)
        self.assertFalse(hasattr(tool_panel, 'show_tool_selector'))
        dialog.close()

    def test_new_tool_delegates_to_native_library_flow_and_selects_added_T_number(self):
        from freecad.camed import tool_panel, tool_creation

        tc = self.make_controller(9, 'New drill')
        job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[]))
        self.panel.job = job
        with patch.object(
            tool_panel, 'fingerprint', side_effect=lambda job: tuple(t.Name for t in job.Tools.Group)
        ):
            dialog = tool_panel.ToolsDialog(self.panel)
            dialog.show()

            def create(owner, parent):
                self.assertIs(owner, self.panel)
                self.assertIs(parent, dialog)
                self.assertTrue(dialog.isVisible())
                job.Tools.Group.append(tc)
                return tc

            with patch.object(tool_creation, 'create_from_library', side_effect=create) as native:
                dialog.create()
            native.assert_called_once_with(self.panel, dialog)
        self.assertEqual(dialog.table.item(dialog.table.currentRow(), 0).text(), 'T9')
        # Avoid attempting a real preview against this test-only Job adapter.
        dialog.pending_update = False
        dialog.close()

    def test_filter_selects_a_visible_match_and_respects_empty_initial_tool(self):
        from freecad.camed import tool_panel

        first = self.make_controller(1, 'Drill')
        second = self.make_controller(2, 'Endmill')
        self.panel.job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[first, second]))
        self.panel.operation.addProperty('App::PropertyLink', 'CAMEditorInitialTool')
        with patch.object(tool_panel, 'fingerprint', return_value=('test',)):
            dialog = tool_panel.ToolsDialog(self.panel)
            dialog.search.setText('Endmill')
            self.assertIs(dialog.selected(), second)
            self.assertTrue(dialog.remove_button.isEnabled())
            self.assertEqual(dialog.table.item(1, 5).text(), '')
            dialog.search.setText('absent')
            self.assertIsNone(dialog.selected())
            self.assertFalse(dialog.remove_button.isEnabled())
            dialog.close()

    def test_geometry_edit_opens_parameter_dialog_instead_of_generic_set_edit(self):
        from freecad.camed import tool_panel

        tool_parameters = importlib.import_module("freecad.camed.tool_parameters")
        tc = self.make_controller(3, 'Drill')
        self.gui.activeDocument = Mock()
        self.panel.job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[tc]))
        with patch.object(tool_panel, 'fingerprint', return_value=('test',)):
            dialog = tool_panel.ToolsDialog(self.panel)
            with patch.object(tool_parameters, 'edit_parameters', return_value=False) as edit:
                dialog.edit_geometry()
            edit.assert_called_once_with(self.panel, tc, dialog)
        self.gui.activeDocument.assert_not_called()
        dialog.close()

    def test_number_button_and_double_click_open_only_number_input(self):
        from freecad.camed import tool_panel

        tool_controller = importlib.import_module("freecad.camed.tool_controller")
        tc = self.make_controller(3, 'Drill')
        self.gui.activeDocument = Mock()
        self.panel.job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[tc]))
        with patch.object(tool_panel, 'fingerprint', return_value=('test',)):
            dialog = tool_panel.ToolsDialog(self.panel)
            with patch.object(tool_controller, 'edit_number', return_value=False) as edit:
                button = next(b for b in dialog.selection_buttons if b.text() == "Edit tool number")
                self.assertTrue(button.isEnabled())
                button.click()
                edit.assert_called_once_with(self.panel, tc, dialog)
                edit.reset_mock()
                dialog.edit_cell(0, 0)
            edit.assert_called_once_with(self.panel, tc, dialog)
        self.gui.activeDocument.assert_not_called()
        self.assertFalse(hasattr(dialog, 'begin_edit'))
        dialog.close()

    def test_feeds_speeds_button_opens_toolbit_parameter_tab_directly(self):
        from freecad.camed import tool_panel

        tool_parameters = importlib.import_module("freecad.camed.tool_parameters")
        tool_controller = importlib.import_module("freecad.camed.tool_controller")
        tc = self.make_controller(3, 'Drill')
        self.panel.job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[tc]))
        with patch.object(tool_panel, 'fingerprint', return_value=('test',)):
            dialog = tool_panel.ToolsDialog(self.panel)
            with (
                patch.object(tool_parameters, 'edit_parameters', return_value=False) as edit,
                patch.object(tool_controller, 'edit_number') as controller,
            ):
                dialog.edit()
            edit.assert_called_once_with(self.panel, tc, dialog, feeds_speeds=True)
            controller.assert_not_called()
        dialog.close()

    def test_remove_button_sits_beside_add_and_tracks_selection(self):
        from freecad.camed import tool_panel

        helper = importlib.import_module('freecad.camed.tool_controller')
        tc = self.make_controller(3, 'Drill')
        self.panel.job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[tc]))
        with patch.object(tool_panel, 'fingerprint', return_value=('test',)):
            dialog = tool_panel.ToolsDialog(self.panel)
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.remove_button.text(), 'Remove tool')
            self.assertTrue(dialog.remove_button.isEnabled())
            row = dialog.layout().itemAt(0).layout()
            self.assertIs(row.itemAt(1).widget(), dialog.remove_button)
            with patch.object(helper, 'remove_from_job', return_value=True) as remove:
                dialog.remove_button.click()
            remove.assert_called_once_with(self.panel, tc)
            dialog.search.setText('no matches')
            self.assertFalse(dialog.remove_button.isEnabled())
            dialog.close()
