"""Scope File > Open/Save/Save As to G-code while a CAMed program is active.

Original FreeCAD commands remain registered and connected. Their visible
menu/toolbar actions and shortcuts are restored when leaving the workbench.
"""

from .i18n import tr
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

_router = None


class FileActionRouter(QtCore.QObject):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.enabled = False
        self.routes = {}
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if enabled:
            self.timer.start()
        else:
            self.timer.stop()
        self.refresh()

    def should_route(self):
        if not self.enabled:
            return False
        from .file_io import active_operation

        return active_operation() is not None

    def execute(self, command):
        try:
            from .file_io import open_dialog, save_active

            if command == "open":
                open_dialog()
            else:
                save_active(command == "save_as")
        except Exception as error:
            if not getattr(error, "cameditor_reported", False):
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "CAMed", str(error))

    def refresh(self):
        main = Gui.getMainWindow()
        action_type = getattr(QtGui, "QAction", None) or QtWidgets.QAction
        route = self.should_route()
        containers = list(main.findChildren(QtWidgets.QMenu)) + list(main.findChildren(QtWidgets.QToolBar))
        button_actions = {}
        for name, command in (("Std_Open", "open"), ("Std_Save", "save"), ("Std_SaveAs", "save_as")):
            original = main.findChild(action_type, name)
            if original is None:
                continue
            entry = self.routes.get(name)
            if entry is None:
                replacement = action_type(original.icon(), original.text(), main)
                replacement.setObjectName("CAMed_" + name)
                replacement.setToolTip(
                    {
                        "open": tr('Open a G-code or FreeCAD file'),
                        "save": tr('Save G-code'),
                        "save_as": tr('Save G-code as'),
                    }[command]
                )
                replacement.triggered.connect(lambda checked=False, mode=command: self.execute(mode))
                entry = self.routes[name] = dict(original=original, replacement=replacement, shortcuts=None)
            replacement = entry["replacement"]
            if route or (self.enabled and command == "open"):
                if entry["shortcuts"] is None:
                    entry["shortcuts"] = original.shortcuts()
                    original.setShortcuts([])
                    replacement.setShortcuts(entry["shortcuts"])
                replacement.setEnabled(True)
                button_actions[original] = replacement
                for container in containers:
                    if original in container.actions():
                        container.insertAction(original, replacement)
                        container.removeAction(original)
            else:
                replacement.setShortcuts([])
                button_actions[replacement] = original
                for container in containers:
                    if replacement in container.actions():
                        container.insertAction(replacement, original)
                        container.removeAction(replacement)
                if entry["shortcuts"] is not None:
                    original.setShortcuts(entry["shortcuts"])
                    entry["shortcuts"] = None

        # Some native toolbar buttons keep a default action independently of
        # the toolbar's action list. Retarget these without dropping their menus.
        for button in main.findChildren(QtWidgets.QToolButton):
            previous = button.defaultAction()
            if previous in button_actions:
                button.setDefaultAction(button_actions[previous])
                button.removeAction(previous)


def activate(enabled):
    global _router
    if _router is None:
        _router = FileActionRouter()
    _router.set_enabled(enabled)
