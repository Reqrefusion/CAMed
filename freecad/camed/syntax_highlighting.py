"""Theme-aware NC word colors with per-block modal motion state."""

from itertools import groupby

from PySide import QtGui

from .drill_cycles import CYCLES
from .gcode_syntax import WORD, code_mask


MOTION_COLORS = {0: 'rapid', 1: 'linear', 2: 'clockwise', 3: 'counterclockwise'}
MOTION_COLORS.update(dict.fromkeys(CYCLES, 'cycle'))
COLORS = {
    'rapid': '#268779',
    'linear': '#367ac9',
    'clockwise': '#8956c3',
    'counterclockwise': '#bd467b',
    'cycle': '#8d7025',
    'tool': '#bb662a',
    'rate': '#49823f',
    'comment': '#748092',
    'number': '#817d8f',
}


def _luminance(color):
    channels = color.getRgbF()[:3]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))


def _readable_color(color, background_luminance):
    def contrast(candidate):
        low, high = sorted((_luminance(candidate), background_luminance))
        return (high + 0.05) / (low + 0.05)

    if contrast(color) >= 4.5:
        return color
    target = max((QtGui.QColor(0, 0, 0), QtGui.QColor(255, 255, 255)), key=contrast)
    original, endpoint = color.getRgbF()[:3], target.getRgbF()[:3]
    for step in range(1, 10):
        mixed = QtGui.QColor.fromRgbF(*(a + (b - a) * step / 10 for a, b in zip(original, endpoint)))
        if contrast(mixed) >= 4.5:
            return mixed
    return target


class NCWordHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, document, palette):
        super().__init__(document)
        # FreeCAD's CodeEditor sets this flag when it loads a file.
        self.enable = False
        self.set_palette(palette)

    def set_palette(self, palette):
        background = _luminance(palette.base().color())
        colors = dict(COLORS, command=palette.text().color().name())
        self.formats = {}
        for name, color in colors.items():
            fmt = QtGui.QTextCharFormat()
            fmt.setForeground(_readable_color(QtGui.QColor(color), background))
            if name in ('command', 'tool'):
                fmt.setFontWeight(QtGui.QFont.Bold)
            self.formats[name] = fmt
        self.rehighlight()

    def highlightBlock(self, text):
        if not self.enable:
            self.setCurrentBlockState(-1)
            return
        code = code_mask(text)
        words = [(match, match[1].upper(), float(match[2])) for match in WORD.finditer(code)]
        gcodes = {value for _, letter, value in words if letter == 'G'}
        motion = next(
            (int(value) for _, letter, value in reversed(words) if letter == 'G' and value in MOTION_COLORS),
            -1 if 80 in gcodes else self.previousBlockState(),
        )
        self.setCurrentBlockState(motion)
        coordinate_color = (
            'command' if gcodes.intersection({28, 30, 53, 92}) else MOTION_COLORS.get(motion, 'command')
        )

        # Program text offsets are Python characters. Qt formats use UTF-16 units.
        offsets = [0]
        for char in text:
            offsets.append(offsets[-1] + (2 if ord(char) > 0xFFFF else 1))
        for match, letter, value in words:
            if letter == 'G':
                category = MOTION_COLORS.get(value, 'command')
            elif letter == 'T' or (letter == 'M' and value == 6):
                category = 'tool'
            elif letter in 'XYZIJKR':
                category = coordinate_color
            elif letter in 'FS':
                category = 'rate'
            elif letter in 'NO':
                category = 'number'
            else:
                category = 'command'
            start, end = match.span()
            self.setFormat(offsets[start], offsets[end] - offsets[start], self.formats[category])

        masked = enumerate(a != b for a, b in zip(text, code))
        for is_comment, group in groupby(masked, key=lambda item: item[1]):
            if is_comment:
                start, _ = next(group)
                end = start
                for end, _ in group:
                    pass
                self.setFormat(offsets[start], offsets[end + 1] - offsets[start], self.formats['comment'])
