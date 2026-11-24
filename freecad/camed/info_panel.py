"""Small native Qt readout with expandable full diagnostics."""

from .i18n import tr
from PySide import QtCore, QtWidgets
from .info_state import diagnostic


class InfoPanel(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._notices = ()
        self._error = None
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        # A QScrollArea defaults to Expanding; do not let its parent consume
        # spare dock height and spread the readout rows across that space.
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 2)
        layout.setSpacing(3)
        heading_row = QtWidgets.QHBoxLayout()
        self.heading = self.label(tr('Line 1 · Column 1'))
        heading_row.addWidget(self.heading, 1)
        self.details_button = QtWidgets.QToolButton(self)
        self.details_button.setText(tr('Details'))
        self.details_button.setCheckable(True)
        self.details_button.setArrowType(QtCore.Qt.RightArrow)
        self.details_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.details_button.setToolTip(tr('Coordinates, tool information and warnings'))
        self.details_button.toggled.connect(self.set_expanded)
        self.progress = self.label(tr('Ready'))
        heading_row.addWidget(self.progress)
        heading_row.addWidget(self.details_button)
        layout.addLayout(heading_row)
        self.coordinates = self.label("X— · Y— · Z— mm")
        layout.addWidget(self.coordinates)
        cutting_row = QtWidgets.QHBoxLayout()
        self.cutting = self.label("F— · S—")
        cutting_row.addWidget(self.cutting, 1)

        layout.addLayout(cutting_row)
        self.coordinates.hide()
        self.cutting.hide()
        self.alert = self.label("")
        self.alert.hide()
        layout.addWidget(self.alert)
        self.details = QtWidgets.QScrollArea(self)
        self.details.setWidgetResizable(True)
        self.details.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.details.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.details.setFixedHeight(96)
        self.details.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.details_label = self.label("")
        self.details.setWidget(self.details_label)
        self.details.hide()
        layout.addWidget(self.details)

    def label(self, text):
        label = QtWidgets.QLabel(text, self)
        label.setTextFormat(QtCore.Qt.PlainText)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        label.setWordWrap(True)
        label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        return label

    def set_expanded(self, expanded):
        self.details.setVisible(bool(expanded))
        self.coordinates.setVisible(bool(expanded))
        self.cutting.setVisible(bool(expanded))
        self.details_button.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)

    def text(self):
        return self._text

    def setText(self, text):
        # Existing file/GL adapters retain their status.setText/text interface.
        self._text = str(text)
        self.feedback()

    def feedback(self):
        badge, short_error, details = diagnostic(self._text, self._error)
        if short_error:
            caption = tr('Error details')
        elif badge == tr('Waiting'):
            caption = tr('Waiting')
            short_error = self._text.splitlines()[0] if self._text else ""
        elif self._notices or badge.startswith(tr('Notes ({count})').split('{count}')[0]):
            caption = tr('Warnings')
        else:
            caption = tr('Details')
        self.details_button.setText(caption)
        self.details_label.setText("\n".join(filter(None, (details, *self._notices))))
        self.alert.setText(short_error)
        self.alert.setVisible(bool(short_error))
        self.details_button.setEnabled(True)

    def set_block(self, block, notices=()):
        self._notices = tuple(notices)
        self.heading.setText(block.heading.split(" · ")[0])
        self.coordinates.setText(block.coordinates)
        self.cutting.setText(block.cutting)
        self.setToolTip(block.tooltip)
        self._error = block.error
        self.feedback()

    def set_position(self, line, column):
        self.heading.setText(tr('Line {line} · Column {column}').format(line=line, column=column))

    def set_progress(self, fraction=None, label=None):
        if label:
            caption = label.replace(tr('Simulation closed'), tr('Ready')).replace("GL ", "")
        else:
            caption = f"%{fraction * 100:.0f}" if fraction is not None else tr('Ready')
        self.progress.setText(caption)
        self.progress.setToolTip(tr('Simulation progress'))
