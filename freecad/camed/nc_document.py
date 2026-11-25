"""Track saved NC text separately from changes that require an FCStd save."""

from contextlib import contextmanager


class NCState:
    def __init__(self, document):
        self.document = document
        self.source_modified = False
        self.project_modified = False
        self.internal_updates = 0

    def sync(self):
        if not self.document.FileName:
            import FreeCADGui as Gui

            Gui.getDocument(self.document.Name).Modified = self.source_modified or self.project_modified

    def set_source_modified(self, modified):
        self.source_modified = modified
        self.sync()


    def mark_project_modified(self):
        self.project_modified = True
        self.sync()


class NCObserver:
    def __init__(self):
        self.documents = {}

    def state(self, document):
        if document is None or getattr(document, "FileName", ""):
            return None
        state = self.documents.get(getattr(document, "Name", ""))
        return state if state is not None and state.document is document else None

    def changed(self, document):
        state = self.state(document)
        if state is not None and not state.internal_updates:
            state.project_modified = True

    def slotChangedObject(self, obj, prop):
        self.changed(getattr(obj, "Document", None))

    def slotCreatedObject(self, obj):
        self.changed(getattr(obj, "Document", None))

    slotDeletedObject = slotCreatedObject

    def slotRelabelDocument(self, document):
        self.changed(document)

    def slotChangedDocument(self, document, prop):
        self.changed(document)

    def slotDeletedDocument(self, document):
        self.documents.pop(document.Name, None)


_observer = None


def track(document):
    """Track only new documents created by opening an NC file."""
    import FreeCAD as App

    global _observer
    if _observer is None:
        _observer = NCObserver()
        App.addDocumentObserver(_observer)
    state = _observer.documents[document.Name] = NCState(document)
    state.sync()
    return state


def state_for(document):
    return _observer.state(document) if _observer is not None else None


@contextmanager
def internal_update(document):
    state = state_for(document)
    if state is None:
        yield
        return
    state.internal_updates += 1
    try:
        yield
    finally:
        state.internal_updates -= 1
        if not state.internal_updates:
            state.sync()
