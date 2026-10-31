"""Stand-in controller: the original Atomstack board (ESP32, stock Grbl) behind
the Marlin gateway.

Emergency use since 31.10.2026, when the SKR Mini MZ died: the Atomstack
"Laser 32-A5 V1.0" board drives X, Y and the laser but has no Z driver.
The head is fixed by hand at focus height (Z motor unplugged), so Z here is
only a number: Z moves are acknowledged and remembered, G28 Z sets it to 0
and G30 "touches" at the height the probe would have measured on the chosen
material (surface_hint). Everything the Pi checks around Z keeps working,
nothing moves.

GrblMarlinBridge looks like a pyserial port to MarlinTransport: it takes the
Marlin lines the gateway writes and answers like LumaCut Marlin, one "ok" per
line. Moves and laser go to Grbl:

  Marlin                      Grbl
  M3 I / M5 I                 M4 S0 (dynamic laser mode, $32=1) / M5
  G0/G1 X Y F S(0..255)       G0/G1 X Y F S(0..$30), Z dropped
  G28 X Y                     $H, then G10 L20 P1 X0 Y0 (home = 0/0)
  M400, M114, M119            wait for Idle / status report "?"
  M112                        feed hold "!" + soft reset Ctrl-X

Grbl sees the home corner as 0/0 like Marlin. Marlin coordinates grow away
from the switches; Grbl's grow towards +, so an axis that homes to + ($23
bit clear) is mirrored (and G2/G3 swap when exactly one axis is mirrored).
"""
from __future__ import annotations

import glob
import logging
import os
import queue
import re
import threading
import time

LOG = logging.getLogger("lumacut.grbl")

WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
STATUS = re.compile(r"^<([A-Za-z]+)[^|>]*(.*)>$")
SETTING = re.compile(r"^\$(\d+)=([-+]?\d+(?:\.\d+)?)")
# Grbl's serial receive buffer (127 usable bytes on classic Grbl).
RX_BUFFER = 120
MARLIN_S_MAX = 255.0
IDENTITY = ("FIRMWARE_NAME:Marlin 2.1.2.9 (LumaCut Grbl-Bridge) "
            "SOURCE_CODE_URL:github.com/theubyte/LumaCut-CNC PROTOCOL_VERSION:1.0 "
            "MACHINE_TYPE:LumaCut CNC Atomstack-Grbl EXTRUDER_COUNT:0")
# Marlin commands that only tune the SKR (speed caps, steps, probe offset,
# idle hold, lights, tones, fan): nothing to do on the Atomstack board.
NO_OP = ("M92", "M201", "M203", "M204", "M205", "M84", "M18", "M17", "M851",
         "M355", "M300", "M106", "M107", "M42", "M401", "M402", "M500", "M501",
         "M117", "M118", "M150", "M593", "M7", "G17", "G40", "G54", "M2", "M30")


def grbl_ports() -> list[str]:
    """USB serial ports of a CH340 (the Atomstack board's USB chip)."""
    found = sorted(glob.glob("/dev/serial/by-id/*1a86*") + glob.glob("/dev/serial/by-id/*CH340*"))
    return found or sorted(glob.glob("/dev/ttyUSB*"))


def open_controller(port: str, baud: int, timeout: float = 0.1, surface_hint=None):
    """The SKR at the configured port, else the Atomstack board through the bridge."""
    if port and os.path.exists(port) and "ttyUSB" not in port and "1a86" not in port:
        import serial
        return serial.Serial(port, baud, timeout=timeout, write_timeout=1.0, exclusive=True)
    ports = grbl_ports()
    if not ports:
        raise ConnectionError("Kein Controller per USB: weder SKR (%s) noch Atomstack-Board (CH340)" % port)
    return GrblMarlinBridge(ports[0], surface_hint=surface_hint)


