"""xTool-Projekte importieren: ``.xcs`` (JSON) und ``.xs`` (ZIP, Studio ≥ 1.7).

Das Format ist nicht offiziell dokumentiert; die Regeln unten sind an echten
Dateien aus xTool Creative Space / xTool Studio 1.6–1.7 nachgemessen:

* ``.xcs``: eine JSON-Datei, Objekte in ``canvas[*].displays``.
* ``.xs``: ZIP mit ``canvases/<id>/displays-<n>.json``; lange Pfade liegen in
  ``vectors/<bucket>/data-<n>.json`` (Verweis ``vectorRef``), Bilder als
  Dateien unter ``resources/`` (Verweis ``resourcePath``).
* Koordinaten in mm, Ursprung links oben (wie der Canvas).
* ``x``/``y`` = linke obere Ecke, ``width``/``height`` = Größe in mm;
  ``angle`` dreht im Uhrzeigersinn um (``x``, ``y``).
* PATH: Weltpunkt = (``offsetX``, ``offsetY``) + ``scale`` · Punkt aus
  ``dPath`` (SVG-Pfadsyntax). Fehlt der Versatz, wird die Pfadbox in die
  Objektbox eingepasst.
* TEXT: die Glyphen liegen als PATH-Objekte in ``charJSONs`` – sie werden als
  Konturen übernommen (sieht aus wie in xTool, auch ohne die Schrift). Ohne
  Glyphen entsteht ein bearbeitbares Textobjekt in der Box.

Übernommen werden RECT (auch abgerundet), CIRCLE/ELLIPSE, LINE, PATH, PEN,
POLYGON/STAR (über ``dPath`` bzw. ``points``), TEXT und BITMAP. Laserwerte aus
``device`` werden bewusst nicht übernommen – die kommen aus der Materialwahl.
Ausgeblendete Objekte werden übersprungen; alles Unbekannte wird gezählt und
in der Statuszeile gemeldet, nie stillschweigend verworfen.
"""

from __future__ import annotations

import base64
import json
import math
import os
import zipfile
from dataclasses import dataclass, field

from lumacut_canvas.model import Geometry, RasterImage, Shape

from .vector import DEFAULT_TOLERANCE_MM, _segments_for

MAX_JSON_BYTES = 200 * 1024 * 1024
ARC_TOLERANCE_MM = 0.02


@dataclass
class XToolImport:
    """Objekte in xTool-Koordinaten (mm, noch nicht platziert)."""

    shapes: list[Shape] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    kinds: dict[str, int] = field(default_factory=dict)

    def skip(self, kind: str) -> None:
        self.skipped[kind] = self.skipped.get(kind, 0) + 1

    def notes(self) -> list[str]:
        return [f"{n}× {k} übersprungen" for k, n in sorted(self.skipped.items())]


# ------------------------------------------------------------------ Laden
def _read_xcs(path) -> list[dict]:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_JSON_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"xTool-Datei nicht lesbar: {exc}") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("xTool-Datei ist zu groß (über 200 MB)")
    if raw[:2] == b"PK":
        # Neuere xTool-Versionen speichern auch unter .xcs gelegentlich ZIP.
        return _read_xs(path)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Keine gültige xTool-.xcs-Datei (kein JSON) – bitte in "
                         "xTool als SVG exportieren und das SVG importieren") from exc
    canvases = data.get("canvas") if isinstance(data, dict) else None
    if not isinstance(canvases, list):
        raise ValueError("xTool-.xcs-Datei ohne Zeichenfläche („canvas“) – "
                         "Format unbekannt, bitte in xTool als SVG exportieren")
    displays: list[dict] = []
    for canvas in canvases[:1]:  # xTool: ein Projekt = eine Zeichenfläche
        if isinstance(canvas, dict) and isinstance(canvas.get("displays"), list):
            displays.extend(d for d in canvas["displays"] if isinstance(d, dict))
    return displays


