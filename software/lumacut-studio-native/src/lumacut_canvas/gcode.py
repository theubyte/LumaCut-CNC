"""Marlin-G-Code aus dem Canvas-Dokument (Pi-400-Profil).

Übernimmt die Regeln des Web-Studios (``software/lumacut-studio/
marlin-postprocessor.mjs``) und der Pi-Freigabeprüfung
(``pi400/marlin/transport.py``): einmal ``M3 I`` (Inline-Laser) für den
ganzen Auftrag, G0 ohne Leistung, jedes G1 mit eigenem ``S`` (0..255) und
``F``; am Ende ``M5 I`` und ``M400``. Ebenen mit ``z_step`` senken den
Fokus zwischen den Durchgängen relativ ab (``G91`` / ``G0 Z-… F600`` /
``G90``) und fahren nach der Ebene wieder auf die Ausgangshöhe; der Pi
fokussiert vor der ersten Leistungsfahrt absolut, daher erst ab Durchgang 2. Referenzfahrt, Fokus und Parken
übernimmt der Pi – deshalb kein G28 hier.

Tiefen-Hook (optional, Standard aus): ``layers_to_gcode(..., pass_hook=f)``
ruft vor jedem Durchgang einer Ebene mit Tiefenplanung
(``JobLayer.pass_depths_mm``, siehe ``material.py``)
``f(layer, index, depth_mm, cumulative_mm)`` auf und fügt die
zurückgegebenen Zeilen direkt nach ``; PASS i OF n`` ein. Ohne Hook (oder
für Ebenen ohne Planung) bleibt die Ausgabe Byte für Byte unverändert.
Hook-Zeilen dürfen keine Zeilenumbrüche enthalten und müssen ASCII sein;
Bewegungen in Z sind Sache des Aufrufers (``MAX_FOCUS_DROP_MM`` beachten).
:func:`depth_comment_hook` ist ein harmloses Beispiel (nur Kommentare).

Die Funktion erzeugt nur Text; sie startet nie eine Maschine.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

from .export import JobLayer, job_layers
from .model import (MAX_FOCUS_DROP_MM, PASSES_RANGE, POWER_RANGE, SPEED_RANGE,
                    Z_STEP_RANGE, Document)
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine

#: ``(layer, pass_index, depth_mm, cumulative_mm) -> Zeilen``
PassHook = Callable[[JobLayer, int, float, float], Iterable[str]]

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


def depth_comment_hook(layer: JobLayer, index: int, depth_mm: float,
                       cumulative_mm: float) -> list[str]:
    """Beispiel-Hook: dokumentiert die geplante Tiefe als Kommentar."""
    return [f"; DEPTH {depth_mm:.3f} TOTAL {cumulative_mm:.3f}"]


def _hook_lines(hook: PassHook, layer: JobLayer, p: int, acc: float) -> list[str]:
    lines = [str(x) for x in hook(layer, p, layer.pass_depths_mm[p], acc)]
    for x in lines:
        if "\n" in x or "\r" in x or not x.isascii():
            raise ValueError("pass_hook: nur einzeilige ASCII-Zeilen erlaubt")
    return lines


def layers_to_gcode(layers: list[JobLayer], pass_hook: PassHook | None = None) -> str:
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
        z_step = float(getattr(layer, "z_step_mm", 0.0) or 0.0)
        drop = z_step * (layer.passes - 1)
        if not Z_STEP_RANGE[0] <= z_step <= Z_STEP_RANGE[1] or drop > MAX_FOCUS_DROP_MM + _EPS:
            raise ValueError(f"Fokus-Absenkung zu groß ({drop:.2f} mm > "
                             f"{MAX_FOCUS_DROP_MM:g} mm): {layer.name}")
        s = round(layer.power_percent / 100 * PWM_MAX)
        f = f"{layer.speed_mm_min:g}"
        out.append("; LAYER " + _comment(layer.name))
        depths = getattr(layer, "pass_depths_mm", ()) or ()
        use_hook = pass_hook is not None and len(depths) == layer.passes
        acc = 0.0
        for p in range(layer.passes):
            if p and z_step > 0:
                out += ["G91", f"G0 Z{-z_step:.3f} F600", "G90"]
            out.append(f"; PASS {p + 1} OF {layer.passes}")
            if use_hook:
                acc += depths[p]
                out += _hook_lines(pass_hook, layer, p, round(acc, 6))
            kinds = getattr(layer, "poly_kinds", ()) or ()
            prev_end = None
            for i, line in enumerate(layer.polylines):
                if len(line) < 2:
                    continue
                # An-/Abfahrt schließt direkt an die Kontur an: kein G0 dazwischen.
                joined = (len(kinds) == len(layer.polylines) and i > 0 and prev_end is not None
                          and (kinds[i] == "lead_out" or kinds[i - 1] == "lead_in")
                          and abs(prev_end[0] - line[0][0]) < 1e-6
                          and abs(prev_end[1] - line[0][1]) < 1e-6)
                prev_end = line[-1]
                if not joined:
                    out.append(f"G0 {_xy(*line[0])}")
                out.extend(f"G1 {_xy(*pt)} F{f} S{s}" for pt in line[1:])
        if z_step > 0 and drop > 0:
            out += ["G91", f"G0 Z{drop:.3f} F600", "G90"]  # zurück auf Fokushöhe
    out += ["M5 I", "M400"]
    return "\n".join(out) + "\n"


def document_to_gcode(doc: Document, pass_hook: PassHook | None = None) -> str:
    """G-Code für alle sichtbaren Ebenen (unterste zuerst)."""
    return layers_to_gcode(job_layers(doc), pass_hook)
