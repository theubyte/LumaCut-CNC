"""Adaptive Fokuskorrektur: Z pro Segment aus den Höhenmeshes.

Nimmt Marlin-G-Code (G0/G1, G90/G91, G20/G21, ``M3 I``/``M5 I``) und erzeugt
absoluten G-Code mit Z je Segment:

    Z_fokus = Oberfläche + Fokusabstand − Schalter→Laserspitze   (docs/MASCHINE.md)

* Brennende Linien (G1) werden in Stücke ≤ ``max_segment_mm`` geteilt.
* Leerfahrten (G0): erst anheben, dann fahren; absenken erst am Ziel – der
  Kopf fährt nie tief über ein höheres Werkstück.
* Z-Achse max. 9 mm/s: wird die Steigung zu groß, sinkt der Vorschub für
  dieses Stück (gemeldet in ``CompensationReport.feed_limited``).
* Z-Untergrenze: nie unter Oberfläche + ``min_clearance_mm`` (2 mm).
* Bögen (G2/G3) und eigene Z-Wörter im Eingang werden abgelehnt.

Langfristig rechnet der Pi die Korrektur (Plan Punkt 4); diese Funktion ist
identisch nutzbar in Studio (Vorschau/Export) und auf dem Pi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Optional

from .heightmap import HeightMapSet

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")


@dataclass
class FocusSettings:
    focus_distance_mm: float = 7.0       # Laserspitze -> Material
    switch_to_tip_mm: float = 1.5        # Schalter -> Laserspitze
    min_clearance_mm: float = 2.0        # Z-Untergrenze über Oberfläche
    max_segment_mm: float = 2.0
    z_resolution_mm: float = 0.02        # kleinere Änderungen nicht ausgeben
    z_max_speed_mm_s: float = 9.0
    outside: str = "hold"                # hold | default | error
    default_surface_z: Optional[float] = None
    method: str = "bicubic"

    def focus_z(self, surface: float) -> float:
        return surface + self.focus_distance_mm - self.switch_to_tip_mm

    def validate(self):
        if self.focus_distance_mm - self.switch_to_tip_mm < self.min_clearance_mm:
            raise ValueError("Fokus-Z läge unter der Z-Untergrenze (Oberfläche + 2 mm)")
        if self.outside not in ("hold", "default", "error"):
            raise ValueError("outside must be hold|default|error")
        if self.outside == "default" and self.default_surface_z is None:
            raise ValueError("default_surface_z required for outside='default'")
        if self.max_segment_mm <= 0:
            raise ValueError("max_segment_mm must be > 0")


@dataclass
class CompensationReport:
    input_lines: int = 0
    output_lines: int = 0
    segments_added: int = 0
    z_min: float = math.inf
    z_max: float = -math.inf
    outside_points: int = 0
    feed_limited: int = 0
    warnings: list[str] = field(default_factory=list)


def _fmt(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def apply_focus_compensation(gcode: str, maps: HeightMapSet,
                             settings: Optional[FocusSettings] = None,
                             start_z: Optional[float] = None) -> tuple[str, CompensationReport]:
    settings = settings or FocusSettings()
    settings.validate()
    rep = CompensationReport()
    out: list[str] = ["G21 G90 ; LumaCut Fokuskorrektur (Höhenmesh)"]
    x = y = 0.0
    z: Optional[float] = start_z
    absolute, scale = True, 1.0
    feed: Optional[float] = None
    motion = 0
    out_feed: Optional[float] = None   # modaler Vorschub im Ausgang

    def target_z(px: float, py: float) -> Optional[float]:
        surf = maps.surface_z(px, py, settings.method)
        if surf is None:
            rep.outside_points += 1
            if settings.outside == "error":
                raise ValueError(f"X{px:.2f} Y{py:.2f} liegt in keinem Höhenmesh")
            if settings.outside == "default":
                surf = settings.default_surface_z
            else:
                return None
        return settings.focus_z(surf)

    def emit_z_only(nz: float):
        nonlocal z, out_feed
        out.append(f"G0 Z{_fmt(nz)}")
        out_feed = None  # Pi setzt bei G0 ggf. F9000 -> F beim nächsten G1 neu
        z = nz
        _track(nz)

    def _track(nz):
        rep.z_min = min(rep.z_min, nz)
        rep.z_max = max(rep.z_max, nz)

    lines = gcode.splitlines()
    rep.input_lines = len(lines)
    for number, raw in enumerate(lines, 1):
        code = re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0]).strip().upper()
        if not code:
            out.append(raw)
            continue
        words = _WORD.findall(code)
        gs = [float(v) for k, v in words if k == "G"]
        if any(g in (2, 3) for g in gs):
            raise ValueError(f"Zeile {number}: G2/G3-Bögen vorher in Linien auflösen")
        for g in gs:
            if g == 20: scale = 25.4
            elif g == 21: scale = 1.0
            elif g == 90: absolute = True
            elif g == 91: absolute = False
        motion_words = [g for g in gs if g in (0, 1)]
        if motion_words:
            motion = int(motion_words[-1])
        vals = {k: float(v) for k, v in words if k in "XYZFS"}
        has_xy = "X" in vals or "Y" in vals
        if "Z" in vals:
            raise ValueError(f"Zeile {number}: Z im Eingang – der Fokus kommt aus dem Höhenmesh")
        is_motion = has_xy and (motion_words or not gs or set(gs) <= {0, 1, 20, 21, 90, 91})
        if not is_motion:
            mode_only = all(k == "G" and float(v) in (20, 21, 90, 91) for k, v in words)
            if not mode_only:  # Modus steckt schon im Kopf (G21 G90), Rest unverändert
                out.append(raw.strip())
            if "F" in vals:
                feed = vals["F"] * scale
                out_feed = feed
            continue
        nx = (vals["X"] * scale if absolute else x + vals["X"] * scale) if "X" in vals else x
        ny = (vals["Y"] * scale if absolute else y + vals["Y"] * scale) if "Y" in vals else y
        if "F" in vals:
            feed = vals["F"] * scale
        s_word = f" S{_fmt(vals['S'])}" if "S" in vals else ""
        if motion == 0:
            tz = target_z(nx, ny)
            if tz is not None and z is not None and tz > z + settings.z_resolution_mm:
                emit_z_only(tz)  # erst hoch
            f_word = f" F{_fmt(vals['F'] * scale)}" if "F" in vals else ""
            out.append(f"G0 X{_fmt(nx)} Y{_fmt(ny)}{s_word}{f_word}")
            out_feed = None
            if tz is not None and (z is None or abs(tz - z) > settings.z_resolution_mm):
                emit_z_only(tz)  # am Ziel absenken / erstmals setzen
        else:
            dist = math.hypot(nx - x, ny - y)
            n = max(1, math.ceil(dist / settings.max_segment_mm))
            rep.segments_added += n - 1
            for k in range(1, n + 1):
                px = x + (nx - x) * k / n
                py = y + (ny - y) * k / n
                tz = target_z(px, py)
                parts = [f"G1 X{_fmt(px)} Y{_fmt(py)}"]
                seg_feed = feed
                if tz is not None and (z is None or abs(tz - z) > settings.z_resolution_mm):
                    if z is not None and feed:
                        t_xy = (dist / n) / (feed / 60)
                        t_z = abs(tz - z) / settings.z_max_speed_mm_s
                        if t_z > t_xy:
                            seg_feed = max(1.0, (dist / n) / t_z * 60)
                            rep.feed_limited += 1
                    parts.append(f"Z{_fmt(tz)}")
                    z = tz
                    _track(tz)
                if s_word:
                    parts.append(s_word.strip())
                if seg_feed is not None and seg_feed != out_feed:
                    parts.append(f"F{_fmt(seg_feed)}")
                    out_feed = seg_feed
                out.append(" ".join(parts))
        x, y = nx, ny
    if rep.outside_points and settings.outside == "hold":
        rep.warnings.append(f"{rep.outside_points} Punkt(e) außerhalb aller Höhenmeshes – Z unverändert.")
    if rep.feed_limited:
        rep.warnings.append(f"{rep.feed_limited} Segment(e) langsamer, weil Z (9 mm/s) nicht folgen kann.")
    rep.output_lines = len(out)
    return "\n".join(out) + "\n", rep
