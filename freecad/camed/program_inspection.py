"""Source headings and contextual word help; no controller analyzer."""

from .i18n import tr
import re
from .gcode_syntax import WORD, code_mask, format_number


def sections(source):
    """Standalone CAM comments are navigation headings; inline notes stay inline."""
    result = []
    for number, line in enumerate(source.splitlines(), 1):
        line = re.sub(r'^\s*(?:/[1-9]?\s*)?(?:N\s*\d+\s*)?', '', line, flags=re.I)
        if line.startswith(';'):
            title = line[1:].strip()
        elif re.fullmatch(r'(?:\([^()]*\)\s*)+', line):
            title = ' · '.join(re.findall(r'\(([^()]*)\)', line)).strip()
        else:
            continue
        if title and any(c.isalnum() for c in title):
            result.append((number, title))
    return result


DESCRIPTIONS = {
    'G0': tr('Rapid positioning'),
    'G1': tr('Linear motion at feed rate F'),
    'G2': tr('Clockwise arc'),
    'G3': tr('Counterclockwise arc'),
    'G4': tr('Dwell'),
    'G17': tr('XY plane'),
    'G18': tr('XZ plane'),
    'G19': tr('YZ plane'),
    'G20': tr('Inches'),
    'G21': tr('Millimeters'),
    'G40': tr('Cancel cutter radius compensation'),
    'G43': tr('Tool length compensation'),
    'G49': tr('Cancel tool length compensation'),
    'G73': tr('Chip-breaking drilling'),
    'G80': tr('Cancel drilling cycle / motion mode'),
    'G81': tr('Drilling'),
    'G82': tr('Drilling with dwell'),
    'G83': tr('Peck drilling'),
    'G90': tr('Absolute coordinates'),
    'G91': tr('Incremental coordinates'),
    'G90.1': tr('Absolute arc center'),
    'G91.1': tr('Incremental arc center'),
    'G94': tr('Feed per minute'),
    'G98': tr("Return to the cycle's initial Z plane"),
    'G99': tr("Return to the cycle's R plane"),
    'M0': tr('Program stop'),
    'M1': tr('Optional stop'),
    'M2': tr('Program end'),
    'M30': tr('Program end'),
    'M3': tr('Spindle clockwise'),
    'M4': tr('Spindle counterclockwise'),
    'M5': tr('Stop spindle'),
    'M6': tr('Change to the preselected tool'),
    'M7': tr('Mist coolant'),
    'M8': tr('Flood coolant'),
    'M9': tr('Coolant off'),
}
PARAMETERS = {
    'X': tr('X coordinate'),
    'Y': tr('Y coordinate'),
    'Z': tr('Z coordinate'),
    'I': tr('Arc center X component'),
    'J': tr('Arc center Y component'),
    'K': tr('Arc center Z component'),
    'F': tr('Programmed feed rate'),
    'S': tr('Programmed spindle speed'),
    'T': tr('Tool preselection; M6 changes the active tool'),
    'H': tr('Tool length offset number'),
    'D': tr('Tool radius offset number'),
    'N': tr('Block number'),
    'R': tr('Arc radius or drilling cycle retract plane'),
    'Q': tr('Drilling cycle peck depth'),
    'P': tr('Dwell / tolerance parameter, depending on the command'),
}


def token_help(line, column):
    for match in WORD.finditer(code_mask(line)):
        if match.start() <= column < match.end():
            letter = match[1].upper()
            value = match[2]
            if letter in 'GM':
                try:
                    key = letter + format_number(float(value))
                except (ValueError, OverflowError):
                    return None
                detail = DESCRIPTIONS.get(key)
                if letter == 'G' and 54 <= float(value) <= 59 and float(value).is_integer():
                    detail = tr('Work coordinate system; machine offsets are not applied in the preview')
            else:
                key, detail = letter + value, PARAMETERS.get(letter)
            return f'{key}: {detail}' if detail else None
    return None
