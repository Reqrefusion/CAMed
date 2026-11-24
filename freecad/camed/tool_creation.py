"""Reuse the library's native New Toolbit flow, then attach it to this Job."""

from .i18n import tr
from .tool_backend import MAX_TOOL_NUMBER, controllers
from .editor_lifecycle import require_idle
from .program_backend import require_document_idle


def _require_owner(owner):
    require_idle()
    if owner.shutting_down or not owner.is_current():
        raise ValueError(tr('Activate the program document to add a tool.'))
    require_document_idle(owner.document)


def _create_bit(parent):
    from Path.Tool.library.ui.editor import LibraryEditor

    library = LibraryEditor(parent=parent)
    try:
        previous = {bit.get_id() for bit in library.browser.get_selected_bits()}
        # This is FreeCAD's own New Toolbit button handler. It owns shape/type
        # selection, dimensions, acceptance and library persistence.
        library._on_add_toolbit_requested()
        selected = library.browser.get_selected_bits()
        if len(selected) != 1 or selected[0].get_id() in previous:
            return None, None
        bit = selected[0]
        return bit, library.browser.get_tool_no_from_current_library(bit)
    finally:
        library.form.deleteLater()
        library.deleteLater()


def _choose_number(job, preferred, parent):
    from PySide import QtWidgets

    used = {int(tc.ToolNumber) for tc in controllers(job)}
    suggested = job.Proxy.nextToolNumber()
    number = int(preferred) if preferred is not None else suggested
    if 0 <= number <= MAX_TOOL_NUMBER and number not in used:
        return number
    if not 0 <= suggested <= MAX_TOOL_NUMBER or suggested in used:
        suggested = next((n for n in range(1, MAX_TOOL_NUMBER + 1) if n not in used), 0)
        if suggested in used:
            raise ValueError(tr('All job tool numbers are in use.'))
    while True:
        number, accepted = QtWidgets.QInputDialog.getInt(
            parent,
            tr('Job tool number'),
            tr('Choose an available tool number for this job:'),
            suggested,
            0,
            MAX_TOOL_NUMBER,
        )
        if not accepted:
            return None
        if number not in used:
            return number


def _attach_bit(owner, bit, number):
    from Path.Tool.Gui.Controller import Create

    _require_owner(owner)
    doc, job = owner.document, owner.job
    detached = bit.obj
    doc.openTransaction(tr('Add new toolbit to job'))
    try:
        tool = bit.attach_to_doc(doc)
        tc = Create(f'TC: {bit.label}', tool, number)
        job.Proxy.addToolController(tc)
        doc.recompute()
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        bit.obj = detached
        raise
    owner.pending_code = True
    return tc


def create_from_library(owner, parent):
    _require_owner(owner)
    with owner.resource_update():
        bit, preferred = _create_bit(parent)
        if bit is None:
            return None
        _require_owner(owner)
        number = _choose_number(owner.job, preferred, parent)
        if number is None:
            return None
        return _attach_bit(owner, bit, number)
