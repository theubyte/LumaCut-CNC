"""Planung: Schneiden, Gravieren und 3D-Relief für einen Laser.

Tiefenmodell (kalibriert an den 5/10/20/40-W-Tabellen von xTool für
Pappelsperrholz, siehe ``model.description`` in der JSON-Datei)::

    d = d_ref · (E / E_ref)^β · (P_eff / P_eff_ref)^α

* Schneiden: ``E = P_eff / v``              (W·min/mm, Linienenergie)
* Gravieren: ``E = P_eff / (v · Zeilenabstand)`` (Flächenenergie)
* ``P_eff = P_optisch · Leistung%``; ``β`` < 1 bildet Verkohlung/Abschattung
  nach, ``α`` > 0 die bessere Kopplung stärkerer Laser.

Alle Ergebnisse sind Startwerte, nicht an der Maschine verifiziert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .db import Laser, Material, MaterialDB, MaterialError

# Grenzen aus dem Canvas-Modell / der Pi-Firmware (Qt-frei dupliziert, damit
# dieses Modul ohne lumacut_canvas nutzbar bleibt; ein Test prüft Gleichheit).
MAX_PASSES = 30
MAX_FOCUS_DROP_MM = 3.0
MAX_Z_STEP_MM = 2.0
WARN_PASSES = 12
ENGRAVE_LEVELS = ("surface", "shallow", "medium", "deep")


def _round_speed(v: float) -> float:
    """Auf 10 mm/min abrunden (langsamer = sicherer für die Tiefe), min. 1."""
    return max(1.0, math.floor(v / 10.0) * 10.0) if v >= 10 else max(1.0, round(v, 1))


def _ref(block: dict, model: dict, li: float | None = None) -> tuple[float, float]:
    """(E_ref, P_eff_ref) eines Referenzblocks."""
    p_ref = float(block.get("ref_power_w", model["reference_power_w"]))
    p_eff_ref = p_ref * float(block["ref_power_pct"]) / 100.0
    e_ref = p_eff_ref / float(block["ref_speed_mm_min"])
    if li is not None:
        e_ref /= li
    return e_ref, p_eff_ref


def depth_per_pass(block: dict, model: dict, p_eff: float, speed: float,
                   line_interval: float | None = None) -> float:
    """Modelltiefe je Durchgang in mm (Gravur, wenn ``line_interval`` gesetzt)."""
    li_ref = block.get("ref_line_interval_mm") if line_interval is not None else None
    e_ref, p_eff_ref = _ref(block, model, li_ref)
    e = p_eff / speed / (line_interval if line_interval is not None else 1.0)
    return (float(block["ref_depth_mm"]) * (e / e_ref) ** model["beta"]
            * (p_eff / p_eff_ref) ** model["alpha"])


def speed_for_depth(block: dict, model: dict, p_eff: float, depth: float,
                    line_interval: float | None = None) -> float:
    """Geschwindigkeit, bei der ``depth`` je Durchgang erreicht wird."""
    li_ref = block.get("ref_line_interval_mm") if line_interval is not None else None
    e_ref, p_eff_ref = _ref(block, model, li_ref)
    scale = float(block["ref_depth_mm"]) * (p_eff / p_eff_ref) ** model["alpha"]
    e = e_ref * (depth / scale) ** (1.0 / model["beta"])
    return p_eff / e / (line_interval if line_interval is not None else 1.0)


def power_for_depth(block: dict, model: dict, speed: float, depth: float,
                    line_interval: float | None = None) -> float:
    """Effektive Leistung (W), die bei ``speed`` die Tiefe ``depth`` ergibt."""
    li_ref = block.get("ref_line_interval_mm") if line_interval is not None else None
    e_ref, p_eff_ref = _ref(block, model, li_ref)
    b, a = model["beta"], model["alpha"]
    k = speed * (line_interval if line_interval is not None else 1.0) * e_ref
    return (depth / float(block["ref_depth_mm"]) * k ** b * p_eff_ref ** a) ** (1.0 / (b + a))


def _root(laser: Laser, model: dict) -> float:
    return math.sqrt(laser.optical_power_w / model["reference_power_w"])


def _focus_step(depth_pp: float, passes: int, model: dict, min_total: float) -> float:
    """Fokus-Absenkung je Durchgang (Summe ≤ 3 mm, Pi-Tastsicherheit)."""
    if passes < 2 or min_total < 2.0:
        return 0.0
    z = min(depth_pp * model.get("focus_follow", 0.7), MAX_Z_STEP_MM,
            MAX_FOCUS_DROP_MM / (passes - 1))
    return math.floor(z * 100) / 100


@dataclass
class _Base:
    material_id: str
    laser_id: str
    op: str
    speed_mm_min: float
    power_pct: float
    passes: int
    depth_per_pass_mm: float
    z_step_mm: float
    line_interval_mm: float | None
    air_assist: str
    warnings: list[str] = field(default_factory=list)

    @property
    def focus_offsets_mm(self) -> list[float]:
        """Fokuslage je Durchgang relativ zum Start (negativ = tiefer)."""
        return [round(-i * self.z_step_mm, 3) for i in range(self.passes)]

    @property
    def feasible(self) -> bool:
        return 1 <= self.passes <= MAX_PASSES


@dataclass
class CutPlan(_Base):
    thickness_mm: float = 0.0
    focus_start_mm: float = 0.0  # Empfehlung, nur Hinweis (Pi fokussiert selbst)


@dataclass
class EngravePlan(_Base):
    level: str = "surface"
    target_depth_mm: float = 0.0


@dataclass
class ReliefPlan(_Base):
    max_depth_mm: float = 0.0
    layer_depth_mm: float = 0.0
    finish_speed_mm_min: float = 0.0
    finish_power_pct: float = 0.0


def _clamp_to_vmax(block, model, laser, p_eff, depth, v, li=None) -> tuple[float, float]:
    """Begrenzt v auf die Maschinengeschwindigkeit und senkt dafür die Leistung."""
    if v <= laser.max_speed_mm_min:
        return v, p_eff
    v = laser.max_speed_mm_min
    return v, min(p_eff, power_for_depth(block, model, v, depth, li))


def plan_cut(db: MaterialDB, material: Material | str, thickness_mm: float,
             laser: Laser | str | None = None) -> CutPlan:
    """Durchgänge, Tiefe je Durchgang, Z-Absenkung, Geschwindigkeit, Leistung."""
    m = db.material(material) if isinstance(material, str) else material
    lz = laser if isinstance(laser, Laser) else db.laser(laser)
    if not m.compatible:
        raise MaterialError(f"{m.name_de}: nicht zulässig – {m.notes}")
    if not m.can_cut:
        raise MaterialError(f"{m.name_de}: mit Diodenlaser nicht schneidbar (nur Gravur)")
    if thickness_mm <= 0:
        raise MaterialError("Dicke muss > 0 sein")
    c, model = m.cut, db.model
    root = _root(lz, model)
    pct = float(c["ref_power_pct"])
    p_eff = lz.optical_power_w * pct / 100.0
    v_slow = float(c["min_speed_mm_min"]) * root
    d_max = min(float(c["max_depth_per_pass_mm"]) * root, depth_per_pass(c, model, p_eff, v_slow))
    need = thickness_mm * model.get("cut_margin", 1.1)
    passes = max(1, math.ceil(need / d_max - 1e-9))
    dpp = need / passes
    v = speed_for_depth(c, model, p_eff, dpp)
    v, p_eff = _clamp_to_vmax(c, model, lz, p_eff, dpp, v)
    pct = float(max(1, min(100, round(p_eff / lz.optical_power_w * 100.0))))
    warn = list(m.warnings)
    if thickness_mm > float(c["max_thickness_mm"]):
        warn.append(f"Dicke {thickness_mm:g} mm über empfohlenem Maximum "
                    f"{c['max_thickness_mm']:g} mm für {m.name_de}.")
    if passes > MAX_PASSES:
        warn.append(f"{passes} Durchgänge nötig – über dem Ebenen-Limit {MAX_PASSES}: "
                    "mit diesem Laser praktisch nicht schneidbar.")
    elif passes > WARN_PASSES:
        warn.append(f"{passes} Durchgänge: sehr langsam, starke Verkohlung möglich.")
    z = _focus_step(thickness_mm / passes, passes, model, thickness_mm)
    focus_start = 0.0 if thickness_mm < 4 else -round(min(2.0, thickness_mm * 0.25), 2)
    if focus_start:
        warn.append(f"Hersteller empfiehlt Fokus etwas unter der Oberfläche: Fokusabstand "
                    f"am Pi um {abs(focus_start):g} mm verringern (nicht automatisch).")
    return CutPlan(material_id=m.id, laser_id=lz.id, op="cut", speed_mm_min=_round_speed(v),
                   power_pct=pct, passes=passes, depth_per_pass_mm=round(dpp, 3), z_step_mm=z,
                   line_interval_mm=None, air_assist=m.air_assist, warnings=warn,
                   thickness_mm=thickness_mm, focus_start_mm=focus_start)


def engrave_levels(db: MaterialDB, material: Material | str) -> list[str]:
    m = db.material(material) if isinstance(material, str) else material
    if not m.can_engrave:
        return []
    return list(ENGRAVE_LEVELS) if m.can_engrave_depth else ["surface"]


def plan_engrave(db: MaterialDB, material: Material | str, level: str = "surface",
                 laser: Laser | str | None = None, depth_mm: float | None = None) -> EngravePlan:
    """Gravur: ``surface`` (Markieren) oder Tiefe ``shallow``/``medium``/``deep``.

    ``depth_mm`` überschreibt die Standardtiefe der Stufe.
    """
    m = db.material(material) if isinstance(material, str) else material
    lz = laser if isinstance(laser, Laser) else db.laser(laser)
    if not m.compatible:
        raise MaterialError(f"{m.name_de}: nicht zulässig – {m.notes}")
    if level not in ENGRAVE_LEVELS:
        raise ValueError(f"Unbekannte Gravurstufe: {level}")
    if level not in engrave_levels(db, m):
        raise MaterialError(f"{m.name_de}: Stufe '{level}' nicht möglich (nur Oberfläche)")
    e, model = m.engrave, db.model
    p_ref = float(e.get("ref_power_w", model["reference_power_w"]))
    warn = list(m.warnings)
    if level == "surface":
        s = e["surface"]
        li = max(float(s["line_interval_mm"]), lz.spot_mm)
        # Gleiche Flächenenergie wie in der Referenz: v skaliert mit P und li.
        v = float(s["speed_mm_min"]) * lz.optical_power_w / p_ref * float(s["line_interval_mm"]) / li
        pct = float(s["power_pct"])
        if v > lz.max_speed_mm_min:
            pct = pct * lz.max_speed_mm_min / v
            v = lz.max_speed_mm_min
        return EngravePlan(material_id=m.id, laser_id=lz.id, op="engrave_surface",
                           speed_mm_min=_round_speed(v), power_pct=float(max(1, min(100, round(pct)))), passes=1,
                           depth_per_pass_mm=0.0, z_step_mm=0.0, line_interval_mm=li,
                           air_assist=m.air_assist, warnings=warn, level=level, target_depth_mm=0.0)
    target = float(depth_mm if depth_mm is not None else model["engrave_levels_mm"][level])
    if target <= 0:
        raise ValueError("Gravurtiefe muss > 0 sein")
    li = max(float(e["ref_line_interval_mm"]), lz.spot_mm)
    pct = float(model["engrave_level_power_pct"][level])
    p_eff = lz.optical_power_w * pct / 100.0
    cap = float(e["max_depth_per_pass_mm"]) * _root(lz, model)
    v_min = float(model.get("engrave_min_speed_mm_min", 300))
    passes = max(1, math.ceil(target / cap - 1e-9))
    while True:
        dpp = target / passes
        v = speed_for_depth(e, model, p_eff, dpp, li)
        if v >= v_min or passes >= MAX_PASSES:
            break
        passes += 1
    v, p_eff = _clamp_to_vmax(e, model, lz, p_eff, dpp, v, li)
    if v < v_min:
        warn.append(f"Tiefe {target:g} mm mit diesem Laser kaum erreichbar.")
    z = _focus_step(dpp, passes, model, 2.0 if target >= 0.8 else 0.0)
    return EngravePlan(material_id=m.id, laser_id=lz.id, op=f"engrave_{level}",
                       speed_mm_min=_round_speed(v),
                       power_pct=float(max(1, min(100, round(p_eff / lz.optical_power_w * 100)))),
                       passes=passes, depth_per_pass_mm=round(dpp, 3), z_step_mm=z,
                       line_interval_mm=li, air_assist=m.air_assist, warnings=warn, level=level,
                       target_depth_mm=target)


def plan_relief(db: MaterialDB, material: Material | str, depth_mm: float,
                laser: Laser | str | None = None,
                line_interval_mm: float | None = None) -> ReliefPlan:
    """Schichtplan für 3D-Relief: Schruppen in Schichten + Schlichtdurchgang.

    Jede Schicht wird mit gleicher Geschwindigkeit/Maximalleistung gelasert;
    die Leistung je Bildpunkt (aus der Höhenkarte) regelt :mod:`.relief`.
    """
    m = db.material(material) if isinstance(material, str) else material
    lz = laser if isinstance(laser, Laser) else db.laser(laser)
    if not m.can_relief:
        raise MaterialError(f"{m.name_de}: für 3D-Relief nicht geeignet")
    if depth_mm <= 0:
        raise ValueError("Relieftiefe muss > 0 sein")
    e, model = m.engrave, db.model
    root = _root(lz, model)
    li = max(line_interval_mm or float(e["ref_line_interval_mm"]), lz.spot_mm)
    target_layer = min(0.25 * root, float(e["max_depth_per_pass_mm"]) * root)
    layers = int(min(60, max(2, math.ceil(depth_mm / target_layer - 1e-9))))
    ld = depth_mm / layers
    p_eff = lz.optical_power_w
    v = speed_for_depth(e, model, p_eff, ld, li)
    v, p_eff = _clamp_to_vmax(e, model, lz, p_eff, ld, v, li)
    warn = list(m.warnings)
    max_rel = float(m.relief.get("max_depth_mm", depth_mm))
    if depth_mm > max_rel:
        warn.append(f"Relieftiefe {depth_mm:g} mm über Empfehlung {max_rel:g} mm "
                    f"({m.relief.get('notes', '')}).")
    if layers > MAX_PASSES:
        warn.append(f"{layers} Schichten – sehr lange Laufzeit.")
    if v < float(model.get("engrave_min_speed_mm_min", 300)):
        warn.append("Sehr langsame Schichten: Brandgefahr, Luftunterstützung zwingend.")
    if m.relief.get("notes"):
        warn.append(m.relief["notes"])
    z = 0.0
    if layers > 1 and depth_mm >= 1.0:
        z = math.floor(min(ld * model.get("focus_follow", 0.7), MAX_Z_STEP_MM,
                           MAX_FOCUS_DROP_MM / (layers - 1)) * 100) / 100
    finish_v = min(lz.max_speed_mm_min, v * 2.0)
    return ReliefPlan(material_id=m.id, laser_id=lz.id, op="relief", speed_mm_min=_round_speed(v),
                      power_pct=float(max(1, min(100, round(p_eff / lz.optical_power_w * 100)))),
                      passes=layers, depth_per_pass_mm=round(ld, 3), z_step_mm=z,
                      line_interval_mm=li, air_assist="on", warnings=warn, max_depth_mm=depth_mm,
                      layer_depth_mm=round(ld, 3), finish_speed_mm_min=_round_speed(finish_v),
                      finish_power_pct=30.0)


def plan(db: MaterialDB, material_id: str, op: str, thickness_mm: float | None = None,
         laser_id: str | None = None, depth_mm: float | None = None):
    """Einheitlicher Einstieg: ``op`` wie in :meth:`Material.operations`."""
    if op == "cut":
        return plan_cut(db, material_id, float(thickness_mm or 0), laser_id)
    if op.startswith("engrave_"):
        return plan_engrave(db, material_id, op.split("_", 1)[1], laser_id, depth_mm)
    if op == "relief":
        d = depth_mm if depth_mm is not None else min(
            2.0, float((thickness_mm or 4) / 2),
            float((db.material(material_id).relief or {}).get("max_depth_mm", 2.0)))
        return plan_relief(db, material_id, d, laser_id)
    raise ValueError(f"Unbekannte Operation: {op}")
