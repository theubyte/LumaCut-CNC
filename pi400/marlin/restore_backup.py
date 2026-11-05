"""Put a backup from GET /api/backup back on the Pi (new SD card, damaged data).

On the Pi, with the service stopped:
    sudo systemctl stop lumacut-marlin.service
    sudo -u lumacut env $(sudo cat /etc/lumacut/lumacut.env | xargs) PYTHONPATH=/opt/lumacut/pi400 \
        python3 -m marlin.restore_backup lumacut-sicherung-DATUM.json
    sudo systemctl start lumacut-marlin.service

Every value passes the same checks as at runtime. The mechanics approval is
not restored: a new SD card may sit in a changed machine, so /api/commission
has to be confirmed again. Motion and laser are never touched.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys

from . import bedmap, materials, web
from .camera_calibration import CalibrationStore
from .storage import atomic_write
from .workspace import STATE_KEYS


def _service_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", web.HTTP), timeout=1):
            return True
    except OSError:
        return False


def _materials(body, notes):
    data = body.get("materials")
    if not isinstance(data, dict) or not isinstance(data.get("materials"), list):
        return
    kept = []
    for item in data["materials"]:
        try:
            kept.append(materials.validate(item, material_id=item.get("id"), builtin=item.get("builtin", False)))
        except (ValueError, TypeError, AttributeError) as exc:
            notes.append("Material übersprungen: %s" % exc)
    revision = data.get("revision")
    atomic_write(web.DATA.parent / "materials.json", json.dumps(
        {"revision": revision if type(revision) is int else 1, "materials": kept}, ensure_ascii=False, indent=1))
    notes.append("Materialien: %d" % len(kept))


def restore(body: dict) -> list[str]:
    """Writes what the backup holds, returns what happened line by line."""
    notes = []
    saved = body.get("config")
    if isinstance(saved, dict):
        good = {k: v for k, v in saved.items() if k in web.config and web.valid_setting(k, v)}
        notes.extend("Einstellung %s ungültig, übersprungen" % k for k in saved if k not in good)
        good["validated"] = False
        atomic_write(web.CONFIG, json.dumps(good, indent=2))
        notes.append("Einstellungen: %d (Mechanik-Freigabe neu bestätigen: /api/commission)" % len(good))
    _materials(body, notes)
    state = body.get("workspace")
    if isinstance(state, dict):
        try:
            web.WORKSPACE.put_state({k: state[k] for k in STATE_KEYS if k in state}, None, "Wiederherstellung")
            notes.append("Arbeitsstand wiederhergestellt")
        except (ValueError, TypeError) as exc:
            notes.append("Arbeitsstand übersprungen: %s" % exc)
    calibration = body.get("camera_calibration")
    if isinstance(calibration, dict):
        store = CalibrationStore()
        try:
            store.save(calibration, store.load()["revision"], "Wiederherstellung")
            notes.append("Kamera-Kalibrierung wiederhergestellt")
        except (ValueError, TypeError, PermissionError) as exc:
            notes.append("Kamera-Kalibrierung übersprungen: %s" % exc)
    bed = body.get("bed_map")
    if isinstance(bed, dict):
        try:
            bedmap.save(web.BED_MAP_FILE, bedmap.BedMap.from_dict(bed))
            notes.append("Bettkarte wiederhergestellt")
        except (ValueError, TypeError, KeyError) as exc:
            notes.append("Bettkarte übersprungen: %s" % exc)
    run = body.get("material_calibration")
    if isinstance(run, dict) and web.valid_matcal(run):
        atomic_write(web.MATCAL_FILE, json.dumps(run, ensure_ascii=False, indent=1))
        notes.append("Materialtest-Ergebnis wiederhergestellt")
    return notes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="LumaCut-Sicherung zurückspielen (Dienst vorher stoppen)")
    parser.add_argument("backup", help="Datei aus GET /api/backup")
    args = parser.parse_args(argv)
    if _service_running():
        print("Der Dienst läuft noch: zuerst sudo systemctl stop lumacut-marlin.service", file=sys.stderr)
        return 2
    try:
        with open(args.backup, encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, ValueError) as exc:
        print("Sicherung nicht lesbar: %s" % exc, file=sys.stderr)
        return 2
    if not isinstance(body, dict) or "config" not in body:
        print("Keine LumaCut-Sicherung", file=sys.stderr)
        return 2
    for line in restore(body):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
