"""Disclosure/readout behavior with stub Qt widgets; no layout rendering."""

import importlib
import sys
import types
import unittest
from unittest.mock import patch
from freecad.camed.validation import preview
from freecad.camed.info_state import readout


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, fn):
        self.callbacks.append(fn)

    def emit(self, *args):
        for fn in list(self.callbacks):
            fn(*args)


class Widget:
    StyledPanel = 1
    NoFrame = 0

    def __init__(self, *args):
        self._text = args[0] if args and isinstance(args[0], str) else ''
        self.visible = True
        self.enabled = True
        self.checked = False
        self.toggled = Signal()

    def setFrameShape(self, value):
        self.frame = value

    def setText(self, value):
        self._text = value

    def text(self):
        return self._text

    def setTextFormat(self, value):
        self.text_format = value

    def setTextInteractionFlags(self, value):
        self.interaction = value

    def setWordWrap(self, value):
        self.wrap = value

    def setToolTip(self, value):
        self.tooltip = value

    def setCheckable(self, value):
        self.checkable = value

    def setChecked(self, value):
        if self.checked != value:
            self.checked = value
            self.toggled.emit(value)

    def setArrowType(self, value):
        self.arrow = value

    def setToolButtonStyle(self, value):
        self.style = value

    def setVisible(self, value):
        self.visible = bool(value)

    def hide(self):
        self.visible = False

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setWidgetResizable(self, value):
        self.resizable = value

    def setHorizontalScrollBarPolicy(self, value):
        pass

    def setMinimumHeight(self, value):
        self.minimum_height = value

    def setMaximumHeight(self, value):
        self.maximum_height = value

    def setWidget(self, value):
        self.widget = value

    def setFixedHeight(self, value):
        self.fixed_height = value

    def setSizePolicy(self, horizontal, vertical):
        self.size_policy = (horizontal, vertical)

    def setAlignment(self, value):
        self.alignment = value


class Layout:
    def __init__(self, *args):
        self.children = []

    def setContentsMargins(self, *args):
        pass

    def setSpacing(self, value):
        pass

    def addWidget(self, widget, *args):
        self.children.append(widget)

    def addLayout(self, layout):
        self.children.append(layout)


class InfoPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qt = types.ModuleType('PySide')
        cls.constants = types.SimpleNamespace(
            RightArrow=1,
            DownArrow=2,
            ToolButtonTextBesideIcon=3,
            PlainText=4,
            TextSelectableByMouse=5,
            ScrollBarAlwaysOff=6,
            AlignLeft=8,
            AlignTop=16,
        )
        qt.QtCore = types.SimpleNamespace(Qt=cls.constants)
        qt.QtWidgets = types.SimpleNamespace(
            QFrame=Widget,
            QVBoxLayout=Layout,
            QHBoxLayout=Layout,
            QLabel=Widget,
            QToolButton=Widget,
            QScrollArea=Widget,
            QSizePolicy=types.SimpleNamespace(Expanding=1, Maximum=2, Fixed=3, Preferred=4),
        )
        with patch.dict(sys.modules, {'PySide': qt}):
            sys.modules.pop('freecad.camed.info_panel', None)
            cls.module = importlib.import_module('freecad.camed.info_panel')

    def setUp(self):
        self.panel = self.module.InfoPanel()

    def test_details_are_collapsed_and_user_can_toggle_them(self):
        p = self.panel
        self.assertFalse(p.details.visible)
        p.setText('Canlı 3B yol güncel; details.')
        p.details_button.setChecked(True)
        self.assertTrue(p.details.visible)
        self.assertEqual(p.details_button.arrow, self.constants.DownArrow)
        p.setText('G-code kaydedildi: part.nc')
        self.assertTrue(p.details.visible)  # Do not override the user's disclosure choice
        self.assertEqual(p.text(), 'G-code kaydedildi: part.nc')
        p.details_button.setChecked(False)
        self.assertFalse(p.details.visible)

    def test_error_reason_is_visible_while_long_details_stay_collapsed(self):
        p = self.panel
        p.setText('Satır 3: Eksik sözcük.\nÖnceki hareketler gösteriliyor.')
        self.assertEqual(p.details_button.text(), 'Error details')
        self.assertEqual(p.alert.text(), 'Satır 3: Eksik sözcük.')
        self.assertTrue(p.alert.visible)
        self.assertFalse(p.details.visible)
        self.assertEqual(p.details_label.text(), p.text())

    def test_current_code_error_survives_save_and_clears_after_valid_preview(self):
        p = self.panel
        p.set_block(readout(preview('G0 Z5\nG1 X'), 2))
        p.setText('G-code kaydedildi: part.nc')
        self.assertEqual(p.details_button.text(), 'Error details')
        self.assertIn('kaydedildi', p.details_label.text())
        p.setText('Canlı 3B yol güncel; details.')
        p.set_block(readout(preview('G0 Z5\nG1 X10 F800'), 2))
        self.assertFalse(p.alert.visible)
        self.assertEqual(p.details_button.text(), 'Details')
        self.assertEqual(p.coordinates.text(), 'X10 · Y0 · Z5 mm')

    def test_native_progress_does_not_replace_selected_source_coordinates(self):
        p = self.panel
        p.set_block(readout(preview('G1 X120 Y35 Z-5 F800 S6000 M3', {6: 1}, 6), 1))
        p.set_progress(0.42)
        self.assertEqual(p.heading.text(), 'Line 1')
        self.assertEqual(p.coordinates.text(), 'X120 · Y35 · Z-5 mm')
        self.assertEqual(p.cutting.text(), 'F800 · S6000 · M3')
        self.assertEqual(p.progress.text(), '%42')
        p.set_progress(label='GL hazırlanıyor')
        self.assertEqual(p.progress.text(), 'hazırlanıyor')
        self.assertEqual(p.coordinates.text(), 'X120 · Y35 · Z-5 mm')

    def test_diagnostics_are_plain_text_and_copyable(self):
        p = self.panel
        p.setText('GL görünümü açılamadı: <part&tool>')
        self.assertEqual(p.alert.text_format, self.constants.PlainText)
        self.assertEqual(p.details_label.text_format, self.constants.PlainText)
        self.assertEqual(p.details_label.interaction, self.constants.TextSelectableByMouse)
        self.assertIn('<part&tool>', p.alert.text())

    def test_expanding_diagnostics_do_not_take_spare_dock_height(self):
        p = self.panel
        p.details_button.setChecked(True)
        self.assertEqual(p.size_policy, (1, 2))
        self.assertEqual(p.details.fixed_height, 96)
        self.assertEqual(p.details.size_policy, (1, 3))
        self.assertEqual(p.heading.size_policy, (4, 2))
        self.assertEqual(p.details_label.alignment, self.constants.AlignLeft | self.constants.AlignTop)

    def test_normal_readout_is_one_row_until_details_are_requested(self):
        p = self.panel
        p.set_block(readout(preview('G1 X10 F100'), 1))
        p.set_position(1, 8)
        self.assertEqual(p.heading.text(), 'Line 1 · Column 8')
        self.assertFalse(p.coordinates.visible)
        self.assertFalse(p.cutting.visible)
        self.assertFalse(p.details.visible)
        p.details_button.setChecked(True)
        self.assertTrue(p.coordinates.visible)
        self.assertTrue(p.cutting.visible)
