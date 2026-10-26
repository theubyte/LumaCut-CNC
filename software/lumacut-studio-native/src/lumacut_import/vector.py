"""SVG- und DXF-Import als Polylinien in Millimetern (Qt-frei).

Kurven (Bézier, Bögen, Kreise, Ellipsen, Splines) werden mit einer
Sehnentoleranz von ``tolerance_mm`` in Liniensegmente zerlegt – genauso wie
der Canvas Ellipsen/Text vor dem G-Code zerlegt.

Koordinaten: SVG ist wie der Canvas y-nach-unten; DXF ist y-nach-oben und
wird an der Arbeitsflächenhöhe gespiegelt (DXF-Ursprung = links unten).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from lumacut_canvas.workarea import WORK_HEIGHT_MM

DEFAULT_TOLERANCE_MM = 0.05
MAX_SEGMENTS_PER_CURVE = 2000
PX_PER_MM = 96.0 / 25.4  # svgelements rechnet in CSS-px (96 ppi)


@dataclass
class Polyline:
    points: list[tuple[float, float]]
    closed: bool = False


@dataclass
class VectorImport:
    polylines: list[Polyline] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)  # Typ -> Anzahl

    def skip(self, kind: str) -> None:
        self.skipped[kind] = self.skipped.get(kind, 0) + 1

    def notes(self) -> list[str]:
        return [f"{n}× {k} übersprungen" for k, n in sorted(self.skipped.items())]


def _segments_for(length_mm: float, radius_mm: float | None, tol: float) -> int:
    """Anzahl Teilstücke für eine Kurve bei Sehnenfehler ``tol``."""
    if radius_mm and radius_mm > tol:
        step = 2.0 * math.sqrt(max(tol * (2 * radius_mm - tol), 1e-12))
    else:
        # Bézier ohne bekannten Radius: 0,5-mm-Schritte halten den Sehnenfehler
        # ab ~0,6 mm Krümmungsradius unter 0,05 mm.
        step = 0.5
    return int(min(MAX_SEGMENTS_PER_CURVE, max(8, math.ceil(length_mm / step))))


def _dedupe(pts: list[tuple[float, float]], eps: float = 1e-6) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    return out


def _finish(pts: list[tuple[float, float]], closed: bool, result: VectorImport) -> None:
    pts = _dedupe(pts)
    if closed and len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts = pts[:-1]
    if len(pts) < 2:
        return
    # Ein "geschlossener" Pfad aus zwei Punkten ist eine Linie.
    result.polylines.append(Polyline(pts, closed and len(pts) >= 3))


# ---------------------------------------------------------------- SVG
def load_svg(source, tolerance_mm: float = DEFAULT_TOLERANCE_MM) -> VectorImport:
    """SVG-Datei (Pfad oder Datei-Objekt) → Polylinien in mm.

    Unterstützt path, rect (auch abgerundet), circle, ellipse, line,
    polyline, polygon, verschachtelte Transformationen, ``use`` und
    Einheiten (mm, cm, in, pt, px, viewBox). ``text`` und eingebettete
    Bilder werden übersprungen (bitte in Pfade umwandeln bzw. als Bild
    importieren).
    """
    import svgelements as se

    svg = se.SVG.parse(os.fspath(source) if isinstance(source, os.PathLike) else source,
                       reify=True, ppi=96.0)
    result = VectorImport()
    k = 1.0 / PX_PER_MM
    for el in svg.elements():
        if isinstance(el, se.Text):
            result.skip("Text")
            continue
        if isinstance(el, se.Image):
            result.skip("eingebettetes Bild")
            continue
        if not isinstance(el, se.Shape):
            continue
        if str(el.values.get("visibility", "")).strip() == "hidden":
            continue
        path = se.Path(el)
        if len(path) == 0:
            continue
        for sub in path.as_subpaths():
            pts: list[tuple[float, float]] = []
            closed = False
            for seg in sub:
                if isinstance(seg, se.Move):
                    if pts:
                        _finish([(x * k, y * k) for x, y in pts], closed, result)
                    pts, closed = [(seg.end.x, seg.end.y)], False
                elif isinstance(seg, se.Close):
                    closed = True
                elif isinstance(seg, (se.Line,)):
                    pts.append((seg.end.x, seg.end.y))
                else:  # CubicBezier, QuadraticBezier, Arc
                    try:
                        length = seg.length(error=1e-4)
                    except Exception:  # noqa: BLE001 - degenerierte Kurve
                        length = math.dist((seg.start.x, seg.start.y), (seg.end.x, seg.end.y))
                    radius = None
                    if isinstance(seg, se.Arc):
                        try:
                            radius = min(abs(seg.rx), abs(seg.ry)) * k
                        except Exception:  # noqa: BLE001
                            radius = None
                    n = _segments_for(length * k, radius, tolerance_mm)
                    for i in range(1, n + 1):
                        q = seg.point(i / n)
                        pts.append((q.x, q.y))
            if pts:
                _finish([(x * k, y * k) for x, y in pts], closed, result)
    return result


# ---------------------------------------------------------------- DXF
DXF_TYPES = ("LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE")
_MM = 4  # ezdxf.units.MM


def dxf_unit_factor(insunits: int) -> float:
    """$INSUNITS → Faktor nach mm; 0 (ohne Einheit) gilt als mm."""
    from ezdxf import units
    if not insunits:
        return 1.0
    try:
        return float(units.conversion_factor(int(insunits), _MM))
    except Exception:  # noqa: BLE001 - unbekannte Einheit
        return 1.0


def load_dxf(path, tolerance_mm: float = DEFAULT_TOLERANCE_MM) -> VectorImport:
    """DXF → Polylinien in mm (Modellbereich, Blöcke werden aufgelöst).

    LINE, LWPOLYLINE (inkl. Bögen/bulge), POLYLINE (2D), CIRCLE, ARC,
    ELLIPSE und SPLINE. Andere Objekte (Text, Bemaßung, Schraffur …) werden
    gezählt und übersprungen.
    """
    import ezdxf
    from ezdxf import path as ezpath
    from ezdxf import recover

    try:
        doc = ezdxf.readfile(os.fspath(path))
    except ezdxf.DXFStructureError:
        doc, _auditor = recover.readfile(os.fspath(path))
    factor = dxf_unit_factor(doc.header.get("$INSUNITS", 0))
    result = VectorImport()
    raw: list[tuple[list[tuple[float, float]], bool]] = []

    def visit(entity, depth: int = 0) -> None:
        kind = entity.dxftype()
        if kind == "INSERT" and depth < 8:
            try:
                for sub in entity.virtual_entities():
                    visit(sub, depth + 1)
            except Exception:  # noqa: BLE001 - kaputter Block
                result.skip("Block")
            return
        if kind not in DXF_TYPES:
            result.skip(kind)
            return
        if kind == "POLYLINE" and not entity.is_2d_polyline and not entity.is_3d_polyline:
            result.skip("POLYLINE (Netz)")
            return
        try:
            p = ezpath.make_path(entity)
        except Exception:  # noqa: BLE001
            result.skip(kind)
            return
        closed_entity = kind in ("CIRCLE",) or (kind == "ELLIPSE" and _full_ellipse(entity)) or \
            bool(getattr(entity, "closed", False)) or \
            (kind == "POLYLINE" and entity.is_closed) or \
            (kind == "SPLINE" and entity.closed)
        for sp in p.sub_paths():
            pts = [(v.x * factor, v.y * factor)
                   for v in sp.flattening(distance=tolerance_mm / max(factor, 1e-9))]
            closed = closed_entity or sp.is_closed
            raw.append((pts, closed))

    for e in doc.modelspace():
        visit(e)
    for pts, closed in raw:
        # y nach oben → Canvas y nach unten (Ursprung links unten).
        _finish([(x, WORK_HEIGHT_MM - y) for x, y in pts], closed, result)
    return result


def _full_ellipse(e) -> bool:
    span = (e.dxf.end_param - e.dxf.start_param) % (2 * math.pi)
    return span < 1e-9 or abs(span - 2 * math.pi) < 1e-9
