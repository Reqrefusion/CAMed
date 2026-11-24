"""Native FreeCAD Path objects for NC text; no model-based CAM operation."""

from .i18n import tr


def create(job, name):
    operation = job.Document.addObject('Path::Feature', name)
    operation.addProperty('App::PropertyStringList', 'Gcode', 'Path')
    operation.addProperty('App::PropertyLink', 'ToolController', 'Path')
    operation.addProperty('App::PropertyBool', 'Active', 'Path')
    operation.Active = True
    job.Proxy.addOperation(operation)
    return operation


def write(operation, lines):
    import Path

    if operation.TypeId != 'Path::Feature':
        raise ValueError(tr('This program format is not supported. Create a new CAMed program.'))
    operation.Gcode = lines
    operation.Path = Path.Path('\n'.join(lines))
