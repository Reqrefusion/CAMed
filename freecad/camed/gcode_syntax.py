"""G-code words, syntax diagnostics and modal-group checks; no FreeCAD dependency."""

from .i18n import tr
import math
import re
from .drill_cycles import CYCLES

BLOCK_DELETE = re.compile(r'^/(?:[1-9](?=[A-Za-z]))?')
WORD = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


class CodeError(ValueError):
    def __init__(self, line, message):
        self.line = line
        super().__init__(tr('Line {line}: {message}').format(line=line, message=message))


def strip_comments(original, number):
    result = []
    depth = 0
    for char in original:
        if char == ";" and depth == 0:
            break
        if char == "(":
            depth += 1
        elif char == ")":
            if not depth:
                raise CodeError(number, tr('Unmatched comment parenthesis.'))
            depth -= 1
        elif not depth:
            result.append(char)
    if depth:
        raise CodeError(number, tr('Unclosed comment parenthesis.'))
    return "".join(result).strip().upper().lstrip("\ufeff")


def code_mask(line):
    """Keep source offsets while hiding comments from hover token lookup."""
    result, depth, semicolon = [], 0, False
    for char in line:
        if char == ';' and not depth:
            semicolon = True
        if char == '(':
            depth += 1
            result.append(' ')
        elif char == ')':
            depth = max(0, depth - 1)
            result.append(' ')
        else:
            result.append(' ' if depth or semicolon else char)
    return ''.join(result)


def format_number(value):
    # Native Command parsing must not receive an E word from scientific notation.
    if value == 0:
        return "0"
    return f"{value:.12f}".rstrip("0").rstrip(".")


MODAL_GROUPS = {
    0: "motion",
    1: "motion",
    2: "motion",
    3: "motion",
    80: "motion",
    **{g: "motion" for g in CYCLES},
    17: "plane",
    18: "plane",
    19: "plane",
    20: "units",
    21: "units",
    90: "distance",
    91: "distance",
    90.1: "center",
    91.1: "center",
    40: "radius_comp",
    41: "radius_comp",
    42: "radius_comp",
    43: "length_comp",
    49: "length_comp",
    94: "feed_mode",
    54: "work",
    55: "work",
    56: "work",
    57: "work",
    58: "work",
    59: "work",
    61: "path_mode",
    61.1: "path_mode",
    64: "path_mode",
    98: "retract",
    99: "retract",
    4: "nonmodal",
}


def parse_words(code, number):
    words = list(WORD.finditer(code))
    if WORD.sub("", code).strip():
        raise CodeError(number, tr('Incomplete word or unsupported expression/macro syntax.'))
    if words and words[0][1] == "N":
        n = float(words.pop(0)[2])
        if not n.is_integer() or n < 0:
            raise CodeError(number, tr('Line numbers must be non-negative integers.'))
    values = {}
    gcodes, mcodes = [], []
    for word in words:
        letter, value = word[1], float(word[2])
        if not math.isfinite(value):
            raise CodeError(number, tr('Enter finite numbers.'))
        if letter == "G":
            gcodes.append(value)
        elif letter == "M":
            mcodes.append(value)
        elif letter in values:
            raise CodeError(number, tr('Repeated {letter} parameter.').format(letter=letter))
        else:
            values[letter] = value
    if set(values) - set("XYZIJRFTSHDPQ"):
        raise CodeError(
            number,
            tr(
                'The preview supports 3-axis XYZ milling. Additional axes and parameters are not supported.'
            ),
        )
    for letter in "THD":
        if letter in values and (values[letter] < 0 or not values[letter].is_integer()):
            raise CodeError(number, tr('{letter} must be a non-negative integer.').format(letter=letter))
    if "S" in values and values["S"] < 0:
        raise CodeError(number, tr('Spindle speed S cannot be negative.'))
    if "F" in values and values["F"] <= 0:
        raise CodeError(number, tr('Feed rate F must be positive.'))
    return values, gcodes, mcodes


def validate_commands(gcodes, mcodes, number):
    seen = set()
    for g in gcodes:
        group = MODAL_GROUPS.get(g)
        if group is None:
            raise CodeError(
                number,
                tr('G{value1} is not supported in the preview. This is not a syntax error.').format(
                    value1=format_number(g)
                ),
            )
        if group in seen:
            raise CodeError(number, tr('Multiple G commands in the same modal group.'))
        seen.add(group)
        if g in (41, 42):
            raise CodeError(number, tr('G41/G42 cutter compensation requires tool and offset information.'))
    allowed_m = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 19, 30, 48, 49}
    if any(m not in allowed_m for m in mcodes):
        raise CodeError(
            number,
            tr('This M command is not supported. Subprogram or machine functions have not been skipped.'),
        )
    if len(set(mcodes)) != len(mcodes):
        raise CodeError(number, tr('Repeated M command.'))
    if any(len(set(mcodes).intersection(group)) > 1 for group in ({0, 1, 2, 30}, {3, 4, 5}, {48, 49})):
        raise CodeError(number, tr('Conflicting M commands in the same group.'))
