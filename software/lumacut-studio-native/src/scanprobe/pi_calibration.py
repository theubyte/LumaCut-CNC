"""Kamera-Kalibrierung vom Pi laden und dorthin zurückschreiben.

Die Kalibrierung gehört zur Maschine und liegt auf dem Pi
(``/etc/lumacut/camera_calibration.json``, ``GET/PUT /api/camera/calibration``).
``camera.json`` bleibt Import/Export-Datei und Rückfall für Simulation/offline.
Schreiben ist optimistisch: mitgeschickt wird die zuletzt gelesene Revision;
hat jemand anderes inzwischen gespeichert, meldet der Pi 409 (:class:`Conflict`).
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Any, Optional

from .calibration import CameraCalibration


class PiCalibrationError(RuntimeError):
    """Deutsche Meldung für die Oberfläche."""


class NotSupported(PiCalibrationError):
    """Pi-Software ohne /api/camera/calibration."""


class Unreachable(PiCalibrationError):
    pass


class Conflict(PiCalibrationError):
    def __init__(self, message: str, current: Optional["PiCalibration"]):
        super().__init__(message)
        self.current = current


TOO_OLD = ("Pi-Software zu alt – Kalibrierung wird nicht auf dem Pi gespeichert. "
           "Pi aktualisieren (pi400/update.sh); bis dahin camera.json importieren.")


@dataclass
class PiCalibration:
    calibration: CameraCalibration
    revision: int = 0
    placeholder: bool = True
    calibrated: bool = False
    updated_at: str = ""
    updated_by: str = ""
    notes: str = ""
    path: str = ""
    writable: bool = True
    storage_error: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_response(cls, data: dict) -> "PiCalibration":
        storage = data.get("storage") if isinstance(data.get("storage"), dict) else {}
        try:
            cal = CameraCalibration.from_dict(data)
        except (TypeError, ValueError) as exc:
            raise PiCalibrationError(f"Kalibrierung vom Pi unlesbar: {exc}") from None
        return cls(cal, int(data.get("revision") or 0), bool(data.get("placeholder")),
                   bool(data.get("calibrated")), str(data.get("updated_at") or ""),
                   str(data.get("updated_by") or ""), str(data.get("notes") or ""),
                   str(storage.get("path") or ""), bool(storage.get("writable", True)),
                   str(storage.get("error") or ""), dict(data))

    def status_text(self) -> str:
        cal = self.calibration
        values = f"{cal.px_per_mm:.2f} px/mm @ Z{cal.scan_z:.0f}, {cal.image_width}×{cal.image_height}"
        if self.placeholder:
            text = "Pi: Platzhalter (unkalibriert) – camera.json importieren und „Auf Pi speichern“"
        else:
            state = "kalibriert" if self.calibrated else "unkalibriert"
            who = f", {self.updated_by}" if self.updated_by else ""
            when = self.updated_at.replace("T", " ").rstrip("Z")
            text = f"Pi: {state}, Revision {self.revision} ({when}{who}) – {values}"
        if self.storage_error:
            text += f"\n⚠ {self.storage_error}"
        if not self.writable:
            text += "\n⚠ Pi kann die Kalibrierung nicht speichern (Ablageort schreibgeschützt)"
        return text


def _map_error(exc: Exception, action: str) -> PiCalibrationError:
    from machine.client import ApiError, ConnectionFailed
    status = getattr(exc, "status", None)
    if isinstance(exc, ApiError) and status in (404, 405):
        return NotSupported(TOO_OLD)
    if isinstance(exc, ConnectionFailed):
        return Unreachable(f"Pi nicht erreichbar – Kalibrierung {action} nicht möglich ({exc})")
    return PiCalibrationError(f"Kalibrierung {action} fehlgeschlagen: {exc}")


def fetch(client: Any) -> PiCalibration:
    try:
        data = client.camera_calibration()
    except Exception as exc:  # noqa: BLE001 - in deutsche Meldung übersetzen
        raise _map_error(exc, "laden") from None
    return PiCalibration.from_response(data)


def is_placeholder_values(cal: CameraCalibration) -> bool:
    from .adapters import default_calibration
    return cal.to_dict() == default_calibration().to_dict()


def store(client: Any, cal: CameraCalibration, revision: int, *, notes: Optional[str] = None,
          calibrated: Optional[bool] = None, updated_by: Optional[str] = None) -> PiCalibration:
    """Kalibrierung auf den Pi schreiben (Revision = zuletzt gelesene)."""
    from machine.client import ApiError
    record = cal.to_dict()
    record["calibrated"] = (not is_placeholder_values(cal)) if calibrated is None else bool(calibrated)
    record["updated_by"] = (updated_by or f"LumaCut Studio ({socket.gethostname()})")[:80]
    if notes is not None:
        record["notes"] = notes[:2000]
    try:
        data = client.put_camera_calibration(record, revision)
    except ApiError as exc:
        if exc.status == 409:
            payload = exc.payload if isinstance(exc.payload, dict) else {}
            current = payload.get("current")
            pc = PiCalibration.from_response(current) if isinstance(current, dict) else None
            reason = payload.get("error") or "Kalibrierung wurde inzwischen auf dem Pi geändert."
            raise Conflict(f"{reason}", pc) from None
        raise _map_error(exc, "speichern") from None
    except Exception as exc:  # noqa: BLE001
        raise _map_error(exc, "speichern") from None
    return PiCalibration.from_response(data)
