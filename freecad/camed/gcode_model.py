"""Preview results and source-block snapshots shared by parser and UI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gcode_syntax import CodeError


MOTION_COMMANDS = ("G0", "G1", "G2", "G3")
MOTION_PREFIXES = tuple(command + " " for command in MOTION_COMMANDS)


def is_motion_line(line):
    """Recognize motion in the normalized preview stream."""
    return line.startswith(MOTION_PREFIXES)


POSITION_WORD = re.compile(r"([XYZ])([+-]?[\d.]+)")


def position_words(line):
    """XYZ values explicitly present in a normalized movement block."""
    return {axis: float(value) for axis, value in POSITION_WORD.findall(line)}


@dataclass
class BlockState:
    source_line: int
    position: tuple[float, float, float]
    motion: str | None
    feed: float | None
    spindle: float | None
    spindle_mode: int | None
    tool: int | None
    selected_tool: int | None
    kind: str
    scale: float = 1.0
    absolute: bool = True
    plane: int = 17
    retract_mode: int = 98
    modal_motion: int | None = None
    ended: bool = False
    display_tool: int | None = None


@dataclass
class Preview:
    lines: list[str]
    error: CodeError | None = None
    notices: list[str] = field(default_factory=list)
    tools: list[int | None] = field(default_factory=list)
    states: list[BlockState] = field(default_factory=list)

    @property
    def has_motion(self):
        return any(is_motion_line(line) for line in self.lines)

    @property
    def can_simulate(self):
        return self.has_motion and len(self.states) == len(self.lines)
