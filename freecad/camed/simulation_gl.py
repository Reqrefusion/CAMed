"""Live G-code bridge to FreeCAD's native OpenGL CAM simulator.

The public GL API builds a snapshot, and its native Qt controls play/pause it.
Keep normalization/tool-change semantics in the editor; reuse CAM's tool-profile
conversion, stock renderer, camera, playback and material-removal engine.
"""

from .i18n import tr
from .gcode_model import position_words
from contextlib import contextmanager
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets


def simulation_commands(motion):
    """Build native commands, preserving tool changes and full-circle endpoints."""
    import Path

    commands = []
    active = None
    position = dict(X=0.0, Y=0.0, Z=0.0)
    for line, number in motion:
        if number != active:
            commands.append(Path.Command(f"T{number}", {}))
            if active is None:
                commands.append(Path.Command("G0 X0 Y0 Z0", {}))
            active = number
        coordinates = position_words(line)
        position.update(coordinates)
        if line.startswith(("G2 ", "G3 ")) and not coordinates:
            line += " " + " ".join(f"{axis}{value:.12f}" for axis, value in position.items())
        commands.append(Path.Command(line, {}))
    return commands


class _PaintObserver(QtCore.QObject):
    def __init__(self, callback, parent):
        super().__init__(parent)
        self.callback = callback

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Paint:
            self.callback()
        return False


