"""Side-panel search and NC numbering around FreeCAD's CodeEditor."""

from .i18n import tr
from PySide import QtCore, QtGui, QtWidgets
from .nc_text import renumber, remove_numbers


def shortcut(parent, key, callback):
    shortcut_type = getattr(QtGui, 'QShortcut', None) or QtWidgets.QShortcut
    item = shortcut_type(QtGui.QKeySequence(key), parent)
    item.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
    item.activated.connect(callback)
    return item


class FindPane(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__(owner.program_area)
        self.tab = owner.search_tab
        self.editor = owner.editor
        self.scope_cursor = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(4)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(3)
        self.query = QtWidgets.QLineEdit(self)
        self.query.setPlaceholderText(tr('Find…'))
        self.query.setClearButtonEnabled(True)
        layout.addWidget(self.query)
        for icon, text, callback in (
            (QtWidgets.QStyle.SP_ArrowUp, tr('Previous match (Shift+Enter)'), lambda: self.find(True)),
            (QtWidgets.QStyle.SP_ArrowDown, tr('Next match (Enter)'), self.find),
            (QtWidgets.QStyle.SP_TitleBarCloseButton, tr('Close search (Escape)'), self.dismiss),
        ):
            button = QtWidgets.QToolButton(self)
            button.setAutoRaise(True)
            button.setIcon(self.style().standardIcon(icon))
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.clicked.connect(callback)
            if icon == QtWidgets.QStyle.SP_TitleBarCloseButton:
                row.addStretch()
            row.addWidget(button)
        layout.addLayout(row)
        self.case = QtWidgets.QCheckBox(tr('Match case'), self)
        layout.addWidget(self.case)
        self.scope = QtWidgets.QCheckBox(tr('Selection only'), self)
        self.scope.setEnabled(False)
        self.scope.hide()
        layout.addWidget(self.scope)
        layout.addSpacing(6)
        self.replacement = QtWidgets.QLineEdit(self)
        self.query.installEventFilter(self)
        self.replacement.installEventFilter(self)
        self.replacement.setPlaceholderText(tr('Replace with…'))
        layout.addWidget(self.replacement)
        row = QtWidgets.QHBoxLayout()
        self.replace_one_button = QtWidgets.QPushButton(tr('Replace'), self)
        self.replace_one_button.setAutoDefault(False)
        self.replace_one_button.clicked.connect(self.replace_one)
        self.replace_all_button = QtWidgets.QPushButton(tr('Replace all'), self)
        self.replace_all_button.setAutoDefault(False)
        self.replace_all_button.setToolTip(tr('Replace all matches'))
        self.replace_all_button.clicked.connect(self.replace_all)
        row.addWidget(self.replace_one_button)
        row.addWidget(self.replace_all_button)
        layout.addLayout(row)
        self.message = QtWidgets.QLabel(self)
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        layout.addStretch()
        self.replacement.returnPressed.connect(self.replace_one)
        self.query.returnPressed.connect(self.find)
        self.query.textChanged.connect(self.query_changed)
        self.shortcuts = [
            shortcut(self, 'Escape', self.dismiss),
            shortcut(self, 'Shift+Return', lambda: self.find(True)),
        ]
        self.query_changed()

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched in (self.query, self.replacement) and kind in (
            QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress
        ):
            close = event.key() == QtCore.Qt.Key_Escape and event.modifiers() == QtCore.Qt.NoModifier
            replace = event.key() == QtCore.Qt.Key_H and event.modifiers() == QtCore.Qt.ControlModifier
            if close or replace:
                # Handle search shortcuts before QLineEdit and FreeCAD consume them.
                event.accept()
                if kind == QtCore.QEvent.KeyPress:
                    if close:
                        self.dismiss()
                    elif self.query.text():
                        self.replacement.setFocus()
                        self.replacement.selectAll()
                return True
        return super().eventFilter(watched, event)

    def query_changed(self):
        self.message.clear()
        self.message.hide()
        enabled = bool(self.query.text())
        self.replace_one_button.setEnabled(enabled)
        self.replace_all_button.setEnabled(enabled)

    def capture_selection(self):
        if not self.isVisible():
            self.scope_cursor = None
            self.scope.setChecked(False)
            self.scope.setEnabled(False)
            self.scope.hide()
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            return
        text = cursor.selectedText()
        if '\u2029' in text or self.scope_cursor is None or not self.scope.isChecked():
            self.scope_cursor = QtGui.QTextCursor(cursor)
            self.scope.setEnabled(True)
            self.scope.show()
            self.scope.setChecked('\u2029' in text)
            if '\u2029' not in text:
                self.query.setText(text)

    def bounds(self):
        if self.scope.isChecked() and self.scope_cursor is not None:
            return self.scope_cursor.selectionStart(), self.scope_cursor.selectionEnd()
        return 0, self.editor.document().characterCount() - 1

    def within(self, cursor):
        start, end = self.bounds()
        return not cursor.isNull() and start <= cursor.selectionStart() < cursor.selectionEnd() <= end

    def flags(self, backwards=False):
        flags = QtGui.QTextDocument.FindFlags()
        if self.case.isChecked():
            flags |= QtGui.QTextDocument.FindCaseSensitively
        if backwards:
            flags |= QtGui.QTextDocument.FindBackward
        return flags

    def showEvent(self, event):
        super().showEvent(event)
        self.tab.setChecked(True)

    def hideEvent(self, event):
        self.tab.setChecked(False)
        super().hideEvent(event)

    def dismiss(self):
        self.hide()
        self.editor.setFocus()

    def find(self, backwards=False):
        query = self.query.text()
        if not query:
            return False
        document = self.editor.document()
        start, end = self.bounds()
        current = self.editor.textCursor()
        if current.selectionStart() < start or current.selectionEnd() > end:
            current.setPosition(end if backwards else start)
        cursor = document.find(query, current, self.flags(backwards))
        if not self.within(cursor):
            boundary = QtGui.QTextCursor(document)
            boundary.setPosition(end if backwards else start)
            cursor = document.find(query, boundary, self.flags(backwards))
        found = self.within(cursor)
        if found:
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()
        self.message.setText('' if found else tr('No matches found.'))
        self.message.setVisible(not found)
        return found

    def replace_one(self):
        selected = self.editor.textCursor().selectedText()
        query = self.query.text()
        equal = selected == query if self.case.isChecked() else selected.casefold() == query.casefold()
        if query and equal and self.within(self.editor.textCursor()):
            self.editor.textCursor().insertText(self.replacement.text())
        self.find()

    def replace_all(self):
        query = self.query.text()
        if not query:
            return
        document = self.editor.document()
        edit = QtGui.QTextCursor(document)
        edit.beginEditBlock()
        cursor = QtGui.QTextCursor(document)
        cursor.setPosition(self.bounds()[0])
        count = 0
        while True:
            cursor = document.find(query, cursor, self.flags())
            if not self.within(cursor):
                break
            cursor.insertText(self.replacement.text())
            count += 1
        edit.endEditBlock()
        self.message.setText(tr('Replaced {count} matches.').format(count=count))
        self.message.show()


def open_search(owner, replace=False):
    from .inspection_tool import show_side_pane

    pane = getattr(owner, 'find_bar', None)
    if pane is None:
        pane = owner.find_bar = FindPane(owner)
    pane.capture_selection()
    show_side_pane(owner, pane)
    field = pane.replacement if replace and pane.query.text() else pane.query
    field.setFocus()
    field.selectAll()


def install(owner):
    from .editor_actions import ACTION_SPECS

    owner.editor_actions = {}
    action_type = getattr(QtGui, 'QAction', None) or QtWidgets.QAction

    def action(name, callback):
        label, key, icon, tooltip = ACTION_SPECS[name]
        item = action_type(label, owner)
        item.setIcon(QtGui.QIcon(icon))
        item.setToolTip(tooltip)
        item.triggered.connect(callback)
        if key:
            item.setShortcut(QtGui.QKeySequence(key))
            item.setShortcutContext(QtCore.Qt.WidgetWithChildrenShortcut)
            owner.addAction(item)
        owner.editor_actions[name] = item
        return item

    owner.search_shortcuts = {
        'Find': shortcut(owner, 'Ctrl+F', lambda: open_search(owner)),
        'Replace': shortcut(owner, 'Ctrl+H', lambda: open_search(owner, replace=True)),
    }

    def numbers(transform):
        cursor = owner.editor.textCursor()
        if cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            cursor.setPosition(end)
            if cursor.atBlockStart() and end > start:
                cursor.movePosition(QtGui.QTextCursor.PreviousCharacter)
            cursor.movePosition(QtGui.QTextCursor.EndOfBlock)
            end = cursor.position()
            cursor.setPosition(start)
            cursor.movePosition(QtGui.QTextCursor.StartOfBlock)
            cursor.setPosition(end, QtGui.QTextCursor.KeepAnchor)
        else:
            cursor.select(QtGui.QTextCursor.Document)
        text = cursor.selectedText().replace('\u2029', '\n')
        replacement = transform(text)
        if replacement == text:
            return
        cursor.beginEditBlock()
        cursor.insertText(replacement)
        cursor.endEditBlock()

    from .inspection_tool import toggle_sections

    action('Sections', lambda: toggle_sections(owner)).setCheckable(True)
    action('Renumber', lambda: numbers(renumber))
    action('RemoveNumbers', lambda: numbers(remove_numbers))
