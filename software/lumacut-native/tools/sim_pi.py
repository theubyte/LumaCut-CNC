"""Development stand-in for the Pi: the real pi400/marlin/web.py against a simulated controller.

Nothing here talks to hardware. Port 8090, data in a temp folder, no update/panel threads.
    python tools/sim_pi.py [--port 8090] [--slow] [--no-camera]
"""
import argparse
import io
import os
import re
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = tempfile.mkdtemp(prefix="lumacut-sim-")
os.environ["LUMACUT_DATA"] = DATA
os.environ["LUMACUT_CAMERA_CALIBRATION"] = str(Path(DATA) / "camera_calibration.json")  # never /etc on the dev machine
sys.path.insert(0, str(ROOT / "pi400"))
sys.path.insert(0, str(ROOT / "tests"))

from marlin import web  # noqa: E402
from marlin.transport import MarlinTransport  # noqa: E402


class SimController:
    """Same behaviour as MarlinSim in tests/test_autorun.py, plus a flat 4 mm plate and optional real time."""
    OFFSET = (-27.4, 13.0)

    def __init__(self, slow=False):
        self.pos = [150.0, 150.0, 40.0]
        self.absolute = True
        self.out = []
        self.slow = slow
        self.feed = 3000.0

    def report(self):
        return "X:%.3f Y:%.3f Z:%.3f E:0.00 Count X:0 Y:0 Z:0" % tuple(self.pos)

    def write(self, raw):
        cmd = raw.decode(errors="replace").strip()
        words = {k: float(v) for k, v in re.findall(r"([XYZFS])([-+]?[0-9.]+)", cmd)}
        reply = []
        head = cmd.split()[0] if cmd else ""
        if head == "M112":  # the firmware stops dead, without an answer; M115 and M999 still work afterwards
            self.out.clear()
            return len(raw)
        if head == "M115":
            reply += ["FIRMWARE_NAME:LumaCut CNC 0.2.6-sim (Nov  5 2026 12:00:00) MACHINE_TYPE:LumaCut CNC", "Cap:Z_PROBE:1"]
        elif cmd.startswith("G28"):
            if "Z" in cmd and "X" not in cmd:
                self.pos[2] = 0.0
            else:
                self.pos[0] = self.pos[1] = 0.0
        elif cmd in ("G90", "G91"):
            self.absolute = cmd == "G90"
        elif re.match(r"G[0123]\b", cmd):
            if "F" in words:
                self.feed = max(words["F"], 1.0)
            before = list(self.pos)
            for i, axis in enumerate("XYZ"):
                if axis in words:
                    self.pos[i] = words[axis] if self.absolute else self.pos[i] + words[axis]
            if self.slow:
                dist = sum((a - b) ** 2 for a, b in zip(before, self.pos)) ** 0.5
                time.sleep(min(dist / (self.feed / 60.0), 0.25))
        elif cmd == "M114":
            reply.append(self.report())
        elif cmd == "M119":
            reply += ["Reporting endstop status", "z_min: open"]
        elif cmd.startswith("G30"):
            self.pos[2] = 8.0
            reply += ["Bed X:%.3f Y:%.3f Z:%.3f" % tuple(self.pos)]
        self.out += [r + "\n" for r in reply] + ["ok\n"]
        return len(raw)

    def readline(self):
        return self.out.pop(0).encode() if self.out else b""

    def reset_input_buffer(self):
        pass

    def close(self):
        pass


