"""Plain G-code file handling through FreeCAD's import/export interface."""

from .i18n import tr
from . import nc_document
from .transactions import document_transaction
from pathlib import Path
import codecs
import os
import re
import tempfile
import FreeCAD as App
from .editor_lifecycle import close_editor as _close_editor, require_idle
from .program_documents import bind_path, initialize_program, new_document

EXTENSIONS = (".nc", ".ngc", ".tap", ".gcode")
FILTER = "G-code (*.nc *.ngc *.tap *.gcode)"


def _decode_source(raw):
    for bom, encoding in (
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
    ):
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding), encoding, bom
    # Turkish Windows NC files are often saved as ANSI rather than UTF-8.
    for encoding in ("utf-8", "cp1254", "cp1252"):
        try:
            return raw.decode(encoding), encoding, b""
        except UnicodeDecodeError:
            pass
    raise ValueError(tr('Cannot read the file encoding. Save the file as UTF-8.'))


def read_source(filename):
    return _decode_source(Path(filename).read_bytes())[0]


def show_open_error(error):
    import FreeCADGui as Gui
    from PySide import QtWidgets

    App.Console.PrintError(tr('CAMed could not open G-code: {error}\n').format(error=error))
    QtWidgets.QMessageBox.warning(Gui.getMainWindow(), tr('Could not open G-code'), str(error))
    error.cameditor_reported = True


def write_source(filename, source, *, preserve_format=False):
    """Encode before writing, then replace the destination in one operation."""
    path = Path(filename)
    resolved = path.resolve()
    if path.suffix.lower() not in EXTENSIONS or resolved.suffix.lower() not in EXTENSIONS:
        raise ValueError(tr('Use a .nc, .ngc, .tap or .gcode file extension.'))
    encoding, bom, newline = "utf-8", b"", "\n"
    if preserve_format:
        try:
            original = resolved.read_bytes()
        except FileNotFoundError:
            pass
        else:
            text, encoding, bom = _decode_source(original)
            line_break = re.search(r"\r\n|\n|\r", text)
            if line_break is not None:
                newline = line_break.group()
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    try:
        data = bom + normalized.replace("\n", newline).encode(encoding)
    except UnicodeEncodeError as error:
        raise ValueError(tr('Some characters cannot be saved in the original encoding. Use Save As to save a UTF-8 copy.')) from error

    descriptor, temporary = tempfile.mkstemp(prefix=".camed-", suffix=".tmp", dir=resolved.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, resolved)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(resolved)


def _editing_panel(operation):
    from . import panel

    owner = panel._panel
    if owner is not None and not owner.shutting_down and owner.operation is operation:
        return owner
    return None


def source_for(operation):
    owner = _editing_panel(operation)
    if owner is not None:
        return owner.editor.toPlainText()
    # An empty edited program is valid source; do not fall back to older commands.
    return (
        operation.LiveEditorSource if hasattr(operation, "LiveEditorSource") else "\n".join(operation.Gcode)
    )


def save_operation(operation, filename):
    previous = getattr(operation, "CAMEditorGCodePath", "")
    same_destination = bool(previous) and Path(previous).resolve() == Path(filename).resolve()
    path = write_source(filename, source_for(operation), preserve_format=same_destination)
    document = getattr(operation, "Document", None)
    state = nc_document.state_for(document)
    with nc_document.internal_update(document):
        bind_path(operation, path)
        if state is not None and previous and not same_destination and document.Label == Path(previous).name:
            document.Label = Path(path).name
    owner = _editing_panel(operation)
    if owner is not None:
        owner.editor.document().setModified(False)
        owner.update_info()
    if state is not None:
        state.set_source_modified(False)
    return path


def _load(filename, doc, source=None, *, rename_document=False):
    """Load into a fresh program, atomically; existing document programs are untouched."""
    if source is None:
        source = read_source(filename)
    import FreeCADGui as Gui
    from .program_backend import require_document_idle

    require_idle()
    require_document_idle(doc)
    _close_editor()
    App.setActiveDocument(doc.Name)
    from .sessions import prepare_session

    with document_transaction(doc, tr('Import CAMed G-code')):
        operation, created = prepare_session(new_program=True, transaction=False)
        if operation is None or not created:
            raise ValueError(tr('Could not create a program for the G-code file.'))
        result = initialize_program(
            operation,
            source,
            filename=filename,
            document_label=Path(filename).name if rename_document else None,
        )
        from .program_stock import apply_import_stock

        apply_import_stock(operation, result)
    try:
        _show_imported_program(operation, source, filename)
    except Exception as error:
        # The import is committed. A view failure must not trigger an import retry.
        from PySide import QtWidgets

        message = tr('Imported {filename} into {document}. The editor view could not be opened or updated.').format(
            filename=Path(filename).name, document=doc.Label
        )
        App.Console.PrintWarning(f'{message}\n{error}\n')
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), tr('G-code imported'), f'{message}\n{error}')
        return doc
    App.Console.PrintMessage(tr('CAMed opened G-code: {filename}\n').format(filename=filename))
    return doc


