"""Load the checkout under test even when FreeCAD preloads the installed addon."""

import os
from pathlib import Path
import sys


def configure_test_paths():
    home = Path(os.environ.get('FREECAD_HOME', Path(sys.executable).resolve().parent.parent))
    root = Path(__file__).resolve().parents[1]
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    sys.path.extend([str(home / 'lib'), str(home / 'Ext'), str(home / 'Mod/CAM')])
    # FreeCAD can pre-import the installed addon. Always test this source tree.
    import freecad

    freecad.__path__ = [str(root / 'freecad'), *list(freecad.__path__)]
    for module_name in list(sys.modules):
        if module_name == 'freecad.camed' or module_name.startswith('freecad.camed.'):
            del sys.modules[module_name]
    vars(freecad).pop('camed', None)
    from freecad import camed

    assert (
        Path(camed.__file__).resolve() == (root / 'freecad/camed/__init__.py').resolve()
    )
    return root
