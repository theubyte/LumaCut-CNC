"""Material database shared by every LumaCut program (docs/ZUSAMMENARBEIT_CLAUDE_GROK.md §3).

One JSON file on the Pi (``materials.json`` next to ``marlin/``), written
atomically. Every change raises ``revision`` by one; a writer sends the
revision it last read as ``base_revision`` and gets a ConflictError (HTTP 409)
when somebody else changed the list in between. The apps keep only a cache.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("lumacut.materials")

PROCESSES = ("Schneiden", "Gravieren", "Markieren")
MODES = ("line", "fill")
MAX_FOCUS_DROP_MM = 3.0      # all passes together (Z floor surface + 2 mm)
MAX_Z_STEP_MM = 2.0
MAX_EXTRA_FIELDS = 32
MAX_EXTRA_BYTES = 16 * 1024
FIELDS = ("id", "name", "thickness_mm", "process", "mode", "power_pct",
          "speed_mm_min", "passes", "interval_mm", "depth_per_pass_mm",
          "z_step_mm", "builtin", "updated")

# Starting points only (same as Android Material.defaults()); every material
# must be tested on the machine. passes = ceil(thickness / depth per pass).
DEFAULTS = (
    dict(name="Pappelsperrholz", thickness_mm=3.0, process="Schneiden", mode="line",
         power_pct=90.0, speed_mm_min=350.0, passes=2, depth_per_pass_mm=1.5, z_step_mm=0.5),
    dict(name="Pappelsperrholz", thickness_mm=3.0, process="Gravieren", mode="fill",
         power_pct=25.0, speed_mm_min=3000.0),
    dict(name="MDF", thickness_mm=3.0, process="Schneiden", mode="line",
         power_pct=95.0, speed_mm_min=300.0, passes=2, depth_per_pass_mm=1.5, z_step_mm=0.5),
    dict(name="Acryl schwarz", thickness_mm=3.0, process="Schneiden", mode="line",
         power_pct=100.0, speed_mm_min=200.0, passes=3, depth_per_pass_mm=1.0, z_step_mm=0.5),
    dict(name="Leder", thickness_mm=2.0, process="Gravieren", mode="fill",
         power_pct=18.0, speed_mm_min=3000.0),
    dict(name="Karton", thickness_mm=1.0, process="Schneiden", mode="line",
         power_pct=45.0, speed_mm_min=1200.0),
    dict(name="Schiefer", thickness_mm=5.0, process="Gravieren", mode="fill",
         power_pct=40.0, speed_mm_min=2500.0, interval_mm=0.08),
)


def validate_tone_curve(curve):
    """Checked darkness curve (``tone_curve``, from the camera calibration):
    measured fields {power, speed, tone}, the lowest reliable power and the
    speed band the apps may slide in."""
    if not isinstance(curve, dict):
        raise ValueError("tone_curve als JSON-Objekt erwartet")
    points = curve.get("points")
    if not isinstance(points, list) or not 2 <= len(points) <= 40:
        raise ValueError("tone_curve.points: 2 bis 40 Messpunkte")
    clean = []
    for p in points:
        if not isinstance(p, dict):
            raise ValueError("tone_curve.points: {power, speed, tone} erwartet")
        point = {"power": _number(p, "power", 0.1, 100.0), "speed": _number(p, "speed", 1.0, 30000.0),
                 "tone": _number(p, "tone", 0.0, 1.0)}
        if "clean" in p:
            point["clean"] = bool(p["clean"])
        clean.append(point)
    result = {"points": clean,
              "min_power_pct": _number(curve, "min_power_pct", 0.0, 100.0, 8.0),
              "interval_mm": _number(curve, "interval_mm", 0.01, 5.0, 0.1),
              "speed_min": _number(curve, "speed_min", 1.0, 30000.0, min(p["speed"] for p in clean)),
              "speed_max": _number(curve, "speed_max", 1.0, 30000.0, max(p["speed"] for p in clean))}
    if result["speed_min"] > result["speed_max"]:
        raise ValueError("tone_curve: speed_min größer als speed_max")
    return result


class ConflictError(RuntimeError):
    """base_revision is outdated: reload, then try again."""

    def __init__(self, message, revision):
        super().__init__(message)
        self.revision = revision


class NotFoundError(KeyError):
    pass


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _number(data, key, low, high, default=None):
    raw = data.get(key, default)
    if raw is None or isinstance(raw, bool):
        raise ValueError("%s fehlt" % key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError("%s ist keine Zahl" % key)
    if not (math.isfinite(value) and low <= value <= high):
        raise ValueError("%s muss zwischen %g und %g liegen" % (key, low, high))
    return value


def validate(data, *, material_id=None, builtin=False):
    """Checked, complete material dict (raises ValueError with a German message)."""
    if not isinstance(data, dict):
        raise ValueError("Material als JSON-Objekt erwartet")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValueError("name: 1 bis 80 Zeichen")
    process = data.get("process")
    if process not in PROCESSES:
        raise ValueError("process muss Schneiden, Gravieren oder Markieren sein")
    mode = data.get("mode")
    if mode not in MODES:
        raise ValueError("mode muss line oder fill sein")
    passes_raw = data.get("passes", 1)
    if isinstance(passes_raw, bool) or not isinstance(passes_raw, (int, float)) \
            or float(passes_raw) != int(passes_raw) or not 1 <= int(passes_raw) <= 30:
        raise ValueError("passes muss eine ganze Zahl zwischen 1 und 30 sein")
    material = {
        "id": material_id or str(uuid.uuid4()),
        "name": name.strip(),
        "thickness_mm": _number(data, "thickness_mm", 0.0, 60.0),
        "process": process,
        "mode": mode,
        "power_pct": _number(data, "power_pct", 0.0, 100.0),
        "speed_mm_min": _number(data, "speed_mm_min", 1.0, 30000.0),
        "passes": int(passes_raw),
        "interval_mm": _number(data, "interval_mm", 0.01, 5.0, 0.1),
        "depth_per_pass_mm": _number(data, "depth_per_pass_mm", 0.0, 50.0, 0.0),
        "z_step_mm": _number(data, "z_step_mm", 0.0, MAX_Z_STEP_MM, 0.0),
        "builtin": bool(builtin),
        "updated": _now(),
    }
    # Fields of other programs (Studio: material_id, laser_id, notes, ...)
    # are kept unchanged and returned as sent.
    extras = {k: v for k, v in data.items() if k not in FIELDS and k != "base_revision"}
    if len(extras) > MAX_EXTRA_FIELDS or not all(isinstance(k, str) and len(k) <= 64 for k in extras):
        raise ValueError("Zu viele oder zu lange Zusatzfelder")
    if len(json.dumps(extras, ensure_ascii=False)) > MAX_EXTRA_BYTES:
        raise ValueError("Zusatzfelder größer als %d KB" % (MAX_EXTRA_BYTES // 1024))
    material.update(extras)
    if material.get("tone_curve") is not None:
        material["tone_curve"] = validate_tone_curve(material["tone_curve"])
    # The apps derive the passes from thickness / depth per pass when set.
    passes = material["passes"]
    if material["depth_per_pass_mm"] > 0 and material["thickness_mm"] > 0:
        passes = max(1, math.ceil(material["thickness_mm"] / material["depth_per_pass_mm"] - 1e-9))
        if passes > 30:
            raise ValueError("Dicke / Tiefe je Durchgang ergibt mehr als 30 Durchgänge")
    if (passes - 1) * material["z_step_mm"] > MAX_FOCUS_DROP_MM + 1e-9:
        raise ValueError("Z-Absenkung über alle Durchgänge %.2f mm, höchstens %g mm" % (
            (passes - 1) * material["z_step_mm"], MAX_FOCUS_DROP_MM))
    return material


class MaterialStore:
    """Thread-safe, revisioned material list in one JSON file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self._data = None

    def _load_locked(self):
        if self._data is not None:
            return self._data
        data = None
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text("utf-8"))
                if (isinstance(raw, dict) and isinstance(raw.get("revision"), int)
                        and isinstance(raw.get("materials"), list)):
                    data = {"revision": raw["revision"],
                            "materials": [m for m in raw["materials"] if isinstance(m, dict)]}
                else:
                    raise ValueError("unbekanntes Format")
            except Exception:
                LOG.exception("materials.json unreadable, keeping a copy and starting fresh")
                try:
                    os.replace(self.path, self.path.with_suffix(".corrupt"))
                except OSError:
                    pass
        if data is None:
            data = {"revision": 1,
                    "materials": [validate(d, builtin=True) for d in DEFAULTS]}
            self._data = data
            self._save_locked()
        self._data = data
        return data

    def _save_locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def _check_revision_locked(self, base_revision):
        current = self._data["revision"]
        if base_revision is None or isinstance(base_revision, bool):
            raise ValueError("base_revision fehlt")
        try:
            base = int(base_revision)
        except (TypeError, ValueError):
            raise ValueError("base_revision ist keine Zahl")
        if base != current:
            raise ConflictError("Materialliste wurde inzwischen geändert (Revision %d) – "
                                "neu laden und erneut versuchen" % current, current)

    def _index_locked(self, material_id):
        for i, m in enumerate(self._data["materials"]):
            if m.get("id") == material_id:
                return i
        raise NotFoundError(material_id)

    def list(self):
        with self.lock:
            data = self._load_locked()
            return {"revision": data["revision"],
                    "materials": [dict(m) for m in data["materials"]]}

    def create(self, body):
        with self.lock:
            self._load_locked()
            self._check_revision_locked(body.get("base_revision") if isinstance(body, dict) else None)
            material = validate(body)
            self._data["materials"].append(material)
            return self._commit_locked(material=material)

    def update(self, material_id, body):
        with self.lock:
            self._load_locked()
            self._check_revision_locked(body.get("base_revision") if isinstance(body, dict) else None)
            index = self._index_locked(material_id)
            old = self._data["materials"][index]
            merged = {**old, **body}
            material = validate(merged, material_id=material_id, builtin=old.get("builtin", False))
            self._data["materials"][index] = material
            return self._commit_locked(material=material)

    def delete(self, material_id, base_revision):
        with self.lock:
            self._load_locked()
            self._check_revision_locked(base_revision)
            index = self._index_locked(material_id)
            del self._data["materials"][index]
            return self._commit_locked()

    def _commit_locked(self, **extra):
        self._data["revision"] += 1
        try:
            self._save_locked()
        except Exception:
            self._data = None   # reload the file as it is on disk
            raise
        result = {"revision": self._data["revision"]}
        result.update({k: dict(v) for k, v in extra.items()})
        return result
