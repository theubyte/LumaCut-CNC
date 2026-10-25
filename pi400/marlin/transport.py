"""Native Marlin USB transport and exclusive LightBurn/TCP gateway.

No GRBL identity spoofing, no '?'/$-commands, no blind line flooding.
One acknowledged Marlin G-code command is in flight at a time.
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
POSITION_RE = re.compile(
    r"(?:^|\s)X:([-+]?\d+(?:\.\d+)?)\s+Y:([-+]?\d+(?:\.\d+)?)\s+Z:([-+]?\d+(?:\.\d+)?)")
WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
COMMENT = re.compile(r"\([^()]*\)")
READ_ONLY = frozenset({"M105", "M114", "M115", "M119", "M503", "M400"})


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
        self.absolute_mode = True
        self.focused_this_job = False
        self.fan_off_at = None
        self.lights = False
        self.exhaust = False
        self.client = None
        self.guard = MarlinLaserGuard()
        self.last_seen = 0.0

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
        self.state = "Disconnected"
        self.homed = False
        self.z_homed = False
        self.surface_z = None
        self.focused_this_job = False
        self.laser_enabled = False
        self.guard = MarlinLaserGuard()
        self.identity = ""
        self.cap_z_probe = None
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

    def _exchange_locked(self, cmd: str, timeout: float = 15.0):
        if self.serial is None:
            raise ConnectionError("SKR USB nicht verbunden")
        self.state = "Busy"
        responses = []
        self.serial.write((cmd + "\n").encode("ascii"))
        deadline = time.monotonic() + timeout
        while True:
            line = self._read_line_locked(deadline)
            responses.append(line)
            lower = line.lower()
            if line.startswith(("Error:", "echo:Error:", "Resend:", "rs ")):
                self.serial_errors += 1
                self.fault = "Marlin: " + line[:150]
                raise RuntimeError(self.fault)
            if lower.startswith("ok"):
                self.commands += 1
                self.state = "Idle"
                return responses

    def ensure_ready(self):
        with self.lock:
            if self.emergency_latched:
                raise RuntimeError("M112-Notstopp verriegelt – Hardware/USB prüfen und Dienst kontrolliert neu starten")
            if self.serial is not None and self.identity:
                return
            if self.owner is not None:
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
                self._exchange_locked("M5 I", timeout=6.0)
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
        self._exchange_locked("M400", timeout=20)
        self._exchange_locked("M114", timeout=10)
        if self.position is None:
            raise RuntimeError("Keine gültige aktuelle Z-Position")
        target = coords["Z"] if self.absolute_mode else self.position[2] + coords["Z"]
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
        """
        if not re.match(r"^G0?1(?:\s|$)", cmd) or not self.laser_enabled:
            return
        coords = {letter:float(value) for letter,value in WORD.findall(cmd)}
        if "S" in coords and coords["S"] <= 0:
            return
        # An inline G1 lacking S may preserve nonzero cutting power.
        self._exchange_locked("M400", timeout=20)
        self._exchange_locked("M114", timeout=10)
        if self.position is None:
            raise RuntimeError("XY-Sicherheitszone: Position nicht bestimmbar")
        px, py = self.position[:2]
        tx = (coords["X"] if self.absolute_mode else px + coords.get("X", 0.0)) if "X" in coords else px
        ty = (coords["Y"] if self.absolute_mode else py + coords.get("Y", 0.0)) if "Y" in coords else py
        limit = self.safe_zone_xy_mm
        if min(px,py,tx,ty) < limit - 0.0001:
            raise ValueError(
                f"30mm-Homing-Sperrzone: Schnitt nur ab X={limit:g} "
                f"und Y={limit:g} mm; Start X{px:.2f} Y{py:.2f}, "
                f"Ziel X{tx:.2f} Y{ty:.2f}")

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
                    return self._exchange_locked(normalized, timeout)
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
            if use_guard:
                normalized = self.guard.check(normalized, self.homing_verified)
            if not normalized:
                return []
            if normalized.startswith(("G0 ", "G1 ")) and "Z" in normalized and self.surface_z is None:
                raise RuntimeError("Keine Werkstückhöhe bekannt; keine Z-Fahrt über LightBurn freigeben")
            if normalized == "M3 I" and self.surface_z is None:
                raise RuntimeError("Werkstückkontakt fehlt: Z-Taster auf Material referenzieren")
            motion = re.match(r"^G0?[0123](?:\s|$)", normalized) is not None
            if (motion or normalized == "M3 I") and not self.homed:
                raise RuntimeError("Maschine nicht referenziert: in LightBurn zuerst Home (G28) ausfuehren; danach G30 fuer Werkstueckfokus")
            try:
                self._z_move_guard_locked(normalized)
                self._xy_cut_guard_locked(normalized)
                if normalized == "M3 I":
                    # Independently power cooling fan before laser PWM mode.
                    # PC6 is FAN0/M106, not laser-enable.
                    self._exchange_locked("M106 P0 S255", timeout=8)
                    self.fan_power = True
                    self.fan_off_at = None
                # Focus on first powered G1, not while traversing XY.
                if (re.match(r"^G0?1(?:\s|$)",normalized) and
                    any(k == "S" and float(v) > 0 for k,v in WORD.findall(normalized)) and
                    self.laser_enabled and not self.focused_this_job):
                    self._focus_before_cut_locked()
                reply = self._exchange_locked(normalized, timeout)
                # Remember the workpiece target sent by LightBurn even if
                # asynchronous Marlin M114 reports arrive out of order.
                if (re.match(r"^G0?[01](?:\s|$)", normalized)
                        and self.absolute_mode):
                    coords = {k: float(v) for k, v in WORD.findall(normalized)}
                    if "X" in coords or "Y" in coords:
                        if "X" in coords and "Y" in coords:
                            self.last_xy_commanded = (coords["X"], coords["Y"])
                        elif self.last_xy_commanded is not None:
                            self.last_xy_commanded = (
                                coords.get("X", self.last_xy_commanded[0]),
                                coords.get("Y", self.last_xy_commanded[1]))
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
                    self.lights = self.exhaust = False
                return reply
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

    def safe_home(self, owner: str = "web", clearance_mm: float | None = None,
                  probe_contact_confirmed: bool = False):
        """LightBurn G28: home XY first into EMPTY L-shaped 30mm bed zone.

        This explicitly relies on the operator keeping the X0/Y0 strips clear
        of any material, and the physical head/probe travel being collision-free.
        Unlike the old routine, it never attempts Z before XY are referenced.
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
                        f"G0 Z{clearance:.2f} F600", "G90", "M400"]
            if self.homing_chime_enabled:
                # K1-style stepper sound: longer, reversible X strokes
                # let the motion planner actually reach the commanded step
                # frequency. 0.8mm strokes were inaudible on quiet TMC2209.
                # All strokes stay within the empty X=0..8mm home strip;
                # no PWM / no Z / no residual position shift.
                commands.extend([
                    "G91",
                    "G1 X8 F1200", "G1 X-8 F1200", "M400",
                    "G1 X8 F1600", "G1 X-8 F1600", "M400",
                    "G90",
                ])
            commands.append("M114")
            result = []
            try:
                for cmd in commands:
                    result = self._exchange_locked(cmd, timeout=150 if "G28" in cmd else 35)
                    if cmd == "G28 Z":
                        self.z_homed = True
                        # G28 Z is a BED / MACHINE origin, NEVER workpiece Z.
                        self.surface_z = None
                self.homed = True
                self.guard = MarlinLaserGuard()
                self.laser_enabled = False
                if self.fan_power:
                    self.fan_off_at = time.monotonic() + self.fan_cooldown_s
                # One upstream G28 must receive exactly one ACK. Sending
                # internal ACKs would corrupt LightBurn flow control.
                return result
            except Exception as exc:
                self._close_locked("Referenzfahrt fehlgeschlagen: " + str(exc))
                raise
            finally:
                self.owner = previous_owner

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
            if not (self.safe_zone_xy_mm <= x <= 390 and
                    self.safe_zone_xy_mm <= y <= 370):
                raise ValueError("Werkstück-Abtastpunkt außerhalb X30..390/Y30..370")
            if z < self.clearance_mm:
                self._exchange_locked(f"G0 Z{self.clearance_mm:.3f} F600", timeout=45)
                self._exchange_locked("M400", timeout=45)
            self._exchange_locked(f"G0 X{x:.3f} Y{y:.3f} F9000", timeout=60)
            self._exchange_locked("M400", timeout=60)
            replies = self._exchange_locked("G30", timeout=120)
            contact = None
            for line in replies:
                match = re.search(
                    r"\bBed\s+X:\s*[-+]?\d+(?:\.\d+)?\s+Y:\s*[-+]?\d+(?:\.\d+)?\s+Z:\s*([-+]?\d+(?:\.\d+)?)",
                    line, re.IGNORECASE)
                if match:
                    contact = float(match.group(1))
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
            self.focused_this_job = False
            return [f"echo:LumaCut workpiece Z:{contact:.3f}"] + replies

    def status(self):
        with self.lock:
            return {
                "connected": self.serial is not None and bool(self.identity),
                "state": self.state, "owner": self.owner or "Frei",
                "identity": self.identity, "homed": self.homed,
                "z_homed": self.z_homed, "z_probe_supported": self.cap_z_probe, "emergency_latched": self.emergency_latched,
                "homing_verified": self.homing_verified,
                "position": self.position, "fault": self.fault,
                "lights": self.lights, "exhaust": self.exhaust,
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
                            # Don't fake 'ok' after rejecting a command.
                            return
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