def _show_imported_program(operation, source, filename):
    import FreeCADGui as Gui
    from . import panel

    # The workbench's activation hook must also select the newly imported program.
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(operation)
    Gui.activateWorkbench("CAMedWorkbench")
    owner = panel.show_panel(operation=operation)
    if owner is not None:
        owner.editor.setPlainText(source)
        owner.apply_text()
        if hasattr(owner, "ensure_simulation"):
            owner.ensure_simulation(focus=True)
        if not getattr(owner, "preview_error", None):
            owner.status.setText(
                tr('Opened: {value1}\n').format(value1=Path(filename).name) + owner.status.text()
            )


def _open(filename):
    # Decode before creating a document, so a read failure leaves no empty project.
    source = read_source(filename)
    require_idle()
    _close_editor()
    with new_document() as doc:
        _load(filename, doc, source, rename_document=True)
        nc_document.track(doc)
        owner = _editing_panel(active_operation())
        if owner is not None:
            owner.editor.document().setModified(False)
            owner.update_info()
        return doc


def open(filename):
    try:
        return _open(filename)
    except Exception as error:
        show_open_error(error)
        raise


def insert(filename, document_name):
    """Standard File > Import handler for a selected existing document."""
    try:
        return _load(filename, App.getDocument(document_name))
    except Exception as error:
        show_open_error(error)
        raise


def open_dialog():
    import FreeCADGui as Gui
    from PySide import QtWidgets

    operation = active_operation()
    previous = getattr(operation, "CAMEditorGCodePath", "") if operation else ""
    filename, _ = QtWidgets.QFileDialog.getOpenFileName(
        Gui.getMainWindow(),
        tr('Open file'),
        previous,
        FILTER + tr(';;FreeCAD project (*.FCStd *.fcstd);;All files (*)'),
    )
    if not filename:
        return
    if Path(filename).suffix.lower() in EXTENSIONS:
        return open(filename)
    return Gui.open(filename)


def export(objects, filename):
    """Standard File > Export: accept a managed program, its job, or its stock."""
    programs = []
    for obj in objects:
        if getattr(obj, "LiveEditorManaged", False):
            matches = [obj]
        else:
            jobs = (
                [obj]
                if getattr(obj, "CAMEditorSession", False)
                else [
                    parent
                    for parent in getattr(obj, "InList", ())
                    if getattr(parent, "CAMEditorSession", False) and parent.Stock is obj
                ]
            )
            matches = [
                op for job in jobs for op in job.Operations.Group if getattr(op, "LiveEditorManaged", False)
            ]
        if not matches:
            raise ValueError(tr('Select a single CAMed program to export.'))
        for op in matches:
            if op not in programs:
                programs.append(op)
    if len(programs) != 1:
        raise ValueError(tr('Select a single CAMed program to export.'))
    # Export is a copy; it must not change the program's Save destination.
    return write_source(filename, source_for(programs[0]))


def active_operation():
    from . import panel

    owner = panel._panel
    if owner is not None and owner.is_current():
        return owner.operation
    doc = App.ActiveDocument
    programs = [obj for obj in doc.Objects if getattr(obj, "LiveEditorManaged", False)] if doc else []
    return programs[0] if len(programs) == 1 else None


def save_active(save_as=False):
    import FreeCADGui as Gui
    from PySide import QtWidgets

    operation = active_operation()
    if operation is None:
        raise ValueError(tr('Open the CAMed program to save.'))
    filename = getattr(operation, "CAMEditorGCodePath", "")
    if save_as or not filename:
        dialog = QtWidgets.QFileDialog(Gui.getMainWindow(), tr('Save G-code as'), "", FILTER)
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dialog.setDefaultSuffix("nc")
        dialog.selectFile(filename or "program.nc")
        if not (getattr(dialog, "exec", None) or dialog.exec_)():
            return False
        filename = dialog.selectedFiles()[0]
        if active_operation() is not operation:
            raise ValueError(tr('Activate the CAMed document.'))
    path = save_operation(operation, filename)
    owner = _editing_panel(operation)
    if owner is not None and owner.is_current():
        owner.status.setText(tr('G-code saved: {path}').format(path=path))
    return True
