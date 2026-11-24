"""FreeCAD document transactions shared by synchronous editor operations."""

from contextlib import contextmanager


@contextmanager
def document_transaction(document, label, *, enabled=True):
    """Join the caller's transaction when it already owns the undo step."""
    if not enabled:
        yield
        return
    document.openTransaction(label)
    try:
        yield
        document.commitTransaction()
    except Exception:
        document.abortTransaction()
        raise
