import types
import unittest
from unittest.mock import Mock
from freecad.camed.live_updates import DocumentObserver


class Owner:
    pass


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.owner = Owner()
        self.owner.enabled = True
        self.owner.shutting_down = False
        self.owner.document = object()
        self.owner.scene_timer = Mock()
        self.owner.scene_timer.isActive.return_value = False
        self.observer = DocumentObserver(self.owner)
        self.obj = types.SimpleNamespace(Document=self.owner.document)

    def test_object_and_recompute_notifications_schedule_update(self):
        self.observer.slotChangedObject(self.obj, 'Shape')
        self.owner.scene_timer.start.assert_called_once()
        self.owner.scene_timer.start.reset_mock()
        self.observer.slotRecomputedDocument(self.owner.document)
        self.owner.scene_timer.start.assert_called_once()

    def test_changes_in_one_event_loop_turn_are_coalesced(self):
        self.owner.scene_timer.isActive.return_value = True
        self.observer.slotChangedObject(self.obj, 'Diameter')
        self.observer.slotRecomputedObject(self.obj)
        self.observer.slotCreatedObject(self.obj)
        self.observer.slotDeletedObject(self.obj)
        self.owner.scene_timer.start.assert_not_called()

    def test_other_document_inactive_and_closed_editor_do_not_schedule(self):
        self.observer.slotRecomputedDocument(object())
        self.owner.enabled = False
        self.observer.slotChangedObject(self.obj, 'Shape')
        self.owner.enabled = True
        self.owner.shutting_down = True
        self.observer.slotChangedObject(self.obj, 'Shape')
        self.owner.scene_timer.start.assert_not_called()

    def test_external_program_source_is_marked_but_internal_writes_are_ignored(self):
        self.owner.operation = self.obj
        self.observer.slotChangedObject(self.obj, 'LiveEditorSource')
        self.assertEqual(self.owner.source_dirty, 'LiveEditorSource')
        self.observer.slotChangedObject(self.obj, 'Gcode')
        self.assertEqual(self.owner.source_dirty, 'LiveEditorSource')
        self.owner.source_dirty = None
        self.owner.applying_program = True
        self.observer.slotChangedObject(self.obj, 'Gcode')
        self.assertIsNone(self.owner.source_dirty)

    def test_mutation_and_internal_recompute_notifications_do_not_run_live_watch(self):
        self.owner.resource_depth = 1
        self.observer.slotCreatedObject(self.obj)
        self.observer.slotRecomputedDocument(self.owner.document)
        self.owner.scene_timer.start.assert_not_called()
        self.owner.resource_depth = 0
        self.owner.applying_program = True
        self.observer.slotRecomputedDocument(self.owner.document)
        self.owner.scene_timer.start.assert_not_called()
