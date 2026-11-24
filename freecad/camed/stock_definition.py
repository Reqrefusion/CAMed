"""Stock coordinates and input validation, independent of FreeCAD/Qt."""

from .i18n import tr
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class Bounds:
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def size(self):
        return self.xmax - self.xmin, self.ymax - self.ymin, self.zmax - self.zmin


@dataclass(frozen=True)
class StockDefinition:
    kind: str = "box_dimensions"
    length: float = 40.0
    width: float = 30.0
    height: float = 10.0
    diameter: float = 30.0
    x: float = -5.0
    y: float = -5.0
    z: float = 0.0
    origin: str = "top_corner"
    xmin: float = -5.0
    ymin: float = -5.0
    zmin: float = -10.0
    xmax: float = 35.0
    ymax: float = 25.0
    zmax: float = 0.0

    def bounds(self):
        values = asdict(self)
        if any(not math.isfinite(v) for v in values.values() if isinstance(v, (float, int))):
            raise ValueError(tr('Stock values must be finite numbers.'))
        if self.kind == "box_bounds":
            result = Bounds(self.xmin, self.ymin, self.zmin, self.xmax, self.ymax, self.zmax)
        elif self.kind in ("box_dimensions", "cylinder"):
            origins = ("top_corner", "bottom_corner", "top_center", "bottom_center")
            if self.origin not in origins:
                raise ValueError(tr('Invalid stock reference point.'))
            if self.kind == "cylinder" and not self.origin.endswith("center"):
                raise ValueError(tr('The cylinder reference point must be the top or bottom center.'))
            length = self.diameter if self.kind == "cylinder" else self.length
            width = self.diameter if self.kind == "cylinder" else self.width
            x = self.x - length / 2 if self.origin.endswith("center") else self.x
            y = self.y - width / 2 if self.origin.endswith("center") else self.y
            z = self.z - self.height if self.origin.startswith("top") else self.z
            result = Bounds(x, y, z, x + length, y + width, z + self.height)
        else:
            raise ValueError(tr('Unknown stock type.'))
        if not all(math.isfinite(v) for v in result.__dict__.values()) or not all(
            math.isfinite(v) for v in result.size
        ):
            raise ValueError(tr('Stock coordinates exceed the calculation range.'))
        if min(result.size) <= 0:
            raise ValueError(tr('Stock dimensions must be positive. Each maximum must exceed its minimum.'))
        return result

    def converted(self, kind, origin=None):
        """Express these bounds in another form without moving their origin."""
        b = self.bounds()
        if kind == "box_bounds":
            return StockDefinition(kind=kind, **b.__dict__)
        if kind not in ("box_dimensions", "cylinder"):
            raise ValueError(tr('Unknown stock type.'))
        origin = origin or ("top_center" if kind == "cylinder" else "top_corner")
        centered = origin.endswith("center")
        result = StockDefinition(
            kind=kind,
            origin=origin,
            length=b.size[0],
            width=b.size[1],
            height=b.size[2],
            diameter=max(b.size[:2]),
            x=(b.xmin + b.xmax) / 2 if centered else b.xmin,
            y=(b.ymin + b.ymax) / 2 if centered else b.ymin,
            z=b.zmax if origin.startswith("top") else b.zmin,
        )
        result.bounds()
        return result

    def to_dict(self):
        self.bounds()
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        result = cls(**data)
        result.bounds()
        return result
