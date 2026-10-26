"""JSON/HTTP-Vertrag für Kamera-Scan und Ein-Klick-Auftrag (Qt-frei).

Anforderungen 2026-10-26 §3: Der Kamera-Scan ist ein optionaler Knopf in
Studio und soll später auch aus einer Android-App gehen. Dieses Modul legt
die Nachrichten fest; Studio nutzt sie für Ereignisse, ein späterer HTTP-
Dienst (Pi oder Studio) kann sie 1:1 ausliefern. **Es gibt dafür heute noch
keinen Server** – die Endpunkte in :data:`ENDPOINTS` sind ein Vorschlag
(``docs/SCAN_PROBE.md``).

Alle Koordinaten in Maschinen-mm (Laserpunkt), Zeiten in Sekunden, Texte
deutsch. Jede Nachricht hat ``"type"``; Clients ignorieren unbekannte Felder.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .control import Progress
from .job_flow import ERROR_CODES, STATES, STEPS

CONTRACT = "lumacut-scanprobe/1"

#: Vorgeschlagene HTTP-Endpunkte (noch nicht implementiert).
ENDPOINTS = {
    "POST /api/scan": "Kamera-Scan starten (ScanRequest) → scan_progress …",
    "GET /api/scan": "letztes scan_progress bzw. scan_result",
    "GET /api/scan/mosaic.png": "Mosaikbild (PNG), Metadaten in scan_result.mosaic",
    "POST /api/scan/cancel": "Scan abbrechen",
    "POST /api/oneclick": "Ein-Klick-Auftrag starten (JobRequest) → job_state …",
    "GET /api/oneclick": "letztes job_state bzw. job_result",
    "POST /api/oneclick/pause": "Pause zwischen zwei Maschinenschritten (nicht während des Laserns)",
    "POST /api/oneclick/resume": "Fortsetzen",
    "POST /api/oneclick/cancel": "Abbrechen (vor dem Lasern: parken; beim Lasern: op=abort am Pi)",
}

MESSAGE_TYPES = ("scan_progress", "scan_result", "job_state", "job_result", "error")
SCAN_PHASES = ("scan", "stitch", "detect", "probe", "verify")
CAMERAS = ("pi", "local")
JOB_STATE_KEYS = ("type", "state", "label", "step", "steps", "message", "progress", "paused")


@dataclass(frozen=True)
class ScanRequest:
    camera: str = "pi"
    bounds: Optional[tuple[float, float, float, float]] = None  # None = ganze Arbeitsfläche
    overlap: float = 0.25

    def to_dict(self) -> dict:
        return {"type": "scan_request", "camera": self.camera,
                "bounds": None if self.bounds is None else list(self.bounds),
                "overlap": self.overlap}


@dataclass(frozen=True)
class JobRequest:
    name: str
    gcode: str
    reuse_mesh: bool = True

    def to_dict(self) -> dict:
        return {"type": "job_request", "name": self.name, "gcode": self.gcode,
                "reuse_mesh": self.reuse_mesh}


def parse_scan_request(d: Any) -> ScanRequest:
    if not isinstance(d, dict):
        raise ValueError("Scan-Anfrage muss ein JSON-Objekt sein")
    camera = d.get("camera", "pi")
    if camera not in CAMERAS:
        raise ValueError(f"Kamera muss {' oder '.join(CAMERAS)} sein")
    bounds = d.get("bounds")
    if bounds is not None:
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
                or not all(isinstance(v, (int, float)) for v in bounds)):
            raise ValueError("bounds: [x0, y0, x1, y1] in mm")
        x0, y0, x1, y1 = (float(v) for v in bounds)
        if x1 <= x0 or y1 <= y0:
            raise ValueError("bounds: x1 > x0 und y1 > y0")
        bounds = (x0, y0, x1, y1)
    overlap = d.get("overlap", 0.25)
    if not isinstance(overlap, (int, float)) or not 0.05 <= overlap <= 0.6:
        raise ValueError("overlap muss zwischen 0.05 und 0.6 liegen")
    return ScanRequest(camera, bounds, float(overlap))


def parse_job_request(d: Any) -> JobRequest:
    if not isinstance(d, dict):
        raise ValueError("Auftrag muss ein JSON-Objekt sein")
    name, gcode = d.get("name"), d.get("gcode")
    if not isinstance(name, str) or not name.lower().endswith((".gcode", ".nc", ".gc")) \
            or "/" in name or "\\" in name:
        raise ValueError("name: Dateiname mit .gcode/.nc/.gc ohne Pfad")
    if not isinstance(gcode, str) or not gcode.strip():
        raise ValueError("gcode fehlt oder ist leer")
    reuse = d.get("reuse_mesh", True)
    if not isinstance(reuse, bool):
        raise ValueError("reuse_mesh muss true/false sein")
    return JobRequest(name, gcode, reuse)


def scan_progress(p: Progress) -> dict:
    return {"type": "scan_progress", "phase": p.phase, "done": int(p.done), "total": int(p.total),
            "progress": round(p.fraction, 4), "message": p.message,
            "eta_s": None if p.eta_s is None else round(float(p.eta_s), 1)}


def scan_result(mosaic, objects: Sequence = (), *, image: bool = False) -> dict:
    """Mosaik-Metadaten (+ optional PNG als Base64) und erkannte Werkstücke."""
    out: dict = {"type": "scan_result", "contract": CONTRACT,
                 "mosaic": mosaic.metadata() if mosaic is not None else None,
                 "objects": [_object_dict(o) for o in objects]}
    if image and mosaic is not None:
        import cv2
        ok, buf = cv2.imencode(".png", mosaic.image)
        if not ok:
            raise ValueError("Mosaik konnte nicht als PNG kodiert werden")
        out["image_png_base64"] = base64.b64encode(buf.tobytes()).decode("ascii")
    return out


def _object_dict(o) -> dict:
    return {"id": o.id, "kind": o.kind, "bounds": o.bounds.to_list(),
            "center": [float(o.center[0]), float(o.center[1])],
            "area_mm2": float(o.area_mm2), "confidence": float(o.confidence)}


def error_message(code: str, message: str) -> dict:
    return {"type": "error", "code": code, "message": message}


def validate_message(d: Any) -> list[str]:
    """Prüft eine ausgehende Nachricht; Rückgabe: Liste der Verstöße (leer = ok)."""
    problems: list[str] = []
    if not isinstance(d, dict) or d.get("type") not in MESSAGE_TYPES:
        return ["unbekannter Nachrichtentyp"]
    t = d["type"]
    if t == "job_state":
        problems += [f"Feld {k} fehlt" for k in JOB_STATE_KEYS if k not in d]
        if d.get("state") not in STATES:
            problems.append("unbekannter Zustand")
        if d.get("state") in STEPS and d.get("step") != STEPS.index(d["state"]) + 1:
            problems.append("step passt nicht zum Zustand")
        err = d.get("error")
        if err is not None and err.get("code") not in ERROR_CODES:
            problems.append("unbekannter Fehlercode")
    elif t == "job_result":
        if d.get("state") not in STATES:
            problems.append("unbekannter Zustand")
        err = d.get("error")
        if err is not None and err.get("code") not in ERROR_CODES:
            problems.append("unbekannter Fehlercode")
    elif t == "scan_progress":
        if d.get("phase") not in SCAN_PHASES:
            problems.append("unbekannte Scan-Phase")
    elif t == "scan_result":
        if d.get("contract") != CONTRACT:
            problems.append("falsche Vertragsversion")
    elif t == "error" and d.get("code") not in ERROR_CODES:
        problems.append("unbekannter Fehlercode")
    return problems
