import unittest
from freecad.camed.nc_text import renumber, remove_numbers
from freecad.camed.validation import preview


class NCTextTests(unittest.TestCase):
    def test_numbered_block_delete_prefixes_are_preserved(self):
        for prefix in ('/', '/1', '/2', '/9'):
            with self.subTest(prefix=prefix):
                source = prefix + ' N20 G1 X10 F100'
                numbered = renumber(source)
                self.assertTrue(numbered.startswith(prefix + ' N10 '), numbered)
                self.assertIsNone(preview(numbered).error)
                self.assertEqual(preview(source).lines, preview(numbered).lines)

    def test_numbering_distinguishes_leading_comments_from_comment_only_blocks(self):
        source = 'N40 (finish) G1 X5 F100\n/1 (a (b)) N60 G1 X6\n(comment);tail\n(header) O123'
        numbered = 'N10 (finish) G1 X5 F100\n/1 N20 (a (b)) G1 X6\n(comment);tail\n(header) O123'
        self.assertEqual(renumber(source), numbered)
        self.assertEqual(renumber(numbered), numbered)
        self.assertEqual(remove_numbers(numbered), remove_numbers(source))

    def test_compact_prefixes_indentation_headers_and_comments(self):
        source = '  /1N20G1X10F100\n  N30 G0 Z5\n(comment)\n; tail\nO123\n%'
        numbered = renumber(source)
        self.assertEqual(numbered, '  /1N10 G1X10F100\n  N20 G0 Z5\n(comment)\n; tail\nO123\n%')
        self.assertEqual(preview(source).lines, preview(numbered).lines)

    def test_number_edits_preserve_moves_comments_and_delete_levels(self):
        cases = [
            ('N+40 G1 X5', 'G1 X5', 'N10 G1 X5'),
            ('N40.0 G1 X5', 'G1 X5', 'N10 G1 X5'),
            ('N4(note)0 G1 X5', '(note)G1 X5', 'N10 (note)G1 X5'),
            ('/1(note)G1 X5', '/1(note)G1 X5', '/1N10 (note)G1 X5'),
            ('/9(foo)N + 4 0.0 G1 X5', '/9(foo)G1 X5', '/9N10 (foo)G1 X5'),
            ('\ufeffN40 G1 X5', '\ufeffG1 X5', '\ufeffN10 G1 X5'),
        ]
        for source, bare, numbered in cases:
            with self.subTest(source=source):
                self.assertEqual(remove_numbers(source), bare)
                self.assertEqual(renumber(source), numbered)
                self.assertEqual(renumber(numbered), numbered)
                for text in (source, bare, numbered):
                    result = preview(text)
                    self.assertIsNone(result.error)
                    self.assertEqual(result.lines, ['G1 X5'])

    def test_empty_lines_and_newline_ending_are_preserved(self):
        self.assertEqual(renumber(''), '')
        self.assertEqual(renumber('G0 Z5\n\n'), 'N10 G0 Z5\n\n')

    def test_start_and_step_are_explicit_and_validated(self):
        self.assertEqual(renumber('G0 Z5\nG1 X10', 100, 5), 'N100 G0 Z5\nN105 G1 X10')
        for start, step in ((-1, 10), (10, 0), (10, -1), (True, 10)):
            with self.assertRaises(ValueError):
                renumber('G0 Z5', start, step)

    def test_remove_numbers_preserves_delete_prefixes_indentation_and_comments(self):
        source = '  /1N20G1X10F100\n\tN30 G0 Z5\nN40 (N99 comment)\n; N50 note\nO123\n%\n'
        removed = remove_numbers(source)
        self.assertEqual(removed, '  /1G1X10F100\n\tG0 Z5\n(N99 comment)\n; N50 note\nO123\n%\n')
        moves = lambda text: [
            line for line in preview(text).lines if line.startswith(("G0 ", "G1 ", "G2 ", "G3 "))
        ]
        self.assertEqual(moves(source), moves(removed))

    def test_remove_spaced_numbers_is_idempotent_and_keeps_unrelated_words(self):
        source = '/2 N 10 G1 X10 F100\nG1 X20 N300\n(N50)\n\n'
        removed = remove_numbers(source)
        self.assertEqual(removed, '/2 G1 X10 F100\nG1 X20 N300\n(N50)\n\n')
        self.assertEqual(remove_numbers(removed), removed)

    def test_number_removal_preserves_empty_input(self):
        for source in ('', '\n', '  \n\t'):
            self.assertEqual(remove_numbers(source), source)
