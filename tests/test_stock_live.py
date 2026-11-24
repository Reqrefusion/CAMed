"""Live stock and Cancel semantics with stub widgets; no GUI rendering."""

import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch
from freecad.camed.stock_definition import StockDefinition


class Dialog:
    def accept(self):
        self.accepted = True

    def reject(self):
        self.rejected = True


class StockLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qt = types.ModuleType('PySide')
        qt.QtCore = types.SimpleNamespace(Signal=lambda *args: Mock())
        qt.QtWidgets = types.SimpleNamespace(
            QWidget=object, QDialog=Dialog, QMessageBox=types.SimpleNamespace(warning=Mock())
        )
        gui = types.ModuleType('FreeCADGui')
        backend = types.ModuleType('freecad.camed.stock_backend')
        backend.load_definition = Mock()
        backend.stock_rotation = Mock()
        backend.validate_dimensions = lambda definition: definition.bounds()
        with patch.dict(
            sys.modules, {'PySide': qt, 'FreeCADGui': gui, 'freecad.camed.stock_backend': backend}
        ):
            for name in ('freecad.camed.stock_panel', 'freecad.camed.stock_tool'):
                sys.modules.pop(name, None)
            cls.panel_module = importlib.import_module('freecad.camed.stock_panel')
            cls.dialog_module = importlib.import_module('freecad.camed.stock_tool')

    def form(self):
        p = self.panel_module.StockPanel.__new__(self.panel_module.StockPanel)
        p.live = True
        p.loading = False
        p.geometry_dirty = True
        p.live_timer = Mock()
        p.live_timer.isActive.return_value = False
        p.message = Mock()
        p.summary = Mock()
        p.apply_button = Mock()
        p.definition = Mock(return_value=StockDefinition(length=80, width=40, height=20))
        p.stock = types.SimpleNamespace(Visibility=True)
        p.current_kind = "box_dimensions"
        p.fields = {p.current_kind: {}}
        p.model = p.definition.return_value
        p.job = types.SimpleNamespace(Stock=p.stock)
        p.apply_callback = Mock(return_value=p.stock)
        p.load = Mock()
        return p

    def test_valid_field_change_schedules_live_update(self):
        p = self.form()
        p.refresh_summary()
        p.live_timer.start.assert_called_once()
        p.apply_callback.assert_not_called()
        p.preview()
        p.apply_callback.assert_called_once_with(p.definition.return_value)
        self.assertFalse(p.geometry_dirty)
        p.load.assert_not_called()  # Keep the field currently being typed intact

    def test_invalid_dimension_keeps_last_valid_stock(self):
        p = self.form()
        p.model = p.definition.return_value = StockDefinition(length=-10)
        p.refresh_summary()
        p.live_timer.start.assert_not_called()
        p.live_timer.stop.assert_called_once()
        p.apply_callback.side_effect = ValueError("invalid dimension")
        self.assertFalse(p.apply())
        p.apply_callback.assert_not_called()

    def test_confirm_does_not_schedule_an_endless_live_loop(self):
        p = self.form()
        self.assertTrue(p.apply())
        p.load.assert_not_called()
        p.live_timer.start.assert_not_called()

    def test_backend_failure_preserves_preview_state_and_reports_error(self):
        p = self.form()
        p.apply_callback.side_effect = ValueError('invalid stock')
        self.assertFalse(p.apply())
        self.assertTrue(p.geometry_dirty)
        self.assertIn('invalid stock', p.message.setText.call_args[0][0])

    def dialog(self):
        d = self.dialog_module.StockDialog.__new__(self.dialog_module.StockDialog)
        d.owner = Mock()
        d.document = d.owner.document
        d.document.HasPendingTransaction = False
        d.edit_started = False
        d.live = True
        d.stock_form = types.SimpleNamespace(live_timer=Mock(), apply=Mock(return_value=True))
        d.accepted = False
        d.rejected = False
        return d

    def test_cancel_rolls_back_all_previews_without_reconstructing_geometry(self):
        d = self.dialog()
        spec = StockDefinition(length=40)
        d.apply_preview(spec)
        d.apply_preview(spec)
        d.document.openTransaction.assert_called_once()
        d.owner.apply_stock.assert_called_with(spec, transaction=False)
        d.reject()
        d.document.abortTransaction.assert_called_once()
        d.document.recompute.assert_called_once()
        d.owner.sync_scene.assert_called_once()
        self.assertTrue(d.rejected)

    def test_cancel_without_edits_leaves_document_untouched(self):
        d = self.dialog()
        d.reject()
        d.document.abortTransaction.assert_not_called()
        self.assertTrue(d.rejected)

    def test_ok_commits_the_preview_transaction_once(self):
        d = self.dialog()
        d.apply_preview(StockDefinition())
        d.accept()
        d.document.commitTransaction.assert_called_once()
        d.owner.sync_scene.assert_called_once()
        self.assertTrue(d.accepted)

    def test_partial_preview_failure_aborts_and_can_be_retried(self):
        d = self.dialog()
        d.owner.apply_stock.side_effect = ValueError('failed to recompute')
        with self.assertRaises(ValueError):
            d.apply_preview(StockDefinition())
        self.assertFalse(d.edit_started)
        d.document.abortTransaction.assert_called_once()
        d.owner.apply_stock.side_effect = None
        d.apply_preview(StockDefinition())
        self.assertTrue(d.edit_started)

    def test_unrelated_transaction_is_never_joined(self):
        d = self.dialog()
        d.document.HasPendingTransaction = True
        with self.assertRaises(ValueError):
            d.apply_preview(StockDefinition())
        d.document.openTransaction.assert_not_called()
        d.document.abortTransaction.assert_not_called()
        d.owner.apply_stock.assert_not_called()

    def test_undo_disabled_confirmation_uses_normal_stock_backend(self):
        d = self.dialog()
        d.live = False
        spec = StockDefinition()
        d.apply_preview(spec)
        d.owner.apply_stock.assert_called_once_with(spec)
        self.assertFalse(d.edit_started)
