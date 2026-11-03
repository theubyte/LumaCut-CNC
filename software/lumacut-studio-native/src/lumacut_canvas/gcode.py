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

Vektor-Füllung: ``JobLayer.fills`` (Schraffurblöcke je Objekt, siehe
``hatch.py``) wird in jedem Durchgang *vor* den Konturen gelasert – gleiche
Leistung/Geschwindigkeit/Durchgänge und derselbe Tiefen-Hook wie die Ebene.
Jede Schraffurstrecke ist ein ``G0`` zum Anfang und ein ``G1`` zum Ende –
das ``G0`` entfällt, wenn die Strecke genau dort beginnt, wo die vorige
endete (Offset-Füllung: Ringe als lückenlose Streckenkette);
die Blöcke (je Objekt, Gruppe oder Ebene, ``Layer.fill_grouping``) werden in
der Reihenfolge der Objekte gefahren, Schraffur ab der nächstgelegenen ihrer
vier Ecken (erste/letzte Zeile × Zeilenanfang/-ende, ``JobLayer.fill_free_corner``;
sonst vorwärts oder rückwärts – je nachdem, welches Ende näher liegt); Offset-Füllung immer
vorwärts (Ring-Reihenfolge außen → innen bzw. innen → außen bleibt). Ohne Füllung bleibt
die Ausgabe unverändert.

Überlauf (``JobLayer.fill_overscan_mm`` > 0, nur Schraffur/Kreuzschraffur,
LightBurn „Overscanning“): jede Schraffurstrecke wird an beiden Enden mit
ausgeschaltetem Laser verlängert – ``G0`` zum vorgezogenen Start, ``G1 … S0``
bis zum Linienanfang (Kopf beschleunigt), ``G1 … S<p>`` über die Linie und
``G1 … S0`` darüber hinaus (wie die Bild-Gravur in ``lumacut_job.raster``).
Die Verlängerung wird an der Arbeitsfläche gekürzt (:func:`overscan_segment`);
bei 0 bleibt die Ausgabe Byte für Byte gleich.

Scan-Versatz (``JobLayer.fill_scan_offset_mm`` ≠ 0, LightBurn „Scanning Offset
Adjustment“, Tabelle in ``lumacut_job.scan_offset``): jede Füllstrecke wird
*nach* der Richtungswahl um den halben Versatz entgegen ihrer Fahrtrichtung
verschoben (:func:`scan_offset_segment`), damit hin- und rücklaufende Linien
trotz Laser-Verzögerung auf einer Kante enden; danach folgt der Überlauf.
Bei 0 bleibt die Ausgabe Byte für Byte gleich.

Die Funktion erzeugt nur Text; sie startet nie eine Maschine.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Iterable

from .export import JobLayer, job_layers
from .hatch import nearest_fill_entry
from .model import (MAX_FOCUS_DROP_MM, PASSES_RANGE, POWER_RANGE, SPEED_RANGE,
                    Z_STEP_RANGE, Document)
from .workarea import (WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine,
    MACHINE_X_MAX, MACHINE_X_MIN, MACHINE_Y_MAX, MACHINE_Y_MIN)

#: ``(layer, pass_index, depth_mm, cumulative_mm) -> Zeilen``
PassHook = Callable[[JobLayer, int, float, float], Iterable[str]]

PWM_MAX = 255
# Erlaubter Bereich in Maschinen-mm (Nullpunkt oben rechts: to_machine(0, 0)
# ist jetzt die *größte* X-Koordinate, darum feste Grenzen statt Ecken).
_MIN_X, _MIN_Y, _MAX_X, _MAX_Y = MACHINE_X_MIN, MACHINE_Y_MIN, MACHINE_X_MAX, MACHINE_Y_MAX
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


def _has_moves(layer: JobLayer) -> bool:
    return bool(layer.polylines or getattr(layer, "fills", None))


def order_fill_blocks(blocks, pos=None, reversible=True, corners=False):
    """Schraffurblöcke in Objekt-Reihenfolge, jeder ab dem nächsten Einstieg.

    Ein rückwärts gefahrener Block kehrt Reihenfolge *und* Richtung seiner
    Strecken um. ``pos`` = aktuelle Kopfposition (``None`` = unbekannt).
    ``reversible=False`` (Offset-Füllung, ``JobLayer.fill_fixed_order``):
    jeder Block vorwärts, damit die gewählte Ring-Reihenfolge erhalten bleibt.
    ``corners`` (Schraffur, ``JobLayer.fill_free_corner``): zusätzlich die
    beiden übrigen Ecken – Zeilen rückwärts bzw. jede Zeile umgedreht
    (:func:`lumacut_canvas.hatch.nearest_fill_entry`); bei Gleichstand bleibt
    der Block vorwärts.
    """
    out = []
    for block in blocks:
        if not block:
            continue
        _, block = nearest_fill_entry(block, pos, reversible, corners)
        out.append(block)
        pos = block[-1][1]
    return out


