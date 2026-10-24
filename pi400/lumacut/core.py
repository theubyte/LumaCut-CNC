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
        self.lightburn_enabled = True
        self.owner = None  # host, job, local
        self.state = "Disconnected"
        self.position = None
        self.settings = {}
        self.last_status = 0.0
        self.homed = False
        self.last_error = ""
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
        if self.owner == "host":
            self.owner = None

    def disconnect_host(self):
        with self.cond:
            if self.owner == "host" and self.state in ("Run", "Jog"):
                self._send_locked(b"!")  # feed hold on dropped stream
            self._disconnect_host_locked()

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
            # Host status requests are independently tracked. The unsolicited
            # dashboard polls remain internal, preventing console spam.
            if self.host is not None:
                if self.host_pending > 0:
                    self.host_pending -= 1
                    return True
                self.suppressed_reports += 1
            return False
        match = SETTING.match(line)
        if match:
            self.settings[int(match.group(1))] = float(match.group(2))
        if line.startswith("ALARM:"):
            self.state = "Alarm"
            self.homed = False
            self.last_error = line
        if line.startswith("error:"):
            self.last_error = line
        self.lines.append(line)
        if line == "ok" or line.startswith("error:"):
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
                        self.replies.clear()
                        LOG.info("SKR connected at %s", self.port)
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
                    try:
                        if self.serial:
                            self.serial.close()
                    except Exception:
                        pass
                    self.serial = None
                    self.state = "Disconnected"
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
                "position": self.position,
                "status_age": round(age, 2) if age is not None else None,
                "settings": dict(self.settings),
                "recent": list(self.lines)[-16:],
                "last_error": self.last_error,
                "diagnostics": {
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

    def serve_host(self, client: socket.socket):
        client.settimeout(0.25)
        with self.cond:
            if (self.owner is not None or self.serial is None or
                    not self.lightburn_enabled or
                    self.state not in ("Idle", "Alarm", "Unknown") or
                    (self.maintenance_file and self.maintenance_file.exists())):
                client.sendall(b"error:9\r\n")
                client.close()
                return
            self.host = client
            self.host_pending = 0
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
                    self.host_pending = min(64, self.host_pending + data.count(b"?"))
                    if b"\x18" in data:
                        self.homed = False
                    self._send_locked(data)  # byte-exact G-code + realtime
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
