# CAMed

[Türkçe](README.tr.md)

CAMed is a G-code editor for FreeCAD with toolpath preview, stock and tool setup,
drilling cycles, and machining simulation.

## Features

- Edit G-code with syntax highlighting, find and replace, and program section navigation.
- Preview the toolpath as you edit. Set box or cylinder stock and assign tools by T number.
- Insert drilling cycles from a form and preview the generated G-code.
- Simulate material removal in FreeCAD. Select a G-code line to jump to its simulation step.

## Installation

1. In FreeCAD, open **Tools → Addon Manager**.
2. In its settings, add [the CAMed GitHub repository](https://github.com/Reqrefusion/CAMed)
   under **Custom repositories** and set the branch to `main`.
3. Find **CAMed** in the list and select **Install**. Restart FreeCAD and select
   the **CAMed** workbench.

## Quick start

1. Open a G-code file with **Ctrl+O**, or choose **New CAMed project** to start
   with a blank editor.
2. Use **Stock…** to set the stock shape and dimensions. If needed, assign
   tools and their T numbers under **Job tools…**.
3. Open **Simulation** and press **Play**. To jump to a point in the
   simulation, select the corresponding line in the editor.
4. Press **Ctrl+S** to save the G-code. To keep the stock and tools with it,
   use **Save FreeCAD project…**.

The interface follows FreeCAD’s language setting and supports English and Turkish.

[Maintenance notes](MAINTENANCE.md) · [License](LICENSE)
