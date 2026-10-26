"""Materialbibliothek ↔ Canvas-Ebene: zuweisen oder verknüpfen.

* **Zuweisen** (``link=False``): Die geplanten Werte (Leistung,
  Geschwindigkeit, Durchgänge, Fokus-Absenkung, Dicke, Tiefe je Durchgang)
  werden einmal auf die Ebene kopiert. Danach ist die Ebene frei.
* **Verknüpfen** (``link=True``): Zusätzlich merkt sich die Ebene den
  Bibliotheksbezug (``material_ref = "lib:<material>/<op>/<laser>"``,
  ``material_link = True``). Ändert sich danach die Dicke (Schneiden) bzw.
  die Zieltiefe (Gravur/Relief) – egal ob im Ebenen-Panel, im Dialog oder per
  Code über ``SetLayerAttr(s)Command`` –, plant der Hook
  :func:`layer_attr_hook` Leistung/Geschwindigkeit/Durchgänge/Fokus neu, und
  zwar im **selben Undo-Schritt**. Ändert man einen dieser Werte von Hand,
  wird die Verknüpfung gelöst (die Ebene behält den Wert); wählt man ein
  anderes Material, verschwindet der Bezug.

Qt-frei bis auf :func:`install_link_hook`, das nur den Hook in
``lumacut_canvas.commands`` registriert.
"""

from __future__ import annotations

import math
from typing import Any

from .db import MaterialDB, MaterialError, load_db
from .planner import MAX_PASSES, MAX_Z_STEP_MM, plan
from .process import layer_process_attrs, process_defaults

REF_PREFIX = "lib:"
# Manuelle Änderung eines dieser Felder löst die Verknüpfung.
MANUAL_FIELDS = ("power", "speed", "passes", "z_step", "depth_per_pass_mm")
# Abgeleitete Felder, die bei einer Neuplanung immer aus der Bibliothek kommen.
AUTO_FIELDS = ("passes", "depth_per_pass_mm")


def make_ref(material_id: str, op: str, laser_id: str) -> str:
    return f"{REF_PREFIX}{material_id}/{op}/{laser_id}"


def parse_ref(ref: str | None) -> tuple[str, str, str] | None:
    """``(material_id, op, laser_id)`` oder ``None`` (kein Bibliotheksbezug)."""
    if not ref or not ref.startswith(REF_PREFIX):
        return None
    parts = ref[len(REF_PREFIX):].split("/")
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]


def _ceil3(v: float) -> float:
    return math.ceil(v * 1000 - 1e-6) / 1000


def plan_layer_attrs(db: MaterialDB, material_id: str, op: str, thickness_mm: float | None = None,
                     laser_id: str | None = None, depth_mm: float | None = None,
                     link: bool = True, layer: Any = None,
                     previous_thickness_mm: float | None = None) -> dict[str, Any]:
    """Ebenen-Attribute für Material/Operation/Dicke (für ``SetLayerAttrsCommand``).

    ``depth_per_pass_mm`` wird so gesetzt, dass die Tiefenplanung des
    Ebenen-Panels (``ceil(Tiefe / Tiefe je Durchgang)``) genau die geplanten
    Durchgänge ergibt. ``layer`` (optional) aktiviert den Feature-Check für
    Kerf/Tabs/Lead-in (:mod:`.process`); ``previous_thickness_mm`` (Neuplanung)
    schützt von Hand geänderte Kerf/Steg-Werte.
    """
    p = plan(db, material_id, op, thickness_mm, laser_id, depth_mm)
    m = db.material(material_id)
    passes = int(min(MAX_PASSES, max(1, p.passes)))
    t = float(thickness_mm or 0.0)
    attrs: dict[str, Any] = {
        "power": float(min(100.0, max(1.0, p.power_pct))),
        "speed": float(min(6000.0, max(1.0, p.speed_mm_min))),
        "passes": passes,
        "z_step": float(min(MAX_Z_STEP_MM, max(0.0, p.z_step_mm))),
        "material": m.name_de,
        "material_ref": make_ref(m.id, op, p.laser_id),
        "material_link": bool(link),
    }
    if op == "cut":
        attrs.update(thickness_mm=t, target_depth_mm=0.0,
                     depth_per_pass_mm=_ceil3(t / passes) if t > 0 else 0.0)
    else:
        depth = float(getattr(p, "target_depth_mm", 0.0) or getattr(p, "max_depth_mm", 0.0) or 0.0)
        attrs.update(thickness_mm=t, target_depth_mm=round(depth, 3),
                     depth_per_pass_mm=_ceil3(depth / passes) if depth > 0 else 0.0)
    if op == "cut" and layer is not None and t > 0:
        prev = None
        if previous_thickness_mm and previous_thickness_mm > 0:
            prev = process_defaults(db, material_id, previous_thickness_mm, p.laser_id)
        attrs.update(layer_process_attrs(layer, process_defaults(db, material_id, t, p.laser_id),
                                         prev))
    return attrs


