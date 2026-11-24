"""Native stock factory integration checks with stubs, not FreeCAD runtime."""

import importlib
import sys
import types
from collections import namedtuple
import unittest
from unittest.mock import Mock, patch
from freecad.camed.stock_definition import StockDefinition


Vector = namedtuple('Vector', 'x y z')
Placement = namedtuple('Placement', 'Base Rotation')


class Identity(str):
    def inverted(self):
        return self

    def multVec(self, point):
        return point


class StockType:
    CreateBox = "CreateBox"
    CreateCylinder = "CreateCylinder"

    @staticmethod
    def FromStock(stock):
        return stock.StockType if stock else "None"


def stock(kind, name="Stock", references=()):
    result = types.SimpleNamespace(
        StockType=kind,
        Name=name,
        InList=list(references),
        ViewObject=types.SimpleNamespace(),
        State=[],
        Shape=Mock(),
        Visibility=False,
        Placement=Placement(Vector(0, 0, 0), Identity("identity")),
    )
    result.Shape.isNull.return_value = False
    return result


class StockBackendTests(unittest.TestCase):
    def setUp(self):
        modules = {
            name: types.ModuleType(name) for name in ("FreeCAD", "Path", "Path.Main", "Path.Main.Stock")
        }
        self.doc = Mock()
        app = modules["FreeCAD"]
        app.ActiveDocument = self.doc
        app.Vector = Vector
        app.Rotation = lambda: Identity("identity")
        app.Placement = Placement
        native = modules["Path.Main.Stock"]
        native.StockType = StockType
        native.StockCreateBox = types.SimpleNamespace(MinExtent=0.001)
        native.StockCreateCylinder = types.SimpleNamespace(MinExtent=0.001)
        native.CreateBox = Mock(side_effect=lambda *a, **kw: stock("CreateBox", "NewBox"))
        native.CreateCylinder = Mock(side_effect=self.create_cylinder)
        modules["Path.Main"].Stock = native
        self.native = native
        self.patcher = patch.dict(sys.modules, modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        sys.modules.pop("freecad.camed.stock_backend", None)
        self.backend = importlib.import_module("freecad.camed.stock_backend")
        self.job = types.SimpleNamespace(Document=self.doc, Stock=stock("CreateBox"), addProperty=Mock())
        self.doc.recompute.side_effect = self.recompute_stock

    def create_cylinder(self, *args, **kwargs):
        result = stock("CreateCylinder", "NewCylinder")
        result.Radius = kwargs["radius"]
        result.Height = kwargs["height"]
        result.Placement = kwargs["placement"]
        result.Axis = kwargs.get("axis", "Z")
        return result

    def recompute_stock(self):
        current = self.job.Stock
        if not hasattr(current, "Placement"):
            return
        (x, y, z), _ = current.Placement
        if current.StockType == "CreateCylinder":
            radius = current.Radius
            xmin, xmax, ymin, ymax = x - radius, x + radius, y - radius, y + radius
        else:
            xmin, xmax, ymin, ymax = x, x + current.Length, y, y + current.Width
        current.Shape.BoundBox = types.SimpleNamespace(
            XMin=xmin, XMax=xmax, YMin=ymin, YMax=ymax, ZMin=z, ZMax=z + current.Height
        )

    def test_box_updates_same_native_object(self):
        old = self.job.Stock
        current = self.backend.apply_stock(self.job, StockDefinition())
        self.assertIs(current, old)
        self.assertTrue(current.Visibility)
        self.assertEqual((current.Length, current.Width, current.Height), (40, 30, 10))
        self.assertEqual(current.Placement, ((-5, -5, -10), "identity"))
        self.native.CreateBox.assert_not_called()
        self.doc.commitTransaction.assert_called_once()

    def test_rotated_box_uses_native_lengths_and_preserves_placement_when_resized(self):
        from dataclasses import replace

        class QuarterTurn:
            def __init__(self, direction=1):
                self.direction = direction

            def inverted(self):
                return QuarterTurn(-self.direction)

            def multVec(self, v):
                return Vector(-self.direction * v.y, self.direction * v.x, v.z)

        box = self.job.Stock
        box.Length, box.Width, box.Height = 40, 20, 10
        placement = Placement(Vector(2, 3, 4), QuarterTurn())
        box.Placement = placement
        spec = self.backend.load_definition(self.job)
        self.assertEqual((spec.length, spec.width, spec.height), (40, 20, 10))
        self.assertEqual((spec.x, spec.y, spec.z), (3, -2, 4))
        self.backend.apply_stock(self.job, replace(spec, length=50))
        self.assertEqual((box.Length, box.Width, box.Height), (50, 20, 10))
        self.assertEqual(box.Placement, placement)

    def test_switch_to_cylinder_uses_native_factory(self):
        spec = StockDefinition(kind="cylinder", diameter=20, height=15, x=1, y=2, z=0, origin="top_center")
        current = self.backend.apply_stock(self.job, spec)
        self.assertIs(current, self.job.Stock)
        self.assertTrue(current.Visibility)
        self.native.CreateCylinder.assert_called_once_with(
            self.job, radius=10, height=15, placement=((1, 2, -15), "identity"), axis="Z"
        )
        self.doc.removeObject.assert_called_once_with("Stock")

    def test_shared_previous_stock_is_not_deleted(self):
        self.job.Stock.InList = [object()]
        spec = StockDefinition(kind="cylinder", origin="top_center")
        self.backend.apply_stock(self.job, spec)
        self.doc.removeObject.assert_not_called()

    def test_cylinder_radius_minimum_is_checked_before_mutation(self):
        with self.assertRaises(ValueError):
            self.backend.apply_stock(
                self.job, StockDefinition(kind="cylinder", diameter=0.001, origin="top_center")
            )
        self.doc.openTransaction.assert_not_called()

    def test_native_geometry_failure_aborts_transaction(self):
        self.job.Stock.Shape.isNull.return_value = True
        with self.assertRaises(ValueError):
            self.backend.apply_stock(self.job, StockDefinition())
        self.doc.abortTransaction.assert_called_once()
        self.doc.commitTransaction.assert_not_called()

    def test_session_transaction_can_own_the_stock_change(self):
        self.backend.apply_stock(self.job, StockDefinition(), transaction=False)
        self.doc.openTransaction.assert_not_called()
        self.doc.commitTransaction.assert_not_called()

    def test_definition_is_saved_and_loaded(self):
        spec = StockDefinition(kind="box_bounds", xmin=-25, xmax=25, ymin=-20, ymax=20, zmin=-8, zmax=0)
        self.backend.apply_stock(self.job, spec)
        self.assertEqual(self.backend.load_definition(self.job), spec)

    def test_external_native_box_edit_overrides_stale_saved_dimensions(self):
        spec = StockDefinition(origin="top_center", x=0, y=0, z=0)
        self.backend.apply_stock(self.job, spec)
        self.job.Stock.Length = 80
        self.doc.recompute()
        current = self.backend.load_definition(self.job)
        self.assertEqual(current.length, 80)
        self.assertEqual(current.origin, "top_center")
        self.assertEqual(current.bounds().xmin, -20)
        self.assertEqual(current.bounds().xmax, 60)
        self.assertEqual(current.x, 20)

    def test_external_native_cylinder_edit_updates_radius_and_keeps_bottom_origin(self):
        spec = StockDefinition(
            kind="cylinder", diameter=20, height=10, origin="bottom_center", x=3, y=4, z=5
        )
        self.backend.apply_stock(self.job, spec)
        self.job.Stock.Radius = 15
        self.job.Stock.Height = 12
        self.doc.recompute()
        current = self.backend.load_definition(self.job)
        self.assertEqual((current.diameter, current.height), (30, 12))
        self.assertEqual((current.x, current.y, current.z), (3, 4, 5))
        self.assertEqual(current.origin, "bottom_center")

    def test_matching_shape_keeps_saved_entry_method_and_origin(self):
        spec = StockDefinition(origin="bottom_center", x=10, y=20, z=-5)
        self.backend.apply_stock(self.job, spec)
        self.assertEqual(self.backend.load_definition(self.job), spec)

    def test_dirty_native_shape_is_not_replaced_with_stale_saved_data(self):
        self.backend.apply_stock(self.job, StockDefinition())
        self.job.Stock.State = ["Touched"]
        with self.assertRaises(ValueError):
            self.backend.load_definition(self.job)


if __name__ == "__main__":
    unittest.main()
