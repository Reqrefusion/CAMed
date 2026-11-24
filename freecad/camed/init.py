"""Register standard FreeCAD file handlers during application startup."""

import FreeCAD as App

FILE_TYPE = "CAMed G-code (*.nc *.ngc *.tap *.gcode)"
HANDLER = "freecad.camed.file_io"
App.addImportType(FILE_TYPE, HANDLER)
App.addExportType(FILE_TYPE, HANDLER)
