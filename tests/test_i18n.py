"""Catalog coverage and formatting contracts without a GUI dependency."""

import ast
from pathlib import Path
from string import Formatter
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / 'freecad' / 'camed'


class TranslationCatalogTests(unittest.TestCase):
    def test_every_translation_call_has_a_finished_turkish_entry(self):
        tree = ET.parse(ROOT / 'resources/translations/CAMed_tr.ts')
        entries = {m.findtext('source'): m.find('translation') for m in tree.findall('.//message')}
        calls = set()
        for path in ROOT.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr':
                    self.assertTrue(node.args and isinstance(node.args[0], ast.Constant), path.name)
                    calls.add(node.args[0].value)
        self.assertEqual(calls, set(entries))
        for source, translation in entries.items():
            with self.subTest(source=source):
                self.assertTrue(translation.text)
                self.assertNotIn('type', translation.attrib)
                fields = lambda text: {
                    (name, spec, conversion)
                    for _, name, spec, conversion in Formatter().parse(text)
                    if name is not None
                }
                self.assertEqual(fields(source), fields(translation.text))
                self.assertEqual(source.count('\n'), translation.text.count('\n'))

    def test_catalog_contains_no_colliding_contexts(self):
        tree = ET.parse(ROOT / 'resources/translations/CAMed_tr.ts')
        self.assertEqual([ctx.findtext('name') for ctx in tree.findall('context')], ['CAMed'])
        self.assertTrue((ROOT / 'resources/translations/CAMed_tr.qm').is_file())
