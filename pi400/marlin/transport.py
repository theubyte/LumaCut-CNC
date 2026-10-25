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
        if not re.match(r"^G0?[01](?:\\s|$)", cmd):
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
        minimum = self.surface_z + self.probe_clearance_mm
        if target < minimum - 0.0001:
            raise ValueError(
                f"Z-Sperre: Ziel {target:.3f} mm, Minimum {minimum:.3f} mm "
                "(2mm Tastabstand). Schneidtiefe begrenzen.")

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
        self._exchange_locked("G90", timeout=8)
        self.absolute_mode = True
        self._exchange_locked(f"G0 Z{goal:.3f} F360", timeout=20)
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
            if use_guard:
                normalized = self.guard.check(normalized, self.homing_verified)
            if not normalized:
                return []
            motion = re.match(r"^G0?[0123](?:\s|$)", normalized) is not None
            if (motion or normalized == "M3 I") and not self.homed:
                raise RuntimeError("SKR erst Z-sicher und vollständig referenzieren")
            try:
                self._z_move_guard_locked(normalized)
                if normalized == "M3 I":
                    # Independently power cooling fan before laser PWM mode.
                    # PC6 is FAN0/M106, not laser-enable.
                    self._exchange_locked("M106 P0 S255", timeout=8)
                    self.fan_power = True
                    self.fan_off_at = None
                # Focus on first powered G1, not while traversing XY.
                if (re.match(r"^G0?1(?:\\s|$)",normalized) and
                    any(k == "S" and float(v) > 0 for k,v in WORD.findall(normalized)) and
                    self.laser_enabled and not self.focused_this_job):
                    self._focus_before_cut_locked()
                reply = self._exchange_locked(normalized, timeout)
                if normalized == "G90":
                    self.absolute_mode = True
                elif normalized == "G91":
                    self.absolute_mode = False
                if normalized.startswith("M3 I"):
                    self.laser_enabled = True  # PWM stays at zero until G1 S
                    self.focused_this_job = False
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

    def safe_home(self, owner: str = "web", clearance_mm: float | None = None):
        """Execute fail-closed laser-off Z-first homing as one exclusive transaction.

        Do not run generic Marlin G28. Verify switch polarity, positive-Z
        retract and available Z travel with disconnected laser first.
        """
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if not self.homing_verified:
                raise PermissionError("Mechanik/Z-Endschalter nicht verifiziert")
            if self.serial is None or not self.identity or self.emergency_latched:
                raise ConnectionError("Marlin USB nicht bereit oder Notstopp verriegelt")
            clearance = self.clearance_mm if clearance_mm is None else clearance_mm
            if not isinstance(clearance, (int, float)) or not 0.5 <= clearance <= 50:
                raise ValueError("Unzulässiger Z-Sicherheitsabstand")
            previous_owner = self.owner
            self.owner = owner
            self.homed = False
            self.z_homed = False
            self.surface_z = None
            self.focused_this_job = False
            commands = ("M5 I", "G28 Z", "M400",
                        "G91", f"G0 Z{clearance:.2f} F360", "G90",
                        "G28 X Y", "M400", "M114")
            result = []
            try:
                for cmd in commands:
                    result = self._exchange_locked(cmd, timeout=150 if "G28" in cmd else 35)
                    if cmd == "G28 Z":
                        self.z_homed = True
                self.homed = True
                self.guard = MarlinLaserGuard()
                self.laser_enabled = False
                if self.fan_power:
                    self.fan_off_at = time.monotonic() + self.fan_cooldown_s
                # One upstream G28 must receive exactly one ACK. Sending
                # nine internal ACKs would corrupt LightBurn flow control.
                return result
            except Exception as exc:
                self._close_locked("Referenzfahrt fehlgeschlagen: " + str(exc))
                raise
            finally:
                self.owner = previous_owner

    def status(self):
        with self.lock:
            return {
                "connected": self.serial is not None and bool(self.identity),
                "state": self.state, "owner": self.owner or "Frei",
                "identity": self.identity, "homed": self.homed,
                "z_homed": self.z_homed, "emergency_latched": self.emergency_latched,
                "homing_verified": self.homing_verified,
                "position": self.position, "fault": self.fault,
                "lights": self.lights, "exhaust": self.exhaust,
                "laser_armed": self.laser_enabled,
                "laser_cooling_fan_on": self.fan_power,
                "workpiece_surface_z": self.surface_z,
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
                client.sendall(b"Error:LumaCut Marlin gateway busy or not ready\r\n")
                client.close()
                return
            self.owner = "lightburn"
            self.lightburn_clients += 1
            self.client = client
            self.guard = MarlinLaserGuard()
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
                            elif normalized.startswith("G28"):
                                if normalized != "G28":
                                    raise ValueError("G28 nur ohne Achsen über Pi erlaubt")
                                lines = self.safe_home(owner="lightburn")
                            else:
                                lines = self.command(cmd, owner="lightburn", timeout=150.0)
                            for line in lines:
                                client.sendall((line + "\r\n").encode("ascii", "replace"))
                        except (ValueError, RuntimeError) as exc:
                            LOG.warning("Rejected LightBurn Marlin command: %s", exc)
                            client.sendall(("Error:LumaCut " + str(exc)[:130] +
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
