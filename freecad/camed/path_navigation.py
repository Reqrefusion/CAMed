"""Map FreeCAD's native Path selection command numbers back to source lines."""

import re
from .gcode_model import MOTION_COMMANDS


def command_sources(operation, lines, sources):
    """Require an exact contiguous native command sequence; never guess an edge."""
    import Path

    expected = [Path.Command(line).toGCode() for line in lines]
    commands = list(operation.Path.Commands)
    actual = [command.toGCode() for command in commands]
    if not expected or len(expected) != len(sources):
        return {}
    # Linear sequence matching also handles very large repetitive programs.
    prefix = [0] * len(expected)
    j = 0
    for i in range(1, len(expected)):
        while j and expected[i] != expected[j]:
            j = prefix[j - 1]
        if expected[i] == expected[j]:
            j += 1
        prefix[i] = j
    matches, j = [], 0
    for i, command in enumerate(actual):
        while j and command != expected[j]:
            j = prefix[j - 1]
        if command == expected[j]:
            j += 1
        if j == len(expected):
            matches.append(i - j + 1)
            if len(matches) > 1:
                return {}
            j = prefix[j - 1]
    if len(matches) != 1:
        return {}
    start = matches[0]
    return {
        start + i + 1: source
        for i, source in enumerate(sources)
        if source is not None and commands[start + i].Name in MOTION_COMMANDS
    }


def build_map(anchor, job, result):
    from .tool_backend import operations, section_records

    chunks = section_records(result)
    current = operations(anchor, job) if job is not None else [anchor]
    if len(chunks) != len(current):
        return {}
    return {
        op.Name: command_sources(op, lines, sources) for op, (_, lines, sources) in zip(current, chunks)
    }


class PathSelection:
    def __init__(self, owner):
        self.owner = owner
        self.mapping = {}
        self.source = None
        self.attached = False

    def attach(self):
        if not self.attached:
            import FreeCADGui as Gui

            if hasattr(Gui, 'Selection'):
                Gui.Selection.addObserver(self)
                self.attached = True

    def detach(self, *args):
        if self.attached:
            import FreeCADGui as Gui

            Gui.Selection.removeObserver(self)
            self.attached = False

    def refresh(self, source, result):
        self.mapping = {}
        self.commands = {}
        try:
            self.mapping = build_map(self.owner.operation, self.owner.job, result)
            from .tool_backend import operations

            current = (
                operations(self.owner.operation, self.owner.job)
                if self.owner.job
                else [self.owner.operation]
            )
            self.commands = {op.Name: tuple(c.toGCode() for c in op.Path.Commands) for op in current}
        except (ValueError, RuntimeError, AttributeError):
            # Navigation is optional; unsupported native layouts leave the path usable.
            self.mapping = {}
        self.source = source

    def addSelection(self, document, obj, sub, point):
        owner = self.owner
        import FreeCADGui as Gui

        if (
            not owner.enabled
            or owner.shutting_down
            or not owner.is_current()
            or owner.timer.isActive()
            or getattr(owner, 'preview_failed', False)
            or getattr(owner, 'applying_program', False)
            or getattr(owner, 'resource_depth', 0)
            or Gui.Control.activeDialog()
            or getattr(owner.document, 'HasPendingTransaction', False) is True
            or document != owner.document.Name
            or owner.editor.toPlainText() != self.source
        ):
            return
        # ViewProviderPath::getElement returns '<1-based command> <G-code>'.
        match = re.fullmatch(r'(\d+)(?:\s+.*)?', sub)
        if match:
            source = self.mapping.get(obj, {}).get(int(match[1]))
            if source is not None:
                operation = owner.document.getObject(obj)
                if operation is None or tuple(
                    c.toGCode() for c in operation.Path.Commands
                ) != self.commands.get(obj):
                    return
                from .inspection_tool import goto_line

                goto_line(owner, source)
