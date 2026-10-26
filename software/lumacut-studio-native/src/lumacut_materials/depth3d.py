"""Brücke Materialbibliothek → Bild-Modus ``depth3d`` (:func:`lumacut_job.raster.sliced_depth_gcode`).

Es gibt zwei Wege zur Tiefengravur aus einer Höhenkarte:

* :mod:`lumacut_materials.relief` – variable Leistung je Bildpunkt, Schichten
  mit gleicher Geschwindigkeit (eigener Generator, Relief-Dialog).
* ``depth3d`` im Bild-Objekt – Schnitte konstanter Leistung (``depth_levels``),
  tiefe Pixel werden in mehr Schichten gelasert, Fokus je Stufe ``z_step_mm``.

Beide nutzen hier denselben Schichtplan (:func:`.planner.plan_relief`): eine
Schicht trägt ``layer_depth_mm`` ab, also ``depth_levels = Schichten``. So
liefern beide Wege für dasselbe Material die gleiche Gesamttiefe, und die
Grenzen (≤ 64 Stufen, Fokusabsenkung ≤ 3 mm) bleiben eingehalten.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .db import MaterialDB
from .planner import plan_relief

MAX_LEVELS = 64


def depth3d_image_settings(db: MaterialDB, material_id: str, depth_mm: float,
                           laser_id: str | None = None,
                           line_interval_mm: float | None = None) -> dict[str, Any]:
    """Felder für ``ImageSettings`` (Modus ``depth3d``) aus dem Reliefplan.

    Wirft ``MaterialError``/``ValueError`` wie :func:`plan_relief`.
    """
    p = plan_relief(db, material_id, depth_mm, laser_id, line_interval_mm)
    levels = max(2, min(MAX_LEVELS, int(p.passes)))
    return {
        "mode": "depth3d",
        "line_interval_mm": float(p.line_interval_mm),
        "power": float(p.power_pct),
        "min_power": 0.0,
        "speed_mm_min": float(p.speed_mm_min),
        "passes": 1,
        "depth_levels": levels,
        "z_step_mm": float(p.z_step_mm),
    }


def apply_to_image_settings(settings: Any, fields: dict[str, Any]) -> Any:
    """``ImageSettings`` mit den Feldern ersetzen (normalisiert)."""
    return replace(settings, **fields).normalized()
