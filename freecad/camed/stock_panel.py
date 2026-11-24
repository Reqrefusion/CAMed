"""Stock geometry and placement controls backed by FreeCAD stock objects."""

from dataclasses import replace
from decimal import Decimal

from .i18n import tr
from PySide import QtCore, QtWidgets
from .stock_definition import StockDefinition
from .stock_backend import load_definition, stock_rotation, validate_dimensions


class StockPanel(QtWidgets.QWidget):
    validity_changed = QtCore.Signal(bool)

    def __init__(self, job, apply_callback, parent=None, tool_mode=False, live=False):
        super().__init__(parent)
        self.job = job
        self.apply_callback = apply_callback
        self.fields = {}
        self.live = live
        self.geometry_dirty = False
        self.live_timer = QtCore.QTimer(self)
        self.live_timer.setSingleShot(True)
        self.live_timer.setInterval(200)
        self.live_timer.timeout.connect(self.preview)
        self.current_kind = None
        self.loading = True
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.shape_tabs = QtWidgets.QTabBar(self)
        self.shape_tabs.setAccessibleName(tr('Stock shape'))
        self.shape_tabs.addTab(tr('Box'))
        self.shape_tabs.addTab(tr('Cylinder'))
        self.shape_tabs.setExpanding(True)
        self.shape_tabs.setDrawBase(False)
        self.shape_tabs.setStyleSheet("""
            QTabBar::tab {
                padding: 7px 16px;
                border-bottom: 2px solid palette(mid);
                color: palette(text);
            }
            QTabBar::tab:selected {
                border-bottom-color: palette(highlight);
                font-weight: bold;
            }
        """)
        layout.addWidget(self.shape_tabs)

        self.box_methods = QtWidgets.QWidget(self)
        methods = QtWidgets.QHBoxLayout(self.box_methods)
        methods.setContentsMargins(0, 0, 0, 0)
        self.dimensions_button = QtWidgets.QRadioButton(tr('Dimensions'), self.box_methods)
        self.bounds_button = QtWidgets.QRadioButton(tr('Min / Max'), self.box_methods)
        self.dimensions_button.setChecked(True)
        methods.addWidget(self.dimensions_button)
        methods.addWidget(self.bounds_button)
        methods.addStretch()
        layout.addWidget(self.box_methods)

        self.pages = QtWidgets.QStackedWidget(self)
        layout.addWidget(self.pages)
        top_center = (tr('Top center'), 'top_center')
        bottom_center = (tr('Bottom center'), 'bottom_center')
        self.box_origin = self.origin_combo((
            (tr('Top corner'), 'top_corner'), top_center,
            (tr('Bottom corner'), 'bottom_corner'), bottom_center,
        ))
        self.cylinder_origin = self.origin_combo((top_center, bottom_center))
        self.geometry_page(
            'box_dimensions', self.box_origin,
            (('length', tr('Length (X)')), ('width', tr('Width (Y)')), ('height', tr('Height (Z)'))),
        )
        self.bounds_page()
        self.geometry_page(
            'cylinder', self.cylinder_origin, (('diameter', tr('Diameter')), ('height', tr('Height (Z)'))),
        )

        if not stock_rotation(job.Stock).isIdentity():
            layout.addWidget(QtWidgets.QLabel(tr('Coordinates and Z levels use the rotated stock axes.'), self))
        self.summary = QtWidgets.QLabel(self)
        self.summary.setWordWrap(True)
        self.summary.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.summary.setBackgroundRole(self.palette().ColorRole.AlternateBase)
        self.summary.setAutoFillBackground(True)
        self.summary.setMargin(9)
        layout.addWidget(self.summary)
        self.apply_button = QtWidgets.QPushButton(tr('Apply stock'), self)
        self.apply_button.clicked.connect(self.apply)
        self.apply_button.setVisible(not tool_mode)
        layout.addWidget(self.apply_button)
        instruction = (
            tr('Changes are previewed immediately. Cancel restores the previous stock. Units: mm.')
            if live
            else (
                tr('Confirm to create or update stock. Units: mm.')
                if tool_mode
                else tr('Apply to update stock. Units: mm.')
            )
        )
        self.setToolTip(instruction)
        self.message = QtWidgets.QLabel("", self)
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        layout.addStretch()
        self.shape_tabs.currentChanged.connect(self.type_changed)
        self.dimensions_button.clicked.connect(self.type_changed)
        self.bounds_button.clicked.connect(self.type_changed)
        self.load(load_definition(job))
        self.loading = False
        self.refresh_summary()

    def origin_combo(self, entries):
        combo = QtWidgets.QComboBox(self)
        for label, data in entries:
            combo.addItem(label, data)
        combo.currentIndexChanged.connect(lambda: self.edit_value('origin', combo.currentData()))
        return combo

    def field(self, kind, key, label):
        field = QtWidgets.QDoubleSpinBox(self)
        field.setDecimals(4)
        field.setRange(-1000000, 1000000)
        field.setSuffix(" mm")
        field.setKeyboardTracking(True)
        field.setAccessibleName(label)
        field.valueChanged.connect(lambda value: self.edit_value(key, value))
        field.lineEdit().textChanged.connect(self.refresh_summary)
        self.fields[kind][key] = field
        return field

    def field_row(self, grid, kind, items, row=0):
        for column, (key, title) in enumerate(items):
            label = QtWidgets.QLabel(title)
            field = self.field(kind, key, title)
            label.setBuddy(field)
            grid.addWidget(label, row, column)
            grid.addWidget(field, row + 1, column)
            grid.setColumnStretch(column, 1)

    def geometry_page(self, kind, origin, dimensions):
        self.fields[kind] = {}
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        sizes = QtWidgets.QGroupBox(tr('Dimensions') if kind == 'cylinder' else '')
        self.field_row(QtWidgets.QGridLayout(sizes), kind, dimensions)
        layout.addWidget(sizes)
        position = QtWidgets.QGroupBox(tr('Position'))
        grid = QtWidgets.QGridLayout(position)
        label = QtWidgets.QLabel(tr('Reference point'))
        label.setBuddy(origin)
        grid.addWidget(label, 0, 0)
        grid.addWidget(origin, 0, 1, 1, 2)
        self.field_row(grid, kind, (('x', 'X'), ('y', 'Y'), ('z', 'Z')), row=1)
        layout.addWidget(position)
        layout.addStretch()
        self.pages.addWidget(page)

    def bounds_page(self):
        self.fields['box_bounds'] = {}
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        group = QtWidgets.QGroupBox(tr('Stock bounds'))
        grid = QtWidgets.QGridLayout(group)
        for column, limit in enumerate((tr('Min'), tr('Max')), 1):
            grid.addWidget(QtWidgets.QLabel(limit), 0, column)
            grid.setColumnStretch(column, 1)
        for row, axis in enumerate('XYZ', 1):
            grid.addWidget(QtWidgets.QLabel(axis), row, 0)
            for column, limit in enumerate(('min', 'max'), 1):
                field = self.field('box_bounds', axis.lower() + limit, f'{axis} {limit}')
                grid.addWidget(field, row, column)
        layout.addWidget(group)
        layout.addStretch()
        self.pages.addWidget(page)

    def select_page(self, kind):
        cylinder = kind == 'cylinder'
        blocker = QtCore.QSignalBlocker(self.shape_tabs)
        self.shape_tabs.setCurrentIndex(1 if cylinder else 0)
        blocker.unblock()
        self.box_methods.setVisible(not cylinder)
        if not cylinder:
            (self.bounds_button if kind == 'box_bounds' else self.dimensions_button).setChecked(True)
        self.pages.setCurrentIndex(('box_dimensions', 'box_bounds', 'cylinder').index(kind))
        self.current_kind = kind

    def load(self, spec):
        """Start editing the exact model values; widgets are only a view of them."""
        self.model = spec
        self.geometry_dirty = False
        self.display_definition(spec)

    def display_definition(self, spec):
        self.loading = True
        try:
            self.draft = spec
            self.select_page(spec.kind)
            if spec.kind != 'box_bounds':
                origin = self.cylinder_origin if spec.kind == 'cylinder' else self.box_origin
                origin.setCurrentIndex(origin.findData(spec.origin))
            for key, field in self.fields[spec.kind].items():
                value = getattr(spec, key)
                precision = max(4, -Decimal(str(value)).as_tuple().exponent)
                field.setDecimals(precision)
                field.setRange(min(-1000000, value), max(1000000, value))
                field.setValue(value)
        finally:
            self.loading = False

    def definition(self):
        return self.draft

    def edit_value(self, key, value):
        if self.loading:
            return
        self.draft = replace(self.draft, **{key: value})
        self.model = self.draft
        self.geometry_dirty = True
        self.refresh_summary()

    def type_changed(self, *_):
        if self.loading:
            return
        if self.shape_tabs.currentIndex() == 1:
            target = 'cylinder'
        else:
            target = 'box_bounds' if self.bounds_button.isChecked() else 'box_dimensions'
        previous = self.current_kind or target
        if previous != target:
            try:
                origin = (
                    self.box_origin.currentData()
                    if target == "box_dimensions"
                    else self.cylinder_origin.currentData()
                    if target == "cylinder"
                    else None
                )
                self.model.bounds()
                if self.model.kind == target and (origin is None or self.model.origin == origin):
                    converted = self.model
                else:
                    converted = self.model.converted(target, origin)
                self.display_definition(converted)
                if (previous == 'cylinder') != (target == 'cylinder'):
                    self.model = converted
                    self.geometry_dirty = True
            except ValueError as error:
                self.select_page(previous)
                self.set_message(str(error))
                self.live_timer.stop()
                return
        self.current_kind = target
        self.refresh_summary()

    def set_message(self, text):
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def checked_bounds(self):
        if not all(field.hasAcceptableInput() for field in self.fields[self.current_kind].values()):
            raise ValueError(tr('Complete the stock measurement.'))
        return validate_dimensions(self.model)

    def refresh_summary(self, *_):
        if self.loading:
            return
        try:
            definition = self.definition()
            b = self.checked_bounds()
            faces = tr('Top Z: {top} mm   ·   Bottom Z: {bottom} mm').format(
                top=f'{b.zmax:.15g}', bottom=f'{b.zmin:.15g}'
            )
            if definition.kind == 'cylinder':
                size = f'Ø{definition.diameter:g} × {definition.height:g} mm'
            else:
                size = f'{b.size[0]:g} × {b.size[1]:g} × {b.size[2]:g} mm'
            self.summary.setText(f'{size}\n{faces}')
            self.summary.setToolTip(
                f"X: {b.xmin:g} … {b.xmax:g}\nY: {b.ymin:g} … {b.ymax:g}\nZ: {b.zmin:g} … {b.zmax:g}"
            )
            self.set_message("")
            self.apply_button.setEnabled(True)
            self.validity_changed.emit(True)
            if self.live and self.geometry_dirty:
                self.live_timer.start()
        except ValueError as error:
            self.summary.setToolTip("")
            self.summary.setText(str(error))
            self.apply_button.setEnabled(False)
            self.validity_changed.emit(False)
            self.live_timer.stop()

    def preview(self):
        if self.live and self.geometry_dirty:
            self.apply()

    def apply(self):
        self.live_timer.stop()
        try:
            self.checked_bounds()
            if self.geometry_dirty or self.job.Stock is None:
                self.apply_callback(self.model)
                self.geometry_dirty = False
            self.set_message("")
            return True
        except Exception as error:
            self.set_message(tr('Could not apply stock: {error}').format(error=error))
            return False