def _room_along(p, d) -> float:
    """Wie weit man von ``p`` in Richtung ``d`` (Einheitsvektor) im erlaubten Bereich bleibt."""
    t = math.inf
    for v, dv, lo, hi in ((p[0], d[0], _MIN_X, _MAX_X), (p[1], d[1], _MIN_Y, _MAX_Y)):
        if dv > 1e-12:
            t = min(t, (hi - v) / dv)
        elif dv < -1e-12:
            t = min(t, (lo - v) / dv)
    return max(0.0, t)


def overscan_segment(a, b, overscan_mm: float):
    """Schraffurstrecke ``a → b`` mit Überlauf: ``(a', b')`` vor bzw. hinter der Strecke.

    Beide Punkte liegen auf der Verlängerung der Strecke, höchstens
    ``overscan_mm`` entfernt und nie außerhalb der Arbeitsfläche (Maschinen-mm,
    an der Grenze gekürzt). Ohne Überlauf oder bei Nulllänge: ``(a, b)``.
    """
    length = math.dist(a, b)
    if overscan_mm <= 0 or length < 1e-9:
        return a, b
    u = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    back = min(overscan_mm, _room_along(a, (-u[0], -u[1])))
    fwd = min(overscan_mm, _room_along(b, u))
    a2 = (a[0] - u[0] * back, a[1] - u[1] * back) if back > 1e-6 else a
    b2 = (b[0] + u[0] * fwd, b[1] + u[1] * fwd) if fwd > 1e-6 else b
    return a2, b2


def scan_offset_segment(a, b, offset_mm: float):
    """Füllstrecke ``a → b`` um ``offset_mm / 2`` entgegen der Fahrtrichtung verschoben.

    Positiver Versatz = der Laser brennt in Fahrtrichtung zu spät; die Strecke
    wandert darum zurück. Die Verschiebung wird an der Arbeitsfläche gekürzt
    (Maschinen-mm), bei Nulllänge oder Versatz 0: ``(a, b)``.
    """
    length = math.dist(a, b)
    if abs(offset_mm) < 1e-9 or length < 1e-9:
        return a, b
    u = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    t = -offset_mm / 2.0          # entlang u
    if t < 0:
        t = -min(-t, _room_along(a, (-u[0], -u[1])))
    else:
        t = min(t, _room_along(b, u))
    if abs(t) < 1e-9:
        return a, b
    return ((a[0] + u[0] * t, a[1] + u[1] * t), (b[0] + u[0] * t, b[1] + u[1] * t))


def layers_to_gcode(layers: list[JobLayer], pass_hook: PassHook | None = None) -> str:
    if not any(_has_moves(l) for l in layers):
        raise ValueError("Keine sichtbaren Objekte zum Lasern")
    out = ["; LUMACUT STUDIO NATIVE CANVAS JOB (homing, focus and park run on the Pi)",
           "G21", "G90", "M5 I", "M3 I"]
    pos = None
    for layer in layers:
        if not _has_moves(layer):
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
            overscan = float(getattr(layer, "fill_overscan_mm", 0.0) or 0.0)
            scan_off = float(getattr(layer, "fill_scan_offset_mm", 0.0) or 0.0)
            for block in order_fill_blocks(getattr(layer, "fills", None) or (), pos,
                                           not getattr(layer, "fill_fixed_order", False),
                                           getattr(layer, "fill_free_corner", False)):
                for a, b in block:
                    if scan_off:
                        a, b = scan_offset_segment(a, b, scan_off)
                    a2, b2 = overscan_segment(a, b, overscan)
                    if pos is None or abs(pos[0] - a2[0]) > 1e-6 or abs(pos[1] - a2[1]) > 1e-6:
                        out.append(f"G0 {_xy(*a2)}")
                    if a2 != a:   # Anlauf mit Laser aus
                        out.append(f"G1 {_xy(*a)} F{f} S0")
                    out.append(f"G1 {_xy(*b)} F{f} S{s}")
                    if b2 != b:   # Auslauf mit Laser aus
                        out.append(f"G1 {_xy(*b2)} F{f} S0")
                    pos = b2
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
                pos = line[-1]
        if z_step > 0 and drop > 0:
            out += ["G91", f"G0 Z{drop:.3f} F600", "G90"]  # zurück auf Fokushöhe
    out += ["M5 I", "M400"]
    return "\n".join(out) + "\n"


def document_to_gcode(doc: Document, pass_hook: PassHook | None = None) -> str:
    """G-Code für alle sichtbaren Ebenen (unterste zuerst)."""
    return layers_to_gcode(job_layers(doc), pass_hook)
