"""Follow existing NC documents without running GUI work inside document callbacks."""

from .i18n import tr

_tracker = None


class DocumentFollower:
    def __init__(self):
        import FreeCAD as App
        import FreeCADGui as Gui
        from PySide import QtCore

        self.following = True
        self.active = True
        self.switching = False
        self.last_programs = {}
        self.registered = True
        self.timer = QtCore.QTimer(Gui.getMainWindow())
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sync)
        self.timer.destroyed.connect(self.dispose)
        App.addDocumentObserver(self)

    def dispose(self, *args):
        import FreeCAD as App

        global _tracker
        self.following = False
        self.active = False
        if self.registered:
            App.removeDocumentObserver(self)
            self.registered = False
        if _tracker is self:
            _tracker = None

    def request(self, *args):
        if self.following and self.active and not self.switching:
            self.timer.start(0)

    def slotActivateDocument(self, document):
        self.request()

    def slotCreatedDocument(self, document):
        self.request()

    def slotChangedObject(self, obj, prop):
        if prop == "LiveEditorManaged":
            self.request()

    def slotDeletedDocument(self, document):
        try:
            self.last_programs.pop(document.Name, None)
        except (RuntimeError, ReferenceError):
            pass
        self.request()

    def slotDeletedObject(self, obj):
        from . import panel

        if panel._panel is not None and obj is panel._panel.operation:
            self.request()

    def target(self, document):
        import FreeCADGui as Gui

        if document is None:
            return None
        candidates = [op for op in document.Objects if getattr(op, 'LiveEditorManaged', False)]
        selected = Gui.Selection.getSelection()
        return next((op for op in candidates if op in selected), None) or next(
            (op for op in candidates if op.Name == self.last_programs.get(document.Name)),
            candidates[0] if len(candidates) == 1 else None,
        )

    def sync(self):
        import FreeCAD as App
        import FreeCADGui as Gui
        from . import panel

        if not self.following or not self.active or self.switching:
            return
        owner = panel._panel
        if Gui.Control.activeDialog() or (
            owner is not None
            and (getattr(owner, 'applying_program', False) or getattr(owner, 'resource_depth', 0))
        ):
            self.timer.start(100)
            return
        self.switching = True
        try:
            target = self.target(App.ActiveDocument)
            if owner is not None and target is owner.operation and owner.owns_operation():
                if owner.isHidden():
                    owner.show()
                    owner.watch_timer.start()
                    owner.path_selection.attach()
                    owner.sync_scene()
                return
            if target is not None:
                panel.show_panel(operation=target, focus=False)
            elif owner is not None:
                if owner.owns_operation():
                    owner.flush_source()
                    owner.pending_code = owner.pending_code or owner.timer.isActive()
                    owner.timer.stop()
                    owner.watch_timer.stop()
                    owner.scene_timer.stop()
                    owner.path_selection.detach()
                    if owner.simulation:
                        owner.simulation.pause()
                    owner.hide()
                else:
                    from .editor_lifecycle import close_editor

                    close_editor()
        except ValueError:
            # A native edit transaction may still be closing after tab activation.
            self.timer.start(100)
        except (ReferenceError, RuntimeError) as error:
            # Stop this handoff after one report; never flood Qt's event handler.
            self.following = False
            App.Console.PrintError(
                tr('CAMed could not switch documents: {error}\n').format(error=error)
            )
        finally:
            self.switching = False


def follow(owner):
    global _tracker
    if _tracker is None:
        _tracker = DocumentFollower()
    _tracker.following = True
    _tracker.active = True
    _tracker.last_programs[owner.document_name] = owner.operation_name
    if owner.shutting_down:
        _tracker.request()


def request():
    if _tracker is not None:
        _tracker.request()


def stop(owner):
    from . import panel

    if _tracker is not None and panel._panel is owner and not _tracker.switching:
        _tracker.following = False
        _tracker.timer.stop()


def set_active(enabled):
    if _tracker is not None:
        _tracker.active = bool(enabled)
        if enabled:
            _tracker.request()
        else:
            _tracker.timer.stop()
