"""Section navigation and hover help around FreeCAD's existing CodeEditor."""

from .i18n import tr
from bisect import bisect_right
from html import escape
from PySide import QtCore, QtGui, QtWidgets
from .program_inspection import sections, token_help


def search_key(text):
    return text.casefold().replace('\u0307', '').replace('ı', 'i')


def goto_line(owner, number):
    block = owner.editor.document().findBlockByNumber(number - 1)
    if not block.isValid():
        return
    owner.editor.setTextCursor(QtGui.QTextCursor(block))
    owner.editor.centerCursor()
    owner.editor.setFocus()


class HoverHelp(QtCore.QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        owner.editor.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() != QtCore.QEvent.ToolTip:
            return False
        owner = self.owner
        cursor = owner.editor.cursorForPosition(event.pos())
        text = cursor.block().text()
        # Qt positions count UTF-16 units. Measure the selected prefix in Python characters.
        cursor.setPosition(cursor.block().position(), QtGui.QTextCursor.KeepAnchor)
        help_text = token_help(text, len(cursor.selectedText()))
        error = getattr(owner, 'preview_error', None)
        if (
            error is not None
            and not owner.timer.isActive()
            and not getattr(owner, 'pending_code', False)
            and not getattr(owner, 'resource_depth', 0)
            and error.line == cursor.blockNumber() + 1
        ):
            help_text = (help_text + '\n' if help_text else '') + str(error)
        if help_text:
            QtWidgets.QToolTip.showText(event.globalPos(), escape(help_text).replace('\n', '<br>'), watched)
        else:
            QtWidgets.QToolTip.hideText()
        return True


class SideTab(QtWidgets.QToolButton):
    """A narrow vertical toggle painted with the current native Qt button style."""

    def __init__(self, parent, label, name, tip):
        super().__init__(parent)
        self.setText(label)
        self.setAccessibleName(name)
        self.setToolTip(tip)
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self):
        return super().sizeHint().transposed()

    def paintEvent(self, event):
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        option.rect = QtCore.QRect(0, 0, self.height(), self.width())
        painter = QtWidgets.QStylePainter(self)
        painter.translate(0, self.height())
        painter.rotate(-90)
        painter.drawComplexControl(QtWidgets.QStyle.CC_ToolButton, option)


