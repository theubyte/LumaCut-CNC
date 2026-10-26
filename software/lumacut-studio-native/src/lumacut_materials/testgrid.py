"""Materialtest-Raster (``lumacut_job.material_test``) → eigenes Preset.

Das Testraster legt je Zelle eine echte Ebene ``"Test P<Leistung>% F<mm/min>"``
an. Nach dem Testlauf wählt der Nutzer die beste Zelle (Ebene) und speichert
deren Leistung/Geschwindigkeit/Durchgänge als eigenes Preset für
Material/Dicke/Operation/Laser. Maßgeblich sind die *Ebenenwerte* (falls der
Nutzer eine Zelle noch angepasst hat), nicht nur der Name.

Qt-frei.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .db import OPERATION_LABELS, MaterialDB, MaterialError
from .planner import MAX_PASSES, plan
from .presets import Preset

TEST_CELL_RE = re.compile(r"^Test P(?P<power>\d+(?:\.\d+)?)% F(?P<speed>\d+(?:\.\d+)?)$")


def is_test_cell(layer: Any) -> bool:
    return bool(TEST_CELL_RE.match(str(getattr(layer, "name", ""))))


def find_test_cells(doc: Any) -> list[Any]:
    """Alle Testzellen-Ebenen eines Dokuments (Reihenfolge wie im Panel)."""
    return [l for l in getattr(doc, "layers", []) if is_test_cell(l)]


def preset_from_test_cell(db: MaterialDB, layer: Any, material_id: str, op: str,
                          thickness_mm: float | None = None, laser_id: str | None = None,
                          name: str | None = None, depth_mm: float | None = None) -> Preset:
    """Preset aus einer Testzellen-Ebene.

    Leistung/Geschwindigkeit/Durchgänge/Fokus-Absenkung kommen aus der Ebene;
    Zeilenabstand, Luft und Warnungen aus der Bibliotheksplanung für dieselbe
    Auswahl. Beim Schneiden gilt: die Zelle ist durchgeschnitten, also
    Tiefe je Durchgang = Dicke / Durchgänge.
    """
    if not is_test_cell(layer):
        raise MaterialError(f"Keine Testzelle: {getattr(layer, 'name', '?')}")
    m = db.material(material_id)
    if not m.compatible:
        raise MaterialError(f"{m.name_de}: nicht lasern")
    if op not in m.operations():
        raise MaterialError(f"{m.name_de}: Operation {op} nicht möglich")
    if op == "cut" and not thickness_mm:
        raise MaterialError("Dicke fehlt")
    try:
        ref = plan(db, material_id, op, thickness_mm, laser_id, depth_mm)
        laser = ref.laser_id
        line_interval = ref.line_interval_mm
        warnings = [w for w in ref.warnings if "Durchgänge" not in w]
        air = ref.air_assist
        plan_depth = float(getattr(ref, "target_depth_mm", 0.0) or getattr(ref, "max_depth_mm", 0.0) or 0.0)
    except (MaterialError, ValueError):
        laser = laser_id or next(l.id for l in db.lasers if l.primary)
        line_interval, warnings, air, plan_depth = None, [], m.air_assist, 0.0
    passes = int(min(MAX_PASSES, max(1, int(getattr(layer, "passes", 1)))))
    if op == "cut":
        dpp = math.ceil(float(thickness_mm) / passes * 1000) / 1000
    else:
        depth = float(depth_mm or plan_depth or 0.0)
        dpp = round(depth / passes, 3) if depth else 0.0
    power = float(getattr(layer, "power"))
    speed = float(getattr(layer, "speed"))
    th = f" {thickness_mm:g} mm" if thickness_mm else ""
    default = f"{m.name_de}{th} – {OPERATION_LABELS.get(op, op)} (Test P{power:g}% F{speed:g})"
    return Preset(name=(name or default).strip(), material_id=m.id, op=op, laser_id=laser,
                  thickness_mm=thickness_mm, power_pct=power, speed_mm_min=speed, passes=passes,
                  z_step_mm=float(getattr(layer, "z_step", 0.0) or 0.0), depth_per_pass_mm=dpp,
                  line_interval_mm=line_interval, air_assist=air,
                  notes=f"Aus Materialtest übernommen ({getattr(layer, 'name', '')}).",
                  warnings=warnings, source="test")
