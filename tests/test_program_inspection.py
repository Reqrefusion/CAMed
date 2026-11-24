import unittest
from freecad.camed.program_inspection import sections, token_help


class NavigationHelpTests(unittest.TestCase):
    def test_headings_ignore_inline_notes_and_keep_physical_line_numbers(self):
        self.assertEqual(
            sections('(KABA)\nG1 X10 (kes)\nN30 (DELİKLER)\n/1 N40 ; FINISH\n(---)\n()'),
            [(1, 'KABA'), (3, 'DELİKLER'), (4, 'FINISH')],
        )

    def test_hover_uses_original_offsets_with_spaces_and_lowercase(self):
        self.assertIn('G83', token_help('  g 83 X10', 5))
        self.assertIn('X10', token_help('  g 83 X10', 8))

    def test_hover_never_interprets_comments_as_code(self):
        for text in ('(G83 Q1)', '; G83 Q1', 'G1 (G83) ; Q1'):
            self.assertIsNone(token_help(text, text.index('G83')))
        self.assertIsNone(token_help('G1 X10', 99))
