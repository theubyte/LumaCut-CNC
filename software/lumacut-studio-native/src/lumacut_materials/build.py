"""Erzeugt die ``settings``-Tabellen in ``materials.json``.

    python -m lumacut_materials.build [pfad]

Für jedes Material, jede Dicke und jeden Laser (LT-80W + generische
5/10/20/40-W-Profile) werden Schneid- und Gravurwerte mit :mod:`.planner`
berechnet und als flache Tabelle gespeichert (Schema:
``thickness_mm, op, laser_id, laser_power_w, speed_mm_min, power_pct, passes,
line_interval_mm, depth_per_pass_mm, z_step_mm``). Ein Test stellt sicher,
dass die Tabelle zum Modell passt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .db import DATA_PATH, MaterialDB, MaterialError
from .planner import plan_cut, plan_engrave


def settings_for(db: MaterialDB, material_id: str) -> list[dict]:
    m = db.material(material_id)
    rows: list[dict] = []
    if not m.compatible:
        return rows

    def row(p, thickness, op):
        lz = db.laser(p.laser_id)
        return {"thickness_mm": thickness, "op": op, "laser_id": lz.id,
                "laser_power_w": lz.optical_power_w, "speed_mm_min": p.speed_mm_min,
                "power_pct": p.power_pct, "passes": p.passes,
                "line_interval_mm": p.line_interval_mm, "depth_per_pass_mm": p.depth_per_pass_mm,
                "z_step_mm": p.z_step_mm}

    for lz in db.lasers:
        if m.can_cut:
            for t in m.thicknesses_mm:
                try:
                    rows.append(row(plan_cut(db, m, t, lz), t, "cut"))
                except MaterialError:
                    pass
        if m.can_engrave:
            for level in (("surface", "shallow", "medium", "deep") if m.can_engrave_depth
                          else ("surface",)):
                rows.append(row(plan_engrave(db, m, level, lz), None, f"engrave_{level}"))
    return rows


def build(path: Path = DATA_PATH) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for m in data["materials"]:
        m["settings"] = []
    db = MaterialDB(data)
    for m in data["materials"]:
        m["settings"] = settings_for(db, m["id"])
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


if __name__ == "__main__":  # pragma: no cover
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_PATH
    d = build(target)
    n = sum(len(m["settings"]) for m in d["materials"])
    print(f"{target}: {len(d['materials'])} Materialien, {n} Tabellenzeilen")
