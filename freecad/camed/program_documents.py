"""Initialize new program metadata and own temporary document lifetimes."""

from .i18n import tr
from contextlib import contextmanager
from pathlib import Path
import sys


def bind_path(operation, filename):
    if not hasattr(operation, 'CAMEditorGCodePath'):
        operation.addProperty('App::PropertyString', 'CAMEditorGCodePath', 'CAMed')
    operation.CAMEditorGCodePath = str(Path(filename).resolve())


def initialize_program(operation, source, *, result=None, filename=None, label=None, document_label=None):
    """Only initialize fresh operations; reuse can never replace existing source."""
    if hasattr(operation, 'LiveEditorSource'):
        raise ValueError(tr('Cannot reinitialize an existing program. Create a new program.'))
    if result is None:
        from .validation import preview

        result = preview(source)
    operation.addProperty('App::PropertyString', 'LiveEditorSource', 'CAMed')
    operation.LiveEditorSource = source
    operation.Gcode = result.lines
    if filename is not None:
        bind_path(operation, filename)
        label = label if label is not None else Path(filename).name
    if label is not None:
        operation.Label = label
    if document_label is not None:
        operation.Document.Label = document_label
    return result


def _discard_document(app, document, previous_name):
    module = sys.modules.get(__package__ + '.panel')
    owner = getattr(module, '_panel', None)
    owns_panel = owner is not None and owner.document is document
    try:
        app.closeDocument(document.Name)
    finally:
        try:
            if owns_panel:
                try:
                    owner.close()
                finally:
                    owner.deleteLater()
                    if module._panel is owner:
                        module._panel = None
        finally:
            if previous_name is not None and previous_name in app.listDocuments():
                app.setActiveDocument(previous_name)


@contextmanager
def new_document(name='CAMed'):
    """Keep a successful new document; on failure discard only that document."""
    import FreeCAD as App

    previous_name = App.ActiveDocument.Name if App.ActiveDocument is not None else None
    document = App.newDocument(name)
    try:
        yield document
    except Exception as failure:
        try:
            _discard_document(App, document, previous_name)
        except Exception as cleanup_error:
            failure.add_note(
                tr('Could not clean up the new document: {cleanup_error}').format(
                    cleanup_error=cleanup_error
                )
            )
        raise
