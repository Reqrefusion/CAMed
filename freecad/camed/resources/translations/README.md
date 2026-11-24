# CAMed translations

[Türkçe](README.tr.md)

CAMed uses `FreeCAD.Qt.translate("CAMed", source)` and registers this
directory through `FreeCADGui.addLanguagePath`. FreeCAD selects the catalog for
the application language. English is the source language; Turkish is supplied in
`CAMed_tr.ts` and its compiled `CAMed_tr.qm` catalog.

Restart FreeCAD after changing its application language. Open windows and labels
already stored in a document are not relabeled by the addon. Native FreeCAD
dialogs use FreeCAD's own translations.

## Updating a translation

Use literal English strings in `tr(...)`. Apply named formatting after translation,
for example `tr("Line {line}").format(line=number)`. Keep G-code, identifiers,
file names, user text and parser matching patterns outside translation calls.

From the addon root, update the catalogs:

```text
python tools/update_translations.py
```

Edit the TS file in Qt Linguist or an XML editor. Preserve all named placeholders,
format specifications and newlines, then compile it with Qt's `lrelease`:

```text
lrelease freecad/camed/resources/translations/CAMed_tr.ts -qm freecad/camed/resources/translations/CAMed_tr.qm
```

If `lrelease` is supplied by a FreeCAD development environment, run it with that
environment's Qt libraries on PATH. Ship both TS and QM files. The addon does not
require Qt Linguist at runtime.

## Adding a language

Create `CAMed_<locale>.ts` with TS attributes `sourcelanguage="en"` and the
target `language` code, and a context named `CAMed`. The update tool populates
missing messages as unfinished. Complete the translations and compile the matching
QM file. No language dictionary or preferences code needs changing.

Catalog tests check coverage, placeholders and line breaks. Offscreen Qt tests
load the compiled catalog through FreeCAD's translator and verify that labels and
diagnostics change language while generated drilling code remains identical.
