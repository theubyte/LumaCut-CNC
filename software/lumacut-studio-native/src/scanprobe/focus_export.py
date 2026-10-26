"""Fokuskorrigierter G-Code-Export (Qt-frei).

Nimmt den normalen Marlin-G-Code des Canvas (``lumacut_canvas.gcode``) und
legt mit :func:`scanprobe.compensation.apply_focus_compensation` je Segment
ein Z aus den Höhenmeshes an. Vorher wird geprüft, ob das überhaupt sicher
geht; das Ergebnis trennt **Fehler** (Export gesperrt) von **Warnungen**
(Export nach Bestätigung).

Fehler
  * G2/G3-Bögen im Eingang (der Canvas-Export erzeugt nur Linien; Bögen kämen
    nur aus fremdem G-Code) und absolute Z-Wörter – beides lässt sich nicht
    mit der Mesh-Korrektur kombinieren. Die relative „Fokus-Absenkung je
    Durchgang" (``z_step``, ``G91``/``G0 Z-…``/``G90``) wird dagegen
    unterstützt: sie wird auf das Mesh-Z aufgerechnet.
  * Material laut Fingerabdruck seit dem Proben verschoben/verändert
    (Vergleich mit dem aktuellen Scan).
  * Keine brennende Strecke liegt in einem Höhenmesh.

Warnungen
  * Teile der Brennstrecke liegen außerhalb aller Meshes. **Rückfall:** dort
    gilt die *höchste* gemessene Oberfläche aller Meshes (Fokus etwas zu hoch,
    aber nie zu tief → keine Kollision mit geprobten Werkstücken). Länge und
    Anteil werden gemeldet.
  * Höhenmesh älter als ``max_age_h`` oder ohne Fingerabdruck / ohne aktuellen
    Scan zum Vergleich.
  * Z (Fokus) läge unter der Pi-Sperre „bekannte Oberfläche + 2 mm“.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import time
from typing import Optional

import numpy as np

from .compensation import (_WORD, CompensationReport, FocusSettings, apply_focus_compensation,
                           is_relative_z_only)
from .heightmap import HeightMapSet

MAX_AGE_H = 8.0


@dataclass
class JobCoverage:
    burn_mm: float = 0.0
    outside_mm: float = 0.0
    outside_points: list[tuple[float, float]] = field(default_factory=list)  # Beispiele

    @property
    def outside_fraction(self) -> float:
        return self.outside_mm / self.burn_mm if self.burn_mm > 0 else 0.0


@dataclass
class FocusExport:
    gcode: Optional[str] = None
    report: Optional[CompensationReport] = None
    coverage: JobCoverage = field(default_factory=JobCoverage)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fallback_surface_z: Optional[float] = None

    @property
    def ok(self) -> bool:
        return not self.errors and self.gcode is not None

    def summary(self) -> str:
        if not self.ok:
            return "Fokuskorrektur nicht möglich:\n• " + "\n• ".join(self.errors)
        r = self.report
        text = (f"Fokuskorrektur angewendet: Z {r.z_min:.2f} … {r.z_max:.2f} mm, "
                f"{r.segments_added} Zusatzsegmente"
                + (f", Fokus-Absenkung je Durchgang bis {-r.focus_offset_min:.2f} mm"
                   if r.focus_offset_min < 0 else "") + ".")
        if self.warnings:
            text += "\n\nBitte prüfen:\n• " + "\n• ".join(self.warnings)
        return text


# ---------------------------------------------------------------- Prüfungen
def precheck_gcode(gcode: str) -> list[str]:
    """Fehler, die eine Kompensation ausschließen (Bögen, absolute Z-Wörter).

    Relative reine Z-Fahrten (Fokus-Absenkung je Durchgang) sind erlaubt.
    """
    errors: list[str] = []
    arcs = z_lines = 0
    absolute = True
    first_arc = first_z = 0
    for n, raw in enumerate(gcode.splitlines(), 1):
        code = re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0]).strip().upper()
        if not code:
            continue
        words = _WORD.findall(code)
        if any(k == "G" and float(v) in (2, 3) for k, v in words):
            arcs += 1
            first_arc = first_arc or n
        for k, v in words:
            if k == "G" and float(v) in (90, 91):
                absolute = float(v) == 90
        if any(k == "Z" for k, _ in words) and not is_relative_z_only(words, absolute):
            z_lines += 1
            first_z = first_z or n
    if arcs:
        errors.append(f"{arcs} Bogenbefehl(e) G2/G3 (erstmals Zeile {first_arc}). Die Fokuskorrektur "
                      "braucht Linien – Bögen vorher in Liniensegmente auflösen (der Canvas-Export "
                      "tut das automatisch; betroffen ist nur fremder G-Code).")
    if z_lines:
        errors.append(f"{z_lines} Zeile(n) mit absoluter Z-Angabe (erstmals Zeile {first_z}). Mit "
                      "Fokuskorrektur kommt Z aus dem Höhenmesh (plus ggf. „Fokus-Absenkung je "
                      "Durchgang“) – absolute Z-Fahrten entfernen oder ohne Korrektur exportieren.")
    return errors


def job_coverage(gcode: str, maps: HeightMapSet, step_mm: float = 1.0,
                 max_examples: int = 5) -> JobCoverage:
    """Brennstrecke (G1 mit S>0 bzw. modal) innerhalb/außerhalb der Meshes.

    Erwartet absolute mm-Koordinaten (G90/G21) wie vom Canvas-Export.
    """
    cov = JobCoverage()
    x = y = 0.0
    absolute, scale, motion, power = True, 1.0, 0, 0.0
    for raw in gcode.splitlines():
        code = re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0]).strip().upper()
        if not code:
            continue
        words = _WORD.findall(code)
        gs = [float(v) for k, v in words if k == "G"]
        for g in gs:
            if g == 20: scale = 25.4
            elif g == 21: scale = 1.0
            elif g == 90: absolute = True
            elif g == 91: absolute = False
            elif g in (0, 1): motion = int(g)
        vals = {k: float(v) for k, v in words if k in "XYS"}
        if "S" in vals:
            power = vals["S"]
        if "X" not in vals and "Y" not in vals:
            continue
        nx = (vals["X"] * scale if absolute else x + vals["X"] * scale) if "X" in vals else x
        ny = (vals["Y"] * scale if absolute else y + vals["Y"] * scale) if "Y" in vals else y
        if motion == 1 and power > 0:
            dist = math.hypot(nx - x, ny - y)
            n = max(1, math.ceil(dist / step_mm))
            piece = dist / n
            for k in range(n):
                t = (k + 0.5) / n
                px, py = x + (nx - x) * t, y + (ny - y) * t
                cov.burn_mm += piece
                if maps.map_for(px, py) is None:
                    cov.outside_mm += piece
                    if len(cov.outside_points) < max_examples and all(
                            math.hypot(px - a, py - b) > 10 for a, b in cov.outside_points):
                        cov.outside_points.append((px, py))
        x, y = nx, ny
    return cov


def highest_surface(maps: HeightMapSet) -> Optional[float]:
    vals = [float(np.nanmax(m.z)) for m in maps.maps if np.isfinite(m.z).any()]
    return max(vals) if vals else None


def lowest_surface(maps: HeightMapSet) -> Optional[float]:
    vals = [float(np.nanmin(m.z)) for m in maps.maps if np.isfinite(m.z).any()]
    return min(vals) if vals else None


def check_maps(maps: HeightMapSet, mosaic=None,
               now: Optional[float] = None, max_age_h: float = MAX_AGE_H) -> tuple[list[str], list[str]]:
    """Alter und Fingerabdruck des Meshes gegen den aktuellen Scan.

    Rückgabe ``(errors, warnings)``.
    """
    errors: list[str] = []
    warnings: list[str] = []
    now = time.time() if now is None else now
    if not maps.maps:
        return ["Höhenmesh ist leer."], []
    if maps.created:
        age_h = (now - maps.created) / 3600
        if age_h > max_age_h:
            warnings.append(f"Höhenmesh ist {age_h:.1f} h alt (> {max_age_h:g} h) – Material kann sich "
                            "verzogen haben. Im Zweifel neu proben.")
    else:
        warnings.append("Höhenmesh ohne Zeitstempel – Alter unbekannt.")
    if mosaic is None:
        warnings.append("Kein aktueller Scan zum Vergleich: Das Material darf seit dem Proben nicht "
                        "bewegt worden sein.")
        return errors, warnings
    if not maps.fingerprints:
        warnings.append("Höhenmesh hat keinen Bild-Fingerabdruck – kann nicht prüfen, ob das Material "
                        "seit dem Proben bewegt wurde.")
        return errors, warnings
    try:
        result = maps.check_material_unchanged(mosaic)
    except Exception as exc:  # pragma: no cover - defekter Fingerabdruck
        warnings.append(f"Fingerabdruck-Vergleich fehlgeschlagen: {exc}")
        return errors, warnings
    moved = [(aid, r) for aid, r in result.items() if not r["ok"]]
    for aid, r in moved:
        why = r.get("reason") or (f"Versatz {r['shift_mm']:.2f} mm, Ähnlichkeit {r['similarity']:.2f}")
        errors.append(f"Bereich {aid}: Material passt nicht mehr zum aktuellen Scan ({why}) – neu proben.")
    return errors, warnings


# ---------------------------------------------------------------- Export
def compensate_for_export(gcode: str, maps: Optional[HeightMapSet], *,
                          settings: Optional[FocusSettings] = None,
                          mosaic=None,
                          pi_surface_z: Optional[float] = None,
                          now: Optional[float] = None,
                          max_age_h: float = MAX_AGE_H) -> FocusExport:
    """Prüft und kompensiert. Der unkorrigierte ``gcode`` bleibt unverändert."""
    res = FocusExport()
    if maps is None or not maps.maps:
        res.errors.append("Kein Höhenmesh vorhanden – Höhenmesh messen (macht der Auftrag "
                          "automatisch) oder laden.")
        return res
    res.errors += precheck_gcode(gcode)
    errs, warns = check_maps(maps, mosaic, now, max_age_h)
    res.errors += errs
    res.warnings += warns
    res.coverage = cov = job_coverage(gcode, maps)
    if cov.burn_mm <= 0:
        res.errors.append("Der Auftrag enthält keine Brennstrecke.")
    elif cov.outside_mm >= cov.burn_mm - 1e-6:
        res.errors.append("Keine Brennstrecke liegt in einem Höhenmesh – Design und geprobte Bereiche "
                          "passen nicht zusammen.")
    fallback = highest_surface(maps)
    res.fallback_surface_z = fallback
    if fallback is None:
        res.errors.append("Höhenmesh enthält keine Messwerte.")
    if res.errors:
        return res
    if cov.outside_mm > 0.05:
        where = ", ".join(f"X{x:.0f} Y{y:.0f}" for x, y in cov.outside_points)
        res.warnings.append(
            f"{cov.outside_mm:.1f} mm von {cov.burn_mm:.1f} mm Brennstrecke "
            f"({cov.outside_fraction:.0%}) liegen außerhalb der geprobten Bereiche (z. B. {where}). "
            f"Dort gilt die höchste gemessene Oberfläche Z{fallback:.2f} (Fokus eher zu hoch, nie zu tief).")
    s = settings or FocusSettings()
    s = FocusSettings(**{**s.__dict__, "outside": "default", "default_surface_z": fallback})
    try:
        out, report = apply_focus_compensation(gcode, maps, s)
    except ValueError as exc:
        res.errors.append(str(exc))
        return res
    out = _explicit_first_cut_z(out)
    res.gcode, res.report = out, report
    for w in report.warnings:
        if "außerhalb" not in w:  # bereits oben mit Länge gemeldet
            res.warnings.append(w)
    if pi_surface_z is not None and math.isfinite(report.z_min):
        # Der Pi prüft jede Z-Fahrt gegen *eine* Oberfläche (letztes G30) + 2 mm.
        # Bei mehreren Werkstückhöhen bzw. Fokus-Absenkung würde er sonst mitten
        # im Auftrag abbrechen (Brennspur halb fertig) – daher hier ein Fehler.
        limit = pi_surface_z + s.min_clearance_mm
        if report.z_min < limit - 1e-6:
            low = lowest_surface(maps)
            why = []
            if low is not None and low < pi_surface_z - 0.05:
                why.append(f"niedrigster geprobter Bereich Z{low:.2f} liegt "
                           f"{pi_surface_z - low:.2f} mm unter der Pi-Oberfläche")
            if report.focus_offset_min < 0:
                why.append(f"Fokus-Absenkung bis {-report.focus_offset_min:.2f} mm (Tiefe je "
                           "Durchgang/3D-Stufen)")
            res.errors.append(
                f"Tiefste Fokushöhe Z{report.z_min:.2f} liegt unter der Pi-Sperre Z{limit:.2f} "
                f"(zuletzt am Pi gemessene Oberfläche {pi_surface_z:.2f} + {s.min_clearance_mm:g} mm)"
                + (" – " + "; ".join(why) if why else "") + ". Der Pi würde den Auftrag mitten im "
                "Lauf abbrechen. Fokus (G30) auf dem niedrigsten Werkstück antasten oder die "
                "Fokus-Absenkung verringern.")
            res.gcode = None
    return res


def _explicit_first_cut_z(gcode: str) -> str:
    """Erstes brennendes G1 bekommt ein explizites Z.

    Der Pi fokussiert vor der ersten Leistungsfahrt automatisch auf *seine*
    gemessene Oberfläche; ein explizites Z im ersten Segment führt sofort
    zurück auf die Mesh-Höhe.
    """
    lines = gcode.splitlines()
    z: Optional[float] = None
    for i, raw in enumerate(lines):
        code = raw.split(";", 1)[0].strip().upper()
        words = dict((k, v) for k, v in _WORD.findall(code))
        if code.startswith(("G0", "G1")) and "Z" in words:
            z = float(words["Z"])
        if code.startswith("G1 ") and "S" in words and float(words["S"]) > 0:
            if "Z" not in words and z is not None:
                zs = f"{z:.3f}".rstrip("0").rstrip(".")
                parts = raw.split(" ")
                # Z nach X/Y einfügen
                idx = max(i2 for i2, p in enumerate(parts) if p[:1] in "XY") + 1
                parts.insert(idx, f"Z{zs}")
                lines[i] = " ".join(parts)
            break
    return "\n".join(lines) + "\n"
