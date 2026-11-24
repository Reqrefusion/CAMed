"""Shared preconditions and safe shutdown for editor-opening commands."""

from .i18n import tr


def require_idle():
    import FreeCADGui as Gui

    if Gui.Control.activeDialog():
        raise ValueError(tr('Finish or cancel the open CAM task first.'))


def close_editor():
    from . import panel

    require_idle()
    owner = panel._panel
    if owner is None:
        return
    if not getattr(owner, "shutting_down", False):
        owner.flush_source()
    if owner.close() is False:
        raise ValueError(tr('Cannot close the editor until the current operation finishes.'))
    owner.deleteLater()
    if panel._panel is owner:
        panel._panel = None
