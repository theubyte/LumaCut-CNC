"""Development stand-in for the Pi: the real pi400/marlin/web.py against a simulated controller.

Nothing here talks to hardware. Port 8090, data in a temp folder, no update/panel threads.
    python tools/sim_pi.py [--port 8090] [--slow]
"""
import argparse
import io
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = tempfile.mkdtemp(prefix="lumacut-sim-")
os.environ["LUMACUT_DATA"] = DATA
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--slow", action="store_true", help="moves take time, so job progress is visible")
    args = ap.parse_args()
    sim = SimController(args.slow)
    web.machine = m = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
    m.homing_verified = True
    m.probe_xy_offset_mm = SimController.OFFSET
    m.ensure_ready()
    web.config["validated"] = True
    web.running = True
    threading.Thread(target=web.monitor_loop, daemon=True, name="sim-heartbeat").start()
    print(f"LumaCut-Simulator auf http://127.0.0.1:{args.port}  (Daten: {DATA})", flush=True)
    web.app.run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
