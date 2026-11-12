"""Text auf Pfad: Buchstaben entlang einer beliebigen Linie / Kontur (Qt-frei).

Entspricht LightBurns *Text on Path* und xTools „Text auf Pfad“: ein Text
wird an eine Linie, einen offenen Pfad, ein Polygon, ein Rechteck oder eine
Ellipse gehängt. Wie beim Bogentext (:mod:`lumacut_job.arctext`) wird jeder
Buchstabe *starr* gesetzt (keine Verzerrung der Glyphen):

* Die Mitte seines Vorschubs liegt auf der Grundlinie bei der Bogenlänge ``s``
  des Pfads (:class:`lumacut_canvas.alongpath.PathCurve`).
* Gedreht wird er nach der Sehne zwischen Anfang und Ende seines Vorschubs
  auf dem Pfad – so stehen die Buchstaben auch an Knicken und in engen
  Kurven ruhig (``rotate=False``: alle Buchstaben aufrecht).
* ``distance_mm`` hebt die Grundlinie senkrecht zum Pfad an (positiv = zur
  Oberseite der Buchstaben, negativ = darunter; −Höhe/2 legt die Mitte der
  Großbuchstaben auf den Pfad).

``position_pct`` (0–100 % der Pfadlänge) ist je nach ``align`` die Lage von
Anfang, Mitte oder Ende des Textes. Geschlossene Umrisse beginnen oben in der
Mitte und laufen im Uhrzeigersinn (:func:`~lumacut_canvas.alongpath.normalize_closed`):
0 % = oben Mitte, 50 % = unten Mitte; der Text darf dort über den Anfang
hinweg laufen. ``flip`` legt den Text auf die andere Seite des Pfads (er läuft
dann in Gegenrichtung, liest sich z. B. unten auf einem Kreis von links nach
rechts). Offene Pfade werden über ihre Enden hinaus geradlinig verlängert –
:class:`PathTextResult` meldet, ob der Text übersteht.

Das Ergebnis sind gruppierte ``polygon``-Objekte (ein Objekt je Buchstabe, mit
Löchern) – wie „Text in Pfade“ und Bogentext unabhängig von installierten
Schriften und für Füllen, Schneiden, Kerf, Stege usw. nutzbar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from lumacut_canvas.alongpath import PathCurve
from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from .arctext import ALIGN_LABELS, ALIGNS, HEIGHT_RANGE, MAX_CHARS, SPACING_RANGE, Glyph, text_span

Point = tuple[float, float]
Ring = list[Point]

POSITION_RANGE = (0.0, 100.0)      # % der Pfadlänge
DISTANCE_RANGE = (-100.0, 100.0)   # mm senkrecht zum Pfad
_TOL = 0.01                        # mm Toleranz für die Arbeitsfläche


@dataclass(frozen=True)
class PathTextSpec:
    text: str = "LumaCut"
    height_mm: float = 8.0
    spacing_mm: float = 0.0
    position_pct: float | None = None   # None: geschlossen 0 % (oben), 50 % (unten bei flip); offen 50 %
    distance_mm: float = 0.0
    flip: bool = False
    align: str = "center"
    rotate: bool = True
    font_family: str = "Segoe UI"
    bold: bool = False
    italic: bool = False

    def normalized(self, closed: bool | None = None) -> "PathTextSpec":
        def clamp(v, rng):
            return max(rng[0], min(rng[1], float(v)))
        text = " ".join(str(self.text or "").split("\n"))[:MAX_CHARS]
        pos = self.position_pct
        if pos is None and closed is not None:
            pos = (50.0 if self.flip else 0.0) if closed else 50.0
        return PathTextSpec(text=text, height_mm=clamp(self.height_mm, HEIGHT_RANGE),
                            spacing_mm=clamp(self.spacing_mm, SPACING_RANGE),
                            position_pct=None if pos is None else clamp(pos, POSITION_RANGE),
                            distance_mm=clamp(self.distance_mm, DISTANCE_RANGE),
                            flip=bool(self.flip),
                            align=self.align if self.align in ALIGNS else "center",
                            rotate=bool(self.rotate),
                            font_family=str(self.font_family or "Segoe UI"),
                            bold=bool(self.bold), italic=bool(self.italic))


@dataclass
class Placement:
    """Lage eines Buchstabens: Mitte seines Vorschubs auf der (angehobenen) Grundlinie."""

    char: str
    s: float                  # Bogenlänge auf dem Pfad (in Laufrichtung des Textes)
    rotation_deg: float       # Drehung des Buchstabens (Uhrzeigersinn, 0 = aufrecht)
    anchor: Point
    rings: list[Ring] = field(default_factory=list)


@dataclass
class PathTextResult:
    placements: list[Placement]
    span_mm: float            # flache Textlänge
    length_mm: float          # Pfadlänge
    closed: bool
    overhang_mm: float        # offener Pfad: so weit steht der Text über die Enden hinaus

    def readout(self) -> str:
        kind = "geschlossen" if self.closed else "offen"
        share = 100.0 * self.span_mm / self.length_mm if self.length_mm > 0 else 0.0
        text = (f"Textlänge {self.span_mm:.1f} mm auf {self.length_mm:.1f} mm Pfad ({kind}, "
                f"{share:.0f} %)")
        if self.overhang_mm > 0.05:
            text += f" – ragt {self.overhang_mm:.1f} mm über das Pfadende hinaus"
        return text


def place_on_path(glyphs: list[Glyph], curve: PathCurve, spec: PathTextSpec) -> PathTextResult:
    """Buchstaben auf ``curve`` setzen.

    Wirft ``ValueError`` ohne Text oder wenn der Text auf einem geschlossenen
    Pfad länger als der Umfang ist (er würde sich selbst überlappen).
    """
    s = spec.normalized(curve.closed)
    span = text_span(glyphs, s.spacing_mm)
    if span <= 0:
        raise ValueError("Kein Text für den Pfad")
    L = curve.length
    if curve.closed and span > L * 0.98:
        raise ValueError(f"Text ({span:.0f} mm) ist länger als der Umfang des Pfads ({L:.0f} mm) "
                         "– Schrift verkleinern oder Abstand verringern")
    path = curve.reversed() if s.flip else curve
    pos = L * s.position_pct / 100.0
    if s.flip:
        pos = (L - pos) % L if curve.closed else L - pos
    start = pos + {"center": -span / 2.0, "start": 0.0, "end": -span}[s.align]
    overhang = 0.0 if curve.closed else max(0.0, -start, start + span - L)
    out = []
    cur = start
    for g in glyphs:
        mid = cur + g.advance / 2.0
        half = max(g.advance / 2.0, 1e-3)
        tangent = path.chord_angle(mid - half, mid + half)
        rot = tangent if s.rotate else 0.0
        base = path.point_at(mid)
        if s.distance_mm:      # senkrecht zur Laufrichtung, zur Oberseite der Buchstaben
            ang = math.radians(tangent)
            base = (base[0] + s.distance_mm * math.sin(ang), base[1] - s.distance_mm * math.cos(ang))
        c, si = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        rings = []
        for ring in g.rings:
            pts = []
            for u, v in ring:
                du = u - g.advance / 2.0
                pts.append((base[0] + du * c - v * si, base[1] + du * si + v * c))
            rings.append(pts)
        out.append(Placement(g.char, mid, rot, base, rings))
        cur += g.advance + s.spacing_mm
    return PathTextResult(out, span, L, curve.closed, overhang)


def pathtext_shapes(glyphs: list[Glyph], curve: PathCurve, spec: PathTextSpec,
                    layer_id: str) -> tuple[list[Shape], PathTextResult]:
    """Text auf Pfad als gruppierte ``polygon``-Objekte (ein Objekt je Buchstabe).

    Die Lage folgt dem Pfad (keine Verschiebung). Wirft ``ValueError``, wenn
    kein sichtbares Zeichen entsteht oder der Text die Arbeitsfläche verlässt.
    """
    res = place_on_path(glyphs, curve, spec)
    rings_all = [p.rings for p in res.placements if p.rings]
    pts = [pt for rings in rings_all for ring in rings for pt in ring]
    if not pts:
        raise ValueError("Der Text hat keine sichtbaren Zeichen")
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    if x0 < -_TOL or y0 < -_TOL or x1 > WORK_WIDTH_MM + _TOL or y1 > WORK_HEIGHT_MM + _TOL:
        raise ValueError("Der Text ragt aus der Arbeitsfläche – Seite, Abstand, Lage oder "
                         "Schrifthöhe ändern")
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
            flat.extend(ring)
        if len(flat) < 3:
            continue
        sh = Shape.from_points("polygon", flat, layer_id, rings=starts)
        sh.groups = (group,)
        out.append(sh)
    return out, res


__all__ = ["ALIGN_LABELS", "ALIGNS", "DISTANCE_RANGE", "POSITION_RANGE", "PathTextResult", "PathTextSpec",
           "pathtext_shapes", "place_on_path"]
