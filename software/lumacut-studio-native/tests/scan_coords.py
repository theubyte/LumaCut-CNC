"""Test-Helfer: Canvas-Formen in Maschinen-mm platzieren (Anforderungen 2026-10-26 §2.3).

Die Scan-Tests legen Fake-Meshes in Maschinen-mm an. Seit dem Nullpunkt oben
rechts gilt nicht mehr ``Maschine = Bildschirm + 30``; die Bildschirmlage wird
deshalb immer über ``lumacut_canvas.workarea.from_machine`` bestimmt.
"""
from __future__ import annotations

import re

from scanprobe.geometry import Rect


def screen_rect(mx: float, my: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Maschinen-Rechteck (linke obere Maschinenecke, Breite, Höhe) -> Bildschirm (x, y, w, h)."""
    from lumacut_canvas.workarea import from_machine
    ax, ay = from_machine(mx, my)
    bx, by = from_machine(mx + w, my + h)
    return min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay)


def add_rect_at_machine(target, mx: float, my: float, w: float, h: float):
    """Rechteck so auf den Canvas legen, dass es in Maschinen-mm ``mx..mx+w`` / ``my..my+h`` liegt."""
    from lumacut_canvas.model import Geometry, Shape
    doc = getattr(target, "document", target)
    return doc.add_shape(Shape("rect", Geometry(*screen_rect(mx, my, w, h)), doc.active_layer_id))


def gcode_rect(gcode: str, pad: float = 1.0) -> Rect:
    """Umgebendes Rechteck aller X/Y-Werte der G0/G1-Zeilen (Maschinen-mm) plus Rand."""
    xs, ys = [], []
    for line in gcode.splitlines():
        if not line.startswith(("G0", "G1")):
            continue
        mx, my = re.search(r"X(-?[\d.]+)", line), re.search(r"Y(-?[\d.]+)", line)
        if mx:
            xs.append(float(mx.group(1)))
        if my:
            ys.append(float(my.group(1)))
    return Rect(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
