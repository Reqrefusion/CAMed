"""Modal G-code state with separate mode, machine, cycle and motion handlers."""

from .i18n import tr
import math
import re
from dataclasses import dataclass, field
from .drill_cycles import CYCLES
from .gcode_model import BlockState, is_motion_line
from .gcode_geometry import arc_center
from .gcode_syntax import (
    BLOCK_DELETE,
    CodeError,
    MODAL_GROUPS,
    parse_words,
    validate_commands,
    strip_comments,
    format_number,
)

KINDS = {
    "(blank or comment)": tr('Comment / blank'),
    "(after program end)": tr('Program end'),
    "(dwell; geometry unchanged)": tr('G4 · Dwell'),
    "(program delimiter or number)": tr('Program header'),
    "(program number)": tr('Program header'),
}


@dataclass
class ProgramState:
    tool: object = None
    selected_tool: object = None
    tool_numbers: object = None
    notices: list = field(default_factory=list)
    missing_tools: set = field(default_factory=set)
    position: dict = field(default_factory=lambda: dict(X=0.0, Y=0.0, Z=0.0))
    motion: object = None
    cycle_parameters: dict = field(default_factory=dict)
    cycle_initial_z: float = 0.0
    retract_mode: int = 98
    absolute: bool = True
    absolute_center: bool = False
    plane: int = 17
    scale: float = 1.0
    feed: object = None
    spindle: object = None
    spindle_mode: object = None
    work_system: object = None
    moved: bool = False
    percent_open: bool = False
    ended: bool = False
    display_tool: object = None

    def __post_init__(self):
        if self.tool_numbers is not None and self.tool_numbers.get(self.tool, 0) == 1:
            self.display_tool = self.tool

    def notice(self, message):
        if message not in self.notices:
            self.notices.append(message)

    def snapshot(self, line, number):
        command = line.split()[0] if is_motion_line(line) else None
        return BlockState(
            source_line=number,
            position=tuple(self.position[axis] for axis in "XYZ"),
            motion=command,
            feed=self.feed,
            spindle=self.spindle,
            spindle_mode=self.spindle_mode,
            tool=self.tool,
            selected_tool=self.selected_tool,
            kind=KINDS.get(line, tr('Setup')),
            scale=self.scale,
            absolute=self.absolute,
            plane=self.plane,
            retract_mode=self.retract_mode,
            modal_motion=self.motion,
            ended=self.ended,
            display_tool=self.display_tool,
        )

    def header(self, code, number):
        if not code:
            return "(blank or comment)"
        if re.fullmatch(r"%\d*", code):
            if code != "%" and self.moved:
                raise CodeError(number, tr('Multiple program headers are not supported in one preview.'))
            if code == "%" and self.percent_open:
                self.ended = True
            self.percent_open = True
            return "(program delimiter or number)"
        if re.fullmatch(r"O\s*\d+", code):
            return "(program number)"
        return None

    def apply_modes(self, values, gcodes, number):
        self._apply_work_coordinates(gcodes, number)
        # Mode changes take effect on this block, independent of textual order.
        if 20 in gcodes:
            self.scale = 25.4
        if 21 in gcodes:
            self.scale = 1.0
        if 90 in gcodes:
            self.absolute = True
        if 91 in gcodes:
            self.absolute = False
        if 90.1 in gcodes:
            self.absolute_center = True
        if 91.1 in gcodes:
            self.absolute_center = False
        for g in gcodes:
            if g in (17, 18, 19):
                self.plane = int(g)
        for gcode in gcodes:
            self._set_motion_mode(gcode)
        if "F" in values:
            self.feed = values["F"] * self.scale
            if not math.isfinite(self.feed):
                raise CodeError(number, tr('Feed rate F must remain finite after unit conversion.'))

    def _apply_work_coordinates(self, gcodes, number):
        for gcode in gcodes:
            if MODAL_GROUPS[gcode] == "work":
                if self.moved and (self.work_system or 54) != gcode:
                    raise CodeError(
                        number, tr('Changing the work coordinate system requires an offset table.')
                    )
                self.work_system = gcode
                self.notice(
                    tr(
                        'G{value1} work coordinates are shown as stock coordinates. Machine offsets are not applied.'
                    ).format(value1=int(gcode))
                )

    def _set_motion_mode(self, gcode):
        if gcode in (0, 1, 2, 3, 80):
            self.motion = None if gcode == 80 else int(gcode)
            self.cycle_parameters = {}
        elif gcode in CYCLES:
            if self.motion != int(gcode):
                self.cycle_parameters.pop("Q", None)
                self.cycle_parameters.pop("P", None)
            if self.motion not in CYCLES:
                self.cycle_initial_z = self.position["Z"]
                self.cycle_parameters = {}
            self.motion = int(gcode)
        elif gcode in (98, 99):
            self.retract_mode = int(gcode)

    def apply_machine(self, values, gcodes, mcodes, number):
        if "S" in values:
            self.spindle = values["S"]
        for m in mcodes:
            if m in (3, 4, 5):
                self.spindle_mode = int(m)
        if "T" in values:
            self.selected_tool = int(values["T"])
            if self.tool_numbers is not None and self.selected_tool not in self.tool_numbers:
                self.note_missing_tool(self.selected_tool, number)
        if 6 in mcodes:
            if self.tool_numbers is not None:
                if self.tool_numbers.get(self.selected_tool, 0) > 1:
                    raise CodeError(
                        number,
                        tr(
                            'T{value1} is assigned to multiple tool controllers. Use unique numbers.'
                        ).format(value1=self.selected_tool),
                    )
            self.tool = self.selected_tool
            if self.tool_numbers is not None and self.tool_numbers.get(self.tool, 0) == 1:
                self.display_tool = self.tool
        if 43 in gcodes:
            self.notice(
                tr(
                    'G43/H tool length information is read. The preview shows programmed tool tip coordinates.'
                )
            )
        if "H" in values and 43 not in gcodes:
            raise CodeError(number, tr('Use the tool length offset H with G43.'))
        if "D" in values and 40 not in gcodes:
            raise CodeError(number, tr('Tool radius offset D is not applied in the preview.'))

    def is_dwell(self, values, gcodes, number):
        if 4 in gcodes and any(g in CYCLES for g in gcodes):
            raise CodeError(number, tr('Do not combine G4 and a drilling cycle in the same line.'))
        if 4 not in gcodes:
            return False
        if (
            set(values) - set("PX")
            or not set(values).intersection("PX")
            or len(values) != 1
            or min(values.values()) < 0
        ):
            raise CodeError(number, tr('G4 requires one non-negative P or X dwell value.'))
        return True

    def is_cycle(self, values, gcodes):
        return self.motion in CYCLES and bool(
            set(values).intersection("XYZRQP") or any(g in CYCLES for g in gcodes)
        )

    def note_missing_tool(self, tool, line):
        if tool in self.missing_tools:
            return
        self.missing_tools.add(tool)
        if tool is None:
            message = tr('No initial tool is defined for the move on line {line}.').format(line=line)
        else:
            message = tr('T{tool} is not defined in this job (line {line}).').format(tool=tool, line=line)
        self.notice(message)

    def check_tool(self, number):
        if self.tool_numbers is None:
            return
        count = self.tool_numbers.get(self.tool, 0)
        if count == 0:
            self.note_missing_tool(self.tool, number)
        elif count > 1:
            raise CodeError(
                number,
                tr('T{value1} is assigned to multiple tool controllers. Use unique numbers.').format(
                    value1=self.tool
                ),
            )

    def cycle_commands(self, values, gcodes, number):
        if "Q" in values and self.motion not in (73, 83):
            raise CodeError(number, tr('Use Q only with G73/G83.'))
        if "P" in values and self.motion != 82:
            raise CodeError(number, tr('Cycle dwell P is supported only with G82.'))
        if self.plane != 17:
            raise CodeError(number, tr('Drilling cycles are supported only in the G17/XY plane.'))
        if not self.absolute:
            raise CodeError(
                number, tr('Use G90 for drilling cycles. Incremental G91 cycles are not supported.')
            )
        if set(values).intersection("IJHD") or 4 in gcodes:
            raise CodeError(number, tr('Unsupported drilling cycle parameter.'))
        self.check_tool(number)
        for key in "ZRQ":
            if key in values:
                self.cycle_parameters[key] = values[key] * self.scale
        if "P" in values:
            self.cycle_parameters["P"] = values["P"]
        if not {"Z", "R"} <= self.cycle_parameters.keys() or self.feed is None:
            raise CodeError(number, tr('The first drilling cycle requires Z, R and a positive F.'))
        params = dict(
            self.cycle_parameters,
            X=values.get("X", self.position["X"] / self.scale) * self.scale,
            Y=values.get("Y", self.position["Y"] / self.scale) * self.scale,
            F=self.feed,
        )
        try:
            from .drill_cycles import expand

            expanded = expand(self.motion, params, self.position, self.cycle_initial_z, self.retract_mode)
        except (ValueError, RuntimeError, KeyError, OverflowError) as error:
            raise CodeError(number, str(error)) from error
        return expanded

    def motion_line(self, values, gcodes, number):
        if "Q" in values:
            raise CodeError(number, tr('Use Q only in G73/G83 drilling cycles.'))
        if "P" in values:
            # Path blending changes controller execution, not the programmed vertices.
            if 64 not in gcodes or values["P"] < 0:
                raise CodeError(number, tr('Parameter P is supported only with G4/G64.'))
        has_axes = bool(set(values).intersection("XYZ"))
        has_center = bool(set(values).intersection("IJR"))
        output = None
        if has_axes or has_center:
            self.check_tool(number)
            if self.motion is None:
                raise CodeError(
                    number, tr('Start motion with G0/G1/G2/G3 before using modal XYZ coordinates.')
                )
            if self.motion < 2 and has_center:
                raise CodeError(number, tr('Use I/J/R only with G2/G3 arcs.'))
            end = dict(self.position)
            output_values = {}
            for axis in "XYZ":
                if axis in values:
                    end[axis] = values[axis] * self.scale + (0 if self.absolute else self.position[axis])
                    output_values[axis] = end[axis]
            if not all(math.isfinite(value) for value in end.values()):
                raise CodeError(
                    number, tr('Coordinates must remain finite after unit and position conversion.')
                )
            if self.motion in (2, 3):
                center = arc_center(
                    self.position,
                    end,
                    values,
                    self.motion,
                    self.plane,
                    self.scale,
                    self.absolute_center,
                    number,
                )
                output_values.update(center)
            if self.feed is not None and (self.motion != 0 or "F" in values):
                output_values["F"] = self.feed
            output = f"G{self.motion} " + " ".join(
                f"{key}{format_number(value)}" for key, value in output_values.items()
            )
            self.position = end
            self.moved = True
        return output or "(mode or machine metadata; geometry unchanged)"

    def end_program(self, mcodes):
        if 2 in mcodes or 30 in mcodes:
            self.ended = True
            self.spindle_mode = 5

    def block(self, original, number):
        if self.ended:
            yield "(after program end)"
            return
        code = re.sub(r"\s+", "", strip_comments(original, number))
        header = self.header(code, number)
        if header is not None:
            yield header
            return
        if code.startswith("/"):
            code = BLOCK_DELETE.sub('', code, count=1)
            self.notice(
                tr('Block delete is assumed off. Lines starting with / are included in the preview.')
            )
        values, gcodes, mcodes = parse_words(code, number)
        if not values and not gcodes and not mcodes:
            yield "(line number)"
            return
        validate_commands(gcodes, mcodes, number)
        self.apply_modes(values, gcodes, number)
        self.apply_machine(values, gcodes, mcodes, number)
        if self.is_dwell(values, gcodes, number):
            output = "(dwell; geometry unchanged)"
        elif self.is_cycle(values, gcodes):
            commands = self.cycle_commands(values, gcodes, number)
            self.end_program(mcodes)
            for command, params in commands:
                if command == "G4":
                    yield "(dwell; geometry unchanged)"
                    continue
                self.position.update({key: value for key, value in params.items() if key in "XYZ"})
                self.moved = True
                yield (
                    command
                    + " "
                    + " ".join(f"{key}{format_number(value)}" for key, value in params.items())
                )
            return
        else:
            output = self.motion_line(values, gcodes, number)
        self.end_program(mcodes)
        yield output
