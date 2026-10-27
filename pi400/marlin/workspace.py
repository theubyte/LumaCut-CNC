"""Shared work state on the Pi: what every app (tablet, phone, PC, web) sees.

The Pi is the machine's centre, so the state of the work lives here and
not on one device:

* ``state.json``   – chosen material (its thickness sets the travel height),
                     marked areas, height mesh and app settings;
* ``project.json`` – the open project (all plates) as the apps write it;
* ``scan.png``     – the scanned work area under the design.

Each part has its own revision. A write names the revision it is based on;
a stale one is refused with 409, so two devices never overwrite each other
unnoticed. ``revisions()`` goes into /api/status: apps see a change within
one status poll and fetch only what changed.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

# The thickest material that fits under the head with 20 mm travel
# clearance below the 80 mm Z limit (owner's decision 2026-10-27).
MAX_MATERIAL_MM = 60.0
STATE_KEYS = ("material", "areas", "probe_points", "heights", "settings")
MAX_PROJECT_BYTES = 30 * 1024 * 1024
MAX_SCAN_BYTES = 16 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ConflictError(Exception):
    def __init__(self, what: str, revision: int):
        super().__init__("%s wurde inzwischen an einem anderen Gerät geändert" % what)
        self.revision = revision


def _validate_state(data: dict) -> dict:
    unknown = set(data) - set(STATE_KEYS)
    if unknown:
        raise ValueError("Unbekannte Felder: " + ", ".join(sorted(unknown)))
    out = {}
    if "material" in data:
        m = data["material"]
        if m is not None:
            if not isinstance(m, dict) or not isinstance(m.get("name"), str) or not m["name"].strip() or len(m["name"]) > 80:
                raise ValueError("material: {name, thickness_mm} erwartet")
            t = m.get("thickness_mm")
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0.0 <= float(t) <= MAX_MATERIAL_MM:
                raise ValueError("Materialstärke 0 … %g mm (darüber fehlt der Platz für den Rückzug)" % MAX_MATERIAL_MM)
            m = {"name": m["name"].strip(), "thickness_mm": round(float(t), 3)}
        out["material"] = m
    if "areas" in data:
        a = data["areas"]
        if not isinstance(a, list) or len(a) > 50 or not all(
                isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                            and -1.0 <= v <= 400.0 for v in b) for b in a):
            raise ValueError("areas: bis zu 50 Rechtecke [minX, minY, maxX, maxY] in mm")
        out["areas"] = [[round(float(v), 3) for v in b] for b in a]
    if "probe_points" in data:
        pts = data["probe_points"]
        if not isinstance(pts, list) or len(pts) > 50 or not all(
                isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                            and -1.0 <= v <= 400.0 for v in p) for p in pts):
            raise ValueError("probe_points: bis zu 50 Punkte [x, y] in mm")
        out["probe_points"] = [[round(float(v), 3) for v in p] for p in pts]
    if "heights" in data:
        h = data["heights"]
        if h is not None and (not isinstance(h, dict) or len(json.dumps(h)) > 2 * 1024 * 1024):
            raise ValueError("heights: Höhenmesh-Objekt (höchstens 2 MB) oder null")
        out["heights"] = h
    if "settings" in data:
        s = data["settings"]
        if not isinstance(s, dict) or len(s) > 100 or not all(
                isinstance(k, str) and len(k) <= 64 and (v is None or isinstance(v, (bool, int, float, str)))
                and (not isinstance(v, str) or len(v) <= 500) for k, v in s.items()):
            raise ValueError("settings: bis zu 100 einfache Werte")
        out["settings"] = s
    return out


class WorkspaceStore:
    def __init__(self, folder: Path):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.state = self._read_json("state.json", {"revision": 0, "material": None, "areas": [], "probe_points": [],
                                                    "heights": None, "settings": {}})
        self.project_meta = self._read_json("project.meta.json", {"revision": 0})
        self.scan_meta = self._read_json("scan.meta.json", {"revision": 0})
        # called with the new state after every write (the Pi takes the material thickness from it)
        self.on_change = None

    def _read_json(self, name, default):
        try:
            data = json.loads((self.dir / name).read_text("utf-8"))
            if isinstance(data, dict):
                return {**default, **data}
        except Exception:
            pass
        return dict(default)

    def _write(self, name, data: bytes):
        tmp = self.dir / (name + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.dir / name)

    def _write_json(self, name, obj):
        self._write(name, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    @staticmethod
    def _stamp(meta, by):
        meta["revision"] = int(meta.get("revision", 0)) + 1
        meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        meta["updated_by"] = (by or "")[:40]

    def revisions(self) -> dict:
        return {"workspace": self.state["revision"], "project": self.project_meta["revision"],
                "scan": self.scan_meta["revision"]}

    def probe_points(self):
        """Tapped probe points, work mm (x right, y down from the work-area top left)."""
        return [tuple(p) for p in self.state.get("probe_points") or []]

    def material_thickness(self):
        m = self.state.get("material")
        return None if not m else float(m["thickness_mm"])

    # --- state -------------------------------------------------------------
    def get_state(self) -> dict:
        with self.lock:
            return dict(self.state)

    def put_state(self, data: dict, base_revision, by="") -> dict:
        changes = _validate_state({k: v for k, v in data.items() if k not in ("base_revision", "updated_by")})
        with self.lock:
            if base_revision is not None and int(base_revision) != self.state["revision"]:
                raise ConflictError("Der Arbeitsstand", self.state["revision"])
            self.state.update(changes)
            self._stamp(self.state, by)
            self._write_json("state.json", self.state)
            result = dict(self.state)
        if self.on_change is not None:
            self.on_change(result)
        return result

    # --- project -----------------------------------------------------------
    def get_project(self):
        with self.lock:
            path = self.dir / "project.json"
            data = path.read_bytes() if path.is_file() else None
            return dict(self.project_meta), data

    def put_project(self, raw: bytes, base_revision, by="") -> dict:
        if len(raw) > MAX_PROJECT_BYTES:
            raise ValueError("Projekt größer als 30 MB")
        try:
            doc = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("Projekt ist kein gültiges JSON")
        if not isinstance(doc, dict):
            raise ValueError("Projekt-Objekt erwartet")
        with self.lock:
            if base_revision is not None and int(base_revision) != self.project_meta["revision"]:
                raise ConflictError("Das Projekt", self.project_meta["revision"])
            self._write("project.json", raw)
            self._stamp(self.project_meta, by)
            self.project_meta["title"] = str(doc.get("title", ""))[:120]
            self.project_meta["bytes"] = len(raw)
            self._write_json("project.meta.json", self.project_meta)
            return dict(self.project_meta)

    # --- scan --------------------------------------------------------------
    def get_scan(self):
        with self.lock:
            path = self.dir / "scan.png"
            return dict(self.scan_meta), (path.read_bytes() if path.is_file() else None)

    def put_scan(self, png: bytes | None, base_revision, by="") -> dict:
        if png is not None:
            if len(png) > MAX_SCAN_BYTES:
                raise ValueError("Scanbild größer als 16 MB")
            if not png.startswith(PNG_MAGIC):
                raise ValueError("Scanbild muss ein PNG sein")
        with self.lock:
            if base_revision is not None and int(base_revision) != self.scan_meta["revision"]:
                raise ConflictError("Das Scanbild", self.scan_meta["revision"])
            if png is None:
                (self.dir / "scan.png").unlink(missing_ok=True)
            else:
                self._write("scan.png", png)
            self._stamp(self.scan_meta, by)
            self.scan_meta["bytes"] = 0 if png is None else len(png)
            self._write_json("scan.meta.json", self.scan_meta)
            return dict(self.scan_meta)


def _base_revision():
    raw = request.args.get("base_revision")
    if raw is None:
        body = request.get_json(silent=True)
        raw = body.get("base_revision") if isinstance(body, dict) else None
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError("base_revision: ganze Zahl erwartet")


def create_blueprint(store: WorkspaceStore) -> Blueprint:
    bp = Blueprint("workspace", __name__)

    @bp.errorhandler(ConflictError)
    def conflict(exc):
        return jsonify(error=str(exc), revision=exc.revision), 409

    @bp.get("/api/workspace")
    def workspace_get():
        return jsonify(store.get_state())

    @bp.put("/api/workspace")
    def workspace_put():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("JSON-Objekt erwartet (Content-Type: application/json)")
        return jsonify(store.put_state(body, _base_revision(), body.get("updated_by", "")))

    @bp.get("/api/workspace/project")
    def project_get():
        meta, data = store.get_project()
        if data is None:
            return jsonify(error="Noch kein Projekt auf dem Pi", **meta), 404
        return data, 200, {"Content-Type": "application/json; charset=utf-8", "X-Revision": str(meta["revision"])}

    @bp.put("/api/workspace/project")
    def project_put():
        return jsonify(store.put_project(request.get_data(), _base_revision(), request.args.get("by", "")))

    @bp.get("/api/workspace/scan")
    def scan_get():
        meta, data = store.get_scan()
        if data is None:
            return jsonify(error="Noch kein Scanbild auf dem Pi", **meta), 404
        return data, 200, {"Content-Type": "image/png", "X-Revision": str(meta["revision"])}

    @bp.put("/api/workspace/scan")
    def scan_put():
        return jsonify(store.put_scan(request.get_data(), _base_revision(), request.args.get("by", "")))

    @bp.delete("/api/workspace/scan")
    def scan_delete():
        return jsonify(store.put_scan(None, _base_revision(), request.args.get("by", "")))

    return bp