class SectionsPane(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__(owner.program_area)
        self.owner = owner
        self.source = None
        self.entries = []
        self.starts = []
        self.rows = {}
        self.setMinimumHeight(120)
        self.setMinimumWidth(150)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(5)
        self.filter = QtWidgets.QLineEdit(self)
        self.filter.setPlaceholderText(tr('Find section…'))
        self.filter.setClearButtonEnabled(True)
        self.filter.setMaximumWidth(220)
        layout.addWidget(self.filter)
        self.items = QtWidgets.QTreeWidget(self)
        self.items.setColumnCount(2)
        self.items.setHeaderHidden(True)
        self.items.setRootIsDecorated(False)
        self.items.setUniformRowHeights(True)
        self.items.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.items.header().setStretchLastSection(False)
        self.items.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.items.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(self.items, 1)
        self.message = QtWidgets.QLabel(self)
        self.message.setAlignment(QtCore.Qt.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setToolTip(
            tr('Standalone comments in parentheses or after ; appear as section headings.')
        )
        layout.addWidget(self.message)
        self.items.itemClicked.connect(self.navigate)
        self.items.itemActivated.connect(self.navigate)
        self.filter.textChanged.connect(self.refresh)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        owner.editor.textChanged.connect(self.changed)
        owner.editor.cursorPositionChanged.connect(self.sync_cursor)

    def changed(self):
        self.source = None
        self.items.setEnabled(False)
        self.timer.stop()
        if self.isVisible():
            self.timer.start()

    def refresh(self, *args):
        self.timer.stop()
        if not self.isVisible():
            return
        source = self.owner.editor.toPlainText()
        if source != self.source:
            self.source = source
            self.entries = sections(source)
            self.starts = [number for number, _ in self.entries]
        self.items.clear()
        self.rows = {}
        query = search_key(self.filter.text())
        for number, title in self.entries:
            if query in search_key(title):
                item = QtWidgets.QTreeWidgetItem(self.items, [title, str(number)])
                item.setData(0, QtCore.Qt.UserRole, number)
                item.setToolTip(0, tr('Line {number} · {title}').format(number=number, title=title))
                item.setToolTip(1, tr('Line {number}').format(number=number))
                item.setTextAlignment(1, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                item.setForeground(1, self.palette().brush(QtGui.QPalette.PlaceholderText))
                self.rows[number] = item
        self.items.setEnabled(bool(self.rows))
        self.message.setText(tr('No matching sections.') if query else tr('No section headings found.'))
        self.message.setVisible(not self.rows)
        self.sync_cursor()

    def sync_cursor(self):
        if not self.isVisible() or self.source is None:
            return
        line = self.owner.editor.textCursor().blockNumber() + 1
        index = bisect_right(self.starts, line) - 1
        number = self.starts[index] if index >= 0 else None
        item = self.rows.get(number)
        if self.items.currentItem() is item:
            return
        self.items.setCurrentItem(item)
        if item is not None:
            self.items.scrollToItem(item)

    def navigate(self, item=None, *args):
        if self.owner.editor.toPlainText() != self.source:
            self.refresh()
            return
        item = item or self.items.currentItem()
        if item is not None:
            goto_line(self.owner, item.data(0, QtCore.Qt.UserRole))

    def showEvent(self, event):
        super().showEvent(event)
        self.owner.editor_actions['Sections'].setChecked(True)
        self.owner.sections_tab.setChecked(True)
        self.refresh()

    def hideEvent(self, event):
        self.timer.stop()
        self.owner.editor_actions['Sections'].setChecked(False)
        self.owner.sections_tab.setChecked(False)
        super().hideEvent(event)


def show_side_pane(owner, pane):
    splitter = owner.program_splitter
    if splitter.indexOf(pane) >= 0 and not pane.isHidden():
        return
    width = pane.width() if splitter.indexOf(pane) >= 0 else 190
    for i in range(splitter.count() - 1):
        other = splitter.widget(i)
        if not other.isHidden():
            width = other.width()
            if other is not pane:
                other.hide()
    if splitter.indexOf(pane) < 0:
        splitter.insertWidget(0, pane)
        splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(splitter.indexOf(owner.code_area), 1)
    pane.show()
    splitter.setSizes(
        [width if splitter.widget(i) is pane else 0 for i in range(splitter.count() - 1)]
        + [max(240, splitter.width() - width)]
    )


def toggle_sections(owner):
    pane = getattr(owner, 'sections_pane', None)
    if pane is not None and not pane.isHidden():
        pane.hide()
        return
    if pane is None:
        pane = owner.sections_pane = SectionsPane(owner)
    show_side_pane(owner, pane)


def install(owner):
    from .editor_tools import open_search

    tabs = QtWidgets.QVBoxLayout()
    tabs.setContentsMargins(0, 0, 0, 0)
    tabs.setSpacing(2)
    owner.sections_tab = SideTab(
        owner.program_area,
        tr('Sections'),
        tr('Program sections'),
        tr('Show or hide program sections (Ctrl+Alt+O)'),
    )
    owner.sections_tab.clicked.connect(owner.editor_actions['Sections'].trigger)
    owner.search_tab = SideTab(
        owner.program_area,
        tr('Find and replace'),
        tr('Find and replace'),
        tr('Find (Ctrl+F) / Replace (Ctrl+H)'),
    )
    owner.search_tab.clicked.connect(
        lambda checked: open_search(owner) if checked else owner.find_bar.dismiss()
    )
    tabs.addWidget(owner.sections_tab)
    tabs.addWidget(owner.search_tab)
    tabs.addStretch()
    owner.program_row.insertLayout(0, tabs)
    owner.hover_help = HoverHelp(owner)
    from .path_navigation import PathSelection

    owner.path_selection = PathSelection(owner)
    owner.destroyed.connect(owner.path_selection.detach)
    if owner.enabled:
        owner.path_selection.attach()
    result = getattr(owner, 'preview_result', None)
    if result is not None and owner.owns_operation():
        owner.path_selection.refresh(owner.editor.toPlainText(), result)


def detach(owner):
    observer = getattr(owner, 'path_selection', None)
    if observer is not None:
        observer.detach()
    for name in ('sections_pane', 'find_bar'):
        pane = getattr(owner, name, None)
        if pane is not None:
            pane.hide()
