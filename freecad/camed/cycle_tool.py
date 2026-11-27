"""Editor-owned canned-cycle form, backed by the native CAM drill generator."""

from .i18n import tr
from PySide import QtCore, QtGui, QtWidgets
from .cycle_builder import CYCLE_DECIMALS, CycleSpec, build_block, insertion_context
from .tool_backend import MAX_TOOL_NUMBER


class CycleDialog(QtWidgets.QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.context = None
        try:
            self.read_context()
        except ValueError:
            # Keep the form available so the user can move to a valid line.
            pass
        self.block = None
        self.setWindowTitle(tr('CAMed · Drilling cycle'))
        self.resize(720, 470)
        self.setMinimumWidth(660)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        body, initial = self._build_cycle_settings(layout)
        body.addWidget(self._build_hole_table(), 1)
        layout.addLayout(body, 1)
        self.add_hole(initial[0], initial[1])
        self._build_preview_and_footer(layout)
        self.kind.currentIndexChanged.connect(self.type_changed)
        self.return_mode.currentIndexChanged.connect(self.schedule)
        owner.editor.cursorPositionChanged.connect(self.schedule)
        owner.editor.textChanged.connect(self.schedule)
        self.type_changed()
        self.refresh()

    def _build_cycle_settings(self, layout):
        cycle_row = QtWidgets.QHBoxLayout()
        cycle_row.addWidget(QtWidgets.QLabel(tr('Cycle'), self))
        self.kind = QtWidgets.QComboBox(self)
        for label, value in (
            (tr('G81 · Drilling'), 81),
            (tr('G83 · Peck drilling'), 83),
            (tr('G73 · Chip breaking'), 73),
            (tr('G82 · Drilling with dwell'), 82),
        ):
            self.kind.addItem(label, value)
        cycle_row.addWidget(self.kind, 1)
        layout.addLayout(cycle_row)
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)
        settings = QtWidgets.QVBoxLayout()
        settings.setSpacing(12)
        heights = QtWidgets.QGroupBox(tr('Depths and motion'), self)
        height_layout = QtWidgets.QVBoxLayout(heights)
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        top = 0.0
        try:
            top = float(self.owner.job.Stock.Shape.BoundBox.ZMax)
        except (AttributeError, RuntimeError, ReferenceError):
            pass
        initial = self.context.position if self.context is not None else (0.0, 0.0, 0.0)
        self.clearance = self.field(max(top + 5, initial[2]), ' mm')
        self.depth = self.field(top - 5, ' mm')
        self.retract = self.field(top + 2, ' mm')
        feed = self.context.feed if self.context is not None else None
        self.feed = self.field(feed or 120, tr(' mm/min'), positive=True)
        self.peck = self.field(2, ' mm', positive=True)
        self.dwell = self.field(0.5, tr(' s'), positive=True)
        self.clearance.setToolTip(tr('Z position used at the start and end of the cycle.'))
        self.retract.setToolTip(tr('Z position where rapid approach ends and drilling feed begins (R).'))
        self.depth.setToolTip(tr('Z coordinate of the hole bottom, measured from the work origin.'))
        form.addRow(tr('Clearance height'), self.clearance)
        form.addRow(tr('Retract plane (R)'), self.retract)
        form.addRow(tr('Hole bottom (Z)'), self.depth)
        self.return_mode = QtWidgets.QComboBox(self)
        self.return_mode.addItem(tr('G98 · Return to clearance Z'), 98)
        self.return_mode.addItem(tr('G99 · Return to R plane'), 99)
        form.addRow(tr('Return between holes'), self.return_mode)
        height_layout.addLayout(form)
        note = QtWidgets.QLabel(tr('Z values are relative to the work origin.'), heights)
        note.setWordWrap(True)
        height_layout.addWidget(note)
        settings.addWidget(heights)
        cutting = QtWidgets.QGroupBox(tr('Cutting parameters'), self)
        self.cutting_form = QtWidgets.QFormLayout(cutting)
        self.cutting_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.tool_number = QtWidgets.QSpinBox(self)
        self.tool_number.setRange(-1, MAX_TOOL_NUMBER)
        self.tool_number.setSpecialValueText(tr('Keep current tool'))
        self.tool_number.setValue(-1)
        self.tool_number.setKeyboardTracking(False)
        self.tool_number.valueChanged.connect(self.schedule)
        self.cutting_form.addRow(tr('Tool number (T):'), self.tool_number)
        self.cutting_form.addRow(tr('Feed rate (F)'), self.feed)
        self.peck_label = QtWidgets.QLabel(tr('Peck depth (Q)'), cutting)
        self.dwell_label = QtWidgets.QLabel(tr('Bottom dwell (P)'), cutting)
        self.cutting_form.addRow(self.peck_label, self.peck)
        self.cutting_form.addRow(self.dwell_label, self.dwell)
        settings.addWidget(cutting)
        settings.addStretch()
        body.addLayout(settings, 1)
        return body, initial

    def _build_hole_table(self):
        positions_group = QtWidgets.QGroupBox(tr('Hole positions'), self)
        positions = QtWidgets.QVBoxLayout(positions_group)
        positions.addWidget(QtWidgets.QLabel(tr('X / Y · Relative to the work origin'), positions_group))
        self.holes = QtWidgets.QTableWidget(0, 2, self)
        self.holes.setHorizontalHeaderLabels(['X (mm)', 'Y (mm)'])
        self.holes.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.holes.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.holes.setMinimumWidth(230)
        positions.addWidget(self.holes, 1)
        row = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton(tr('Add hole'), self)
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(lambda: self.add_hole())
        self.remove_button = QtWidgets.QPushButton(tr('Remove selected'), self)
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(self.remove_hole)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        positions.addLayout(row)
        return positions_group

    def _build_preview_and_footer(self, layout):
        self.preview_toggle = QtWidgets.QToolButton(self)
        self.preview_toggle.setText(tr('Code preview'))
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.setAutoRaise(True)
        self.preview_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.preview_toggle.setArrowType(QtCore.Qt.RightArrow)
        self.preview_toggle.toggled.connect(self.toggle_preview)
        layout.addWidget(self.preview_toggle)
        self.code = QtWidgets.QPlainTextEdit(self)
        self.code.setReadOnly(True)
        self.code.setFont(self.owner.editor.font())
        self.code.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.code.setFixedHeight(140)
        self.code.hide()
        layout.addWidget(self.code)
        self.message = QtWidgets.QLabel('', self)
        self.message.setWordWrap(True)
        self.message.setTextFormat(QtCore.Qt.PlainText)
        self.message.hide()
        layout.addWidget(self.message)
        footer = QtWidgets.QHBoxLayout()
        self.location = QtWidgets.QLabel('', self)
        self.location.setToolTip(tr('Click a line in the editor to change the insertion point.'))
        footer.addWidget(self.location, 1)
        buttons = QtWidgets.QDialogButtonBox(self)
        self.insert_button = buttons.addButton(tr('Insert code'), QtWidgets.QDialogButtonBox.AcceptRole)
        self.insert_button.setDefault(True)
        buttons.addButton(tr('Cancel'), QtWidgets.QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    def read_context(self):
        if not self.owner.is_current():
            raise ValueError(tr('The target program is no longer active.'))
        source = self.owner.editor.toPlainText()
        self.cursor = QtGui.QTextCursor(self.owner.editor.textCursor())
        self.cursor.setPosition(self.cursor.selectionStart())
        self.cursor.movePosition(QtGui.QTextCursor.StartOfBlock)
        # Qt cursor offsets use UTF-16; derive the Python prefix from line count.
        position = sum(len(line) + 1 for line in source.split('\n')[: self.cursor.blockNumber()])
        _, self.context = insertion_context(source, position)

    def field(self, value, suffix, positive=False):
        field = QtWidgets.QDoubleSpinBox(self)
        field.setDecimals(CYCLE_DECIMALS)
        field.setRange(10 ** -CYCLE_DECIMALS if positive else -1000000, 1000000)
        field.setSuffix(suffix)
        field.setKeyboardTracking(False)
        field.setValue(value)
        field.valueChanged.connect(self.schedule)
        return field

    def schedule(self, *_):
        self.timer.start()

    def toggle_preview(self, visible):
        self.code.setVisible(visible)
        self.preview_toggle.setArrowType(QtCore.Qt.DownArrow if visible else QtCore.Qt.RightArrow)
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())

    def type_changed(self, *_):
        cycle = self.kind.currentData()
        self.cutting_form.setRowVisible(self.peck, cycle in (73, 83))
        self.cutting_form.setRowVisible(self.dwell, cycle == 82)
        self.schedule()

    def add_hole(self, x=None, y=None):
        row = self.holes.rowCount()
        if row >= 1000:
            return
        if x is None:
            x = self.holes.cellWidget(row - 1, 0).value() if row else 0
            y = self.holes.cellWidget(row - 1, 1).value() if row else 0
        self.holes.insertRow(row)
        self.holes.setCellWidget(row, 0, self.field(x, ''))
        self.holes.setCellWidget(row, 1, self.field(y, ''))
        self.holes.setCurrentCell(row, 0)
        self.remove_button.setEnabled(self.holes.rowCount() > 1)
        self.add_button.setEnabled(self.holes.rowCount() < 1000)
        self.schedule()

    def remove_hole(self):
        if self.holes.rowCount() <= 1:
            return
        row = self.holes.currentRow()
        self.holes.removeRow(row if row >= 0 else self.holes.rowCount() - 1)
        self.remove_button.setEnabled(self.holes.rowCount() > 1)
        self.add_button.setEnabled(self.holes.rowCount() < 1000)
        self.schedule()

    def specification(self):
        fields = [self.depth, self.retract, self.clearance, self.feed, self.peck, self.dwell]
        points = []
        for row in range(self.holes.rowCount()):
            x, y = (self.holes.cellWidget(row, col) for col in (0, 1))
            fields.extend((x, y))
            x.interpretText()
            y.interpretText()
            points.append((x.value(), y.value()))
        for field in fields:
            field.interpretText()
        self.tool_number.interpretText()
        number = self.tool_number.value()
        return CycleSpec(
            cycle=self.kind.currentData(),
            holes=tuple(points),
            depth=self.depth.value(),
            retract=self.retract.value(),
            clearance=self.clearance.value(),
            feed=self.feed.value(),
            peck=self.peck.value(),
            dwell=self.dwell.value(),
            return_mode=self.return_mode.currentData(),
            tool_number=number if number >= 0 else None,
        )

    def refresh(self):
        self.timer.stop()
        try:
            self.read_context()
            self.location.setText(
                tr('Insert before line {value1}').format(value1=self.cursor.blockNumber() + 1)
            )
            self.block = build_block(self.specification(), self.context)
            self.code.setPlainText(self.block)
            self.message.setText('')
            self.message.hide()
            self.insert_button.setEnabled(True)
        except Exception as error:
            self.block = None
            self.code.clear()
            self.location.clear()
            self.message.setText(str(error))
            self.message.show()
            self.insert_button.setEnabled(False)

    def accept(self):
        self.refresh()
        if self.block is None:
            return
        self.timer.stop()
        self.cursor.beginEditBlock()
        try:
            self.cursor.insertText(self.block)
        finally:
            self.cursor.endEditBlock()
        self.owner.editor.setTextCursor(self.cursor)
        self.owner.editor.ensureCursorVisible()
        super().accept()

    def done(self, result):
        self.timer.stop()
        self.owner.editor.cursorPositionChanged.disconnect(self.schedule)
        self.owner.editor.textChanged.disconnect(self.schedule)
        if getattr(self.owner, 'cycle_dialog', None) is self:
            self.owner.cycle_dialog = None
        super().done(result)
        if not getattr(self.owner, 'shutting_down', False) and self.owner.is_current():
            self.owner.editor.setFocus()


def show_cycle_tool():
    from .panel import show_panel

    owner = show_panel()
    if owner is None:
        return
    dialog = getattr(owner, 'cycle_dialog', None)
    if dialog is None:
        dialog = CycleDialog(owner)
        owner.cycle_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
