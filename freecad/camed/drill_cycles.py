"""Adapt normalized source cycles to FreeCAD's own drill-cycle expander."""

from .i18n import tr
import math

CYCLES = (73, 81, 82, 83)
MAX_PECKS = 10000


def expand(cycle, params, position, initial_z, retract_mode):
    if not all(math.isfinite(v) for v in (*position.values(), *params.values(), initial_z)):
        raise ValueError(tr('Drilling cycle values must be finite.'))
    if params['R'] <= params['Z']:
        raise ValueError(tr('Drilling depth Z must be below the retract plane R.'))
    if params['F'] <= 0:
        raise ValueError(tr('Drilling requires a positive feed rate F.'))
    if cycle in (73, 83):
        q = params.get('Q', 0)
        if q <= 0 or params['R'] - q >= params['R']:
            raise ValueError(tr('G73/G83 requires a positive, measurable peck depth Q.'))
        if (params['R'] - params['Z']) / q > MAX_PECKS:
            raise ValueError(tr('The cycle exceeds 10000 pecks. Increase Q.'))
    if params.get('P', 0) < 0:
        raise ValueError(tr('Dwell P cannot be negative.'))
    try:
        import Path
        from Path.Base.MachineState import MachineState
        from Path.Post.DrillCycleExpander import DrillCycleExpander
    except ImportError as error:
        raise ValueError(tr('This FreeCAD version does not support drilling cycle preview.')) from error
    # Explicit initial plane makes G98 consistent over modal hole repetitions.
    start = dict(position)
    start.update(F=params['F'], G0F=None, ReturnMode='R')
    state = MachineState(start)
    engine = DrillCycleExpander(state)
    commands = engine.expand_command(Path.Command(f'G{cycle}', dict(params)), strict=False)
    if not commands:
        raise ValueError(tr('FreeCAD could not expand the drilling cycle.'))
    result = []
    for command in commands:
        name = command.Name
        if name not in ('G0', 'G1', 'G4'):
            raise ValueError(tr('FreeCAD generated an unexpected cycle motion: {name}').format(name=name))
        values = {
            k: float(v)
            for k, v in command.Parameters.items()
            if k in ('X', 'Y', 'Z') or (name == 'G1' and k == 'F')
        }
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError(tr('FreeCAD returned invalid cycle coordinates.'))
        result.append((name, values))
    final_z = max(initial_z, params['R']) if retract_mode == 98 else params['R']
    last_z = next((values['Z'] for name, values in reversed(result) if 'Z' in values), position['Z'])
    if final_z != last_z:
        result.append(('G0', {'X': params['X'], 'Y': params['Y'], 'Z': final_z}))
    return result
