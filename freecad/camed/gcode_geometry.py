"""Pure XYZ arc geometry used by the G-code interpreter."""

from .i18n import tr
import math
from .gcode_syntax import CodeError


def radius_center(start, end, radius, clockwise, number):
    dx, dy = end["X"] - start["X"], end["Y"] - start["Y"]
    chord = math.hypot(dx, dy)
    r = abs(radius)
    if chord <= 1e-9 or r < chord / 2 - 1e-9:
        raise CodeError(
            number, tr('Arc radius R is incompatible with the chord. Use I/J for a full circle.')
        )
    height = math.sqrt(max(0, r * r - chord * chord / 4))
    side = (-1 if clockwise else 1) * (-1 if radius < 0 else 1)
    return {"I": dx / 2 - side * dy / chord * height, "J": dy / 2 + side * dx / chord * height}


def arc_center(position, end, values, motion, plane, scale, absolute_center, number):
    if plane != 17:
        raise CodeError(
            number, tr('XZ/YZ arcs are not supported in the preview. Linear moves are supported.')
        )
    if "R" in values:
        if set(values).intersection("IJ"):
            raise CodeError(number, tr('Do not combine R and I/J in the same arc.'))
        center = radius_center(position, end, values["R"] * scale, motion == 2, number)
    else:
        if not set(values).intersection("IJ"):
            raise CodeError(number, tr('Specify I/J or R for the arc center.'))
        if absolute_center and not {"I", "J"} <= set(values):
            raise CodeError(number, tr('G90.1 requires both I and J for an absolute XY arc center.'))
        center = {
            key: values[key] * scale - (position[axis] if absolute_center else 0)
            for key, axis in (("I", "X"), ("J", "Y"))
            if key in values
        }
    if not all(math.isfinite(value) for value in center.values()):
        raise CodeError(number, tr('Arc center coordinates must be finite.'))
    cx = position["X"] + center.get("I", 0)
    cy = position["Y"] + center.get("J", 0)
    r0 = math.hypot(position["X"] - cx, position["Y"] - cy)
    r1 = math.hypot(end["X"] - cx, end["Y"] - cy)
    if not math.isfinite(r0) or not math.isfinite(r1) or r0 <= 1e-9 or abs(r0 - r1) > max(0.001, r0 * 1e-5):
        raise CodeError(number, tr('The start and end radii of the arc do not match.'))
    return center
