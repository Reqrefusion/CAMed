"""Validate a complete immutable input before touching the native GL engine.

Python exceptions cannot recover a native renderer crash. Never reset its last
good snapshot while stock/tools are incomplete or a profile is malformed.
"""

from .gcode_model import is_motion_line
from .i18n import tr
import math
import re
from .tool_backend import controllers
from .scene_state import signature
from .timeline import boundaries

FLOAT_MAX = 3.402823466e38
GEOMETRY_LIMIT = math.sqrt(FLOAT_MAX / 16)


def scalar(value, label, positive=False):
    value = float(value)
    if not math.isfinite(value) or abs(value) > FLOAT_MAX or (positive and value <= 0):
        raise ValueError(tr('{label}: enter a finite, valid value.').format(label=label))
    return value


def solid(shape, label):
    if shape is None or shape.isNull() or not shape.isValid():
        raise ValueError(tr('{label} geometry is invalid or not ready.').format(label=label))
    if not shape.Solids or scalar(shape.Volume, label, True) <= 0:
        raise ValueError(tr('{label} must be a closed solid.').format(label=label))
    box = shape.BoundBox
    lengths = [scalar(getattr(box, axis), label, True) for axis in ("XLength", "YLength", "ZLength")]
    # Native segment lengths are computed with float squares.
    if sum(length * length for length in lengths) > FLOAT_MAX:
        raise ValueError(
            tr("{label} dimensions exceed the simulation's numeric range.").format(label=label)
        )
    return max(lengths)


def profile_points(profile, number):
    label = tr('T{number} profile').format(number=number)
    try:
        points = [scalar(value, label) for value in profile]
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(tr('{label} is invalid.').format(label=label)) from error
    if len(points) < 4 or len(points) % 2 or any(r < 0 for r in points[::2]):
        raise ValueError(tr('{label}: at least two radius/height pairs are required.').format(label=label))
    if any(abs(value) > GEOMETRY_LIMIT for value in points):
        raise ValueError(tr("{label} exceeds the simulation's numeric range.").format(label=label))
    if max(points[::2]) <= 0 or max(points[1::2]) <= min(points[1::2]):
        raise ValueError(tr('{label}: diameter and length cannot be zero.').format(label=label))
    return points


def controller_profile(native, by_number, number):
    if not isinstance(number, int) or not 0 <= number <= 2147483647:
        raise ValueError(tr('Enter a valid CAM tool number.'))
    matches = by_number.get(number, [])
    if len(matches) != 1 or matches[0].Tool is None:
        raise ValueError(
            tr('T{number} has missing geometry or an ambiguous tool number.').format(number=number)
        )
    tool = matches[0].Tool
    if any(state in getattr(tool, "State", []) for state in ("Invalid", "Touched", "Recompute")):
        raise ValueError(tr('Waiting for T{number} geometry to recompute.').format(number=number))
    solid(tool.Shape, f"T{number}")
    diameter = scalar(tool.Diameter, tr('T{number} diameter').format(number=number), True)
    profile = profile_points(native.GetToolProfile(tool, 0.5), number)
    return profile, number, diameter


def fallback_profile(native, by_number):
    """Choose geometry for the renderer without assigning a document tool."""
    for number in by_number:
        try:
            return controller_profile(native, by_number, number)
        except (ValueError, TypeError, AttributeError, OverflowError, RuntimeError, ReferenceError):
            continue
    number = 1
    while number in by_number:
        number += 1
    return [0.5, 10.0, 0.5, 0.0, 0.0, 0.0], number, 1.0


def prepare(owner, native):
    result = owner.preview_result
    stock_object = owner.job.Stock
    if stock_object is None:
        raise ValueError(tr('Stock is required for simulation.'))
    dimension = solid(stock_object.Shape, tr('Stock'))
    quality = scalar(getattr(owner, "simulation_quality", native.quality), tr('Simulation quality'), True)
    before = signature(owner.job, owner.operation)
    stock = stock_object.Shape.copy()
    by_number = {}
    for tc in controllers(owner.job):
        by_number.setdefault(int(tc.ToolNumber), []).append(tc)
    display_tools = [state.display_tool for state in result.states]
    motion_indices = [i for i, line in enumerate(result.lines) if is_motion_line(line)]
    profiles = {}
    if any(display_tools[i] is None for i in motion_indices):
        fallback = fallback_profile(native, by_number)
        fallback_number = fallback[1]
        profiles[fallback_number] = fallback
        display_tools = [fallback_number if number is None else number for number in display_tools]
    motion = [(result.lines[i], display_tools[i]) for i in motion_indices]
    for line, _ in motion:
        if any(abs(float(value)) > GEOMETRY_LIMIT for value in re.findall(r"[XYZIJ]([+-]?[\d.]+)", line)):
            raise ValueError(tr("Motion coordinates exceed the simulation's numeric range."))
    for _, number in motion:
        if number not in profiles:
            profiles[number] = controller_profile(native, by_number, number)
    tools = list(profiles.values())
    diameters = {number: diameter for _, number, diameter in tools}
    if (
        not owner.is_current()
        or getattr(owner, "resource_depth", 0)
        or signature(owner.job, owner.operation) != before
    ):
        raise ValueError(tr('Finish editing stock and tools before updating the simulation.'))
    ends, total = boundaries(result, dimension, quality, diameters, tool_trace=display_tools)
    if total >= 2147483600:
        raise ValueError(tr('The program exceeds the simulation step limit.'))
    return stock, quality, motion, tools, ends, total
