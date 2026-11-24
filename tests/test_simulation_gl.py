"""GL stream/lifecycle tests with a strict fake engine; no Qt/GL rendering."""

from contextlib import contextmanager
import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch
from freecad.camed.validation import preview


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, fn):
        self.callbacks.append(fn)

    def disconnect(self, fn):
        self.callbacks.remove(fn)

    def emit(self, *args):
        for fn in list(self.callbacks):
            fn(*args)


class Timer:
    def __init__(self, owner):
        self.timeout = Signal()
        self.active = False

    @staticmethod
    def singleShot(delay, fn):
        fn()

    def setInterval(self, value):
        pass

    def start(self):
        self.active = True

    def stop(self):
        self.active = False


class QObject:
    def __init__(self, parent=None):
        pass


class Display:
    def __init__(self):
        self.play = Signal()
        self.singleStep = Signal()
        self.destroyed = Signal()
        self.stockVisibleChanged = Signal()
        self.baseVisibleChanged = Signal()
        self.pathVisibleChanged = Signal()
        self.path_button = Mock()
        self.stageChanged = Signal()
        self.playing = False
        self.pos = 0
        self.end = 0
        self.button = Mock()
        self.button.click.side_effect = self.click
        self.slider = Mock()
        self.slider.valueChanged = Signal()
        self.slider.value.side_effect = lambda: self.pos
        self.slider.maximum.side_effect = lambda: self.end
        self.step = Mock()
        self.controls = dict(
            playButton=self.button,
            stageSlider=self.slider,
            singleStepButton=self.step,
            pathButton=self.path_button,
            stockModelButton=Mock(),
        )

    def parentWidget(self):
        return None

    def metaObject(self):
        return types.SimpleNamespace(className=lambda: 'CAMSimulator::GuiDisplay')

    def findChild(self, cls, name):
        return self.controls.get(name)

    def click(self):
        self.playing = not self.playing
        self.play.emit(self.playing)


class Solid:
    def __init__(self, label='stock-1', length=40, width=20, height=10):
        self.label = label
        self.Volume = length * width * height
        self.Solids = [self]
        self.BoundBox = types.SimpleNamespace(
            XLength=length,
            YLength=width,
            ZLength=height,
            XMin=0,
            YMin=0,
            ZMin=0,
            XMax=length,
            YMax=width,
            ZMax=height,
        )

    def isNull(self):
        return False

    def isValid(self):
        return True

    def copy(self):
        return Solid(self.label, self.BoundBox.XLength, self.BoundBox.YLength, self.BoundBox.ZLength)

    def hashCode(self):
        return hash(self.label)


class Engine:
    def __init__(self, display):
        self.display = display
        self.commands = []
        self.tools = []
        self.builds = []
        self.resets = 0

    def ResetSimulation(self, doc):
        self.commands = []
        self.tools = []
        self.profiles = []
        self.resets += 1

    def AddTool(self, profile, number, diameter, resolution):
        self.tools.append(number)
        self.profiles.append((profile, diameter))
        self.commands.append(f'T{number}')  # Native AddTool's important side effect

    def AddCommand(self, command):
        self.commands.append(command.text)

    def BeginSimulation(self, stock, quality):
        self.builds.append((stock.label, quality))
        self.display.end = len(self.commands)
        self.display.pos = 0
        self.display.playing = False

    def SetBaseShape(self, shape, resolution):
        raise AssertionError('Stock reference must not be displayed as a part')