def _read_xs(path) -> list[dict]:
    try:
        zf = zipfile.ZipFile(os.fspath(path))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("Keine gültige xTool-.xs-Datei (kein ZIP-Archiv) – bitte "
                         "in xTool als SVG exportieren und das SVG importieren") from exc
    with zf:
        names = zf.namelist()

        def load(name):
            info = zf.getinfo(name)
            if info.file_size > MAX_JSON_BYTES:
                raise ValueError(f"xTool-Datei: {name} ist zu groß")
            return json.loads(zf.read(name).decode("utf-8-sig"))

        chunks = [n for n in names if n.startswith("canvases/") and
                  os.path.basename(n).startswith("displays-") and n.endswith(".json")]
        if not chunks:
            raise ValueError("xTool-.xs-Datei ohne Objekte (keine canvases/…/displays-*.json) "
                             "– Format unbekannt, bitte in xTool als SVG exportieren")
        canvas_ids = sorted({n.split("/")[1] for n in chunks})
        first = canvas_ids[0]

        def chunk_index(name):
            stem = os.path.basename(name)[len("displays-"):-len(".json")]
            return int(stem) if stem.isdigit() else 0

        displays: list[dict] = []
        try:
            for name in sorted((n for n in chunks if n.split("/")[1] == first), key=chunk_index):
                part = load(name)
                items = part.get("displays") if isinstance(part, dict) else part
                displays.extend(d for d in items or [] if isinstance(d, dict))
            vectors: dict[str, dict[str, str]] = {}
            for name in names:
                parts = name.split("/")
                if len(parts) == 3 and parts[0] == "vectors" and parts[2].startswith("data-") \
                        and parts[2].endswith(".json"):
                    entries = load(name)
                    if isinstance(entries, dict):
                        entries = entries.get("entries", entries)
                        vectors.setdefault(parts[1], {}).update(
                            {k: v for k, v in entries.items() if isinstance(v, str)})
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"xTool-.xs-Datei beschädigt: {exc}") from exc

        def resolve(d: dict) -> None:
            ref = d.get("vectorRef")
            if isinstance(ref, dict):
                bucket = vectors.get(str(ref.get("bucketType", "svg")), {})
                value = bucket.get(str(ref.get("vectorHash", "")))
                if value is not None:
                    d.setdefault(str(ref.get("originalField", "dPath")), value)
            res = d.get("resourcePath")
            if isinstance(res, str) and not d.get("base64") and res in names:
                info = zf.getinfo(res)
                if info.file_size <= MAX_JSON_BYTES:
                    d["_resource_bytes"] = zf.read(res)
            for ch in d.get("charJSONs") or []:
                if isinstance(ch, dict):
                    resolve(ch)

        for d in displays:
            resolve(d)
    return displays


# ------------------------------------------------------------------ Geometrie
def _f(d: dict, key: str, default: float = 0.0) -> float:
    try:
        v = float(d.get(key, default))
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _xy(v, default=(1.0, 1.0)) -> tuple[float, float]:
    if isinstance(v, dict):
        try:
            return float(v.get("x", default[0])), float(v.get("y", default[1]))
        except (TypeError, ValueError):
            return default
    return default


def _rotator(d: dict):
    """Funktion Punkt → Punkt: Drehung um (x, y) um ``angle`` (Uhrzeigersinn)."""
    ang = _f(d, "angle") % 360.0
    if abs(ang) < 1e-9 or abs(ang - 360.0) < 1e-9:
        return lambda p: p
    ox, oy = _f(d, "x"), _f(d, "y")
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    return lambda p: (ox + (p[0] - ox) * c - (p[1] - oy) * s,
                      oy + (p[0] - ox) * s + (p[1] - oy) * c)


def _box_geom(d: dict) -> Geometry | None:
    """Objektbox (x, y, w, h, angle um x/y) → Geometry (Drehung um Boxmitte)."""
    w, h = _f(d, "width"), _f(d, "height")
    if w <= 1e-9 or h <= 1e-9:
        return None
    x, y, ang = _f(d, "x"), _f(d, "y"), _f(d, "angle")
    cx, cy = _rotator(d)((x + w / 2, y + h / 2))
    return Geometry(cx - w / 2, cy - h / 2, w, h, ang % 360.0)


def _subpaths(d_attr: str, tol: float, k: float = 1.0) -> list[tuple[list[tuple[float, float]], bool]]:
    import svgelements as se

    path = se.Path(d_attr)
    out: list[tuple[list[tuple[float, float]], bool]] = []
    for sub in path.as_subpaths():
        pts: list[tuple[float, float]] = []
        closed = False
        for seg in sub:
            if isinstance(seg, se.Move):
                if pts:
                    out.append((pts, closed))
                pts, closed = [(float(seg.end.x), float(seg.end.y))], False
            elif isinstance(seg, se.Close):
                closed = True
            elif isinstance(seg, se.Line):
                pts.append((float(seg.end.x), float(seg.end.y)))
            else:
                try:
                    length = seg.length(error=1e-4)
                except Exception:  # noqa: BLE001 - degenerierte Kurve
                    length = math.dist((seg.start.x, seg.start.y), (seg.end.x, seg.end.y))
                n = _segments_for(length * k, None, tol)
                pts.extend((float(q.x), float(q.y)) for q in (seg.point(i / n) for i in range(1, n + 1)))
        if pts:
            out.append((pts, closed))
    return out


