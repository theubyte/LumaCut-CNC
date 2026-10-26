"""Schnittfuge (Kerf), Haltestege (Tabs) und Anschnitt (Lead-in) je Material.

Startwerte für die Bahnplanung beim **Schneiden**. Die Materialdatenbank
trägt je schneidbarem Material einen ``process``-Block (erzeugt von
:mod:`.build` aus :data:`PROCESS_TABLE`)::

    kerf_mm      = kerf_base_mm · √(Spot / 0,08 mm) + kerf_per_mm · Dicke
    tab_width_mm = tab_base_mm + tab_per_mm · Dicke   (0,2 … 3 mm)
    tab_spacing_mm, lead_in_mm                         (fest je Material)

Alle Werte sind Schätzungen für einen 10-W-Diodenlaser (Spot ≈ 0,08 mm) und
**nicht an der Maschine gemessen**: Kerf vor Passteilen immer mit einem
Testquadrat nachmessen (Soll − Ist = Kerf).

``kerf_mm`` hier ist die **Schnittbreite**. Die Ebene (``Layer.kerf_mm``,
:mod:`lumacut_job.cutpath`) erwartet den **Versatz** zur Abfallseite, also
die halbe Schnittbreite (:attr:`ProcessDefaults.kerf_offset_mm`).

:func:`layer_process_attrs` prüft zur Laufzeit, welche Felder die Ebene hat
(Feature-Check), und setzt nur Größen, nie Schalter:

* Kerf-Versatz und Stegbreite werden gesetzt.
* Stegabstand und Anfahrt nur, wenn die Ebene sie schon nutzt (> 0) –
  ``tab_spacing_mm > 0`` bzw. ``lead_in_mm > 0`` würden sie sonst einschalten.
* Beim Neuplanen einer verknüpften Ebene (``previous``) bleiben von Hand
  geänderte Werte stehen: überschrieben wird nur, was noch dem alten
  Material-Startwert (oder dem Ebenen-Standard) entspricht.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .db import MaterialDB, MaterialError

REF_SPOT_MM = 0.08

# Kategorie/Material → (kerf_base_mm, kerf_per_mm, tab_base_mm, tab_per_mm,
#                       tab_spacing_mm, lead_in_mm)
_WOOD = (0.10, 0.025, 0.30, 0.06, 40.0, 1.0)
PROCESS_TABLE: dict[str, tuple[float, float, float, float, float, float]] = {
    "basswood_plywood": _WOOD, "birch_plywood": _WOOD, "basswood_solid": _WOOD,
    "mdf": (0.10, 0.03, 0.30, 0.06, 40.0, 1.0),
    "hardwood": (0.10, 0.03, 0.30, 0.06, 40.0, 1.0),
    "softwood": _WOOD, "bamboo": _WOOD,
    "balsa": (0.10, 0.02, 0.40, 0.08, 30.0, 0.5),
    "cork": (0.15, 0.03, 0.50, 0.08, 30.0, 0.5),
    "cardboard": (0.10, 0.02, 0.30, 0.05, 30.0, 0.0),
    "paper": (0.08, 0.02, 0.20, 0.00, 25.0, 0.0),
    "leather_veg": (0.12, 0.03, 0.40, 0.05, 30.0, 0.5),
    "felt_wool": (0.15, 0.02, 0.50, 0.05, 30.0, 0.0),
    "cotton_fabric": (0.12, 0.02, 0.50, 0.00, 25.0, 0.0),
    "acrylic_black": (0.10, 0.02, 0.30, 0.05, 50.0, 1.0),
    "acrylic_color_opaque": (0.10, 0.02, 0.30, 0.05, 50.0, 1.0),
    "eva_foam": (0.20, 0.03, 0.80, 0.10, 30.0, 0.5),
    "laser_rubber": (0.15, 0.03, 0.50, 0.08, 30.0, 0.5),
}
PROCESS_KEYS = ("kerf_mm", "tab_width_mm", "tab_spacing_mm", "lead_in_mm")

# Mögliche Feldnamen an der Canvas-Ebene (der Planer legt sie fest; die
# erste vorhandene Variante gewinnt).
LAYER_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "kerf_mm": ("kerf_mm", "kerf_offset_mm", "kerf"),
    "tab_width_mm": ("tab_width_mm", "tab_mm", "tabs_width_mm"),
    "tab_spacing_mm": ("tab_spacing_mm", "tab_distance_mm", "tabs_spacing_mm"),
    "lead_in_mm": ("lead_in_mm", "leadin_mm", "lead_in_length_mm"),
}


def process_block(material_id: str) -> dict | None:
    """``process``-Block für die JSON-Datenbank (von :mod:`.build` genutzt)."""
    row = PROCESS_TABLE.get(material_id)
    if row is None:
        return None
    keys = ("kerf_base_mm", "kerf_per_mm", "tab_base_mm", "tab_per_mm", "tab_spacing_mm",
            "lead_in_mm")
    return {**dict(zip(keys, row)), "status": "estimate"}


@dataclass(frozen=True)
class ProcessDefaults:
    kerf_mm: float
    tab_width_mm: float
    tab_spacing_mm: float
    lead_in_mm: float

    @property
    def kerf_offset_mm(self) -> float:
        """Versatz je Seite = halbe Schnittbreite (für ``Layer.kerf_mm``)."""
        return round(self.kerf_mm / 2.0, 3)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def layer_values(self) -> dict[str, float]:
        """Werte in Ebenen-Semantik (Kerf als Versatz)."""
        return {**self.to_dict(), "kerf_mm": self.kerf_offset_mm}

    def summary(self) -> str:
        parts = [f"Kerf {self.kerf_mm:.2f} mm (Versatz {self.kerf_offset_mm:.3f} mm)", f"Stege {self.tab_width_mm:.1f} mm / "
                 f"{self.tab_spacing_mm:g} mm"]
        if self.lead_in_mm:
            parts.append(f"Anschnitt {self.lead_in_mm:g} mm")
        return ", ".join(parts)


def process_defaults(db: MaterialDB, material_id: str, thickness_mm: float,
                     laser_id: str | None = None) -> ProcessDefaults | None:
    """Startwerte für Material/Dicke/Laser; ``None`` wenn nicht schneidbar."""
    m = db.material(material_id)
    block = m.process
    if not m.can_cut or not block:
        return None
    t = float(thickness_mm or 0.0)
    if t <= 0:
        raise MaterialError("Dicke fehlt")
    lz = db.laser(laser_id) if laser_id else next(l for l in db.lasers if l.primary)
    spot = float(getattr(lz, "spot_mm", REF_SPOT_MM) or REF_SPOT_MM)
    kerf = block["kerf_base_mm"] * math.sqrt(spot / REF_SPOT_MM) + block["kerf_per_mm"] * t
    tab = min(3.0, max(0.2, block["tab_base_mm"] + block["tab_per_mm"] * t))
    return ProcessDefaults(kerf_mm=round(max(spot, kerf), 3), tab_width_mm=round(tab, 2),
                           tab_spacing_mm=float(block["tab_spacing_mm"]),
                           lead_in_mm=float(block["lead_in_mm"]))


def layer_process_fields(layer: Any) -> dict[str, str]:
    """Feature-Check: Prozess-Schlüssel → vorhandenes Ebenen-Feld."""
    out: dict[str, str] = {}
    for key, names in LAYER_FIELD_CANDIDATES.items():
        for n in names:
            if hasattr(layer, n):
                out[key] = n
                break
    return out


# Ebenen-Standardwerte (lumacut_canvas.model.CUT_LAYER_DEFAULTS), als
# "unverändert" gewertet.
_LAYER_DEFAULTS = {"kerf_mm": 0.0, "tab_width_mm": 1.0, "tab_spacing_mm": 0.0, "lead_in_mm": 0.0}
# Größen, die nur gesetzt werden, wenn die Ebene die Funktion schon nutzt.
_ONLY_IF_ACTIVE = ("tab_spacing_mm", "lead_in_mm")


def layer_process_attrs(layer: Any, defaults: ProcessDefaults | None,
                        previous: ProcessDefaults | None = None) -> dict[str, float]:
    """Ebenen-Attribute für die vorhandenen Felder (Feature-Check).

    ``previous``: Startwerte vor einer Dickenänderung; dann wird nur
    überschrieben, was der Nutzer nicht von Hand geändert hat.
    """
    if defaults is None:
        return {}
    values = defaults.layer_values()
    old = previous.layer_values() if previous is not None else None
    out: dict[str, float] = {}
    for key, field_name in layer_process_fields(layer).items():
        current = getattr(layer, field_name, None)
        if key in _ONLY_IF_ACTIVE and not (isinstance(current, (int, float)) and current > 0):
            continue
        if old is not None and isinstance(current, (int, float)):
            untouched = (abs(current - old[key]) < 1e-6
                         or abs(current - _LAYER_DEFAULTS.get(key, 0.0)) < 1e-6)
            if not untouched:
                continue
        out[field_name] = values[key]
    return out
