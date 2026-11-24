"""Estimate imported NC stock using FreeCAD's own motion-edge geometry."""

import math
from .gcode_model import is_motion_line
from .stock_definition import StockDefinition


def estimate_definition(result, job):
    import FreeCAD as App
    import Path
    from Path import Geom
    from .tool_backend import controllers

    if result.error:
        return None
    position = App.Vector(0, 0, 0)
    bounds = App.BoundBox()
    used = set()
    for line, state, number in zip(result.lines, result.states, result.tools):
        if not is_motion_line(line):
            continue
        command = Path.Command(line)
        if command.Name != 'G0':
            edge = Geom.edgeForCmd(command, position)
            if edge is not None:
                bounds.add(edge.BoundBox)
                used.add(number)
        position = App.Vector(*state.position)
    if not bounds.isValid():
        return None
    # NC describes cutter motion, not the original blank. Leave a small side
    # allowance and include the known cutter radius where a T number exists.
    margin = 1.0
    for tc in controllers(job):
        if int(tc.ToolNumber) in used and tc.Tool is not None:
            diameter = float(tc.Tool.Diameter)
            if math.isfinite(diameter) and diameter > 0:
                margin = max(margin, diameter / 2)
    # The editor assumes work Z0 is the stock top. Positive feed moves can
    # be approaches/retracts, so they must not add material above that plane.
    bottom, top = min(0.0, bounds.ZMin), 0.0
    if top - bottom < 1.0:
        bottom = top - 1.0
    definition = StockDefinition(
        kind='box_bounds',
        xmin=bounds.XMin - margin,
        xmax=bounds.XMax + margin,
        ymin=bounds.YMin - margin,
        ymax=bounds.YMax + margin,
        zmin=bottom,
        zmax=top,
    )
    definition.bounds()
    return definition


def apply_import_stock(operation, result):
    from PathScripts import PathUtils
    from .stock_backend import apply_stock

    job = PathUtils.findParentJob(operation)
    definition = estimate_definition(result, job)
    if definition is not None:
        stock = apply_stock(job, definition, transaction=False)
        stock.Label = 'Stok · G-code tahmini'
        return True
    return False
