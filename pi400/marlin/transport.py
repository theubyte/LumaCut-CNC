"""USB transport to the LumaCut firmware and exclusive LightBurn/TCP gateway.

The firmware's G-code subset and its answers are the contract in
docs/FIRMWARE_EIGEN.md. No '?'/$-commands, no blind line flooding.
One acknowledged command is in flight at a time, except for plain job moves
sent with stream_command(): there a small, ok-counted window
(STREAM_MAX_LINES / STREAM_MAX_BYTES, half of the firmware's receive side)
keeps the planner fed. Every streamed line passes the same MarlinLaserGuard
and XY/Z guards first.
Live cutting requires validated homing, PWM isolation and hard interlock.
"""
from __future__ import annotations

import logging
import os
import re
import socket
import threading
import time
from collections import deque

LOG = logging.getLogger("lumacut.marlin")

# Melodies on the stepper coils (LumaCut firmware M300: no motion, laser off).
# (frequency Hz, duration ms); 0 Hz is a rest. No tones on alarms by design.
# Light effects on the dimmable 24 V LED strip (PC8, firmware M355): steps
# of (brightness %, duration ms). Afterwards the light returns to the
# operator's setting. Alarms get light only, never tones.
LIGHT_EFFECTS = {
    "home": ((100, 120), (0, 100), (100, 120), (0, 100)),
    "start": ((10, 60), (25, 60), (45, 60), (70, 60), (100, 250)),
    "done": ((100, 250), (20, 250), (100, 250), (20, 250), (100, 250), (20, 250), (100, 300)),
    "error": ((100, 80), (0, 80)) * 3,
}

MELODIES = {
    "home": ((784, 130), (0, 40), (1047, 260)),
    "start": ((523, 110), (659, 110), (784, 220)),
    "done": ((784, 120), (659, 120), (523, 120), (0, 60), (1047, 320)),
}
POSITION_RE = re.compile(
    r"(?:^|\s)X:([-+]?\d+(?:\.\d+)?)\s+Y:([-+]?\d+(?:\.\d+)?)\s+Z:([-+]?\d+(?:\.\d+)?)")
PROBE_RESULT_RE = re.compile(
    r"\bBed X:[-+]?\d+(?:\.\d+)? Y:[-+]?\d+(?:\.\d+)? Z:([-+]?\d+(?:\.\d+)?)")
WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
COMMENT = re.compile(r"\([^()]*\)")
READ_ONLY = frozenset({"M114", "M115", "M119", "M122", "M400"})
# LightBurn and its exports send these; the firmware rejects them and they
# change nothing here (one coordinate frame, no M7 output, M30 is no job end).
FILTERED = frozenset({"M30", "G54", "M7", "G17", "G40"})
# Every endstop stops all axes, switches the laser off and empties the queue
# (contract, Sicherheit 7), then reports "endstops hit: X:.. Y:.. Z:..".
# A Z hit always aborts. A X/Y hit is expected only on the way to that axis's
# zero (parking at the switches), see MarlinTransport._is_fault_locked.
Z_ENDSTOP_HIT = re.compile(r"endstops hit:.*[ :]Z:", re.IGNORECASE)
ENDSTOP_HIT = re.compile(r"endstops hit:(.*)", re.IGNORECASE)
ENDSTOP_AXIS = re.compile(r"(?:^|[ :])([XYZ]):")
AT_SWITCH_MM = 0.5     # a target this close to zero runs onto the switch


def is_marlin_error(line: str) -> bool:
    return line.startswith("Error:") or Z_ENDSTOP_HIT.search(line) is not None
# Streaming window (#18). The firmware's receive side holds at least 16 lines
# of 96 characters: stay at half of both so a slow ok can never overflow it.
# LUMACUT_STREAM_WINDOW=1 restores strict one-line-at-a-time sending.
def _stream_window_setting(raw) -> int:
    try:
        return max(1, min(16, int(raw)))
    except (TypeError, ValueError):
        return 8


STREAM_MAX_LINES = _stream_window_setting(os.environ.get("LUMACUT_STREAM_WINDOW", "8"))
STREAM_MAX_BYTES = 768
STREAMABLE = re.compile(r"^G0?[01]\s")
# X/Y travel until web.py sets the Pi's configured one (config "travels";
# measured with head v6 on 31.10.2026: 370 x 360, set via /api/settings).
TRAVEL_XY_MM = (390.0, 370.0)
# Park corner: at X0/Y0 the v6 housing reaches 67 mm towards +X and 24 mm
# towards +Y from the beam (build_kopf_v6.py), plus 10 mm. Burning is
# forbidden only inside this rectangle; everything else is work area.
PARK_CORNER_MM = (78.0, 35.0)
# The Pi probes only with the head this far from the bed edges, on both sides
# (the high side is travel - 10). The laser is off while probing, so the head
# may enter the park corner.
PROBE_HEAD_MIN = (10.0, 10.0)
# Fast multi-point probing: low hop between the points of one area.
PROBE_HOP_MM = 3.0
# Highest switch-tip Z above the homed bed: above 80 mm the head runs out
# of the Z linear rail. The firmware's hard limit is the same; the Pi checks
# it as well, before anything is sent.
Z_MAX_MM = 80.0
# Parked and after homing the head waits this low over the bed in the park
# corner (owner 31.10.): with the motors unpowered (emergency stop, board
# reset, power loss) the rack-driven Z can only drop this far.
PARK_Z_MM = 1.0
_XY_MOTION = re.compile(r"^G0?[0123](?:\s|$)")
# Z steps/mm of the worm lift (head v6 retrofit /mfw/zmount/v7/nachruest,
# 01.11.): worm 1:10, pinion 10 teeth module 1 on a printed rack = 3.1416 mm
# per motor turn, 16 microsteps. Sent on every connect: the Pi owns the value.
Z_STEPS_PER_MM = 1018.59
# Firmware errors after which the position in the firmware is no longer true.
REFERENCE_LOST_ERRORS = ("Error:Planner underrun", "Error:Driver reset")
# op=z_test: Z without homing to check the direction, slow (2 mm/s).
Z_TEST_MAX_MM = 10.0
Z_TEST_FEED_MM_MIN = 120
AXIS_TEST_FEED_MM_MIN = 300
AXIS_TEST_CENTER = {"X": 195, "Y": 185}
# Z max feedrate (M203 Z). 9 mm/s from the belt drive; the worm lift reaches
# ~30 (owner raises it in steps, config z_speed_mm_s), but the firmware caps
# M203 Z at 9 (contract). Z travel moves ask for this speed, M203 caps them.
Z_SPEED_DEFAULT = 9.0
Z_SPEED_MAX = 30.0
SUPPLY_TEST_MAX_S = 30.0  # op=supply_test: laser rail on for measuring, beam off
SERVICE_LASER_PING_S = 5.0  # service slider: beam off when the page stops confirming
TTL_TEST_MAX_S = 10.0  # op=ttl_test: PWM pin at full duty, laser relay off
# Z0 is where the switch homes, not the bed: the bare bed measured 0.7 to
# 1.2 mm below it (2026-10-29), so a contact down to this depth is real.
BED_BELOW_Z0_MM = 3.0
# Travel height over unknown ground = material thickness + this (owner's
# rule): the probe tip, the lowest part of the head, clears everything.
TRAVEL_GAP_MM = 20.0
# Least relative lift before homing when Z is unknown (the head may stand
# just above the workpiece after an emergency stop).
MIN_BLIND_LIFT_MM = 5.0


def _fault_text(line: str) -> str:
    if Z_ENDSTOP_HIT.search(line):
        return "Z-Taster während der Fahrt ausgelöst, Z gestoppt: " + line[:120]
    hit = ENDSTOP_HIT.search(line)
    if hit:
        return ("Endschalter %s während der Fahrt ausgelöst, alle Achsen gestoppt: "
                % "/".join(ENDSTOP_AXIS.findall(hit.group(1)))) + line[:120]
    return "Firmware: " + line[:150]


class MarlinCommandError(RuntimeError):
    """The firmware rejected a command but the serial protocol is in sync."""

    responses: list = []


class Aborted(RuntimeError):
    """The operator stopped the run between two safe steps (laser off)."""

    def __init__(self, message="Abgebrochen"):
        super().__init__(message)


class ProbeFailed(RuntimeError):
    """One probe point of probe_surface failed; ``cause`` says why."""

    def __init__(self, x, y, cause):
        super().__init__("Abtasten bei X%.1f Y%.1f fehlgeschlagen: %s" % (x, y, cause))
        self.x, self.y, self.cause = x, y, cause



def normalize(line: str) -> str:
    while True:
        transformed = COMMENT.sub("", line)
        if transformed == line:
            break
        line = transformed
    return line.split(";", 1)[0].strip().upper()


# X/Y acceleration (mm/s²) and top speed (mm/s), defaults of the firmware
# (docs/FIRMWARE_EIGEN.md, Maschine).
FIRMWARE_MOTION = (500.0, 150.0)
# Hard caps for runtime limits and the motion test (belt-driven diode gantry).
MOTION_ACCEL_RANGE = (100.0, 20000.0)
MOTION_SPEED_RANGE = (10.0, 500.0)


def parse_endstops(lines) -> dict:
    """M119 report -> {"x_min": True (pressed) / False (open), ...}."""
    out = {}
    for line in lines:
        m = re.match(r"\s*([xyz]_(?:min|max)|z_probe)\s*:\s*(TRIGGERED|open)", line, re.I)
        if m:
            out[m.group(1).lower()] = m.group(2).upper() == "TRIGGERED"
    return out


def _ch340_port():
    from .grbl_bridge import grbl_ports
    try:
        return next(iter(grbl_ports()), None)
    except Exception:
        return None


def _open_boot_port(port: str, baud: int):
    """Serial port for the Anet boot loader; DTR/RTS start released so that
    avr_flash's own falling edge is the one reset."""
    import serial
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout, ser.write_timeout = port, baud, 0.05, 2.0
    ser.dtr = ser.rts = False
    ser.exclusive = True
    ser.open()
    return ser


def segment_enters_corner(p, q, corner) -> bool:
    """True when the straight line p -> q passes through x < cx and y < cy."""
    lo, hi = 0.0, 1.0
    for a, b, limit in ((p[0], q[0], corner[0] - 0.0001), (p[1], q[1], corner[1] - 0.0001)):
        # a + t (b - a) < limit
        d = b - a
        if abs(d) < 1e-12:
            if a >= limit:
                return False
            continue
        t = (limit - a) / d
        if d > 0:
            hi = min(hi, t)
        else:
            lo = max(lo, t)
    return lo < hi


def motion_commands(accel: float, speed: float, z_speed: float = Z_SPEED_DEFAULT) -> list[str]:
    """Runtime limits: X/Y max acceleration and feedrate, Z max feedrate, default accelerations."""
    return ["M201 X%d Y%d" % (accel, accel), "M203 X%d Y%d Z%g" % (speed, speed, z_speed),
            "M204 P%d T%d" % (accel, accel)]


