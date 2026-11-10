"""Park routine and job start the time estimate plans around every job.

The Pi runs every Studio job from wherever the head is and parks after it
(pi400/marlin/transport.py): a head sitting low in the park corner rises to
the travel height before its first X/Y move (``_unpark_before_locked``),
after the job ``park_safezone`` lifts to ``max(Z, travel height, probe
minimum)``, rapids to ``G0 X0 Y0 F9000`` and lowers to the park height
(``_lower_to_park_locked``). :class:`ParkRoutine` holds those heights,
:class:`JobStart` where the job starts and how the Pi places it.

What ``/api/status`` reports (and is mirrored here – nothing else):

* ``travel_z_mm`` – ``machine.travel_z``: the configured Z clearance
  (``config.z_clearance_mm``, default 20 mm) or material thickness + 20 mm
  when that is higher, at most Z 80 mm. Older answers without it: the
  clearance from ``config.z_clearance_mm``.
* ``config.park_z_mm`` – park height over the bed (default 1 mm, 0 = the head
  stays at the travel height).
* ``probe_minimum_z`` – surface + probe clearance once a surface was probed
  (``park_safezone`` never goes below it), else null.
* ``position`` – head X/Y/Z (machine mm); the job's first move starts there.
  At X0/Y0 at the park height the head is parked low and lifts first.
* ``origin.user`` and the panel's origin choice – the Pi moves the job so
  its anchor lands on the head („Aktuelle Position“) or the user origin
  (``placement.translate``; :func:`lumacut_job.park_corner.placement_offset`).

Not reported: the Z acceleration (firmware ``M201 Z`` 100 mm/s²) and the
park feed (fixed ``F9000``) – they stay mirrors.

Like the motion calibration (:mod:`lumacut_job.motion`) the heights of the
last Pi seen are stored in QSettings so the Windows app estimates with them
offline; the start (head position, origin) is live only – offline the
estimate plans from the park corner with the job unshifted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Callable

PARK_Z_MM = 1.0           # transport.PARK_Z_MM, config park_z_mm
TRAVEL_Z_MM = 20.0        # config z_clearance_mm (travel_z without material)
PARK_FEED = 9000.0        # "G0 X0.000 Y0.000 F9000"
Z_ACCEL = 100.0           # firmware DEFAULT_MAX_ACCELERATION Z (M201 Z, not changed by the Pi)
Z_MAX_MM = 80.0           # transport.Z_MAX_MM

PARK_Z_RANGE = (0.0, 20.0)        # web.py settings: „Parkhöhe muss 0..20 mm sein“
CLEARANCE_RANGE = (0.5, 50.0)     # „Z-Rückzug muss zwischen 0,5 und 50 mm liegen“
TRAVEL_Z_RANGE = (0.5, Z_MAX_MM)  # material + 20 mm, capped at Z_MAX_MM

#: Head within this distance of X0/Y0 and of the park height counts as parked.
PARKED_TOL_MM = 0.05

DEFAULT_SOURCE = "default"
PI = "pi"
SAVED = "saved"
_SOURCE_TEXT = {PI: "Pi", SAVED: "Pi, zuletzt gesehen", DEFAULT_SOURCE: "Standard"}


def _fmt(v: float) -> str:
    return ("%.1f" % v).rstrip("0").rstrip(".")


@dataclass(frozen=True)
class ParkRoutine:
    """Moves the Pi adds around a job (machine mm, head parked at X0/Y0)."""
    park_z: float = PARK_Z_MM
    travel_z: float = TRAVEL_Z_MM
    feed: float = PARK_FEED
    z_accel: float = Z_ACCEL
    #: park_safezone never goes below this before the park move (probe minimum)
    min_park_lift_z: float = 0.0
    source: str = DEFAULT_SOURCE

    @property
    def lift_mm(self) -> float:
        """Rise from the park height to the travel height (0 = parks at travel height)."""
        return max(0.0, self.travel_z - self.park_z) if self.park_z > 0 else 0.0

    @property
    def is_default(self) -> bool:
        return (self.park_z, self.travel_z, self.min_park_lift_z) == (PARK_Z_MM, TRAVEL_Z_MM, 0.0)

    def same_heights(self, other: "ParkRoutine") -> bool:
        return ((self.park_z, self.travel_z, self.min_park_lift_z)
                == (other.park_z, other.travel_z, other.min_park_lift_z))

    def label(self) -> str:
        """``Fahrhöhe 25 mm, Parkhöhe 1 mm (Pi)``."""
        park = "auf Fahrhöhe" if self.park_z <= 0 else f"{_fmt(self.park_z)} mm"
        text = f"Fahrhöhe {_fmt(self.travel_z)} mm, Parkhöhe {park}"
        if self.min_park_lift_z > self.travel_z:
            text += f", Parkfahrt über Z{_fmt(self.min_park_lift_z)}"
        return f"{text} ({_SOURCE_TEXT.get(self.source, self.source)})"

    def with_source(self, source: str) -> "ParkRoutine":
        return replace(self, source=source)


DEFAULT_PARK = ParkRoutine()


@dataclass(frozen=True)
class JobStart:
    """Where the next job starts and how the Pi places it (live, not stored).

    ``head`` = status position (None = unknown: parked low at X0/Y0);
    ``origin`` / ``anchor`` = the panel's choice (visible corner names);
    ``target`` = head X/Y („current“) or user origin („user“), None = unknown
    (the job is planned unshifted, like the park-corner check lets it pass).
    """
    head: tuple[float, float, float] | None = None
    origin: str = "absolute"
    anchor: str = "tr"
    target: tuple[float, float] | None = None

    def offset(self, gcode: str) -> tuple[float, float]:
        """(dx, dy) the Pi adds to every X/Y of ``gcode`` (0, 0 absolute / unknown)."""
        if self.origin == "absolute" or self.target is None:
            return 0.0, 0.0
        from .park_corner import placement_offset, powered_bounds
        box = powered_bounds(gcode)
        if box is None:
            return 0.0, 0.0
        try:
            return placement_offset(box, self.origin, self.anchor, self.target)
        except ValueError:
            return 0.0, 0.0

    def parked_low(self, routine: ParkRoutine) -> bool:
        """Head down in the park corner (the Pi lifts it before the first move)."""
        if self.head is None:
            return routine.park_z > 0
        x, y, z = self.head
        return (routine.park_z > 0 and abs(x) <= PARKED_TOL_MM and abs(y) <= PARKED_TOL_MM
                and z <= routine.park_z + PARKED_TOL_MM)

    def start_xy(self) -> tuple[float, float]:
        return (0.0, 0.0) if self.head is None else (self.head[0], self.head[1])

    def from_park_corner(self) -> bool:
        x, y = self.start_xy()
        return abs(x) <= PARKED_TOL_MM and abs(y) <= PARKED_TOL_MM


DEFAULT_START = JobStart()


# --- status ------------------------------------------------------------------------

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


def _raw(status: Any) -> Any:
    raw = getattr(status, "raw", status)
    return raw if isinstance(raw, dict) else None


def routine_from_status(status: Any) -> ParkRoutine | None:
    """Park / travel heights from a ``/api/status`` answer (or ``MachineStatus``).

    None when the answer carries neither ``config`` nor ``travel_z_mm`` (older
    Pi or a reduced answer) – keep what is known. Missing or out-of-range
    single values fall back to the Pi defaults.
    """
    raw = _raw(status)
    if raw is None:
        return None
    cfg = raw.get("config") if isinstance(raw.get("config"), dict) else None
    travel = _number(raw.get("travel_z_mm"), *TRAVEL_Z_RANGE)
    if cfg is None and travel is None:
        return None
    cfg = cfg or {}
    if travel is None:
        clearance = _number(cfg.get("z_clearance_mm"), *CLEARANCE_RANGE)
        travel = TRAVEL_Z_MM if clearance is None else clearance
    park = _number(cfg.get("park_z_mm"), *PARK_Z_RANGE)
    probe_min = _number(raw.get("probe_minimum_z"), 0.0, Z_MAX_MM)
    return ParkRoutine(park_z=PARK_Z_MM if park is None else park, travel_z=travel,
                       min_park_lift_z=probe_min or 0.0, source=PI)


def start_from_status(status: Any, origin: str = "absolute", anchor: str = "tr") -> JobStart:
    """Job start from a status (``MachineStatus`` or raw dict) and the origin choice."""
    head = getattr(status, "position", None)
    if head is None:
        raw = _raw(status) or {}
        pos = raw.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) >= 3:
            vals = [_number(v, -1e6, 1e6) for v in pos[:3]]
            head = None if any(v is None for v in vals) else tuple(vals)
    else:
        try:
            head = tuple(float(v) for v in head[:3])
            if len(head) < 3 or not all(math.isfinite(v) for v in head):
                head = None
        except (TypeError, ValueError):
            head = None
    target = None
    if origin == "current" and head is not None:
        target = (head[0], head[1])
    elif origin == "user":
        user = getattr(getattr(status, "origin", None), "user", None)
        if user is None:
            o = (_raw(status) or {}).get("origin")
            user = o.get("user") if isinstance(o, dict) else None
        try:
            target = (float(user[0]), float(user[1])) if user else None
        except (TypeError, ValueError, IndexError):
            target = None
    elif origin != "absolute":
        origin = "absolute"
    return JobStart(head, origin, anchor, target)


# --- active routine / start ----------------------------------------------------------

_active_park: ParkRoutine = DEFAULT_PARK
_active_start: JobStart = DEFAULT_START
_listeners: list[Callable[[], None]] = []


def active_park() -> ParkRoutine:
    return _active_park


def active_start() -> JobStart:
    return _active_start


def _notify() -> None:
    for cb in list(_listeners):
        try:
            cb()
        except Exception:  # pragma: no cover - a listener must not break the others
            import logging
            logging.getLogger(__name__).exception("Park-Listener fehlgeschlagen")


def set_active_park(routine: ParkRoutine | None) -> bool:
    """Heights the estimate uses by default (None = Pi defaults); True if changed."""
    global _active_park
    new = DEFAULT_PARK if routine is None else routine
    changed = not new.same_heights(_active_park)
    _active_park = new
    if changed:
        _notify()
    return changed


def set_active_start(start: JobStart | None) -> bool:
    """Start / placement the estimate uses by default (None = park corner, absolute)."""
    global _active_start
    new = DEFAULT_START if start is None else start
    changed = new != _active_start
    _active_start = new
    if changed:
        _notify()
    return changed


def add_park_listener(cb: Callable[[], None]) -> None:
    if cb not in _listeners:
        _listeners.append(cb)


def remove_park_listener(cb: Callable[[], None]) -> None:
    if cb in _listeners:
        _listeners.remove(cb)


# --- persistence (same QSettings store as the motion calibration) -------------------

_KEY_PARK = "estimate/park_z"
_KEY_TRAVEL = "estimate/travel_z"


def load_saved(store) -> ParkRoutine | None:
    """Heights of the last Pi seen, or None (nothing / invalid stored)."""
    try:
        park = _number(store.value(_KEY_PARK), *PARK_Z_RANGE)
        travel = _number(store.value(_KEY_TRAVEL), *TRAVEL_Z_RANGE)
    except Exception:
        return None
    if park is None or travel is None:
        return None
    routine = ParkRoutine(park_z=park, travel_z=travel, source=SAVED)
    return None if routine.is_default else routine


def save(store, routine: ParkRoutine) -> None:
    """Store park / travel height (the probe minimum belongs to one surface – not stored)."""
    store.setValue(_KEY_PARK, float(routine.park_z))
    store.setValue(_KEY_TRAVEL, float(routine.travel_z))
    sync = getattr(store, "sync", None)
    if sync is not None:
        sync()


class ParkSync:
    """Follows the Machine panel's status polls and origin choice.

    On start the heights stored in ``store`` become active („zuletzt
    gesehen“); every status with ``config`` / ``travel_z_mm`` sets the Pi's
    heights and stores changed ones. The start (head position, origin,
    target) follows every status and origin / anchor change – not while the
    Pi runs a job or a frame (the head moves, the next job starts after it).
    """

    def __init__(self, machine_panel=None, store=None) -> None:
        if store is None:
            from .motion import default_store
            store = default_store()
        self.store = store
        self.machine = machine_panel
        saved = load_saved(store)
        if saved is not None:
            set_active_park(saved)
        sig = getattr(machine_panel, "status_changed", None)
        if sig is not None:
            sig.connect(self.on_status)
        for name in ("origin_combo", "anchor_combo"):
            combo = getattr(machine_panel, name, None)
            if combo is not None and hasattr(combo, "currentIndexChanged"):
                combo.currentIndexChanged.connect(lambda _i=0: self.update_start())

    def _origin(self, status) -> tuple[str, str]:
        job_origin = getattr(self.machine, "job_origin", None)
        if not callable(job_origin):
            return "absolute", "tr"
        try:
            origin, wire = job_origin()
        except Exception:  # noqa: BLE001 - panel without status
            return "absolute", "tr"
        from .park_corner import visible_anchor
        return str(origin), visible_anchor(str(wire), getattr(status, "coord_convention", None))

    def update_start(self, status=None) -> JobStart | None:
        if status is None:
            status = getattr(self.machine, "_status", None)
        if status is None:
            set_active_start(None)
            return None
        raw = _raw(status) or {}
        running = (raw.get("activity") in ("job", "framing")
                   or getattr(getattr(status, "job", None), "active", False) is True
                   or getattr(status, "framing", False) is True)
        if running:
            return active_start()
        start = start_from_status(status, *self._origin(status))
        set_active_start(start)
        return start

    def on_status(self, status) -> ParkRoutine | None:
        routine = routine_from_status(status)
        if routine is not None:
            current = active_park()
            if current.source != PI or not routine.same_heights(current):
                set_active_park(routine)
                save(self.store, routine)
        self.update_start(status)
        return routine
