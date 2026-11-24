"""Open FreeCAD's full ToolBit parameter dialog, applying accepted edits only."""

from .i18n import tr
from copy import deepcopy
from .tool_backend import controllers
from .editor_lifecycle import require_idle
from .program_backend import require_document_idle


def _apply_parameters(document, tool, edited):
    from Path.Tool.FeedsSpeeds import get_presets, set_presets

    # Keep the original document object, controller links and native BitBody.
    # Copy only values actually changed in the native detached working copy.
    shape_type = tool.Proxy._shape_type
    document.openTransaction(tr('Edit toolbit parameters'))
    try:
        for name in edited.obj.PropertiesList:
            if name in ('BitBody', 'Shape', 'Placement', 'Presets') or not hasattr(tool, name):
                continue
            value = edited.obj.getPropertyByName(name)
            if tool.getPropertyByName(name) != value:
                setattr(tool, name, value)
        presets = get_presets(edited.obj)
        if get_presets(tool) != presets:
            set_presets(tool, presets)
        tool.Proxy._shape_type = edited._shape_type
        document.recompute()
        if 'Invalid' in tool.State:
            raise ValueError(tr('FreeCAD could not compute the toolbit geometry.'))
        document.commitTransaction()
    except Exception:
        document.abortTransaction()
        tool.Proxy._shape_type = shape_type
        raise


def edit_parameters(owner, controller, parent, *, feeds_speeds=False):
    import FreeCAD as App
    from PySide import QtWidgets
    from Path.Tool.toolbit import ToolBit
    from Path.Tool.toolbit.ui.editor import ToolBitEditor

    require_idle()
    if owner.shutting_down or not owner.is_current():
        raise ValueError(tr('Activate the program document to edit the toolbit.'))
    if not any(tc is controller for tc in controllers(owner.job)):
        raise ValueError(tr('The selected tool does not belong to this job.'))
    tool = controller.Tool
    if tool is None:
        raise ValueError(tr('Toolbit geometry is not ready.'))
    document = owner.document
    require_document_idle(document)
    schema = App.Units.getSchema()
    editor = None
    with owner.resource_update():
        try:
            edited = ToolBit.from_dict(deepcopy(tool.Proxy.to_dict()))
            if edited._tool_bit_shape is tool.Proxy._tool_bit_shape:
                raise ValueError(tr('FreeCAD could not create a separate toolbit editing copy.'))
            # The T number belongs to the separate native controller editor.
            editor = ToolBitEditor(edited, parent=parent)
            if feeds_speeds:
                editor.form.tabWidget.setCurrentIndex(editor.feeds_tab_idx)
            if editor.show() != QtWidgets.QDialog.Accepted:
                return False
            require_idle()
            if owner.shutting_down or not owner.is_current():
                raise ValueError(tr("The tool's document is no longer active."))
            require_document_idle(document)
            _apply_parameters(document, tool, edited)
            owner.pending_code = True
            return True
        finally:
            # Construction can change units before the native dialog takes over.
            if App.Units.getSchema() != schema:
                App.Units.setSchema(schema)
            if editor is not None:
                editor.form.deleteLater()
                editor.deleteLater()