class MarlinLaserGuard:
    """Conservatively permit only the firmware's laser inline operation."""

    def __init__(self):
        self.inline = False

    def check(self, command: str, homing_verified: bool):
        cmd = normalize(command)
        if not cmd:
            return ""
        if not cmd.isascii() or len(cmd) > 96:
            raise ValueError("G-Code überschreitet das Firmware-Limit von 96 Zeichen")
        if cmd == "G20":
            raise ValueError("Z-Sicherheitsgrenze benötigt Millimeter, G20 gesperrt")
        if cmd.startswith(("$", "?", "!", "~")):
            raise ValueError("GRBL-Befehl am LumaCut-Controller nicht zulässig")
        if cmd in FILTERED:
            return ""
        # Allow only known laser motion, harmless queries and exhaust. Other
        # commands can change the machine's limits, steps or outputs, so they
        # are never forwarded from a job file or LightBurn.
        if cmd in READ_ONLY or cmd in ("M8", "M9", "M5", "M5 I",
                                         "G90", "G91", "G20", "G21"):
            if cmd.startswith("M5"):
                self.inline = False
            return cmd
        # The I selector is a *bare flag* (M3 I, M5 I).
        # Recognize that spelling without turning it into a GRBL parameter.
        parsed = re.sub(r"(?<![A-Z])I(?=\s|$)", "I1", cmd)
        if cmd.startswith("G28"):
            # G28 takes bare axis flags such as "G28 Z" / "G28 X Y".
            parsed = re.sub(r"\b([XYZ])\b", r"\g<1>1", parsed)
        words = WORD.findall(parsed)
        if not words or WORD.sub("", parsed).strip():
            raise ValueError("Nicht unterstützte G-Code-Syntax")
        families = [f"{letter}{int(float(value))}" for letter, value in words
                    if letter in ("G", "M") and float(value).is_integer()]
        allowed_families = {"G0", "G1", "G2", "G3", "G4", "G28",
                            "G90", "G91", "G20", "G21", "M3", "M5",
                            "M8", "M9", "M112", "M114",
                            "M115", "M119", "M400", "M410"}
        if any(f not in allowed_families for f in families):
            raise ValueError("G-Code nicht freigegeben")
        if len(families) > 1:
            raise ValueError("Pro Zeile nur ein G/M-Befehl erlaubt")
        if any(l not in "GMXYZIJFSP" for l, _ in words):
            raise ValueError("Unbekannter G-Code-Parameter")
        if any(m in families for m in ("M112", "M410")):
            # Emergency commands are not legal job-file instructions.
            # The dedicated emergency endpoint writes M112 immediately.
            raise ValueError("Notstopp ausschließlich über separaten M112-Kanal")
        if "M4" in families:
            raise ValueError("M4 gibt es nicht: M3 I erforderlich")
        if "M3" in families:
            # A single bare I flag is required, never M3 S which can fire
            # the laser immediately while stationary.
            if cmd != "M3 I":
                raise ValueError("Nur M3 I ohne S/O ist freigegeben")
            self.inline = True
            return cmd
        if "M5" in families:
            if any(l == "I" for l, _ in words):
                self.inline = False
            return cmd
        if "G28" in families:
            # A bare G28 homes in the firmware's own order. The Pi intercepts
            # all G28 and executes a safe, staged home sequence.
            raise ValueError("G28 nur über Pi-Zuerst-Z-Referenzfahrt erlaubt")
        if any(m in families for m in ("G0", "G1", "G2", "G3")):
            if not homing_verified:
                raise ValueError("Fahrbewegung erst nach bestätigter Mechanik-Konfiguration freigeben")
            if "G0" in families and any(l == "S" and float(v) > 0 for l, v in words):
                raise ValueError("G0 darf keine Laserleistung S>0 enthalten")
            # S is modal in the firmware: a G1 without S keeps the last power.
            if any(m in families for m in ("G1", "G2", "G3")):
                power = [float(v) for l, v in words if l == "S"]
                if power and not self.inline and max(power) > 0:
                    raise ValueError("Laserleistung ohne vorheriges M3 I verweigert")
                if any(not 0 <= x <= 255 for x in power):
                    raise ValueError("S-Wert außerhalb 0..255")
        return cmd


