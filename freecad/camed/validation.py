"""Public source-to-preview API; preserve source text and valid-prefix behavior."""

from .gcode_model import BlockState, Preview
from .gcode_state import ProgramState
from .gcode_syntax import CodeError

__all__ = ("BlockState", "Preview", "CodeError", "preview", "prepare")


def preview(text, tool_numbers=None, default_tool=None):
    result = Preview([])
    try:
        result.lines.extend(
            _prepared_lines(text, result.notices, tool_numbers, default_tool, result.tools, result.states)
        )
    except CodeError as error:
        result.error = error
    return result


def prepare(text):
    return list(_prepared_lines(text))


def _prepared_lines(
    text, notices=None, tool_numbers=None, default_tool=None, tool_trace=None, state_trace=None
):
    if not text:
        return
    state = ProgramState(
        tool=default_tool,
        selected_tool=default_tool,
        tool_numbers=tool_numbers,
        notices=notices if notices is not None else [],
    )
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for number, original in enumerate(lines, 1):
        for line in state.block(original, number):
            if tool_trace is not None:
                tool_trace.append(state.tool)
            if state_trace is not None:
                state_trace.append(state.snapshot(line, number))
            yield line
