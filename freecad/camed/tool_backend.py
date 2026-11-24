"""Bind native CAM controllers to consecutive G-code tool sections."""

from .gcode_model import is_motion_line, position_words
from collections import Counter


# Upper bound of the native ToolController's ToolNumber property.
MAX_TOOL_NUMBER = 10000


def controllers(job):
    current = []
    for tc in list(job.Tools.Group):
        if tc is None:
            continue
        try:
            doc = getattr(tc, "Document", None)
            if doc is not None and doc.getObject(tc.Name) is not tc:
                continue
            current.append(tc)
        except (RuntimeError, ReferenceError):
            continue
    return current


def tool_numbers(job):
    return dict(Counter(int(tc.ToolNumber) for tc in controllers(job)))


def sections(result):
    return [(number, lines) for number, lines, _ in section_records(result)]


def section_records(result):
    """Native section lines with source provenance; synthetic prefixes have none."""
    groups = []
    states = getattr(result, 'states', [])
    position = dict(X=0.0, Y=0.0, Z=0.0)
    for index, (line, number) in enumerate(zip(result.lines, result.tools)):
        if not groups or groups[-1][0] != number:
            prefix = []
            if groups:
                prefix = ["G0 " + " ".join(f"{k}{v:.12f}" for k, v in position.items())]
            groups.append((number, prefix, [None] * len(prefix)))
        groups[-1][1].append(line)
        groups[-1][2].append(states[index].source_line if index < len(states) else index + 1)
        if is_motion_line(line):
            position.update(position_words(line))
    # A positioning prefix alone is not a program move. Remove sections that
    # merely select tools before the first actual move or between changes.
    useful = [
        (number, lines, sources)
        for number, lines, sources in groups
        if any(source is not None and is_motion_line(line) for line, source in zip(lines, sources))
    ]
    return useful or [
        (
            result.tools[0] if result.tools else None,
            result.lines,
            [states[i].source_line if i < len(states) else i + 1 for i in range(len(result.lines))],
        )
    ]


def operations(anchor, job):
    return [anchor] + [op for op in job.Operations.Group if getattr(op, "CAMEditorProgram", None) is anchor]


def update_operations(anchor, job, result):
    from .native_program import create, write

    doc = anchor.Document
    available = controllers(job)
    by_number = {int(tc.ToolNumber): tc for tc in available}
    chunks = section_records(result)
    states = {state.source_line: state for state in result.states}
    current = operations(anchor, job)
    while len(current) < len(chunks):
        op = create(job, "CAMedToolSection")
        op.addProperty("App::PropertyLink", "CAMEditorProgram", "CAMed")
        op.CAMEditorProgram = anchor
        current.append(op)
    for op, (number, lines, sources) in zip(current, chunks):
        # Keep native controller links without inventing source T commands.
        state = next((states[source] for source in sources if source in states), None)
        op.ToolController = by_number.get(state.display_tool if state else number)
        write(op, lines)
        op.Label = "G-code" if op is anchor else f"G-code · T{number}"
        op.Visibility = any(is_motion_line(s) for s in lines)
        op.touch()
    for op in current[len(chunks) :]:
        doc.removeObject(op.Name)
    # Keep sections adjacent in the native operation order, without changing
    # the relative order of other programs/operations in the job.
    ordered = [op for op in job.Operations.Group if op not in current]
    original = list(job.Operations.Group)
    before = sum(op not in current for op in original[: original.index(anchor)])
    ordered[before:before] = current[: len(chunks)]
    job.Operations.Group = ordered
    return current[: len(chunks)]


def fingerprint(job):
    def shape_key(tool):
        shape = getattr(tool, "Shape", None)
        native_hash = getattr(shape, "hashCode", None)
        return (
            getattr(shape, "Volume", None),
            native_hash() if callable(native_hash) else None,
            str(getattr(tool, "ToolType", "")),
        )

    return tuple(
        (
            tc.Name,
            int(tc.ToolNumber),
            str(tc.Label),
            str(tc.HorizFeed),
            str(tc.VertFeed),
            str(tc.SpindleSpeed),
            shape_key(tc.Tool),
            str(getattr(tc.Tool, "Diameter", "")),
        )
        for tc in controllers(job)
    )
