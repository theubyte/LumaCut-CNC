"""Materialdatenbank: Laden von ``materials.json``.

Die JSON-Datei ist das Austauschformat (auch außerhalb der App nutzbar).
``settings`` je Material ist eine vorberechnete Tabelle (siehe
:mod:`.build`); maßgeblich für die App sind die Modellparameter
``cut``/``engrave``/``relief``, aus denen :mod:`.planner` rechnet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).with_name("materials.json")
DEFAULT_LASER_ID = "lasertree_lt80w_aa_pro"


class MaterialError(ValueError):
    """Material/Operation nicht möglich oder nicht zulässig."""


@dataclass(frozen=True)
class Laser:
    id: str
    name: str
    optical_power_w: float
    spot_mm: float
    max_speed_mm_min: float
    wavelength_nm: int = 450
    focal_length_mm: float | None = None
    pwm_max: int = 255
    primary: bool = False
    notes: str = ""
    sources: tuple[str, ...] = ()

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Laser":
        return Laser(id=d["id"], name=d["name"], optical_power_w=float(d["optical_power_w"]),
                     spot_mm=float(d["spot_mm"]), max_speed_mm_min=float(d["max_speed_mm_min"]),
                     wavelength_nm=int(d.get("wavelength_nm", 450)),
                     focal_length_mm=d.get("focal_length_mm"), pwm_max=int(d.get("pwm_max", 255)),
                     primary=bool(d.get("primary", False)), notes=d.get("notes", ""),
                     sources=tuple(d.get("sources", ())))


@dataclass(frozen=True)
class Material:
    id: str
    name: str
    name_de: str
    category: str
    compatible: bool
    status: str  # ok | caution | engrave_only | unsafe | not_possible
    notes: str
    warnings: tuple[str, ...]
    air_assist: str
    sources: tuple[str, ...]
    thicknesses_mm: tuple[float, ...]
    cut: dict | None
    engrave: dict | None
    relief: dict | None
    settings: tuple[dict, ...] = field(default=(), compare=False, repr=False)
    # Schnittfuge/Haltestege/Anschnitt-Startwerte, s. :mod:`.process`
    process: dict | None = field(default=None, compare=False, repr=False)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Material":
        return Material(id=d["id"], name=d["name"], name_de=d.get("name_de", d["name"]),
                        category=d["category"], compatible=bool(d["compatible"]),
                        status=d.get("status", "ok"), notes=d.get("notes", ""),
                        warnings=tuple(d.get("warnings", ())), air_assist=d.get("air_assist", "on"),
                        sources=tuple(d.get("sources", ())),
                        thicknesses_mm=tuple(float(t) for t in d.get("thicknesses_mm", ())),
                        cut=d.get("cut"), engrave=d.get("engrave"), relief=d.get("relief"),
                        settings=tuple(d.get("settings", ())), process=d.get("process"))

    @property
    def can_cut(self) -> bool:
        return self.compatible and self.cut is not None

    @property
    def can_engrave(self) -> bool:
        return self.compatible and self.engrave is not None

    @property
    def can_engrave_depth(self) -> bool:
        return self.can_engrave and "ref_depth_mm" in self.engrave

    @property
    def can_relief(self) -> bool:
        return self.can_engrave_depth and bool(self.relief and self.relief.get("suitable"))

    def operations(self) -> list[str]:
        """Mögliche Operationen in Anzeige-Reihenfolge."""
        ops = []
        if self.can_cut:
            ops.append("cut")
        if self.can_engrave:
            ops.append("engrave_surface")
        if self.can_engrave_depth:
            ops += ["engrave_shallow", "engrave_medium", "engrave_deep"]
        if self.can_relief:
            ops.append("relief")
        return ops


OPERATION_LABELS = {"cut": "Schneiden", "engrave_surface": "Gravur Oberfläche",
                    "engrave_shallow": "Gravur flach", "engrave_medium": "Gravur mittel",
                    "engrave_deep": "Gravur tief", "relief": "3D-Relief"}


class MaterialDB:
    def __init__(self, data: dict[str, Any]) -> None:
        if data.get("format") != "lumacut-materials":
            raise ValueError("Keine LumaCut-Materialdatei")
        self.raw = data
        self.model: dict[str, Any] = data["model"]
        self.disclaimer: str = data.get("disclaimer", "")
        self.relief_guide: dict[str, Any] = data.get("relief_guide", {})
        self.lasers: list[Laser] = [Laser.from_dict(l) for l in data["lasers"]]
        self.materials: list[Material] = [Material.from_dict(m) for m in data["materials"]]
        ids = [m.id for m in self.materials]
        if len(ids) != len(set(ids)):
            raise ValueError("Doppelte Material-IDs")

    # --- Abfragen -------------------------------------------------------------
    def material(self, material_id: str) -> Material:
        for m in self.materials:
            if m.id == material_id:
                return m
        raise KeyError(material_id)

    def laser(self, laser_id: str | None = None) -> Laser:
        laser_id = laser_id or self.default_laser.id
        for l in self.lasers:
            if l.id == laser_id:
                return l
        raise KeyError(laser_id)

    @property
    def default_laser(self) -> Laser:
        return next((l for l in self.lasers if l.primary), None) or self.laser(DEFAULT_LASER_ID)

    def compatible(self) -> list[Material]:
        return [m for m in self.materials if m.compatible]

    def incompatible(self) -> list[Material]:
        return [m for m in self.materials if not m.compatible]

    def check(self, material_id: str) -> list[str]:
        """Warnungen zu einem Material (leer = keine Bedenken)."""
        m = self.material(material_id)
        out = list(m.warnings)
        if not m.compatible:
            out.insert(0, f"NICHT LASERN: {m.name_de} – {m.notes}")
        return out

    def search(self, text: str) -> list[Material]:
        t = text.lower()
        return [m for m in self.materials if t in m.name.lower() or t in m.name_de.lower()]


def load_db(path: str | Path | None = None) -> MaterialDB:
    if path is None:
        return _default_db()
    return MaterialDB(json.loads(Path(path).read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def _default_db() -> MaterialDB:
    return MaterialDB(json.loads(DATA_PATH.read_text(encoding="utf-8")))
