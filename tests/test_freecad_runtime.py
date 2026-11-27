"""Opt-in tests using real FreeCAD documents and undo transactions.
Run with the FreeCAD distribution's python.exe and tests/run_freecad_checks.py.
"""

import os
from pathlib import Path
import tempfile
import unittest
from freecad.camed.program_backend import persist_source, apply_preview
from freecad.camed.validation import preview


class FeatureProbe:
    def __init__(self):
        self.errors = []

    def execute(self, obj):
        pass


@unittest.skipUnless(
    os.environ.get('CAMEDITOR_FREECAD_TESTS') == '1', 'Run tests/run_freecad_checks.py with FreeCAD Python'
)
class FreeCADRuntimeTests(unittest.TestCase):
    def setUp(self):
        import FreeCAD as App

        self.app = App
        self.doc = App.newDocument('CAMedRuntimeTest')
        self.names = [self.doc.Name]
        self.doc.UndoMode = 1
        self.op = self.doc.addObject('App::FeaturePython', 'Program')
        self.op.addProperty('App::PropertyString', 'LiveEditorSource')
        self.op.addProperty('App::PropertyStringList', 'Gcode')
        self.op.Proxy = FeatureProbe()
        self.op.LiveEditorSource = 'G1 X1 F100'
        self.op.Gcode = ['G1 X1 F100']
        self.doc.recompute()
        self.doc.clearUndos()

    def tearDown(self):
        for name in self.names:
            if name in self.app.listDocuments():
                self.app.closeDocument(name)

    def test_native_abort_preserves_source_and_old_path_through_fcstd_roundtrip(self):
        source = 'G1 X25 F100\nG0 Z'
        persist_source(self.op, source)
        self.op.Proxy.errors = ['forced recompute failure']
        with self.assertRaises(ValueError):
            apply_preview(self.op, None, preview(source))
        self.assertEqual(self.op.LiveEditorSource, source)
        self.assertEqual(list(self.op.Gcode), ['G1 X1 F100'])
        self.assertFalse(self.doc.HasPendingTransaction)
        with tempfile.TemporaryDirectory() as folder:
            filename = str(Path(folder) / 'source.FCStd')
            name = self.doc.Name
            self.doc.saveAs(filename)
            self.app.closeDocument(name)
            restored = self.app.openDocument(filename)
            self.names.append(restored.Name)
            self.assertEqual(restored.getObject('Program').LiveEditorSource, source)
            self.assertEqual(list(restored.getObject('Program').Gcode), ['G1 X1 F100'])

    def test_success_updates_native_path_without_rewriting_source(self):
        source = 'G91 G1 X2 F100\nX3'
        persist_source(self.op, source)
        result = preview(source)
        apply_preview(self.op, None, result)
        self.assertEqual(self.op.LiveEditorSource, source)
        self.assertEqual(list(self.op.Gcode), ['G1 X2 F100', 'G1 X5 F100'])
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertFalse(persist_source(self.op, source))

    def test_foreign_transaction_is_never_committed_or_joined(self):
        self.doc.openTransaction('Unrelated tool edit')
        self.op.Gcode = ['G1 X2 F100']
        self.assertTrue(self.doc.HasPendingTransaction)
        with self.assertRaises(ValueError):
            persist_source(self.op, 'G1 X50 F100')
        with self.assertRaises(ValueError):
            apply_preview(self.op, None, preview('G1 X50 F100'))
        self.assertTrue(self.doc.HasPendingTransaction)
        self.assertEqual(self.op.LiveEditorSource, 'G1 X1 F100')
        self.doc.abortTransaction()

    def test_actual_native_drill_generator_and_expander_stay_connected(self):
        from freecad.camed.cycle_builder import CycleSpec, build_block

        for cycle in (73, 81, 82, 83):
            with self.subTest(cycle=cycle):
                source = build_block(CycleSpec(cycle=cycle, holes=((10, 10), (25, 10))))
                result = preview(source)
                self.assertIsNone(result.error, str(result.error))
                self.assertEqual(result.states[-1].position, (25, 10, 5))
                self.assertEqual(len(result.lines), len(result.states))

    def test_native_drill_words_use_three_decimal_places(self):
        from freecad.camed.cycle_builder import CycleSpec, build_block
        from freecad.camed.gcode_syntax import parse_words
        from freecad.camed.validation import preview

        spec = CycleSpec(
            cycle=82, holes=((12.12345, -8.98765),), depth=-5.34567,
            retract=2.11111, clearance=5.43219, feed=120.12367, dwell=0.56789,
        )
        block = build_block(spec)
        self.assertEqual(block.splitlines().count('G0 Z5.432'), 2)
        line = next(line for line in block.splitlines() if line.startswith('G82 '))
        self.assertNotRegex(line, r"\.\d{4,}")
        values, _, _ = parse_words(line, 1)
        self.assertEqual(values, {'X': 12.123, 'Y': -8.988, 'Z': -5.346, 'R': 2.111, 'F': 120.124, 'P': 0.568})
        self.assertIsNone(preview(block).error)

    def test_native_path_command_selection_maps_expanded_cycles_and_tool_sections(self):
        import Path as NativePath
        from freecad.camed.tool_backend import section_records
        from freecad.camed.path_navigation import command_sources

        result = preview('G0 Z5\nT2 M6\nG83 X10 Z-4 R1 Q2 F100\nG80\nT1 M6\nG1 X20')
        self.assertIsNone(result.error)
        chunks = section_records(result)
        self.assertEqual([n for n, _, _ in chunks], [None, 2, 1])
        for _, lines, sources in chunks:
            op = self.doc.addObject('Path::Feature', 'NativeSelectionPath')
            op.Path = NativePath.Path(
                [NativePath.Command('(native preamble)'), NativePath.Command('M6')]
                + [NativePath.Command(line) for line in lines]
                + [NativePath.Command('(native end)')]
            )
            mapping = command_sources(op, lines, sources)
            expected = {
                i + 3: src
                for i, (line, src) in enumerate(zip(lines, sources))
                if src is not None and line.startswith(('G0 ', 'G1 ', 'G2 ', 'G3 '))
            }
            self.assertEqual(mapping, expected)
            self.assertNotIn(None, mapping.values())

    def test_native_selection_rejects_unknown_or_ambiguous_command_layouts(self):
        import Path as NativePath
        from freecad.camed.path_navigation import command_sources

        op = self.doc.addObject('Path::Feature', 'AmbiguousPath')
        op.Path = NativePath.Path('G1 X10\nG1 X10')
        self.assertEqual(command_sources(op, ['G1 X10'], [1]), {})
        self.assertEqual(command_sources(op, ['G1 X20'], [1]), {})
        self.assertEqual(command_sources(op, [], []), {})

    def test_native_box_property_edit_overrides_saved_stock_form(self):
        import json
        import types
        from Path.Main import Stock
        from freecad.camed.stock_definition import StockDefinition
        from freecad.camed.stock_backend import load_definition

        stock = Stock.CreateBox(
            None,
            extent=self.app.Vector(40, 30, 10),
            placement=self.app.Placement(self.app.Vector(-20, -15, -10), self.app.Rotation()),
        )
        self.doc.recompute()
        cached = StockDefinition(origin="top_center", x=0, y=0, z=0)
        job = types.SimpleNamespace(Stock=stock, CAMEditorStockDefinition=json.dumps(cached.to_dict()))
        stock.Length = 80
        self.doc.recompute()
        loaded = load_definition(job)
        self.assertEqual(loaded.length, 80)
        self.assertEqual(loaded.origin, "top_center")
        self.assertEqual((loaded.bounds().xmin, loaded.bounds().xmax), (-20, 60))

    def test_native_cylinder_property_edit_preserves_current_center_and_base(self):
        import json
        import types
        from Path.Main import Stock
        from freecad.camed.stock_definition import StockDefinition
        from freecad.camed.stock_backend import load_definition

        stock = Stock.CreateCylinder(
            None,
            radius=10,
            height=10,
            placement=self.app.Placement(self.app.Vector(3, 4, 5), self.app.Rotation()),
            axis="Z",
        )
        self.doc.recompute()
        cached = StockDefinition(
            kind="cylinder", diameter=20, height=10, origin="bottom_center", x=3, y=4, z=5
        )
        job = types.SimpleNamespace(Stock=stock, CAMEditorStockDefinition=json.dumps(cached.to_dict()))
        stock.Radius = 15
        stock.Height = 12
        self.doc.recompute()
        loaded = load_definition(job)
        self.assertEqual((loaded.diameter, loaded.height), (30, 12))
        self.assertEqual((loaded.x, loaded.y, loaded.z), (3, 4, 5))

    def test_native_rotated_box_keeps_placement_after_dimension_edit(self):
        from dataclasses import replace
        from types import SimpleNamespace
        from Path.Main import Stock
        from freecad.camed.stock_backend import apply_stock, load_definition

        rotation = self.app.Rotation(self.app.Vector(0, 0, 1), 45)
        placement = self.app.Placement(self.app.Vector(2, 3, 4), rotation)
        stock = Stock.CreateBox(None, extent=self.app.Vector(40, 20, 10), placement=placement)
        self.doc.recompute()
        job = SimpleNamespace(Stock=stock, Document=self.doc, CAMEditorStockDefinition='')
        spec = load_definition(job)
        self.assertEqual((spec.length, spec.width, spec.height), (40, 20, 10))
        apply_stock(job, replace(spec, length=50))
        self.assertEqual(stock.Length.Value, 50)
        self.assertTrue(stock.Placement.isSame(placement, 1e-8))

    def test_stock_preview_abort_restores_native_rotated_box(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from Path.Main import Stock

        with patch.dict(sys.modules, {'FreeCADGui': Mock()}):
            from freecad.camed.stock_tool import StockDialog
        placement = self.app.Placement(
            self.app.Vector(2, 3, 4), self.app.Rotation(self.app.Vector(0, 0, 1), 45)
        )
        stock = Stock.CreateBox(None, extent=self.app.Vector(40, 20, 10), placement=placement)
        self.doc.recompute()
        original_name = stock.Name

        def apply_preview_size(length, *, transaction):
            self.assertFalse(transaction)
            stock.Length = length
            stock.Placement = self.app.Placement()
            self.doc.recompute()
            return stock

        owner = SimpleNamespace(apply_stock=apply_preview_size, is_current=lambda: False)
        dialog = SimpleNamespace(document=self.doc, owner=owner, edit_started=False, live=True)
        StockDialog.apply_preview(dialog, 60)
        StockDialog.apply_preview(dialog, 80)
        StockDialog.rollback(dialog)
        restored = self.doc.getObject(original_name)
        self.assertEqual((restored.Length.Value, restored.Width.Value), (40, 20))
        self.assertTrue(restored.Placement.isSame(placement, 1e-8))
        self.assertFalse(self.doc.HasPendingTransaction)

    def test_import_adds_two_programs_without_replacing_original_document_data(self):
        import importlib, sys, types
        from unittest.mock import Mock, patch
        from freecad.camed import file_io

        package = importlib.import_module('freecad.camed')
        fake_panel = types.ModuleType('freecad.camed.panel')
        fake_panel._panel = None
        fake_panel.show_panel = Mock(return_value=None)
        gui = types.ModuleType('FreeCADGui')
        gui.Control = types.SimpleNamespace(activeDialog=lambda: None)
        gui.Selection = Mock()
        gui.activateWorkbench = Mock()
        sessions = types.ModuleType('freecad.camed.sessions')
        created = []

        def create(**kwargs):
            self.assertEqual(kwargs, dict(new_program=True, transaction=False))
            op = self.doc.addObject('App::FeaturePython', 'ImportedProgram')
            op.addProperty('App::PropertyStringList', 'Gcode')
            created.append(op)
            return op, True

        sessions.prepare_session = create
        stock_module = types.ModuleType("freecad.camed.program_stock")
        stock_module.apply_import_stock = Mock()
        self.doc.Label = 'Original CAD project'
        self.op.addProperty('App::PropertyString', 'CAMEditorGCodePath')
        self.op.CAMEditorGCodePath = 'original.nc'
        with (
            patch.dict(
                sys.modules,
                {
                    'FreeCADGui': gui,
                    'freecad.camed.panel': fake_panel,
                    'freecad.camed.sessions': sessions,
                    'freecad.camed.program_stock': stock_module,
                },
            ),
            patch.object(package, 'panel', fake_panel, create=True),
            patch.object(file_io, '_close_editor'),
        ):
            file_io._load('one.nc', self.doc, 'G1 X99 F100')
            file_io._load('two.nc', self.doc, 'G1 X55 F100')
        self.assertEqual(self.doc.Label, 'Original CAD project')
        self.assertEqual(self.op.LiveEditorSource, 'G1 X1 F100')
        self.assertEqual(self.op.CAMEditorGCodePath, 'original.nc')
        self.assertEqual([op.LiveEditorSource for op in created], ['G1 X99 F100', 'G1 X55 F100'])
        self.assertIsNot(created[0], created[1])
        self.assertEqual(
            [call.kwargs['operation'] for call in fake_panel.show_panel.call_args_list], created
        )

    def test_failed_import_rolls_back_only_new_objects(self):
        import importlib, sys, types
        from unittest.mock import patch
        from freecad.camed import file_io

        package = importlib.import_module('freecad.camed')
        fake_panel = types.ModuleType('freecad.camed.panel')
        fake_panel._panel = None
        gui = types.ModuleType('FreeCADGui')
        gui.Control = types.SimpleNamespace(activeDialog=lambda: None)
        sessions = types.ModuleType('freecad.camed.sessions')

        def create(**kwargs):
            op = self.doc.addObject('App::FeaturePython', 'ImportedProgram')
            op.addProperty('App::PropertyStringList', 'Gcode')
            return op, True

        sessions.prepare_session = create
        original_names = set(obj.Name for obj in self.doc.Objects)
        label = self.doc.Label
        with (
            patch.dict(
                sys.modules,
                {
                    'FreeCADGui': gui,
                    'freecad.camed.panel': fake_panel,
                    'freecad.camed.sessions': sessions,
                },
            ),
            patch.object(package, 'panel', fake_panel, create=True),
            patch.object(file_io, '_close_editor'),
            patch(
                'freecad.camed.program_documents.bind_path',
                side_effect=OSError('forced bind failure'),
            ),
        ):
            with self.assertRaises(OSError):
                file_io._load('bad.nc', self.doc, 'G1 X99 F100')
        self.assertEqual(set(obj.Name for obj in self.doc.Objects), original_names)
        self.assertEqual(self.doc.Label, label)
        self.assertEqual(self.op.LiveEditorSource, 'G1 X1 F100')
        self.assertFalse(self.doc.HasPendingTransaction)

    def test_stock_form_method_switch_preserves_model_bounds_and_later_edits(self):
        import json, types

        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide import QtWidgets
        from Path.Main import Stock
        from freecad.camed.stock_definition import StockDefinition
        from freecad.camed.stock_panel import StockPanel

        self.__class__._qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.__class__._qt_app.setQuitOnLastWindowClosed(False)
        stock = Stock.CreateBox(
            None,
            extent=self.app.Vector(40, 30, 10),
            placement=self.app.Placement(self.app.Vector(-20, -15, -10), self.app.Rotation()),
        )
        self.doc.recompute()
        cached = StockDefinition(origin='top_center', x=0, y=0, z=0)
        job = types.SimpleNamespace(
            Document=self.doc, Stock=stock, CAMEditorStockDefinition=json.dumps(cached.to_dict())
        )
        form = StockPanel(job, lambda _: stock, tool_mode=True)
        try:
            model_bounds = StockDefinition(
                kind='box_bounds', xmin=4, xmax=26, ymin=5, ymax=37, zmin=-11, zmax=1
            )
            form.load(model_bounds)
            self.assertEqual(form.definition().bounds(), model_bounds.bounds())
            form.dimensions_button.click()
            self.assertEqual(form.definition().bounds(), model_bounds.bounds())
            self.assertEqual(form.box_origin.currentData(), 'top_center')
            form.fields['box_dimensions']['length'].setValue(80)
            expected = form.definition().bounds()
            form.bounds_button.click()
            self.assertEqual(form.definition().bounds(), expected)
            form.dimensions_button.click()
            self.assertEqual(form.definition().bounds(), expected)
            self.assertEqual(form.fields['box_dimensions']['length'].value(), 80)
            form.bounds_button.click()
            form.shape_tabs.setCurrentIndex(1)
            self.assertEqual(form.definition().kind, 'cylinder')
            self.assertTrue(form.box_methods.isHidden())
            self.assertIn('Ø80', form.summary.text())
            form.shape_tabs.setCurrentIndex(0)
            self.assertEqual(form.definition().kind, 'box_bounds')
            self.assertFalse(form.box_methods.isHidden())
            previous_x = form.fields['box_bounds']['xmin'].value()
            form.fields['box_bounds']['xmin'].setValue(form.fields['box_bounds']['xmax'].value())
            form.shape_tabs.setCurrentIndex(1)
            self.assertEqual(form.shape_tabs.currentIndex(), 0)
            self.assertEqual(form.definition().kind, 'box_bounds')
            self.assertFalse(form.apply_button.isEnabled())
            form.fields['box_bounds']['xmin'].setValue(previous_x)
            self.assertTrue(form.apply_button.isEnabled())
        finally:
            form.live_timer.stop()
            form.close()

    def test_failed_new_document_restores_previous_document_and_cleans_only_its_panel(self):
        import importlib, sys, types
        from unittest.mock import Mock, patch
        from freecad.camed.program_documents import new_document

        package = importlib.import_module('freecad.camed')
        panel = types.ModuleType('freecad.camed.panel')
        panel._panel = None
        with (
            patch.dict(sys.modules, {'freecad.camed.panel': panel}),
            patch.object(package, 'panel', panel, create=True),
        ):
            with self.assertRaisesRegex(ValueError, 'forced initialization failure'):
                with new_document() as document:
                    name = document.Name
                    owner = types.SimpleNamespace(
                        document=document, close=Mock(return_value=False), deleteLater=Mock()
                    )
                    panel._panel = owner
                    raise ValueError('forced initialization failure')
        self.assertNotIn(name, self.app.listDocuments())
        self.assertIs(self.app.ActiveDocument, self.doc)
        self.assertIsNone(panel._panel)
        owner.close.assert_called_once()
        owner.deleteLater.assert_called_once()
        self.assertEqual(self.op.LiveEditorSource, 'G1 X1 F100')

    def test_successful_new_document_keeps_source_and_explicit_metadata(self):
        from freecad.camed.program_documents import new_document, initialize_program

        with new_document() as document:
            self.names.append(document.Name)
            operation = document.addObject('App::FeaturePython', 'FreshProgram')
            operation.addProperty('App::PropertyStringList', 'Gcode')
            initialize_program(operation, 'G1 X50 F100', filename='fresh.nc', document_label='Fresh NC')
        self.assertIs(self.app.ActiveDocument, document)
        self.assertEqual(document.Label, 'Fresh NC')
        self.assertEqual(document.FileName, '')
        self.assertEqual(operation.LiveEditorSource, 'G1 X50 F100')
        self.assertTrue(operation.CAMEditorGCodePath.endswith('fresh.nc'))
        self.assertEqual(self.op.LiveEditorSource, 'G1 X1 F100')

    def test_import_stock_uses_native_arc_extents_and_ignores_rapid_travel(self):
        import types
        from freecad.camed.program_stock import estimate_definition

        job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[]))
        result = preview('G0 X1000 Y1000 Z50\nG0 X0 Y0 Z-2\nG2 I5 J0 F100')
        definition = estimate_definition(result, job)
        self.assertEqual(definition.kind, 'box_bounds')
        b = definition.bounds()
        self.assertAlmostEqual(b.xmin, -1)
        self.assertAlmostEqual(b.xmax, 11)
        self.assertAlmostEqual(b.ymin, -6)
        self.assertAlmostEqual(b.ymax, 6)
        self.assertEqual((b.zmin, b.zmax), (-2, 0))

    def test_empty_partial_and_rapid_only_programs_have_no_invented_stock(self):
        import types
        from freecad.camed.program_stock import estimate_definition

        job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[]))
        for source in ('', 'G0 X50 Z5', 'G1 X10 F100\nG0 Z'):
            self.assertIsNone(estimate_definition(preview(source), job))

    def test_import_stock_handles_inches_incremental_motion_and_tool_radius(self):
        import types
        from freecad.camed.program_stock import estimate_definition

        tc = types.SimpleNamespace(ToolNumber=4, Tool=types.SimpleNamespace(Diameter=10))
        job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[tc]))
        result = preview('G20 G91\nT4 M6\nG1 X1 Z-0.1 F10\nX1')
        b = estimate_definition(result, job).bounds()
        self.assertAlmostEqual(b.xmax, 55.8)
        self.assertAlmostEqual(b.xmin, -5)
        self.assertAlmostEqual(b.zmin, -2.54)
        self.assertEqual(b.zmax, 0)

    def test_first_stock_preview_can_be_removed_without_leaving_a_solid(self):
        from Path.Main import Stock
        from freecad.camed.stock_backend import clear_stock

        job = self.doc.addObject('App::FeaturePython', 'EmptyJob')
        job.addProperty('App::PropertyLink', 'Stock')
        job.addProperty('App::PropertyLink', 'Model')
        job.Model = self.doc.addObject('App::DocumentObjectGroup', 'Model')
        stock = Stock.CreateBox(job, extent=self.app.Vector(40, 30, 10), placement=self.app.Placement())
        job.Stock = stock
        self.doc.recompute()
        name = stock.Name
        clear_stock(job)
        self.assertIsNone(job.Stock)
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(job.CAMEditorStockDefinition, '')
        self.assertFalse(self.doc.HasPendingTransaction)

    def test_native_nc_path_needs_no_model_or_stock_to_recompute(self):
        import types
        from freecad.camed.native_program import create, write

        job = self.doc.addObject('App::FeaturePython', 'NCJob')
        job.addProperty('App::PropertyLink', 'Operations')
        job.Operations = self.doc.addObject('App::DocumentObjectGroup', 'NCOperations')
        job.Proxy = types.SimpleNamespace(addOperation=job.Operations.addObject)
        op = create(job, 'NCProgram')
        write(op, preview('G91 G1 X2 F100\nX3').lines)
        self.doc.recompute()
        self.assertEqual(op.TypeId, 'Path::Feature')
        self.assertEqual(list(job.Operations.Group), [op])
        self.assertAlmostEqual(op.Path.Commands[-1].Parameters['X'], 5)
        self.assertNotIn('Invalid', op.State)

    def test_non_native_program_is_rejected_without_mutating_source(self):
        from freecad.camed.native_program import write

        op = self.doc.addObject('Path::FeaturePython', 'LegacyNC')
        op.addProperty('App::PropertyString', 'Source')
        op.addProperty('App::PropertyString', 'LiveEditorSource')
        op.addProperty('App::PropertyStringList', 'Gcode')
        op.Source = 'Text'
        op.LiveEditorSource = 'G1 X27 F100'
        with self.assertRaisesRegex(ValueError, 'program format is not supported'):
            write(op, preview(op.LiveEditorSource).lines)
        self.assertIs(self.doc.getObject(op.Name), op)
        self.assertIsNone(op.Proxy)
        self.assertEqual(op.LiveEditorSource, 'G1 X27 F100')
        self.assertEqual(list(op.Gcode), [])

    def test_stock_includes_deep_start_of_rising_cut(self):
        import types
        from freecad.camed.program_stock import estimate_definition

        job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[]))
        result = preview('G0 Z-50\nG0 Z-8\nG1 X10 Z-2 F100')
        bounds = estimate_definition(result, job).bounds()
        self.assertEqual((bounds.zmin, bounds.zmax), (-8, 0))

    def test_stock_height_ignores_positive_feed_approaches_and_retracts(self):
        import types
        from freecad.camed.program_stock import estimate_definition

        job = types.SimpleNamespace(Tools=types.SimpleNamespace(Group=[]))
        result = preview('G0 Z100\nG1 Z30 F500\nG1 Z-4 F100\nG1 X30 Y20\nG1 Z80 F500')
        bounds = estimate_definition(result, job).bounds()
        self.assertEqual((bounds.zmin, bounds.zmax), (-4, 0))
        self.assertEqual(bounds.size[2], 4)

    def test_native_job_tool_removal_shared_geometry_and_undo(self):
        import sys, types
        from contextlib import nullcontext
        from unittest.mock import patch
        from Path.Tool.Controller import Create
        from freecad.camed.native_program import create
        from freecad.camed.tool_controller import remove_from_job

        job = self.doc.addObject('App::FeaturePython', 'RemovalJob')
        job.addProperty('App::PropertyLink', 'Tools')
        job.Tools = self.doc.addObject('App::DocumentObjectGroup', 'RemovalTools')
        job.addProperty('App::PropertyLink', 'Operations')
        job.Operations = self.doc.addObject('App::DocumentObjectGroup', 'RemovalOperations')
        job.Proxy = types.SimpleNamespace(addOperation=job.Operations.addObject)
        anchor = create(job, 'RemovalProgram')
        anchor.addProperty('App::PropertyString', 'LiveEditorSource')
        anchor.LiveEditorSource = 'T3 M6\nG1 X10 F100'
        first = Create(toolNumber=3, assignViewProvider=False)
        tool_name = first.Tool.Name
        second = Create('SharedTC', tool=first.Tool, toolNumber=4, assignViewProvider=False)
        job.Tools.Group = [first, second]
        anchor.ToolController = first
        anchor.addProperty('App::PropertyLink', 'CAMEditorInitialTool')
        anchor.CAMEditorInitialTool = first
        self.doc.recompute()
        first_name, second_name = first.Name, second.Name
        owner = types.SimpleNamespace(
            document=self.doc,
            job=job,
            operation=anchor,
            shutting_down=False,
            is_current=lambda: True,
            resource_update=nullcontext,
            pending_code=False,
        )
        gui = types.SimpleNamespace(Control=types.SimpleNamespace(activeDialog=lambda: None))
        with patch.dict(sys.modules, {'FreeCADGui': gui}):
            self.assertTrue(remove_from_job(owner, first))
            self.assertIsNone(self.doc.getObject(first_name))
            self.assertIsNotNone(self.doc.getObject(tool_name))
            self.assertIsNone(anchor.CAMEditorInitialTool)
            self.doc.undo()
            self.assertIsNotNone(self.doc.getObject(first_name))
            self.doc.redo()
            self.assertTrue(remove_from_job(owner, second))
            self.assertIsNone(self.doc.getObject(second_name))
            self.assertIsNone(self.doc.getObject(tool_name))
            self.doc.undo()
        restored = self.doc.getObject(second_name)
        self.assertIsNotNone(restored.Tool)
        self.assertTrue(restored.Tool.Shape.isValid())
        self.assertFalse(restored.Tool.Shape.isNull())
        self.assertEqual(anchor.LiveEditorSource, 'T3 M6\nG1 X10 F100')
        self.assertFalse(self.doc.HasPendingTransaction)
