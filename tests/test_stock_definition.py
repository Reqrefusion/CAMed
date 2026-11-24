import unittest
from freecad.camed.stock_definition import StockDefinition, Bounds


class StockDefinitionTests(unittest.TestCase):
    def test_top_corner_box(self):
        self.assertEqual(StockDefinition().bounds(), Bounds(-5, -5, -10, 35, 25, 0))

    def test_top_center_box(self):
        spec = StockDefinition(length=40, width=20, height=5, x=10, y=20, z=0, origin="top_center")
        self.assertEqual(spec.bounds(), Bounds(-10, 10, -5, 30, 30, 0))

    def test_bottom_corner_and_center(self):
        self.assertEqual(StockDefinition(x=0, y=0, z=2, origin="bottom_corner").bounds().zmax, 12)
        b = StockDefinition(x=0, y=0, z=2, origin="bottom_center").bounds()
        self.assertEqual((b.xmin, b.ymin, b.zmin), (-20, -15, 2))

    def test_min_max(self):
        b = StockDefinition(kind="box_bounds", xmin=-1, xmax=2, ymin=-2, ymax=3, zmin=-10, zmax=0).bounds()
        self.assertEqual(b.size, (3, 5, 10))

    def test_cylinder(self):
        spec = StockDefinition(kind="cylinder", diameter=20, height=15, x=2, y=3, z=0, origin="top_center")
        self.assertEqual(spec.bounds(), Bounds(-8, -7, -15, 12, 13, 0))

    def test_invalid_values(self):
        for spec in (
            StockDefinition(length=0),
            StockDefinition(height=-1),
            StockDefinition(x=float("nan")),
            StockDefinition(diameter=float("inf")),
            StockDefinition(kind="box_bounds", xmin=35, xmax=35),
            StockDefinition(kind="cylinder", origin="top_corner"),
            StockDefinition(origin="unknown"),
            StockDefinition(kind="sphere"),
        ):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                spec.bounds()

    def test_persistent_roundtrip(self):
        spec = StockDefinition(kind="cylinder", diameter=28, x=0, y=0, origin="bottom_center")
        self.assertEqual(StockDefinition.from_dict(spec.to_dict()), spec)

    def test_box_entry_methods_roundtrip_without_moving_any_face(self):
        bounds = StockDefinition(kind="box_bounds", xmin=4, xmax=26, ymin=5, ymax=37, zmin=-11, zmax=1)
        for origin in ("top_corner", "top_center", "bottom_corner", "bottom_center"):
            with self.subTest(origin=origin):
                dimensions = bounds.converted("box_dimensions", origin)
                self.assertEqual(dimensions.bounds(), bounds.bounds())
                self.assertEqual(dimensions.converted("box_bounds").bounds(), bounds.bounds())

    def test_cylinder_origin_conversion_preserves_center_and_both_z_faces(self):
        cylinder = StockDefinition(
            kind="cylinder", diameter=30, height=12, origin="bottom_center", x=3, y=4, z=-5
        )
        top = cylinder.converted("cylinder", "top_center")
        self.assertEqual(top.bounds(), cylinder.bounds())
        self.assertEqual((top.x, top.y, top.z), (3, 4, 7))
        self.assertEqual(top.converted("cylinder", "bottom_center").bounds(), cylinder.bounds())


if __name__ == "__main__":
    unittest.main()
