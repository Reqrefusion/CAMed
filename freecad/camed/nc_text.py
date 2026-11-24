"""Pure NC text edits; no FreeCAD or Qt dependency."""

from itertools import pairwise

from .gcode_syntax import BLOCK_DELETE, WORD, code_mask
from .i18n import tr


def _unnumbered_block(line):
    # The parser ignores comments and whitespace even inside an N word.
    # Keep original offsets so embedded comments survive the edit.
    masked = code_mask(line)
    prefix_end = 0
    while prefix_end < len(line) and (line[prefix_end].isspace() or line[prefix_end] == '\ufeff'):
        prefix_end += 1
    offsets = [i for i in range(prefix_end, len(line)) if not masked[i].isspace()]
    code = ''.join(line[i] for i in offsets)
    delete = BLOCK_DELETE.match(code)
    word_start = delete.end() if delete else 0
    if delete:
        prefix_end = offsets[word_start - 1] + 1
        while prefix_end < len(line) and line[prefix_end].isspace():
            prefix_end += 1
    prefix = line[:prefix_end]
    body = line[prefix_end:]
    code = code[word_start:]
    if not code.startswith(('N', 'n')):
        return prefix, body, code
    number = WORD.match(code)
    if number is None:
        return prefix, body, ''
    value = float(number[2])
    if value < 0 or not value.is_integer():
        return prefix, body, ''
    word_offsets = offsets[word_start:word_start + number.end()]
    gaps = (line[left + 1:right] for left, right in pairwise(word_offsets))
    comments = ''.join(gap for gap in gaps if gap.strip())
    body = line[prefix_end:word_offsets[0]] + comments + line[word_offsets[-1] + 1:].lstrip()
    return prefix, body, code[number.end():]


def renumber(source, start=10, step=10):
    """Preserve indentation and / or /1..9 block-delete prefixes."""
    if type(start) is not int or type(step) is not int or start < 0 or step <= 0:
        raise ValueError(
            tr(
                'The starting line number must be a non-negative integer and the increment a positive integer.'
            )
        )
    result = []
    number = start
    for prefix, body, code in map(_unnumbered_block, source.split('\n')):
        if code and not code.startswith(('%', 'O', 'o')):
            result.append(f'{prefix}N{number} {body}')
            number += step
        else:
            result.append(prefix + body)
    return '\n'.join(result)


def remove_numbers(source):
    """Remove leading N sequence words, preserving indentation and block delete."""
    return '\n'.join(prefix + body for prefix, body, _ in map(_unnumbered_block, source.split('\n')))