class GLTests(unittest.TestCase):
    def setUp(self):
        self.gui = types.ModuleType('FreeCADGui')
        self.qt = types.ModuleType('PySide')
        self.qt.QtCore = types.SimpleNamespace(
            QTimer=Timer,
            QObject=QObject,
            QEvent=types.SimpleNamespace(Paint=1),
            Qt=types.SimpleNamespace(Checked=2, Unchecked=0),
        )
        self.qt.QtWidgets = types.SimpleNamespace(
            QWidget=object, QToolButton=object, QSlider=object, QMdiArea=object,
            QApplication=types.SimpleNamespace(focusWidget=lambda: None),
        )
        self.path = types.ModuleType('Path')
        self.path.Command = lambda text, params: types.SimpleNamespace(text=text)
        self.modules = {'FreeCADGui': self.gui, 'PySide': self.qt, 'Path': self.path}
        with patch.dict(sys.modules, self.modules):
            sys.modules.pop('freecad.camed.simulation_gl', None)
            self.module = importlib.import_module('freecad.camed.simulation_gl')
        self.display = Display()
        self.engine = Engine(self.display)
        self.gui.getMainWindow = lambda: types.SimpleNamespace(
            findChildren=lambda cls: [self.display], findChild=lambda cls: None
        )
        self.gui.getDocument = Mock(return_value='gui-doc')
        self.gui.Control = types.SimpleNamespace(activeDialog=lambda: None, closeDialog=Mock())
        anchor = types.SimpleNamespace(Name='Program')
        extra = types.SimpleNamespace(CAMEditorProgram=anchor)
        unrelated = types.SimpleNamespace(Name='Other')
        tool = lambda: types.SimpleNamespace(Shape=Solid('tool', 6, 6, 20), Diameter=6)
        self.tcs = [
            types.SimpleNamespace(
                Name=f'TC{n}',
                Label=f'Tool {n}',
                ToolNumber=n,
                Tool=tool(),
                HorizFeed=100,
                VertFeed=100,
                SpindleSpeed=1000,
            )
            for n in (1, 6, 8)
        ]
        self.owner = types.SimpleNamespace(
            operation=anchor,
            document=object(),
            status=Mock(),
            is_current=Mock(return_value=True),
            job=types.SimpleNamespace(
                Tools=types.SimpleNamespace(Group=self.tcs),
                Stock=types.SimpleNamespace(Shape=Solid()),
                CAMEditorSession=True,
            ),
        )
        self.session = self.module.GLSession(self.owner)
        self.owner.simulation = self.session
        items = [Mock(), Mock(), Mock()]
        form = types.SimpleNamespace(listOperations=Mock(), toolButtonPlay=Mock())
        form.listOperations.item.side_effect = lambda i: items[i]
        self.items = items
        self.session.native = types.SimpleNamespace(
            onJobChange=Mock(),
            operations=[anchor, extra, unrelated],
            millSim=self.engine,
            GetToolProfile=Mock(return_value=[3, 20, 3, 0]),
            quality=10,
            baseShape='reference',
        )
        self.set_source('T6 M6\nG0 Z10\nG1 X10 F100')

    def set_source(self, source):
        self.owner.preview_result = preview(source, {1: 1, 6: 1, 8: 1}, 1)

    def reload(self, **kwargs):
        with patch.dict(sys.modules, self.modules):
            self.session.reload(**kwargs)

    def test_native_stream_registers_once_and_restores_tool_after_registration(self):
        self.set_source('T6 M6\nG0 Z10\nT8\nG1 X10 F100\nM6\nG1 X20\nT6 M6\nG1 X30')
        self.reload()
        self.assertEqual(self.engine.tools, [6, 8])
        self.assertEqual(
            self.engine.commands,
            [
                'T6',
                'T8',
                'T6',
                'G0 X0 Y0 Z0',
                'G0 Z10',
                'G1 X10 F100',
                'T8',
                'G1 X20 F100',
                'T6',
                'G1 X30 F100',
            ],
        )
        self.session.native.onJobChange.assert_not_called()  # No modal CAM task panel

    def test_invalid_change_only_loads_valid_prefix_and_never_autoplays(self):
        self.set_source('T6 M6\nG0 Z10\nG999\nG1 X30')
        self.reload(autoplay=True)
        self.assertEqual(self.engine.commands, ['T6', 'T6', 'G0 X0 Y0 Z0', 'G0 Z10'])
        self.assertFalse(self.session.autoplay_timer.active)

    def test_missing_tool_uses_previous_geometry_and_entire_timeline(self):
        self.set_source('T6 M6\nG0 Z10\nT5 M6\nG1 X30 F100\nT8 M6\nG1 X40')
        self.reload()
        self.assertIsNone(self.owner.preview_result.error)
        self.assertEqual(self.engine.tools, [6, 8])
        self.assertNotIn('T5', self.engine.commands)
        self.assertIn(5, self.owner.preview_result.tools)
        self.assertIn('G1 X30 F100', self.engine.commands)
        self.assertIn('G1 X40 F100', self.engine.commands)
        self.assertEqual(len(self.session.block_ends), 6)
        self.assertEqual(self.session.block_ends[-1], self.session.timeline_steps)
        self.assertEqual(self.session.native.GetToolProfile.call_count, 2)

    def test_no_tool_assignments_use_a_render_only_one_mm_tool(self):
        self.owner.job.Tools.Group = []
        self.owner.preview_result = preview('G0 Z10\nG1 X20 F100\nT1 M6\nG1 X30', {}, None)
        self.reload()
        self.assertEqual(len(self.engine.tools), 1)
        self.assertEqual(self.engine.profiles, [([0.5, 10, 0.5, 0, 0, 0], 1.0)])
        self.assertIn('G1 X30 F100', self.engine.commands)
        self.assertGreater(self.session.timeline_steps, 0)
        self.assertEqual(self.owner.job.Tools.Group, [])
        self.assertEqual(
            self.owner.preview_result.notices,
            [
                'No initial tool is defined for the move on line 1.',
                'T1 is not defined in this job (line 3).',
            ],
        )
        self.assertEqual(self.owner.preview_result.tools, [None, None, 1, 1])
        self.session.native.GetToolProfile.assert_not_called()

    def test_unknown_first_tool_uses_first_usable_job_tool_then_matches_source(self):
        self.tcs[0].Tool = None
        self.owner.preview_result = preview('T5 M6\nG0 Z10\nT8 M6\nG1 X30 F100', {1: 1, 6: 1, 8: 1}, None)
        self.reload()
        self.assertEqual(self.engine.tools, [6, 8])
        self.assertEqual(self.owner.preview_result.tools, [5, 5, 8, 8])
        self.assertEqual(self.owner.preview_result.notices, ['T5 is not defined in this job (line 1).'])
        self.assertEqual(self.session.block_ends[-1], self.session.timeline_steps)

    def test_adding_real_tool_replaces_previous_tool_geometry(self):
        self.set_source('T5 M6\nG0 Z10\nG1 X30 F100')
        self.reload()
        self.session.native.GetToolProfile.assert_called_once_with(self.tcs[0].Tool, 0.5)
        self.session.native.GetToolProfile.reset_mock()
        self.tcs.append(
            types.SimpleNamespace(
                Name='TC5',
                Label='Tool 5',
                ToolNumber=5,
                Tool=types.SimpleNamespace(Shape=Solid('real5', 6, 6, 20), Diameter=6),
                HorizFeed=100,
                VertFeed=100,
                SpindleSpeed=1000,
            )
        )
        self.owner.preview_result = preview('T5 M6\nG0 Z10\nG1 X30 F100', {5: 1}, 5)
        self.reload()
        self.session.native.GetToolProfile.assert_called_once_with(self.tcs[-1].Tool, 0.5)
        self.assertEqual(self.owner.preview_result.notices, [])

    def test_repeated_unknown_tool_uses_each_previous_tool_and_correct_arc_timing(self):
        self.tcs[1].Tool.Diameter = 2
        self.tcs[2].Tool.Diameter = 20
        self.set_source('T6 M6\nG0 X0 Y0\nT5 M6\nG2 I2 J0 F100\nT8 M6\nT5 M6\nG2 I2 J0')
        self.reload()
        self.assertEqual(self.engine.tools, [6, 8])
        self.assertEqual([s.display_tool for s in self.owner.preview_result.states], [6, 6, 6, 6, 8, 8, 8])
        self.assertEqual(self.session.block_ends[3] - self.session.block_ends[2], 182)
        self.assertEqual(self.session.block_ends[6] - self.session.block_ends[5], 17)
        self.assertNotIn('T5', self.engine.commands)

    def test_incomplete_source_pauses_existing_view_until_valid_motion_returns(self):
        self.reload()
        self.set_source('G1 X')
        self.reload(autoplay=True)
        self.assertEqual(len(self.engine.builds), 1)
        self.assertFalse(self.session.closed)
        self.assertIs(self.owner.simulation, self.session)
        self.display.button.setEnabled.assert_called_with(False)
        self.display.step.setEnabled.assert_called_with(False)

        self.set_source('G1 x100 y20 z-10')
        self.reload()
        self.assertEqual(len(self.engine.builds), 2)
        self.assertEqual(len(self.session.block_ends), 1)
        moves = [command for command in self.engine.commands if command.startswith('G1 ')]
        self.assertEqual(moves, ['G1 X100 Y20 Z-10'])
        self.display.button.setEnabled.assert_called_with(True)

    def test_reload_pauses_native_playback_and_resumes_after_initialization(self):
        self.reload()
        self.display.button.click()
        self.assertTrue(self.session.is_playing())
        self.reload(autoplay=True)
        self.assertFalse(self.session.is_playing())
        self.session._frame_rendered(self.session.generation)
        for _ in range(3):
            self.session._autoplay()
        self.assertTrue(self.session.is_playing())
        self.assertFalse(self.session.autoplay_timer.active)

    def test_stock_rebuild_uses_new_stock(self):
        self.reload()
        self.owner.job.Stock.Shape = Solid('stock-2')
        self.reload()
        self.assertEqual(self.engine.builds, [('stock-1', 10), ('stock-2', 10)])

    def test_finished_native_playback_does_not_count_as_running(self):
        self.reload()
        self.display.button.click()
        self.display.pos = self.display.end
        self.assertFalse(self.session.is_playing())

    def test_view_close_cancels_pending_restart_and_releases_owner(self):
        self.reload(autoplay=True)
        self.display.destroyed.emit()
        self.assertTrue(self.session.closed)
        self.assertIsNone(self.owner.simulation)
        self.assertFalse(self.session.autoplay_timer.active)
        self.gui.Control.closeDialog.assert_not_called()

    def test_cancel_pauses_disconnects_and_does_not_recreate_view(self):
        self.reload()
        self.display.button.click()
        resets = self.engine.resets
        self.session.cancel()
        self.assertFalse(self.display.playing)
        self.assertEqual(self.display.play.callbacks, [])
        self.assertIsNone(self.owner.simulation)
        self.reload(autoplay=True)
        self.assertEqual(self.engine.resets, resets)

    def test_inactive_document_does_not_touch_engine(self):
        self.owner.is_current.return_value = False
        self.reload()
        self.assertEqual(self.engine.resets, 0)

    def test_bad_tool_geometry_is_rejected(self):
        self.tcs[1].Tool.Shape.isValid = lambda: False
        with self.assertRaisesRegex(ValueError, 'T6'):
            self.reload()
        self.assertEqual(self.engine.builds, [])

    def test_autoplay_timeout_leaves_manual_play_available(self):
        self.reload(autoplay=True)
        self.display.end = 0
        for _ in range(50):
            self.session._autoplay()
        self.assertFalse(self.session.autoplay_timer.active)
        self.assertFalse(self.session.is_playing())
        self.owner.status.setText.assert_called_once()

    def test_open_builds_gl_view_without_native_task_panel(self):
        template = self.session.native

        class NativeGL:
            def __init__(self):
                self.quality = 10
                self.baseShape = None
                self.GetToolProfile = template.GetToolProfile

            def Activate(self):
                raise AssertionError('Must not open CAM task panel')

        modules = dict(self.modules)
        for name in ('Path.Main', 'Path.Main.Gui', 'Path.Main.Gui.SimulatorGL', 'CAMSimulator'):
            modules[name] = types.ModuleType(name)
        modules['Path.Main.Gui.SimulatorGL'].CAMSimulation = NativeGL
        modules['CAMSimulator'].PathSim = lambda: self.engine
        with patch.dict(sys.modules, modules):
            self.session.open()
        self.assertIsInstance(self.session.native, NativeGL)
        self.assertFalse(hasattr(self.session, "taskForm"))
        self.assertEqual(self.engine.builds, [('stock-1', 10)])

    def test_render_shows_stock_and_hides_reference_model(self):
        self.reload()
        changes = []
        self.display.stockVisibleChanged.connect(changes.append)
        base_changes = []
        self.display.baseVisibleChanged.connect(base_changes.append)
        self.session._frame_rendered(self.session.generation)
        self.assertEqual(changes, [True])
        self.assertEqual(base_changes, [False])
        self.display.controls["stockModelButton"].hide.assert_called_once_with()

    def test_autoplay_waits_for_actual_gl_paint(self):
        self.reload(autoplay=True)
        for _ in range(5):
            self.session._autoplay()
        self.assertFalse(self.session.is_playing())
        self.session._paint_started()
        self.session._autoplay()
        self.assertTrue(self.session.is_playing())

    def test_old_paint_callback_cannot_start_replaced_snapshot(self):
        self.reload(autoplay=True)
        old = self.session.generation
        self.reload(autoplay=True)
        self.session._frame_rendered(old)
        self.assertFalse(self.session.frame_ready)
        self.session._frame_rendered(self.session.generation)
        self.assertTrue(self.session.frame_ready)

    def test_queued_frame_does_not_touch_deleted_document_or_inactive_owner(self):
        class DeletedJob:
            @property
            def Stock(self):
                raise ReferenceError("Cannot access attribute 'Stock' of deleted object")

        self.owner.is_current.return_value = False
        self.owner.job = DeletedJob()
        self.session.pending_line = 4
        self.session._frame_rendered(self.session.generation)
        self.assertFalse(self.session.frame_ready)
        self.assertEqual(self.session.pending_line, 4)
        self.display.path_button.setChecked.assert_not_called()

    def test_explicit_manual_play_can_start_valid_partial_prefix(self):
        self.set_source('T6 M6\nG0 Z10\nG1 X')
        self.reload(autoplay=True, allow_partial=True)
        self.session._frame_rendered(self.session.generation)
        for _ in range(3):
            self.session._autoplay()
        self.assertTrue(self.session.is_playing())
        self.assertEqual(self.engine.commands, ['T6', 'T6', 'G0 X0 Y0 Z0', 'G0 Z10'])

    def test_closing_gl_view_stays_closed_until_explicit_request(self):
        self.reload()
        self.owner.enabled = True
        self.owner.shutting_down = False
        self.owner.ensure_simulation = Mock()
        self.display.destroyed.emit()
        self.owner.ensure_simulation.assert_not_called()
        self.assertTrue(self.owner.simulation_dismissed)
        self.assertIsNone(self.owner.simulation)

    def test_closing_view_while_editor_closes_does_not_reopen(self):
        self.reload()
        self.owner.enabled = True
        self.owner.shutting_down = True
        self.owner.ensure_simulation = Mock()
        self.display.destroyed.emit()
        self.owner.ensure_simulation.assert_not_called()

    def test_focus_selects_existing_gl_mdi_view(self):
        self.reload()

        class SubWindow:
            def __init__(self):
                self.show = Mock()

            def parentWidget(self):
                return None

        window = SubWindow()
        area = types.SimpleNamespace(setActiveSubWindow=Mock())
        self.qt.QtWidgets.QMdiArea = object
        self.qt.QtWidgets.QMdiSubWindow = SubWindow
        self.gui.getMainWindow = lambda: types.SimpleNamespace(findChild=lambda cls: area)
        self.display.parentWidget = lambda: window
        self.session.focus()
        area.setActiveSubWindow.assert_called_once_with(window)
        window.show.assert_called_once()

    def test_background_rebuild_restores_selected_cad_view(self):
        cad = object()
        area = types.SimpleNamespace(active=cad, activeSubWindow=Mock(), setActiveSubWindow=Mock())
        area.activeSubWindow.side_effect = lambda: area.active
        area.setActiveSubWindow.side_effect = lambda view: setattr(area, 'active', view)
        self.gui.getMainWindow = lambda: types.SimpleNamespace(
            findChildren=lambda cls: [self.display], findChild=lambda cls: area
        )
        begin = self.engine.BeginSimulation

        def activates_gl(stock, quality):
            area.setActiveSubWindow('gl-view')
            begin(stock, quality)

        focus = Mock()
        self.qt.QtWidgets.QApplication.focusWidget = lambda: focus
        self.engine.BeginSimulation = activates_gl
        self.reload()
        focus.setFocus.assert_called_once_with()
        self.assertEqual(
            area.setActiveSubWindow.call_args_list, [unittest.mock.call('gl-view'), unittest.mock.call(cad)]
        )
        area.setActiveSubWindow.reset_mock()
        focus.setFocus.reset_mock()
        self.reload(preserve_view=False)
        area.setActiveSubWindow.assert_called_once_with('gl-view')
        focus.setFocus.assert_not_called()

    def test_paths_start_visible_and_preserve_user_toggle_on_reload(self):
        changes = []
        self.display.pathVisibleChanged.connect(changes.append)
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.assertEqual(changes, [True])
        self.display.path_button.setChecked.assert_called_with(True)
        self.display.pathVisibleChanged.emit(False)
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.assertEqual(changes, [True, False, False])
        self.display.path_button.setChecked.assert_called_with(False)

    def test_failed_background_rebuild_also_preserves_cad_selection(self):
        cad = object()
        area = types.SimpleNamespace(activeSubWindow=lambda: cad, setActiveSubWindow=Mock())
        self.gui.getMainWindow = lambda: types.SimpleNamespace(
            findChildren=lambda cls: [self.display], findChild=lambda cls: area
        )
        self.tcs[1].Tool.Shape.isValid = lambda: False
        with self.assertRaises(ValueError):
            self.reload()
        area.setActiveSubWindow.assert_not_called()

    def test_seek_pauses_and_uses_motion_weights_without_rebuilding(self):
        self.set_source('G0 X0\nG1 X1\nG1 X10')
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.display.end = self.session.timeline_steps
        self.display.button.click()
        changes = []
        self.display.stageChanged.connect(changes.append)
        builds = len(self.engine.builds)
        self.session.seek_line(2)
        self.assertFalse(self.session.is_playing())
        self.assertEqual(len(self.engine.builds), builds)
        # 0->0 = 1 step, then 0->1 = 2; native next frame adds one.
        self.assertAlmostEqual(changes[0], 2.5 / 21)

    def test_seek_before_paint_keeps_latest_selected_source_line(self):
        self.reload()
        self.session.seek_line(2)
        self.session.seek_line(3)
        self.assertEqual(self.session.pending_line, 3)
        changes = []
        self.display.stageChanged.connect(changes.append)
        self.session._frame_rendered(self.session.generation)
        self.assertIsNone(self.session.pending_line)
        self.assertEqual(len(changes), 1)

    def test_snapshot_seeks_owner_cursor_after_render(self):
        self.owner.selected_source_line = lambda: 3
        self.reload()
        self.assertEqual(self.session.pending_line, 3)
        self.session._frame_rendered(self.session.generation)
        self.assertIsNone(self.session.pending_line)
        self.reload(autoplay=True)
        self.assertIsNone(self.session.pending_line)

    def test_native_full_circle_gets_explicit_endpoint(self):
        self.set_source('G0 X10 Y0\nG2 I-10 J0')
        self.reload()
        self.assertIn('G0 X0 Y0 Z0', self.engine.commands)
        self.assertIn('G2 I-10 J0 X10.000000000000 Y0.000000000000 Z0.000000000000', self.engine.commands)

    def test_empty_snapshot_has_no_seek_or_origin_motion(self):
        self.set_source('; no motion')
        self.reload()
        self.session._frame_rendered(self.session.generation)
        changes = []
        self.display.stageChanged.connect(changes.append)
        self.session.seek_line(1)
        self.assertEqual(changes, [])
        self.assertEqual(self.engine.commands, [])

    def test_quality_update_can_explicitly_preserve_progress(self):
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.display.pos = self.display.end // 2
        fraction = self.display.pos / self.display.end
        self.reload(autoplay=True, preserve_progress=True)
        self.assertEqual(self.session.pending_fraction, fraction)
        changes = []
        self.display.stageChanged.connect(changes.append)
        self.session._frame_rendered(self.session.generation)
        self.assertIsNone(self.session.pending_fraction)
        self.assertEqual(len(changes), 1)
        for _ in range(3):
            self.session._autoplay()
        self.assertTrue(self.session.is_playing())

    def test_explicit_restart_discards_previous_progress(self):
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.display.pos = self.display.end // 2
        self.reload(autoplay=True, allow_partial=True)
        self.assertIsNone(self.session.pending_fraction)

    def test_seeking_one_step_ahead_uses_native_single_step(self):
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.display.pos = 0
        emitted = []
        self.display.singleStep.connect(lambda: emitted.append(True))
        self.session._seek_fraction(1 / self.display.end)
        self.assertEqual(emitted, [True])

    def test_fast_seeks_keep_latest_target_before_native_slider_updates(self):
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.display.end = 100
        self.display.pos = 0
        targets = []
        self.display.stageChanged.connect(targets.append)
        self.session._seek_fraction(0.5)
        self.session._seek_fraction(0.1)
        self.session._seek_fraction(0.01)
        self.assertEqual(targets, [0.495, 0.095, 0.005])
        self.assertEqual(self.session.requested_step, 0)
        self.session._paint_started()
        self.assertIsNone(self.session.requested_step)

    def test_native_stage_slider_changes_refresh_readout_without_rebuild(self):
        self.owner.update_info = Mock()
        self.reload()
        builds = len(self.engine.builds)
        self.display.pos = 2
        self.display.slider.valueChanged.emit(2)
        self.owner.update_info.assert_called_once_with()
        self.assertEqual(len(self.engine.builds), builds)

    def test_cancel_disconnects_progress_updates(self):
        self.owner.update_info = Mock()
        self.reload()
        self.session.cancel()
        self.assertEqual(self.display.slider.valueChanged.callbacks, [])
        self.display.slider.valueChanged.emit(2)
        self.owner.update_info.assert_not_called()

    def test_bad_profiles_never_reset_last_good_native_snapshot(self):
        self.reload()
        resets = self.engine.resets
        commands = list(self.engine.commands)
        for bad in (
            None,
            [],
            [3, 20, 3],
            [float('nan'), 20, 3, 0],
            [-3, 20, 3, 0],
            [3, 0, 3, 0],
            [1e30, 20, 3, 0],
        ):
            with self.subTest(profile=bad):
                self.session.native.GetToolProfile.return_value = bad
                with self.assertRaises(ValueError):
                    self.reload()
                self.assertEqual(self.engine.resets, resets)
                self.assertEqual(self.engine.commands, commands)
                self.assertFalse(self.session.rebuilding)

    def test_bad_stock_never_touches_native_engine(self):
        self.reload()
        self.owner.job.Stock.Shape = Solid()
        self.owner.job.Stock.Shape.Solids = []
        resets = self.engine.resets
        with self.assertRaises(ValueError):
            self.reload()
        self.assertEqual(self.engine.resets, resets)

    def test_invalid_used_tool_is_rejected_before_reset(self):
        self.reload()
        resets = self.engine.resets
        self.tcs[1].Tool.Shape.isValid = lambda: False
        with self.assertRaises(ValueError):
            self.reload()
        self.assertEqual(self.engine.resets, resets)

    def test_incomplete_unused_new_tool_is_not_sent_to_native_gl(self):
        self.tcs.append(
            types.SimpleNamespace(
                Name='TC24',
                Label='new tool',
                ToolNumber=24,
                Tool=None,
                HorizFeed=100,
                VertFeed=100,
                SpindleSpeed=1000,
            )
        )
        self.reload()
        self.assertEqual(self.engine.tools, [6])
        self.session.native.GetToolProfile.assert_called_once_with(self.tcs[1].Tool, 0.5)

    def test_touched_tool_waits_for_geometry_recompute(self):
        self.tcs[1].Tool.State = ['Touched']
        with self.assertRaises(ValueError):
            self.reload()
        self.assertEqual(self.engine.resets, 0)
        self.session.native.GetToolProfile.assert_not_called()
        self.tcs[1].Tool.State = []
        self.reload()
        self.assertEqual(self.engine.resets, 1)

    def test_nested_reload_during_profile_extraction_is_deferred(self):
        self.session.native.GetToolProfile.side_effect = lambda *args: (
            self.session.reload(),
            [3, 20, 3, 0],
        )[1]
        self.reload()
        self.assertEqual(self.engine.resets, 1)
        self.assertTrue(self.owner.pending_code)
        self.assertFalse(self.session.rebuilding)

    def test_mutation_lock_blocks_reload_seek_and_autoplay(self):
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.owner.resource_depth = 1
        resets = self.engine.resets
        self.reload(autoplay=True)
        self.session.seek_line(3)
        self.session._autoplay()
        self.assertEqual(self.engine.resets, resets)
        self.assertTrue(self.owner.pending_code)
        self.assertFalse(self.session.is_playing())

    def test_geometry_change_mid_conversion_does_not_publish_stale_snapshot(self):
        def changed(*args):
            self.tcs[1].Tool.Diameter = 8
            return [3, 20, 3, 0]

        self.session.native.GetToolProfile.side_effect = changed
        with self.assertRaises(ValueError):
            self.reload()
        self.assertEqual(self.engine.resets, 0)

    def test_bad_diameter_and_step_overflow_do_not_reach_native_gl(self):
        for diameter in (0, -1, float('inf'), float('nan')):
            with self.subTest(diameter=diameter):
                self.tcs[1].Tool.Diameter = diameter
                with self.assertRaises(ValueError):
                    self.reload()
                self.assertEqual(self.engine.resets, 0)
        self.tcs[1].Tool.Diameter = 6
        self.set_source('T6 M6\nG1 X10000000000')
        with self.assertRaises(ValueError):
            self.reload()
        self.assertEqual(self.engine.resets, 0)

    def test_native_task_panel_blocks_snapshot_publication(self):
        self.gui.Control.activeDialog = lambda: object()
        self.reload()
        self.assertEqual(self.engine.resets, 0)
        self.assertTrue(self.owner.pending_code)

    def test_native_publish_cannot_paint_half_built_inputs(self):
        self.reload()
        state = {'updates': True}
        renderer = types.SimpleNamespace(
            updatesEnabled=lambda: state['updates'],
            setUpdatesEnabled=lambda value: state.update(updates=value),
        )
        renderer.parentWidget = lambda: None
        self.session.renderer = renderer
        original = self.engine.BeginSimulation
        blocked = []

        @contextmanager
        def block_signals(widget):
            self.assertIs(widget, renderer)
            blocked.append(True)
            try:
                yield
            finally:
                blocked.pop()

        self.qt.QtCore.QSignalBlocker = block_signals

        def begin(stock, quality):
            self.assertFalse(state['updates'])
            self.assertEqual(blocked, [True])
            original(stock, quality)

        self.engine.BeginSimulation = begin
        self.reload(preserve_camera=True)
        self.assertTrue(state['updates'])
        self.assertFalse(blocked)

    def test_render_update_state_is_restored_after_publish_exception(self):
        self.reload()
        state = {'updates': True}
        renderer = types.SimpleNamespace(
            updatesEnabled=lambda: state['updates'],
            setUpdatesEnabled=lambda value: state.update(updates=value),
        )
        self.session.renderer = renderer
        self.engine.AddTool = Mock(side_effect=RuntimeError('native bridge error'))
        with self.assertRaises(RuntimeError):
            self.reload()
        self.assertTrue(state['updates'])
        self.assertFalse(self.session.rebuilding)

    def test_live_program_change_starts_from_beginning(self):
        self.reload()
        self.session._frame_rendered(self.session.generation)
        self.display.pos = self.display.end // 2
        self.set_source('G1 X100 F200\nY50')
        self.reload(autoplay=True)
        self.assertIsNone(self.session.pending_fraction)
        self.assertEqual(self.display.pos, 0)

    def test_cancel_closes_own_native_view_and_retains_engine_until_destroyed(self):
        self.reload()

        class Window:
            def __init__(self):
                self.destroyed = Signal()
                self.close = Mock()

        window = Window()
        self.qt.QtWidgets.QMdiSubWindow = Window
        self.display.parentWidget = lambda: window
        self.session.cancel()
        window.close.assert_called_once()
        self.assertEqual(len(window.destroyed.callbacks), 1)
        self.assertTrue(self.session.closed)
        self.assertIsNone(self.owner.simulation)
