"""CAMed projects: native CAM resources prepared behind the UI."""

from .i18n import tr
from .transactions import document_transaction
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets
from PathScripts import PathUtils


def prepare_session(*, new_program=False, transaction=True):
    """Reuse a program normally; imports always request a fresh, independent Job.

    With transaction=False the caller owns the entire creation transaction.
    """
    from Path.Main import Job
    from Path.Main.Gui.Job import ViewProvider as JobViewProvider
    from .native_program import create
    from .stock_backend import clear_stock

    if App.ActiveDocument is None:
        App.newDocument("CAMed")
    doc = App.ActiveDocument
    selected = [] if new_program else list(Gui.Selection.getSelection())
    # Reuse only a program owned by this editor. Ordinary CAM jobs remain separate.
    candidates = (
        [] if new_program else [op for op in doc.Objects if getattr(op, "LiveEditorManaged", False)]
    )
    chosen = [op for op in selected if op in candidates]
    if not chosen and len(candidates) == 1:
        chosen = candidates
    if not chosen and len(candidates) > 1:
        labels = [f"{op.Label} ({op.Name})" for op in candidates]
        label, ok = QtWidgets.QInputDialog.getItem(
            Gui.getMainWindow(), "CAMed", tr('Select a program to open.'), labels, 0, False
        )
        if not ok:
            return None, False
        chosen = [candidates[labels.index(label)]]
    if chosen:
        op = chosen[0]
        job = PathUtils.findParentJob(op)
        if job is None:
            raise ValueError(tr("The program's simulation resources are missing."))
        if not getattr(job, 'CAMEditorSession', False) or getattr(op, 'Proxy', None) is not None:
            raise ValueError(tr('This program format is not supported. Create a new CAMed program.'))
        from .program_backend import configure_cycle_time

        configure_cycle_time(job)
        # Native Job restore recreates its default stock; preserve an explicitly
        # unconfigured editor session across FCStd save/reopen as well.
        if getattr(job, "CAMEditorStockDefinition", None) == "":
            clear_stock(job)
        return op, False

    with document_transaction(doc, tr('Create CAMed project'), enabled=transaction):
        # The native Create helper indexes base[0]; use its native constructor
        # directly so an NC-only Job needs neither a dummy model nor a solid.
        job = doc.addObject("Path::FeaturePython", "JobCAMed")
        job.addExtension("App::GroupExtensionPython")
        job.Proxy = Job.ObjectJob(job, [])
        clear_stock(job, transaction=False)
        job.ViewObject.Proxy = JobViewProvider(job.ViewObject)
        job.ViewObject.addExtension("Gui::ViewProviderGroupExtensionPython")
        job.ViewObject.Proxy.deleteOnReject = False
        job.Label = "CAMed"
        job.addProperty("App::PropertyBool", "CAMEditorSession", "CAMed")
        job.CAMEditorSession = True
        op = create(job, "Program")
        op.Label = "G-code"
        op.addProperty("App::PropertyBool", "LiveEditorManaged", "CAMed")
        op.LiveEditorManaged = True
        op.Gcode = []
        op.Visibility = False
        doc.recompute()
        for name in ("Model", "SetupSheet", "Tools", "Operations", "Workplanes"):
            resource = getattr(job, name, None)
            if resource is not None and getattr(resource, "ViewObject", None) is not None:
                resource.ViewObject.ShowInTree = False
    return op, True
