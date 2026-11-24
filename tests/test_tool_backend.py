import sys
import types
import unittest
from unittest.mock import patch
from freecad.camed.validation import preview
from freecad.camed.tool_backend import update_operations


def operation(name):
    return types.SimpleNamespace(
        Name=name,
        Label=name,
        Gcode=[],
        ViewObject=types.SimpleNamespace(),
        addProperty=lambda *args: None,
        touch=lambda: None,
        LiveEditorSource='original full source',
    )


class ToolBackendTests(unittest.TestCase):
    def setUp(self):
        self.anchor = operation('Main')
        self.other = operation('Other')
        self.controllers = [types.SimpleNamespace(ToolNumber=i) for i in (1, 6, 8)]
        self.job = types.SimpleNamespace(
            Tools=types.SimpleNamespace(Group=self.controllers),
            Operations=types.SimpleNamespace(Group=[self.other, self.anchor]),
        )
        self.deleted = []

        def remove(name):
            self.deleted.append(name)
            self.job.Operations.Group = [o for o in self.job.Operations.Group if o.Name != name]

        self.doc = types.SimpleNamespace(removeObject=remove)
        self.anchor.Document = self.doc

        def create(name, parentJob):
            op = operation(name + str(len(parentJob.Operations.Group)))
            op.Document = self.doc
            parentJob.Operations.Group.append(op)
            return op

        native = types.ModuleType("freecad.camed.native_program")
        native.create = lambda job, name: create(name, job)
        native.write = lambda op, lines: setattr(op, "Gcode", lines)
        self.modules = {"freecad.camed.native_program": native}

    def update(self, source):
        result = preview(source, {1: 1, 6: 1, 8: 1}, 1)
        with patch.dict(sys.modules, self.modules):
            return update_operations(self.anchor, self.job, result)

    def test_sections_bind_native_controllers_preserve_source_and_other_operations(self):
        ops = self.update('T6 M6\nG0 Z10\nT8 M6\nG1 X20 F100')
        self.assertIs(ops[0], self.anchor)
        self.assertIs(ops[0].ToolController, self.controllers[1])
        self.assertIs(ops[1].ToolController, self.controllers[2])
        self.assertIs(ops[1].CAMEditorProgram, self.anchor)
        self.assertEqual(self.job.Operations.Group, [self.other] + ops)
        self.assertEqual(self.anchor.LiveEditorSource, 'original full source')

    def test_edit_reuses_and_then_removes_old_sections(self):
        first = self.update('T6 M6\nG0 Z10\nT8 M6\nG1 X20 F100')
        second = self.update('T6 M6\nG0 Z20\nT8 M6\nG1 X30 F100')
        self.assertIs(first[1], second[1])
        self.assertEqual(self.deleted, [])
        last = self.update('T6 M6\nG0 Z20')
        self.assertEqual(last, [self.anchor])
        self.assertEqual(self.deleted, [first[1].Name])
        self.assertEqual(self.job.Operations.Group, [self.other, self.anchor])

    def test_unknown_tool_uses_previous_controller_and_keeps_later_path(self):
        self.update('T6 M6\nG0 Z10\nT8 M6\nG1 X20 F100')
        last = self.update('T6 M6\nG0 Z10\nT99 M6\nG1 X50')
        self.assertEqual(len(last), 2)
        self.assertIs(last[1].ToolController, self.controllers[1])
        self.assertEqual(last[1].Gcode[-1], 'G1 X50')
        self.assertEqual(last[1].Label, 'G-code · T99')

    def test_reparse_does_not_inherit_generated_first_section_tool(self):
        from freecad.camed.program_backend import parse_program

        self.anchor.CAMEditorInitialTool = None
        self.anchor.ToolController = None
        result, _ = parse_program(self.anchor, self.job, 'T6 M6\nG1 X10 F100')
        with patch.dict(sys.modules, self.modules):
            update_operations(self.anchor, self.job, result)
        self.assertEqual(self.anchor.ToolController.ToolNumber, 6)
        result, initial = parse_program(self.anchor, self.job, 'G1 X5 F100\nT6 M6\nG1 X10')
        self.assertIsNone(initial)
        self.assertIsNone(result.states[0].display_tool)
        self.assertTrue(result.can_simulate)
        del self.anchor.CAMEditorInitialTool
        _, initial = parse_program(self.anchor, self.job, 'G0 X1')
        self.assertIs(initial, self.controllers[1])

    def test_deleted_controller_references_are_not_used(self):
        from freecad.camed.tool_backend import controllers

        alive = types.SimpleNamespace(Name='Alive')
        removed = types.SimpleNamespace(Name='Removed')
        doc = types.SimpleNamespace(getObject=lambda name: alive if name == 'Alive' else None)
        alive.Document = doc
        removed.Document = doc
        self.job.Tools.Group = [alive, removed, None]
        self.assertEqual(controllers(self.job), [alive])
