"""Umwandlung von Modellobjekten in QPainterPath (für Anzeige und Export).

Benötigt QtGui; für Text muss eine QGuiApplication existieren (Schriften).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontInfo, QFontMetricsF, QPainterPath, QTransform

from .linefont import EM_UNITS as _LINE_EM_UNITS, is_line_font, text_strokes
from .model import Geometry, Shape, text_layout

# Text wird in dieser Größe aufgebaut und dann exakt in die Objektbox skaliert,
# dadurch ist die Box (und nicht die Punktgröße) die maßgebliche Größe in mm.
_TEXT_BUILD_PT = 100.0

# Glatte Kreise/Ellipsen (Anforderungen 2026-10-26 §9.3): größter Abstand der
# Polylinie zur echten Kurve im G-Code, in der Schraffur und bei Boole/Versatz.
FLATTEN_TOL_MM = 0.02
MIN_ELLIPSE_SEGMENTS = 64
MAX_ELLIPSE_SEGMENTS = 4096
# Qt flacht Bézierkurven ab, bis der Fehler ≈ 0,5 Geräteeinheiten unterschreitet;
# vergrößert abflachen und zurückrechnen → Fehler ≈ 0,5/k mm (gemessen ≤ 0,013 mm).
_QT_FLATTEN_UNITS = 0.5
# Ellipse im QPainterPath aus 8 Bézierbögen à 45° statt Qts 4 à 90°:
# Formfehler 4·10⁻⁶·r statt 2,7·10⁻⁴·r (Ø 360 mm: 0,001 statt 0,05 mm) –
# gilt für Anzeige, SVG-Export (echte Kurven „C“) und Kurven-Abflachung.
_ELLIPSE_BEZIER_ARCS = 8
# Verschweißter Text (LightBurn *Weld*): Qt vereinigt die Buchstaben über
# ``QPainterPath.simplified`` und flacht dabei die Kurven sehr dicht ab. Vergrößert
# um k = _WELD_SCALE / tol (gemessen ≈ 0,0015 mm bei tol 0,01 mm), danach
# Douglas-Peucker mit 0,4 · tol gegen die Punktflut (≈ 1,5 × so viele Punkte wie
# der unverschweißte Umriss statt ≈ 8 ×) – zusammen unter ``WELD_TOL_MM``.
WELD_TOL_MM = 0.01
_WELD_SCALE = 0.1
_WELD_THIN = 0.4


def text_font(family: str, bold: bool = False, italic: bool = False) -> QFont:
    font = QFont(family)
    font.setPointSizeF(_TEXT_BUILD_PT)
    font.setBold(bold)
    font.setItalic(italic)
    return font


# Einlinien-Schriften (:mod:`linefont`): Geviert in Aufbau-Einheiten wie eine Systemschrift
# bei 96 dpi (100 pt = 133,3 px), damit Größe in pt, Zeilenabstand und Zeichenabstand
# dieselbe Bedeutung haben.
LINE_FONT_EM = _TEXT_BUILD_PT * 96.0 / 72.0


def text_em(family: str, bold: bool = False, italic: bool = False) -> float:
    """Geviert der Schrift ``family`` in Aufbau-Einheiten (auch für Einlinien-Schriften)."""
    if is_line_font(family):
        return LINE_FONT_EM
    return em_units(text_font(family, bold, italic))


def line_text_path(text: str, family: str, italic: bool = False, *, letter_spacing: float = 0.0,
                   line_spacing: float = 100.0, align: str = "left") -> QPainterPath:
    """Einlinien-Text (LightBurns *single-line font*) als offene Striche in Aufbau-Einheiten.

    Jeder Strich ist ein offener Teilpfad (``moveTo`` / ``lineTo``, kein ``closeSubpath``);
    in sich geschlossene Striche („o“) enden auf ihrem Anfangspunkt. Gleicher Satz wie
    :func:`text_path` (Zeilenabstand 1,25 × 100 pt, Zeichenabstand in % des Gevierts).
    """
    k = LINE_FONT_EM / _LINE_EM_UNITS
    path = QPainterPath()
    for stroke in text_strokes(text, family, italic, letter_spacing=letter_spacing,
                               line_spacing=line_spacing, align=align,
                               pitch_units=_TEXT_BUILD_PT * 1.25 / k):
        path.moveTo(stroke[0][0] * k, stroke[0][1] * k)
        for x, y in stroke[1:]:
            path.lineTo(x * k, y * k)
    return path


def em_units(font: QFont) -> float:
    """Geviert (Schriftgröße) von ``font`` in Umriss-Einheiten."""
    em = QFontInfo(font).pixelSize()
    if em <= 0:  # ohne Schriftdatenbank (z. B. Windows offscreen) meldet Qt -1
        em = font.pointSizeF() * 96.0 / 72.0
    return float(em)


def text_path(text: str, family: str, bold: bool = False, italic: bool = False, *,
              letter_spacing: float = 0.0, line_spacing: float = 100.0,
              align: str = "left") -> QPainterPath:
    """Textumriss in Aufbau-Einheiten (eine Zeile je ``\\n``).

    Text-Satz wie LightBurns *H-Space / V-Space / Align X*: ``letter_spacing`` in %
    der Schriftgröße zusätzlich nach jedem Zeichen, ``line_spacing`` in % des
    Standard-Zeilenabstands (1,25 × Schriftgröße), ``align`` richtet die Zeilen nach
    ihrer Laufweite links / mittig / rechts aus. Standardwerte = bisheriger Umriss.
    Einlinien-Schriften (:func:`linefont.is_line_font`) geben offene Striche
    (:func:`line_text_path`, ``bold`` wirkungslos, ``italic`` = schräg gestellt).
    """
    if is_line_font(family):
        return line_text_path(text, family, italic, letter_spacing=letter_spacing,
                              line_spacing=line_spacing, align=align)
    path = QPainterPath()
    font = text_font(family, bold, italic)
    if letter_spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing / 100.0 * em_units(font))
    lines = [line or " " for line in (text or " ").split("\n")]
    pitch = _TEXT_BUILD_PT * 1.25
    if line_spacing != 100.0:
        pitch *= line_spacing / 100.0
    offsets = [0.0] * len(lines)
    if align in ("center", "right") and len(lines) > 1:
        fm = QFontMetricsF(font)
        adv = [fm.horizontalAdvance(line) for line in lines]
        widest = max(adv)
        share = 0.5 if align == "center" else 1.0
        offsets = [(widest - a) * share for a in adv]
    for i, line in enumerate(lines):
        path.addText(QPointF(offsets[i], i * pitch), font, line)
    return path


def text_bounds(path: QPainterPath) -> QRectF:
    """Box eines Textpfads. Ein Einlinien-Text aus nur waagrechten (oder senkrechten)
    Strichen – „-“, „_“, „|“ – hätte Höhe (Breite) 0; die fehlende Ausdehnung wird
    dann um den Strich herum auf 1 Aufbau-Einheit gesetzt, damit er in eine Box passt."""
    r = path.boundingRect()
    if r.width() > 0 and r.height() <= 0:
        r = QRectF(r.x(), r.y() - 0.5, r.width(), 1.0)
    elif r.height() > 0 and r.width() <= 0:
        r = QRectF(r.x() - 0.5, r.y(), 1.0, r.height())
    return r


def shape_text_path(shape: Shape) -> QPainterPath:
    """Textumriss eines Textobjekts mit Schrift und Satz (Aufbau-Einheiten)."""
    return text_path(shape.text, shape.font_family, shape.font_bold, shape.font_italic,
                     **text_layout(shape))


def weld_path(path: QPainterPath, tol: float = WELD_TOL_MM) -> QPainterPath:
    """Alle Teilpfade von ``path`` (mm) nach der Nicht-Null-Regel vereinigen.

    Überlappende Buchstaben werden ein Umriss ohne innere Kanten, Löcher (Innenräume
    von „o“, „A“ …) bleiben Löcher, sofern kein anderer Buchstabe sie überdeckt. Das
    Ergebnis besteht nur aus geraden Strecken (Kurven mit Fehler ≈ ``tol`` abgeflacht),
    überschneidet sich nicht und wird nach der Gerade-Ungerade-Regel wie bisher gefüllt.
    """
    if path.isEmpty():
        return QPainterPath(path)
    from shapely.geometry import LineString
    k = max(1.0, _WELD_SCALE / tol)
    big = QTransform.fromScale(k, k).map(path)
    big.setFillRule(Qt.WindingFill)
    out = QPainterPath()
    for poly in big.simplified().toSubpathPolygons():
        pts = [(p.x() / k, p.y() / k) for p in poly]
        if len(pts) > 1 and pts[0] != pts[-1]:
            pts.append(pts[0])
        if len(pts) < 4:
            continue
        thin = list(LineString(pts).simplify(_WELD_THIN * tol, preserve_topology=False).coords)
        if len(thin) < 4:      # winziger Splitter: ungekürzt behalten
            thin = pts
        out.moveTo(*thin[0])
        for x, y in thin[1:-1]:
            out.lineTo(x, y)
        out.closeSubpath()
    return out


def text_aspect(text: str, family: str, bold: bool = False, italic: bool = False,
                **layout) -> float:
    """Breite/Höhe des Textumrisses, um neue Textobjekte maßstäblich anzulegen
    (``layout``: Text-Satz wie :func:`text_path`)."""
    r = text_bounds(text_path(text, family, bold, italic, **layout))
    return r.width() / r.height() if r.height() > 0 else 1.0


def curve_controls(p0, p1, p2, p3) -> tuple[tuple[float, float], tuple[float, float]]:
    """Bézier-Kontrollpunkte für das Catmull-Rom-Segment p1→p2."""
    c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
    c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
    return c1, c2


def add_point_rings(path: QPainterPath, pts, ranges, curves: set[int], closed: bool) -> None:
    """Ringe aus Stützpunkten anhängen; Segmente in ``curves`` als Kurve."""
    for a, b in ranges:
        ring = pts[a:b]
        n = len(ring)
        if n == 0:
            continue
        path.moveTo(*ring[0])
        n_seg = n if closed and n > 2 else n - 1
        for k in range(n_seg):
            p1, p2 = ring[k], ring[(k + 1) % n]
            if a + k in curves:
                if closed:
                    p0, p3 = ring[(k - 1) % n], ring[(k + 2) % n]
                else:
                    p0 = ring[k - 1] if k > 0 else p1
                    p3 = ring[k + 2] if k + 2 < n else p2
                c1, c2 = curve_controls(p0, p1, p2, p3)
                path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*p2))
            elif closed and k == n - 1:
                break  # gerades Schlusssegment: closeSubpath
            else:
                path.lineTo(*p2)
        if closed:
            path.closeSubpath()


def geometry_transform(g: Geometry) -> QTransform:
    """Drehung des Objekts um seine Boxmitte (Identität bei rot == 0)."""
    t = QTransform()
    if g.rot:
        cx, cy = g.center()
        t.translate(cx, cy)
        t.rotate(g.rot)
        t.translate(-cx, -cy)
    return t


def local_path(shape: Shape) -> QPainterPath:
    """Umriss in Arbeitsflächen-mm *ohne* Drehung."""
    g = shape.geom
    path = QPainterPath()
    if shape.kind == "line":
        path.moveTo(g.x, g.y)
        path.lineTo(g.x + g.w, g.y + g.h)
        return path
    if shape.kind in ("polygon", "path"):
        add_point_rings(path, shape.abs_points(), shape.ring_ranges(), set(shape.curves),
                        closed=shape.kind == "polygon")
        return path
    b = g.local_bounds()
    box = QRectF(b.x, b.y, b.w, b.h)
    if shape.kind == "rect" and shape.corner_radius:
        from .corners import effective_radius
        r = effective_radius(shape)
        if r:
            add_rounded_rect(path, box, r)
        else:
            path.addRect(box)
    elif shape.kind in ("rect", "image"):  # Bild: Umriss = Bildrahmen
        path.addRect(box)
    elif shape.kind == "ellipse":
        add_ellipse(path, box)
    elif shape.kind == "text":
        src = shape_text_path(shape)
        r = text_bounds(src)
        if r.width() > 0 and r.height() > 0:
            t = QTransform()
            t.translate(box.x(), box.y())
            t.scale(box.width() / r.width(), box.height() / r.height())
            t.translate(-r.x(), -r.y())
            path = t.map(src)
            if shape.text_weld and not is_line_font(shape.font_family):
                path = weld_path(path)   # Einlinien-Striche haben keine Fläche
    return path


def add_rounded_rect(path: QPainterPath, box: QRectF, r: float) -> None:
    """Rechteck mit Eckenradius ``r`` (mm, wirksam; < 0 = nach innen gewölbt):
    Start auf der Oberkante bei (x + |r|, y), im Uhrzeigersinn wie ``addRect``;
    jede Ecke aus zwei kubischen 45°-Bögen (Formfehler ≈ 4·10⁻⁶·|r| wie bei
    der Ellipse)."""
    from .corners import arc_sweep, corner_geometry
    corners = corner_geometry(box.x(), box.y(), box.width(), box.height(), r)
    a = abs(r)
    path.moveTo(corners[-1][1][0], corners[-1][1][1])
    for entry, exit_, centre in corners:
        cur = path.currentPosition()
        if math.dist((cur.x(), cur.y()), entry) > 1e-9:
            path.lineTo(*entry)
        a0, sweep = arc_sweep(entry, exit_, centre)
        n = 2
        d = sweep / n
        k = 4.0 / 3.0 * math.tan(d / 4.0)
        for i in range(n):
            t0, t1 = a0 + i * d, a0 + (i + 1) * d
            c0, s0, c1, s1 = math.cos(t0), math.sin(t0), math.cos(t1), math.sin(t1)
            end = exit_ if i == n - 1 else (centre[0] + a * c1, centre[1] + a * s1)
            path.cubicTo(QPointF(centre[0] + a * (c0 - k * s0), centre[1] + a * (s0 + k * c0)),
                         QPointF(centre[0] + a * (c1 + k * s1), centre[1] + a * (s1 - k * c1)),
                         QPointF(*end))
    path.closeSubpath()


def add_ellipse(path: QPainterPath, box: QRectF, arcs: int = _ELLIPSE_BEZIER_ARCS) -> None:
    """Geschlossene Ellipse in ``box`` aus ``arcs`` kubischen Bögen (Start rechts,
    Richtung wie ``QPainterPath.addEllipse``)."""
    cx, cy = box.center().x(), box.center().y()
    a, b = box.width() / 2.0, box.height() / 2.0
    d = 2.0 * math.pi / arcs
    k = 4.0 / 3.0 * math.tan(d / 4.0)
    path.moveTo(cx + a, cy)
    for i in range(arcs):
        t0, t1 = i * d, (i + 1) * d
        c0, s0, c1, s1 = math.cos(t0), math.sin(t0), math.cos(t1), math.sin(t1)
        path.cubicTo(QPointF(cx + a * (c0 - k * s0), cy + b * (s0 + k * c0)),
                     QPointF(cx + a * (c1 + k * s1), cy + b * (s1 - k * c1)),
                     QPointF(cx + a * c1, cy + b * s1))
    path.closeSubpath()


def ellipse_segments(a: float, b: float, tol: float = FLATTEN_TOL_MM) -> int:
    """Segmentzahl für eine Ellipse mit Halbachsen ``a``, ``b`` (mm).

    Gleichmäßig im Parameter t: der Sehnenfehler ist höchstens der eines Kreises
    mit dem größeren Halbmesser R, also R·(1 − cos(π/n)) ≤ ``tol``. Mindestens
    :data:`MIN_ELLIPSE_SEGMENTS`, Vielfaches von 4 (Scheitel liegen auf Punkten).
    """
    r = max(abs(a), abs(b))
    if r <= tol:
        n = MIN_ELLIPSE_SEGMENTS
    else:
        n = math.ceil(math.pi / math.acos(1.0 - tol / r))
    n = min(MAX_ELLIPSE_SEGMENTS, max(MIN_ELLIPSE_SEGMENTS, n))
    return -(-n // 4) * 4


def ellipse_polygon(g: Geometry, tol: float = FLATTEN_TOL_MM) -> list[tuple[float, float]]:
    """Ellipse der Box ``g`` als geschlossene Polylinie (erster = letzter Punkt),
    Drehung um die Boxmitte wie :func:`geometry_transform`."""
    cx, cy = g.x + g.w / 2.0, g.y + g.h / 2.0
    a, b = abs(g.w) / 2.0, abs(g.h) / 2.0
    n = ellipse_segments(a, b, tol)
    r = math.radians(g.rot or 0.0)
    cr, sr = math.cos(r), math.sin(r)
    pts = []
    for i in range(n):
        t = 2.0 * math.pi * i / n
        u, v = a * math.cos(t), b * math.sin(t)
        pts.append((cx + u * cr - v * sr, cy + u * sr + v * cr))
    pts.append(pts[0])
    return pts


def shape_polygons(shape: Shape, tol: float = FLATTEN_TOL_MM) -> list[list[tuple[float, float]]]:
    """Umriss als Polylinien in Arbeitsflächen-mm (inkl. Drehung), Kurven mit
    Sehnenfehler ≤ ``tol``. Geschlossene Ringe enden auf ihrem Startpunkt.

    Gemeinsame Quelle für G-Code, Schraffur-Beschnitt und Boole/Versatz.
    Ellipsen werden analytisch zerlegt (≥ 64 Segmente), alles andere über Qt
    mit vergrößerter Auflösung; gerade Strecken bekommen keine Zusatzpunkte.
    """
    if shape.kind == "ellipse":
        return [ellipse_polygon(shape.geom, tol)]
    path = shape_path(shape)
    k = max(1.0, _QT_FLATTEN_UNITS / tol)
    out = []
    for poly in path.toSubpathPolygons(QTransform.fromScale(k, k)):
        out.append([(p.x() / k, p.y() / k) for p in poly])
    return out


def shape_path(shape: Shape) -> QPainterPath:
    """Umriss des Objekts in Arbeitsflächen-mm inklusive Drehung.

    Anzeige, SVG/PNG-Export und G-Code gehen alle über diese Funktion, daher
    wirkt eine Drehung überall gleich.
    """
    path = local_path(shape)
    if shape.geom.rot:
        path = geometry_transform(shape.geom).map(path)
    return path
