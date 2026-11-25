import FreeCAD as App
import FreeCADGui as Gui
from .i18n import register_translations, tr

from pathlib import Path

register_translations()


def icon(name):
    return str(Path(__file__).parent / "resources" / "icons" / name)


class OpenEditor:
    def GetResources(self):
        return {
            "MenuText": tr('G-code editor'),
            "Pixmap": icon("editor.svg"),
            "ToolTip": tr('Open the G-code editor and preview'),
        }

    def IsActive(self):
        return True

    def open(self):
        from .panel import show_panel

        show_panel()

    def error_title(self):
        return "CAMed"

    def Activated(self):
        try:
            self.open()
        except Exception as error:
            from PySide import QtWidgets

            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.error_title(), str(error))


class StockSettings(OpenEditor):
    def GetResources(self):
        return {
            "MenuText": tr('Stock…'),
            "Pixmap": icon("stock.svg"),
            "ToolTip": tr('Set stock shape, dimensions and position'),
        }

    def open(self):
        from .stock_tool import show_stock_tool

        show_stock_tool()


class ToolSettings(StockSettings):
    def GetResources(self):
        return {
            "MenuText": tr('Job tools…'),
            "Pixmap": ":/icons/CAM_ToolController.svg",
            "ToolTip": tr('Manage tool numbers and cutting tools for this job'),
        }

    def open(self):
        from .tool_panel import show_tools

        show_tools()


class CannedCycle(OpenEditor):
    def GetResources(self):
        return {
            "MenuText": tr('Insert drilling cycle'),
            "Pixmap": ":/icons/CAM_Drilling.svg",
            "ToolTip": tr('Insert a G81, G82, G83 or G73 drilling cycle'),
        }

    def open(self):
        from .cycle_tool import show_cycle_tool

        show_cycle_tool()

    def error_title(self):
        return tr('Drilling cycle')


def active_editor():
    from . import panel

    owner = panel._panel
    return (
        owner
        if owner is not None and owner.enabled and not owner.shutting_down and owner.is_current()
        else None
    )


class EditorAction(OpenEditor):
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        from .editor_actions import ACTION_SPECS

        label, shortcut, image, tooltip = ACTION_SPECS[self.name]
        return {
            'MenuText': label,
            'Pixmap': image,
            'ToolTip': tooltip + (f' ({shortcut})' if shortcut else ''),
        }

    def IsActive(self):
        return active_editor() is not None

    def Activated(self):
        owner = active_editor()
        if owner is not None:
            owner.editor_actions[self.name].trigger()


class Preview(EditorAction):
    def __init__(self):
        super().__init__('Preview')

    def GetResources(self):
        return {
            'MenuText': tr('Simulation'),
            'Pixmap': ':/icons/CAM_SimulatorGL.svg',
            'ToolTip': tr('Open or activate the simulation view'),
        }

    def Activated(self):
        owner = active_editor()
        if owner is not None:
            owner.show_simulation()


class NewProject(OpenEditor):
    def GetResources(self):
        return {
            "MenuText": tr('New CAMed project'),
            "Pixmap": ":/icons/document-new.svg",
            "ToolTip": tr('Create a blank G-code project'),
        }

    def open(self):
        from .editor_lifecycle import close_editor
        from . import panel

        close_editor()
        App.newDocument("CAMed")
        panel.show_panel()


class SaveGCode(OpenEditor):
    def GetResources(self):
        return {
            "MenuText": tr('Save G-code'),
            "Pixmap": ":/icons/document-save.svg",
            "ToolTip": tr('Save G-code'),
        }

    def IsActive(self):
        from .file_io import active_operation

        return active_operation() is not None

    def open(self):
        from .file_io import save_active

        save_active()


class SaveProject(OpenEditor):
    def GetResources(self):
        return {
            "MenuText": tr('Save FreeCAD project…'),
            "Pixmap": "document-save-as",
            "ToolTip": tr('Save the program, stock and tools as a FreeCAD project'),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def open(self):
        from .editor_lifecycle import require_idle
        from .program_backend import require_document_idle

        document = App.ActiveDocument
        if document is None:
            return
        require_idle()
        require_document_idle(document)
        owner = active_editor()
        if owner is not None:
            if owner.timer.isActive() or owner.pending_code:
                owner.apply_text()
            owner.flush_source()
        Gui.getDocument(document.Name).saveAs()


Gui.addCommand("CAMed_Open", OpenEditor())
Gui.addCommand("CAMed_Stock", StockSettings())
Gui.addCommand("CAMed_Tools", ToolSettings())
Gui.addCommand("CAMed_Cycle", CannedCycle())
Gui.addCommand("CAMed_New", NewProject())
Gui.addCommand("CAMed_SaveGCode", SaveGCode())
Gui.addCommand("CAMed_SaveProject", SaveProject())
Gui.addCommand('CAMed_Preview', Preview())
from .editor_actions import ACTION_SPECS

for name in ACTION_SPECS:
    Gui.addCommand('CAMed_' + name, EditorAction(name))


class CAMedWorkbench(Gui.Workbench):
    MenuText = "CAMed"
    ToolTip = tr('G-code editor, stock setup and simulation')
    Icon = icon("editor.svg")

    def Initialize(self):
        self.appendToolbar(
            "CAMed",
            [
                "CAMed_New",
                "CAMed_Open",
                'Separator',
                "CAMed_Stock",
                "CAMed_Tools",
                "CAMed_Cycle",
                'CAMed_Preview',
            ],
        )
        self.appendMenu(
            "CAMed",
            [
                "CAMed_New",
                "CAMed_Open",
                "CAMed_Stock",
                "CAMed_Tools",
                "CAMed_Cycle",
                'CAMed_Preview',
                "Separator",
                "CAMed_SaveGCode",
                "CAMed_SaveProject",
            ],
        )
        from .editor_actions import ACTION_GROUPS

        for label, names in ACTION_GROUPS:
            self.appendMenu(['CAMed', label], ['CAMed_' + name for name in names])

    def Activated(self):
        Gui.runCommand("CAMed_Open")
        from .file_actions import activate

        activate(True)

    def Deactivated(self):
        from . import panel

        if panel._panel is not None:
            panel._panel.set_active(False)
        from .file_actions import activate

        activate(False)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(CAMedWorkbench())
