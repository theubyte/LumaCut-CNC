"""Focus follows the surface: Z per segment from a HeightMapSet (pure Python).

Same rules as Android ``FocusCompensation`` and the Windows app's
``apply_focus_compensation`` (docs/MASCHINE.md):

    Z = surface + focus gap - switch-to-tip offset,  never below surface + 2 mm

* Burning lines (G1) are split into pieces <= ``max_segment_mm``; every piece
  gets the Z of its end point. When Z cannot follow (9 mm/s) the feed of that
  piece is lowered.
* Rapids (G0) go up first and lower at the target, so the head never travels
  low over a taller part.
* Per-pass focus drops ``G91`` / ``G0 Z-0.5`` / ``G90`` are not sent; they
  become an offset on the map Z (and a positive one returns to focus).
* Arcs, relative X/Y moves and absolute Z words are refused: a job with its
  own Z is already compensated and must not be compensated again.
* Workflow lines (G28, G30, M2) belong to the automatic run, not here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .heightmap import HeightMapSet

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
_MOTION = re.compile(r"^G0*([0-3])(?:\s|$)")
Z_FEED = 600            # mm/min for Z-only rapids (firmware caps Z at 9 mm/s)
Z_RESOLUTION_MM = 0.01
LOWER_BEFORE_CUT_MM = 1.0   # larger Z jumps at a cut start happen laser-off


@dataclass
class Report:
    segments: int = 0
    z_min: float = math.inf
    z_max: float = -math.inf
    outside_mm: float = 0.0
    feed_limited: int = 0
    lowest_offset_mm: float = 0.0
    warnings: list = field(default_factory=list)

    def as_dict(self):
        return {"segments": self.segments,
                "z_min": None if self.segments == 0 else round(self.z_min, 3),
                "z_max": None if self.segments == 0 else round(self.z_max, 3),
                "outside_mm": round(self.outside_mm, 1), "feed_limited": self.feed_limited,
                "lowest_offset_mm": round(self.lowest_offset_mm, 3),
                "warnings": list(self.warnings)}


def _clean(raw):
    return re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0]).strip().upper()


def has_absolute_z(lines):
    """True when the job moves Z absolutely itself (already compensated)."""
    absolute = True
    for raw in lines:
        line = _clean(raw)
        if line == "G90":
            absolute = True
        elif line == "G91":
            absolute = False
        elif absolute and _MOTION.match(line) and "Z" in dict(_WORD.findall(line)):
            return True
    return False


def _f(value):
    return "%.3f" % value


def compensate(lines, maps: HeightMapSet, focus_gap_mm, tip_offset_mm, *,
               clearance_mm=2.0, max_segment_mm=2.0, z_max_mm_s=9.0, start_z=None):
    """(compensated lines, Report). Raises ValueError for unsupported input."""
    gap = focus_gap_mm - tip_offset_mm
    if gap < clearance_mm - 1e-9:
        raise ValueError("Fokushöhe läge näher als %g mm am Werkstück "
                         "(Fokusabstand / Schalter-Offset prüfen)" % clearance_mm)
    rep = Report()
    out = ["G90"]
    x = y = 0.0
    z = start_z
    relative = False
    offset = 0.0
    feed = None         # modal feed of the job
    out_feed = None     # feed Marlin has right now (G0 lines change it)
    last_s = None       # power of the last cut, Marlin forgets it on G0

    def surface_z(px, py, length):
        surface, inside = maps.surface(px, py)
        if not inside:
            rep.outside_mm += length
        target = surface + gap + offset
        if target < surface + clearance_mm - 1e-9:
            raise ValueError("Fokus-Absenkung führt unter Oberfläche + %g mm" % clearance_mm)
        return target

    def z_only(target):
        nonlocal z, out_feed
        out.append("G0 Z%s F%d" % (_f(target), Z_FEED))
        out_feed = None
        z = target

    for number, raw in enumerate(lines, 1):
        line = _clean(raw)
        if not line:
            continue
        if line == "G90":
            relative = False
            continue
        if line == "G91":
            relative = True
            continue
        words = _WORD.findall(line)
        values = {k: float(v) for k, v in words if k in "XYZFS"}
        motion = _MOTION.match(line)
        g = int(motion.group(1)) if motion else None
        if g in (2, 3):
            raise ValueError("Zeile %d: Bögen (G2/G3) – in der App als Linien ausgeben" % number)
        if relative:
            keys = {k for k, _ in words} - {"G"}
            if g in (0, 1) and "Z" in keys and keys <= {"Z", "F"}:
                offset = round(offset + values["Z"], 6)
                if offset > 20.0:
                    raise ValueError("Zeile %d: Fokus-Versatz über 20 mm" % number)
                rep.lowest_offset_mm = min(rep.lowest_offset_mm, offset)
                continue
            if g is None and not (keys & {"X", "Y", "Z"}):
                out.append(line)
                continue
            raise ValueError("Zeile %d: relative X/Y-Fahrten (G91) gehen im automatischen "
                             "Ablauf nicht" % number)
        if g in (0, 1) and "Z" in values:
            raise ValueError("Zeile %d: Auftrag enthält schon Z-Werte" % number)
        if g is None or not ("X" in values or "Y" in values):
            if g is not None and "F" in values:
                feed = values["F"]
            out.append(line)
            if g is not None and "F" in values:
                out_feed = feed
            continue
        nx, ny = values.get("X", x), values.get("Y", y)
        s_word = (" S%g" % values["S"]) if "S" in values else ""
        if g == 1 and "S" in values:
            last_s = values["S"]
        if "F" in values:
            feed = values["F"]
        if g == 0:
            target = surface_z(nx, ny, 0.0)
            if z is not None and target > z + Z_RESOLUTION_MM:
                z_only(target)                  # up first
            out.append("G0 X%s Y%s%s%s" % (_f(nx), _f(ny), s_word,
                                           (" F%g" % values["F"]) if "F" in values else ""))
            out_feed = None
            if z is None or abs(target - z) > Z_RESOLUTION_MM:
                z_only(target)                  # down at the target
        else:
            start = surface_z(x, y, 0.0)
            if z is None or abs(start - z) > LOWER_BEFORE_CUT_MM:
                # Never travel a large Z distance while burning (first cut
                # without a rapid, a big per-pass drop): settle Z first. The
                # rapid resets Marlin's inline power, so the cut needs its S.
                z_only(start)
                if not s_word and last_s is not None:
                    s_word = " S%g" % last_s
            length = math.hypot(nx - x, ny - y)
            pieces = max(1, math.ceil(length / max_segment_mm))
            for k in range(1, pieces + 1):
                px = x + (nx - x) * k / pieces
                py = y + (ny - y) * k / pieces
                target = surface_z(px, py, length / pieces)
                parts = ["G1 X%s Y%s" % (_f(px), _f(py))]
                piece_feed = feed
                if z is None or abs(target - z) > Z_RESOLUTION_MM:
                    if z is not None and feed:
                        t_xy = (length / pieces) / (feed / 60.0)
                        t_z = abs(target - z) / z_max_mm_s
                        if t_z > t_xy:
                            piece_feed = max(1.0, (length / pieces) / t_z * 60.0)
                            rep.feed_limited += 1
                    parts.append("Z" + _f(target))
                    z = target
                rep.z_min, rep.z_max = min(rep.z_min, z), max(rep.z_max, z)
                if s_word:
                    parts.append(s_word.strip())
                if piece_feed is not None and piece_feed != out_feed:
                    parts.append("F%g" % round(piece_feed, 1))
                    out_feed = piece_feed
                out.append(" ".join(parts))
                rep.segments += 1
        x, y = nx, ny
    if rep.outside_mm > 0.5:
        rep.warnings.append("%.0f mm Laserweg außerhalb der abgetasteten Bereiche – dort gilt "
                            "die höchste gemessene Oberfläche" % rep.outside_mm)
    if rep.feed_limited:
        rep.warnings.append("%d Stück(e) langsamer, weil Z (9 mm/s) nicht folgen kann"
                            % rep.feed_limited)
    return out, rep
