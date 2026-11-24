"""Small geometry signatures for externally edited CAM resources."""

from .tool_backend import fingerprint


def signature(job, operation):
    stock = job.Stock
    shape = stock.Shape if stock is not None else None
    box = getattr(shape, "BoundBox", None)
    bounds = tuple(getattr(box, name, None) for name in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"))
    shape_hash = getattr(shape, "hashCode", None)
    stock_state = (
        getattr(stock, "Name", None),
        bounds,
        getattr(shape, "Volume", None),
        str(getattr(stock, "Placement", "")),
        getattr(job, "CAMEditorStockDefinition", ""),
        shape_hash() if callable(shape_hash) else None,
    )
    initial = getattr(operation, "CAMEditorInitialTool", None)
    return stock_state, fingerprint(job), getattr(initial, "Name", None)
