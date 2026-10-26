"""Voreinstellungen (Presets): speichern, laden, auf Ebenen anwenden.

Ein Preset bündelt die Planungsergebnisse (Leistung, Geschwindigkeit,
Durchgänge, Fokus-Absenkung je Durchgang, Zeilenabstand, Luft) für ein
Material/Dicke/Operation/Laser. Auf eine Canvas-Ebene übertragen werden
``power``, ``speed``, ``passes`` und ``z_step``; Zeilenabstand, Fokus-Start
und Luftunterstützung sind Hinweise (die Ebene kennt sie noch nicht).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .db import OPERATION_LABELS, MaterialDB
from .planner import MAX_PASSES, plan

PRESET_FORMAT = "lumacut-material-presets"


@dataclass
class Preset:
    name: str
    material_id: str
    op: str
    laser_id: str
    thickness_mm: float | None
    power_pct: float
    speed_mm_min: float
    passes: int
    z_step_mm: float = 0.0
    depth_per_pass_mm: float = 0.0
    line_interval_mm: float | None = None
    focus_start_mm: float = 0.0
    air_assist: str = "on"
    notes: str = ""
    warnings: list[str] = field(default_factory=list)
    source: str = "planner"  # planner | test (aus dem Materialtest-Raster übernommen)
    id: str = ""  # stabile ID auf dem Pi (``/api/materials/presets/<id>``), s. preset_id()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Preset":
        names = {f.name for f in fields(Preset)}
        return Preset(**{k: v for k, v in d.items() if k in names})

    def layer_values(self) -> dict[str, Any]:
        """Werte für ``Document.update_layer`` (Bereiche wie im Canvas-Modell)."""
        return {"power": float(min(100.0, max(1.0, self.power_pct))),
                "speed": float(min(6000.0, max(1.0, self.speed_mm_min))),
                "passes": int(min(MAX_PASSES, max(1, self.passes))),
                "z_step": float(min(2.0, max(0.0, self.z_step_mm)))}

    def summary(self) -> str:
        parts = [f"{self.power_pct:g} %", f"{self.speed_mm_min:g} mm/min", f"{self.passes}×"]
        if self.depth_per_pass_mm:
            parts.append(f"{self.depth_per_pass_mm:g} mm/Durchgang")
        if self.z_step_mm:
            parts.append(f"Z −{self.z_step_mm:g} mm/Durchgang")
        if self.line_interval_mm:
            parts.append(f"Zeilenabstand {self.line_interval_mm:g} mm")
        parts.append(f"Luft {self.air_assist}")
        return ", ".join(parts)


def preset_id(name: str) -> str:
    """Stabile, URL-sichere ID aus dem Namen: ``<slug>-<6 hex>`` (max. 64 Zeichen).

    Gleicher Name ergibt auf jedem Gerät dieselbe ID (Windows, Android, Web)."""
    folded = name.strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        folded = folded.replace(a, b)
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:56] or "preset"
    return f"{slug}-{hashlib.sha1(name.strip().encode('utf-8')).hexdigest()[:6]}"


def make_preset(db: MaterialDB, material_id: str, op: str, thickness_mm: float | None = None,
                laser_id: str | None = None, name: str | None = None,
                depth_mm: float | None = None) -> Preset:
    """Plant und verpackt das Ergebnis als Preset."""
    p = plan(db, material_id, op, thickness_mm, laser_id, depth_mm)
    m = db.material(material_id)
    th = f" {thickness_mm:g} mm" if thickness_mm else ""
    return Preset(name=name or f"{m.name_de}{th} – {OPERATION_LABELS.get(op, op)}",
                  material_id=m.id, op=op, laser_id=p.laser_id, thickness_mm=thickness_mm,
                  power_pct=float(p.power_pct), speed_mm_min=float(p.speed_mm_min),
                  passes=int(p.passes), z_step_mm=float(p.z_step_mm),
                  depth_per_pass_mm=float(p.depth_per_pass_mm),
                  line_interval_mm=p.line_interval_mm,
                  focus_start_mm=float(getattr(p, "focus_start_mm", 0.0)),
                  air_assist=p.air_assist, notes=m.notes, warnings=list(p.warnings))


def apply_to_layer(doc, layer_id: str, preset: Preset) -> dict[str, Any]:
    """Preset direkt auf eine Ebene anwenden (ohne Undo). Gibt die Werte zurück."""
    values = preset.layer_values()
    doc.update_layer(layer_id, **values)
    return values


class PresetStore:
    """Eigene Presets als JSON-Datei."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.presets: list[Preset] = []
        if self.path.exists():
            self.load()

    def load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("format") != PRESET_FORMAT:
            raise ValueError("Keine LumaCut-Preset-Datei")
        self.presets = [Preset.from_dict(d) for d in data.get("presets", [])]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"format": PRESET_FORMAT, "version": 1, "presets": [p.to_dict() for p in self.presets]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def names(self) -> list[str]:
        return [p.name for p in self.presets]

    def get(self, name: str) -> Preset:
        for p in self.presets:
            if p.name == name:
                return p
        raise KeyError(name)

    def by_id(self, pid: str) -> Preset | None:
        return next((p for p in self.presets if pid and p.id == pid), None)

    def put(self, preset: Preset) -> None:
        """Hinzufügen oder gleichnamiges (bzw. gleiche ID) Preset ersetzen."""
        self.presets = [p for p in self.presets
                        if p.name != preset.name and not (preset.id and p.id == preset.id)] + [preset]

    def remove(self, name: str) -> None:
        self.presets = [p for p in self.presets if p.name != name]
