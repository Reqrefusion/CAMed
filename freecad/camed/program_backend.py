"""Keep source persistence separate from the replaceable native preview."""

from .i18n import tr
from .transactions import document_transaction


def require_document_idle(document):
    # Do not commit or join a native tool/task's unrelated undo transaction.
    if getattr(document, 'HasPendingTransaction', False) is True:
        raise ValueError(tr("Finish the document's current operation first."))


def persist_source(operation, source):
    """Write raw text before a preview transaction, without recomputing geometry."""
    if hasattr(operation, 'LiveEditorSource') and operation.LiveEditorSource == source:
        return False
    require_document_idle(operation.Document)
    if not hasattr(operation, 'LiveEditorSource'):
        operation.addProperty('App::PropertyString', 'LiveEditorSource', 'CAMed')
    operation.LiveEditorSource = source
    return True


def initial_tool(operation):
    if hasattr(operation, 'CAMEditorInitialTool'):
        return operation.CAMEditorInitialTool
    return getattr(operation, 'ToolController', None)


def _estimate_nc_job(proxy):
    job = proxy.obj
    for section in job.Operations.Group:
        if getattr(section, 'LiveEditorManaged', False) or getattr(section, 'CAMEditorProgram', None):
            controller = section.ToolController
            if (controller is None or controller.ToolNumber == 0) and section.Path.Length > 0:
                job.CycleTime = '—'
                return
    return type(proxy).getCycleTime(proxy)


def configure_cycle_time(job):
    """Keep the native job proxy in FCStd and specialize only this editor session."""
    if getattr(job, 'CAMEditorSession', False) is not True:
        return
    from Path.Main.Job import ObjectJob

    proxy = job.Proxy
    if type(proxy) is ObjectJob and 'getCycleTime' not in vars(proxy):
        from types import MethodType

        proxy.getCycleTime = MethodType(_estimate_nc_job, proxy)


def parse_program(operation, job, source):
    from .validation import preview

    initial = None
    if job is None:
        return preview(source), initial
    from .tool_backend import tool_numbers

    initial = initial_tool(operation)
    number = int(initial.ToolNumber) if initial else None
    return preview(source, tool_numbers(job), number), initial


def apply_preview(operation, job, result, initial=None):
    """Roll back generated paths on failure; never roll back the user's text."""
    document = operation.Document
    require_document_idle(document)
    with document_transaction(document, tr('Update CAMed preview')):
        if job is not None:
            from .tool_backend import update_operations

            configure_cycle_time(job)
            if not hasattr(operation, 'CAMEditorInitialTool'):
                operation.addProperty('App::PropertyLink', 'CAMEditorInitialTool', 'CAMed')
                operation.CAMEditorInitialTool = initial
            affected = update_operations(operation, job, result)
        else:
            operation.Gcode = result.lines
            operation.touch()
            affected = [operation]
        document.recompute()
        if any(
            getattr(getattr(item, 'Proxy', None), 'errors', []) or 'Invalid' in item.State
            for item in affected
        ):
            raise ValueError(tr('FreeCAD could not generate the toolpath.'))
