"""Controller checks with stubs; these do NOT verify the FreeCAD GUI/API."""

import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


def load_panel():
    modules = {
        name: types.ModuleType(name)
        for name in (
            "FreeCAD",
            "FreeCADGui",
            "PySide",
            "Path",
            "Path.Main",
            "Path.Main.Gui",
            "Path.Main.Gui.Editor",
            "PathScripts",
        )
    }
    modules["PySide"].QtCore = types.SimpleNamespace()
    modules["PySide"].QtGui = types.SimpleNamespace()
    modules["PySide"].QtWidgets = types.SimpleNamespace(QDockWidget=object)
    modules["Path.Main.Gui.Editor"].CodeEditor = object
    modules["PathScripts"].PathUtils = object
    with patch.dict(sys.modules, modules):
        name = "freecad.camed.panel"
        sys.modules.pop(name, None)
        panel = importlib.import_module(name)
    return panel


class PanelFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_panel()

    def setUp(self):
        self.panel = self.module.LivePanel.__new__(self.module.LivePanel)
        p = self.panel
        p.document = Mock(Name="Demo")
        p.operation = types.SimpleNamespace(
            Name="Custom",
            Visibility=True,
            Gcode=["G1 X1"],
            State=[],
            Proxy=types.SimpleNamespace(errors=[]),
            touch=Mock(),
            addProperty=lambda *args: None,
        )
        p.operation.Document = p.document
        p.operation_name = "Custom"
        p.document.getObject.return_value = p.operation
        self.module.App.getDocument = Mock(return_value=p.document)
        self.module.App.ActiveDocument = p.document
        p.editor = Mock()
        p.editor.textCursor.return_value.positionInBlock.return_value = 0
        p.editor.toPlainText.return_value = "G1 X10 F100"
        p.timer = Mock()
        p.timer.isActive.return_value = False
        p.status = Mock()
        p.valid = True
        p.ui_ready = True
        p.enabled = True
        p.shutting_down = False
        p.simulation_failed = False
        p.preview_error = None
        from freecad.camed.validation import preview

        # These controller tests model an already configured initial tool.
        p.preview_result = preview('G1 X10 F100', {1: 1}, 1)
        parser = patch.object(
            self.module,
            'parse_program',
            side_effect=lambda operation, job, source: (preview(source, {1: 1}, 1), None),
        )
        parser.start()
        self.addCleanup(parser.stop)
        p.watch_timer = Mock()
        p.scene_signature = None
        self.module.Gui.Control = types.SimpleNamespace(activeDialog=lambda: None)
        p.simulation = Mock()
        p.simulation.is_playing.return_value = True

    def test_edit_pauses_and_valid_text_keeps_cursor_following(self):
        p = self.panel
        p.text_changed()
        p.simulation.pause.assert_called_once()
        self.assertTrue(p.operation.Visibility)
        p.apply_text()
        self.assertTrue(p.valid)
        self.assertTrue(p.operation.Visibility)
        self.assertEqual(p.operation.Gcode, ["G1 X10 F100"])
        p.document.commitTransaction.assert_called_once()
        p.simulation.reload.assert_called_once_with(autoplay=False, preserve_camera=True)

    def test_missing_initial_tool_keeps_path_and_reloads_material_simulation(self):
        from freecad.camed.validation import preview

        p = self.panel
        previous = p.simulation
        p.status.text.return_value = 'Toolpath updated.'
        with patch.object(
            self.module, 'parse_program', return_value=(preview('G1 X10 F100', {}, None), None)
        ):
            p.apply_text()
        self.assertTrue(p.valid)
        self.assertTrue(p.operation.Visibility)
        self.assertEqual(p.operation.Gcode, ['G1 X10 F100'])
        previous.reload.assert_called_once_with(autoplay=False, preserve_camera=True)
        previous.cancel.assert_not_called()
        self.assertIs(p.simulation, previous)
        self.assertFalse(p.preview_failed)

    def test_partial_first_line_clears_old_path_without_resuming(self):
        p = self.panel
        p.editor.toPlainText.return_value = "G1 X"
        old_simulation = p.simulation
        p.text_changed()
        p.apply_text()
        self.assertFalse(p.valid)
        self.assertEqual(p.operation.Gcode, [])
        self.assertEqual(p.operation.LiveEditorSource, "G1 X")
        self.assertFalse(p.operation.Visibility)
        old_simulation.cancel.assert_not_called()
        old_simulation.reload.assert_not_called()
        old_simulation.set_enabled.assert_called_with(False)
        self.assertIs(p.simulation, old_simulation)

    def test_partial_last_line_shows_new_prefix_and_allows_manual_simulation(self):
        p = self.panel
        p.editor.toPlainText.return_value = "G1 X25 F300\nG0 Z"
        p.text_changed()
        p.apply_text()
        self.assertTrue(p.valid)
        self.assertTrue(p.operation.Visibility)
        self.assertEqual(p.operation.Gcode, ["G1 X25 F300"])
        self.assertEqual(p.operation.LiveEditorSource, "G1 X25 F300\nG0 Z")
        p.simulation.reload.assert_called_once_with(autoplay=False, preserve_camera=True)
        self.assertIn('Line 2', p.status.setText.call_args[0][0])

    def test_paused_simulation_does_not_autoplay(self):
        p = self.panel
        p.simulation.is_playing.return_value = False
        p.text_changed()
        p.apply_text()
        p.simulation.reload.assert_called_once_with(autoplay=False, preserve_camera=True)
        self.assertTrue(p.valid)

    def test_native_operation_failure_aborts_transaction(self):
        p = self.panel
        p.operation.Proxy.errors = [(1, "bad command")]
        p.text_changed()
        p.apply_text()
        p.document.abortTransaction.assert_called_once()
        p.document.commitTransaction.assert_not_called()
        self.assertFalse(p.valid)
        p.simulation.reload.assert_not_called()

    def test_changed_document_blocks_updates(self):
        p = self.panel
        self.module.App.ActiveDocument = None
        p.apply_text()
        self.assertFalse(p.valid)
        p.document.openTransaction.assert_not_called()
        p.simulation.pause.assert_called_once()

    def test_stock_preview_only_rebuilds_simulation_after_commit(self):
        self.scene()
        p = self.panel
        backend = types.ModuleType("freecad.camed.stock_backend")

        def apply(job, definition, *, transaction):
            job.Stock.Shape.BoundBox.XMax = definition
            return job.Stock

        backend.apply_stock = Mock(side_effect=apply)
        p.document.HasPendingTransaction = True
        with patch.dict(sys.modules, {"freecad.camed.stock_backend": backend}):
            p.apply_stock(60, transaction=False)
            p.sync_scene()
            p.apply_stock(80, transaction=False)
            p.simulation.reload.assert_not_called()
            p.document.HasPendingTransaction = False
            p.sync_scene()
            p.sync_scene()
        p.simulation.reload.assert_called_once_with(autoplay=True, preserve_camera=True)

    def test_first_stock_opens_simulator_without_refitting_or_taking_focus(self):
        self.scene()
        p = self.panel
        p.simulation = None
        stock = p.job.Stock
        p.job.Stock = None
        p.remember_scene()
        p.job.Stock = stock
        module = types.ModuleType("freecad.camed.simulation_gl")
        module.GLSession = Mock()
        with patch.dict(sys.modules, {"freecad.camed.simulation_gl": module}):
            p.sync_scene()
        module.GLSession.return_value.open.assert_called_once_with(focus=False, preserve_camera=True)

    def scene(self):
        p = self.panel
        tc = types.SimpleNamespace(
            Name='TC1',
            Label='Endmill',
            ToolNumber=1,
            HorizFeed='100',
            VertFeed='100',
            SpindleSpeed='1000',
            Tool=types.SimpleNamespace(Diameter=6, Shape=types.SimpleNamespace(Volume=20)),
        )
        p.operation.CAMEditorInitialTool = tc
        p.job = types.SimpleNamespace(
            Tools=types.SimpleNamespace(Group=[tc]),
            Stock=types.SimpleNamespace(
                Name='Stock',
                Placement='',
                Visibility=True,
                Shape=types.SimpleNamespace(
                    Volume=8000,
                    BoundBox=types.SimpleNamespace(XMin=0, YMin=0, ZMin=-10, XMax=40, YMax=20, ZMax=0),
                ),
            ),
            CAMEditorStockDefinition='',
        )
        p.remember_scene()
        return tc

    def test_empty_program_keeps_stock_in_cad_without_starting_gl(self):
        self.scene()
        p = self.panel
        p.simulation = None
        p.valid = False
        module = types.ModuleType('freecad.camed.simulation_gl')
        module.GLSession = Mock()
        with patch.dict(sys.modules, {'freecad.camed.simulation_gl': module}):
            p.ensure_simulation()
            p.ensure_simulation(focus=True)
        module.GLSession.assert_not_called()
        self.assertIsNone(p.simulation)

    def test_stock_change_outside_dialog_reloads_existing_gl_view(self):
        p = self.panel
        self.scene()
        p.job.Stock.Shape.BoundBox.XMax = 80
        p.sync_scene()
        p.simulation.reload.assert_called_once_with(autoplay=True, preserve_camera=True)
        p.sync_scene()
        p.simulation.reload.assert_called_once()

    def test_tool_geometry_change_reparses_t_assignments(self):
        p = self.panel
        tc = self.scene()
        p.apply_text = Mock()
        tc.Tool.Diameter = 8
        p.sync_scene()
        p.apply_text.assert_called_once()

    def test_native_tool_edit_keeps_gl_view_and_pauses_updates(self):
        p = self.panel
        self.scene()
        self.module.Gui.Control.activeDialog = lambda: object()
        p.sync_scene()
        p.simulation.pause.assert_called_once()
        p.simulation.set_enabled.assert_called_once_with(False)
        p.simulation.cancel.assert_not_called()
        p.simulation.focus.assert_not_called()
        p.simulation.reload.assert_not_called()

    def test_leaving_workbench_stops_watch_without_destroying_view(self):
        p = self.panel
        inspection = types.ModuleType('freecad.camed.inspection_tool')
        inspection.detach = Mock()
        with patch.dict(sys.modules, {'freecad.camed.inspection_tool': inspection}):
            p.set_active(False)
        inspection.detach.assert_called_once_with(p)
        self.assertFalse(p.enabled)
        p.watch_timer.stop.assert_called_once()
        p.simulation.pause.assert_called_once()
        p.simulation.cancel.assert_not_called()

    def test_inactive_workbench_does_not_reopen_simulation(self):
        p = self.panel
        p.enabled = False
        p.simulation = None
        module = types.ModuleType('freecad.camed.simulation_gl')
        module.GLSession = Mock()
        with patch.dict(sys.modules, {'freecad.camed.simulation_gl': module}):
            p.ensure_simulation()
        module.GLSession.assert_not_called()

    def test_reopening_editor_resets_shutdown_and_reattaches_view(self):
        p = self.panel
        p.shutting_down = True
        p.ensure_simulation = Mock()
        p.set_active(True)
        self.assertFalse(p.shutting_down)
        p.watch_timer.start.assert_called_once()
        p.ensure_simulation.assert_called_once_with()

    def test_external_tool_change_updates_warnings_without_a_simulator(self):
        from freecad.camed.program_backend import parse_program

        self.scene()
        p = self.panel
        p.job.Stock = None
        p.simulation = None
        p.editor.toPlainText.return_value = 'T7 M6\nG1 X10 F100'
        p.remember_scene()
        with (
            patch.object(self.module, 'parse_program', wraps=parse_program) as parse,
            patch.object(self.module, 'apply_preview'),
        ):
            p.apply_text()
            self.assertTrue(any('T7' in notice for notice in p.preview_result.notices))
            p.job.Tools.Group[0].ToolNumber = 7
            p.sync_scene()
            self.assertEqual(p.preview_result.notices, [])
            p.sync_scene()
            self.assertEqual(parse.call_count, 2)
            p.job.Tools.Group[0].ToolNumber = 1
            p.sync_scene()
            self.assertTrue(any('T7' in notice for notice in p.preview_result.notices))
            self.assertIsNone(p.simulation)

    def test_periodic_watch_does_not_select_gl_view(self):
        self.scene()
        self.panel.sync_scene()
        self.panel.simulation.focus.assert_not_called()

    def test_gl_button_returns_without_rebuilding_or_restarting(self):
        self.scene()
        p = self.panel
        p.simulation_dismissed = True
        p.show_simulation()
        self.assertFalse(p.simulation_dismissed)
        p.simulation.focus.assert_called_once()
        p.simulation.reload.assert_not_called()

    def test_dismissed_gl_view_is_not_automatically_recreated(self):
        self.scene()
        p = self.panel
        p.simulation = None
        p.simulation_dismissed = True
        module = types.ModuleType('freecad.camed.simulation_gl')
        module.GLSession = Mock()
        with patch.dict(sys.modules, {'freecad.camed.simulation_gl': module}):
            p.ensure_simulation()
            module.GLSession.assert_not_called()
            p.show_simulation()
            module.GLSession.assert_called_once_with(p)

    def test_external_full_source_updates_editor_and_preview(self):
        p = self.panel
        p.source_dirty = 'LiveEditorSource'
        p.operation.LiveEditorSource = 'G1 X25 F100'
        p.apply_text = Mock()
        p.sync_scene()
        p.editor.setPlainText.assert_called_once_with('G1 X25 F100')
        p.apply_text.assert_called_once()
        self.assertIsNone(p.source_dirty)

    def test_cursor_change_seeks_without_rebuilding(self):
        p = self.panel
        p.timer.isActive.return_value = False
        p.selected_source_line = Mock(return_value=7)
        p.cursor_changed()
        p.simulation.seek_line.assert_called_once_with(7)
        p.simulation.reload.assert_not_called()

    def test_typing_with_line_follow_enabled_does_not_resume_playback(self):
        p = self.panel
        p.selected_source_line = Mock(return_value=7)
        p.text_changed()
        p.simulation.pause.assert_called_once()

    def test_info_shows_cursor_block_and_actual_native_progress(self):
        from freecad.camed.validation import preview

        p = self.panel
        p.info = Mock()
        p.editor.textCursor.return_value.blockNumber.return_value = 1
        p.timer.isActive.return_value = False
        p.preview_result = preview('G0 Z5\nG1 X120 Y35 Z-5 F800 S6000 M3', {6: 1}, 6)
        p.simulation.closed = False
        p.simulation.frame_ready = True
        p.simulation.stage.value.return_value = 84
        p.simulation.stage.maximum.return_value = 200
        p.update_info()
        block = p.info.set_block.call_args.args[0]
        self.assertEqual(block.heading, 'Line 2 · G1 · T6')
        self.assertEqual(block.coordinates, 'X120 · Y35 · Z-5 mm')
        self.assertEqual(block.cutting, 'F800 · S6000 · M3')
        p.info.set_progress.assert_called_once_with(0.42)

    def test_typing_clears_stale_info_and_does_not_seek_old_snapshot(self):
        from freecad.camed.validation import preview

        p = self.panel
        p.info = Mock()
        p.editor.textCursor.return_value.blockNumber.return_value = 1
        p.timer.isActive.return_value = True
        p.preview_result = preview('G0 Z5\nG1 X120 F800')
        p.cursor_changed()
        block = p.info.set_block.call_args.args[0]
        self.assertEqual(block.coordinates, 'X— · Y— · Z— mm')
        self.assertIsNone(block.error)
        p.info.set_progress.assert_called_once_with(label='Updating…')
        p.simulation.seek_line.assert_not_called()

    def test_source_readout_and_simulation_always_follow_current_line(self):
        from freecad.camed.validation import preview

        p = self.panel
        p.info = Mock()
        p.editor.textCursor.return_value.blockNumber.return_value = 0
        p.timer.isActive.return_value = False
        p.preview_result = preview('G1 X15 F300', {1: 1}, 1)
        p.simulation.closed = False
        p.simulation.frame_ready = True
        p.simulation.stage.value.return_value = 20
        p.simulation.stage.maximum.return_value = 100
        p.cursor_changed()
        self.assertIn('X15', p.info.set_block.call_args.args[0].coordinates)
        p.info.set_progress.assert_called_once_with(0.2)
        p.simulation.seek_line.assert_called_once_with(1)

    def test_resource_scope_blocks_reentrant_watch_and_defers_code(self):
        p = self.panel
        self.scene()
        p.scene_timer = Mock()
        p.scene_timer.isActive.return_value = False
        p.timer.isActive.return_value = True
        with p.resource_update():
            self.assertEqual(p.resource_depth, 1)
            p.sync_scene()
            p.apply_text()
            p.simulation.reload.assert_not_called()
            self.assertTrue(p.pending_code)
        self.assertEqual(p.resource_depth, 0)
        p.scene_timer.start.assert_called_once_with()
        p.apply_text = Mock()
        p.sync_scene()
        p.apply_text.assert_called_once_with()

    def test_nested_resource_scope_releases_only_after_outer_operation(self):
        p = self.panel
        p.scene_timer = Mock()
        p.scene_timer.isActive.return_value = False
        p.timer.isActive.return_value = False
        with p.resource_update():
            with p.resource_update():
                self.assertEqual(p.resource_depth, 2)
            p.scene_timer.start.assert_not_called()
        p.scene_timer.start.assert_called_once_with()

    def test_resource_scope_releases_lock_after_creation_or_pause_error(self):
        p = self.panel
        p.scene_timer = Mock()
        p.scene_timer.isActive.return_value = False
        p.timer.isActive.return_value = False
        with self.assertRaises(ValueError):
            with p.resource_update():
                raise ValueError('tool creation failed')
        self.assertEqual(p.resource_depth, 0)
        p.simulation.pause.side_effect = RuntimeError('view gone')
        with self.assertRaises(RuntimeError):
            with p.resource_update():
                pass
        self.assertEqual(p.resource_depth, 0)

    def test_source_apply_and_watch_do_not_reenter_document_recompute(self):
        p = self.panel
        p.applying_program = True
        p.apply_text()
        p.sync_scene()
        self.assertTrue(p.pending_code)
        p.document.openTransaction.assert_not_called()
        p.simulation.reload.assert_not_called()

    def test_failed_stock_snapshot_is_not_retried_until_input_changes(self):
        from freecad.camed.validation import preview

        p = self.panel
        self.scene()
        p.preview_result = preview('G1 X10 F100', {1: 1}, 1)
        p.job.Stock.Shape.BoundBox.XMax = 80
        p.simulation.reload.side_effect = ValueError('invalid stock')
        p.sync_scene()
        p.sync_scene()
        p.simulation.reload.assert_called_once()
        self.assertTrue(p.preview_failed)
        p.simulation.set_enabled.assert_called_with(False)
        p.simulation.reload.side_effect = None
        p.job.Stock.Shape.BoundBox.XMax = 90
        p.sync_scene()
        self.assertFalse(p.preview_failed)
        self.assertEqual(p.simulation.reload.call_count, 2)

    def test_parse_failure_still_preserves_full_source(self):
        p = self.panel
        p.operation.LiveEditorSource = "old source"
        with patch.object(self.module, "parse_program", side_effect=ValueError("bad controller")):
            p.apply_text()
        self.assertEqual(p.operation.LiveEditorSource, "G1 X10 F100")
        self.assertTrue(p.preview_failed)
        p.document.openTransaction.assert_not_called()

    def test_source_can_flush_to_its_inactive_document(self):
        p = self.panel
        self.module.App.ActiveDocument = None
        self.assertFalse(p.is_current())
        p.flush_source()
        self.assertEqual(p.operation.LiveEditorSource, "G1 X10 F100")
        self.assertFalse(p.applying_program)
        p.document.recompute.assert_not_called()

    def test_native_pending_transaction_defers_preview_without_mutating_source(self):
        p = self.panel
        p.document.HasPendingTransaction = True
        p.operation.LiveEditorSource = "old source"
        p.apply_text()
        self.assertTrue(p.pending_code)
        self.assertEqual(p.operation.LiveEditorSource, "old source")
        p.document.openTransaction.assert_not_called()

    def test_close_during_a_native_task_is_rejected_before_teardown(self):
        p = self.panel
        self.module.Gui.Control.activeDialog = lambda: object()
        event = Mock()
        p.closeEvent(event)
        event.ignore.assert_called_once()
        self.assertFalse(p.shutting_down)
        p.watch_timer.stop.assert_not_called()

    def test_pending_source_defers_initial_gl_session_until_applied(self):
        self.scene()
        p = self.panel
        p.simulation = None
        p.pending_code = True
        module = types.ModuleType('freecad.camed.simulation_gl')
        module.GLSession = Mock()
        with patch.dict(sys.modules, {'freecad.camed.simulation_gl': module}):
            p.ensure_simulation()
            module.GLSession.assert_not_called()
            p.pending_code = False
            p.ensure_simulation()
            module.GLSession.assert_called_once_with(p)

    def test_active_task_blocks_reopening_existing_panel_before_any_action(self):
        p = self.panel
        p.close = Mock()
        self.module.Gui.Control.activeDialog = lambda: object()
        with patch.object(self.module, "_panel", p):
            with self.assertRaises(ValueError):
                self.module.show_panel()
        p.close.assert_not_called()
        p.document.openTransaction.assert_not_called()

    def test_stock_notice_tracks_stock_without_changing_program_notices(self):
        from freecad.camed.validation import preview

        p = self.panel
        p.info = Mock()
        p.editor.textCursor.return_value.blockNumber.return_value = 0
        p.preview_result = preview('T4 M6\nG1 X10 F100', {1: 1}, 1)
        tool_notices = p.preview_result.notices.copy()
        self.assertTrue(tool_notices)
        p.job = types.SimpleNamespace(Stock=None)
        missing = 'Stock is required for simulation.'
        for stock in (None, object(), None):
            p.job.Stock = stock
            p.update_info()
            displayed = p.info.set_block.call_args.args[1]
            self.assertEqual(displayed, tool_notices + ([missing] if stock is None else []))
        self.assertEqual(p.preview_result.notices, tool_notices)

    def test_unconfigured_stock_does_not_open_or_fail_gl(self):
        p = self.panel
        p.job = types.SimpleNamespace(Stock=None)
        p.simulation = None
        module = types.ModuleType('freecad.camed.simulation_gl')
        module.GLSession = Mock()
        with patch.dict(sys.modules, {'freecad.camed.simulation_gl': module}):
            p.ensure_simulation()
            p.ensure_simulation(focus=True)
        module.GLSession.assert_not_called()
        self.assertFalse(p.simulation_failed)


if __name__ == "__main__":
    unittest.main()
