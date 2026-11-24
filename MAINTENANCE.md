# CAMed maintenance

[Türkçe](MAINTENANCE.tr.md)

## FreeCAD improvements and their impact on CAMed

CAMed uses FreeCAD’s G-code editor, stock and tool editors, drilling generator,
and OpenGL simulator. Two improvements to FreeCAD’s simulator Python API would
enable camera synchronization and reduce the maintenance needed for line seeking.

- **Camera synchronization.** FreeCAD should expose the simulator camera through
  its Python API, with a way to read and set its state and observe changes.
  CAMed could then keep the normal 3D view and simulator in sync in both
  directions when the user rotates, pans, or zooms. The normal 3D view would
  also follow when the simulator fits the stock to the view.
- **Seeking by G-code line.** FreeCAD should expose the final simulation step
  for each submitted command. Today `timeline.py` calculates where each source
  line ends. Changes to the step calculations in `MillPathSegment` or
  `MillSimulation` require checking that mapping. With the native step indices,
  CAMed could seek to the last step of the final command generated from the
  selected line and remove its duplicate step calculations.

## Tests

Run the Python tests from the add-on root.

```text
python -B -m unittest discover -s tests -q
```

In FreeCAD's Python environment, run `tests/run_qt_checks.py` and
`tests/run_freecad_checks.py` for the additional Qt and runtime checks.
Configure `QT_PLUGIN_PATH` for the offscreen Qt tests. Set `FREECAD_CAM_ROOT` to
FreeCAD's `Mod/CAM` directory to enable native cycle tests in a standard Python
environment.

[Translation maintenance](freecad/camed/resources/translations/README.md)
