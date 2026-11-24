"""Build editor blocks with FreeCAD's original drilling toolpath generator."""

from .i18n import tr
from dataclasses import dataclass
import math
from .drill_cycles import CYCLES, MAX_PECKS
from .validation import preview
from .gcode_syntax import format_number


@dataclass(frozen=True)
class CycleSpec:
    cycle: int = 81
    holes: tuple = ((0.0, 0.0),)
    depth: float = -5.0
    retract: float = 2.0
    clearance: float = 5.0
    feed: float = 120.0
    peck: float = 2.0
    dwell: float = 0.5
    return_mode: int = 98

    def validate(self):
        if self.cycle not in CYCLES or self.return_mode not in (98, 99):
            raise ValueError(tr('Invalid drilling cycle or return mode.'))
        if not 1 <= len(self.holes) <= 1000:
            raise ValueError(tr('Enter between 1 and 1000 hole positions.'))
        if any(len(point) != 2 for point in self.holes):
            raise ValueError(tr('Enter X and Y for each hole.'))
        values = (
            self.depth,
            self.retract,
            self.clearance,
            self.feed,
            self.peck,
            self.dwell,
            *(value for point in self.holes for value in point),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError(tr('Enter finite numeric values.'))
        if self.depth >= self.retract:
            raise ValueError(tr('Hole bottom Z must be below the retract plane R.'))
        if self.clearance < self.retract:
            raise ValueError(tr('Clearance Z must be at or above the retract plane R.'))
        if self.feed <= 0:
            raise ValueError(tr('Feed rate F must be greater than zero.'))
        if self.cycle in (73, 83):
            if self.peck <= 0 or self.retract - self.peck >= self.retract:
                raise ValueError(tr('Peck depth Q must be greater than zero.'))
            pecks = (self.retract - self.depth) / self.peck
            if pecks > MAX_PECKS or pecks * len(self.holes) > 25000:
                raise ValueError(tr('Too many pecks. Increase Q or reduce the number of holes.'))
        if self.cycle == 82 and self.dwell <= 0:
            raise ValueError(tr('Dwell P must be greater than zero for G82.'))


def insertion_context(source, position):
    """Insert before the cursor's source line; never replace selected code."""
    position = min(max(int(position), 0), len(source))
    start = source.rfind('\n', 0, position) + 1
    result = preview(source[:start])
    if result.error:
        raise ValueError(tr('Correct the preceding lines: {value1}').format(value1=result.error))
    context = result.states[-1] if result.states else None
    if context and context.ended:
        raise ValueError(tr('Move the cursor before M2/M30 or the closing % line.'))
    if context and context.modal_motion in CYCLES:
        raise ValueError(tr("Move the cursor after the current cycle's G80 line."))
    return start, context


def build_block(spec, context=None):
    spec.validate()
    if context is not None and context.ended:
        raise ValueError(tr('Cannot insert a cycle after the program end.'))
    if context is not None and context.modal_motion in CYCLES:
        raise ValueError(tr('End the current cycle with G80 first.'))
    try:
        import FreeCAD as App
        import Part
        import Path
        from Path.Base.Generator import drill
    except ImportError as error:
        raise ValueError(tr('Could not load the FreeCAD drilling generator.')) from error
    lines = [
        '(Drilling cycle)',
        'G21 G90 G17',
        f'G0 Z{format_number(spec.clearance)}',
        f'G{spec.return_mode}',
    ]
    for x, y in spec.holes:
        edge = Part.makeLine(App.Vector(x, y, spec.clearance), App.Vector(x, y, spec.depth))
        commands = drill.generate(
            edge,
            dwelltime=float(spec.dwell if spec.cycle == 82 else 0),
            peckdepth=float(spec.peck if spec.cycle in (73, 83) else 0),
            retractheight=float(spec.retract),
            chipBreak=spec.cycle == 73,
        )
        if len(commands) != 1 or commands[0].Name != f'G{spec.cycle}':
            raise ValueError(tr('FreeCAD could not generate the selected drilling cycle.'))
        params = dict(commands[0].Parameters, F=spec.feed)
        lines.append(Path.Command(commands[0].Name, params).toGCode().strip())
    lines.extend(['G80', f'G0 Z{format_number(spec.clearance)}'])
    # Preserve the program's units, distance mode, plane, return mode and feed.
    # Positions intentionally end at the last hole, at the explicit safe Z.
    if context is not None:
        scale = context.scale
        restore = [
            f'G{20 if scale == 25.4 else 21}',
            f'G{90 if context.absolute else 91}',
            f'G{context.plane}',
            f'G{context.retract_mode}',
        ]
        if context.modal_motion in (0, 1, 2, 3):
            restore.append(f'G{context.modal_motion}')
        if context.feed is not None:
            restore.append('F' + format_number(context.feed / scale))
        lines.append(' '.join(restore))
    lines.append('(End drilling cycle)')
    text = '\n'.join(lines) + '\n'
    checked = preview(text)
    if checked.error:
        raise ValueError(str(checked.error))
    return text
