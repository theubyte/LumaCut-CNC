"""Bogentext: Buchstaben entlang eines Kreisbogens (Qt-frei).

Entspricht „Text auf Kreis“ in LightBurn/xTool und ``ArcText`` der
Android-App (``android/core/.../Extras.kt``): Die Grundlinie liegt auf dem
Kreis, die Bogenlänge der Grundlinie entspricht der flachen Textlänge.
Anders als Android wird jeder Buchstabe *starr* gedreht und gesetzt (keine
Verzerrung der Glyphen) – so wie es die Desktop-Programme tun.

Winkel in Grad, im Uhrzeigersinn ab 12 Uhr (0 = oben, 180 = unten),
Bildschirmkoordinaten (Y nach unten), mm. ``align`` legt fest, worauf sich
der Winkel bezieht: Mitte (``center``), Anfang (``start``) oder Ende
(``end``) des Textes in Leserichtung.

* ``bottom=False`` (oben/außen): Text läuft im Uhrzeigersinn, Buchstaben
  zeigen nach außen – liest sich oben auf dem Kreis von links nach rechts.
* ``bottom=True`` (unten/innen): Text läuft gegen den Uhrzeigersinn,
  Buchstaben zeigen zur Mitte – liest sich unten auf dem Kreis von links
  nach rechts (wie die untere Zeile eines Stempels).

Die Glyphen kommen als :class:`Glyph` (Vorschub + Umrisse relativ zum
Ursprung auf der Grundlinie, Y nach unten); die Qt-Seite
(:mod:`lumacut_job.arctext_qt`) liefert sie aus der Schrift.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, clamp_offset

Point = tuple[float, float]
Ring = list[Point]

RADIUS_RANGE = (2.0, 500.0)        # mm, Radius der Grundlinie
HEIGHT_RANGE = (1.0, 200.0)        # mm, Höhe der Großbuchstaben
SPACING_RANGE = (-20.0, 50.0)      # mm zusätzlich zwischen den Buchstaben
ANGLE_RANGE = (-360.0, 360.0)
MAX_CHARS = 200
ALIGNS = ("center", "start", "end")
ALIGN_LABELS = {"center": "Mitte", "start": "Anfang", "end": "Ende"}


@dataclass(frozen=True)
class Glyph:
    """Ein Zeichen: Vorschub (mm) und Umrisse relativ zum Grundlinien-Ursprung."""

    char: str
    advance: float
    rings: tuple[tuple[Point, ...], ...] = ()


@dataclass(frozen=True)
class ArcSpec:
    text: str = "LumaCut"
    radius_mm: float = 40.0
    height_mm: float = 8.0
    spacing_mm: float = 0.0
    angle_deg: float | None = None      # None: 0° oben, 180° unten
    bottom: bool = False
    align: str = "center"               # Bezug des Winkels: center | start | end
    font_family: str = "Segoe UI"
    bold: bool = False
    italic: bool = False

    def normalized(self) -> "ArcSpec":
        def clamp(v, rng):
            return max(rng[0], min(rng[1], float(v)))
        text = " ".join(str(self.text or "").split("\n"))[:MAX_CHARS]
        angle = (180.0 if self.bottom else 0.0) if self.angle_deg is None else clamp(self.angle_deg, ANGLE_RANGE)
        return ArcSpec(text=text, radius_mm=clamp(self.radius_mm, RADIUS_RANGE),
                       height_mm=clamp(self.height_mm, HEIGHT_RANGE),
                       spacing_mm=clamp(self.spacing_mm, SPACING_RANGE), angle_deg=angle,
                       bottom=bool(self.bottom),
                       align=self.align if self.align in ALIGNS else "center",
                       font_family=str(self.font_family or "Segoe UI"),
                       bold=bool(self.bold), italic=bool(self.italic))


@dataclass
class Placement:
    """Lage eines Buchstabens: Mitte seines Vorschubs auf der Grundlinie."""

    char: str
    angle_deg: float          # Position auf dem Kreis (Uhrzeigersinn ab 12 Uhr)
    rotation_deg: float       # Drehung des Buchstabens (Uhrzeigersinn)
    anchor: Point             # Punkt auf dem Kreis
    rings: list[Ring] = field(default_factory=list)


def point_on_circle(center: Point, radius: float, angle_deg: float) -> Point:
    a = math.radians(angle_deg)
    return center[0] + radius * math.sin(a), center[1] - radius * math.cos(a)


def text_span(glyphs: list[Glyph], spacing_mm: float) -> float:
    """Flache Länge der Grundlinie inkl. Zeichenabstand (mm)."""
    if not glyphs:
        return 0.0
    return sum(g.advance for g in glyphs) + spacing_mm * (len(glyphs) - 1)


def place_glyphs(glyphs: list[Glyph], radius_mm: float, angle_deg: float = 0.0,
                 bottom: bool = False, spacing_mm: float = 0.0,
                 center: Point = (0.0, 0.0), cap_height_mm: float = 0.0,
                 align: str = "center") -> list[Placement]:
    """Buchstaben auf den Kreis um ``center`` setzen.

    ``angle_deg`` ist je nach ``align`` die Lage von Mitte, Anfang oder Ende
    des Textes (Leserichtung) auf dem Kreis.

    Wirft ``ValueError``, wenn der Text länger als der Kreisumfang ist oder
    (unten/innen) die Buchstaben höher als der Radius sind.
    """
    r = float(radius_mm)
    if r <= 0:
        raise ValueError("Der Radius muss größer als 0 sein")
    span = text_span(glyphs, spacing_mm)
    if span <= 0:
        raise ValueError("Kein Text für den Bogen")
    if span > 2 * math.pi * r * 0.98:
        raise ValueError(f"Text ({span:.0f} mm) ist länger als der Kreisumfang "
                         f"({2 * math.pi * r:.0f} mm) – Radius vergrößern, Schrift verkleinern "
                         "oder Abstand verringern")
    if bottom and cap_height_mm >= r:
        raise ValueError("Buchstaben sind höher als der Radius – Radius vergrößern oder Schrift "
                         "verkleinern")
    sign = -1.0 if bottom else 1.0
    out = []
    if align not in ALIGNS:
        raise ValueError(f"Unbekannte Ausrichtung „{align}“")
    s = {"center": -span / 2.0, "start": 0.0, "end": -span}[align]
    for g in glyphs:
        mid = s + g.advance / 2.0
        ang = angle_deg + sign * math.degrees(mid / r)
        rot = ang + (180.0 if bottom else 0.0)
        anchor = point_on_circle(center, r, ang)
        c, si = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        rings = []
        for ring in g.rings:
            pts = []
            for u, v in ring:
                du = u - g.advance / 2.0
                pts.append((anchor[0] + du * c - v * si, anchor[1] + du * si + v * c))
            rings.append(pts)
        out.append(Placement(g.char, ang, rot, anchor, rings))
        s += g.advance + spacing_mm
    return out


def arc_shapes(glyphs: list[Glyph], spec: ArcSpec, layer_id: str,
               target_center: Point | None = None, cap_height_mm: float = 0.0) -> list[Shape]:
    """Bogentext als gruppierte ``polygon``-Objekte (ein Objekt je Buchstabe).

    Die Hüllbox des Ergebnisses wird auf ``target_center`` (Standard: Mitte
    der Arbeitsfläche) gelegt und, falls nötig, in die Arbeitsfläche
    geschoben. Wirft ``ValueError``, wenn sie nicht hineinpasst.
    """
    s = spec.normalized()
    places = place_glyphs(glyphs, s.radius_mm, s.angle_deg, s.bottom, s.spacing_mm,
                          cap_height_mm=cap_height_mm, align=s.align)
    rings_all = [p.rings for p in places if p.rings]
    pts = [pt for rings in rings_all for ring in rings for pt in ring]
    if not pts:
        raise ValueError("Der Text hat keine sichtbaren Zeichen")
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    if x1 - x0 > WORK_WIDTH_MM or y1 - y0 > WORK_HEIGHT_MM:
        raise ValueError(f"Bogentext {x1 - x0:.0f} × {y1 - y0:.0f} mm ist größer als die "
                         f"Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm)")
    tx, ty = target_center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    dx, dy = tx - (x0 + x1) / 2.0, ty - (y0 + y1) / 2.0
    cdx, cdy = clamp_offset(Rect(x0 + dx, y0 + dy, x1 - x0, y1 - y0))
    dx, dy = dx + cdx, dy + cdy
    group = new_id()
    out = []
    for rings in rings_all:
        flat: list[Point] = []
        starts = []
        for ring in rings:
            if len(ring) < 3:
                continue
            if flat:
                starts.append(len(flat))
            flat.extend((x + dx, y + dy) for x, y in ring)
        if len(flat) < 3:
            continue
        sh = Shape.from_points("polygon", flat, layer_id, rings=starts)
        sh.groups = (group,)
        out.append(sh)
    return out
