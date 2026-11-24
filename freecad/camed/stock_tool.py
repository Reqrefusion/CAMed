"""Stock setup as a standalone toolbar tool; reuse the existing stock form."""

from .i18n import tr
import FreeCADGui as Gui
from PySide import QtWidgets
from .stock_panel import StockPanel
from .program_backend import require_document_idle


class StockDialog(QtWidgets.QDialog):
    def __init__(self, owner):
        super().__init__(Gui.getMainWindow())
        self.owner = owner
        self.document = owner.document
        self.live = bool(self.document.UndoMode)
        self.edit_started = False
        self.setWindowTitle("CAMed · " + tr("Stock"))
        self.setMinimumWidth(460)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        self.stock_form = StockPanel(
            owner.job,
            self.apply_preview,
            self,
            tool_mode=True,
            live=self.live,
        )
        layout.addWidget(self.stock_form)
        buttons = QtWidgets.QDialogButtonBox(self)
        ok = buttons.addButton(tr('OK'), QtWidgets.QDialogButtonBox.AcceptRole)
        ok.setDefault(True)
        ok.setEnabled(self.stock_form.apply_button.isEnabled())
        self.stock_form.validity_changed.connect(ok.setEnabled)
        buttons.addButton(tr('Cancel'), QtWidgets.QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_preview(self, definition):
        if not self.live:
            require_document_idle(self.document)
            return self.owner.apply_stock(definition)
        if not self.edit_started:
            require_document_idle(self.document)
            self.document.openTransaction(tr('CAMed stock settings'))
            self.edit_started = True
        try:
            return self.owner.apply_stock(definition, transaction=False)
        except Exception:
            self.rollback()
            raise

    def rollback(self):
        if not self.edit_started:
            return
        try:
            self.document.abortTransaction()
        except ReferenceError:
            # Closing the document disposes its transaction as well.
            self.edit_started = False
            return
        self.edit_started = False
        self.document.recompute()
        if self.owner.is_current():
            self.owner.sync_scene()

    def accept(self):
        if self.stock_form.apply():
            if self.edit_started:
                self.document.commitTransaction()
                self.edit_started = False
                self.owner.sync_scene()
            super().accept()

    def reject(self):
        self.stock_form.live_timer.stop()
        try:
            if self.edit_started:
                self.rollback()
        except Exception as error:
            QtWidgets.QMessageBox.warning(
                self, "CAMed", tr('Could not restore the previous stock: {error}').format(error=error)
            )
            return
        super().reject()


def show_stock_tool():
    from .panel import show_panel

    owner = show_panel(focus=False)
    if owner is None:
        return
    dialog = StockDialog(owner)
    execute = getattr(dialog, "exec", None) or dialog.exec_
    return execute()
