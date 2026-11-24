"""Check scoped action/shortcut restoration with lightweight Qt substitutes."""

import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Action:
    def __init__(self, icon=None, text=None, parent=None):
        self.keys = []
        self.triggered = Mock()
        self.label = text

    def icon(self):
        return None

    def text(self):
        return self.label

    def shortcuts(self):
        return list(self.keys)

    def setShortcuts(self, keys):
        self.keys = list(keys)

    def setObjectName(self, name):
        self.name = name

    def setToolTip(self, text):
        pass

    def setEnabled(self, enabled):
        self.enabled = enabled


class Container:
    def __init__(self, actions):
        self.items = list(actions)

    def actions(self):
        return list(self.items)

    def insertAction(self, before, action):
        self.items.insert(self.items.index(before), action)

    def removeAction(self, action):
        self.items.remove(action)


class FileActionTests(unittest.TestCase):
    def setUp(self):
        self.original = Action(text='Save')
        self.original.keys = ['Ctrl+S']
        self.save_as = Action(text='Save As')
        self.save_as.keys = ['Ctrl+Shift+S']
        self.other = Action(text='Other')
        self.container = Container([self.other, self.original, self.save_as])
        self.main = Mock()
        self.main.findChild.side_effect = lambda cls, name: {
            'Std_Save': self.original,
            'Std_SaveAs': self.save_as,
        }.get(name)
        self.main.findChildren.side_effect = lambda cls: [self.container] if cls is Container else []
        gui = types.ModuleType('FreeCADGui')
        gui.getMainWindow = Mock(return_value=self.main)
        qt = types.ModuleType('PySide')
        qt.QtCore = types.SimpleNamespace(QObject=object)
        qt.QtGui = types.SimpleNamespace(QAction=Action)
        qt.QtWidgets = types.SimpleNamespace(QMenu=Container, QToolBar=type('Toolbar', (), {}))
        io = types.ModuleType('freecad.camed.file_io')
        self.active = Mock(return_value=object())
        io.active_operation = self.active
        with patch.dict(sys.modules, {'FreeCADGui': gui, 'PySide': qt}):
            sys.modules.pop('freecad.camed.file_actions', None)
            self.module = importlib.import_module('freecad.camed.file_actions')
        self.io_context = patch.dict(sys.modules, {'freecad.camed.file_io': io})
        self.io_context.start()
        self.addCleanup(self.io_context.stop)
        self.router = self.module.FileActionRouter.__new__(self.module.FileActionRouter)
        self.router.routes = {}
        self.router.enabled = True

    def test_routes_save_and_restores_original_order_and_shortcuts(self):
        self.router.refresh()
        save = self.router.routes['Std_Save']['replacement']
        self.assertEqual(self.original.keys, [])
        self.assertEqual(save.keys, ['Ctrl+S'])
        self.assertNotIn(self.original, self.container.items)
        self.router.enabled = False
        self.router.refresh()
        self.assertEqual(self.container.items, [self.other, self.original, self.save_as])
        self.assertEqual(self.original.keys, ['Ctrl+S'])
        self.assertEqual(self.save_as.keys, ['Ctrl+Shift+S'])
        self.assertEqual(save.keys, [])
        self.original.triggered.connect.assert_not_called()

    def test_switching_to_non_cam_document_restores_native_save(self):
        self.router.refresh()
        self.active.return_value = None
        self.router.refresh()
        self.assertEqual(self.container.items, [self.other, self.original, self.save_as])
        self.assertEqual(self.original.keys, ['Ctrl+S'])

    def test_repeated_refresh_does_not_duplicate_actions_or_lose_shortcuts(self):
        self.router.refresh()
        self.router.refresh()
        self.assertEqual(len(self.container.items), 3)
        self.assertEqual(self.router.routes['Std_Save']['replacement'].keys, ['Ctrl+S'])

    def test_open_is_routed_without_a_program_and_restored_when_leaving(self):
        original_open = Action(text='Open')
        original_open.keys = ['Ctrl+O']
        self.container.items.insert(0, original_open)
        self.main.findChild.side_effect = lambda cls, name: {
            'Std_Open': original_open,
            'Std_Save': self.original,
            'Std_SaveAs': self.save_as,
        }.get(name)
        self.active.return_value = None
        self.router.refresh()
        self.assertEqual(original_open.keys, [])
        self.assertEqual(self.router.routes['Std_Open']['replacement'].keys, ['Ctrl+O'])
        self.assertIn(self.original, self.container.items)
        self.router.enabled = False
        self.router.refresh()
        self.assertEqual(original_open.keys, ['Ctrl+O'])
        self.assertIs(self.container.items[0], original_open)


if __name__ == '__main__':
    unittest.main()
