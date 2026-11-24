"""Update Qt TS catalogs from literal tr() calls. Run lrelease to compile QM files."""

import ast
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / 'freecad' / 'camed'


def messages():
    found = {}
    for path in sorted(ROOT.glob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'tr'
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.setdefault(node.args[0].value, []).append((path.name, node.lineno))
    return found


def update(path):
    tree = ET.parse(path)
    root = tree.getroot()
    existing = {
        message.findtext('source'): message.find('translation')
        for context in root.findall('context')
        if context.findtext('name') == 'CAMed'
        for message in context.findall('message')
    }
    for context in root.findall('context'):
        root.remove(context)
    context = ET.SubElement(root, 'context')
    ET.SubElement(context, 'name').text = 'CAMed'
    for source, locations in sorted(messages().items()):
        message = ET.SubElement(context, 'message')
        for filename, line in locations:
            ET.SubElement(message, 'location', filename='../../' + filename, line=str(line))
        ET.SubElement(message, 'source').text = source
        if source in existing:
            message.append(existing[source])
        else:
            ET.SubElement(message, 'translation', type='unfinished')
    ET.indent(tree, space='  ')
    tree.write(path, encoding='utf-8', xml_declaration=True)
    print(path.name, len(messages()), 'messages')


if __name__ == '__main__':
    for path in sorted((ROOT / 'resources' / 'translations').glob('*.ts')):
        update(path)