class GLSession:
    def __init__(self, owner):
        self.owner = owner
        self.native = None
        self.display = None
        self.play_button = None
        self.stage = None
        self.playing = False
        self.enabled = True
        self.closed = False
        self.generation = 0
        self.frame_ready = False
        self.awaiting_paint = False
        self.frame_observer = None
        self.renderer = None
        self.autoplay_timer = QtCore.QTimer(owner)
        self.autoplay_timer.setInterval(40)
        self.autoplay_timer.timeout.connect(self._autoplay)
        self.pending_ticks = 0
        self.block_ends = []
        self.timeline_steps = 0
        self.pending_line = None
        self.pending_fraction = None
        self.requested_step = None
        self.rebuilding = False

    def open(self, *, preserve_camera=False):
        try:
            from Path.Main.Gui.SimulatorGL import CAMSimulation
        except ImportError as error:
            raise ValueError(tr('This FreeCAD build does not include the OpenGL CAM simulator.')) from error
        import CAMSimulator

        self.native = CAMSimulation()
        self.native.job = self.owner.job
        self.native.millSim = CAMSimulator.PathSim()
        self.native.quality = getattr(self.owner, "simulation_quality", 10)
        # Reuse CAM's profile converter and GL engine, without its modal task
        # panel. Stock/tools remain available while the GL view stays open.
        self.reload(preserve_view=preserve_camera, preserve_camera=preserve_camera)

    def focus(self):
        if self.display is None:
            return
        ancestor = self.display
        mdi_area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        while ancestor is not None:
            if isinstance(ancestor, QtWidgets.QMdiSubWindow):
                if mdi_area is not None:
                    mdi_area.setActiveSubWindow(ancestor)
                ancestor.show()
                return
            ancestor = ancestor.parentWidget()

    def _bind_display(self):
        # GuiDisplay is the native GL view's C++ QObject, not the task panel.
        # Its public play(bool) signal reports native user play/pause actions.
        if self.display is not None:
            return
        for widget in reversed(Gui.getMainWindow().findChildren(QtWidgets.QWidget)):
            if widget.metaObject().className().split("::")[-1] != "GuiDisplay":
                continue
            play = widget.findChild(QtWidgets.QToolButton, "playButton")
            stage = widget.findChild(QtWidgets.QSlider, "stageSlider")
            if play is None or stage is None:
                continue
            self.display = widget
            self.play_button = play
            self.stage = stage
            stage.valueChanged.connect(self._progress_changed)
            widget.play.connect(self._playing_changed)
            widget.singleStep.connect(self._stepped)
            widget.destroyed.connect(self._view_closed)
            widget.pathVisibleChanged.connect(self._paths_changed)
            if getattr(self.owner.job, "CAMEditorSession", False):
                stock_button = widget.findChild(QtWidgets.QToolButton, "stockModelButton")
                if stock_button is not None:
                    stock_button.hide()
            parent = widget.parentWidget()
            if parent is not None:
                for render in parent.findChildren(QtWidgets.QWidget):
                    if render.metaObject().className().split("::")[-1] == "DlgCAMSimulator":
                        self.renderer = render
                        self.frame_observer = _PaintObserver(self._paint_started, render)
                        render.installEventFilter(self.frame_observer)
                        break
            return
        raise ValueError(tr('Could not find the simulation playback controls.'))

    def _paint_started(self):
        self.requested_step = None
        if not self.awaiting_paint:
            return
        self.awaiting_paint = False
        token = self.generation
        # Event filters run before paintGL. A queued callback marks readiness
        # after native GL has actually initialized/rendered this snapshot.
        QtCore.QTimer.singleShot(0, lambda: self._frame_rendered(token))

    def _frame_rendered(self, token):
        if not self.closed and token == self.generation and self.owner.is_current():
            self.frame_ready = True
            self.display.stockVisibleChanged.emit(True)
            if getattr(self.owner.job, "CAMEditorSession", False):
                self.display.baseVisibleChanged.emit(False)
            visible = getattr(self.owner, "paths_visible", True)
            button = self.display.findChild(QtWidgets.QToolButton, "pathButton")
            if button is not None:
                button.setChecked(visible)
            self.display.pathVisibleChanged.emit(visible)
            if self.pending_line is not None:
                line = self.pending_line
                self.pending_line = None
                self.seek_line(line)
            elif self.pending_fraction is not None:
                fraction = self.pending_fraction
                self.pending_fraction = None
                self._seek_fraction(fraction)
            self._progress_changed()

    def _progress_changed(self, *args):
        if self.closed:
            return
        update = getattr(self.owner, "update_info", None)
        if callable(update):
            update()

    def seek_line(self, source_line):
        if (
            self.closed
            or not self.owner.is_current()
            or self.rebuilding
            or getattr(self.owner, "resource_depth", 0)
            or Gui.Control.activeDialog()
        ):
            return
        self.pause()
        if not self.frame_ready:
            self.pending_line = source_line
            return
        if (
            self.display is None
            or self.stage is None
            or self.timeline_steps <= 0
            or self.stage.maximum() <= 0
        ):
            return
        from .timeline import block_step

        fraction = block_step(self.block_ends, source_line) / self.timeline_steps
        if fraction == 0 and (self.stage.value() > 0 or self.requested_step is not None):
            # Native seeking to zero schedules a single step. A fresh snapshot
            # is the native API's way to show pristine stock before any move.
            self.reload()
            self.pending_line = source_line
            return
        self._seek_fraction(fraction)

    def _seek_fraction(self, fraction):
        if self.stage is None or self.stage.maximum() <= 0:
            return
        desired = round(fraction * self.stage.maximum())
        current = self.requested_step if self.requested_step is not None else self.stage.value()
        if self.requested_step is not None and desired == current + 1:
            return
        if self.requested_step is None and desired == current:
            return
        # Native SetSimulationStage schedules one single step on the next
        # frame; compensate so the displayed cutter ends at this block.
        target = max(0, desired - 1)
        if target == current:
            self.display.singleStep.emit()
        else:
            self.display.stageChanged.emit(float((target + 0.5) / self.stage.maximum()))
        self.requested_step = target

    def _paths_changed(self, visible):
        self.owner.paths_visible = bool(visible)

    def _playing_changed(self, playing):
        self.playing = bool(playing)

    def _stepped(self):
        self.playing = False

    def _view_closed(self, *args):
        if self.closed:
            return
        # Child widgets may already be destroyed; do not call their methods.
        self.frame_observer = None
        self.renderer = None
        self.display = None
        self.play_button = None
        self.stage = None
        self.playing = False
        self.autoplay_timer.stop()
        self.closed = True
        self.generation += 1
        if self.owner.simulation is self:
            self.owner.simulation = None
        self.owner.simulation_dismissed = True
        update = getattr(self.owner, "update_info", None)
        if callable(update):
            update()

    def is_playing(self):
        if self.closed or not self.playing:
            return False
        if (
            self.stage is not None
            and self.stage.maximum() > 0
            and self.stage.value() >= self.stage.maximum()
        ):
            self.playing = False
        return self.playing

    def pause(self):
        self.autoplay_timer.stop()
        if self.is_playing() and self.play_button is not None:
            self.play_button.click()
        self.playing = False

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if self.display is not None:
            for name in ("playButton", "singleStepButton", "stageSlider"):
                control = self.display.findChild(QtWidgets.QWidget, name)
                if control is not None:
                    control.setEnabled(self.enabled)

    def reload(
        self, autoplay=False, allow_partial=False, preserve_view=True, preserve_progress=False, *, preserve_camera=False
    ):
        if self.closed or not self.owner.is_current():
            return
        if self.rebuilding or getattr(self.owner, "resource_depth", 0) or Gui.Control.activeDialog():
            self.owner.pending_code = True
            request = getattr(self.owner, "request_update", None)
            if callable(request):
                request()
            return
        area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        previous_view = area.activeSubWindow() if area is not None and preserve_view else None
        self.rebuilding = True
        try:
            self._rebuild(autoplay, allow_partial, preserve_progress, preserve_camera)
        finally:
            self.rebuilding = False
            # Native Reset/BeginSimulation can activate their MDI view.
            # Even a failed live rebuild must preserve the user's tab.
            if previous_view is not None and self.owner.is_current():
                try:
                    area.setActiveSubWindow(previous_view)
                except RuntimeError:
                    pass  # The previous Qt window may have been closed.

    def _rebuild(self, autoplay, allow_partial, preserve_progress, preserve_camera):
        if self.closed or not self.owner.is_current():
            return
        result = self.owner.preview_result
        if not result.can_simulate:
            self.cancel()
            return
        from .simulation_input import prepare

        stock, quality, motion, tools, ends, total = prepare(self.owner, self.native)
        # Convert commands before ResetSimulation too: nothing below this
        # boundary may depend on partially built FreeCAD document objects.
        commands = simulation_commands(motion)
        previous_fraction = (
            self.stage.value() / self.stage.maximum()
            if preserve_progress
            and autoplay
            and not allow_partial
            and self.frame_ready
            and self.stage is not None
            and self.stage.maximum() > 0
            else None
        )
        self.pause()
        self.generation += 1
        self.frame_ready = False
        self.awaiting_paint = False
        self.requested_step = None
        with self._render_transaction() as freeze:
            self._publish(
                stock, quality, tools, commands, ends, total, result, autoplay, previous_fraction, freeze,
                preserve_camera,
            )
        if result.has_motion and autoplay and (not result.error or allow_partial):
            self.pending_ticks = 0
            self.autoplay_timer.start()

    @contextmanager
    def _render_transaction(self):
        """Prevent Qt/OCC event pumping from painting half-published GL inputs."""
        frozen = []

        def freeze(widget):
            if widget is not None and not any(old is widget for old, _ in frozen):
                previous = widget.updatesEnabled()
                widget.setUpdatesEnabled(False)
                frozen.append((widget, previous))

        try:
            freeze(self.renderer)
            yield freeze
        finally:
            for widget, previous in frozen:
                try:
                    widget.setUpdatesEnabled(previous)
                except RuntimeError:
                    pass  # Native MDI cloning/closing may delete the widget.

    def _publish(
        self, stock, quality, tools, commands, ends, total, result, autoplay, previous_fraction, freeze,
        preserve_camera,
    ):
        gui_doc = Gui.getDocument(self.owner.document)
        engine = self.native.millSim
        engine.ResetSimulation(gui_doc)
        self._bind_display()
        freeze(self.renderer)
        self.block_ends, self.timeline_steps = ends, total
        selector = getattr(self.owner, "selected_source_line", None)
        self.pending_line = selector() if callable(selector) and not autoplay else None
        self.pending_fraction = previous_fraction
        # Register each physical tool once. AddTool also appends a T command,
        # so explicitly select the correct first/changed tool in the stream.
        for profile, number, diameter in tools:
            engine.AddTool(profile, number, diameter, 1)
        for command in commands:
            engine.AddCommand(command)
        self.awaiting_paint = True
        self.native.quality = quality
        if preserve_camera and self.renderer is not None:
            # Native simulationStarted fits the stock and activates the view.
            # The GL engine initializes independently of that notification.
            with QtCore.QSignalBlocker(self.renderer):
                engine.BeginSimulation(stock, quality)
            window = self.renderer.parentWidget()
            while window is not None and not isinstance(window, QtWidgets.QMainWindow):
                window = window.parentWidget()
            if window is not None and not window.windowTitle():
                window.setWindowTitle(f"{self.owner.document.Label} - {tr('Simulation')}")
        else:
            engine.BeginSimulation(stock, quality)
        # CAMed's hidden reference is a stock helper, not a finished part.
        # Ordinary CAM projects can still display the actual base model.
        if not getattr(self.owner.job, "CAMEditorSession", False) and self.native.baseShape is not None:
            engine.SetBaseShape(self.native.baseShape, 1)
        self.playing = False
        self.set_enabled(result.has_motion)

    def _autoplay(self):
        self.pending_ticks += 1
        if (
            self.closed
            or not self.owner.is_current()
            or not self.enabled
            or getattr(self.owner, "resource_depth", 0)
            or Gui.Control.activeDialog()
        ):
            self.autoplay_timer.stop()
            return
        if (
            self.frame_ready
            and self.pending_ticks >= 3
            and self.stage is not None
            and self.stage.maximum() > 0
        ):
            self.autoplay_timer.stop()
            if not self.is_playing():
                self.play_button.click()
        elif self.pending_ticks >= 50:
            self.autoplay_timer.stop()
            self.owner.status.setText(tr('Simulation updated. Use the play button to start.'))

    def cancel(self):
        if self.closed:
            return
        self.pause()
        self.set_enabled(False)
        self.closed = True
        self.generation += 1
        if self.stage is not None:
            try:
                self.stage.valueChanged.disconnect(self._progress_changed)
            except (RuntimeError, TypeError):
                pass
        if self.display is not None:
            for signal, callback in (
                (self.display.play, self._playing_changed),
                (self.display.singleStep, self._stepped),
                (self.display.pathVisibleChanged, self._paths_changed),
                (self.display.destroyed, self._view_closed),
            ):
                try:
                    signal.disconnect(callback)
                except (RuntimeError, TypeError):
                    pass
        if self.renderer is not None and self.frame_observer is not None:
            try:
                self.renderer.removeEventFilter(self.frame_observer)
                self.frame_observer.deleteLater()
            except RuntimeError:
                pass
        if self.renderer is not None:
            self.renderer.setUpdatesEnabled(False)
        window = self.display.parentWidget() if self.display is not None else None
        while window is not None:
            if isinstance(window, QtWidgets.QMdiSubWindow):
                # Keep the engine alive until its native renderer is destroyed.
                lifetime = self.renderer if self.renderer is not None else window
                lifetime.destroyed.connect(lambda *args, native=self.native: None)
                window.close()
                break
            window = window.parentWidget()
        self.frame_observer = None
        self.renderer = None
        self.display = None
        self.play_button = None
        self.stage = None
        if self.owner.simulation is self:
            self.owner.simulation = None
