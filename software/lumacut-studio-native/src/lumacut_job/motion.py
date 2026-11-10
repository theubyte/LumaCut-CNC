"""Motion limits the time estimate plans with (Pi motion calibration).

The Pi keeps a motion calibration ``config.motion = {accel, speed}`` (mm/s²,
mm/s; ``null`` = firmware 500 mm/s² / 150 mm/s) and sends it as ``M201 X Y``,
``M203 X Y Z9`` and ``M204 P T`` at every controller connection – jobs run
with it. On a weaker controller (Atomstack / Grbl) ``/api/status`` reports it
already capped to ``$120`` / ``$110``. ``config.z_speed_mm_s`` is the Z top
speed (the SKR firmware caps ``M203 Z`` at 9 mm/s).

LightBurn plans its preview time with the device's acceleration settings and
xTool Creative Space with the machine model's; so far LumaCut always used the
firmware defaults, which overestimated jobs on a calibrated SKR
(2100 mm/s², 200 mm/s) by a wide margin. :func:`active_motion` is what
:func:`lumacut_job.estimate.estimate_gcode` uses when no explicit limits are
passed; :class:`MotionSync` (Qt) follows the Machine panel's status polls and
keeps the last seen calibration in QSettings so the Windows app estimates with
it offline, too.

Model: Marlin limits the feed per axis (``M203 X Y``), so a diagonal move may
run faster than ``speed`` when its F asks for it (the axis components stay at
or below ``speed``); with ``M201 X`` = ``Y`` = ``M204`` the acceleration is the
same in every direction. Cartesian kinematics (the SKR machine); a CoreXY
frame would limit the motor axes instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

FIRMWARE_ACCEL = 500.0      # mm/s²  (docs/MASCHINE.md, pi400 FIRMWARE_MOTION)
FIRMWARE_SPEED = 150.0      # mm/s
FIRMWARE_Z_SPEED = 9.0      # mm/s, M203 Z cap of the LumaCut firmware

ACCEL_RANGE = (100.0, 20000.0)   # Pi op=motion_limits
SPEED_RANGE = (10.0, 500.0)
Z_SPEED_RANGE = (2.0, 30.0)

FIRMWARE = "firmware"
PI = "pi"            # read from the connected Pi in this session
PI_FIRMWARE = "pi_firmware"   # Pi seen, no calibration saved (firmware values)
EXPLICIT = "explicit"         # limits passed to estimate_gcode directly
SAVED = "saved"      # last calibration seen, loaded from QSettings

_SOURCE_TEXT = {FIRMWARE: "Firmware-Standard", PI: "Pi-Kalibrierung",
                PI_FIRMWARE: "Pi ohne Kalibrierung (Firmware)",
                SAVED: "Pi-Kalibrierung (zuletzt gesehen)", EXPLICIT: "Vorgabe"}


@dataclass(frozen=True)
class MotionProfile:
    accel: float = FIRMWARE_ACCEL       # mm/s², X/Y
    speed: float = FIRMWARE_SPEED       # mm/s, per X/Y axis
    z_speed: float = FIRMWARE_Z_SPEED   # mm/s
    source: str = FIRMWARE

    @property
    def is_default(self) -> bool:
        return (self.accel, self.speed, self.z_speed) == (
            FIRMWARE_ACCEL, FIRMWARE_SPEED, FIRMWARE_Z_SPEED)

    def same_limits(self, other: "MotionProfile") -> bool:
        return (self.accel, self.speed, self.z_speed) == (other.accel, other.speed, other.z_speed)

    def label(self) -> str:
        """``Pi-Kalibrierung 2100 mm/s², 200 mm/s`` (Z only when not 9 mm/s)."""
        text = f"{_SOURCE_TEXT.get(self.source, self.source)} {self.accel:g} mm/s², {self.speed:g} mm/s"
        if self.z_speed != FIRMWARE_Z_SPEED:
            text += f", Z {self.z_speed:g} mm/s"
        return text

    def with_source(self, source: str) -> "MotionProfile":
        return MotionProfile(self.accel, self.speed, self.z_speed, source)


DEFAULT = MotionProfile()


def _number(value: Any, lo: float, hi: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        v = float(value)
    except ValueError:
        return None
    if not math.isfinite(v) or not lo <= v <= hi:
        return None
    return v


def motion_from_status(raw: Any) -> MotionProfile | None:
    """Motion limits from a ``/api/status`` answer (``MachineStatus.raw``).

    ``None`` when the answer carries no ``config`` (older Pi or a reduced
    answer) – keep what is known. ``config.motion`` null / incomplete / out of
    range means the Pi runs the firmware values. Z: ``z_speed_mm_s`` capped
    at the firmware's 9 mm/s.
    """
    if not isinstance(raw, dict):
        return None
    cfg = raw.get("config")
    if not isinstance(cfg, dict):
        return None
    motion = cfg.get("motion") if isinstance(cfg.get("motion"), dict) else {}
    accel = _number(motion.get("accel"), *ACCEL_RANGE)
    speed = _number(motion.get("speed"), *SPEED_RANGE)
    z = _number(cfg.get("z_speed_mm_s"), *Z_SPEED_RANGE)
    z = FIRMWARE_Z_SPEED if z is None else min(z, FIRMWARE_Z_SPEED)
    if accel is None or speed is None:
        return MotionProfile(z_speed=z, source=PI_FIRMWARE)
    return MotionProfile(accel, speed, z, PI)


# --- active profile ------------------------------------------------------

_active: MotionProfile = DEFAULT
_listeners: list[Callable[[MotionProfile], None]] = []


def active_motion() -> MotionProfile:
    """Limits the estimate uses by default (firmware values until a Pi is seen)."""
    return _active


def set_active_motion(profile: MotionProfile | None) -> bool:
    """Set the default limits (``None`` = firmware). Returns True if they changed;
    listeners are called only then."""
    global _active
    new = DEFAULT if profile is None else profile
    changed = not new.same_limits(_active)
    _active = new
    if changed:
        for cb in list(_listeners):
            try:
                cb(new)
            except Exception:  # pragma: no cover - a listener must not break the others
                import logging
                logging.getLogger(__name__).exception("Bewegungs-Listener fehlgeschlagen")
    return changed


def add_motion_listener(cb: Callable[[MotionProfile], None]) -> None:
    if cb not in _listeners:
        _listeners.append(cb)


def remove_motion_listener(cb: Callable[[MotionProfile], None]) -> None:
    if cb in _listeners:
        _listeners.remove(cb)


# --- persistence (QSettings-like store: value / setValue / remove) -------------

_KEY_ACCEL = "estimate/motion_accel"
_KEY_SPEED = "estimate/motion_speed"
_KEY_Z = "estimate/motion_z_speed"


def load_saved(store) -> MotionProfile | None:
    """Last calibration seen on a Pi, or None (nothing / invalid stored)."""
    try:
        accel = _number(store.value(_KEY_ACCEL), *ACCEL_RANGE)
        speed = _number(store.value(_KEY_SPEED), *SPEED_RANGE)
        z = _number(store.value(_KEY_Z), *Z_SPEED_RANGE)
    except Exception:
        return None
    if accel is None or speed is None:
        return None
    profile = MotionProfile(accel, speed,
                            FIRMWARE_Z_SPEED if z is None else min(z, FIRMWARE_Z_SPEED), SAVED)
    return None if profile.is_default else profile


def save(store, profile: MotionProfile) -> None:
    store.setValue(_KEY_ACCEL, float(profile.accel))
    store.setValue(_KEY_SPEED, float(profile.speed))
    store.setValue(_KEY_Z, float(profile.z_speed))
    sync = getattr(store, "sync", None)
    if sync is not None:
        sync()


def default_store():
    import os
    from PySide6.QtCore import QSettings
    path = os.environ.get("LUMACUT_MOTION_SETTINGS")
    if path:
        return QSettings(path, QSettings.IniFormat)
    return QSettings("LumaCut", "LumaCut Studio")


class MotionSync:
    """Follows the Machine panel's status polls (``status_changed``).

    On start the last calibration stored in ``store`` becomes active (source
    „zuletzt gesehen“); every status with a ``config`` sets the Pi's limits
    and stores them when they differ. ``store=None`` = the app's QSettings
    (or the ini file named by ``LUMACUT_MOTION_SETTINGS`` – the tests use a
    temporary one so a test never changes the estimate of a later run).
    """

    def __init__(self, machine_panel=None, store=None) -> None:
        if store is None:
            store = default_store()
        self.store = store
        saved = load_saved(store)
        if saved is not None:
            set_active_motion(saved)
        sig = getattr(machine_panel, "status_changed", None)
        if sig is not None:
            sig.connect(self.on_status)

    def on_status(self, status) -> MotionProfile | None:
        profile = motion_from_status(getattr(status, "raw", status))
        if profile is None:
            return None
        current = active_motion()
        if current.source not in (PI, PI_FIRMWARE) or not profile.same_limits(current):
            set_active_motion(profile)
            # firmware limits (motion null) are stored too: a reset calibration
            # must not come back from QSettings on the next start
            save(self.store, profile)
        return profile
