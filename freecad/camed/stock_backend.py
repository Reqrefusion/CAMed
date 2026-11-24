"""Reuse FreeCAD's native box/cylinder stock factories and persistence."""

from .i18n import tr
from .transactions import document_transaction
import json
import math
import FreeCAD as App
from Path.Main import Stock as NativeStock
from .stock_definition import StockDefinition


def stock_rotation(stock):
    """Coordinate frame used by the form, including the native cylinder axis."""
    kind = NativeStock.StockType.FromStock(stock) if stock is not None else None
    if kind not in (NativeStock.StockType.CreateBox, NativeStock.StockType.CreateCylinder):
        return App.Rotation()
    rotation = stock.Placement.Rotation
    if kind == NativeStock.StockType.CreateCylinder and str(stock.Axis) != 'Z':
        axis = App.Vector(1, 0, 0) if str(stock.Axis) == 'X' else App.Vector(0, 1, 0)
        rotation = rotation.multiply(App.Rotation(App.Vector(0, 0, 1), axis))
    return rotation


def native_definition(stock):
    """The native stock shape is authoritative; saved data only preserves UI choices."""
    if stock is None:
        return StockDefinition()
    if (
        any(state in getattr(stock, "State", []) for state in ("Invalid", "Touched", "Recompute"))
        or stock.Shape.isNull()
    ):
        raise ValueError(tr('Stock geometry is not ready. Recompute the document first.'))
    kind = NativeStock.StockType.FromStock(stock)
    if kind in (NativeStock.StockType.CreateBox, NativeStock.StockType.CreateCylinder):
        base = stock_rotation(stock).inverted().multVec(stock.Placement.Base)
        height = float(stock.Height)
        if kind == NativeStock.StockType.CreateBox:
            result = StockDefinition(
                kind='box_dimensions', length=float(stock.Length), width=float(stock.Width),
                height=height, x=base.x, y=base.y, z=base.z, origin='bottom_corner',
            )
        else:
            result = StockDefinition(
                kind='cylinder', diameter=2 * float(stock.Radius), height=height,
                x=base.x, y=base.y, z=base.z, origin='bottom_center',
            )
    else:
        bb = stock.Shape.BoundBox
        result = StockDefinition(
            kind="box_bounds", xmin=bb.XMin, ymin=bb.YMin, zmin=bb.ZMin,
            xmax=bb.XMax, ymax=bb.YMax, zmax=bb.ZMax,
        )
    result.bounds()
    return result


def load_definition(job):
    actual = native_definition(job.Stock)
    saved = getattr(job, "CAMEditorStockDefinition", "")
    if not saved or job.Stock is None:
        return actual
    try:
        cached = StockDefinition.from_dict(json.loads(saved))
    except (ValueError, TypeError):
        return actual
    same_type = (actual.kind == "cylinder") == (cached.kind == "cylinder")
    if not same_type:
        return actual
    cached_bounds, actual_bounds = cached.bounds(), actual.bounds()
    if all(
        math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-7)
        for a, b in zip(cached_bounds.__dict__.values(), actual_bounds.__dict__.values())
    ):
        return cached
    # Keep the user's reference-point preference, but derive every measurement
    # again from the current native shape, including external property edits.
    return actual.converted(cached.kind, cached.origin)


def validate_dimensions(definition):
    bounds = definition.bounds()
    cylindrical = definition.kind == 'cylinder'
    minimum = (
        NativeStock.StockCreateCylinder.MinExtent if cylindrical else NativeStock.StockCreateBox.MinExtent
    )
    if cylindrical:
        measured = (definition.diameter / 2, definition.height)
    elif definition.kind == 'box_dimensions':
        measured = (definition.length, definition.width, definition.height)
    else:
        measured = bounds.size
    if min(measured) < minimum:
        raise ValueError(tr('Stock dimensions must be at least {minimum:g} mm.').format(minimum=minimum))
    return bounds


def apply_stock(job, definition, transaction=True):
    """Change only this Job's stock. Reuse the object while its type is stable."""
    bounds = validate_dimensions(definition)
    doc = job.Document
    if App.ActiveDocument is not doc:
        raise ValueError(tr('Activate the CAMed document.'))
    cylindrical = definition.kind == "cylinder"
    expected = NativeStock.StockType.CreateCylinder if cylindrical else NativeStock.StockType.CreateBox
    old = job.Stock
    old_kind = NativeStock.StockType.FromStock(old) if old is not None else None
    rotation = stock_rotation(old)
    base = App.Vector(
        definition.x if cylindrical else bounds.xmin,
        definition.y if cylindrical else bounds.ymin,
        bounds.zmin,
    )
    placement = App.Placement(rotation.multVec(base), rotation)
    size = bounds.size
    if definition.kind == 'box_dimensions':
        size = definition.length, definition.width, definition.height
    with document_transaction(doc, tr('CAMed stock settings'), enabled=transaction):
        if old_kind == expected:
            stock = old
            if cylindrical:
                stock.Radius = definition.diameter / 2
                stock.Height = definition.height
                stock.Axis = "Z"
            else:
                stock.Length, stock.Width, stock.Height = size
            stock.Placement = placement
        elif cylindrical:
            stock = NativeStock.CreateCylinder(
                job, radius=definition.diameter / 2, height=definition.height, placement=placement, axis="Z"
            )
        else:
            stock = NativeStock.CreateBox(job, extent=App.Vector(*size), placement=placement)
        job.Stock = stock
        stock.Label = tr('Stock · Cylinder') if cylindrical else tr('Stock · Box')
        if stock.ViewObject is not None:
            stock.ViewObject.DisplayMode = "Flat Lines"
            stock.ViewObject.Transparency = 65
            stock.ViewObject.DrawStyle = "Solid"
        stock.Visibility = True
        if not hasattr(job, "CAMEditorStockDefinition"):
            job.addProperty("App::PropertyString", "CAMEditorStockDefinition", "CAMed")
        job.CAMEditorStockDefinition = json.dumps(definition.to_dict())
        doc.recompute()
        if "Invalid" in stock.State or stock.Shape.isNull():
            raise ValueError(tr('FreeCAD could not create the stock geometry.'))
        # The internal model is solely a carrier for native CAM's required
        # base geometry; keep it in sync without displaying a duplicate solid.
        reference = getattr(job, "CAMEditorReference", None)
        if reference:
            reference.Shape = stock.Shape.copy()
            reference.Visibility = False
            doc.recompute()
        if old is not None and stock is not old and not old.InList:
            doc.removeObject(old.Name)
        return stock


def clear_stock(job, transaction=True):
    """Restore an unconfigured stock without leaving a preview solid behind."""
    from .program_backend import require_document_idle

    doc = job.Document
    if App.ActiveDocument is not doc:
        raise ValueError(tr('Activate the CAMed document.'))
    if transaction:
        require_document_idle(doc)
    old = job.Stock
    if old is None:
        return
    with document_transaction(doc, tr('Remove CAMed stock'), enabled=transaction):
        job.Stock = None
        if not hasattr(job, "CAMEditorStockDefinition"):
            job.addProperty("App::PropertyString", "CAMEditorStockDefinition", "CAMed")
        job.CAMEditorStockDefinition = ""
        if not old.InList:
            doc.removeObject(old.Name)
        doc.recompute()
