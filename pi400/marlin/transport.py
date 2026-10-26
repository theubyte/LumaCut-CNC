"""Native Marlin USB transport and exclusive LightBurn/TCP gateway.

No GRBL identity spoofing, no '?'/$-commands, no blind line flooding.
One acknowledged Marlin G-code command is in flight at a time, except for
plain job moves sent with stream_command(): there a small, ok-counted
window (STREAM_MAX_LINES / STREAM_MAX_BYTES, below Marlin's BUFSIZE 8 and
256-byte RX buffer) keeps the planner fed. Every streamed line passes the
same MarlinLaserGuard and XY/Z guards first.
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
    r"\bBed\s+X:\s*[-+]?\d+(?:\.\d+)?\s+Y:\s*[-+]?\d+(?:\.\d+)?\s+Z:\s*([-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE)
WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
COMMENT = re.compile(r"\([^()]*\)")
READ_ONLY = frozenset({"M105", "M114", "M115", "M119", "M503", "M400"})
ERROR_PREFIXES = ("Error:", "echo:Error:", "Resend:", "rs ")
# Streaming window (#18). Marlin BUFSIZE 8 / RX_BUFFER_SIZE 256 on the SKR:
# stay at half of both so a slow ok can never overflow the serial buffer.
# LUMACUT_STREAM_WINDOW=1 restores strict one-line-at-a-time sending.
def _stream_window_setting(raw) -> int:
    try:
        return max(1, min(8, int(raw)))
    except (TypeError, ValueError):
        return 4


STREAM_MAX_LINES = _stream_window_setting(os.environ.get("LUMACUT_STREAM_WINDOW", "4"))
STREAM_MAX_BYTES = 200
STREAMABLE = re.compile(r"^G0?[01]\s")
# Marlin refuses G30 ("Z Probe Past Bounds") when the head is within
# PROBING_MARGIN (10 mm in the BTT example config) of X_BED_SIZE/Y_BED_SIZE.
PROBE_HEAD_MAX = (380.0, 360.0)
# The same margin on the low side (X/Y_MIN_POS 0). The laser is off while
# probing, so the head may enter the 30 mm safezone like it does to park;
# the safezone only forbids burning there.
PROBE_HEAD_MIN = (10.0, 10.0)
# Fast multi-point probing: low hop between the points of one area.
PROBE_HOP_MM = 3.0


class MarlinCommandError(RuntimeError):
    """Marlin rejected a command but the serial protocol was re-synchronized."""

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


class MarlinLaserGuard:
    """Conservatively permit only real Marlin 2.1 laser inline operation."""

    def __init__(self):
        self.inline = False
        self.last_rapid = False

    def check(self, command: str, homing_verified: bool):
        cmd = normalize(command)
        if not cmd:
            return ""
        if not cmd.isascii() or len(cmd) > 96:
            raise ValueError("G-Code überschreitet Marlin-Limit von 96 Zeichen")
        if cmd == "G20":
            raise ValueError("Z-Sicherheitsgrenze benötigt Millimeter, G20 gesperrt")
        if cmd.startswith(("$", "?", "!", "~")):
            raise ValueError("GRBL-Befehl am Marlin-Controller nicht zulässig")
        # Allow only known laser motion, harmless queries and lighting/exhaust.
        # Other Marlin commands can switch heater MOSFETs, disable software
        # limits or remap machine coordinates, so they are never forwarded.
        if cmd in READ_ONLY or cmd in ("M7", "M8", "M9", "M5", "M5 I",
                                         "G90", "G91", "G20", "G21"):
            if cmd.startswith("M5"):
                self.inline = False
                self.last_rapid = False
            return cmd
        # Marlin treats the I selector as a *bare flag* (M3 I, M5 I).
        # Recognize that spelling without turning it into a GRBL parameter.
        parsed = re.sub(r"(?<![A-Z])I(?=\s|$)", "I1", cmd)
        if cmd.startswith("G28"):
            # Marlin G28 takes bare axis flags such as "G28 Z" / "G28 X Y".
            parsed = re.sub(r"\b([XYZ])\b", r"\g<1>1", parsed)
        words = WORD.findall(parsed)
        if not words or WORD.sub("", parsed).strip():
            raise ValueError("Nicht unterstützte G-Code-Syntax")
        families = [f"{letter}{int(float(value))}" for letter, value in words
                    if letter in ("G", "M") and float(value).is_integer()]
        allowed_families = {"G0", "G1", "G2", "G3", "G4", "G28",
                            "G90", "G91", "G20", "G21", "M3", "M5",
                            "M7", "M8", "M9", "M105", "M112", "M114",
                            "M115", "M119", "M400", "M410", "M503"}
        if any(f not in allowed_families for f in families):
            raise ValueError("Marlin-G-Code nicht freigegeben")
        if len(families) > 1:
            raise ValueError("Pro Zeile nur ein G/M-Befehl erlaubt")
        if any(l not in "GMXYZIJRFSP" for l, _ in words):
            raise ValueError("Unbekannter G-Code-Parameter")
        if any(m in families for m in ("M112", "M410")):
            # Emergency commands are not legal job-file instructions.
            # The dedicated emergency endpoint writes M112 immediately.
            raise ValueError("Notstopp ausschließlich über separaten M112-Kanal")
        if "M4" in families:
            raise ValueError("Marlin M4 I nutzt Vorschub statt S-Leistung: M3 I erforderlich")
        if "M3" in families:
            # A single bare I flag is required, never M3 S which can fire
            # the laser immediately while stationary.
            if cmd != "M3 I":
                raise ValueError("Nur Marlin M3 I ohne S/O ist freigegeben")
            self.inline = True
            self.last_rapid = False
            return cmd
        if "M5" in families:
            if any(l == "I" for l, _ in words):
                self.inline = False
            self.last_rapid = False
            return cmd
        if "G28" in families:
            # Native Marlin G28 may move XY before Z retracting. The Pi
            # intercepts all G28 and executes a safe, staged home sequence.
            raise ValueError("G28 nur über Pi-Zuerst-Z-Referenzfahrt erlaubt")
        if any(m in families for m in ("G0", "G1", "G2", "G3")):
            if not homing_verified:
                raise ValueError("Fahrbewegung erst nach bestätigter Mechanik-Konfiguration freigeben")
            is_rapid = "G0" in families
            if is_rapid:
                if any(l == "S" and float(v) > 0 for l, v in words):
                    raise ValueError("G0 darf keine Laserleistung S>0 enthalten")
                self.last_rapid = True
            # A powered cut after a G0 requires a new S, per Marlin firmware.
            if any(m in families for m in ("G1", "G2", "G3")):
                power = [float(v) for l, v in words if l == "S"]
                if power and not self.inline and max(power) > 0:
                    raise ValueError("Laserleistung ohne vorheriges M3 I verweigert")
                if any(not 0 <= x <= 255 for x in power):
                    raise ValueError("Marlin S-Wert außerhalb 0..255")
                if self.last_rapid and self.inline and not power:
                    raise ValueError("Erste Bearbeitungsfahrt nach G0 benötigt S-Leistung")
                self.last_rapid = False
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
        self.cap_binary_transfer = False
        self.firmware = {"state": "idle", "progress": 0, "message": ""}
        # LightBurn assumes S is modal; Marlin resets inline power on G0.
        self.last_cut_s = None
        self.homed = False
        self.z_homed = False
        self.homing_verified = False
        self.emergency_latched = False
        self.clearance_mm = 20.0
        self.position = None
        self.fault = ""
        self.lines = deque(maxlen=80)
        self.commands = 0
        self.serial_errors = 0
        self.lightburn_clients = 0
        self.laser_enabled = False
        self.fan_power = False
        self.fan_cooldown_s = 180
        self.laser_supply_settle_ms = 800
        # A workpiece contact probe must explicitly establish surface_z.
        # Positive machine Z must point AWAY from the material.
        self.surface_z = None
        self.probe_tip_offset_mm = 1.5
        self.focus_gap_mm = 7.0
        self.probe_clearance_mm = 2.0
        # X<30 or Y<30 are permanently reserved for machine homing.
        # Cutting must occur strictly inside the remaining rectangle.
        self.safe_zone_xy_mm = 30.0
        self.probe_xy_offset_mm = None
        self.last_probe_laser_xy = None
        self.last_xy_commanded = None
        self.homing_chime_enabled = True
        self.job_chime_enabled = True
        # None = not tried yet; False after "Unknown command" (old firmware).
        self.motor_tones_supported: bool | None = None
        self.absolute_mode = True
        self.focused_this_job = False
        self.fan_off_at = None
        self.lights = False
        self.light_pct = 60            # operator brightness 1..100 %
        self.light_effects = True
        # None = not tried; True = M355 dimming; False = old firmware (M7/M9).
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
        self.state = "Disconnected"
        self.homed = False
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
        self.cap_binary_transfer = False
        self.motor_tones_supported = None   # new firmware may have been flashed
        if message:
            self.fault = message[:200]

    def _read_line_locked(self, deadline):
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
                if "FIRMWARE_NAME:Marlin" in line:
                    self.identity = line
                return line
        raise TimeoutError("Keine Marlin-Bestätigung vor Fristablauf")

    def _await_stream_ack_locked(self, timeout: float):
        """Read until one streamed line is acknowledged.

        Marlin answers strictly in order, one ok per received line
        (ADVANCED_OK "ok N.. P.. B.." counts the same). An error line
        belongs to one of the lines in flight and is followed by its ok;
        it is remembered and raised once the window is drained.
        """
        deadline = time.monotonic() + timeout
        while True:
            line = self._read_line_locked(deadline)
            if line.startswith(ERROR_PREFIXES):
                self.serial_errors += 1
                self.fault = "Marlin: " + line[:150]
                if not self.stream_error:
                    self.stream_error = self.fault
                continue
            if line.lower().startswith("ok"):
                self.inflight.popleft()
                self.commands += 1
                return

    def _drain_locked(self, timeout: float = 150.0):
        """Wait for every streamed line; raise a remembered Marlin error."""
        while self.inflight:
            self._await_stream_ack_locked(timeout)
        if self.stream_error:
            message, self.stream_error = self.stream_error, ""
            self.state = "Idle"
            raise MarlinCommandError(message)

    def _exchange_locked(self, cmd: str, timeout: float = 15.0):
        if self.serial is None:
            raise ConnectionError("SKR USB nicht verbunden")
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
            if line.startswith(ERROR_PREFIXES):
                self.serial_errors += 1
                self.fault = "Marlin: " + line[:150]
                # A Marlin error is usually followed by a normal "ok".
                # Consume that trailing ACK before the next command;
                # otherwise M114/G30 will read a stale ACK as its own.
                ack_deadline = min(deadline, time.monotonic() + 4.0)
                try:
                    while True:
                        trailing = self._read_line_locked(ack_deadline)
                        responses.append(trailing)
                        if trailing.lower().startswith("ok"):
                            self.state = "Idle"
                            # Keep the report lines Marlin printed between
                            # the error and its ACK (G30 reports the stop
                            # position there) for callers that can use them.
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
                raise RuntimeError("M112-Notstopp verriegelt – SKR zurücksetzen, dann Notstopp quittieren")
            if self.serial is not None and self.identity:
                return
            if self.owner not in (None, owner):
                raise RuntimeError("SKR noch nicht bereit, während Client verbunden ist")
            self._close_locked()
            try:
                self.serial = self._open()
                # STM32 USB may reset at open. Allow boot banner to settle.
                time.sleep(1.0)
                # Ignore unsolicited 'start'/welcome, then ask native M115.
                self.serial.reset_input_buffer()
                reply = self._exchange_locked("M115", timeout=8.0)
                if not any("FIRMWARE_NAME:Marlin" in x for x in reply):
                    raise RuntimeError("SKR meldet kein echtes Marlin M115")
                if "LumaCut CNC" not in self.identity:
                    raise RuntimeError("Fremde/alte Marlin-Firmware: LumaCut CNC Kennung fehlt")
                caps = [line.strip() for line in reply
                        if line.strip().startswith("Cap:Z_PROBE:")]
                # A firmware compiled without HAS_BED_PROBE cannot perform
                # real G30 probing, even when M119 recognizes Z_MIN.
                self.cap_z_probe = (caps[-1] == "Cap:Z_PROBE:1") if caps else None
                # Needed for firmware updates over USB (M28 B1 + M997).
                self.cap_binary_transfer = "Cap:BINARY_FILE_TRANSFER:1" in (
                    line.strip() for line in reply)
                self._exchange_locked("M5 I", timeout=6.0)
                # The installed EEPROM from earlier firmware reported
                # M203 Z6. Marlin limits homing and probing feedrate by that
                # runtime cap, even if the new firmware requests 7.2 mm/s.
                # User requested 1.8x Z speed. Set 9 mm/s on every SKR USB
                # reconnect; do not write permanent EEPROM without an
                # explicit flash/configuration workflow.
                self._exchange_locked("M203 Z9", timeout=6.0)
                # The same stale EEPROM may still hold the Mega Zero example
                # probe offset { -40, -10, 2 }. Marlin then shifts every G30
                # by X+40/Y+10, adds 2 mm to the result and lowers the
                # "triggered early" limit by 2 mm. The Pi applies the real
                # X/Y switch offset itself, so the firmware offset must be 0.
                try:
                    self._exchange_locked("M851 X0 Y0 Z0", timeout=6.0)
                except MarlinCommandError:
                    LOG.warning("M851 X/Y not accepted, resetting Z offset only")
                    self._exchange_locked("M851 Z0", timeout=6.0)
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
            # The target is known without asking Marlin. Draining the
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

    def _xy_cut_guard_locked(self, cmd: str):
        """Reject any armed linear cut touching the 30mm X/Y home bands.

        The previous tool position matters as much as the commanded target:
        an XY line from the home corner to the work area is not a cut.
        G0 with laser safely extinguished is permitted in home bands.

        The start point is the Pi's own record of the last commanded XY,
        not an M400/M114 query: M400 drains Marlin's planner, so querying
        before every segment stopped the head at each vector node and burnt
        dots/uneven lines into the material. Every XY move reaches Marlin
        through this gateway, so the commanded record is exact.
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
        lowest_x, lowest_y = min(px, tx), min(py, ty)
        if "I" in coords or "J" in coords:
            # Arc: the whole circle is a conservative envelope.
            cx, cy = px + coords.get("I", 0.0), py + coords.get("J", 0.0)
            radius = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            lowest_x, lowest_y = min(lowest_x, cx - radius), min(lowest_y, cy - radius)
        limit = self.safe_zone_xy_mm
        if min(lowest_x, lowest_y) < limit - 0.0001:
            raise ValueError(
                f"30mm-Homing-Sperrzone: Schnitt nur ab X={limit:g} "
                f"und Y={limit:g} mm; Start X{px:.2f} Y{py:.2f}, "
                f"Ziel X{tx:.2f} Y{ty:.2f}")

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
        self._exchange_locked(f"G0 Z{goal:.3f} F600", timeout=20)
        self._exchange_locked("M400", timeout=30)
        self._exchange_locked("M114", timeout=8)
        self.focused_this_job = True

    def command(self, cmd: str, owner: str = "web",
                timeout: float = 20.0, use_guard=True):
        with self.lock:
            normalized, passthrough = self._prepare_locked(cmd, owner, use_guard)
            if not normalized:
                return []
            if passthrough:
                return self._exchange_locked(normalized, timeout)
            return self._send_locked(normalized, timeout)

    def stream_command(self, cmd: str, owner: str = "job", timeout: float = 150.0):
        """Send a job line, keeping plain moves in a small ok-counted window.

        Same normalization and guards as command(). Only absolute G0/G1
        lines whose guards need no extra Marlin exchange (known start XY,
        focus done, no relative mode) are streamed; everything else first
        drains the window and then runs exactly like command(). A Marlin
        error on any streamed line stops further sending and raises after
        the window is drained.
        """
        with self.lock:
            normalized, passthrough = self._prepare_locked(cmd, owner, True)
            if not normalized:
                return []
            if passthrough:
                return self._exchange_locked(normalized, timeout)
            if not self._streamable_locked(normalized):
                return self._send_locked(normalized, timeout)
            return self._send_locked(normalized, timeout, stream=True)

    def drain(self, owner: str = "job", timeout: float = 150.0):
        """Wait until every streamed line is acknowledged by Marlin."""
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
            raise ConnectionError("Marlin USB nicht bereit")
        if self.emergency_latched:
            raise RuntimeError("M112-Notstopp aktiv; keine weiteren Bewegungen")
        normalized = normalize(cmd)
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
        # LightBurn often emits G0 X... Y... without an F word.
        # Marlin's modal feedrate might still be the slow Z feedrate;
        # give XY-only rapids their own travel speed every time.
        if (re.match(r"^G0?0(?:\s|$)", normalized)
                and re.search(r"\b[XY]\s*[-+]?\d", normalized)
                and not re.search(r"\bZ\s*[-+]?\d", normalized)
                and not re.search(r"\bF\s*[-+]?\d", normalized)):
            normalized += " F9000"
        # LightBurn treats S as modal, Marlin does not: after G0 the
        # inline power is 0, so a following G1 without S cuts at 0 and
        # the guard rejected it (which latched M112 mid-job). Re-send
        # the last cut power, exactly what LightBurn intended.
        if (owner == "lightburn" and self.laser_enabled and self.guard.last_rapid
                and self.last_cut_s is not None
                and re.match(r"^G0?[123](?:\s|$)", normalized)
                and not any(k == "S" for k, _ in WORD.findall(normalized))):
            normalized += f" S{self.last_cut_s:g}"
        if use_guard:
            normalized = self.guard.check(normalized, self.homing_verified)
        if not normalized:
            return "", True
        if normalized.startswith(("G0 ", "G1 ")) and "Z" in normalized and self.surface_z is None:
            raise RuntimeError("Keine Werkstückhöhe bekannt; keine Z-Fahrt über LightBurn freigeben")
        if normalized == "M3 I" and self.surface_z is None:
            raise RuntimeError("Werkstückkontakt fehlt: Z-Taster auf Material referenzieren")
        motion = re.match(r"^G0?[0123](?:\s|$)", normalized) is not None
        if (motion or normalized == "M3 I") and not self.homed:
            raise RuntimeError("Maschine nicht referenziert: in LightBurn zuerst Home (G28) ausfuehren; danach G30 fuer Werkstueckfokus")
        return normalized, False

    def _send_locked(self, normalized: str, timeout: float, stream: bool = False):
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
            if stream:
                reply = self._stream_write_locked(normalized, timeout)
            else:
                reply = self._exchange_locked(normalized, timeout)
            # Remember the workpiece target sent by LightBurn even if
            # asynchronous Marlin M114 reports arrive out of order.
            # Relative moves are tracked too: the cut guard uses this
            # record as the start point of the next segment.
            if re.match(r"^G0?[0123](?:\s|$)", normalized):
                coords = {k: float(v) for k, v in WORD.findall(normalized)}
                if "S" in coords and not normalized.startswith(("G0 ", "G00 ")):
                    self.last_cut_s = coords["S"]
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
            if normalized == "M7":
                self.lights = True
            if normalized == "M8":
                self.exhaust = True
            if normalized == "M9":
                self.exhaust = False
                if self.light_pwm is not True:
                    self.lights = False    # old firmware: M9 also switched PC8 off
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
        """Melody on the X/Y stepper coils, the head does not move.

        Uses the LumaCut firmware M300 (firmware/marlin/motor_tone.cpp): each
        tone alternates one microstep forward and back in SpreadCycle, so the
        motors sing loudly with zero net travel; Marlin refuses it while the
        laser is on. Coordinates and homing stay valid. Older firmware
        without it answers "Unknown command" and the melodies switch off
        quietly until the next connection.
        """
        notes = MELODIES.get(event)
        if (notes is None or self.serial is None or self.laser_enabled
                or self.motor_tones_supported is False):
            return False
        try:
            for hz, ms in notes:
                replies = self._exchange_locked(f"M300 S{hz} P{ms}",
                                                timeout=ms / 1000.0 + 10)
                text = " ".join(replies).lower()
                if "unknown command" in text:
                    self.motor_tones_supported = False
                    LOG.info("Firmware without motor tones (M300); melodies off")
                    return False
                if "refused" in text:
                    return False
            self.motor_tones_supported = True
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

    def _light_raw_locked(self, pct: float) -> bool:
        """Sets PC8 to ``pct``; False when the firmware cannot dim (old M7/M9)."""
        if self.light_pwm is not False:
            replies = self._exchange_locked(
                "M355 S%d P%d" % (1 if pct > 0 else 0, round(max(0.0, min(100.0, pct)) * 2.55)), timeout=8)
            if "unknown command" not in " ".join(replies).lower():
                self.light_pwm = True
                return True
            self.light_pwm = False
            LOG.info("Firmware without dimmable light (M355); using M7/M9")
        if pct > 0:
            self._exchange_locked("M7", timeout=8)
        else:
            self._exchange_locked("M9", timeout=8)
            if self.exhaust:
                self._exchange_locked("M8", timeout=8)
        return False

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
        if (steps is None or not self.light_effects or self.serial is None
                or self.light_pwm is False or self.emergency_latched):
            return False
        before = self.state
        try:
            for pct, ms in steps:
                if not self._light_raw_locked(pct):
                    return False           # old firmware: no effects
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

    def safe_home(self, owner: str = "web", clearance_mm: float | None = None,
                  probe_contact_confirmed: bool = False, should_stop=None):
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
                raise ConnectionError("Marlin USB nicht bereit oder Notstopp verriegelt")
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
            commands = ["M5 I", "G28 X Y", "M400",
                        "G28 Z", "M400", "G91",
                        f"G0 Z{clearance:.2f} F600", "G90", "M400", "M114"]
            result = []
            try:
                for index, cmd in enumerate(commands):
                    if index == 3 and should_stop is not None and should_stop():
                        self.last_xy_commanded = (0.0, 0.0)
                        raise Aborted()
                    result = self._exchange_locked(cmd, timeout=150 if "G28" in cmd else 35)
                    if cmd == "G28 Z":
                        self.z_homed = True
                        # G28 Z is a BED / MACHINE origin, NEVER workpiece Z.
                        self.surface_z = None
                self.homed = True
                self.absolute_mode = True
                self.last_xy_commanded = (0.0, 0.0)
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
            if self.position[2] < self.clearance_mm:
                self._exchange_locked(f"G0 Z{self.clearance_mm:.3f} F600", timeout=45)
            self._exchange_locked(f"G0 X{x:.3f} Y{y:.3f} F9000", timeout=90)
            self._exchange_locked("M400", timeout=90)
            result = self._exchange_locked("M114", timeout=8)
            self.last_xy_commanded = (x, y)
            return result

    def park_safezone(self, owner: str = "web"):
        """LightBurn M2: laser-off, Z retract, then XY park inside keep-out.

        Explicit end-of-job only. M5 I is used for intermediate segments,
        and MUST NOT trigger a park. Never drive Z downward to park.
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
            # Positive Z is verified upward, and Z_max is currently 90mm.
            # Current height always wins, to avoid a dangerous downward park.
            z_target = max(self.position[2], self.clearance_mm,
                           0.0 if self.surface_z is None else
                           self.surface_z + self.probe_clearance_mm)
            if z_target > 90.0:
                raise RuntimeError("Z-Position außerhalb konfiguriertem Z-Hub")
            if not self.absolute_mode:
                self._exchange_locked("G90", timeout=8)
                self.absolute_mode = True
            self._exchange_locked(f"G0 Z{z_target:.3f} F600", timeout=45)
            self._exchange_locked("M400", timeout=45)
            self._exchange_locked("G0 X0.000 Y0.000 F9000", timeout=90)
            self._exchange_locked("M400", timeout=90)
            result = self._exchange_locked("M114", timeout=8)
            self.focused_this_job = False
            self.last_xy_commanded = (0.0, 0.0)
            self._light_effect_locked("done")
            if self.job_chime_enabled:
                self._play_stepper_chime_locked("done")
            return result

    def probe_workpiece(self, owner: str = "lightburn"):
        """Intercept LightBurn G30; use native Marlin probe, preserve bed Z0."""
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
            laser_x, laser_y, z = self.position
            # Some queued M114 reports are stale (for example X0/Y0 from
            # homing arrives after LightBurn has moved to X120/Y120).
            # Wait for a *verified* position matching the last commanded XY.
            if self.last_xy_commanded is not None:
                tx, ty = self.last_xy_commanded
                if abs(laser_x - tx) > 0.15 or abs(laser_y - ty) > 0.15:
                    for _ in range(5):
                        self._exchange_locked("M400", timeout=20)
                        self._exchange_locked("M114", timeout=8)
                        if self.position is not None:
                            laser_x, laser_y, z = self.position
                        if abs(laser_x - tx) <= 0.15 and abs(laser_y - ty) <= 0.15:
                            break
                    else:
                        raise RuntimeError(
                            f"G30 Positionsabgleich fehlgeschlagen: erwartet X{tx:.2f} "
                            f"Y{ty:.2f}, Marlin meldet X{laser_x:.2f} Y{laser_y:.2f}")
            # After M2 parks at X0/Y0, a repeated G30 should use the
            # previously successful measurement location, not the park.
            # Reuse only when the requested position is inside keep-out.
            if laser_x < self.safe_zone_xy_mm or laser_y < self.safe_zone_xy_mm:
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
                    PROBE_HEAD_MIN[0], PROBE_HEAD_MAX[0],
                    PROBE_HEAD_MIN[1], PROBE_HEAD_MAX[1]))
            if z < self.clearance_mm:
                self._exchange_locked(f"G0 Z{self.clearance_mm:.3f} F600", timeout=45)
                self._exchange_locked("M400", timeout=45)
            self._exchange_locked(f"G0 X{x:.3f} Y{y:.3f} F9000", timeout=60)
            self._exchange_locked("M400", timeout=60)
            self.last_xy_commanded = (x, y)
            start_z = max(z, self.clearance_mm)
            note = ""
            try:
                replies = self._exchange_locked("G30", timeout=120)
                contact = None
                for line in replies:
                    # Only the dedicated G30 result line is a measurement.
                    # The "X: Y: Z:" report that follows it is the position
                    # AFTER Marlin's post-probe raise, never the contact.
                    match = PROBE_RESULT_RE.search(line)
                    if match:
                        contact = float(match.group(1))
            except MarlinCommandError as exc:
                if "probing failed" not in str(exc).lower():
                    raise
                replies = list(exc.responses)
                contact = self._early_trigger_contact_locked(start_z)
                note = ("echo:LumaCut G30: Marlin meldete 'Probing Failed' "
                        "(Kontakt oberhalb Firmware-Grenze Z_CLEARANCE_MULTI_PROBE), "
                        f"Taster bestaetigt geschaltet bei Z{contact:.3f}")
                LOG.warning(note)
            if contact is None or not 0.0 <= contact <= 90.0:
                raise RuntimeError("Marlin G30 meldet keinen gültigen Z-Tastkontakt")
            self.surface_z = contact
            self.last_probe_laser_xy = (laser_x, laser_y)
            lift = max(self.clearance_mm, contact + self.probe_clearance_mm)
            self._exchange_locked(f"G0 Z{lift:.3f} F600", timeout=45)
            self._exchange_locked("M400", timeout=45)
            self._exchange_locked(f"G0 X{laser_x:.3f} Y{laser_y:.3f} F9000", timeout=60)
            self._exchange_locked("M400", timeout=60)
            self._exchange_locked("M114", timeout=8)
            self.last_xy_commanded = (laser_x, laser_y)
            self.focused_this_job = False
            self.fault = ""
            head = [f"echo:LumaCut workpiece Z:{contact:.3f}"] + ([note] if note else [])
            # Never forward Marlin's own Error line: LightBurn would abort
            # the job although the contact is measured and valid.
            return head + [line for line in replies
                           if not line.startswith(("Error:", "echo:Error:"))]

    def _early_trigger_contact_locked(self, start_z: float) -> float:
        """Evaluate a G30 that Marlin rejected as 'Probing Failed'.

        Marlin 2.1.2.9 (single probing, Probe::run_z_probe) reports failure
        in two different situations:
          * no trigger: the head reached Z_PROBE_LOW_POINT (-2 mm), switch open
          * triggered early: contact above -offset.z + Z_CLEARANCE_MULTI_PROBE
            (5 mm in the stock example config, 16 mm in the LumaCut build).
        In the second case Marlin has stopped the stepper at the trigger and
        set current_position from the stepper counts; nothing raises the head
        afterwards (fixed probe, no stow move). M114 therefore reports the
        exact contact height and M119 still reads the pressed switch.
        Accept only that physically confirmed case.
        """
        self._exchange_locked("M400", timeout=20)
        self.position = None
        self._exchange_locked("M114", timeout=8)
        if self.position is None:
            raise RuntimeError("G30 fehlgeschlagen und Kontakthöhe nicht lesbar (M114)")
        stop_z = self.position[2]
        endstops = self._exchange_locked("M119", timeout=8)
        pressed = any(re.match(r"^\s*z_(?:min|probe)\s*:\s*TRIGGERED", line, re.IGNORECASE)
                      for line in endstops)
        if not pressed:
            raise RuntimeError(
                f"G30 ohne Tasterkontakt bis Z{stop_z:.2f}: kein Material unter dem "
                "Taster oder X/Y-Tasterversatz falsch")
        if stop_z >= start_z - 0.3:
            raise RuntimeError(
                f"Z-Taster war schon beim G30-Start (Z{start_z:.2f}) gedrückt: "
                "Taster klemmt/Verdrahtung prüfen, Material zu hoch für Z-Rückzug")
        if stop_z < 0.0:
            raise RuntimeError(f"G30-Kontakt Z{stop_z:.2f} unter Maschinenboden: Z-Referenz prüfen")
        return stop_z

    def _probe_head_ok(self, x: float, y: float) -> bool:
        return (PROBE_HEAD_MIN[0] <= x <= PROBE_HEAD_MAX[0] and
                PROBE_HEAD_MIN[1] <= y <= PROBE_HEAD_MAX[1])

    def probe_reachable(self, x: float, y: float) -> bool:
        """True when the switch can probe laser point X/Y (head = point - offset)."""
        if self.probe_xy_offset_mm is None:
            return False
        dx, dy = self.probe_xy_offset_mm
        return self._probe_head_ok(x - dx, y - dy)

    def _probe_here_locked(self, start_z: float) -> float:
        """G30 E0 at the current head XY: contact Z, the switch stays deployed.

        A plain G30 stows the fixed probe afterwards, so the next G30 deploys
        it again and Marlin first raises to Z_CLEARANCE_BETWEEN_PROBES (16 mm)
        before it descends. E0 skips the stow; probe_surface() stows once
        with M402 at the end. One measurement per point (no MULTIPLE_PROBING).
        """
        contact = None
        try:
            for line in self._exchange_locked("G30 E0", timeout=120):
                match = PROBE_RESULT_RE.search(line)
                if match:
                    contact = float(match.group(1))
        except MarlinCommandError as exc:
            if "probing failed" not in str(exc).lower():
                raise
            contact = self._early_trigger_contact_locked(start_z)
        if contact is None or not 0.0 <= contact <= 90.0:
            raise RuntimeError("Marlin G30 meldet keinen gültigen Z-Tastkontakt")
        return contact

    def probe_surface(self, groups, owner: str = "job", progress=None,
                      should_stop=None, hop_mm: float = PROBE_HOP_MM):
        """Probe several laser X/Y points quickly; returns the contacts per group.

        ``groups`` are lists of laser points, one list per motif area. Inside
        an area the head only hops to the highest contact of that area plus
        ``hop_mm``; between areas it travels at the Z clearance (unknown
        height there). The lowest point is probed once more at the end, so
        the measured surface (and with it the Z floor surface + 2 mm) is the
        lowest one: every focus height of the job is then allowed. Laser stays
        off; the switch is stowed (M402) and Z raised whatever happens.
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
                    return self._probe_here_locked(z)
                except (MarlinCommandError, RuntimeError, ValueError) as exc:
                    raise ProbeFailed(x, y, exc) from exc

            def lift(target):
                nonlocal z
                if z < target - 0.001:
                    self._exchange_locked(f"G0 Z{target:.3f} F600", timeout=45)
                    z = target

            def go(x, y):
                hx, hy = x - dx, y - dy
                self._exchange_locked(f"G0 X{hx:.3f} Y{hy:.3f} F9000", timeout=60)
                self.last_xy_commanded = (hx, hy)

            try:
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
                            lift(self.clearance_mm if tallest is None
                                 else max(self.clearance_mm, tallest + hop_mm))
                        go(x, y)
                        contact = contact_at(x, y)
                        values[gi][pi] = contact
                        highest = contact if highest is None else max(highest, contact)
                        tallest = highest if tallest is None else max(tallest, highest)
                        z = contact
                        lift(highest + hop_mm)
                        step_done()
                check_stop()
                gi, pi = min(((g, p) for g in range(len(groups)) for p in range(len(groups[g]))),
                             key=lambda gp: values[gp[0]][gp[1]])
                if gi != len(groups) - 1:
                    lift(max(self.clearance_mm, tallest + hop_mm))
                x, y = groups[gi][pi]
                go(x, y)
                low = values[gi][pi] + hop_mm
                if z > low + 0.001:
                    self._exchange_locked(f"G0 Z{low:.3f} F600", timeout=45)
                    z = low
                contact = contact_at(x, y)
                values[gi][pi] = contact
                z = contact
                step_done()
                self._stow_probe_locked()
                lift(max(self.clearance_mm, tallest + self.probe_clearance_mm))
                self._exchange_locked("M400", timeout=45)
                self._exchange_locked("M114", timeout=8)
                self.surface_z = min(v for g in values for v in g)
                self.last_probe_laser_xy = (x, y)
                self.focused_this_job = False
                self.fault = ""
                return values
            except Exception:
                if self.serial is not None:
                    try:
                        self._stow_probe_locked()
                    except Exception:
                        LOG.warning("M402 after failed probing not confirmed", exc_info=True)
                raise

    def _stow_probe_locked(self):
        """M402: stow the switch after G30 E0 (no Z move on a fixed probe)."""
        try:
            self._exchange_locked("M402", timeout=20)
        except MarlinCommandError:
            LOG.warning("M402 rejected by firmware")

    def clear_emergency(self):
        """Release the M112 latch once the SKR has demonstrably restarted.

        After M112 Marlin sits in kill() and answers nothing. A fresh M115
        reply with LumaCut identity therefore proves a reset/power cycle:
        the board is unhomed with laser PWM and the PC6 rail off.
        """
        with self.lock:
            if not self.emergency_latched:
                return "Kein Notstopp aktiv"
            if self.owner is not None:
                raise RuntimeError("Steuerung belegt: " + self.owner)
            self._close_locked()
            self.emergency_latched = False
            try:
                self.ensure_ready()
            except Exception as exc:
                self.emergency_latched = True
                raise RuntimeError("SKR antwortet noch nicht: Reset-Taste am SKR drücken "
                                   "oder 24 V und USB kurz trennen (" + str(exc)[:80] + ")")
            self.fault = ""
            return "Notstopp quittiert: SKR neu gestartet, bitte neu referenzieren"

    def flash_firmware(self, image: bytes, settle_timeout: float = 120.0,
                       boot_wait: float = 8.0, poll: float = 3.0):
        """Write firmware.bin to the SKR SD over USB, reboot it, verify M115.

        Runs for minutes: call from a worker thread. Ownership 'firmware'
        keeps LightBurn, jobs and the heartbeat away for the whole update.
        """
        from .firmware_flash import BinaryUploader, TARGET_NAME, validate_image
        info = validate_image(image)
        expected = info["build"]
        with self.lock:
            if self.owner is not None:
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity or self.emergency_latched:
                raise RuntimeError("SKR nicht bereit oder Notstopp aktiv")
            if not self.cap_binary_transfer:
                raise RuntimeError(
                    "Aktuelle SKR-Firmware kann keine Dateien empfangen "
                    "(Cap:BINARY_FILE_TRANSFER:0): einmalig per SD-Karte flashen")
            self.owner = "firmware"
            previous = self.identity
            self.firmware = {"state": "uploading", "progress": 0,
                             "message": "Laser aus, SD-Karte prüfen"}
        try:
            with self.lock:
                self._exchange_locked("M5 I", timeout=8)
                self._exchange_locked("M400", timeout=60)
                # PC6 switches the laser module's 24 V rail: off before reset.
                self._exchange_locked("M107 P0", timeout=8)
                self._exchange_locked("M9", timeout=8)
                self.laser_enabled = False
                self.fan_power = False
                self.lights = self.exhaust = False
                media = self._exchange_locked("M21", timeout=15)
                if not any("SD card ok" in line for line in media):
                    raise RuntimeError("Keine SD-Karte im SKR erkannt (M21): "
                                       "microSD (FAT32) dauerhaft im SKR stecken lassen")
                try:
                    self._exchange_locked("M30 " + TARGET_NAME, timeout=15)
                except MarlinCommandError:
                    pass  # no previous firmware.bin on the card
                self.state = "Busy"
                self.serial.reset_input_buffer()
                port = self.serial
            # Outside the lock so /api/status stays responsive; the
            # 'firmware' owner already keeps every other sender out.
            uploader = BinaryUploader(port, log=self.lines.append)

            def progress(done, total):
                self.firmware.update(progress=round(100 * done / total),
                                     message=f"Übertrage {done // 1024} / {total // 1024} KB")
            uploader.upload(TARGET_NAME, image, progress)
            with self.lock:
                self.firmware.update(state="rebooting", progress=100,
                                     message="SKR startet neu, Bootloader flasht")
                # M997 reboots immediately: no 'ok' will follow.
                self.serial.write(b"M997\n")
                self.serial.flush()
                time.sleep(0.5)
                self._close_locked("Firmware-Update: SKR startet neu")
            deadline = time.monotonic() + settle_timeout
            time.sleep(boot_wait)  # bootloader flashes ~145 KB, USB is gone meanwhile
            last_error = ""
            while time.monotonic() < deadline:
                try:
                    self.ensure_ready(owner="firmware")
                    break
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(poll)
            else:
                raise RuntimeError("SKR nach dem Flashen nicht wieder erreichbar: " + last_error[:120])
            with self.lock:
                running = self.identity
            if expected and f"({expected})" not in running:
                raise RuntimeError(
                    f"SKR läuft nicht mit dem neuen Build ({expected}); "
                    "Bootloader hat die Datei nicht übernommen. Meldung: " + running[:120])
            if not expected and running == previous:
                raise RuntimeError("SKR meldet unveränderte Firmware nach dem Flashen")
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

    def status(self):
        with self.lock:
            return {
                "connected": self.serial is not None and bool(self.identity),
                "state": self.state, "owner": self.owner or "Frei",
                "identity": self.identity, "homed": self.homed,
                "z_homed": self.z_homed, "z_probe_supported": self.cap_z_probe, "emergency_latched": self.emergency_latched,
                "firmware_upload_supported": self.cap_binary_transfer,
                "firmware_update": dict(self.firmware),
                "homing_verified": self.homing_verified,
                "position": self.position, "fault": self.fault,
                "lights": self.lights, "exhaust": self.exhaust,
                "light_brightness": int(round(self.light_pct)), "light_dimmable": self.light_pwm,
                "light_effects": self.light_effects,
                "laser_armed": self.laser_enabled,
                "laser_cooling_fan_on": self.fan_power,
                "workpiece_surface_z": self.surface_z,
                "safe_zone_xy_mm": self.safe_zone_xy_mm,
                "probe_xy_offset_mm": self.probe_xy_offset_mm,
                "cutting_bounds": {"x_min":self.safe_zone_xy_mm,
                                   "y_min":self.safe_zone_xy_mm,
                                   "x_max":390.0, "y_max":370.0},
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

    def emergency_stop(self):
        # Emergency parser can accept M112 during long G-code commands.
        # A hardware E-Stop / power interlock remains essential.
        # Do not acquire the long-running command lock: a streaming G28
        # or G1 may be awaiting 'ok'. Marlin's EMERGENCY_PARSER accepts M112
        # on the input stream while a move is underway.
        serial_port = self.serial
        if serial_port is None:
            self.emergency_latched = True
            self.homed = False
            self.fault = "Software-Notstopp NICHT übertragen: USB getrennt, physischen Not-Aus benutzen"
            raise ConnectionError(self.fault)
        if serial_port is not None:
            try:
                serial_port.write(b"M112\n")
                self.fault = "M112 ausgelöst: SKR stromlos schalten und prüfen"
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
            # microcontroller with a finite Marlin RX/command queue.
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
                                # LightBurn's Marlin-flavor initialization:
                                # G00 is a modal rapid with no destination;
                                # G17 and G40 don't change our XY laser
                                # trajectory. Send real G21 to Marlin and
                                # return its genuine ACK.
                                lines = self.command("G21", owner="lightburn", timeout=15)
                            elif normalized == "G54":
                                # This controller uses the default frame only.
                                # Synchronize against Marlin (actual ACK),
                                # without pretending to support G55+ offsets.
                                lines = self.command("M400", owner="lightburn", timeout=15)
                            elif normalized == "M2":
                                lines = self.park_safezone(owner="lightburn")
                            elif normalized == "G30":
                                lines = self.probe_workpiece(owner="lightburn")
                            elif normalized.startswith("G28"):
                                if normalized != "G28":
                                    raise ValueError("G28 nur ohne Achsen über Pi erlaubt")
                                lines = self.safe_home(owner="lightburn")
                            else:
                                lines = self.command(cmd, owner="lightburn", timeout=150.0)
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
            LOG.warning("LightBurn Marlin connection lost", exc_info=True)
        finally:
            # Marlin may still be in continuous inline laser mode if a Wi-Fi
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
