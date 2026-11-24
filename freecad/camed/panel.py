"""Reuse CAM's editor, native Path renderer and OpenGL CAM simulator."""

from .i18n import tr
import FreeCAD as App
from contextlib import contextmanager
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from Path.Main.Gui.Editor import CodeEditor
from PathScripts import PathUtils

from .program_backend import persist_source, parse_program, apply_preview

_panel = None


class LivePanel(QtWidgets.QDockWidget):
    def __init__(self, operation):
        super().__init__("CAMed", Gui.getMainWindow())
        self.setObjectName("CAMedDock")
        self.setMinimumWidth(360)
        self.operation = operation
        self.document = operation.Document
        self.document_name = self.document.Name
        self.operation_name = operation.Name
        self.simulation = None
        self.enabled = True
        self.shutting_down = False
        self.ui_ready = False
        self.simulation_failed = False
        self.simulation_dismissed = False
        self.paths_visible = True
        self.simulation_quality = 10
        self.scene_signature = None
        self.resource_depth = 0
        self.pending_code = False
        self.valid = False
        self.previous_visibility = operation.Visibility
        self.job = PathUtils.findParentJob(operation)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.apply_text)

        self._build_editor()
        self.editor.setPlainText(
            operation.LiveEditorSource
            if hasattr(operation, "LiveEditorSource")
            else "\n".join(operation.Gcode)
        )
        # CodeEditor uses FreeCAD's own highlighter. Initialising with text
        # enables it; no second syntax-highlighting implementation is added.
        self.editor.textChanged.connect(self.text_changed)
        self.editor.cursorPositionChanged.connect(self.cursor_changed)
        self.apply_text()
        if self.shutting_down:
            return
        self.ui_ready = True
        self.watch_timer = QtCore.QTimer(self)
        self.watch_timer.setInterval(250)
        self.watch_timer.timeout.connect(self.sync_scene)
        self.watch_timer.start()
        self.scene_timer = QtCore.QTimer(self)
        self.scene_timer.setSingleShot(True)
        self.scene_timer.setInterval(0)
        self.scene_timer.timeout.connect(self.sync_scene)
        self.document_observer = None
        self.attach_observer()
        from .inspection_tool import install as install_inspection

        install_inspection(self)

    def _build_editor(self):
        body = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        header = QtWidgets.QHBoxLayout()
        self.program_title = title = QtWidgets.QLabel(tr('Untitled.nc'), body)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        title.setMinimumWidth(60)
        title.setMaximumWidth(160)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        self.editor = CodeEditor(body)
        self.editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 4)
        self.editor.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.editor.setMinimumWidth(240)
        from .editor_tools import install

        install(self)
        self.number_menu_button = QtWidgets.QToolButton(body)
        self.number_menu_button.setText(tr('Line numbers'))
        self.number_menu_button.setAutoRaise(True)
        number_menu = QtWidgets.QMenu(self.number_menu_button)
        for name in ('Renumber', 'RemoveNumbers'):
            number_menu.addAction(self.editor_actions[name])
        self.number_menu_button.clicked.connect(
            lambda: number_menu.popup(
                self.number_menu_button.mapToGlobal(
                    self.number_menu_button.rect().bottomLeft() + QtCore.QPoint(0, 1)
                )
            )
        )
        header.addWidget(self.number_menu_button)
        from .info_panel import InfoPanel

        self.info = InfoPanel(body)
        self.status = self.info
        self.program_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, body)
        self.program_splitter.setChildrenCollapsible(False)
        self.code_area = QtWidgets.QWidget(self.program_splitter)
        code_layout = QtWidgets.QVBoxLayout(self.code_area)
        code_layout.setContentsMargins(0, 0, 0, 0)
        code_layout.setSpacing(4)
        code_layout.addWidget(self.editor, 1)
        self.program_splitter.addWidget(self.code_area)
        self.program_splitter.setStretchFactor(0, 1)
        self.program_area = QtWidgets.QWidget(body)
        self.program_row = QtWidgets.QHBoxLayout(self.program_area)
        self.program_row.setContentsMargins(0, 0, 0, 0)
        self.program_row.setSpacing(4)
        self.program_row.addWidget(self.program_splitter, 1)
        layout.addWidget(self.program_area, 1)
        layout.addWidget(self.info)
        self.setWidget(body)

    def attach_observer(self):
        if getattr(self, "scene_timer", None) is not None and self.document_observer is None:
            from .live_updates import DocumentObserver

            self.document_observer = DocumentObserver(self)
            App.addDocumentObserver(self.document_observer)

    def request_update(self):
        if (
            not self.shutting_down
            and self.enabled
            and getattr(self, "resource_depth", 0) == 0
            and getattr(self, "scene_timer", None) is not None
            and not self.scene_timer.isActive()
        ):
            self.scene_timer.start()

    @contextmanager
    def resource_update(self):
        """Native tool forms/libraries can pump Qt events during construction."""
        self.resource_depth = getattr(self, "resource_depth", 0) + 1
        try:
            if self.resource_depth == 1:
                self.pending_code = getattr(self, "pending_code", False) or self.timer.isActive()
                self.timer.stop()
                if getattr(self, "scene_timer", None) is not None:
                    self.scene_timer.stop()
                if self.simulation:
                    self.simulation.pause()
                    self.simulation.set_enabled(False)
            yield
        finally:
            self.resource_depth -= 1
            if self.resource_depth == 0:
                self.request_update()

    def selected_source_line(self):
        return self.editor.textCursor().blockNumber() + 1

    def cursor_changed(self, *args):
        if (
            not self.enabled
            or self.shutting_down
            or getattr(self, "resource_depth", 0)
            or getattr(self, "applying_program", False)
        ):
            return
        self.update_info()
        if not self.is_current() or self.timer.isActive():
            return
        line = self.selected_source_line()
        if line is not None and self.simulation is not None:
            self.simulation.seek_line(line)

    def update_info(self):
        if self.shutting_down:
            return
        if not self.owns_operation():
            self.retire()
            return
        info = getattr(self, "info", None)
        if info is None:
            return
        from .info_state import readout

        line = self.editor.textCursor().blockNumber() + 1
        pending = self.timer.isActive()
        result = None if pending else getattr(self, "preview_result", None)
        notices = list(result.notices) if result is not None else []
        if getattr(self, "job", None) is not None and self.job.Stock is None:
            notices.append(tr('Stock is required for simulation.'))
        info.set_block(readout(result, line), notices)
        info.set_position(line, self.editor.textCursor().positionInBlock() + 1)
        title = getattr(self, "program_title", None)
        if title is not None:
            from pathlib import Path

            path = getattr(self.operation, "CAMEditorGCodePath", "")
            name = Path(path).name if path else tr('Untitled.nc')
            title.setText(name + (" *" if self.editor.document().isModified() else ""))
            title.setToolTip(path or tr('Unsaved program'))
        if not self.is_current():
            info.set_progress(label=tr('Document inactive'))
        elif pending:
            info.set_progress(label=tr('Updating…'))
        elif getattr(self, "preview_failed", False):
            info.set_progress(label=tr('Stopped'))
        elif self.simulation is None or self.simulation.closed:
            info.set_progress(label=tr('Ready'))
        elif not self.simulation.frame_ready:
            info.set_progress(label=tr('Preparing…'))
        else:
            stage = self.simulation.stage
            fraction = stage.value() / stage.maximum() if stage is not None and stage.maximum() > 0 else 0
            info.set_progress(min(1, max(0, fraction)))

    def owns_operation(self):
        try:
            doc = App.getDocument(self.document.Name)
            return doc is self.document and doc.getObject(self.operation_name) is self.operation
        except (RuntimeError, ReferenceError):
            return False

    def is_current(self):
        return self.owns_operation() and App.ActiveDocument is self.document

    def flush_source(self):
        if not self.owns_operation():
            return
        previous = getattr(self, "applying_program", False)
        self.applying_program = True
        try:
            persist_source(self.operation, self.editor.toPlainText())
        finally:
            self.applying_program = previous

    def sim_controls(self, enabled):
        if self.simulation:
            self.simulation.set_enabled(enabled)

    def text_changed(self):
        if self.shutting_down:
            return
        self.valid = False
        if self.simulation:
            self.simulation.pause()
            self.sim_controls(False)
        self.status.setText(tr('Updating toolpath…'))
        self.timer.start()
        self.update_info()

    def apply_text(self):
        if self.shutting_down:
            return
        if not self.owns_operation():
            self.retire()
            return
        if (
            getattr(self, "resource_depth", 0)
            or getattr(self, "applying_program", False)
            or Gui.Control.activeDialog()
            or getattr(self.document, "HasPendingTransaction", False) is True
            or (self.simulation is not None and getattr(self.simulation, "rebuilding", False) is True)
        ):
            self.pending_code = True
            return
        self.pending_code = False
        self.timer.stop()
        if not self.is_current():
            self.valid = False
            if self.simulation:
                self.simulation.pause()
                self.sim_controls(False)
            self.status.setText(tr('Activate the program document. The program may have been deleted.'))
            return
        self.applying_program = True
        self.preview_failed = False
        try:
            source = self.editor.toPlainText()
            # Source survives parser, controller and native recompute failures.
            persist_source(self.operation, source)
            job = getattr(self, "job", None)
            result, initial = parse_program(self.operation, job, source)
            self.preview_result = result
            self.preview_error = result.error
            op = self.operation
            apply_preview(op, job, result, initial)
            navigation = getattr(self, 'path_selection', None)
            if navigation is not None:
                navigation.refresh(source, result)
            op.Visibility = result.has_motion
            self.valid = result.has_motion
            if result.error:
                self.status.setText(
                    tr('{value1}\nOnly motions before this error are shown.').format(value1=result.error)
                )
            else:
                self.status.setText(tr('Toolpath updated.') if source.strip() else tr('Ready'))
            if self.simulation:
                if result.can_simulate:
                    self.simulation.reload(autoplay=False)
                else:
                    self.simulation.cancel()
                    self.simulation = None
            self.remember_scene()
            if getattr(self, "ui_ready", False) and self.simulation is None:
                self.ensure_simulation()
        except Exception as error:
            if not self.owns_operation():
                self.retire()
                return
            self.preview_failed = True
            self.valid = False
            self.operation.Visibility = False
            if getattr(self, "job", None) is not None:
                from .tool_backend import operations

                for item in operations(self.operation, self.job):
                    item.Visibility = False
            self.sim_controls(False)
            self.status.setText(tr('Preview stopped: {error}').format(error=error))
            self.remember_scene()
        finally:
            self.applying_program = False
            self.update_info()

    def apply_stock(self, definition, *, transaction=True):
        if not self.is_current():
            raise ValueError(tr('Activate the CAMed document.'))
        from .stock_backend import apply_stock

        with self.resource_update():
            stock = apply_stock(self.job, definition, transaction=transaction)
        if transaction:
            self.sync_scene()
        return stock

    def clear_stock(self):
        if not self.is_current():
            raise ValueError(tr('Activate the CAMed document.'))
        from .stock_backend import clear_stock

        if self.simulation:
            self.simulation.cancel()
            self.simulation = None
        clear_stock(self.job)
        self.remember_scene()
        self.update_info()

    def remember_scene(self):
        if getattr(self, "job", None) is not None:
            try:
                from .scene_state import signature

                self.scene_signature = signature(self.job, self.operation)
            except (AttributeError, RuntimeError, ReferenceError):
                self.scene_signature = None

    def ensure_simulation(self, focus=False, *, preserve_camera=False):
        if self.shutting_down or not self.is_current():
            return
        if not self.valid:
            return
        if not getattr(getattr(self, 'preview_result', None), 'can_simulate', False):
            return
        if getattr(getattr(self, "job", None), "Stock", None) is None:
            if focus:
                self.update_info()
                self.status.details_button.setChecked(True)
            return
        if getattr(self, "resource_depth", 0) or getattr(self, "applying_program", False):
            return
        if getattr(self, "simulation_dismissed", False) and not focus:
            return
        if (
            not getattr(self, "ui_ready", False)
            or not self.enabled
            or self.shutting_down
            or not self.is_current()
            or self.simulation_failed
            or Gui.Control.activeDialog()
            or getattr(self, "pending_code", False)
            or getattr(self.document, "HasPendingTransaction", False) is True
        ):
            return
        if self.simulation is not None:
            if focus:
                self.simulation.focus()
            return
        from .simulation_gl import GLSession

        sim = GLSession(self)
        try:
            self.simulation = sim
            sim.open(preserve_camera=preserve_camera)
            self.remember_scene()
        except Exception as error:
            sim.cancel()
            self.simulation = None
            self.simulation_failed = True
            self.status.setText(tr('Could not open the simulation: {error}').format(error=error))

    def show_simulation(self):
        if Gui.Control.activeDialog():
            self.status.setText(tr('Close the tool editor first.'))
            return
        if getattr(self, 'preview_failed', False) or self.timer.isActive():
            self.apply_text()
        self.simulation_failed = False
        self.simulation_dismissed = False
        self.ensure_simulation(focus=True)

    def set_active(self, enabled):
        from . import editor_documents

        editor_documents.set_active(enabled)
        self.enabled = bool(enabled)
        if self.enabled:
            self.shutting_down = False
            self.simulation_failed = False
            self.watch_timer.start()
            self.attach_observer()
            navigation = getattr(self, 'path_selection', None)
            if navigation is not None:
                navigation.attach()
            self.ensure_simulation()
        else:
            from .inspection_tool import detach as detach_inspection

            detach_inspection(self)
            self.watch_timer.stop()
            if self.simulation:
                self.simulation.pause()

    def sync_scene(self):
        if (
            self.shutting_down
            or not self.enabled
            or getattr(self, "resource_depth", 0)
            or getattr(self, "applying_program", False)
            or (self.simulation is not None and getattr(self.simulation, "rebuilding", False) is True)
        ):
            return
        if not self.owns_operation():
            self.retire()
            return
        if not self.is_current():
            if self.simulation:
                self.simulation.pause()
            from . import editor_documents

            editor_documents.request()
            return
        self.update_info()
        if Gui.Control.activeDialog() or getattr(self.document, "HasPendingTransaction", False) is True:
            if self.simulation:
                self.simulation.pause()
                self.simulation.set_enabled(False)
            return
        if getattr(self, "pending_code", False):
            self.apply_text()
            return
        source_property = getattr(self, "source_dirty", None)
        if source_property:
            self.source_dirty = None
            source = (
                self.operation.LiveEditorSource
                if source_property == "LiveEditorSource"
                else "\n".join(self.operation.Gcode)
            )
            if source != self.editor.toPlainText():
                self.editor.setPlainText(source)
                self.apply_text()
                return
        if getattr(self.job, "Stock", None) is None and self.simulation is not None:
            self.simulation.cancel()
            self.simulation = None
        if self.job is not None:
            self._refresh_scene_resources()

    def _refresh_scene_resources(self):
        from .scene_state import signature

        current = None
        try:
            current = signature(self.job, self.operation)
            previous = self.scene_signature
            if previous is not None and current[1:] != previous[1:]:
                # Tool bindings and warnings also belong to the text preview.
                self.apply_text()
                return
            self.scene_signature = current
            stock_changed = previous is not None and current[0] != previous[0]
            if self.simulation is None:
                self.ensure_simulation(preserve_camera=stock_changed)
                return
            self.simulation.set_enabled(self.valid and not getattr(self, "preview_failed", False))
            if previous is None or current == previous:
                return
            running = self.simulation.is_playing()
            self.simulation.reload(autoplay=running and not self.preview_error, preserve_camera=stock_changed)
            if getattr(self, "preview_failed", False):
                self.preview_failed = False
                self.valid = getattr(getattr(self, "preview_result", None), "has_motion", self.valid)
                self.status.setText(str(self.preview_error) if self.preview_error else tr('Simulation updated.'))
        except Exception as error:
            self.preview_failed = True
            if current is not None:
                self.scene_signature = current
            if self.simulation is not None:
                self.simulation.pause()
                self.simulation.set_enabled(False)
            self.status.setText(tr('Could not update the simulation: {error}').format(error=error))

    def stop_updates(self):
        self.shutting_down = True
        cycle_dialog = getattr(self, 'cycle_dialog', None)
        if cycle_dialog is not None:
            cycle_dialog.reject()
        for name in ('timer', 'watch_timer', 'scene_timer'):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        from .inspection_tool import detach

        detach(self)
        observer = getattr(self, 'document_observer', None)
        if observer is not None:
            App.removeDocumentObserver(observer)
            self.document_observer = None
        if self.simulation:
            self.simulation.cancel()
            self.simulation = None

    def retire(self):
        self.stop_updates()
        self.hide()
        from . import editor_documents

        editor_documents.request()

    def closeEvent(self, event):
        if self.shutting_down:
            super().closeEvent(event)
            return
        if (
            getattr(self, "applying_program", False)
            or getattr(self, "resource_depth", 0)
            or (Gui.Control.activeDialog() and self.is_current())
        ):
            self.status.setText(tr('Finish or cancel the current CAM task. Your code is retained.'))
            event.ignore()
            return
        try:
            self.flush_source()
        except Exception as error:
            self.status.setText(tr('Could not preserve the program text: {error}').format(error=error))
            event.ignore()
            return
        # Raw source is already saved above; do not rebuild a renderer while closing.
        self.stop_updates()
        from . import editor_documents

        editor_documents.stop(self)
        if self.is_current():
            self.operation.Visibility = self.previous_visibility
        super().closeEvent(event)


