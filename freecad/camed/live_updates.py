"""Coalesce FreeCAD document notifications into the next Qt event-loop turn."""

import weakref


class DocumentObserver:
    def __init__(self, owner):
        self.owner = weakref.ref(owner)

    def changed(self, document):
        owner = self.owner()
        if owner is not None and owner.enabled and not owner.shutting_down and document is owner.document:
            if getattr(owner, "resource_depth", 0) or getattr(owner, "applying_program", False):
                return
            if not owner.scene_timer.isActive():
                owner.scene_timer.start()

    def slotChangedObject(self, obj, prop):
        owner = self.owner()
        if (
            owner is not None
            and obj is getattr(owner, "operation", None)
            and prop in ("LiveEditorSource", "Gcode")
            and not getattr(owner, "applying_program", False)
        ):
            if prop == "LiveEditorSource" or getattr(owner, "source_dirty", None) != "LiveEditorSource":
                owner.source_dirty = prop
        try:
            self.changed(obj.Document)
        except (RuntimeError, ReferenceError):
            pass

    def slotRecomputedObject(self, obj):
        try:
            self.changed(obj.Document)
        except (RuntimeError, ReferenceError):
            pass

    def slotRecomputedDocument(self, document):
        self.changed(document)

    def slotCreatedObject(self, obj):
        try:
            self.changed(obj.Document)
        except (RuntimeError, ReferenceError):
            pass

    def slotDeletedObject(self, obj):
        try:
            document = obj.Document
        except (RuntimeError, ReferenceError):
            owner = self.owner()
            document = owner.document if owner is not None else None
        self.changed(document)
