import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch
from freecad.camed import editor_lifecycle


class EditorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.owner = types.SimpleNamespace(
            flush_source=Mock(), close=Mock(return_value=True), deleteLater=Mock()
        )
        self.panel = types.ModuleType('freecad.camed.panel')
        self.panel._panel = self.owner
        self.gui = types.ModuleType('FreeCADGui')
        self.gui.Control = types.SimpleNamespace(activeDialog=Mock(return_value=None))
        self.scope = patch.dict(
            sys.modules, {'freecad.camed.panel': self.panel, 'FreeCADGui': self.gui}
        )
        self.scope.start()
        self.addCleanup(self.scope.stop)
        package = importlib.import_module('freecad.camed')
        attribute = patch.object(package, 'panel', self.panel, create=True)
        attribute.start()
        self.addCleanup(attribute.stop)

    def test_active_task_never_flushes_or_closes_the_editor(self):
        self.gui.Control.activeDialog.return_value = object()
        with self.assertRaises(ValueError):
            editor_lifecycle.close_editor()
        self.owner.flush_source.assert_not_called()
        self.owner.close.assert_not_called()
        self.assertIs(self.panel._panel, self.owner)

    def test_failed_source_flush_keeps_the_editor_open(self):
        self.owner.flush_source.side_effect = RuntimeError('source write failed')
        with self.assertRaises(RuntimeError):
            editor_lifecycle.close_editor()
        self.owner.close.assert_not_called()
        self.owner.deleteLater.assert_not_called()
        self.assertIs(self.panel._panel, self.owner)

    def test_rejected_close_never_deletes_the_editor(self):
        self.owner.close.return_value = False
        with self.assertRaises(ValueError):
            editor_lifecycle.close_editor()
        self.owner.deleteLater.assert_not_called()
        self.assertIs(self.panel._panel, self.owner)

    def test_success_flushes_before_close_and_delete(self):
        order = []
        self.owner.flush_source.side_effect = lambda: order.append('flush')
        self.owner.close.side_effect = lambda: order.append('close') or True
        self.owner.deleteLater.side_effect = lambda: order.append('delete')
        editor_lifecycle.close_editor()
        self.assertEqual(order, ['flush', 'close', 'delete'])
        self.assertIsNone(self.panel._panel)
