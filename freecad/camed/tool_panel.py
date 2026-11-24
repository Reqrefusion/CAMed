"""Small job tool list; native CAM forms own tool geometry and settings."""

from .i18n import tr
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets
from .tool_backend import controllers, fingerprint
from .program_backend import initial_tool

_dialog = None


class ToolsDialog(QtWidgets.QDialog):
    def __init__(self, owner):
        super().__init__(Gui.getMainWindow())
        self.owner = owner
        self.setWindowTitle(tr('CAMed · Job tools'))
        self.resize(760, 480)
        self.setMinimumSize(620, 390)
        self.entries = []
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(
            self.button(
                tr('New toolbit…'),
                ":/icons/CAM_ToolLibrary.svg",
                self.create,
                tr('Create a toolbit using the FreeCAD tool editor'),
            )
        )
        self.remove_button = self.button(
            tr('Remove tool'),
            ":/icons/edit-delete.svg",
            self.remove,
            tr('Remove the selected tool from this job'),
        )
        top.addWidget(self.remove_button)
        top.addStretch()
        self.search = QtWidgets.QLineEdit(self)
        self.search.setPlaceholderText(tr('Find tool…'))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_rows)
        top.addWidget(self.search)
        layout.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["T No", tr('Name'), tr('Type'), tr('Diameter'), tr('Cutting length'), tr('Status')]
        )
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setColumnHidden(2, True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)
        header.resizeSection(5, self.table.fontMetrics().horizontalAdvance(tr('Initial')) + 20)
        self.table.currentCellChanged.connect(lambda *args: self.selection_changed())
        self.table.cellDoubleClicked.connect(self.edit_cell)
        layout.addWidget(self.table, 1)

        actions = QtWidgets.QHBoxLayout()
        self.selection_buttons = []
        for text, icon, callback, tooltip in (
            (
                tr('Edit toolbit'),
                ":/icons/CAM_ToolController.svg",
                self.edit_geometry,
                tr('Edit toolbit dimensions'),
            ),
            (
                tr('Feeds and speeds'),
                ":/icons/CAM_FeedsSpeeds.svg",
                self.edit,
                tr("Open the toolbit's feeds and speeds settings"),
            ),
            (
                tr('Edit tool number'),
                ":/icons/CAM_ToolController.svg",
                self.edit_number,
                tr("Change the selected tool's T number"),
            ),
            (
                tr('Set initial tool'),
                ":/icons/Std_Apply.svg",
                self.use_default,
                tr('Select the tool used before the first M6 command'),
            ),
        ):
            button = self.button(text, icon, callback, tooltip)
            self.selection_buttons.append(button)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.info = QtWidgets.QLabel(self)
        self.info.setTextFormat(QtCore.Qt.PlainText)
        self.info.setWordWrap(True)
        self.info.setMinimumHeight(20)
        layout.addWidget(self.info)
        footer = QtWidgets.QDialogButtonBox(self)
        footer.addButton(tr('Close'), QtWidgets.QDialogButtonBox.RejectRole)
        footer.rejected.connect(self.close)
        layout.addWidget(footer)
        self.pending_update = False
        self.signature = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def button(self, text, icon, callback, tooltip):
        image = QtGui.QIcon(icon)
        if image.isNull():
            standard = (
                QtWidgets.QStyle.SP_DirOpenIcon if tr('Library') in text else QtWidgets.QStyle.SP_FileIcon
            )
            image = self.style().standardIcon(standard)
        button = QtWidgets.QPushButton(image, text, self)
        button.setToolTip(tooltip)
        button.setAutoDefault(False)
        button.clicked.connect(callback)
        return button

    def filter_rows(self, *args):
        query = self.search.text().strip().casefold()
        for row in range(self.table.rowCount()):
            text = " ".join(self.table.item(row, col).text() for col in range(5))
            self.table.setRowHidden(row, query not in text.casefold())
        if self.selected() is None:
            for row in range(self.table.rowCount()):
                if not self.table.isRowHidden(row):
                    self.table.selectRow(row)
                    break
        self.selection_changed()

    def selection_changed(self):
        tc = self.selected()
        self.remove_button.setEnabled(tc is not None)
        for button in self.selection_buttons:
            button.setEnabled(tc is not None)
        if tc is None:
            message = (
                tr('No tools yet. Select New toolbit to add one to this job.')
                if not self.entries
                else tr('Select a tool.')
            )
            if self.entries and self.search.text().strip():
                message = tr('No matching tools.')
            self.info.setText(message)
            return
        number = int(tc.ToolNumber)
        count = sum(int(item.ToolNumber) == number for item in self.entries)
        if count > 1:
            self.info.setText(
                tr('T{number} is assigned more than once. Give each tool a unique number.').format(
                    number=number
                )
            )
        else:
            self.info.setText(tr('G-code usage: T{number} M6').format(number=number))

    def refresh(self, force=False):
        if getattr(self.owner, "shutting_down", False) or not self.owner.is_current():
            self.close()
            return
        if Gui.Control.activeDialog() or (getattr(self.owner, "resource_depth", 0) and not force):
            return
        initial = initial_tool(self.owner.operation)
        signature = (fingerprint(self.owner.job), getattr(initial, "Name", None))
        if signature == self.signature:
            if self.pending_update and not Gui.Control.activeDialog():
                self.pending_update = False
                self.owner.apply_text()
            return
        previous = self.selected()
        changed = self.signature is not None
        self.signature = signature
        self.entries = sorted(controllers(self.owner.job), key=lambda tc: (int(tc.ToolNumber), tc.Name))
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.entries))
            for row, tc in enumerate(self.entries):
                tool = tc.Tool
                values = [
                    f"T{tc.ToolNumber}",
                    tc.Label,
                    str(getattr(tool, "ToolType", "—")),
                    str(getattr(tool, "Diameter", "—")),
                    str(getattr(tool, "CuttingEdgeHeight", "—")),
                    tr('Initial') if tc is initial else "",
                ]
                for col, value in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(value)
                    item.setToolTip(
                        value + tr('\nDouble-click to edit the T number') if col == 0 else value
                    )
                    if col == 0:
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    self.table.setItem(row, col, item)
            if self.entries:
                row = self.entries.index(previous) if previous in self.entries else 0
                self.table.selectRow(row)
        finally:
            self.table.blockSignals(False)
        self.filter_rows()
        if changed:
            self.pending_update = True

    def selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entries) and not self.table.isRowHidden(row):
            return self.entries[row]
        return None

    def ready(self):
        if getattr(self.owner, "shutting_down", False):
            return False
        if self.owner.simulation:
            self.owner.simulation.pause()
        if Gui.Control.activeDialog():
            QtWidgets.QMessageBox.information(
                self, "CAMed", tr('Finish or cancel the open CAM task first.')
            )
            return False
        return self.owner.is_current()

    def create(self):
        if not self.ready():
            return
        try:
            from .tool_creation import create_from_library

            tc = create_from_library(self.owner, self)
            self.refresh(force=True)
            if tc is not None:
                self.search.clear()
                if tc in self.entries:
                    self.table.selectRow(self.entries.index(tc))
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, tr('Could not add tool'), str(error))
        finally:
            if not self.owner.shutting_down and self.owner.is_current():
                self.show()
                self.raise_()

    def remove(self):
        tc = self.selected()
        if tc is None or not self.ready():
            return
        try:
            from .tool_controller import remove_from_job

            remove_from_job(self.owner, tc)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, tr('Could not remove tool'), str(error))
        finally:
            if not self.owner.shutting_down and self.owner.is_current():
                self.refresh(force=True)

    def edit_geometry(self):
        tc = self.selected()
        if tc is None or not self.ready():
            return
        try:
            from .tool_parameters import edit_parameters

            edit_parameters(self.owner, tc, self)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, tr('Could not edit toolbit'), str(error))
        finally:
            if not self.owner.shutting_down and self.owner.is_current():
                self.refresh(force=True)
                self.show()
                self.raise_()

    def edit_cell(self, row, column):
        if column == 0:
            self.edit_number()
        else:
            self.edit_geometry()

    def edit(self):
        tc = self.selected()
        if tc is None or not self.ready():
            return
        try:
            from .tool_parameters import edit_parameters

            edit_parameters(self.owner, tc, self, feeds_speeds=True)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, tr('Could not open feeds and speeds'), str(error))
        finally:
            if not self.owner.shutting_down and self.owner.is_current():
                self.refresh(force=True)
                self.show()
                self.raise_()

    def edit_number(self):
        tc = self.selected()
        if tc is None or not self.ready():
            return
        try:
            from .tool_controller import edit_number

            edit_number(self.owner, tc, self)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, tr('Could not edit tool number'), str(error))
        finally:
            if not self.owner.shutting_down and self.owner.is_current():
                self.refresh(force=True)
                self.show()
                self.raise_()

    def use_default(self):
        from .tool_controller import set_initial_tool

        tc = self.selected()
        if tc is None or not self.ready():
            return
        try:
            set_initial_tool(self.owner, tc)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, tr('Set initial tool'), str(error))
        finally:
            if not self.owner.shutting_down and self.owner.is_current():
                self.refresh(force=True)

    def closeEvent(self, event):
        self.timer.stop()
        if (
            self.pending_update
            and not getattr(self.owner, "shutting_down", False)
            and self.owner.is_current()
            and not Gui.Control.activeDialog()
        ):
            self.owner.apply_text()
        super().closeEvent(event)


def show_tools():
    global _dialog
    from .panel import show_panel

    owner = show_panel()
    if owner is None:
        return
    if _dialog is not None:
        _dialog.close()
        _dialog.deleteLater()
    _dialog = ToolsDialog(owner)
    _dialog.show()
