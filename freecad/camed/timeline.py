"""Source block boundaries in the native GL simulator's discrete timeline.

Mirror PathSimulator/AppGL/MillPathSegment's step counts, not line percentages
or machining-time estimates. GLSession seeds the native initial position at
the same XYZ origin the editor's modal normalizer uses.
"""

from .gcode_model import is_motion_line
import math
import re


def boundaries(result, stock_dimension, quality, diameters, tool_trace=None):
    resolution = min(4.0, max(0.5, stock_dimension * 0.05 / quality))
    small_step = math.pi / (2 if quality < 4 else 4 if quality < 8 else 8)
    position = dict(X=0.0, Y=0.0, Z=0.0)
    total = 0
    ends = []
    for index, (line, tool) in enumerate(
        zip(result.lines, result.tools if tool_trace is None else tool_trace)
    ):
        if is_motion_line(line):
            values = {key: float(value) for key, value in re.findall(r"([XYZIJ])([+-]?[\d.]+)", line)}
            end = {axis: values.get(axis, position[axis]) for axis in "XYZ"}
            radius = math.hypot(values.get("I", 0), values.get("J", 0))
            if line.startswith(("G2 ", "G3 ")) and radius > 1e-6:
                cx = position["X"] + values.get("I", 0)
                cy = position["Y"] + values.get("J", 0)
                start_angle = math.atan2(cx - position["X"], position["Y"] - cy)
                end_angle = math.atan2(cx - end["X"], end["Y"] - cy)
                direction = -1 if line.startswith("G3 ") else 1
                sweep = (start_angle - end_angle) * direction
                if sweep < 1e-6:
                    sweep += math.tau
                small = radius <= diameters.get(tool, 0) / 2
                # Native large-radius clamp currently resolves to 2 degrees.
                step = small_step if small else math.pi / 90
                total += int(sweep / step) + 1 + int(not small)
            else:
                distance = math.sqrt(sum((end[a] - position[a]) ** 2 for a in "XYZ"))
                total += max(1, int(distance / resolution))
            position = end
        states = getattr(result, "states", [])
        source_line = states[index].source_line if index < len(states) else index + 1
        while len(ends) < source_line:
            ends.append(ends[-1] if ends else 0)
        ends[source_line - 1] = total
    return ends, total


def block_step(ends, source_line):
    """One-based source line; errors/trailing comments retain last valid state."""
    return ends[min(max(source_line - 1, 0), len(ends) - 1)] if ends and source_line > 0 else 0
