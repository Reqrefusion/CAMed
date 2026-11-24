"""Native job controller number edits and removal."""

from .i18n import tr
from .transactions import document_transaction
from .tool_backend import MAX_TOOL_NUMBER, controllers
from .editor_lifecycle import require_idle
from .program_backend import require_document_idle


def _require_controller(owner, controller):
    require_idle()
    if owner.shutting_down or not owner.is_current():
        raise ValueError(tr('Activate the program document to edit tool settings.'))
    if not any(tc is controller for tc in controllers(owner.job)):
        raise ValueError(tr('The selected tool does not belong to this job.'))
    require_document_idle(owner.document)


def edit_number(owner, controller, parent):
    from PySide import QtWidgets

    _require_controller(owner, controller)
    with owner.resource_update():
        number = int(controller.ToolNumber)
        while True:
            number, accepted = QtWidgets.QInputDialog.getInt(
                parent, tr('Edit tool number'), tr('Tool number (T):'), number, 0, MAX_TOOL_NUMBER
            )
            if not accepted:
                return False
            _require_controller(owner, controller)
            if number == int(controller.ToolNumber):
                return False
            if any(tc is not controller and int(tc.ToolNumber) == number for tc in controllers(owner.job)):
                QtWidgets.QMessageBox.warning(
                    parent,
                    tr('Tool number in use'),
                    tr('T{number} is already assigned in this job. Enter a different number.').format(
                        number=number
                    ),
                )
                continue
            break
        document = owner.document
        with document_transaction(document, tr('Edit tool number')):
            controller.ToolNumber = number
            document.recompute()
        owner.pending_code = True
        return True


def set_initial_tool(owner, controller):
    _require_controller(owner, controller)
    operation = owner.operation
    if getattr(operation, 'CAMEditorInitialTool', None) is controller:
        return False
    with owner.resource_update():
        with document_transaction(owner.document, tr('Set initial tool')):
            if not hasattr(operation, 'CAMEditorInitialTool'):
                operation.addProperty('App::PropertyLink', 'CAMEditorInitialTool', 'CAMed')
            operation.CAMEditorInitialTool = controller
        owner.pending_code = True
    return True


def remove_from_job(owner, controller):
    from .tool_backend import operations

    _require_controller(owner, controller)
    allowed = [owner.job.Tools, *operations(owner.operation, owner.job)]
    if any(not any(ref is item for item in allowed) for ref in controller.InList):
        raise ValueError(tr('This tool is used by another job or CAM operation.'))
    with owner.resource_update():
        document = owner.document
        document.openTransaction(tr('Remove tool from job'))
        try:
            if _native_delete(controller) is False:
                document.abortTransaction()
                return False
            document.removeObject(controller.Name)
            document.recompute()
            document.commitTransaction()
        except Exception:
            document.abortTransaction()
            raise
        owner.pending_code = True
        return True


def _native_delete(controller):
    view = controller.ViewObject
    hook = getattr(getattr(view, 'Proxy', None), 'onDelete', None)

    def invoke():
        if hook is not None:
            return hook(view, None)
        from Path.Base import Util

        Util.clearExpressionEngine(controller)
        controller.Proxy.onDelete(controller, None)

    try:
        return invoke()
    except AttributeError as error:
        # Some weekly builds call the group cleanup method on a sketch BitBody.
        # Delete the same private body contents through the native document API,
        # then let the native ToolBit/controller hooks finish their cleanup.
        if 'removeObjectsFromDocument' not in str(error):
            raise
        tool = controller.Tool
        body = getattr(tool, 'BitBody', None)
        if body is None or len(tool.InList) != 1:
            raise
        document = controller.Document
        for child in list(getattr(body, "Group", ())):
            document.removeObject(child.Name)
        document.removeObject(body.Name)
        tool.BitBody = None
        return invoke()