def _path_world(d: dict, subs):
    """Lokale Pfadpunkte → mm (Versatz + Skalierung, sonst Box einpassen)."""
    sx, sy = _xy(d.get("scale"))
    rot = _rotator(d)
    if "offsetX" in d and "offsetY" in d:
        ox, oy = _f(d, "offsetX"), _f(d, "offsetY")
        tf = lambda p: rot((ox + sx * p[0], oy + sy * p[1]))  # noqa: E731
    else:
        xs = [p[0] for pts, _ in subs for p in pts]
        ys = [p[1] for pts, _ in subs for p in pts]
        x0, y0 = min(xs), min(ys)
        bw, bh = max(xs) - x0, max(ys) - y0
        w, h = _f(d, "width"), _f(d, "height")
        kx = w / bw if bw > 1e-9 and w > 1e-9 else sx
        ky = h / bh if bh > 1e-9 and h > 1e-9 else sy
        X, Y = _f(d, "x"), _f(d, "y")
        tf = lambda p: rot((X + (p[0] - x0) * kx, Y + (p[1] - y0) * ky))  # noqa: E731
    return [([tf(p) for p in pts], closed) for pts, closed in subs]


def _shapes_from_rings(rings, layer_id: str) -> list[Shape]:
    """Geschlossene Ringe → ein Polygon (mit Löchern), offene → je ein Pfad."""
    shapes: list[Shape] = []
    closed = [pts for pts, c in rings if c and len(pts) >= 3]
    if closed:
        flat, starts = [], []
        for pts in closed:
            if flat:
                starts.append(len(flat))
            if len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-9:
                pts = pts[:-1]
            flat.extend(pts)
        shapes.append(Shape.from_points("polygon", flat, layer_id, rings=starts))
    for pts, c in rings:
        if not c and len(pts) >= 2:
            shapes.append(Shape.from_points("path", pts, layer_id))
        elif c and len(pts) == 2:
            shapes.append(Shape.from_points("path", pts, layer_id))
    return shapes


