"""G-Code → Werkzeugbahn für die Pfadvorschau (Qt-frei).

Liest genau den G-Code, den der Export/Sendepfad erzeugt (Vektor-Ebenen mit
Füllung, Bild-Gravuren), und zerlegt ihn in XY-Bewegungen:

* ``cut``   – G1 bei eingeschaltetem Laser (``M3 I`` aktiv, ``S`` > 0)
* ``rapid`` – G0 oder G1 mit ``S0``/Laser aus (Leerfahrt)

Zusammenhängende Schnittbewegungen bilden einen *Lauf* (``runs``): Start-
markierung und Reihenfolgenummer der Vorschau. ``; LAYER <name>`` und
``; IMAGE <id>`` ordnen die Bewegungen einer Ebene bzw. einem Bild zu.
Reine Z-Bewegungen (Fokus-Absenkung) zählen nicht zur XY-Bahn.

Die Startposition vor der ersten Bewegung ist unbekannt (der Pi referenziert
und parkt selbst); die erste Positionierfahrt zählt daher – wie in
``lumacut_job.estimate`` – mit Länge 0.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_WORD = re.compile(r"([A-Z])\s*(-?\d+(?:\.\d*)?|-?\.\d+)")

CUT = "cut"
RAPID = "rapid"


@dataclass(frozen=True)
class Move:
    kind: str                      # CUT | RAPID
    x0: float
    y0: float
    x1: float
    y1: float
    source: tuple[str, str]        # ("layer", Name) | ("image", Objekt-ID) | ("", "")
    power: float = 0.0             # S-Wert (0 bei Leerfahrt)
    feed: float = 0.0              # mm/min (0 = Eilgang)

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)


@dataclass
class Toolpath:
    moves: list[Move] = field(default_factory=list)
    runs: list[tuple[int, int]] = field(default_factory=list)   # [start, end) in moves
    cut_length_mm: float = 0.0
    rapid_length_mm: float = 0.0

    def lengths_until(self, n: int) -> tuple[float, float]:
        """(Schnitt-, Leerfahrt-Länge) der ersten ``n`` Bewegungen."""
        cut = rapid = 0.0
        for m in self.moves[:max(0, n)]:
            if m.kind == CUT:
                cut += m.length
            else:
                rapid += m.length
        return cut, rapid

    def runs_until(self, n: int) -> int:
        """Wie viele Läufe bis Bewegung ``n`` begonnen haben."""
        return sum(1 for s, _ in self.runs if s < n)

    def sources(self) -> list[tuple[str, str]]:
        seen: dict[tuple[str, str], None] = {}
        for m in self.moves:
            seen.setdefault(m.source, None)
        return list(seen)


def parse_gcode(gcode: str) -> Toolpath:
    tp = Toolpath()
    pos: list[float] | None = None      # XY; None = Start unbekannt
    absolute = True
    laser_on = False
    feed = 0.0
    power = 0.0
    source: tuple[str, str] = ("", "")
    run_start: int | None = None

    def close_run() -> None:
        nonlocal run_start
        if run_start is not None and run_start < len(tp.moves):
            tp.runs.append((run_start, len(tp.moves)))
        run_start = None

    for raw in gcode.splitlines():
        code, _, comment = raw.partition(";")
        comment = comment.strip()
        if comment.startswith("LAYER "):
            close_run()
            source = ("layer", comment[6:].strip())
        elif comment.startswith("IMAGE "):
            close_run()
            source = ("image", comment[6:].split()[0] if comment[6:].split() else "")
        line = code.strip().upper()
        if not line:
            continue
        if line == "G90":
            absolute = True
            continue
        if line == "G91":
            absolute = False
            continue
        if line.startswith("M3") or line.startswith("M4"):
            laser_on = True
            continue
        if line.startswith("M5"):
            laser_on = False
            close_run()
            continue
        words = dict(_WORD.findall(line))
        g = words.get("G")
        if g is None or int(float(g)) not in (0, 1):
            continue
        g = int(float(g))
        if "F" in words and g == 1:
            feed = float(words["F"])
        if g == 1 and "S" in words:
            power = float(words["S"])
        if "X" not in words and "Y" not in words:
            continue                     # reine Z-/Vorschub-Zeile
        if pos is None:
            if not absolute:
                continue
            pos = [float(words.get("X", 0.0)), float(words.get("Y", 0.0))]
            continue
        tgt = list(pos)
        for k, axis in enumerate("XY"):
            if axis in words:
                v = float(words[axis])
                tgt[k] = v if absolute else pos[k] + v
        if math.hypot(tgt[0] - pos[0], tgt[1] - pos[1]) <= 1e-9:
            pos = tgt
            continue
        cutting = g == 1 and laser_on and power > 0
        m = Move(CUT if cutting else RAPID, pos[0], pos[1], tgt[0], tgt[1], source,
                 power if cutting else 0.0, feed if g == 1 else 0.0)
        if cutting:
            if run_start is None:
                run_start = len(tp.moves)
            tp.cut_length_mm += m.length
        else:
            close_run()
            tp.rapid_length_mm += m.length
        tp.moves.append(m)
        pos = tgt
    close_run()
    return tp