def _jpeg_blocks(cols, rows, cb, cr, luma):
    """Baseline JPEG with DC coefficients only: 8x8 flat blocks, fast enough in plain Python and readable by every decoder."""
    width, height = cols * 8, rows * 8
    def seg(marker, body):
        return bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body
    out = bytearray([0xFF, 0xD8])
    out += seg(0xDB, bytes([0]) + bytes([8] * 64))
    out += seg(0xC0, bytes([8]) + struct.pack(">HH", height, width) + bytes([3, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0]))
    out += seg(0xC4, bytes([0x00, 0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(12)))
    out += seg(0xC4, bytes([0x10, 1] + [0] * 15) + bytes([0]))
    out += seg(0xDA, bytes([3, 1, 0, 2, 0, 3, 0, 0, 63, 0]))
    codes = [(0b00, 2), (0b010, 3), (0b011, 3), (0b100, 3), (0b101, 3), (0b110, 3), (0b1110, 4), (0b11110, 5), (0b111110, 6)]
    acc = 0; n = 0; data = bytearray()
    def bits(value, length):
        nonlocal acc, n
        acc = (acc << length) | value; n += length
        while n >= 8:
            n -= 8
            b = (acc >> n) & 0xFF
            data.append(b)
            if b == 0xFF:
                data.append(0)
        acc &= (1 << n) - 1
    def dc(diff):
        size = abs(diff).bit_length()
        bits(*codes[size])
        if size:
            bits(diff if diff > 0 else diff + (1 << size) - 1, size)
        bits(0, 1)  # end of block
    prev = [0, 0, 0]
    for j in range(rows):
        for i in range(cols):
            for c, v in enumerate((luma(i, j) - 128, cb, cr)):
                dc(int(v) - prev[c]); prev[c] = int(v)
    if n:
        bits((1 << (8 - n)) - 1, 8 - n)
    return bytes(out + data + bytes([0xFF, 0xD9]))


def test_jpeg(sim, width, height, settings):
    """What the head camera would see: a bed with a 20 mm grid and one darker plate, moving with the head."""
    cols, rows = max(width // 8, 20), max(height // 8, 15)
    travel_x = web.config["travels"]["x"]
    hx, hy = travel_x - sim.pos[0], sim.pos[1]
    fov = 90.0
    exposure = settings.get("exposure")
    level = 1.0 if exposure is None else min(1.6, 0.35 + exposure / 700.0)
    if settings.get("gain") is not None:
        level *= 0.7 + settings["gain"] / 170.0
    kelvin = settings.get("white_balance") or 4500
    warm = int(max(-30, min(30, (4500 - kelvin) / 90)))
    def luma(i, j):
        x = hx + (i / cols - 0.5) * fov
        y = hy + (j / rows - 0.5) * fov * rows / cols
        v = 95 if 110 <= x <= 250 and 110 <= y <= 230 else 185
        if x % 20 < 1.4 or y % 20 < 1.4:
            v -= 32
        return max(1, min(254, int(v * level)))
    return _jpeg_blocks(cols, rows, -8 - warm // 2, 6 + warm, luma)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--slow", action="store_true", help="moves take time, so job progress is visible")
    ap.add_argument("--no-camera", action="store_true", help="behave like a Pi without head camera")
    ap.add_argument("--motion", metavar="ACCEL,SPEED", help="saved motion limits like on the real Pi, e.g. 1050,150 (mm/s², mm/s)")
    args = ap.parse_args()
    sim = SimController(args.slow)
    web.machine = m = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
    m.homing_verified = True
    m.probe_xy_offset_mm = SimController.OFFSET
    m.ensure_ready()
    web.config["validated"] = True
    web.config["probe_offset_x_mm"], web.config["probe_offset_y_mm"] = SimController.OFFSET
    if args.motion:
        accel, speed = (float(v) for v in args.motion.split(","))
        web.config["motion"] = {"accel": accel, "speed": speed}
    if not args.no_camera:
        web.CAMERA = str(Path(DATA) / "video0")
        Path(web.CAMERA).touch()
        web.head_camera.ranges = lambda device: {"exposure": (1, 5000), "gain": (0, 255), "white_balance": (2800, 6500)}
        web.head_camera.snapshot = lambda device, w, h, settings: (time.sleep(0.5 if args.slow else 0.08), test_jpeg(sim, w, h, settings))[1]
    web.running = True
    threading.Thread(target=web.monitor_loop, daemon=True, name="sim-heartbeat").start()
    print(f"LumaCut-Simulator auf http://127.0.0.1:{args.port}  (Daten: {DATA})", flush=True)
    web.app.run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
