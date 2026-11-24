import types
import unittest
from freecad.camed.program_documents import initialize_program, bind_path


class ProgramDocumentTests(unittest.TestCase):
    def fresh(self):
        return types.SimpleNamespace(
            Document=types.SimpleNamespace(Label='Original', FileName='project.FCStd'),
            Label='G-code',
            addProperty=lambda *args: None,
        )

    def test_initialize_sets_source_path_and_program_label_without_renaming_document(self):
        operation = self.fresh()
        initialize_program(operation, 'G1 X10 F100', filename='part.nc')
        self.assertEqual(operation.LiveEditorSource, 'G1 X10 F100')
        self.assertEqual(operation.Gcode, ['G1 X10 F100'])
        self.assertEqual(operation.Label, 'part.nc')
        self.assertTrue(operation.CAMEditorGCodePath.endswith('part.nc'))
        self.assertEqual(operation.Document.Label, 'Original')
        self.assertEqual(operation.Document.FileName, 'project.FCStd')

    def test_existing_source_even_when_empty_cannot_be_overwritten(self):
        for source in ('', 'G1 X10 F100'):
            operation = self.fresh()
            operation.LiveEditorSource = source
            with self.assertRaises(ValueError):
                initialize_program(operation, 'G1 X99 F100', filename='other.nc')
            self.assertEqual(operation.LiveEditorSource, source)
            self.assertEqual(operation.Label, 'G-code')
            self.assertFalse(hasattr(operation, 'CAMEditorGCodePath'))

    def test_explicit_new_document_label_and_prepared_path_are_supported(self):
        operation = self.fresh()
        result = types.SimpleNamespace(lines=['G1 X20 F100'])
        initialize_program(operation, 'source', result=result, document_label='Contour · NC')
        self.assertEqual(operation.Gcode, result.lines)
        self.assertEqual(operation.Document.Label, 'Contour · NC')
        self.assertFalse(hasattr(operation, 'CAMEditorGCodePath'))

    def test_binding_a_save_target_does_not_change_source_or_labels(self):
        operation = self.fresh()
        operation.LiveEditorSource = 'G0 Z5'
        bind_path(operation, 'copy.nc')
        self.assertEqual(operation.LiveEditorSource, 'G0 Z5')
        self.assertEqual(operation.Label, 'G-code')
        self.assertEqual(operation.Document.Label, 'Original')