class MarlinTransport:
    def __init__(self, port: str, baud: int = 115200, serial_factory=None):
        self.port = port
        self.baud = baud
        self.serial_factory = serial_factory
        self.lock = threading.RLock()
        self.serial = None
        self.owner = None
        self.state = "Disconnected"
        self.identity = ""
        self.cap_z_probe = None
        self.cap_self_update = False
        # Lift the firmware allows without a Z reference (Cap:Z_UNHOMED_LIFT), and
        # what this Pi has used of it since the reference was lost.
        self.z_unhomed_lift = None
        self.blind_lift_used = 0.0
        # ok lines of M410 written ahead of the command lock. Every ok is the same
        # text, so whichever comes first is taken for the M410, the counts stay right.
        self._stray_oks = 0
        self._stray_lock = threading.Lock()
        self.firmware = {"state": "idle", "progress": 0, "message": ""}
        self.homed = False
        self.z_homed = False
        self.homing_verified = False
        self.emergency_latched = False
        self.clearance_mm = 20.0
        self.park_z_mm = PARK_Z_MM     # 0 = stay at the travel height
        self.z_speed_mm_s = Z_SPEED_DEFAULT
        self.parked_low = False        # head down at park_z_mm in the park corner
        # Thickness of the chosen material (Pi workspace), None = not chosen.
        self.material_mm = None
        # Last Z the head is known to be at (machine Z, also commanded job Z),
        # kept by the web layer in a file: it decides how far to lift before
        # homing when the firmware lost its position (emergency stop, reset).
        self.last_known_z = None
        self.position = None
        self.fault = ""
        self.lines = deque(maxlen=80)
        self.commands = 0
        self.serial_errors = 0
        self.lightburn_clients = 0
        self.laser_enabled = False
        self.fan_power = False
        self.service_power = 0
        self.service_ping = 0.0
        self.fan_cooldown_s = 180
        self.laser_supply_settle_ms = 800
        # A workpiece contact probe must explicitly establish surface_z.
        # Positive machine Z must point AWAY from the material.
        self.surface_z = None
        self.probe_tip_offset_mm = 1.5
        self.focus_gap_mm = 7.0
        self.probe_clearance_mm = 2.0
        # The head parks and homes in this corner (PARK_CORNER_MM): never
        # burn inside it. The rest of X0..travel / Y0..travel is work area.
        self.park_corner = PARK_CORNER_MM
        self.travel_xy = TRAVEL_XY_MM
        self.probe_xy_offset_mm = None
        # (accel mm/s², speed mm/s) from the tablet's motion calibration,
        # sent on every connect like M203 Z9; None = firmware values.
        self.motion_limits = None
        # Reference check by the X/Y switches: at X0/Y0 both must be pressed.
        # None until homing showed whether they are (False: switches do not
        # reach X0/Y0 on this machine, the check stays off), True = active.
        self.switch_check = None
        self.reference_lost = ""
        self.last_probe_laser_xy = None
        self.last_xy_commanded = None
        self.homing_chime_enabled = True
        self.job_chime_enabled = True
        self.absolute_mode = True
        self.focused_this_job = False
        self.fan_off_at = None
        self.lights = False
        self.light_pct = 60            # operator brightness 1..100 %
        self.light_effects = True
        # None = not switched yet since connecting; True = M355 answered.
        self.light_pwm: bool | None = None
        self.exhaust = False
        self.client = None
        self.guard = MarlinLaserGuard()
        self.last_seen = 0.0
        # Streamed lines written but not yet acknowledged (#18).
        self.inflight = deque()
        self.stream_window = STREAM_MAX_LINES
        self.stream_bytes = STREAM_MAX_BYTES
        self.stream_error = ""
        self.streamed = 0

    def _open(self):
        if self.serial_factory:
            return self.serial_factory(self.port, self.baud, timeout=0.1)
        import serial
        return serial.Serial(self.port, self.baud, timeout=0.1,
                             write_timeout=1.0, exclusive=True)

    def _close_locked(self, message=""):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass
        self.serial = None
        self.inflight.clear()
        with self._stray_lock:
            self._stray_oks = 0
        self.blind_lift_used = 0.0
        self.service_power = 0
        self.state = "Disconnected"
        self.homed = False
        self.parked_low = False
        self.light_pwm = None          # new firmware may have been flashed
        self.z_homed = False
        self.surface_z = None
        self.focused_this_job = False
        self.laser_enabled = False
        # A reconnecting SKR boots with PC6 off; force a fresh M106 and
        # supply settle time instead of trusting the stale flag.
        self.fan_power = False
        self.fan_off_at = None
        self.last_xy_commanded = None
        self.guard = MarlinLaserGuard()
        self.identity = ""
        self.cap_z_probe = None
        self.cap_self_update = False
        if message:
            self.fault = message[:200]

    def _note_firmware_line(self, line: str):
        """State the firmware changed by itself, whoever happens to read the line."""
        if line.startswith("echo:Laser off"):
            self.service_power = 0
        elif line.startswith(REFERENCE_LOST_ERRORS):
            self.homed = False
            self.z_homed = False
            self.surface_z = None
            self.last_xy_commanded = None
            self.laser_enabled = False
            self.guard.inline = False
            self.reference_lost = "Firmware meldet: " + line[6:]

    def _take_stray_ok(self, line: str) -> bool:
        if not line.lower().startswith("ok"):
            return False
        with self._stray_lock:
            if self._stray_oks <= 0:
                return False
            self._stray_oks -= 1
            return True

    def _read_line_locked(self, deadline, until_no_stray=False):
        """Next line from the firmware, without the ok lines owed to an early M410.

        until_no_stray: return "" as soon as the last of those has come.
        """
        while time.monotonic() < deadline:
            raw = self.serial.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                self.last_seen = time.monotonic()
                self.lines.append(line)
                p = POSITION_RE.search(line)
                if p:
                    self.position = [float(p.group(i)) for i in (1, 2, 3)]
                    if self.z_homed:
                        self.last_known_z = self.position[2]
                if "FIRMWARE_NAME:" in line:
                    self.identity = line
                self._note_firmware_line(line)
                if self._take_stray_ok(line):
                    if until_no_stray and not self._stray_oks:
                        return ""
                    continue
                return line
        raise TimeoutError("Keine Bestätigung der Firmware vor Fristablauf")

    def _is_fault_locked(self, line: str) -> bool:
        """Firmware error, or an endstop hit that was not on the way to zero.

        A hit emptied the firmware's queue and stopped all axes, so the Pi's
        record of the commanded XY is void afterwards. Parking runs onto the
        X0/Y0 switches: there a hit may come just before zero and is no fault.
        """
        hit = ENDSTOP_HIT.search(line)
        fault = is_marlin_error(line)
        if hit and not fault and (self.inflight or self.laser_enabled):
            # The hit also threw away every line the firmware had received: with
            # lines under way or the laser armed this cannot be a harmless parking.
            fault = True
        if hit and not fault and self.last_xy_commanded is not None:
            target = dict(zip("XY", self.last_xy_commanded))
            fault = any(target[axis] > AT_SWITCH_MM
                        for axis in ENDSTOP_AXIS.findall(hit.group(1)) if axis in target)
        if hit and fault:
            self.last_xy_commanded = None
        return fault

    def _await_stream_ack_locked(self, timeout: float):
        """Read until one streamed line is acknowledged.

        The firmware answers strictly in order, one "ok P.. B.." per received
        line. An error line
        belongs to one of the lines in flight and is followed by its ok;
        it is remembered and raised once the window is drained.
        """
        deadline = time.monotonic() + timeout
        while True:
            line = self._read_line_locked(deadline)
            if self._is_fault_locked(line):
                self.serial_errors += 1
                self.fault = _fault_text(line)
                if not self.stream_error:
                    self.stream_error = self.fault
                continue
            if line.lower().startswith("ok"):
                self.inflight.popleft()
                self.commands += 1
                return

    def _drain_locked(self, timeout: float = 150.0):
        """Wait for every streamed line; raise a remembered firmware error."""
        while self.inflight:
            self._await_stream_ack_locked(timeout)
        if self.stream_error:
            message, self.stream_error = self.stream_error, ""
            self.state = "Idle"
            raise MarlinCommandError(message)

    def _exchange_locked(self, cmd: str, timeout: float = 15.0):
        if self.serial is None:
            raise ConnectionError("SKR USB nicht verbunden")
        if cmd.startswith("M5"):
            self.service_power = 0
        self._unpark_before_locked(cmd)
        if self.inflight or self.stream_error:
            # Any normal exchange (M114, M5, G30, ...) must not read the
            # ok of a streamed line as its own answer.
            self._drain_locked(max(timeout, 150.0))
        self.state = "Busy"
        responses = []
        self.serial.write((cmd + "\n").encode("ascii"))
        deadline = time.monotonic() + timeout
        while True:
            line = self._read_line_locked(deadline)
            responses.append(line)
            lower = line.lower()
            if self._is_fault_locked(line):
                self.serial_errors += 1
                self.fault = _fault_text(line)
                # An error is followed by a normal "ok".
                # Consume that trailing ACK before the next command;
                # otherwise M114/G30 will read a stale ACK as its own.
                ack_deadline = min(deadline, time.monotonic() + 4.0)
                try:
                    while True:
                        trailing = self._read_line_locked(ack_deadline)
                        responses.append(trailing)
                        if trailing.lower().startswith("ok"):
                            self.state = "Idle"
                            error = MarlinCommandError(self.fault)
                            error.responses = responses
                            raise error
                except TimeoutError as exc:
                    raise ConnectionError(
                        self.fault + " (SKR hat kein abschliessendes ok geliefert)"
                    ) from exc
            if lower.startswith("ok"):
                self.commands += 1
                self.state = "Idle"
                return responses

    def ensure_ready(self, owner=None):
        with self.lock:
            if self.emergency_latched:
                raise RuntimeError("M112-Notstopp verriegelt – erst Notstopp quittieren")
            if self.serial is not None and self.identity:
                return
            if self.owner not in (None, owner):
                raise RuntimeError("SKR noch nicht bereit, während Client verbunden ist")
            self._connect_locked()

    def _connect_locked(self, quit_emergency: bool = False):
        """Open the port, prove the firmware by M115, set the Pi's runtime values.

        The firmware keeps nothing across a reset: speeds, steps and limits
        are sent on every connection (the Pi is the central store).
        ``quit_emergency`` sends M999; otherwise a firmware that is still
        latched (Pi service restarted after an M112) latches the Pi too.
        """
        self._close_locked()
        try:
            self.serial = self._open()
            # The Grbl bridge buffers by itself and asks for a deeper window
            # (short arc segments would starve Grbl's planner otherwise).
            self.stream_window = getattr(self.serial, "stream_window", STREAM_MAX_LINES)
            self.stream_bytes = getattr(self.serial, "stream_bytes", STREAM_MAX_BYTES)
            # STM32 USB may reset at open. Allow boot banner to settle.
            time.sleep(1.0)
            self.serial.reset_input_buffer()
            reply = self._exchange_locked("M115", timeout=8.0)
            if ("FIRMWARE_NAME:LumaCut CNC" not in self.identity
                    or "MACHINE_TYPE:LumaCut CNC" not in self.identity):
                raise RuntimeError("Fremde oder alte Firmware: LumaCut-CNC-Kennung im M115 fehlt")
            caps = [line.strip() for line in reply]
            self.cap_z_probe = "Cap:Z_PROBE:1" in caps if any(
                c.startswith("Cap:Z_PROBE:") for c in caps) else None
            self.cap_self_update = "Cap:SELF_UPDATE:1" in caps
            lift_caps = [c.split(":")[2] for c in caps if c.startswith("Cap:Z_UNHOMED_LIFT:")]
            self.z_unhomed_lift = float(lift_caps[0]) if lift_caps else None
            if quit_emergency:
                self._exchange_locked("M999", timeout=6.0)
            try:
                self._exchange_locked("M5 I", timeout=6.0)
            except MarlinCommandError as exc:
                if "emergency stop" in str(exc).lower():
                    self.emergency_latched = True
                raise
            self._exchange_locked("M92 Z%g" % Z_STEPS_PER_MM, timeout=6.0)
            # X/Y acceleration and speed from the calibration, Z speed.
            self._apply_motion_locked()
            self.state = "Idle"
            self.fault = ""
        except Exception as exc:
            self._close_locked(str(exc))
            raise

    def set_workpiece_surface(self, contact_confirmed: bool, owner: str = "web"):
        """Declare measured Z position at physical switch contact.

        Only call while switch physically touches the current workpiece;
        NOT after retracting, nor from a normal machine home.
        """
        with self.lock:
            if self.owner not in (None, owner) or not self.homed:
                raise RuntimeError("Z-Referenz nur nach XYZ-Homing und ohne Fremdsteuerung")
            if not contact_confirmed:
                raise ValueError("Kontakt zur Werkstückoberfläche nicht bestätigt")
            # Query actual position; no silent inferred zero.
            self._exchange_locked("M400", timeout=20)
            self._exchange_locked("M114", timeout=10)
            if self.position is None:
                raise RuntimeError("M114 meldet keine gültige Z-Position")
            self.surface_z = self.position[2]
            self.focused_this_job = False
            return self.surface_z

    def _z_move_guard_locked(self, cmd: str):
        """Prevent tool probe from approaching closer than 2mm to material."""
        if not re.match(r"^G0?[01](?:\s|$)", cmd):
            return
        coords = {name:float(value) for name,value in WORD.findall(cmd)}
        if "Z" not in coords:
            return
        if self.surface_z is None:
            raise ValueError("Z-Fahrten nur mit vermessener Werkstückoberfläche erlaubt")
        if self.absolute_mode:
            # The target is known without asking the firmware. Draining the
            # planner here would stop the head on every focus-compensated
            # segment (a Z word on each 2 mm piece) and burn dots.
            target = coords["Z"]
        else:
            self._exchange_locked("M400", timeout=20)
            self._exchange_locked("M114", timeout=10)
            if self.position is None:
                raise RuntimeError("Keine gültige aktuelle Z-Position")
            target = self.position[2] + coords["Z"]
        minimum = max(0.0, self.surface_z + self.probe_clearance_mm)
        if target < minimum - 0.0001:
            raise ValueError(
                f"Z-Sperre: Ziel {target:.3f} mm, Minimum {minimum:.3f} mm "
                "(2mm Tastabstand). Schneidtiefe begrenzen.")
        if target > Z_MAX_MM + 0.0001:
            raise ValueError(
                f"Z-Sperre: Ziel {target:.3f} mm über der Höchstgrenze Z{Z_MAX_MM:g} "
                "(darüber läuft der Kopf aus der Linearschiene).")
        if self.z_homed:
            self.last_known_z = target

    def _xy_cut_guard_locked(self, cmd: str):
        """Reject any armed linear cut touching the 30mm X/Y home bands.

        The previous tool position matters as much as the commanded target:
        an XY line from the home corner to the work area is not a cut.
        G0 with laser safely extinguished is permitted in home bands.

        The start point is the Pi's own record of the last commanded XY,
        not an M400/M114 query: M400 waits for an empty queue, so querying
        before every segment stopped the head at each vector node and burnt
        dots/uneven lines into the material. Every XY move reaches the
        firmware through this gateway, so the commanded record is exact.
        """
        if not re.match(r"^G0?[123](?:\s|$)", cmd) or not self.laser_enabled:
            return
        coords = {letter:float(value) for letter,value in WORD.findall(cmd)}
        if "S" in coords and coords["S"] <= 0:
            return
        # An inline G1 lacking S may preserve nonzero cutting power.
        if self.last_xy_commanded is None:
            self._exchange_locked("M400", timeout=20)
            self._exchange_locked("M114", timeout=10)
            if self.position is None:
                raise RuntimeError("XY-Sicherheitszone: Position nicht bestimmbar")
            self.last_xy_commanded = (self.position[0], self.position[1])
        px, py = self.last_xy_commanded
        tx, ty = self._xy_target(coords, px, py)
        if "I" in coords or "J" in coords:
            # Arc: the whole circle's box is a conservative envelope.
            cx, cy = px + coords.get("I", 0.0), py + coords.get("J", 0.0)
            radius = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            hits = self.in_park_corner(min(px, tx, cx - radius), min(py, ty, cy - radius))
        else:
            hits = segment_enters_corner((px, py), (tx, ty), self.park_corner)
        if hits:
            ex, ey = self.park_corner
            raise ValueError(
                f"Park-Ecke X0..{ex:g} / Y0..{ey:g} mm: dort wird nicht gelasert; "
                f"Start X{px:.2f} Y{py:.2f}, Ziel X{tx:.2f} Y{ty:.2f}")

    def _unpark_before_locked(self, cmd: str):
        """Every path to the firmware passes here: the head sitting low in the park
        corner rises to the travel height before any X/Y move, so it never
        drags over the bed. Any Z move ends the parked state."""
        if not self.parked_low or not _XY_MOTION.match(cmd):
            return
        coords = {k for k, _ in WORD.findall(cmd)}
        self.parked_low = False
        if "Z" in coords or not coords & {"X", "Y"}:
            return
        lift = [f"G0 Z{self.travel_z:.3f} F{self.z_feed}", "M400"]
        if not self.absolute_mode:
            lift = ["G90"] + lift + ["G91"]
        for line in lift:
            self._exchange_locked(line, timeout=45)

    def _lower_to_park_locked(self):
        """At X0/Y0 after homing or parking: down to park_z_mm over the bed
        (Z0 is where the switch met the bed right there). Never elsewhere."""
        if not self.park_z_mm or not self.z_homed or self.last_xy_commanded != (0.0, 0.0):
            return False
        if not self.absolute_mode:
            self._exchange_locked("G90", timeout=8)
            self.absolute_mode = True
        self._exchange_locked(f"G0 Z{self.park_z_mm:.3f} F{self.z_feed}", timeout=45)
        self._exchange_locked("M400", timeout=45)
        self.parked_low = True
        return True

    def in_park_corner(self, x: float, y: float) -> bool:
        """True when point X/Y (or a box starting there) lies in the park corner."""
        ex, ey = self.park_corner
        return x < ex - 0.0001 and y < ey - 0.0001

    def _xy_target(self, coords, px, py):
        tx = (coords["X"] if self.absolute_mode else px + coords["X"]) if "X" in coords else px
        ty = (coords["Y"] if self.absolute_mode else py + coords["Y"]) if "Y" in coords else py
        return tx, ty

    def _focus_before_cut_locked(self):
        if self.focused_this_job:
            return
        if self.surface_z is None:
            raise RuntimeError("Fokus nicht möglich: Werkstückoberfläche nicht abgetastet")
        goal = self.surface_z + self.focus_gap_mm - self.probe_tip_offset_mm
        minimum = self.surface_z + self.probe_clearance_mm
        if goal < minimum:
            raise ValueError("Fokus würde 2mm Taster-Sicherheitsgrenze unterschreiten")
        # Focus must precede the first laser-powered move, after LightBurn's
        # XY positioning rapid. Restrict this to absolute machine Z.
        self._exchange_locked("M400", timeout=20)
        if not self.absolute_mode:
            raise ValueError("Automatischer Fokus benötigt absolute Z-Koordinaten (G90)")
        self._exchange_locked("G90", timeout=8)
        self.absolute_mode = True
        self._exchange_locked(f"G0 Z{goal:.3f} F{self.z_feed}", timeout=20)
        self._exchange_locked("M400", timeout=30)
        self._exchange_locked("M114", timeout=8)
        self.focused_this_job = True

    def command(self, cmd: str, owner: str = "web",
                timeout: float = 20.0, use_guard=True, after_queue=False):
        """One acknowledged command. ``after_queue``: an M5 from a job or from
        LightBurn waits for the moves before it (the firmware's M5 acts at
        once, the rest of the queue would run unlit)."""
        with self.lock:
            normalized, passthrough = self._prepare_locked(cmd, owner, use_guard)
            if not normalized:
                return []
            if passthrough:
                return self._exchange_locked(normalized, timeout)
            return self._send_locked(normalized, timeout, after_queue=after_queue)

    def stream_command(self, cmd: str, owner: str = "job", timeout: float = 150.0):
        """Send a job line, keeping plain moves in a small ok-counted window.

        Same normalization and guards as command(). Only absolute G0/G1
        lines whose guards need no extra exchange (known start XY, focus
        done, no relative mode) are streamed; everything else first drains
        the window and then runs exactly like command(). A firmware error on
        any streamed line stops further sending and raises after the window
        is drained. An M5 in the job waits for the moves before it.
        """
        with self.lock:
            normalized, passthrough = self._prepare_locked(cmd, owner, True)
            if not normalized:
                return []
            if passthrough:
                return self._exchange_locked(normalized, timeout)
            if not self._streamable_locked(normalized):
                return self._send_locked(normalized, timeout, after_queue=True)
            return self._send_locked(normalized, timeout, stream=True)

    def drain(self, owner: str = "job", timeout: float = 150.0):
        """Wait until every streamed line is acknowledged by the firmware."""
        with self.lock:
            if self.serial is None:
                self.inflight.clear()
                return
            try:
                self._drain_locked(timeout)
            except MarlinCommandError:
                raise
            except Exception as exc:
                self.serial_errors += 1
                self._close_locked(str(exc))
                raise

    def _streamable_locked(self, normalized: str) -> bool:
        if self.stream_window <= 1 or not STREAMABLE.match(normalized):
            return False
        if not self.absolute_mode:
            return False
        words = WORD.findall(normalized)
        powered = any(k == "S" and float(v) > 0 for k, v in words)
        if (normalized.startswith(("G1", "G01")) and powered
                and self.laser_enabled and not self.focused_this_job):
            return False  # focus first (M400 + Z move)
        if self.laser_enabled and self.last_xy_commanded is None:
            return False  # cut guard would ask M114 for the start point
        return True

    def _stream_write_locked(self, normalized: str, timeout: float):
        self._unpark_before_locked(normalized)
        if self.stream_error:
            self._drain_locked(timeout)
        size = len(normalized) + 1
        while self.inflight and (len(self.inflight) >= self.stream_window
                                 or sum(self.inflight) + size > self.stream_bytes):
            self._await_stream_ack_locked(timeout)
        if self.stream_error:
            self._drain_locked(timeout)
        self.state = "Busy"
        self.serial.write((normalized + "\n").encode("ascii"))
        self.inflight.append(size)
        self.streamed += 1
        return []

    def _prepare_locked(self, cmd: str, owner: str, use_guard=True):
        """Owner/state checks, LightBurn rewrites and the laser guard.

        Returns (normalized, passthrough): passthrough lines (empty or a
        bare LightBurn G0/G1 mode switch) skip the motion guards.
        """
        if self.owner not in (None, owner):
            raise RuntimeError("Steuerung belegt: " + self.owner)
        if self.serial is None or not self.identity:
            raise ConnectionError("SKR USB nicht bereit")
        if self.emergency_latched:
            raise RuntimeError("M112-Notstopp aktiv; keine weiteren Bewegungen")
        # G01 and M05 are the same commands; the firmware's table has G1 and M5.
        normalized = re.sub(r"^([GM])0+(?=\d)", r"\1", normalize(cmd))
        # A bare G0/G1 from LightBurn changes only the modal motion
        # type; there is no destination and thus no motion to authorize.
        # In particular this must not erase a confirmed homing state.
        if normalized in ("G0", "G00", "G1", "G01"):
            if owner == "lightburn":
                return normalized, True
        # LightBurn's Move arrows may issue a G1 X/Y ... S... jog,
        # even though no M3 I laser mode has been enabled. A Move
        # command must NEVER activate the laser: convert XY-only jogging
        # to a rapid without any S word, while laser mode is off.
        if (owner == "lightburn" and not self.laser_enabled
                and re.match(r"^G0?1(?:\s|$)", normalized)
                and re.search(r"\b[XY]\s*[-+]?\d", normalized)
                and not re.search(r"\bZ\s*[-+]?\d", normalized)
                and any(k == "S" for k, _ in WORD.findall(normalized))):
            normalized = re.sub(r"^G0?1", "G0", normalized)
            normalized = re.sub(r"\s*S\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)", "", normalized)
        # LightBurn often emits G0 X... Y... without an F word. The modal G0
        # feed might still be the slow Z feed of the Pi's last lift;
        # give XY-only rapids their own travel speed every time.
        if (re.match(r"^G0?0(?:\s|$)", normalized)
                and re.search(r"\b[XY]\s*[-+]?\d", normalized)
                and not re.search(r"\bZ\s*[-+]?\d", normalized)
                and not re.search(r"\bF\s*[-+]?\d", normalized)):
            normalized += " F9000"
        if use_guard:
            normalized = self.guard.check(normalized, self.homing_verified)
        if not normalized:
            return "", True
        # G0 has no S in the firmware's table and always runs at power 0. The
        # guard has refused S>0 already; an S0 must not end up as modal power.
        if re.match(r"^G0(?:\s|$)", normalized):
            normalized = re.sub(r"\s*S\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)", "", normalized)
        if normalized.startswith(("G0 ", "G1 ")) and "Z" in normalized and self.surface_z is None:
            raise RuntimeError("Keine Werkstückhöhe bekannt; keine Z-Fahrt über LightBurn freigeben")
        # The frame's glimmer (web.py, at most 1 %) needs no focus height.
        if normalized == "M3 I" and self.surface_z is None and owner != "frame":
            raise RuntimeError("Werkstückkontakt fehlt: Z-Taster auf Material referenzieren")
        motion = re.match(r"^G0?[0123](?:\s|$)", normalized) is not None
        if (motion or normalized == "M3 I") and not self.homed:
            raise RuntimeError("Maschine nicht referenziert: in LightBurn zuerst Home (G28) ausfuehren; danach G30 fuer Werkstueckfokus")
        return normalized, False

    def _send_locked(self, normalized: str, timeout: float, stream: bool = False,
                     after_queue: bool = False):
        """Guards needing the machine state, the exchange and bookkeeping."""
        try:
            self._z_move_guard_locked(normalized)
            self._xy_cut_guard_locked(normalized)
            if normalized == "M3 I":
                # Independently power cooling fan before laser PWM mode.
                # PC6 is FAN0/M106, not laser-enable.
                if not self.fan_power:
                    self._exchange_locked("M106 P0 S255", timeout=8)
                    # PC6 also switches the laser module's 24 V rail.
                    # A diode module needs a moment after power-up;
                    # otherwise the first line of a job burns weak.
                    self._exchange_locked(
                        f"G4 P{int(self.laser_supply_settle_ms)}", timeout=10)
                self.fan_power = True
                self.fan_off_at = None
            # Focus on first powered G1, not while traversing XY.
            if (re.match(r"^G0?1(?:\s|$)",normalized) and
                any(k == "S" and float(v) > 0 for k,v in WORD.findall(normalized)) and
                self.laser_enabled and not self.focused_this_job):
                self._focus_before_cut_locked()
            if after_queue and normalized.startswith("M5"):
                self._exchange_locked("M400", timeout=max(timeout, 150.0))
            if stream:
                reply = self._stream_write_locked(normalized, timeout)
            else:
                reply = self._exchange_locked(normalized, timeout)
            # Remember the target sent. Relative moves are tracked too: the cut guard uses this
            # record as the start point of the next segment.
            if re.match(r"^G0?[0123](?:\s|$)", normalized):
                coords = {k: float(v) for k, v in WORD.findall(normalized)}
                if "X" in coords or "Y" in coords:
                    if self.absolute_mode and "X" in coords and "Y" in coords:
                        self.last_xy_commanded = (coords["X"], coords["Y"])
                    elif self.last_xy_commanded is not None:
                        self.last_xy_commanded = self._xy_target(
                            coords, *self.last_xy_commanded)
            if normalized == "G90":
                self.absolute_mode = True
            elif normalized == "G91":
                self.absolute_mode = False
            if normalized.startswith("M3 I"):
                self.laser_enabled = True  # PWM stays at zero until G1 S
            if normalized.startswith("M5"):
                self.laser_enabled = False
                if self.fan_power:
                    self.fan_off_at = time.monotonic() + self.fan_cooldown_s
            if normalized == "M8":
                self.exhaust = True
            if normalized == "M9":
                self.exhaust = False
            return reply
        except (ValueError, MarlinCommandError) as exc:
            # Rejected G-code is not the same as a disconnected USB cable.
            # The laser state is handled by the LightBurn session on errors.
            self.fault = str(exc)[:200]
            self.state = "Idle"
            raise
        except Exception as exc:
            self.serial_errors += 1
            self._close_locked(str(exc))
            raise

    def service_cooldown(self):
        """Release PC6 only after cooldown and confirmed safe laser-off.

        This is a Pi-mediated timer, not an independent hardware timer.
        """
        with self.lock:
            if (self.owner not in (None, "lightburn") or self.serial is None or
                not self.identity or self.emergency_latched or
                not self.fan_power or self.fan_off_at is None or
                time.monotonic() < self.fan_off_at or self.laser_enabled):
                return False
            self._exchange_locked("M5 I", timeout=8)
            self._exchange_locked("M400", timeout=15)
            self._exchange_locked("M107 P0", timeout=8)
            self.fan_power = False
            self.fan_off_at = None
            return True

    def _play_stepper_chime_locked(self, event: str) -> bool:
        """Melody on the X/Y stepper coils with M300, the head does not move.

        Each tone alternates one microstep forward and back, so the motors
        sing with zero net travel; coordinates and homing stay valid. The
        firmware refuses it while the laser is on or an axis moves: then the
        melody just stays silent.
        """
        notes = MELODIES.get(event)
        if notes is None or self.serial is None or self.laser_enabled:
            return False
        try:
            for hz, ms in notes:
                self._exchange_locked(f"M300 S{hz} P{ms}", timeout=ms / 1000.0 + 10)
            return True
        except Exception as exc:
            LOG.warning("Motor melody '%s' unavailable: %s", event, exc)
            return False

    def play_melody(self, event: str, owner: str = "job") -> bool:
        """Job start/end light effect and melody; never blocks a job on failure."""
        with self.lock:
            if self.owner not in (None, owner):
                return False
            self._light_effect_locked(event)
            if not self.job_chime_enabled:
                return False
            return self._play_stepper_chime_locked(event)

    # ---------- dimmable light (PC8) ----------

    def _light_raw_locked(self, pct: float):
        """Sets PC8 to ``pct``."""
        self._exchange_locked(
            "M355 S%d P%d" % (1 if pct > 0 else 0, round(max(0.0, min(100.0, pct)) * 2.55)), timeout=8)
        self.light_pwm = True

    def _apply_light_locked(self):
        self._light_raw_locked(self.light_pct if self.lights else 0)

    def set_light(self, on: bool, pct: float | None = None, owner: str = "web"):
        """Light on/off and brightness 1..100 %; returns (on, pct, dimmable)."""
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None:
                raise ConnectionError("SKR USB nicht verbunden")
            if pct is not None:
                if not 1 <= pct <= 100:
                    raise ValueError("Helligkeit 1..100 %")
                self.light_pct = int(round(pct))   # whole percent: clients read an integer
            self.lights = bool(on)
            self._apply_light_locked()
            return self.lights, self.light_pct, self.light_pwm

    def _light_effect_locked(self, event: str) -> bool:
        """Plays LIGHT_EFFECTS[event], then restores the operator's light."""
        steps = LIGHT_EFFECTS.get(event)
        if steps is None or not self.light_effects or self.serial is None or self.emergency_latched:
            return False
        before = self.state
        try:
            for pct, ms in steps:
                self._light_raw_locked(pct)
                time.sleep(ms / 1000.0)
            self._apply_light_locked()
            return True
        except Exception as exc:
            # A light effect must never leave the machine looking busy.
            LOG.warning("Light effect '%s' unavailable: %s", event, exc)
            if self.serial is not None:
                self.state = before
            return False

    def light_effect(self, event: str, owner: str = "job") -> bool:
        with self.lock:
            if self.owner not in (None, owner):
                return False
            return self._light_effect_locked(event)

    @property
    def travel_z(self) -> float:
        """Height for every move over unknown ground: material + 20 mm, at
        least the clearance, never above Z_MAX_MM."""
        h = self.clearance_mm if self.material_mm is None else max(self.clearance_mm, self.material_mm + TRAVEL_GAP_MM)
        return min(h, Z_MAX_MM)

    def _lift_before_home_locked(self, operator_clear: bool) -> list:
        """Commands that bring the head up before X/Y homing crosses the bed.

        Z known (homed): absolute to the travel height. Z unknown (emergency
        stop, SKR reset): relative by travel height minus the last known Z,
        at least 5 mm, never above the rail (Z_MAX_MM). Without a last known
        Z only the operator can say the head stands clear (operator_clear).
        """
        if self.z_homed and self.position is not None:
            if self.position[2] < self.travel_z - 0.01:
                return [f"G0 Z{self.travel_z:.2f} F{self.z_feed}"]
            return []
        if self.last_known_z is not None:
            last = self.last_known_z
            lift = min(max(self.travel_z - last, MIN_BLIND_LIFT_MM), Z_MAX_MM - last)
            if self.z_unhomed_lift is not None:
                # The firmware refuses more than its budget without a Z reference.
                lift = min(lift, self.z_unhomed_lift - self.blind_lift_used)
            if lift <= 0.05:
                return []
            self.blind_lift_used += lift
            return ["G91", f"G0 Z{lift:.2f} F{self.z_feed}", "G90"]
        if operator_clear:
            return []
        raise RuntimeError("Kopfhöhe unbekannt: Steht der Kopf frei über allem auf dem Bett? "
                           "Dann das Referenzieren bestätigen.")

    @property
    def z_feed(self) -> int:
        """Feed (mm/min) of Z travel moves: the old F600 up to 10 mm/s, else the Z limit."""
        return max(600, int(round(self.z_speed_mm_s * 60)))

    def set_z_speed(self, speed: float, owner: str = "web"):
        """Stores the Z max feedrate and sends it (M203 Z) when connected."""
        if not isinstance(speed, (int, float)) or not 2 <= speed <= Z_SPEED_MAX:
            raise ValueError("Z-Tempo: 2..%g mm/s" % Z_SPEED_MAX)
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            self.z_speed_mm_s = float(speed)
            if self.serial is not None and self.identity and not self.emergency_latched:
                self._exchange_locked("M400", timeout=60)
                self._exchange_locked("M203 Z%g" % self.z_speed_mm_s, timeout=6.0)

    def z_test(self, distance: float, owner: str = "web", speed: float | None = None):
        """Z only, relative and slow, also without homing (owner 01.11.).

        For checking the Z direction after a drive change: homing itself
        runs Z into the switch and would drive the wrong way at full force.
        At most Z_TEST_MAX_MM, laser off, X/Y untouched; the machine stays
        unhomed afterwards (the firmware's Z is no longer the real height).
        Unhomed the firmware's Z says nothing, but its travel limits still
        apply: G92 puts the test in the middle of the range and Z0 afterwards,
        so the later blind lift before homing stays inside it too.
        """
        if not isinstance(distance, (int, float)) or not 0 < abs(distance) <= Z_TEST_MAX_MM:
            raise ValueError("Z-Test: höchstens ±%g mm" % Z_TEST_MAX_MM)
        if speed is not None and not 2 <= speed <= Z_SPEED_MAX:
            raise ValueError("Z-Test: Tempo 2..%g mm/s" % Z_SPEED_MAX)
        # A speed test lifts the M203 cap for this one move, then restores it.
        feed = int(round(speed * 60)) if speed else Z_TEST_FEED_MM_MIN
        wait = abs(distance) * 60.0 / feed + 15
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise ConnectionError("SKR USB nicht bereit oder Notstopp verriegelt")
            known = self.z_homed
            self.homed = False
            self.z_homed = False
            self.surface_z = None
            self.parked_low = False
            self._exchange_locked("M5 I", timeout=6.0)
            if not known:
                self._exchange_locked("G92 Z%g" % (Z_MAX_MM / 2), timeout=wait)
            self._exchange_locked("G91", timeout=6.0)
            try:
                if speed and speed > self.z_speed_mm_s:
                    self._exchange_locked("M203 Z%g" % speed, timeout=6.0)
                self._exchange_locked("G0 Z%+.3f F%d" % (distance, feed), timeout=wait)
                if not known:
                    self.blind_lift_used += distance
                self._exchange_locked("M400", timeout=wait)
            finally:
                self._exchange_locked("G90", timeout=6.0)
                if speed and speed > self.z_speed_mm_s:
                    self._exchange_locked("M203 Z%g" % self.z_speed_mm_s, timeout=6.0)
            result = self._exchange_locked("M114", timeout=6.0)
            self._exchange_locked("G92 Z0", timeout=wait)
            return result

    def axis_test(self, axis: str, distance: float, owner: str = "web"):
        """X or Y only, relative and slow, also without homing.

        Direction and travel check before the first homing: a wrong direction
        there runs the axis away from its switch into the far end. At most
        Z_TEST_MAX_MM, laser off; the machine stays unhomed afterwards.
        """
        if axis not in AXIS_TEST_CENTER:
            raise ValueError("Achsen-Test: nur X oder Y")
        if not isinstance(distance, (int, float)) or not 0 < abs(distance) <= Z_TEST_MAX_MM:
            raise ValueError("Achsen-Test: höchstens ±%g mm" % Z_TEST_MAX_MM)
        wait = abs(distance) * 60.0 / AXIS_TEST_FEED_MM_MIN + 15
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise ConnectionError("SKR USB nicht bereit oder Notstopp verriegelt")
            self.homed = False
            self.parked_low = False
            self.last_xy_commanded = None
            self._exchange_locked("M5 I", timeout=6.0)
            # The firmware's limits still apply: the test runs in the middle of the range.
            self._exchange_locked("G92 %s%g" % (axis, AXIS_TEST_CENTER[axis]), timeout=wait)
            self._exchange_locked("G91", timeout=6.0)
            try:
                self._exchange_locked("G0 %s%+.3f F%d" % (axis, distance, AXIS_TEST_FEED_MM_MIN), timeout=wait)
                self._exchange_locked("M400", timeout=wait)
            finally:
                self._exchange_locked("G90", timeout=6.0)
            return self._exchange_locked("M114", timeout=6.0)

    def supply_test(self, seconds: float, owner: str = "web"):
        """Laser 24 V rail (relay on FAN0) on for a few seconds, beam off.

        For measuring the supply voltage (owner 01.11.: laser fan spun up
        briefly at job start, then nothing). M5 I keeps the PWM low; no
        motion, no homing needed. The lock is released while waiting so the
        heartbeat keeps running.
        """
        if not isinstance(seconds, (int, float)) or not 1 <= seconds <= SUPPLY_TEST_MAX_S:
            raise ValueError("Versorgungstest: 1..%g s" % SUPPLY_TEST_MAX_S)
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise ConnectionError("SKR USB nicht bereit oder Notstopp verriegelt")
            self._exchange_locked("M5 I", timeout=6.0)
            self._exchange_locked("M400", timeout=15)
            self._exchange_locked("M106 P0 S255", timeout=8)
            self.fan_power = True
            self.fan_off_at = None
        try:
            time.sleep(seconds)
        finally:
            with self.lock:
                if self.serial is not None and not self.emergency_latched:
                    self._exchange_locked("M5 I", timeout=6.0)
                    self._exchange_locked("M107 P0", timeout=8)
                self.fan_power = False
                self.fan_off_at = None

    def set_laser_supply(self, on: bool, owner: str = "web"):
        """Service menu: laser 24 V rail (relay on FAN0) on or off, beam off.

        Stays as set, no timer: switching either way also ends a service beam.
        """
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise ConnectionError("SKR USB nicht bereit oder Notstopp verriegelt")
            self._exchange_locked("M5 I", timeout=6.0)
            self._exchange_locked("M400", timeout=15)
            if on:
                self._exchange_locked("M106 P0 S255", timeout=8)
                self.fan_power = True
                self.fan_off_at = None
            else:
                self._exchange_locked("M107 P0", timeout=8)
                self.fan_power = False
                self.fan_off_at = None

    def service_laser(self, percent: float, owner: str = "web"):
        """Service menu slider: stationary beam 0..100 %, no time limit.

        The page confirms with service_laser_ping() while the beam is on; when
        it stops, service_laser_watchdog() switches the beam off. The rail stays as set.
        """
        if not isinstance(percent, (int, float)) or not 0 <= percent <= 100:
            raise ValueError("Laser: Leistung 0..100 %")
        power = int(round(percent * 2.55))
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise ConnectionError("SKR USB nicht bereit oder Notstopp verriegelt")
            self.service_ping = time.monotonic()
            if power == self.service_power:
                return power
            if power == 0:
                self._exchange_locked("M5", timeout=6.0)
                return 0
            if not self.service_power:
                self._exchange_locked("M5 I", timeout=6.0)
                self._exchange_locked("M400", timeout=15)
            self._exchange_locked("M3 S%d" % power, timeout=6.0)
            self.service_power = power
        return power

    def service_laser_ping(self):
        """The service page is still open. Never changes the power: an old
        tab or a late request must not bring a switched-off beam back."""
        self.service_ping = time.monotonic()
        return self.service_power

    def service_laser_watchdog(self):
        """Beam off when the service page is gone (closed, hidden, network)."""
        with self.lock:
            if (not self.service_power or
                    time.monotonic() - self.service_ping < SERVICE_LASER_PING_S):
                return False
            self._exchange_locked("M5", timeout=6.0)
            return True

    def ttl_test(self, seconds: float, owner: str = "web"):
        """Laser PWM pin at full duty with the laser rail OFF (owner 01.11.).

        For measuring the TTL pin (PA9) with a meter: the relay is switched
        off first and stays off, so the module has no supply. 0 V at S255 means
        pin, firmware or wiring fault. M114 every second: the firmware ends a
        stationary beam after 5 s without a command (Sicherheit 6).
        """
        if not isinstance(seconds, (int, float)) or not 1 <= seconds <= TTL_TEST_MAX_S:
            raise ValueError("TTL-Test: 1..%g s" % TTL_TEST_MAX_S)
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise ConnectionError("SKR USB nicht bereit oder Notstopp verriegelt")
            self._exchange_locked("M5 I", timeout=6.0)
            self._exchange_locked("M400", timeout=15)
            self._exchange_locked("M107 P0", timeout=8)
            self.fan_power = False
            self.fan_off_at = None
            try:
                self._exchange_locked("M3 S255", timeout=6.0)
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    time.sleep(min(1.0, max(0.0, end - time.monotonic())))
                    self._exchange_locked("M114", timeout=6.0)
            finally:
                self._exchange_locked("M5", timeout=6.0)

    def safe_home(self, owner: str = "web", clearance_mm: float | None = None,
                  probe_contact_confirmed: bool = False, should_stop=None, operator_clear: bool = False):
        """LightBurn G28: home XY first into EMPTY L-shaped 30mm bed zone.

        This explicitly relies on the operator keeping the X0/Y0 strips clear
        of any material, and the physical head/probe travel being collision-free.
        Unlike the old routine, it never attempts Z before XY are referenced.
        ``should_stop`` is checked after the X/Y homing: an abort then leaves
        the head in the X0/Y0 park corner, laser off, Z untouched and the
        machine unhomed (Aborted). A running G28 itself is never cut short.
        """
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if not self.homing_verified:
                raise PermissionError("Mechanik/Z-Endschalter nicht verifiziert")
            if self.serial is None or not self.identity or self.emergency_latched:
                raise ConnectionError("SKR USB nicht bereit oder Notstopp verriegelt")
            clearance = self.clearance_mm if clearance_mm is None else clearance_mm
            if probe_contact_confirmed:
                raise ValueError("G28 referenziert ausschließlich den Maschinenboden; Werkstückkontakt separat mit G30")
            if not isinstance(clearance, (int, float)) or not 0.5 <= clearance <= 50:
                raise ValueError("Unzulässiger Z-Sicherheitsabstand")
            previous_owner = self.owner
            self.owner = owner
            self.homed = False
            self.z_homed = False
            self.surface_z = None
            self.last_probe_laser_xy = None
            self.last_xy_commanded = None
            self.focused_this_job = False
            # Up to the travel height before X/Y cross the bed.
            lift = self._lift_before_home_locked(operator_clear)
            final = min(Z_MAX_MM, max(clearance, self.travel_z))
            if self.park_z_mm:
                final = self.park_z_mm     # stays low in the park corner (_lower_to_park_locked)
            commands = ["M5 I"] + lift + ["G28 X Y R0", "M400",
                        "G28 Z", "M400", "G91",
                        f"G0 Z{final:.2f} F{self.z_feed}", "G90", "M400", "M114"]
            result = []
            try:
                for cmd in commands:
                    # an abort after X/Y homing: stop before Z leaves the park corner
                    if cmd == "G28 Z" and should_stop is not None and should_stop():
                        self.last_xy_commanded = (0.0, 0.0)
                        raise Aborted()
                    try:
                        result = self._exchange_locked(cmd, timeout=150 if "G28" in cmd else 35)
                    except MarlinCommandError as exc:
                        # Budget used up (earlier lifts this Pi cannot know of, after a
                        # service restart): the head has already risen, homing may go on.
                        if cmd not in lift or "Out of bounds" not in str(exc):
                            raise
                        self.fault = ""
                        LOG.warning("Blinder Hub abgelehnt: %s", exc)
                        continue
                    if cmd == "G28 Z":
                        self.z_homed = True
                        self.blind_lift_used = 0.0
                        # G28 Z is a BED / MACHINE origin, NEVER workpiece Z.
                        self.surface_z = None
                self.homed = True
                self.absolute_mode = True
                self.last_xy_commanded = (0.0, 0.0)
                self.reference_lost = ""
                self._lower_to_park_locked()
                # Do the switches reach X0/Y0? Only then can they check the reference later.
                stops = parse_endstops(self._exchange_locked("M119", timeout=8))
                self.switch_check = bool(stops.get("x_min") and stops.get("y_min"))
                if not self.switch_check:
                    LOG.warning("X/Y switches not pressed after homing (%s): reference check off", stops)
                self.guard = MarlinLaserGuard()
                self.laser_enabled = False
                self._light_effect_locked("home")
                if self.homing_chime_enabled:
                    self._play_stepper_chime_locked("home")
                if self.fan_power:
                    self.fan_off_at = time.monotonic() + self.fan_cooldown_s
                # One upstream G28 must receive exactly one ACK. Sending
                # internal ACKs would corrupt LightBurn flow control.
                return result
            except Aborted:
                raise
            except Exception as exc:
                self._close_locked("Referenzfahrt fehlgeschlagen: " + str(exc))
                raise
            finally:
                self.owner = previous_owner

    def move_to(self, x: float, y: float, owner: str = "web"):
        """Laser-off absolute XY move (camera scan, positioning).

        Never burns: M5 I first, refused while the laser is armed. Z is only
        ever raised (to the clearance height when lower), never lowered, so a
        move cannot collide with the workpiece. XY may cross the safe zone
        like parking does; the laser is off.
        """
        import math
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise RuntimeError("SKR nicht bereit / Notstopp aktiv")
            if not self.homed:
                raise RuntimeError("Fahren erst nach gültiger XYZ-Referenzfahrt")
            if self.laser_enabled:
                raise RuntimeError("Fahren bei aktivem Laser unzulässig")
            if not (math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= 390.0 and 0.0 <= y <= 370.0):
                raise ValueError("Ziel außerhalb X0..390 / Y0..370")
            self._exchange_locked("M5 I", timeout=8)
            self._exchange_locked("M400", timeout=30)
            self._exchange_locked("M114", timeout=8)
            if self.position is None:
                raise RuntimeError("Position unbekannt: keine Fahrt")
            if not self.absolute_mode:
                self._exchange_locked("G90", timeout=8)
                self.absolute_mode = True
            if self.position[2] < self.travel_z:
                self._exchange_locked(f"G0 Z{self.travel_z:.3f} F{self.z_feed}", timeout=45)
            self._exchange_locked(f"G0 X{x:.3f} Y{y:.3f} F9000", timeout=90)
            self._exchange_locked("M400", timeout=90)
            result = self._exchange_locked("M114", timeout=8)
            self.last_xy_commanded = (x, y)
            return result

    def _check_parked_locked(self):
        """At X0/Y0 the X and Y switches must be pressed; open means the head
        was moved by hand or lost steps: the reference is dropped (the next
        automatic job homes first). None when nothing can be checked."""
        if not self.homed or self.switch_check is not True or self.last_xy_commanded != (0.0, 0.0):
            return None
        stops = parse_endstops(self._exchange_locked("M119", timeout=8))
        if "x_min" not in stops or "y_min" not in stops:
            return None
        if stops["x_min"] and stops["y_min"]:
            return True
        open_axes = "/".join(a.upper() for a in ("x", "y") if not stops[a + "_min"])
        self.homed = False
        self.z_homed = False
        self.surface_z = None
        self.last_xy_commanded = None
        self.reference_lost = ("Kopf steht nicht mehr am Nullpunkt (Endschalter %s offen) – von Hand bewegt "
                               "oder Schritte verloren. Vor dem nächsten Auftrag wird neu referenziert." % open_axes)
        LOG.warning("Reference lost: %s switch open at X0/Y0", open_axes)
        return False

    def check_reference(self, owner=None):
        """Reference check while nobody else drives the machine (idle monitor, before a start)."""
        with self.lock:
            if (self.owner not in (None, owner) or self.serial is None or not self.identity
                    or self.emergency_latched or self.laser_enabled):
                return None
            return self._check_parked_locked()

    def _apply_motion_locked(self, limits=None):
        accel, speed = limits or self.motion_limits or FIRMWARE_MOTION
        for cmd in motion_commands(accel, speed, self.z_speed_mm_s):
            self._exchange_locked(cmd, timeout=6.0)

    def controller_motion(self):
        """(accel mm/s², speed mm/s) the controller itself allows, None = SKR.

        Only the Grbl bridge (Atomstack board) has fixed limits of its own
        ($110/$111, $120/$121); Marlin takes the Pi's M201/M203.
        """
        bridge = self.serial
        if bridge is None or not hasattr(bridge, "max_rate"):
            return None
        s = bridge.settings
        accel = min(s.get(120, 1000.0), s.get(121, 1000.0))
        return (accel, bridge.max_rate() / 60.0)

    def set_motion_limits(self, limits, owner: str = "web"):
        """Stores (accel, speed) or None (firmware values) and sends them when connected."""
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            self.motion_limits = limits
            if self.serial is not None and self.identity and not self.emergency_latched:
                self._exchange_locked("M400", timeout=60)
                self._apply_motion_locked()

    def motion_test(self, accel: float, speed: float, x: float, y: float, span: float,
                    cycles: int, owner: str = "web", should_stop=None):
        """Laser-off stress moves for the motion calibration.

        Sets [accel]/[speed] for the test only, then drives [cycles] times
        out from (x, y) by [span] mm and back: +X, -X, +Y, -Y and both
        diagonals, ending exactly at (x, y). Z is raised to the clearance
        first (as moveto). The stored limits are restored afterwards, also
        on error. A lost step shows as an offset of the next lasered mark.
        """
        import math
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise RuntimeError("SKR nicht bereit / Notstopp aktiv")
            if not self.homed:
                raise RuntimeError("Fahren erst nach gültiger XYZ-Referenzfahrt")
            if self.laser_enabled:
                raise RuntimeError("Fahren bei aktivem Laser unzulässig")
            if not (MOTION_ACCEL_RANGE[0] <= accel <= MOTION_ACCEL_RANGE[1]
                    and MOTION_SPEED_RANGE[0] <= speed <= MOTION_SPEED_RANGE[1]):
                raise ValueError("Beschleunigung %g..%g mm/s², Tempo %g..%g mm/s" % (MOTION_ACCEL_RANGE + MOTION_SPEED_RANGE))
            if not (math.isfinite(x) and math.isfinite(y) and 5.0 <= span <= 120.0 and 1 <= cycles <= 30
                    and 0.0 <= x - span and x + span <= 390.0 and 0.0 <= y - span and y + span <= 370.0):
                raise ValueError("Testbewegung außerhalb X0..390 / Y0..370")
            self._exchange_locked("M5 I", timeout=8)
            self._exchange_locked("M400", timeout=30)
            self._exchange_locked("M114", timeout=8)
            if self.position is None:
                raise RuntimeError("Position unbekannt: keine Fahrt")
            if not self.absolute_mode:
                self._exchange_locked("G90", timeout=8)
                self.absolute_mode = True
            if self.position[2] < self.travel_z:
                self._exchange_locked(f"G0 Z{self.travel_z:.3f} F{self.z_feed}", timeout=45)
            self._exchange_locked(f"G0 X{x:.3f} Y{y:.3f} F9000", timeout=90)
            self._exchange_locked("M400", timeout=90)
            feed = speed * 60
            try:
                self._apply_motion_locked((accel, speed))
                for _ in range(cycles):
                    for dx, dy in ((span, 0), (-span, 0), (0, span), (0, -span), (span, span), (-span, -span)):
                        self._exchange_locked(f"G0 X{x + dx:.3f} Y{y + dy:.3f} F{feed:.0f}", timeout=60)
                        self._exchange_locked(f"G0 X{x:.3f} Y{y:.3f} F{feed:.0f}", timeout=60)
                    if should_stop is not None and should_stop():
                        break
                self._exchange_locked("M400", timeout=180)
            finally:
                self._apply_motion_locked()
            result = self._exchange_locked("M114", timeout=8)
            self.last_xy_commanded = (x, y)
            return result

    def park_safezone(self, owner: str = "web"):
        """LightBurn M2: laser-off, Z retract, then XY park inside keep-out.

        Explicit end-of-job only. M5 I is used for intermediate segments,
        and MUST NOT trigger a park. Z never goes down on the way; only at
        X0/Y0 it lowers to park_z_mm (_lower_to_park_locked).
        """
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise RuntimeError("SKR nicht bereit / Notstopp aktiv")
            if not self.homed:
                raise RuntimeError("Parken erst nach gültiger XYZ-Referenzfahrt")
            self._exchange_locked("M5 I", timeout=8)
            self.laser_enabled = False
            self.guard.inline = False
            if self.fan_power:
                self.fan_off_at = time.monotonic() + self.fan_cooldown_s
            self._exchange_locked("M400", timeout=30)
            self._exchange_locked("M114", timeout=8)
            if self.position is None:
                raise RuntimeError("Parkhöhe unbekannt: keine Fahrt")
            # Positive Z is verified upward, and Z_max is Z_MAX_MM (80 mm).
            # Current height always wins, to avoid a dangerous downward park.
            z_target = max(self.position[2], self.travel_z,
                           0.0 if self.surface_z is None else
                           self.surface_z + self.probe_clearance_mm)
            if z_target > Z_MAX_MM + 0.0001:
                raise RuntimeError("Z-Position außerhalb konfiguriertem Z-Hub (max. Z%g)" % Z_MAX_MM)
            if not self.absolute_mode:
                self._exchange_locked("G90", timeout=8)
                self.absolute_mode = True
            self._exchange_locked(f"G0 Z{z_target:.3f} F{self.z_feed}", timeout=45)
            self._exchange_locked("M400", timeout=45)
            self._exchange_locked("G0 X0.000 Y0.000 F9000", timeout=90)
            self._exchange_locked("M400", timeout=90)
            result = self._exchange_locked("M114", timeout=8)
            self.focused_this_job = False
            self.last_xy_commanded = (0.0, 0.0)
            # parked at X0/Y0: the switches show whether the job lost steps
            self._check_parked_locked()
            if self._lower_to_park_locked():
                result = self._exchange_locked("M114", timeout=8)
            self._light_effect_locked("done")
            if self.job_chime_enabled:
                self._play_stepper_chime_locked("done")
            return result

    def probe_workpiece(self, owner: str = "lightburn"):
        """Intercept LightBurn G30; probe with the firmware's G30, preserve bed Z0."""
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if not self.homed or not self.homing_verified:
                raise RuntimeError("G30 benötigt Maschinenreferenz: zuerst G28 senden")
            if self.serial is None or self.emergency_latched:
                raise RuntimeError("SKR nicht verbunden / Notstopp aktiv")
            if self.laser_enabled:
                raise RuntimeError("Werkstückabtastung bei aktivem Laser unzulässig")
            if self.cap_z_probe is False:
                raise RuntimeError("SKR meldet Cap:Z_PROBE:0: G30 nicht installiert. "
                                   "Aktuelle SKR-Firmware mit Z-MIN-Probe flashen "
                                   "und M115 Cap:Z_PROBE:1 pruefen.")
            if self.probe_xy_offset_mm is None:
                raise ValueError("X/Y-Tasterversatz muss zuerst kalibriert sein")
            self.surface_z = None
            self.focused_this_job = False
            self._exchange_locked("M5 I", timeout=8)
            self._exchange_locked("M400", timeout=20)
            self._exchange_locked("M114", timeout=8)
            if self.position is None:
                raise RuntimeError("Ausgangsposition für G30 unbekannt")
            self._absolute_locked()
            laser_x, laser_y, z = self.position
            if self.last_xy_commanded is not None:
                tx, ty = self.last_xy_commanded
                if abs(laser_x - tx) > 0.15 or abs(laser_y - ty) > 0.15:
                    raise RuntimeError(
                        f"G30 Positionsabgleich fehlgeschlagen: erwartet X{tx:.2f} "
                        f"Y{ty:.2f}, Firmware meldet X{laser_x:.2f} Y{laser_y:.2f}")
            # After M2 parks at X0/Y0, a repeated G30 should use the
            # previously successful measurement location, not the park.
            # Reuse only when the requested position is inside keep-out.
            if self.in_park_corner(laser_x, laser_y):
                if self.last_probe_laser_xy is None:
                    raise ValueError("G30 in Parkzone: zuerst eine Werkstueckposition anfahren")
                laser_x, laser_y = self.last_probe_laser_xy
                self._exchange_locked(
                    f"G0 X{laser_x:.3f} Y{laser_y:.3f} F9000", timeout=60)
                self._exchange_locked("M400", timeout=60)
                self._exchange_locked("M114", timeout=8)
            dx, dy = self.probe_xy_offset_mm
            # Offset is (probe-tip minus laser-point) in machine XY.
            # Reposition head so probe reaches the selected laser XY point.
            x, y = laser_x - dx, laser_y - dy
            if not self._probe_head_ok(x, y):
                raise ValueError("Werkstück-Abtastpunkt außerhalb X%g..%g/Y%g..%g" % (
                    PROBE_HEAD_MIN[0], self.travel_xy[0] - 10.0,
                    PROBE_HEAD_MIN[1], self.travel_xy[1] - 10.0))
            if z < self.travel_z:
                self._exchange_locked(f"G0 Z{self.travel_z:.3f} F{self.z_feed}", timeout=45)
                self._exchange_locked("M400", timeout=45)
            self._exchange_locked(f"G0 X{x:.3f} Y{y:.3f} F9000", timeout=60)
            self._exchange_locked("M400", timeout=60)
            self.last_xy_commanded = (x, y)
            contact, replies = self._probe_here_locked()
            self.surface_z = contact
            self.last_probe_laser_xy = (laser_x, laser_y)
            lift = min(Z_MAX_MM, max(self.travel_z, contact + self.probe_clearance_mm))
            self._exchange_locked(f"G0 Z{lift:.3f} F{self.z_feed}", timeout=45)
            self._exchange_locked("M400", timeout=45)
            self._exchange_locked(f"G0 X{laser_x:.3f} Y{laser_y:.3f} F9000", timeout=60)
            self._exchange_locked("M400", timeout=60)
            self._exchange_locked("M114", timeout=8)
            self.last_xy_commanded = (laser_x, laser_y)
            self.focused_this_job = False
            self.fault = ""
            return [f"echo:LumaCut workpiece Z:{contact:.3f}"] + replies

    def _absolute_locked(self):
        """G90 before absolute moves. A relative jog that failed after its
        G91 left the firmware relative: G30's "G0 X212 Y167" then drove from
        X185/Y180 into the X end (01.11.)."""
        if not self.absolute_mode:
            self._exchange_locked("G90", timeout=8)
            self.absolute_mode = True

    def _probe_head_ok(self, x: float, y: float) -> bool:
        return (PROBE_HEAD_MIN[0] <= x <= self.travel_xy[0] - 10.0 and
                PROBE_HEAD_MIN[1] <= y <= self.travel_xy[1] - 10.0)

    def probe_reachable(self, x: float, y: float) -> bool:
        """True when the switch can probe laser point X/Y (head = point - offset)."""
        if self.probe_xy_offset_mm is None:
            return False
        dx, dy = self.probe_xy_offset_mm
        return self._probe_head_ok(x - dx, y - dy)

    def _probe_here_locked(self):
        """G30 at the current head XY: (contact Z, reply lines), the head stays
        at the contact. M400 first: the lift before it must have left the
        switch, or the firmware answers "Probe already triggered"."""
        self._exchange_locked("M400", timeout=60)
        try:
            replies = self._exchange_locked("G30", timeout=120)
        except MarlinCommandError as exc:
            text = str(exc).lower()
            if "already triggered" in text:
                raise RuntimeError("Z-Taster war schon beim G30-Start gedrückt: Taster klemmt/"
                                   "Verdrahtung prüfen, Material zu hoch für Z-Rückzug") from exc
            if "probing failed" in text:
                raise RuntimeError("G30 ohne Tasterkontakt: kein Material unter dem Taster "
                                   "oder X/Y-Tasterversatz falsch") from exc
            raise
        contact = None
        for line in replies:
            match = PROBE_RESULT_RE.search(line)
            if match:
                contact = float(match.group(1))
        if contact is None or not -BED_BELOW_Z0_MM <= contact <= Z_MAX_MM:
            raise RuntimeError("G30 meldet keinen gültigen Z-Tastkontakt")
        return contact, replies

    def probe_surface(self, groups, owner: str = "job", progress=None,
                      should_stop=None, hop_mm: float = PROBE_HOP_MM, skip_missing: bool = False):
        """Probe several laser X/Y points quickly; returns the contacts per group.

        ``groups`` are lists of laser points, one list per motif area. Inside
        an area the head only hops to the highest contact of that area plus
        ``hop_mm``; between areas it travels at the Z clearance (unknown
        height there). The lowest point is probed once more at the end, so
        the measured surface (and with it the Z floor surface + 2 mm) is the
        lowest one: every focus height of the job is then allowed. Laser stays
        off. A failed point leaves the head there; the caller parks.
        ``skip_missing`` (bed map): a point where the switch finds nothing
        before the firmware's lowest probe Z is left None instead of
        stopping; every other probe error still stops.
        """
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if not self.homed or not self.homing_verified:
                raise RuntimeError("Abtasten benötigt Maschinenreferenz")
            if self.serial is None or self.emergency_latched:
                raise RuntimeError("SKR nicht verbunden / Notstopp aktiv")
            if self.laser_enabled:
                raise RuntimeError("Werkstückabtastung bei aktivem Laser unzulässig")
            if self.cap_z_probe is False:
                raise RuntimeError("SKR meldet Cap:Z_PROBE:0: G30 nicht installiert")
            if self.probe_xy_offset_mm is None:
                raise ValueError("X/Y-Tasterversatz muss zuerst kalibriert sein")
            if not groups or any(not g for g in groups):
                raise ValueError("Keine Abtastpunkte")
            for group in groups:
                for x, y in group:
                    if not self.probe_reachable(x, y):
                        raise ValueError("Abtastpunkt X%.1f Y%.1f für den Taster nicht erreichbar" % (x, y))
            dx, dy = self.probe_xy_offset_mm
            self._absolute_locked()
            self.surface_z = None
            self.focused_this_job = False
            values = [[None] * len(g) for g in groups]
            total = sum(len(g) for g in groups) + 1
            done = 0

            def step_done():
                nonlocal done
                done += 1
                if progress is not None:
                    progress(done, total)

            def check_stop():
                if should_stop is not None and should_stop():
                    raise Aborted()

            def contact_at(x, y):
                try:
                    return self._probe_here_locked()[0]
                except (MarlinCommandError, RuntimeError, ValueError) as exc:
                    raise ProbeFailed(x, y, exc) from exc

            def lift(target):
                nonlocal z
                target = min(target, Z_MAX_MM)
                if z < target - 0.001:
                    self._exchange_locked(f"G0 Z{target:.3f} F{self.z_feed}", timeout=45)
                    z = target

            def go(x, y):
                hx, hy = x - dx, y - dy
                self._exchange_locked(f"G0 X{hx:.3f} Y{hy:.3f} F9000", timeout=60)
                self.last_xy_commanded = (hx, hy)

            self._exchange_locked("M5 I", timeout=8)
            self._exchange_locked("M400", timeout=20)
            self._exchange_locked("M114", timeout=8)
            if self.position is None:
                raise RuntimeError("Ausgangsposition für das Abtasten unbekannt")
            if not self.absolute_mode:
                self._exchange_locked("G90", timeout=8)
                self.absolute_mode = True
            z = self.position[2]
            tallest = None
            for gi, group in enumerate(groups):
                highest = None
                for pi, (x, y) in enumerate(group):
                    check_stop()
                    if highest is not None:
                        lift(highest + hop_mm)
                    else:   # new area: height unknown, travel high
                        lift(self.travel_z if tallest is None
                             else max(self.travel_z, tallest + hop_mm))
                    go(x, y)
                    try:
                        contact = contact_at(x, y)
                    except ProbeFailed as exc:
                        if not skip_missing or "ohne Tasterkontakt" not in str(exc.cause):
                            raise
                        LOG.warning("Probe point skipped: %s", exc)
                        self._exchange_locked("M114", timeout=8)
                        z = self.position[2] if self.position is not None else -BED_BELOW_Z0_MM
                        lift(self.travel_z if highest is None else highest + hop_mm)
                        step_done()
                        continue
                    values[gi][pi] = contact
                    highest = contact if highest is None else max(highest, contact)
                    tallest = highest if tallest is None else max(tallest, highest)
                    z = contact
                    lift(highest + hop_mm)
                    step_done()
            check_stop()
            found = [(g, p) for g in range(len(groups)) for p in range(len(groups[g]))
                     if values[g][p] is not None]
            if not found:
                raise RuntimeError("Der Taster hat an keinem Punkt eine Fläche gefunden")
            gi, pi = min(found, key=lambda gp: values[gp[0]][gp[1]])
            if gi != len(groups) - 1:
                lift(max(self.travel_z, tallest + hop_mm))
            x, y = groups[gi][pi]
            go(x, y)
            low = values[gi][pi] + hop_mm
            if z > low + 0.001:
                self._exchange_locked(f"G0 Z{low:.3f} F{self.z_feed}", timeout=45)
                z = low
            contact = contact_at(x, y)
            values[gi][pi] = contact
            z = contact
            step_done()
            lift(max(self.travel_z, tallest + self.probe_clearance_mm))
            self._exchange_locked("M400", timeout=45)
            self._exchange_locked("M114", timeout=8)
            self.surface_z = min(v for g in values for v in g if v is not None)
            self.last_probe_laser_xy = (x, y)
            self.focused_this_job = False
            self.fault = ""
            return values

    def clear_emergency(self):
        """Release the M112 latch with M999, on a fresh connection.

        The firmware answers M115 and M999 while latched. Afterwards the
        board is unhomed with laser PWM and the PC6 rail off; also after a
        reset or power cycle, where M999 changes nothing.
        """
        with self.lock:
            if not self.emergency_latched:
                return "Kein Notstopp aktiv"
            if self.owner is not None:
                raise RuntimeError("Steuerung belegt: " + self.owner)
            self.emergency_latched = False
            try:
                self._connect_locked(quit_emergency=True)
            except Exception as exc:
                self.emergency_latched = True
                raise RuntimeError("SKR antwortet nicht: USB prüfen, Reset-Taste am SKR drücken "
                                   "oder 24 V und USB kurz trennen (" + str(exc)[:80] + ")")
            self.fault = ""
            return "Notstopp quittiert, bitte neu referenzieren"

    def flash_firmware(self, image: bytes, settle_timeout: float = 60.0,
                       boot_wait: float = 3.0, poll: float = 2.0):
        """Self-update (M997, firmware_flash.py), then verify the build by M115.

        The firmware keeps the running image until the whole new one arrived
        with a good checksum. Any failure before "ok DONE" therefore leaves it
        untouched; the port is closed and the heartbeat connects again. Runs
        for up to a minute: call from a worker thread. Ownership 'firmware'
        keeps LightBurn, jobs and the heartbeat away for the whole update.
        """
        from .firmware_flash import SelfUpdateUploader, validate_image
        info = validate_image(image)
        expected = info["build"]
        with self.lock:
            if self.owner is not None:
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise RuntimeError("SKR nicht bereit oder Notstopp aktiv")
            if not self.cap_self_update:
                raise RuntimeError(
                    "Aktuelle SKR-Firmware kann sich nicht selbst aktualisieren "
                    "(Cap:SELF_UPDATE fehlt): einmalig per SD-Karte flashen")
            self.owner = "firmware"
            previous = self.identity
            self.firmware = {"state": "uploading", "progress": 0,
                             "message": "Laser, Relais, Licht und Abluft aus"}
        try:
            with self.lock:
                self._exchange_locked("M5 I", timeout=8)
                self._exchange_locked("M400", timeout=60)
                # PC6 switches the laser module's 24 V rail: off before reset.
                self._exchange_locked("M107 P0", timeout=8)
                self._exchange_locked("M9", timeout=8)
                self._exchange_locked("M355 S0", timeout=8)
                self.laser_enabled = False
                self.fan_power = False
                self.lights = self.exhaust = False
                self.state = "Busy"
                self.serial.reset_input_buffer()
                port = self.serial
            # Outside the lock so /api/status stays responsive; the
            # 'firmware' owner already keeps every other sender out.
            uploader = SelfUpdateUploader(port, log=self.lines.append)

            def progress(done, total):
                self.firmware.update(progress=round(100 * done / total),
                                     message=f"Übertrage {done // 1024} / {total // 1024} KB")
            try:
                uploader.upload(image, progress)
            except Exception as exc:
                with self.lock:
                    self._close_locked("Firmware-Update abgebrochen, laufende Firmware bleibt: "
                                       + str(exc)[:120])
                raise RuntimeError("Firmware-Update abgebrochen, laufende Firmware bleibt: "
                                   + str(exc)[:150]) from exc
            with self.lock:
                self.firmware.update(state="rebooting", progress=100,
                                     message="SKR kopiert die neue Firmware und startet neu")
                # After "ok DONE" the firmware drops USB by itself.
                self._close_locked("Firmware-Update: SKR startet neu")
            deadline = time.monotonic() + settle_timeout
            time.sleep(boot_wait)
            last_error = ""
            while time.monotonic() < deadline:
                try:
                    self.ensure_ready(owner="firmware")
                    break
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(poll)
            else:
                raise RuntimeError("SKR nach dem Update nicht wieder erreichbar, Rettung per SD-Karte: "
                                   + last_error[:120])
            with self.lock:
                running = self.identity
            if expected and f"({expected})" not in running:
                raise RuntimeError(
                    f"SKR läuft nicht mit dem neuen Build ({expected}). Meldung: " + running[:120])
            if not expected and running == previous:
                raise RuntimeError("SKR meldet unveränderte Firmware nach dem Update")
            self.firmware = {"state": "done", "progress": 100,
                             "message": "Neue Firmware aktiv: " + (expected or running[:60])}
            return self.firmware["message"]
        except Exception as exc:
            self.firmware = {"state": "error", "progress": self.firmware.get("progress", 0),
                             "message": str(exc)[:200]}
            raise
        finally:
            with self.lock:
                if self.owner == "firmware":
                    self.owner = None

    def flash_avr(self, hex_text: str, port: str | None = None, opener=None):
        """Flash a firmware.hex onto the Anet board (ATmega1284P) over USB.

        avr_flash.py talks to the board's boot loader directly (STK500, the
        CH340's DTR resets the chip) and reads every page back. Runs ~20 s:
        call from a worker thread. Owner 'firmware' keeps everyone else away.
        The Anet build is Marlin and this gateway only drives the firmware of
        docs/FIRMWARE_EIGEN.md, so there is no reconnect and no M115 check.
        """
        from .avr_flash import BOOT_BAUD, flash as avr_flash, validate_hex
        from .grbl_bridge import grbl_ports
        info = validate_hex(hex_text)
        expected = info["build"]
        with self.lock:
            if self.owner is not None:
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.emergency_latched:
                raise RuntimeError("Notstopp aktiv – erst quittieren")
            port = port or next(iter(grbl_ports()), None)
            if not port:
                raise RuntimeError("Kein Anet-Board (CH340) per USB gefunden")
            self.owner = "firmware"
            self.firmware = {"state": "uploading", "progress": 0,
                             "message": "Laser aus, Board startet den Bootloader"}
        try:
            with self.lock:
                if self.serial is not None and self.identity:
                    for cmd in ("M5 I", "M107 P0", "M9"):
                        try:
                            self._exchange_locked(cmd, timeout=8)
                        except Exception:
                            pass
                self.laser_enabled = self.fan_power = False
                self.lights = self.exhaust = False
                self._close_locked("Firmware-Update: Anet wird geflasht")
                self.state = "Busy"
            ser = (opener or _open_boot_port)(port, BOOT_BAUD)

            def progress(done, total):
                step = "Schreibe" if done <= total // 2 else "Prüfe"
                self.firmware.update(progress=round(100 * done / total),
                                     message="%s %d / %d Seiten" % (step, done, total))
            try:
                avr_flash(ser, info["image"], progress, log=self.lines.append)
            finally:
                try:
                    ser.dtr = ser.rts = False
                    ser.close()
                except Exception:
                    pass
            self.firmware = {"state": "done", "progress": 100,
                             "message": "Anet-Firmware geschrieben und geprüft: " + (expected or "ohne Build-Stempel")}
            return self.firmware["message"]
        except Exception as exc:
            self.firmware = {"state": "error", "progress": self.firmware.get("progress", 0),
                             "message": str(exc)[:200]}
            raise
        finally:
            with self.lock:
                if self.owner == "firmware":
                    self.owner = None

    def status(self):
        with self.lock:
            return {
                "connected": self.serial is not None and bool(self.identity),
                "state": self.state, "owner": self.owner or "Frei",
                "identity": self.identity, "homed": self.homed,
                "z_homed": self.z_homed, "z_probe_supported": self.cap_z_probe, "emergency_latched": self.emergency_latched,
                "firmware_upload_supported": self.cap_self_update,
                # CH340 board for an Anet firmware.hex (flash_avr), None = none
                "firmware_avr_port": _ch340_port(),
                "firmware_update": dict(self.firmware),
                "homing_verified": self.homing_verified,
                "reference": {"switch_check": self.switch_check, "lost": self.reference_lost},
                "position": self.position, "fault": self.fault,
                "lights": self.lights, "exhaust": self.exhaust,
                "light_brightness": int(round(self.light_pct)), "light_dimmable": self.light_pwm,
                "light_effects": self.light_effects,
                "laser_armed": self.laser_enabled,
                "laser_cooling_fan_on": self.fan_power,
                "service_laser_percent": int(round(self.service_power / 2.55)),
                "workpiece_surface_z": self.surface_z,
                "park_corner_mm": {"x": self.park_corner[0], "y": self.park_corner[1]},
                "probe_xy_offset_mm": self.probe_xy_offset_mm,
                # burn anywhere in this box except the park corner
                "cutting_bounds": {"x_min": 0.0, "y_min": 0.0,
                                   "x_max": self.travel_xy[0], "y_max": self.travel_xy[1]},
                "probe_minimum_z": (None if self.surface_z is None else
                                    self.surface_z + self.probe_clearance_mm),
                "laser_focus_z": (None if self.surface_z is None else
                                  self.surface_z + self.focus_gap_mm - self.probe_tip_offset_mm),
                "cooldown_remaining_s": (None if self.fan_off_at is None else
                    max(0, round(self.fan_off_at - time.monotonic()))),
                "serial_errors": self.serial_errors,
                "command_count": self.commands,
                "stream_window": self.stream_window,
                "streamed_count": self.streamed,
                "lightburn_clients": self.lightburn_clients,
                "recent": list(self.lines)[-25:]
            }

    def quick_stop(self, owner: str = "job"):
        """Beam and motion stop at once, the reference stays.

        M5 I does not touch queued blocks (they would burn on), M410 clears
        them on reception. Written ahead of the command lock like M112: a
        running M400 or G28 holds the lock until it ends, and its answer comes
        early because of this very M410. Its own ok is counted and taken out
        of the stream, so nobody reads it as the answer to something else.
        """
        if self.owner not in (None, owner):
            raise RuntimeError("Steuerung belegt: " + self.owner)
        serial_port = self.serial
        if serial_port is None:
            raise ConnectionError("SKR USB nicht verbunden")
        self._write_m410(serial_port)
        self.service_power = 0
        contended = not self.lock.acquire(blocking=False)
        if contended:
            self.lock.acquire()
        try:
            if self.serial is None:
                return
            if contended:
                # Whoever held the lock may have streamed on after our first M410.
                self._write_m410(self.serial)
            self.service_power = 0
            self.laser_enabled = False
            self.guard.inline = False
            self.last_xy_commanded = None
            try:
                self._drain_locked(30.0)
            except MarlinCommandError as exc:
                LOG.warning("Quick stop: %s", exc)
            self._absorb_stray_oks(time.monotonic() + 5.0)
        finally:
            self.lock.release()

    def _write_m410(self, serial_port):
        with self._stray_lock:
            self._stray_oks += 1
        serial_port.write(b"M410\n")

    def _absorb_stray_oks(self, deadline):
        try:
            while self._stray_oks:
                line = self._read_line_locked(deadline, until_no_stray=True)
                if line and self._is_fault_locked(line):
                    self.serial_errors += 1
                    self.fault = _fault_text(line)
        except TimeoutError:
            LOG.warning("Quick stop: Bestätigung von M410 fehlt")
            with self._stray_lock:
                self._stray_oks = 0

    def emergency_stop(self):
        # The firmware evaluates M112 on reception, also with a full queue.
        # A hardware E-Stop / power interlock remains essential.
        # Do not acquire the long-running command lock: a streaming G28
        # or G1 may be awaiting 'ok'.
        self.service_power = 0
        serial_port = self.serial
        if serial_port is None:
            self.emergency_latched = True
            self.homed = False
            self.fault = "Software-Notstopp NICHT übertragen: USB getrennt, physischen Not-Aus benutzen"
            raise ConnectionError(self.fault)
        if serial_port is not None:
            try:
                serial_port.write(b"M112\n")
                self.fault = "M112 ausgelöst: Notstopp quittieren, dann neu referenzieren"
                self.emergency_latched = True
                self.homed = False
                self.z_homed = False
                self.laser_enabled = False
            except Exception as exc:
                self.fault = "Software-Notstopp fehlgeschlagen: " + str(exc)
                raise

    def serve_client(self, client):
        client.settimeout(1.0)
        with self.lock:
            if self.owner is not None or self.serial is None or not self.identity:
                # Do not generate repeated unsolicited error lines for every
                # reconnect attempt. LightBurn reconnects aggressively when
                # a previous stream aborts.
                client.close()
                return
            self.owner = "lightburn"
            self.lightburn_clients += 1
            self.client = client
            self.guard = MarlinLaserGuard()
            self.focused_this_job = False
        fragment = bytearray()
        try:
            # Line-by-line ACK backpressure. Never send blind batches to a
            # microcontroller with a finite receive and command queue.
            while True:
                try:
                    payload = client.recv(4096)
                except socket.timeout:
                    continue
                if not payload:
                    break
                for b in payload:
                    if b in (10, 13):
                        if not fragment:
                            continue
                        cmd = fragment.decode("ascii", errors="replace")
                        fragment.clear()
                        try:
                            normalized = normalize(cmd)
                            if normalized == "M112":
                                self.emergency_stop()
                                client.sendall(b"Error:LumaCut M112 emergency stop sent; reset required\r\n")
                                return
                            if normalized == "G00 G17 G40 G21":
                                # LightBurn's initialization line:
                                # G00 is a modal rapid with no destination;
                                # G17 and G40 don't change our XY laser
                                # trajectory. Send real G21 and return its
                                # genuine ACK.
                                lines = self.command("G21", owner="lightburn", timeout=15)
                            elif normalized in FILTERED:
                                # LightBurn waits for an answer, the firmware
                                # never sees these (FILTERED).
                                lines = ["ok"]
                            elif normalized == "M2":
                                lines = self.park_safezone(owner="lightburn")
                            elif normalized == "G30":
                                lines = self.probe_workpiece(owner="lightburn")
                            elif normalized.startswith("G28"):
                                if normalized != "G28":
                                    raise ValueError("G28 nur ohne Achsen über Pi erlaubt")
                                lines = self.safe_home(owner="lightburn")
                            else:
                                lines = self.command(cmd, owner="lightburn", timeout=150.0,
                                                     after_queue=True)
                            for line in lines:
                                client.sendall((line + "\r\n").encode("ascii", "replace"))
                        except (ValueError, RuntimeError) as exc:
                            LOG.warning("Rejected LightBurn command %r: %s", normalized, exc)
                            client.sendall(("Error:LumaCut [" + normalized[:55] + "] " + str(exc)[:95] +
                                            "\r\n").encode("ascii", "replace"))
                            # Do not fake "ok": LightBurn must abort this job,
                            # but a rejected G-code must not look like USB loss.
                            # If cutting was armed, latch emergency stop.
                            if self.laser_enabled and not self.emergency_latched:
                                self.emergency_stop()
                                return
                            if self.serial is None or self.emergency_latched:
                                return
                            continue
                    elif 32 <= b <= 126 and len(fragment) < 95:
                        fragment.append(b)
                    else:
                        client.sendall(b"Error:LumaCut invalid/oversize G-code\r\n")
                        return
        except (OSError, ConnectionError, TimeoutError):
            LOG.warning("LightBurn connection lost", exc_info=True)
        finally:
            # The firmware may still be in inline laser mode if a Wi-Fi
            # client disappears mid-job. Fail closed instead of leaving it
            # armed until the firmware timeout. Hardware cutoff still needed.
            if self.laser_enabled and not self.emergency_latched:
                try:
                    self.emergency_stop()
                except Exception:
                    LOG.error("Could not issue M112 after unsafe LightBurn disconnect")
            with self.lock:
                if self.client is client:
                    self.owner = None
                    self.client = None
                    self.guard = MarlinLaserGuard()
            try:
                client.close()
            except OSError:
                pass


def serve_tcp(bridge: MarlinTransport, host: str, port: int, running):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(2)
        server.settimeout(1)
        while running():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            threading.Thread(target=bridge.serve_client, args=(conn,),
                             name="marlin-lb", daemon=True).start()
