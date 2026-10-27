"""Camera calibration of the head camera, stored on the Pi.

The calibration belongs to the machine, not to a client: Studio (Windows),
the tablet app and the browser read and write the same JSON file through
``GET/PUT /api/camera/calibration``.

Storage (first match wins, see :func:`candidate_paths`):

1. ``LUMACUT_CAMERA_CALIBRATION`` (env, e.g. in /etc/lumacut/lumacut.env) – only this path
2. ``/etc/lumacut/camera_calibration.json`` (install.sh: /etc/lumacut root:lumacut 1775)
3. ``pi400/config/camera_calibration.json`` in the repository (development, no /etc)
4. ``$LUMACUT_DATA/camera_calibration.json`` (older installations whose service may only
   write /var/lib/lumacut)

Writes are atomic (temporary file in the same directory, fsync, rename) and
optimistic: the client sends the ``revision`` it has read; a different stored
revision is rejected with :class:`CalibrationConflict` instead of being
overwritten silently. Without a file the defaults are returned and flagged
``placeholder`` – never mistaken for a measured calibration.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import logging
import math
import os
import tempfile
import threading
from pathlib import Path

FORMAT = "lumacut-camera-calibration/1"
SCHEMA_VERSION = 1
FILENAME = "camera_calibration.json"
ETC_PATH = Path("/etc/lumacut") / FILENAME
REPO_PATH = Path(__file__).resolve().parent.parent / "config" / FILENAME
MAX_BYTES = 64 * 1024

# Placeholder values, identical to Studio's adapters.default_calibration().
DEFAULTS = {
    "image_width": 640,
    "image_height": 480,
    "px_per_mm": 4.0,
    "scan_z": 40.0,
    "offset_mm": [30.0, -20.0],
    "rotation_deg": 0.0,
    "flip_x": 1,
    "flip_y": 1,
    "crop_fraction": 0.04,
    "camera_matrix": None,
    "dist_coeffs": None,
    "exposure": None,
    "homography": None,
    # The tablet app's own model (lens grid or four marks), stored as it is;
    # the Pi only checks its shape. Windows Studio will follow this model.
    "android": None,
}
META_DEFAULTS = {"calibrated": False, "notes": "", "updated_by": ""}
# Read-only fields a client may send back unchanged (GET -> edit -> PUT).
IGNORED = {"format", "placeholder", "updated_at", "storage", "status"}


class CalibrationConflict(RuntimeError):
    """Stored revision differs from the one the client edited."""

    def __init__(self, message: str, current: dict):
        super().__init__(message)
        self.current = current


def candidate_paths(env=None) -> list[Path]:
    env = os.environ if env is None else env
    override = (env.get("LUMACUT_CAMERA_CALIBRATION") or "").strip()
    if override:
        return [Path(override)]
    data = Path(env.get("LUMACUT_DATA", "/var/lib/lumacut"))
    paths = [ETC_PATH, REPO_PATH, data / FILENAME]
    return list(dict.fromkeys(paths))


def _number(data, key, low, high, errors, integer=False):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append("%s: Zahl erwartet" % key)
        return
    if not math.isfinite(value):
        errors.append("%s: endliche Zahl erwartet" % key)
    elif not (low <= value <= high):
        errors.append("%s: %g liegt außerhalb %g … %g" % (key, value, low, high))
    elif integer and int(value) != value:
        errors.append("%s: ganze Zahl erwartet" % key)


def _matrix(value, rows, cols):
    return (isinstance(value, list) and len(value) == rows and
            all(isinstance(r, list) and len(r) == cols and
                all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in r) for r in value))


def _det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def validate(data) -> dict:
    """Return the normalized calibration fields or raise ValueError (German)."""
    if not isinstance(data, dict):
        raise ValueError("Kalibrierung muss ein JSON-Objekt sein")
    if data.get("format", FORMAT) != FORMAT:
        raise ValueError("Unbekanntes Format %r, erwartet %s" % (data.get("format"), FORMAT))
    if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValueError("Schema-Version %r wird nicht unterstützt (erwartet %d)"
                         % (data.get("schema_version"), SCHEMA_VERSION))
    allowed = set(DEFAULTS) | set(META_DEFAULTS) | IGNORED | {
        "schema_version", "revision", "comment"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError("Unbekannte Felder: " + ", ".join(unknown))
    merged = dict(DEFAULTS)
    merged.update({k: data[k] for k in DEFAULTS if k in data})
    errors: list[str] = []
    _number(merged, "image_width", 160, 8192, errors, integer=True)
    _number(merged, "image_height", 120, 8192, errors, integer=True)
    _number(merged, "px_per_mm", 0.5, 100.0, errors)
    _number(merged, "scan_z", 0.0, 80.0, errors)
    _number(merged, "rotation_deg", -180.0, 180.0, errors)
    _number(merged, "crop_fraction", 0.0, 0.4, errors)
    if merged["crop_fraction"] == 0.4:  # wie Studio: 0 <= crop_fraction < 0.4
        errors.append("crop_fraction: muss kleiner als 0.4 sein")
    for key in ("flip_x", "flip_y"):
        if merged[key] not in (1, -1) or isinstance(merged[key], bool):
            errors.append("%s: +1 oder -1 erwartet" % key)
    off = merged["offset_mm"]
    if not (_matrix([off], 1, 2) and all(abs(v) <= 200 for v in off)):
        errors.append("offset_mm: [x, y] in mm erwartet, je höchstens ±200")
    if merged["exposure"] is not None:
        _number(merged, "exposure", -10000.0, 100000.0, errors)
    k = merged["camera_matrix"]
    if k is not None and not (_matrix(k, 3, 3) and k[0][0] > 0 and k[1][1] > 0):
        errors.append("camera_matrix: 3×3-Matrix mit positiven Brennweiten erwartet")
    d = merged["dist_coeffs"]
    if d is not None and not (_matrix([d], 1, len(d) if isinstance(d, list) else 0)
                              and len(d) in (4, 5, 8, 12, 14) and all(abs(v) < 1000 for v in d)):
        errors.append("dist_coeffs: Liste mit 4, 5, 8, 12 oder 14 endlichen Zahlen erwartet")
    if (k is None) != (d is None):
        errors.append("camera_matrix und dist_coeffs nur zusammen angeben")
    a = merged["android"]
    if a is not None:
        if not isinstance(a, dict):
            errors.append("android: Objekt erwartet")
        else:
            for key in ("photoWidth", "photoHeight"):
                v = a.get(key)
                if isinstance(v, bool) or not isinstance(v, int) or not 160 <= v <= 8192:
                    errors.append("android.%s: ganze Zahl 160 … 8192 erwartet" % key)
            if a.get("lens") is None and not (isinstance(a.get("photo"), list) and len(a["photo"]) == 4):
                errors.append("android: Linsenmodell oder vier Kalibrierpunkte erwartet")
    h = merged["homography"]
    if h is not None and not (_matrix(h, 3, 3) and abs(_det3(h)) > 1e-12):
        errors.append("homography: invertierbare 3×3-Matrix erwartet")
    meta = dict(META_DEFAULTS)
    meta.update({k: data[k] for k in META_DEFAULTS if k in data})
    if not isinstance(meta["calibrated"], bool):
        errors.append("calibrated: true oder false erwartet")
    for key, limit in (("notes", 2000), ("updated_by", 80)):
        if not isinstance(meta[key], str) or len(meta[key]) > limit:
            errors.append("%s: Text mit höchstens %d Zeichen erwartet" % (key, limit))
    if errors:
        raise ValueError("Kalibrierung ungültig: " + "; ".join(errors))
    for key in ("image_width", "image_height", "flip_x", "flip_y"):
        merged[key] = int(merged[key])
    for key in ("px_per_mm", "scan_z", "rotation_deg", "crop_fraction"):
        merged[key] = float(merged[key])
    merged["offset_mm"] = [float(v) for v in off]
    merged.update(meta)
    return merged


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CalibrationStore:
    """Thread-safe load/save of the camera calibration JSON."""

    def __init__(self, paths=None):
        self.paths = [Path(p) for p in (paths or candidate_paths())]
        self._lock = threading.Lock()

    # -- locations ------------------------------------------------------
    @staticmethod
    def _writable(path: Path) -> bool:
        directory = path.parent
        if path.exists() and not os.access(path, os.W_OK) and not os.access(directory, os.W_OK):
            return False
        while not directory.exists():
            directory = directory.parent
        return os.access(directory, os.W_OK | os.X_OK)

    def write_path(self) -> Path | None:
        return next((p for p in self.paths if self._writable(p)), None)

    def read_path(self) -> Path | None:
        target = self.write_path()
        if target is not None and target.is_file():
            return target
        return next((p for p in self.paths if p.is_file()), None)

    # -- read -----------------------------------------------------------
    def load(self) -> dict:
        with self._lock:
            return self._load_locked()

    def _load_locked(self) -> dict:
        path = self.read_path()
        target = self.write_path()
        storage = {"path": str(path or target or self.paths[0]),
                   "write_path": None if target is None else str(target),
                   "writable": target is not None, "error": ""}
        record = None
        if path is not None:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                record = validate(raw)
                record["revision"] = int(raw.get("revision", 0))
                record["updated_at"] = str(raw.get("updated_at", ""))
            except (OSError, ValueError, TypeError) as exc:
                logging.exception("Kamera-Kalibrierung %s unlesbar", path)
                storage["error"] = "Kalibrierdatei %s unlesbar, Platzhalter aktiv: %s" % (path, exc)
                record = None
        placeholder = record is None
        if placeholder:
            record = dict(DEFAULTS, **META_DEFAULTS)
            record.update(revision=0, updated_at="")
        record.update(format=FORMAT, schema_version=SCHEMA_VERSION,
                      placeholder=placeholder, storage=storage,
                      status=("platzhalter" if placeholder else
                              "kalibriert" if record["calibrated"] else "unkalibriert"))
        return copy.deepcopy(record)

    # -- write ----------------------------------------------------------
    def save(self, data: dict, expected_revision, updated_by: str | None = None) -> dict:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("revision fehlt: zuerst GET /api/camera/calibration lesen und "
                             "dessen revision mitschicken")
        record = validate(data)
        if updated_by is not None:
            record["updated_by"] = str(updated_by)[:80]
        with self._lock:
            current = self._load_locked()
            if current["revision"] != expected_revision:
                who = current.get("updated_by") or "unbekannt"
                raise CalibrationConflict(
                    "Kalibrierung wurde inzwischen geändert (Revision %d vom %s durch %s, "
                    "bearbeitet wurde Revision %d). Neu laden und Änderungen erneut eintragen."
                    % (current["revision"], current.get("updated_at") or "?", who,
                       expected_revision), current)
            record["revision"] = current["revision"] + 1
            record["updated_at"] = _now()
            record["format"] = FORMAT
            record["schema_version"] = SCHEMA_VERSION
            text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
            errors = []
            for path in self.paths:
                if not self._writable(path):
                    continue
                try:
                    atomic_write(path, text)
                    break
                except OSError as exc:
                    errors.append("%s: %s" % (path, exc))
            else:
                raise PermissionError("Kalibrierung kann nicht gespeichert werden – kein "
                                      "beschreibbarer Ablageort (" + "; ".join(errors or [
                                          str(p) for p in self.paths]) + ")")
            return self._load_locked()


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` so that readers see either the old or the new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


# -- HTTP API (registered in web.py) ----------------------------------------
def create_blueprint(store_factory=None):
    from flask import Blueprint, jsonify, request

    blueprint = Blueprint("camera_calibration", __name__)
    holder = {}

    def store() -> CalibrationStore:
        if "store" not in holder:
            holder["store"] = (store_factory or CalibrationStore)()
        return holder["store"]

    @blueprint.get("/api/camera/calibration")
    def calibration_get():
        return jsonify(store().load())

    @blueprint.put("/api/camera/calibration")
    def calibration_put():
        # JSON only: a foreign web page cannot send application/json to the Pi
        # without a CORS preflight, which this server never grants (CSRF).
        origin = request.headers.get("Origin")
        if origin and origin.split("://", 1)[-1].rstrip("/") != request.host:
            return jsonify(error="Fremde Webseite darf die Kalibrierung nicht ändern"), 403
        if not request.is_json:
            return jsonify(error="Content-Type application/json erwartet"), 415
        if (request.content_length or 0) > MAX_BYTES:
            return jsonify(error="Kalibrierung zu groß (max. 64 KB)"), 413
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Ungültiges JSON – Objekt mit den Kalibrierwerten erwartet")
        revision = data.get("revision")
        by = data.get("updated_by")
        try:
            saved = store().save(data, revision, None if by is None else str(by))
        except CalibrationConflict as exc:
            return jsonify(error=str(exc), current=exc.current), 409
        where = saved["storage"]["path"]
        return jsonify(dict(saved, message="Kamera-Kalibrierung gespeichert (Revision %d, %s)"
                            % (saved["revision"], where)))

    return blueprint