class GrblMarlinBridge:
    def __init__(self, port: str, baud: int = 115200, surface_hint=None, serial_port=None):
        if serial_port is None:
            import serial
            # DTR/RTS stay released: on the ESP32 board they pull EN/GPIO0
            # and would hold the chip in reset or the boot loader.
            serial_port = serial.Serial()
            serial_port.port, serial_port.baudrate = port, baud
            serial_port.timeout, serial_port.write_timeout = 0.05, 1.0
            serial_port.dtr = serial_port.rts = False
            serial_port.exclusive = True
            serial_port.open()
        self.port = port
        self.ser = serial_port
        self.surface_hint = surface_hint
        self.out: "queue.Queue[str]" = queue.Queue()
        self.inbox: "queue.Queue[str]" = queue.Queue()
        self.pending: list[int] = []           # byte sizes of lines in Grbl's buffer
        self.cond = threading.Condition()
        self.settings: dict[int, float] = {}
        self.state = "Unknown"
        self.mpos = [0.0, 0.0]
        self.wco = [0.0, 0.0]
        self.pins = ""
        self.status_seq = 0
        self.z = 0.0
        self.relative = False
        self.closed = False
        self.banner = ""
        self.private_active = False
        self.private_reply = None
        self.private_lines: list[str] = []
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        try:
            self._startup()
        except Exception:
            self.close()
            raise
        self.worker = threading.Thread(target=self._work_loop, daemon=True)
        self.worker.start()

    # ---- pyserial surface used by MarlinTransport -------------------------

    def write(self, data: bytes):
        text = data.decode("ascii", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("M112"):
                self._emergency()
            elif line:
                self.inbox.put(line)
        return len(data)

    def readline(self) -> bytes:
        try:
            return (self.out.get(timeout=0.1) + "\n").encode()
        except queue.Empty:
            return b""

    def reset_input_buffer(self):
        while not self.out.empty():
            try:
                self.out.get_nowait()
            except queue.Empty:
                break

    def close(self):
        self.closed = True
        try:
            self.ser.close()
        except Exception:
            pass

    # ---- Grbl side --------------------------------------------------------

    def _raw(self, data: bytes):
        self.ser.write(data)

    def _read_loop(self):
        buf = b""
        while not self.closed:
            try:
                chunk = self.ser.read(256)
            except Exception as exc:
                LOG.warning("Grbl serial read failed: %s", exc)
                self.closed = True
                with self.cond:
                    self.cond.notify_all()
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self._on_line(raw.decode("ascii", errors="replace").strip())

    def _on_line(self, line: str):
        if not line:
            return
        with self.cond:
            if self.private_active and not self.pending and (
                    line == "ok" or line.startswith("error:")):
                self.private_reply = line
            elif line == "ok":
                if self.pending:
                    self.pending.pop(0)
                    self.out.put("ok")
            elif line.startswith("error:"):
                if self.pending:
                    self.pending.pop(0)
                    self.out.put("Error:Grbl " + line)
                    self.out.put("ok")
            elif line.startswith("ALARM:"):
                self.state = "Alarm"
                self.out.put("Error:Grbl " + line + " (Grbl gesperrt)")
                # Grbl drops its buffer on an alarm: answer the lost lines.
                for _ in self.pending:
                    self.out.put("ok")
                self.pending.clear()
            elif line.startswith("<"):
                self._on_status(line)
            elif SETTING.match(line):
                m = SETTING.match(line)
                self.settings[int(m.group(1))] = float(m.group(2))
            elif line.lower().startswith("grbl"):
                self.banner = line
            elif self.private_active:
                self.private_lines.append(line)
            self.cond.notify_all()
        LOG.debug("grbl< %s", line)

    def _on_status(self, line: str):
        m = STATUS.match(line)
        if not m:
            return
        self.state = m.group(1)
        self.pins = ""
        for field in m.group(2).split("|"):
            key, _, value = field.partition(":")
            nums = [float(v) for v in value.split(",") if re.match(r"^[-+]?\d", v)]
            if key == "MPos" and len(nums) >= 2:
                self.mpos = nums[:2]
            elif key == "WPos" and len(nums) >= 2:
                self.mpos = [nums[0] + self.wco[0], nums[1] + self.wco[1]]
            elif key == "WCO" and len(nums) >= 2:
                self.wco = nums[:2]
            elif key == "Pn":
                self.pins = value
        self.status_seq += 1

    def _status(self, timeout: float = 2.0):
        with self.cond:
            seq = self.status_seq
            self._raw(b"?")
            end = time.monotonic() + timeout
            while self.status_seq == seq and not self.closed:
                left = end - time.monotonic()
                if left <= 0:
                    raise TimeoutError("Grbl antwortet nicht auf ?")
                self.cond.wait(left)

    def _send_grbl(self, line: str):
        """Queue one line in Grbl's buffer (character counting)."""
        size = len(line) + 1
        with self.cond:
            while self.pending and sum(self.pending) + size > RX_BUFFER:
                if self.closed:
                    raise ConnectionError("Grbl getrennt")
                self.cond.wait(0.5)
            self.pending.append(size)
            self._raw((line + "\n").encode("ascii"))

    def _startup(self):
        # The ESP32 may reboot when the port opens; give it its banner time.
        end = time.monotonic() + 4.0
        while time.monotonic() < end and not self.banner:
            time.sleep(0.1)
        self._raw(b"\r\n\r\n")
        time.sleep(0.3)
        self._status()
        # The Atomstack firmware boots in "Door" (safety door) and queues
        # every line until cycle start. Resume only with the door input
        # closed; Grbl then runs what it queued (here only blank lines).
        if self.state == "Door" and "D" not in self.pins:
            self._raw(b"~")
            time.sleep(0.5)
            self._status()
        if self.state == "Door":
            raise ConnectionError("Grbl meldet Tür offen (Door): Türschalter am Board prüfen")
        self.reset_input_buffer()
        self._read_settings()
        if not self.settings:
            raise ConnectionError("Board am %s antwortet nicht wie Grbl ($$)" % self.port)
        if int(self.settings.get(32, 0)) != 1:
            # Without laser mode Grbl keeps the beam on during G0 rapids.
            raise ConnectionError("Grbl-Lasermodus aus ($32=0): erst $32=1 setzen")
        self._status()
        if self.state == "Alarm":
            self._private_cmd("$X")

    def _private_cmd(self, line: str, timeout: float = 120.0) -> str:
        with self.cond:
            while self.pending:
                self.cond.wait(0.5)
            self.private_reply = None
            self.private_lines = []
            self.private_active = True
            self._raw((line + "\n").encode("ascii"))
            end = time.monotonic() + timeout
            while self.private_reply is None:
                left = end - time.monotonic()
                if left <= 0 or self.closed:
                    self.private_active = False
                    raise TimeoutError("Grbl: keine Antwort auf " + line)
                self.cond.wait(left)
            self.private_active = False
            return self.private_reply

    def _read_settings(self):
        self._private_cmd("$$", timeout=5.0)
        LOG.info("Grbl %s settings %s", self.banner, self.settings)

    # ---- translation ------------------------------------------------------

    def _sign(self, axis: int) -> float:
        """+1 when Grbl homes this axis to - (Marlin and Grbl both grow away)."""
        mask = int(self.settings.get(23, 0))
        return 1.0 if mask & (1 << axis) else -1.0

    def _marlin_xy(self):
        wx = self.mpos[0] - self.wco[0]
        wy = self.mpos[1] - self.wco[1]
        return wx * self._sign(0), wy * self._sign(1)

    def _power(self, s: float) -> float:
        top = self.settings.get(30, 1000.0) or 1000.0
        return round(max(0.0, min(MARLIN_S_MAX, s)) * top / MARLIN_S_MAX, 1)

    def _motion(self, cmd: str, words) -> str | None:
        code = cmd.split()[0]
        g = int(float(code[1:]))
        sx, sy = self._sign(0), self._sign(1)
        if g in (2, 3) and sx * sy < 0:
            g = 5 - g
        parts = ["G%d" % g]
        moved = False
        for letter, value in words[1:]:
            v = float(value)
            if letter == "Z":
                self.z = (self.z + v) if self.relative else v
                continue
            if letter in "XI":
                parts.append("%s%.3f" % (letter, v * sx))
                moved = moved or letter == "X"
            elif letter in "YJ":
                parts.append("%s%.3f" % (letter, v * sy))
                moved = moved or letter == "Y"
            elif letter == "S":
                parts.append("S%g" % self._power(v))
            elif letter == "F":
                parts.append("F%g" % v)
            elif letter == "R":
                parts.append("R%g" % v)
        if not moved and g in (0, 1):
            return None     # only Z (fixed head) or only F/S
        return " ".join(parts)

    def _handle(self, line: str):
        cmd = line.split(";", 1)[0].strip().upper()
        words = WORD.findall(cmd)
        head = cmd.split()[0] if cmd else ""
        family = head[0] + str(int(float(head[1:]))) if re.match(r"^[GM]\d+(\.\d+)?$", head) else head
        if family == "M115":
            self.out.put(IDENTITY)
            self.out.put("Cap:Z_PROBE:1")
            self.out.put("Cap:BINARY_FILE_TRANSFER:0")
            self.out.put("ok")
        elif family in ("G0", "G1", "G2", "G3"):
            grbl = self._motion(cmd, words)
            if grbl is None:
                self.out.put("ok")
            else:
                self._send_grbl(grbl)
        elif family == "M3":
            # Marlin inline mode: power only with each G1 S. Grbl M4 (dynamic)
            # scales power with speed and is off while standing still.
            self._send_grbl("M4 S0")
        elif family == "M4":
            self._send_grbl("M4 S0")
        elif family == "M5":
            self._send_grbl("M5")
        elif family in ("M8", "M9"):
            self._send_grbl(family)
        elif family in ("G90", "G91"):
            self.relative = family == "G91"
            self._send_grbl(family)
        elif family in ("G20", "G21"):
            self._send_grbl(family)
        elif family == "G4":
            ms = dict(words[1:]).get("P", "0")
            self._send_grbl("G4 P%.3f" % (float(ms) / 1000.0))
        elif family == "G28":
            self._home(cmd)
        elif family == "G30":
            self._idle()
            x, y = self._marlin_xy()
            hint = None
            try:
                hint = self.surface_hint() if self.surface_hint else None
            except Exception:
                LOG.exception("surface hint failed")
            self.z = 0.0 if hint is None else float(hint)
            self.out.put("Bed X: %.2f Y: %.2f Z: %.2f" % (x, y, self.z))
            self.out.put("X:%.2f Y:%.2f Z:%.2f E:0.00 Count X:0 Y:0 Z:0" % (x, y, self.z))
            self.out.put("ok")
        elif family == "M400":
            self._idle()
            self.out.put("ok")
        elif family == "M114":
            self._idle()
            x, y = self._marlin_xy()
            self.out.put("X:%.2f Y:%.2f Z:%.2f E:0.00 Count X:0 Y:0 Z:0" % (x, y, self.z))
            self.out.put("ok")
        elif family == "M119":
            self._idle()
            self.out.put("Reporting endstop status")
            self.out.put("x_min: %s" % ("TRIGGERED" if "X" in self.pins else "open"))
            self.out.put("y_min: %s" % ("TRIGGERED" if "Y" in self.pins else "open"))
            self.out.put("z_min: open")
            self.out.put("z_probe: open")
            self.out.put("ok")
        elif family == "M105":
            self.out.put("ok T:0")
        elif family == "M503":
            self.out.put("echo:; Atomstack-Board mit Grbl (%s)" % (self.banner or "?"))
            for key in sorted(self.settings):
                self.out.put("echo:  $%d=%g" % (key, self.settings[key]))
            self._idle()
            # Read-only board information (build, parser state, offsets,
            # startup lines, ESP32 info where the firmware knows it).
            for query in ("$I", "$G", "$#", "$N", "[ESP420]", "[ESP800]"):
                try:
                    reply = self._private_cmd(query, timeout=3.0)
                except TimeoutError:
                    reply = "keine Antwort"
                for extra in self.private_lines:
                    self.out.put("echo:  %s -> %s" % (query, extra))
                self.out.put("echo:  %s: %s" % (query, reply))
            self.out.put("ok")
        elif family == "M410":
            self._raw(b"!")
            time.sleep(0.2)
            self._raw(b"\x18")
            self.out.put("ok")
        elif family in NO_OP:
            self.out.put("ok")
        else:
            self.out.put("echo:Unknown command: \"%s\"" % cmd)
            self.out.put("ok")

    def _idle(self, timeout: float = 600.0):
        """M400: Grbl buffer empty and the machine standing still."""
        end = time.monotonic() + timeout
        with self.cond:
            while self.pending and time.monotonic() < end:
                self.cond.wait(0.2)
        while time.monotonic() < end:
            self._status()
            if self.state in ("Idle", "Alarm", "Hold", "Door"):
                return
            time.sleep(0.1)
        raise TimeoutError("Grbl wird nicht Idle")

    def _home(self, cmd: str):
        axes = set(re.findall(r"\b([XYZ])\b", cmd)) or {"X", "Y", "Z"}
        if axes & {"X", "Y"}:
            self._idle()
            reply = self._private_cmd("$H", timeout=120.0)
            if reply != "ok":
                self.out.put("Error:Grbl Referenzfahrt: " + reply)
                self.out.put("ok")
                return
            self._private_cmd("G10 L20 P1 X0 Y0")
            self._private_cmd("G90")
            self.relative = False
            self._status()
        if "Z" in axes:
            self.z = 0.0
        self.out.put("ok")

    def _work_loop(self):
        while not self.closed:
            try:
                line = self.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._handle(line)
            except Exception as exc:
                LOG.warning("bridge %r: %s", line, exc)
                self.out.put("Error:Grbl-Bridge " + str(exc)[:120])
                self.out.put("ok")

    def _emergency(self):
        try:
            self._raw(b"!")
            self._raw(b"\x18")
        except Exception:
            LOG.exception("Grbl emergency write failed")
        with self.cond:
            self.pending.clear()
        # Marlin stays silent after M112; so does the bridge until reopened.
        while not self.inbox.empty():
            try:
                self.inbox.get_nowait()
            except queue.Empty:
                break
        self.closed = True