def _rounded_rect(d: dict, r: float, layer_id: str) -> list[Shape]:
    w, h = _f(d, "width"), _f(d, "height")
    r = min(r, w / 2, h / 2)
    x, y = _f(d, "x"), _f(d, "y")
    n = max(4, math.ceil((math.pi / 2) / (2 * math.acos(max(-1.0, 1 - ARC_TOLERANCE_MM / r)))))
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90.0), (x + w - r, y + h - r, 0.0),
                       (x + r, y + h - r, 90.0), (x + r, y + r, 180.0)):
        for i in range(n + 1):
            a = math.radians(a0 + 90.0 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    rot = _rotator(d)
    return [Shape.from_points("polygon", [rot(p) for p in pts], layer_id)]


def _bitmap(d: dict, layer_id: str) -> Shape | None:
    from PySide6.QtGui import QImage
    from PySide6.QtCore import Qt

    from .image import MAX_PIXELS_LONG_SIDE, grayscale_png

    raw = d.get("_resource_bytes")
    if raw is None:
        data = d.get("base64")
        if not isinstance(data, str) or not data:
            return None
        if data.startswith("data:"):
            data = data.split(",", 1)[-1]
        try:
            raw = base64.b64decode(data, validate=False)
        except (ValueError, TypeError):
            return None
    img = QImage.fromData(raw)
    if img.isNull():
        return None
    w, h = _f(d, "width"), _f(d, "height")
    if w <= 0 or h <= 0:
        sx, sy = _xy(d.get("scale"))
        w, h = img.width() * sx, img.height() * sy
    long_side = max(img.width(), img.height())
    if long_side > MAX_PIXELS_LONG_SIDE:
        img = img.scaled(img.width() * MAX_PIXELS_LONG_SIDE // long_side,
                         img.height() * MAX_PIXELS_LONG_SIDE // long_side,
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    png, pw, ph = grayscale_png(img)
    geom = _box_geom({**d, "width": w, "height": h})
    if geom is None:
        return None
    return Shape("image", geom, layer_id, image=RasterImage(png, pw, ph))


def _display_shapes(d: dict, layer_id: str, res: XToolImport, tol: float) -> list[Shape]:
    kind = str(d.get("type", "")).upper()
    if kind in ("RECT", "SQUARE"):
        r = _f(d, "radius")
        if r > 1e-6:
            return _rounded_rect(d, r, layer_id)
        g = _box_geom(d)
        return [Shape("rect", g, layer_id)] if g else []
    if kind in ("CIRCLE", "ELLIPSE"):
        g = _box_geom(d)
        return [Shape("ellipse", g, layer_id)] if g else []
    if kind == "LINE":
        x, y = _f(d, "x"), _f(d, "y")
        ex, ey = _xy(d.get("endPoint"), (_f(d, "width"), 0.0))
        sx, _ = _xy(d.get("scale"))
        p0, p1 = (x, y), _rotator(d)((x + ex * sx, y + ey))
        if math.dist(p0, p1) < 1e-6:
            return []
        return [Shape("line", Geometry(x, y, p1[0] - x, p1[1] - y), layer_id)]
    if kind == "TEXT":
        glyphs = [c for c in d.get("charJSONs") or [] if isinstance(c, dict) and c.get("dPath")]
        rings = []
        for g in glyphs:
            subs = _subpaths(str(g["dPath"]), tol, max(abs(_xy(g.get("scale"))[0]), 1e-6))
            if subs:
                rings.extend(_path_world(g, subs))
        if rings:
            return _shapes_from_rings(rings, layer_id)
        g = _box_geom(d)
        text = str(d.get("text") or "").strip()
        if g is None or not text:
            return []
        style = d.get("style") if isinstance(d.get("style"), dict) else {}
        sub = str(style.get("fontSubfamily", "")).lower()
        return [Shape("text", g, layer_id, text=text,
                      font_family=str(style.get("fontFamily") or "Segoe UI"),
                      font_bold="bold" in sub, font_italic="italic" in sub)]
    if kind == "BITMAP":
        sh = _bitmap(d, layer_id)
        return [sh] if sh else []
    if d.get("dPath"):
        sx, sy = _xy(d.get("scale"))
        subs = _subpaths(str(d["dPath"]), tol, max(abs(sx), abs(sy), 1e-6))
        if not subs:
            return []
        rings = _path_world(d, subs)
        if d.get("isClosePath") is True:
            rings = [(pts, True) for pts, _ in rings]
        return _shapes_from_rings(rings, layer_id)
    pts = d.get("points")
    if isinstance(pts, list) and len(pts) >= 2:
        try:
            local = [(float(p["x"]), float(p["y"])) for p in pts]
        except (KeyError, TypeError, ValueError):
            return []
        rings = _path_world(d, [(local, bool(d.get("isClosePath")))])
        return _shapes_from_rings(rings, layer_id)
    return []


def load_xtool(path, layer_id: str, tolerance_mm: float = DEFAULT_TOLERANCE_MM) -> XToolImport:
    """``.xcs``/``.xs`` lesen → Canvas-Objekte in xTool-Koordinaten (mm)."""
    suffix = os.path.splitext(os.fspath(path))[1].lower()
    displays = _read_xs(path) if suffix == ".xs" else _read_xcs(path)
    res = XToolImport()
    displays = sorted(displays, key=lambda d: _f(d, "zOrder"))
    for d in displays:
        kind = str(d.get("type", "?")).upper() or "?"
        if d.get("visible") is False or d.get("visibleState") is False:
            res.skip(f"ausgeblendet ({kind})")
            continue
        try:
            shapes = _display_shapes(d, layer_id, res, tolerance_mm)
        except (ValueError, TypeError, KeyError, ZeroDivisionError):
            shapes = []
        if not shapes:
            res.skip(_LABELS.get(kind, kind))
            continue
        res.kinds[kind] = res.kinds.get(kind, 0) + 1
        res.shapes.extend(shapes)
    if not res.shapes:
        if res.skipped:
            raise ValueError("xTool-Datei: nichts importierbar (" + ", ".join(res.notes())
                             + ") – bitte in xTool als SVG exportieren")
        raise ValueError("xTool-Datei enthält keine Objekte")
    return res


_LABELS = {"TEXT": "Text", "BITMAP": "Bild", "PATH": "Pfad", "LINE": "Linie",
           "RECT": "Rechteck", "CIRCLE": "Kreis"}
