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
READ_ONLY = frozenset({"M114", "M115", "M119", "M503", "M400"})


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
        if any(x in cmd for x in ("M42", "M500", "M502", "M997", "M303", "M104", "M140")):
            raise ValueError("Hardware-/Druckerfunktion in Laserjobs gesperrt")
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
        if any(m in families for m in ("M112", "M410")):
            # Emergency command handled out-of-band by transport.
            return cmd
        if "M4" in families:
            raise ValueError("Marlin M4 I nutzt Vorschub statt S-Leistung: M3 I erforderlich")
        if "M3" in families:
            # Only M3 I without power safely selects Marlin continuous inline.
            other = {letter for letter, val in words if letter not in ("M", "I")}
            has_i = any(l == "I" for l, _ in words)
            if not has_i or other:
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
            if not homing_verified:
                raise ValueError("G28 erst nach verifizierter Endschalter-/Z-Richtung freigeben")
            if self.inline:
                raise ValueError("Vor G28 Laser mit M5 I deaktivieren")
        if any(m in families for m in ("G0", "G1", "G2", "G3")):
            if not homing_verified:
                raise ValueError("Fahrbewegung erst nach bestätigter Mechanik-Konfiguration freigeben")
            is_rapid = "G0" in families
            if is_rapid:
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
        self.homing_verified = False
        self.position = None
        self.fault = ""
        self.lines = deque(maxlen=80)
        self.commands = 0
        self.serial_errors = 0
        self.lightburn_clients = 0
        self.laser_enabled = False
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

    def command(self, cmd: str, owner: str = "web",
                timeout: float = 20.0, use_guard=True):
        with self.lock:
            if self.owner not in (None, owner):
                raise RuntimeError("Steuerung belegt: " + self.owner)
            if self.serial is None or not self.identity:
                raise ConnectionError("Marlin USB nicht bereit")
            normalized = normalize(cmd)
            if use_guard:
                normalized = self.guard.check(normalized, self.homing_verified)
            if not normalized:
                return []
            try:
                reply = self._exchange_locked(normalized, timeout)
                if normalized.startswith("G28"):
                    # A successful Z-only home never implies XYZ is homed.
                    parts = normalized.split()
                    if len(parts) == 1 or ("X" in parts and "Y" in parts):
                        self.homed = True
                    else:
                        self.homed = False
                if normalized.startswith("M3 I"):
                    self.laser_enabled = True  # PWM stays at zero until G1 S
                if normalized.startswith("M5"):
                    self.laser_enabled = False
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

    def status(self):
        with self.lock:
            return {
                "connected": self.serial is not None and bool(self.identity),
                "state": self.state, "owner": self.owner or "Frei",
                "identity": self.identity, "homed": self.homed,
                "homing_verified": self.homing_verified,
                "position": self.position, "fault": self.fault,
                "lights": self.lights, "exhaust": self.exhaust,
                "laser_armed": self.laser_enabled,
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
        if serial_port is not None:
            try:
                serial_port.write(b"M112\n")
                self.fault = "M112 ausgelöst: SKR stromlos schalten und prüfen"
                self.homed = False
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
            with self.lock:
                # Do NOT reset firmware during motion. Emergency parser M112
                # is only triggered by deliberate user action.
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
