"""Fail-closed modal guard for laser G-code in LightBurn and local jobs.

A CNC spindle can run M3 at nonzero power during G0 traverses. For LumaCut
laser operation require grblHAL laser mode ($32=1) and M4 for any positive
laser power. This is a conservative source-level guard, not a safety interlock.
"""
from __future__ import annotations

import re

COMMENT = re.compile(r"\([^()]*\)")
WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")


def clean(line: str) -> str:
    while True:
        reduced = COMMENT.sub("", line)
        if reduced == line:
            return reduced.split(";", 1)[0].strip().upper()
        line = reduced


class LaserGuard:
    """Track M3/M4/M5 and S words; reject any potentially powered M3 mode."""

    def __init__(self):
        self.mode = "M5"
        self.s = 0.0

    def check(self, line: str):
        text = clean(line)
        if not text or text == "%":
            return
        if not text.isascii():
            raise ValueError("Nur ASCII-G-Code erlaubt")
        words = WORD.findall(text)
        if not words:
            # Preserve ordinary grblHAL lines; unknown verbs fail closed.
            if text not in ("%",):
                raise ValueError("G-Code-Zeile nicht lesbar")
            return
        remainder = WORD.sub("", text)
        if remainder.strip():
            raise ValueError("Unbekannte G-Code-Syntax")
        mode = self.mode
        power = self.s
        for letter, raw in words:
            if letter == "M":
                number = float(raw)
                if number == 3:
                    mode = "M3"
                elif number == 4:
                    mode = "M4"
                elif number in (5, 2, 30):
                    mode = "M5"
                    power = 0.0
            if letter == "S":
                power = float(raw)
                if not 0 <= power <= 100000:
                    raise ValueError("Ungültiger Laser-S-Wert")
        if mode == "M3" and power > 0:
            raise ValueError("M3 mit Laserleistung verboten: M4-Lasermodus verwenden")
        self.mode, self.s = mode, power


def check_program(source: str) -> None:
    guard = LaserGuard()
    for index, line in enumerate(source.splitlines(), 1):
        try:
            guard.check(line)
        except ValueError as exc:
            raise ValueError(f"G-Code-Zeile {index}: {exc}") from exc