def _can_reuse_panel(operation):
    if _panel is None or _panel.shutting_down or not _panel.is_current():
        return False
    if operation is None:
        for selected in Gui.Selection.getSelection():
            if selected.Document is _panel.document and getattr(selected, "LiveEditorManaged", False):
                return selected is _panel.operation
        return True
    return operation is _panel.operation


def show_panel(operation=None, *, focus=True):
    global _panel
    if Gui.Control.activeDialog():
        raise ValueError(tr('Finish or cancel the open task, then try again.'))
    if _can_reuse_panel(operation):
        _panel.show()
        _panel.raise_()
        _panel.set_active(True)
        from .editor_documents import follow

        follow(_panel)
        return _panel
    if operation is None:
        from .sessions import prepare_session

        operation, _ = prepare_session()
        if operation is None:
            return
    elif (
        operation.Document is not App.ActiveDocument
        or operation.Document.getObject(operation.Name) is not operation
        or not getattr(operation, "LiveEditorManaged", False)
    ):
        raise ValueError(tr('Select a CAMed program in the active document.'))
    area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea) if not focus else None
    view = area.activeSubWindow() if area is not None else None
    if _panel is not None:
        from .editor_lifecycle import close_editor

        close_editor()
    if operation.Document is not App.ActiveDocument:
        App.setActiveDocument(operation.Document.Name)
    _panel = LivePanel(operation)
    Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, _panel)
    _panel.show()
    if view is not None:
        try:
            area.setActiveSubWindow(view)
        except RuntimeError:
            pass
    from .editor_documents import follow

    follow(_panel)
    owner = _panel
    QtCore.QTimer.singleShot(
        0,
        lambda: (
            owner.ensure_simulation(focus=focus)
            if _panel is owner and not owner.shutting_down and owner.is_current()
            else None
        ),
    )
    return _panel
