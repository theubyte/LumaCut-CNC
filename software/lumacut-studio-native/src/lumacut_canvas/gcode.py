"""Marlin-G-Code aus dem Canvas-Dokument (Pi-400-Profil).

Übernimmt die Regeln des Web-Studios (``software/lumacut-studio/
marlin-postprocessor.mjs``) und der Pi-Freigabeprüfung
(``pi400/marlin/transport.py``): einmal ``M3 I`` (Inline-Laser) für den
ganzen Auftrag, G0 ohne Leistung, jedes G1 mit eigenem ``S`` (0..255) und
``F``; am Ende ``M5 I`` und ``M400``. Referenzfahrt, Fokus und Parken
übernimmt der Pi – deshalb kein G28 hier.

Die Funktion erzeugt nur Text; sie startet nie eine Maschine.
"""

from __future__ import annotations

import re

from .export import JobLayer, job_layers
from .model import PASSES_RANGE, POWER_RANGE, SPEED_RANGE, Document
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine

PWM_MAX = 255
_MIN_X, _MIN_Y = to_machine(0.0, 0.0)
_MAX_X, _MAX_Y = to_machine(WORK_WIDTH_MM, WORK_HEIGHT_MM)
_EPS = 1e-6


def _xy(x: float, y: float) -> str:
    if not (_MIN_X - _EPS <= x <= _MAX_X + _EPS and _MIN_Y - _EPS <= y <= _MAX_Y + _EPS):
        raise ValueError("Koordinate außerhalb der Arbeitsfläche")
    x = min(max(x, _MIN_X), _MAX_X)
    y = min(max(y, _MIN_Y), _MAX_Y)
    return f"X{x:.3f} Y{y:.3f}"


def _comment(text: str) -> str:
    return re.sub(r"[^\x20-\x7E]", "?", text)[:72]


def layers_to_gcode(layers: list[JobLayer]) -> str:
    if not any(l.polylines for l in layers):
        raise ValueError("Keine sichtbaren Objekte zum Lasern")
    out = ["; LUMACUT STUDIO NATIVE CANVAS JOB (homing, focus and park run on the Pi)",
           "G21", "G90", "M5 I", "M3 I"]
    for layer in layers:
        if not layer.polylines:
            continue
        if not (POWER_RANGE[0] <= layer.power_percent <= POWER_RANGE[1]
                and SPEED_RANGE[0] <= layer.speed_mm_min <= SPEED_RANGE[1]
                and PASSES_RANGE[0] <= layer.passes <= PASSES_RANGE[1]):
            raise ValueError(f"Ungültige Ebenen-Parameter: {layer.name}")
        s = round(layer.power_percent / 100 * PWM_MAX)
        f = f"{layer.speed_mm_min:g}"
        out.append("; LAYER " + _comment(layer.name))
        for p in range(layer.passes):
            out.append(f"; PASS {p + 1} OF {layer.passes}")
            for line in layer.polylines:
                if len(line) < 2:
                    continue
                out.append(f"G0 {_xy(*line[0])}")
                out.extend(f"G1 {_xy(*pt)} F{f} S{s}" for pt in line[1:])
    out += ["M5 I", "M400"]
    return "\n".join(out) + "\n"


def document_to_gcode(doc: Document) -> str:
    """G-Code für alle sichtbaren Ebenen (unterste zuerst)."""
    return layers_to_gcode(job_layers(doc))