def relink_attrs(db: MaterialDB, layer: Any, changes: dict[str, Any]) -> dict[str, Any]:
    """Abgeleitete Attribute für eine Änderung an einer (verknüpften) Ebene."""
    ref = getattr(layer, "material_ref", "")
    if "material_ref" in changes or not ref:
        return {}
    if "material" in changes and changes["material"] != getattr(layer, "material", ""):
        return {"material_ref": "", "material_link": False}
    if not getattr(layer, "material_link", False):
        return {}
    if "material_link" in changes:
        return {}
    parsed = parse_ref(ref)
    if parsed is None:
        return {}
    material_id, op, laser_id = parsed
    trigger = "thickness_mm" if op == "cut" else "target_depth_mm"
    triggered = trigger in changes or (op != "cut" and "thickness_mm" in changes)
    manual = [k for k in MANUAL_FIELDS if k in changes]
    if manual and not triggered:
        return {"material_link": False}
    if op == "cut":
        if "thickness_mm" not in changes:
            return {}
        t = float(changes["thickness_mm"] or 0.0)
        if t <= 0:
            return {"material_link": False}
        new = plan_layer_attrs(db, material_id, op, t, laser_id, layer=layer,
                               previous_thickness_mm=float(getattr(layer, "thickness_mm", 0) or 0))
    else:
        if "target_depth_mm" not in changes and "thickness_mm" not in changes:
            return {}
        depth = changes.get("target_depth_mm", getattr(layer, "target_depth_mm", 0.0))
        t = changes.get("thickness_mm", getattr(layer, "thickness_mm", 0.0))
        if op in ("engrave_surface",) or not depth:
            return {}
        new = plan_layer_attrs(db, material_id, op, t or None, laser_id, depth_mm=float(depth),
                               layer=layer)
    # Durchgänge/Tiefe je Durchgang, die das Ebenen-Panel aus den *alten*
    # Werten mitschickt, ersetzt die Neuplanung; alle anderen Werte aus der
    # Änderung behalten Vorrang.
    out = {k: v for k, v in new.items() if k not in changes or k in AUTO_FIELDS}
    out["__override__"] = tuple(k for k in AUTO_FIELDS if k in changes)
    return out


_HOOK_DB: MaterialDB | None = None


def layer_attr_hook(layer: Any, changes: dict[str, Any]) -> dict[str, Any]:
    """Hook für ``lumacut_canvas.commands.register_layer_attr_hook``."""
    global _HOOK_DB
    if not getattr(layer, "material_ref", ""):
        return {}
    if _HOOK_DB is None:
        _HOOK_DB = load_db()
    try:
        return relink_attrs(_HOOK_DB, layer, changes)
    except (MaterialError, ValueError, KeyError):
        # Nicht planbar (z. B. Dicke außerhalb der Tabelle): Wert übernehmen,
        # Verknüpfung lösen, damit keine veralteten Werte vorgetäuscht werden.
        return {"material_link": False}


def install_link_hook(db: MaterialDB | None = None) -> None:
    """Hook in den Canvas-Undo-Befehlen registrieren (idempotent)."""
    global _HOOK_DB
    if db is not None:
        _HOOK_DB = db
    from lumacut_canvas.commands import register_layer_attr_hook
    register_layer_attr_hook(layer_attr_hook)


def link_status(layer: Any) -> str:
    """Kurzer Anzeigetext für den Verknüpfungszustand einer Ebene."""
    parsed = parse_ref(getattr(layer, "material_ref", ""))
    if parsed is None:
        return ""
    state = "verknüpft" if getattr(layer, "material_link", False) else "zugewiesen"
    return f"{getattr(layer, 'material', '') or parsed[0]} ({state})"


def preset_layer_attrs(db: MaterialDB, preset: Any, link: bool = False,
                       layer: Any = None) -> dict[str, Any]:
    """Ebenen-Attribute für ein gespeichertes Preset.

    Eigene Presets (z. B. aus dem Materialtest) werden standardmäßig nur
    *zugewiesen*: eine Dickenänderung würde sonst die gemessenen Werte durch
    die Bibliotheksplanung ersetzen. ``link=True`` verknüpft trotzdem.
    """
    values = preset.layer_values()
    t = float(preset.thickness_mm or 0.0)
    passes = int(values["passes"])
    attrs: dict[str, Any] = dict(values)
    try:
        m = db.material(preset.material_id)
        attrs["material"] = m.name_de
        attrs["material_ref"] = make_ref(m.id, preset.op, preset.laser_id)
        attrs["material_link"] = bool(link)
    except (MaterialError, KeyError):
        attrs["material"] = preset.name
    if preset.op == "cut":
        attrs.update(thickness_mm=t, target_depth_mm=0.0,
                     depth_per_pass_mm=_ceil3(t / passes) if t > 0 else 0.0)
        if layer is not None and t > 0 and "material_ref" in attrs:
            try:
                attrs.update(layer_process_attrs(
                    layer, process_defaults(db, preset.material_id, t, preset.laser_id)))
            except (MaterialError, StopIteration, KeyError):
                pass
    else:
        dpp = float(preset.depth_per_pass_mm or 0.0)
        attrs.update(thickness_mm=t, target_depth_mm=round(dpp * passes, 3) if dpp else 0.0,
                     depth_per_pass_mm=dpp)
    return attrs
