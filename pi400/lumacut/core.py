"""Thread-safe GRBL USB controller and exclusive LightBurn TCP bridge.

One reader owns the serial receive stream. Internal telemetry '?' is never
forwarded to LightBurn. Only a status requested by the remote host is echoed.
All other native GRBL lines, including ok/error/alarm/$$, are preserved.
"""
from __future__ import annotations

import logging
import re
import socket
import threading
import time
from collections import deque
from pathlib import Path

from .laser_guard import LaserGuard

LOG = logging.getLogger(__name__)
STATUS = re.compile(r"^<([^|>]+)")
SETTING = re.compile(r"^\$(\d+)=([-+]?\d+(?:\.\d+)?)")
MACHINE_POS = re.compile(r"(?:^|\|)MPos:([-+\d.]+),([-+\d.]+),([-+\d.]+)")


class Controller:
    def __init__(self, port: str, baud: int = 115200, serial_factory=None):
        self.port, self.baud = port, baud
        self.maintenance_file = None
        self.serial_factory = serial_factory
        self.serial = None
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.running = False
        self.read_thread = None
        self.host = None
        self.host_pending = 0
        self.host_commands = deque(maxlen=32768)
        self.host_fragment = bytearray()
        self.host_overflow = False
        self.host_guard = LaserGuard()
        self.bootstrap_ready = False
        self.bootstrap_pending = 0
        self.lightburn_enabled = True
        self.owner = None  # host, job, local
        self.state = "Disconnected"
        self.position = None
        self.settings = {}
        self.last_status = 0.0
        self.homed = False
        self.identity = {"version": "", "firmware": "", "board": "", "driver": ""}
        self.extra_outputs = {"PC6": None}
        self.last_error = ""
        self.last_skr_error = ""
        self.skr_errors = 0
        self.last_bridge_rejection = ""
        self.bridge_rejections = 0
        self.replies = deque(maxlen=1024)
        self.lines = deque(maxlen=100)
        self.bytes_usb = 0
        self.bytes_host = 0
        self.suppressed_reports = 0
        self.faults = 0
        self.accessories = {"lights": False, "exhaust": False}
        self.last_accessory_toggle = 0.0
        self.last_poll = 0.0
        self.last_connect_attempt = 0.0

    def _open(self):
        if self.serial_factory:
            return self.serial_factory(self.port, self.baud, timeout=0.05)
        import serial
        return serial.Serial(self.port, self.baud, timeout=0.05, write_timeout=1,
                             exclusive=True)

    def start(self):
        with self.lock:
            self.running = True
        self.read_thread = threading.Thread(target=self._worker, name="grbl-usb",
                                            daemon=True)
        self.read_thread.start()

    def stop(self):
        with self.cond:
            self.running = False
            self._disconnect_host_locked()
            self.cond.notify_all()
        if self.read_thread:
            self.read_thread.join(timeout=3)
        with self.lock:
            if self.serial:
                self.serial.close()
                self.serial = None

    def _disconnect_host_locked(self):
        if self.host:
            try:
                self.host.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.host.close()
            except OSError:
                pass
        self.host = None
        self.host_pending = 0
        self.host_commands.clear()
        self.host_fragment.clear()
        self.host_overflow = False
        self.host_guard = LaserGuard()
        if self.owner == "host":
            self.owner = None

    def disconnect_host(self):
        with self.cond:
            try:
                if self.owner == "host" and self.state in ("Run", "Jog"):
                    self._send_locked(b"!")  # feed hold on dropped stream
            except (OSError, ConnectionError):
                LOG.warning("Unable to feed-hold after LightBurn disconnect", exc_info=True)
            finally:
                self._disconnect_host_locked()

    def _bridge_rejected_locked(self, reason: str, command: str = ""):
        """Synthetic rejections must never masquerade as SKR error:9.

        GRBL error:9 specifically means a controller alarm or jog lockout.
        Bridge rejections are therefore reported with a vendor MSG and
        error:20 (unsupported G-code) for a command that needs an ACK.
        """
        detail = reason[:160]
        self.bridge_rejections += 1
        self.last_bridge_rejection = detail
        LOG.warning("Pi LightBurn bridge rejection: %s command=%r", detail, command[:120])
        if self.host is not None:
            self.host.sendall(("[MSG:LumaCut bridge: " + detail +
                               "]\r\nerror:20\r\n").encode("ascii", "replace"))

    def _send_locked(self, data: bytes):
        if self.serial is None:
            raise ConnectionError("SKR USB nicht verbunden")
        self.serial.write(data)

    def _read_response(self, line: str):
        if line.startswith("<"):
            match = STATUS.match(line)
            if match:
                self.state = match.group(1).split(":")[0]
            pos = MACHINE_POS.search(line)
            if pos:
                self.position = [float(pos.group(i)) for i in (1, 2, 3)]
            accessory = ""
            if "|A:" in line:
                accessory = line.split("|A:", 1)[1].split("|", 1)[0].split(">", 1)[0]
            self.accessories["lights"] = "M" in accessory
            self.accessories["exhaust"] = "F" in accessory
            self.last_status = time.monotonic()
            # Wake local homing completion checks as soon as grblHAL
            # reports a fresh machine state. A $H 'ok' alone is not
            # sufficient proof that the previous <Home> report is stale.
            self.cond.notify_all()
            # Host status requests are independently tracked. The unsolicited
            # dashboard polls remain internal, preventing console spam.
            if self.host is not None:
                if self.host_pending > 0:
                    self.host_pending -= 1
                    return True
                self.suppressed_reports += 1
            return False
        for prefix, field in (("[VER:", "version"), ("[FIRMWARE:", "firmware"),
                              ("[BOARD:", "board"), ("[DRIVER:", "driver")):
            if line.startswith(prefix) and line.endswith("]"):
                self.identity[field] = line[len(prefix):-1]
                break
        if line.startswith("[LCIO:PC6=") and line.endswith("]"):
            pin_state = line[len("[LCIO:PC6="):-1]
            if pin_state in ("0", "1"):
                self.extra_outputs["PC6"] = int(pin_state)
        match = SETTING.match(line)
        if match:
            self.settings[int(match.group(1))] = float(match.group(2))
        if line.startswith("ALARM:"):
            self.state = "Alarm"
            self.homed = False
            self.last_error = line
        if line.startswith("error:"):
            self.last_error = line
            self.last_skr_error = line
            self.skr_errors += 1
            pending = self.host_commands[0] if self.host_commands else "local/bootstrap"
            LOG.warning("SKR native GRBL error: %s pending=%r state=%s",
                        line, pending[:140], self.state)
        self.lines.append(line)
        if line == "ok" or line.startswith("error:"):
            if self.bootstrap_pending > 0 and self.host is None:
                if line != "ok":
                    self.bootstrap_pending = 0
                    self.bootstrap_ready = False
                    self.last_error = "SKR-Initialisierung fehlgeschlagen: " + line
                else:
                    self.bootstrap_pending -= 1
                    if self.bootstrap_pending == 0:
                        identity_ok = (self.identity["firmware"] == "grblHAL" and
                                       "LumaCut SKR Mini MZ" in self.identity["board"] and
                                       "FAN1-LASER" in self.identity["board"])
                        settings_ok = {30, 32, 130, 131, 132}.issubset(self.settings)
                        self.bootstrap_ready = bool(identity_ok and settings_ok)
                        if not self.bootstrap_ready:
                            self.last_error = (
                                "USB Controller ohne FAN1-LASER Pinbelegung oder passt nicht zum LumaCut SKR "
                                "oder erforderliche $-Parameter fehlen")

            if self.host is not None and self.host_commands:
                sent = self.host_commands.popleft()
                if line == "ok":
                    if sent == "$H":
                        self.homed = True
                    if sent.startswith("$") and "=" in sent:
                        m = SETTING.match(sent)
                        if m:
                            self.settings[int(m.group(1))] = float(m.group(2))
                        if sent.startswith(("$3=", "$23=", "$130=", "$131=", "$132=")):
                            self.homed = False
            self.replies.append(line)
            self.cond.notify_all()
        return self.host is not None

    def _worker(self):
        buf = bytearray()
        while True:
            with self.lock:
                if not self.running:
                    break
                if self.serial is None and time.monotonic() - self.last_connect_attempt > 3:
                    self.last_connect_attempt = time.monotonic()
                    try:
                        self.serial = self._open()
                        self.state = "Unknown"
                        self.extra_outputs["PC6"] = None
                        self.replies.clear()
                        self.settings.clear()
                        self.identity = {"version": "", "firmware": "", "board": "", "driver": ""}
                        self.bootstrap_pending = 2
                        self.bootstrap_ready = False
                        self.last_error = ""
                        # USB CDC is the only control channel. Identify real
                        # grblHAL and read machine limits before allowing
                        # LightBurn streams or Pi motion commands.
                        time.sleep(0.3)
                        self._send_locked(b"$I\n" + bytes((36, 36, 10)))
                        LOG.info("SKR connected and init queries sent at %s", self.port)
                    except Exception as exc:
                        self.state = "Disconnected"
                        self.last_error = str(exc)[:150]
            try:
                if self.serial:
                    received = self.serial.read(256)
                    if received:
                        with self.cond:
                            self.bytes_usb += len(received)
                            for b in received:
                                if b in (10, 13):
                                    if buf:
                                        line = buf.decode("ascii", errors="replace")
                                        buf.clear()
                                        forward = self._read_response(line)
                                        if forward:
                                            try:
                                                self.host.sendall((line + "\r\n").encode())
                                            except OSError:
                                                self._disconnect_host_locked()
                                elif len(buf) < 4096:
                                    buf.append(b)
                                else:
                                    # Never acknowledge a corrupt overlong line.
                                    self.faults += 1
                                    buf.clear()
                    now = time.monotonic()
                    with self.lock:
                        if (self.host_pending == 0 and now - self.last_poll >=
                                (1.0 if self.host is not None else 0.5)):
                            self._send_locked(b"?")
                            self.last_poll = now
                else:
                    time.sleep(0.25)
            except Exception as exc:
                with self.cond:
                    LOG.warning("SKR serial error: %s", exc)
                    self.last_error = str(exc)[:150]
                    self.faults += 1
                    if self.host is not None:
                        self._disconnect_host_locked()
                    # Wake blocked G-code senders immediately on USB loss.
                    # Waiting for 30-second ACK deadlines leaves jobs stuck.
                    self.replies.clear()
                    self.replies.append("error:SKR-USB-disconnected")
                    self.cond.notify_all()
                    try:
                        if self.serial:
                            self.serial.close()
                    except Exception:
                        pass
                    self.serial = None
                    self.state = "Disconnected"
                    self.extra_outputs["PC6"] = None
                    self.bootstrap_ready = False
                    self.bootstrap_pending = 0
                    self.homed = False
                    buf.clear()

    def status(self):
        with self.lock:
            age = (time.monotonic() - self.last_status) if self.last_status else None
            return {
                "connected": self.serial is not None and age is not None and age < 5,
                "maintenance": bool(self.maintenance_file and self.maintenance_file.exists()),
                "accessories": dict(self.accessories),
                "state": self.state,
                "owner": self.owner or "Frei",
                "homed": self.homed,
                "identity": dict(self.identity),
                "bootstrap_ready": self.bootstrap_ready,
                "extra_outputs": dict(self.extra_outputs),
                "position": self.position,
                "status_age": round(age, 2) if age is not None else None,
                "settings": dict(self.settings),
                "recent": list(self.lines)[-16:],
                "last_error": self.last_error,
                "last_skr_error": self.last_skr_error,
                "last_bridge_rejection": self.last_bridge_rejection,
                "diagnostics": {
                    "bridge_rejections": self.bridge_rejections,
                    "skr_errors": self.skr_errors,
                    "usb_bytes": self.bytes_usb,
                    "host_bytes": self.bytes_host,
                    "suppressed_status": self.suppressed_reports,
                    "serial_faults": self.faults,
                },
            }

    def _acquire_local(self, owner="local"):
        if self.maintenance_file and self.maintenance_file.exists():
            raise RuntimeError("Pi-Softwareupdate: Maschinensteuerung gesperrt")
        if self.serial is None:
            raise ConnectionError("SKR USB nicht erreichbar")
        if self.owner not in (None, owner):
            raise RuntimeError("Steuerung belegt: " + self.owner)
        if not self.bootstrap_ready:
            raise ConnectionError("SKR-Initialisierung noch nicht abgeschlossen")
        self.owner = owner

    def command(self, cmd, timeout=10.0, owner="local"):
        if not isinstance(cmd, str) or not cmd.strip() or "\n" in cmd or "\r" in cmd:
            raise ValueError("Ungültiger GRBL-Befehl")
        with self.cond:
            self._acquire_local(owner)
            self.replies.clear()
            try:
                self._send_locked((cmd + "\n").encode("ascii"))
                deadline = time.monotonic() + timeout
                while not self.replies:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TimeoutError("Keine GRBL-Bestätigung: " + cmd)
                    self.cond.wait(timeout=min(left, 0.5))
                response = self.replies.popleft()
                if response == "ok" and cmd == "$H":
                    self.homed = True
                if cmd == "$X" or cmd == "\x18":
                    self.homed = False
                return response
            finally:
                if owner == "local":
                    self.owner = None

    def wait_for_idle_after_homing(self, timeout=15.0):
        """Wait for a *fresh* Idle status after the $H acknowledgment.

        The status poller owns the serial RX stream. Never race it by
        reading the serial port directly, and never weaken Home guards
        simply because a prior $H command returned 'ok'.
        """
        with self.cond:
            minimum_status_time = time.monotonic()
            deadline = minimum_status_time + timeout
            while True:
                if self.serial is None or not self.bootstrap_ready:
                    raise ConnectionError("SKR USB nach Referenzfahrt nicht bereit")
                if self.state in ("Alarm", "Door", "Sleep", "Check"):
                    self.homed = False
                    raise RuntimeError(
                        "Referenzfahrt konnte nicht abgeschlossen werden: " + self.state)
                if (self.state == "Idle" and
                        self.last_status >= minimum_status_time and self.homed):
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "SKR meldet nach $H noch " + self.state +
                        " statt Idle. Keine weitere Z-Bewegung ausgeführt.")
                self.cond.wait(timeout=min(remaining, 0.5))

    def command_batch(self, commands, timeout=10.0):
        with self.lock:
            self._acquire_local("job")
        try:
            responses = []
            for cmd in commands:
                if cmd.strip():
                    reply = self.command(cmd.strip(), timeout=timeout, owner="job")
                    responses.append(reply)
                    if reply != "ok":
                        break
            return responses
        finally:
            with self.lock:
                if self.owner == "job":
                    self.owner = None

    def realtime(self, char):
        if char not in (b"!", b"~", b"?", b"\x18", b"\xa0", b"\xa1"):
            raise ValueError("Invalid realtime command")
        with self.lock:
            self._send_locked(char)
            if char == b"\x18":
                self.homed = False

    @staticmethod
    def host_command_allowed(command: str) -> bool:
        """LightBurn may stream laser jobs but may not bypass service PIN control.

        The system-level $-settings and GPIO commands are the Pi Service
        Studio's responsibility. Ordinary $I, $$, $G, $H, $X, $J,
        G0/G1/G2/G3, M3/M4/M5 and standard job control stay available.
        """
        c = command.strip().upper()
        if c.startswith("$LC") or c in ("$PGM", "$RST", "$SLP"):
            return False
        if re.match(r"^\$\d+\s*=", c) or re.match(r"^\$N\d+\s*=", c):
            return False
        # Do not let unauthenticated LightBurn port 23 drive arbitrary I/O.
        if re.search(r"(?<![A-Z0-9])M6[2-8](?![0-9.])", c):
            return False
        return True

    def _forward_host_bytes_locked(self, data: bytes):
        """Parse newline-bounded G-code to enforce authorization safely.

        All GRBL realtime bytes bypass buffering. Only complete allowed
        ASCII lines reach the STM32. A rejected line produces exactly one
        error response and never enters the host->ACK correlation queue.
        """
        realtime = frozenset((ord("?"), ord("!"), ord("~"), 0x18,
                              0x85, 0x90, 0x91, 0x92,
                              0x93, 0x94, 0x95, 0x96,
                              0xA0, 0xA1))
        for byte in data:
            if byte in realtime:
                if byte == ord("?"):
                    self.host_pending = min(64, self.host_pending + 1)
                if byte == 0x18:
                    self.homed = False
                    self.host_commands.clear()
                    self.host_fragment.clear()
                    self.host_overflow = False
                    self.host_guard = LaserGuard()
                self._send_locked(bytes((byte,)))
            elif byte in (10, 13):
                if not self.host_fragment and not self.host_overflow:
                    continue  # Ignore empty LF after CR; avoid extra 'ok'.
                if self.host_overflow:
                    allowed = False
                    command = ""
                else:
                    command = self.host_fragment.decode("ascii", "replace").strip()
                    allowed = self.host_command_allowed(command)
                self.host_fragment.clear()
                self.host_overflow = False
                reason = None
                if not allowed:
                    reason = "blocked service command or malformed G-code"
                elif command:
                    if not self.bootstrap_ready:
                        reason = "SKR firmware bootstrap incomplete"
                    elif self.settings.get(32) != 1 and not command.startswith("$"):
                        reason = "SKR laser mode $32=1 is required"
                    elif not command.startswith("$"):
                        try:
                            self.host_guard.check(command)
                        except ValueError as exc:
                            reason = str(exc)
                if reason:
                    self._bridge_rejected_locked(reason, command)
                elif command:
                    self.host_commands.append(command)
                    self._send_locked((command + "\n").encode("ascii"))
            elif 32 <= byte <= 126:
                if len(self.host_fragment) < 240 and not self.host_overflow:
                    self.host_fragment.append(byte)
                else:
                    self.host_overflow = True
            else:
                # Invalid byte: reject the whole text line. Never truncate
                # dangerous, malformed or overlong commands into safe syntax.
                self.host_overflow = True

    def serve_host(self, client: socket.socket):
        client.settimeout(0.25)
        # Detect half-open LightBurn clients on Linux/Pi without dropping an
        # actively streaming socket. A second connection never steals a job.
        if hasattr(socket, "SO_KEEPALIVE") and hasattr(client, "setsockopt"):
            try:
                client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                for flag, value in (("TCP_KEEPIDLE", 15),
                                    ("TCP_KEEPINTVL", 5),
                                    ("TCP_KEEPCNT", 3)):
                    if hasattr(socket, flag):
                        client.setsockopt(socket.IPPROTO_TCP,
                                          getattr(socket, flag), value)
            except OSError:
                LOG.debug("TCP keepalive tuning unavailable", exc_info=True)
        with self.cond:
            reason = None
            if self.owner is not None:
                reason = "machine already owned by " + self.owner
            elif self.serial is None:
                reason = "SKR USB port disconnected"
            elif not self.bootstrap_ready:
                reason = "SKR not ready: check FAN1-LASER firmware revision and USB bootstrap"
            elif not self.lightburn_enabled:
                reason = "LightBurn TCP disabled in LumaCut"
            elif self.state not in ("Idle", "Alarm", "Unknown", "Hold"):
                reason = "machine not idle: " + self.state
            elif self.maintenance_file and self.maintenance_file.exists():
                reason = "Pi firmware update in progress"
            if reason is not None:
                self.bridge_rejections += 1
                self.last_bridge_rejection = reason
                LOG.warning("LightBurn TCP connection refused: %s", reason)
                try:
                    client.sendall(("[MSG:LumaCut bridge: " + reason +
                                    "]\r\n").encode("ascii", "replace"))
                except OSError:
                    pass
                client.close()
                return
            self.host = client
            self.host_pending = 0
            self.host_commands.clear()
            self.host_fragment.clear()
            self.host_overflow = False
            self.host_guard = LaserGuard()
            self.owner = "host"
            self.bytes_host = 0
        try:
            while self.running:
                try:
                    data = client.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                with self.lock:
                    if self.host is not client:
                        break
                    self.bytes_host += len(data)
                    self._forward_host_bytes_locked(data)
        except (OSError, ConnectionError):
            pass
        finally:
            self.disconnect_host()


def serve_lightburn(controller: Controller, bind: str, port: int, running):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((bind, port))
        server.listen(1)
        server.settimeout(1)
        LOG.info("GRBL TCP bridge listening %s:%s", bind, port)
        while running():
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            LOG.info("LightBurn connection from %s", addr)
            threading.Thread(target=controller.serve_host, args=(conn,),
                             name="lightburn-client", daemon=True).start()
