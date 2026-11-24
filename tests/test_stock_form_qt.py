"""Real stock dialog controls with an isolated document adapter."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from freecad.camed.stock_definition import StockDefinition


@unittest.skipUnless(os.environ.get('CAMEDITOR_QT_TESTS') == '1', 'Requires Qt')
class StockFormQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def dialog(self, spec, *, live=True, existing=True):
        from PySide import QtWidgets
        from freecad.camed import stock_panel, stock_tool

        stock = SimpleNamespace(Visibility=True)
        job = SimpleNamespace(Stock=stock if existing else None)
        owner = SimpleNamespace(
            document=Mock(UndoMode=int(live), HasPendingTransaction=False),
            job=job, is_current=lambda: True, sync_scene=Mock(),
        )

        def apply(definition, **kwargs):
            job.Stock = stock
            return stock

        owner.apply_stock = Mock(side_effect=apply)
        with (
            patch.object(stock_tool.Gui, 'getMainWindow', return_value=None),
            patch.object(stock_panel, 'load_definition', return_value=spec),
            patch.object(stock_panel, 'stock_rotation', return_value=SimpleNamespace(isIdentity=lambda: True)),
        ):
            dialog = stock_tool.StockDialog(owner)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        box = dialog.findChild(QtWidgets.QDialogButtonBox)
        ok = next(b for b in box.buttons() if box.buttonRole(b) == QtWidgets.QDialogButtonBox.AcceptRole)
        return dialog, dialog.stock_form, ok, owner

    def test_entry_method_switch_and_accept_preserve_existing_stock(self):
        for length, x, origin in ((1.0001, 0, 'top_center'), (40, 999990, 'top_corner')):
            with self.subTest(length=length):
                spec = StockDefinition(length=length, x=x, origin=origin)
                dialog, form, ok, owner = self.dialog(spec)
                form.bounds_button.click()
                self.assertEqual(form.fields['box_bounds']['xmax'].value(), spec.bounds().xmax)
                self.assertFalse(form.live_timer.isActive())
                form.dimensions_button.click()
                self.assertEqual(form.definition(), spec)
                ok.click()
                self.assertTrue(dialog.result())
                owner.apply_stock.assert_not_called()
                owner.document.openTransaction.assert_not_called()

    def test_editing_one_field_preserves_precise_bounds_and_applies_once(self):
        spec = StockDefinition(length=1.0001, x=0, origin='top_center')
        dialog, form, ok, owner = self.dialog(spec)
        form.bounds_button.click()
        form.fields['box_bounds']['zmin'].setValue(-12.5)
        form.preview()
        ok.click()
        owner.apply_stock.assert_called_once()
        saved = owner.apply_stock.call_args.args[0]
        self.assertEqual(saved.bounds().size[0], spec.length)
        self.assertEqual(saved.zmin, -12.5)
        owner.document.commitTransaction.assert_called_once()

    def test_invalid_numeric_entries_disable_visible_ok_and_pending_preview(self):
        dialog, form, ok, owner = self.dialog(StockDefinition())
        field = form.fields['box_dimensions']['length']
        for invalid in (-1, 0.0001):
            field.setValue(invalid)
            self.assertFalse(ok.isEnabled())
            self.assertFalse(form.live_timer.isActive())
            ok.click()
            owner.apply_stock.assert_not_called()
        field.setValue(31)
        self.assertTrue(ok.isEnabled())
        ok.click()
        self.assertEqual(owner.apply_stock.call_args.args[0].length, 31)

    def test_incomplete_keyboard_input_disables_ok_before_leaving_the_field(self):
        from PySide import QtCore, QtTest

        dialog, form, ok, owner = self.dialog(StockDefinition())
        field = form.fields['box_dimensions']['length']
        field.setFocus()
        field.selectAll()
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Minus)
        self.assertFalse(ok.isEnabled())
        self.assertFalse(form.live_timer.isActive())
        owner.apply_stock.assert_not_called()
        field.selectAll()
        QtTest.QTest.keyClicks(field, '45')
        self.assertTrue(ok.isEnabled())
        ok.click()
        self.assertEqual(owner.apply_stock.call_args.args[0].length, 45)

    def test_default_stock_is_created_on_confirmation(self):
        from PySide import QtWidgets

        dialog, form, ok, owner = self.dialog(StockDefinition(), existing=False)
        form.bounds_button.click()
        owner.apply_stock.assert_not_called()
        self.assertFalse(form.live_timer.isActive())
        self.assertFalse(form.findChildren(QtWidgets.QCheckBox))
        self.assertIsNone(owner.job.Stock)
        ok.click()
        owner.apply_stock.assert_called_once()
        self.assertTrue(owner.job.Stock.Visibility)
