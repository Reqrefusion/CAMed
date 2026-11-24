"""Use FreeCAD's Qt translator; English is the untranslated source language."""

from pathlib import Path


def tr(source):
    try:
        import FreeCAD as App
    except ImportError:
        return source
    translate = getattr(getattr(App, 'Qt', None), 'translate', None)
    return translate('CAMed', source) if callable(translate) else source


def register_translations():
    import FreeCADGui as Gui

    Gui.addLanguagePath(str(Path(__file__).parent / 'resources' / 'translations'))
    Gui.updateLocale()
