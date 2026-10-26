"""Material-Grundlage für die Ebenen: Dicke, Tiefe je Durchgang, Durchgänge.

Qt-frei. Eine Ebene kann optional ein Material (Name + Dicke) und eine
Tiefe je Durchgang tragen. Daraus ergibt sich die Zahl der Durchgänge::

    Tiefe    = Zieltiefe (``target_depth_mm``) oder, wenn 0, Materialdicke
    passes   = ceil(Tiefe / depth_per_pass_mm)       (begrenzt auf PASSES_RANGE)

Der Wert ist *abgeleitet, aber überschreibbar*: :func:`material_layer_attrs`
liefert die abgeleiteten Durchgänge für ``Document.update_layer``; setzt der
Nutzer ``passes`` danach von Hand, gilt sein Wert. :func:`layer_pass_plan`
rechnet immer mit den tatsächlich eingestellten ``layer.passes`` und meldet
über :attr:`PassPlan.reaches_target`, ob die Tiefe damit erreicht wird.

Die Feldnamen (``thickness_mm``, ``depth_per_pass_mm``) entsprechen
``lumacut_materials.presets.Preset``; :func:`material_from_preset` übernimmt
ein solches Preset, ohne dass dieses Modul davon abhängt.

ACHTUNG: :data:`BUILTIN_MATERIALS` sind *editierbare Startwerte* für eigene
Testschnitte, keine geprüften Empfehlungen. Laserleistung, Optik, Fokus und
Materialcharge verändern das Ergebnis stark – immer erst einen Materialtest
laufen lassen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

PASSES_RANGE = (1, 30)              # wie model.PASSES_RANGE (zirkulären Import vermeiden)
THICKNESS_RANGE = (0.0, 50.0)       # mm
DEPTH_PER_PASS_RANGE = (0.0, 10.0)  # mm, 0 = keine Tiefenplanung
_EPS = 1e-9


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class Material:
    """Ein Material mit Dicke und optionalen Startwerten für die Ebene."""

    name: str
    thickness_mm: float
    depth_per_pass_mm: float = 0.0
    power: float | None = None       # % – optionale Startwerte
    speed: float | None = None       # mm/min
    z_step: float | None = None      # mm Fokus-Absenkung je Durchgang
    notes: str = ""

    def normalized(self) -> "Material":
        return replace(self, name=str(self.name).strip() or "Material",
                       thickness_mm=round(_clamp(float(self.thickness_mm), *THICKNESS_RANGE), 3),
                       depth_per_pass_mm=round(_clamp(float(self.depth_per_pass_mm),
                                                      *DEPTH_PER_PASS_RANGE), 3))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "thickness_mm": self.thickness_mm,
                             "depth_per_pass_mm": self.depth_per_pass_mm}
        for k in ("power", "speed", "z_step"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.notes:
            d["notes"] = self.notes
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Material":
        opt = {k: (None if d.get(k) is None else float(d[k])) for k in ("power", "speed", "z_step")}
        return Material(name=str(d.get("name", "Material")),
                        thickness_mm=float(d.get("thickness_mm", 0.0)),
                        depth_per_pass_mm=float(d.get("depth_per_pass_mm", 0.0)),
                        notes=str(d.get("notes", "")), **opt).normalized()


_START = "Editierbarer Startwert, nicht validiert – vorher Materialtest machen."

#: Kleine eingebaute Liste – editierbare STARTWERTE, keine geprüften Empfehlungen.
BUILTIN_MATERIALS: tuple[Material, ...] = (
    Material("Pappelsperrholz 3 mm", 3.0, 1.0, power=100.0, speed=300.0, notes=_START),
    Material("Pappelsperrholz 4 mm", 4.0, 1.0, power=100.0, speed=250.0, notes=_START),
    Material("MDF 3 mm", 3.0, 0.75, power=100.0, speed=250.0, notes=_START),
    Material("Acryl (gegossen) 3 mm", 3.0, 1.0, power=100.0, speed=200.0, notes=_START),
    Material("Graukarton 1,5 mm", 1.5, 0.75, power=80.0, speed=600.0, notes=_START),
)


def builtin_material(name: str) -> Material:
    for m in BUILTIN_MATERIALS:
        if m.name == name:
            return m
    raise KeyError(name)


def material_from_preset(preset: Any, name: str | None = None) -> Material:
    """Aus einem ``lumacut_materials``-Preset (duck-typed) ein Material machen."""
    return Material(name=name or str(getattr(preset, "name", "Material")),
                    thickness_mm=float(getattr(preset, "thickness_mm", 0.0) or 0.0),
                    depth_per_pass_mm=float(getattr(preset, "depth_per_pass_mm", 0.0) or 0.0),
                    power=getattr(preset, "power_pct", None),
                    speed=getattr(preset, "speed_mm_min", None),
                    z_step=getattr(preset, "z_step_mm", None)).normalized()


def passes_for_depth(depth_mm: float, depth_per_pass_mm: float) -> int:
    """``ceil(depth / depth_per_pass)``, begrenzt auf PASSES_RANGE (min. 1)."""
    if depth_per_pass_mm <= 0 or depth_mm <= 0:
        return PASSES_RANGE[0]
    n = math.ceil(depth_mm / depth_per_pass_mm - _EPS)
    return int(_clamp(n, *PASSES_RANGE))


@dataclass(frozen=True)
class PassPlan:
    """Tiefen je Durchgang für eine Ebene."""

    depth_mm: float                  # Zieltiefe
    depth_per_pass_mm: float
    pass_depths: tuple[float, ...]   # Tiefe, die der jeweilige Durchgang abträgt

    @property
    def passes(self) -> int:
        return len(self.pass_depths)

    @property
    def total_mm(self) -> float:
        return round(sum(self.pass_depths), 6)

    @property
    def cumulative(self) -> tuple[float, ...]:
        """Erreichte Tiefe nach jedem Durchgang."""
        out, acc = [], 0.0
        for d in self.pass_depths:
            acc += d
            out.append(round(acc, 6))
        return tuple(out)

    @property
    def reaches_target(self) -> bool:
        return self.total_mm + 1e-6 >= self.depth_mm


def plan_passes(depth_mm: float, depth_per_pass_mm: float,
                passes: int | None = None) -> PassPlan:
    """Liste der Tiefen je Durchgang.

    Ohne ``passes`` wird die Anzahl abgeleitet (:func:`passes_for_depth`).
    Mit ``passes`` (Nutzer-Override) trägt jeder Durchgang höchstens
    ``depth_per_pass_mm`` ab; überzählige Durchgänge haben Tiefe 0
    (Nachschnitt), zu wenige erreichen die Zieltiefe nicht.
    """
    depth = max(0.0, float(depth_mm))
    dpp = float(depth_per_pass_mm)
    if dpp <= 0:
        raise ValueError("depth_per_pass_mm muss > 0 sein")
    n = passes_for_depth(depth, dpp) if passes is None else int(_clamp(int(passes), *PASSES_RANGE))
    left, out = depth, []
    for _ in range(n):
        d = min(dpp, left) if left > _EPS else 0.0
        out.append(round(d, 6))
        left -= d
    return PassPlan(depth, dpp, tuple(out))


def layer_depth_mm(layer: Any) -> float:
    """Zieltiefe der Ebene: ``target_depth_mm`` oder sonst Materialdicke."""
    t = float(getattr(layer, "target_depth_mm", 0.0) or 0.0)
    return t if t > 0 else float(getattr(layer, "thickness_mm", 0.0) or 0.0)


def layer_pass_plan(layer: Any) -> PassPlan | None:
    """Plan mit den eingestellten ``layer.passes``; None ohne Tiefenplanung."""
    dpp = float(getattr(layer, "depth_per_pass_mm", 0.0) or 0.0)
    depth = layer_depth_mm(layer)
    if dpp <= 0 or depth <= 0:
        return None
    return plan_passes(depth, dpp, int(layer.passes))


def derived_passes(layer: Any) -> int | None:
    """Abgeleitete Durchgänge (ohne Override) oder None ohne Tiefenplanung."""
    dpp = float(getattr(layer, "depth_per_pass_mm", 0.0) or 0.0)
    depth = layer_depth_mm(layer)
    return passes_for_depth(depth, dpp) if dpp > 0 and depth > 0 else None


def material_layer_attrs(material: Material, target_depth_mm: float = 0.0,
                         apply_settings: bool = True) -> dict[str, Any]:
    """Attribute für ``Document.update_layer`` bzw. ``SetLayerAttrsCommand``.

    Setzt Material, Dicke, Zieltiefe, Tiefe je Durchgang und die abgeleiteten
    Durchgänge; mit ``apply_settings`` auch die optionalen Startwerte
    (Leistung, Geschwindigkeit, Fokus-Absenkung).
    """
    m = material.normalized()
    attrs: dict[str, Any] = {"material": m.name, "thickness_mm": m.thickness_mm,
                             "target_depth_mm": max(0.0, float(target_depth_mm)),
                             "depth_per_pass_mm": m.depth_per_pass_mm}
    depth = attrs["target_depth_mm"] or m.thickness_mm
    if m.depth_per_pass_mm > 0 and depth > 0:
        attrs["passes"] = passes_for_depth(depth, m.depth_per_pass_mm)
    if apply_settings:
        for k in ("power", "speed", "z_step"):
            if getattr(m, k) is not None:
                attrs[k] = float(getattr(m, k))
    return attrs
