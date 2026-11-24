"""Compact source-block readout from the existing modal parser's snapshots."""

from .i18n import tr
import re
from bisect import bisect_right
from dataclasses import dataclass


def number(value):
    if value is None:
        return "—"
    # Readout precision only; never change original source or simulated geometry.
    return f"{value:.3f}".rstrip("0").rstrip(".") if value else "0"


@dataclass
class Readout:
    heading: str
    coordinates: str
    cutting: str
    tooltip: str
    error: object = None


def readout(result, source_line):
    states = getattr(result, "states", []) if result is not None else []
    error = getattr(result, "error", None)
    if not states:
        kind = tr('Error') if error else "—"
        return Readout(
            tr('Line {source_line} · {kind}').format(source_line=source_line, kind=kind),
            "X— · Y— · Z— mm",
            "F— · S—",
            tr('No valid line information yet.'),
            str(error) if error else None,
        )
    index = bisect_right(states, source_line, key=lambda state: state.source_line) - 1
    state = states[max(0, index)]
    stopped = error is not None and source_line >= error.line
    kind = (
        tr('Last valid: {value1}').format(value1=state.source_line)
        if stopped
        else state.motion or state.kind
    )
    tool = f"T{state.tool}" if state.tool is not None else "T—"
    coords = " · ".join(f"{axis}{number(value)}" for axis, value in zip("XYZ", state.position)) + " mm"
    spindle_suffix = {3: " · M3", 4: " · M4", 5: tr(' · Stopped')}.get(state.spindle_mode, "")
    cutting = f"F{number(state.feed)} · S{number(state.spindle)}{spindle_suffix}"
    tooltip = tr(
        'Programmed tool tip position at the end of the current line. X/Y/Z: mm; F: mm/min; S: rpm. Simulation progress is shown separately.'
    )
    if state.selected_tool is not None and state.selected_tool != state.tool:
        tooltip += tr(' T{value1} is preselected; active tool {tool}, waiting for M6.').format(
            value1=state.selected_tool, tool=tool
        )
    if stopped:
        tooltip += tr(' Showing the last valid line {value1} because of an error.').format(
            value1=state.source_line
        )
    return Readout(
        tr('Line {source_line} · {kind} · {tool}').format(source_line=source_line, kind=kind, tool=tool),
        coords,
        cutting,
        tooltip,
        str(error) if error else None,
    )


def diagnostic(text, error=None):
    """Badge + short error; keep full explanations in the expandable details."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Accept either supported language, including messages retained after a
    # locale change. These are diagnostic patterns, not translatable UI labels.
    line_pattern = r"(?:Line|Satır) (\d+):"
    error_line = error or next((line for line in lines if re.match(line_pattern, line)), None)
    if error_line is None:
        error_line = next(
            (
                line
                for line in lines
                if any(
                    term in line.casefold()
                    for term in (
                        "could not",
                        "cannot",
                        "preview stopped",
                        "açılamadı",
                        "güncellenemedi",
                        "önizleme durduruldu",
                        "korunamadı",
                    )
                )
            ),
            None,
        )
    if error_line:
        match = re.match(line_pattern, error_line)
        badge = tr('Error · Line {value1}').format(value1=match[1]) if match else tr('Error')
        details = text if error_line in text else error_line + "\n" + text
        return badge, error_line, details
    if any(any(term in line.casefold() for term in ('updating', 'güncelleniyor')) for line in lines):
        return tr('Updating'), "", text
    if any(
        any(
            term in line.casefold()
            for term in (
                'activate ',
                'finish ',
                'close the tool editor',
                'önce açık',
                'önce takım',
                'etkinleştirin',
                'açık görevi',
            )
        )
        for line in lines
    ):
        return tr('Waiting'), "", text
    notes = sum(
        any(
            term in line.casefold()
            for term in (
                "offset",
                "ofset",
                "assumed",
                "varsayılıyor",
                "no tools are assigned",
                "eşlemesi yapılmadı",
                "tool length",
                "takım boyu",
                "geometry in the simulation",
                "geometrisiyle",
                "geometry is missing",
                "geometrisi tanımlı değil",
            )
        )
        for line in lines
    )
    if notes:
        return tr('Notes ({count})').format(count=notes), "", text
    badge = (
        tr('Up to date')
        if text.startswith(
            (
                'Toolpath updated',
                'Simulation updated',
                'Takım yolu güncellendi',
                'Simülasyon güncellendi',
                'Canlı 3B yol güncel',
            )
        )
        else (
            tr('Saved')
            if text.startswith(('G-code saved', 'G-code kaydedildi'))
            else tr('Opened')
            if text.startswith(('Opened:', 'Açıldı:'))
            else tr('Information')
        )
    )
    return badge, "", text
