"""Red line laser on the head for height measurement (3D), switched by a Pi GPIO.

A 5 mW measuring laser only, it never burns. It hangs on a Pi pin through a
small transistor/MOSFET module (5 V from the header), not on the SKR: the
SKR's spare FAN2 pin is the laser enable in the firmware. Off by default;
every "on" switches itself off after AUTO_OFF_S, so a lost client never
leaves it burning into somebody's eyes.
"""
from __future__ import annotations

import subprocess
import threading

AUTO_OFF_S = 120.0
# BCM numbers usable as plain outputs on the Pi 400 header (not ID EEPROM 0/1).
PINS = range(2, 28)


class LineLaser:
    def __init__(self, run=subprocess.run):
        self._run = run
        self.gpio = None
        self.on = False
        self._timer = None
        self._lock = threading.Lock()

    def _write(self, level: bool):
        done = self._run(["pinctrl", "set", str(self.gpio), "op", "dh" if level else "dl"],
                         capture_output=True, text=True, timeout=5, check=False)
        if done.returncode != 0:
            raise RuntimeError("Linienlaser-Pin GPIO %d nicht schaltbar: %s" % (self.gpio, (done.stderr or "").strip()[:120]))

    def configure(self, gpio):
        """Pin (BCM) or None; the old pin is switched off first, the new one starts off."""
        if gpio is not None and (isinstance(gpio, bool) or int(gpio) not in PINS):
            raise ValueError("Linienlaser-GPIO muss 2..27 sein (BCM-Nummer) oder leer")
        with self._lock:
            if self.gpio is not None:
                try:
                    self._write(False)
                except Exception:
                    pass
            self._cancel()
            self.gpio = None if gpio is None else int(gpio)
            self.on = False
            if self.gpio is not None:
                self._write(False)

    def set(self, on: bool):
        with self._lock:
            if self.gpio is None:
                raise RuntimeError("Linienlaser nicht eingerichtet (GPIO-Pin unter Einstellungen eintragen)")
            self._write(on)
            self.on = on
            self._cancel()
            if on:
                self._timer = threading.Timer(AUTO_OFF_S, self._auto_off)
                self._timer.daemon = True
                self._timer.start()

    def _auto_off(self):
        try:
            self.set(False)
        except Exception:
            pass

    def _cancel(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def status(self) -> dict:
        return {"gpio": self.gpio, "on": self.on}
