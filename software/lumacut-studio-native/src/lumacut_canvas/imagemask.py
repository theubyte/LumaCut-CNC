"""Live image mask (LightBurn *Tools › Apply Mask to Image* / *Remove Mask*).

Unlike :mod:`imagecrop` (destructive *Crop Image*), the mask is stored on the image
(:attr:`model.RasterImage.mask`) and the original pixels stay untouched:

* **Apply**: the selected closed shapes (rectangle, ellipse, polygon / star, text, closed
  paths – several shapes and holes combine by the even-odd rule like a fill) become the
  image's mask. Their outlines are flattened (0.01 mm) and stored normalised to the image's
  unrotated box, so moving, scaling and rotating the image carries the mask along. The shapes
  are taken into the image (LightBurn hides the mask shape the same way).
* **View / job**: :attr:`RasterImage.view_png` is the PNG with the mask applied – pixels whose
  centre lies outside become transparent (alpha 0, grey 255) – so the canvas, the job, the
  dialog preview, frame, estimate, SVG / PNG export and tracing use the same paths as a
  cropped image (transparent pixels never burn). The box keeps its size.
* **Release**: the mask comes back as one closed polygon (with all rings) on the layer the
  shape came from, the image is whole again. Edit the outline and apply it again – that is
  how the mask is moved or reshaped.
* **Several masks** (round 104): applying shapes to an image that already has a mask narrows
  it – the new mask is the overlap of the old one and the shapes (two masks on top of each
  other, like applying LightBurn's mask a second time to the masked result). **Hide**
  (``mode="hide"``, „Bereich im Bild ausblenden“) is the opposite: the shapes' area becomes
  transparent and the rest stays – the inverse mask, e.g. to take a logo, a date stamp or a
  background corner out of a photo; on a masked image it punches further holes. Both combine
  in any order; the result is stored as one set of even-odd rings (exterior + holes), so
  release, project files, view and job need nothing new. Several selected images take the
  same shapes at once (:class:`imagemask_ui.ImageMask`).

A plain first „Maske auf Bild anwenden“ stores the shapes' rings exactly as before (no
polygon operation), so masks of round 100 stay byte-identical.

Images without a mask (every image before this feature) are unchanged byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from .imagecrop import CropError, _bytes_of, canvas_to_pixels, decode_png, encode_png, mask_shapes
from .model import Shape

FLATTEN_TOL_MM = 0.01
MAX_MASK_POINTS = 200_000
MODES = ("keep", "hide")       # keep = show inside the shapes (mask), hide = make them transparent
MIN_AREA_PX2 = 1e-6            # slivers of the polygon operations below this are dropped


class MaskError(CropError):
    """User-facing reason why the mask was not applied / released (German text)."""


@dataclass
class MaskResult:
    shape: Shape            # the image with the mask (same id)
    kept_share: float       # share of the visible pixels that stay visible (0..1)
    rings: int              # number of mask rings
    points: int             # number of mask points


# ------------------------------------------------------------------------- raster

def _pixel_path(w: int, h: int, mask):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainterPath, QPolygonF
    path = QPainterPath()
    for ring in mask:
        path.addPolygon(QPolygonF([QPointF(u * w, v * h) for u, v in ring]))
        path.closeSubpath()
    path.setFillRule(Qt.OddEvenFill)
    return path


def mask_inside(w: int, h: int, mask) -> np.ndarray:
    """Bool array (h × w): pixel centre inside the even-odd area of the normalised rings."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    canvas = QImage(w, h, QImage.Format_Grayscale8)
    canvas.fill(QColor(0, 0, 0))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(Qt.NoPen)
    p.fillPath(_pixel_path(w, h, mask), QColor(255, 255, 255))
    p.end()
    return _bytes_of(canvas, h)[:, :w] >= 128


@lru_cache(maxsize=32)
def _masked(png: bytes, w: int, h: int, mask: tuple) -> bytes:
    gray, alpha = decode_png(png)
    ph, pw = gray.shape
    inside = mask_inside(pw, ph, mask)
    base = np.full(gray.shape, 255, np.uint8) if alpha is None else alpha
    new_alpha = np.where(inside, base, 0).astype(np.uint8)
    new_gray = np.where(new_alpha > 0, gray, 255).astype(np.uint8)
    if bool((new_alpha == 255).all()):
        return encode_png(new_gray)
    return encode_png(new_gray, new_alpha)


def masked_png(png: bytes, w: int, h: int, mask) -> bytes:
    """``png`` with the mask applied (cached – the canvas asks on every repaint)."""
    if not mask:
        return png
    return _masked(png, int(w), int(h), tuple(tuple(map(tuple, r)) for r in mask))


# ------------------------------------------------------------------------- apply / release

def mask_rings(image: Shape, shapes) -> tuple:
    """Outlines of ``shapes`` in canvas mm → rings normalised to the image's unrotated box."""
    from PySide6.QtCore import QPointF

    from .shape_paths import shape_polygons
    to_px = canvas_to_pixels(image)
    w, h = image.image.px_width, image.image.px_height
    rings = []
    for s in shapes:
        for pts in shape_polygons(s, FLATTEN_TOL_MM):
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            if len(pts) < 3:
                continue
            ring = []
            for x, y in pts:
                q = to_px.map(QPointF(x, y))
                ring.append((q.x() / w, q.y() / h))
            rings.append(tuple(ring))
    return tuple(rings)


def ring_area(rings, w: int, h: int) -> BaseGeometry:
    """Even-odd area of normalised ``rings`` in pixel units (shapely) – like :func:`mask_inside`."""
    area: BaseGeometry = Polygon()
    for ring in rings:
        if len(ring) < 3:
            continue
        area = area.symmetric_difference(Polygon([(u * w, v * h) for u, v in ring]).buffer(0))
    return area


def area_rings(area: BaseGeometry, w: int, h: int) -> tuple:
    """Area in pixel units → normalised rings (every polygon's exterior and holes, even-odd)."""
    if area.is_empty:
        return ()
    if isinstance(area, Polygon):
        polys = [area]
    elif isinstance(area, MultiPolygon):
        polys = list(area.geoms)
    else:
        polys = [g for g in getattr(area, "geoms", ()) if isinstance(g, (Polygon, MultiPolygon))]
        polys = [p for g in polys for p in (g.geoms if isinstance(g, MultiPolygon) else [g])]
    rings = []
    for p in polys:
        if p.area <= MIN_AREA_PX2:
            continue
        for ring in (p.exterior, *p.interiors):
            pts = [(float(x) / w, float(y) / h) for x, y in ring.coords]
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if len(pts) >= 3:
                rings.append(tuple(pts))
    return tuple(rings)


def combine_rings(old: tuple, new: tuple, mode: str, w: int, h: int) -> tuple:
    """Rings of the combined mask: ``old`` (empty = whole image) narrowed by ``new``.

    ``keep``: overlap of the old visible area and the shapes; ``hide``: the old visible area
    without the shapes. A first ``keep`` mask returns ``new`` unchanged."""
    if mode not in MODES:
        raise ValueError(f"unknown mask mode {mode!r}")
    if mode == "keep" and not old:
        return tuple(new)
    box = Polygon([(0, 0), (w, 0), (w, h), (0, h)])
    base = ring_area(old, w, h).intersection(box) if old else box
    shapes = ring_area(new, w, h)
    area = base.intersection(shapes) if mode == "keep" else base.difference(shapes)
    return area_rings(area, w, h)


def apply_mask(image: Shape, shapes, mode: str = "keep") -> MaskResult:
    """Image with the even-odd area of ``shapes`` as live mask (see module doc).

    ``mode="keep"`` shows only the inside of the shapes, ``mode="hide"`` makes the inside
    transparent. An existing mask is narrowed (overlap resp. further holes)."""
    if mode not in MODES:
        raise ValueError(f"unknown mask mode {mode!r}")
    if image.kind != "image" or image.image is None:
        raise MaskError("Für die Maske ein Bild auswählen.")
    masks = mask_shapes(shapes)
    if not masks:
        raise MaskError("Für die Maske eine geschlossene Form (Rechteck, Ellipse, Vieleck, Text "
                        "oder geschlossener Pfad) zusammen mit dem Bild auswählen.")
    lb = image.geom.local_bounds()
    if lb.w <= 0 or lb.h <= 0:
        raise MaskError("Das Bild hat keine Fläche.")
    gray, alpha = decode_png(image.image.png)
    h, w = gray.shape
    if (w, h) != (image.image.px_width, image.image.px_height):
        image = replace(image, image=replace(image.image, px_width=w, px_height=h))
    new = mask_rings(image, masks)
    if not new:
        raise MaskError("Die Form hat keine Fläche.")
    old = tuple(image.image.mask)
    shown = np.ones((h, w), bool) if alpha is None else alpha > 0
    before = shown & mask_inside(w, h, old) if old else shown
    shape_inside = mask_inside(w, h, new)
    if not (shape_inside & before).any():
        raise MaskError("Die Form überdeckt das Bild nicht – Form über das Bild legen."
                        if not old else
                        "Die Form überdeckt den sichtbaren Teil des Bildes nicht – Form über "
                        "den sichtbaren Teil legen.")
    rings = combine_rings(old, new, mode, w, h)
    points = sum(len(r) for r in rings)
    if points > MAX_MASK_POINTS:
        raise MaskError(f"Die Maske hat zu viele Punkte ({points}) – Form erst vereinfachen.")
    visible = shown & mask_inside(w, h, rings) if rings else np.zeros((h, w), bool)
    if not visible.any():
        raise MaskError("Die Form verdeckt den ganzen sichtbaren Teil – es bliebe nichts übrig."
                        if mode == "hide" else
                        "Die Form überdeckt den sichtbaren Teil des Bildes nicht – Form über "
                        "den sichtbaren Teil legen.")
    if np.array_equal(visible, before):
        raise MaskError("Die Form deckt das ganze Bild ab – nichts zu maskieren." if not old
                        else "Die Form ändert die Maske nicht – nichts zu maskieren.")
    layer = image.image.mask_layer if old and image.image.mask_layer else masks[0].layer_id
    out = replace(image, image=replace(image.image, mask=rings, mask_layer=layer))
    share = int(np.count_nonzero(visible)) / int(np.count_nonzero(shown))
    return MaskResult(out, share, len(rings), points)


def mask_outline(image: Shape, layer_id: str) -> Shape:
    """The image's mask as one closed ``polygon`` (all rings) in canvas mm on ``layer_id``."""
    from PySide6.QtCore import QPointF

    from .shape_paths import geometry_transform
    if image.kind != "image" or image.image is None or not image.image.mask:
        raise MaskError("Das Bild hat keine Maske.")
    lb = image.geom.local_bounds()
    t = geometry_transform(image.geom)
    pts: list[tuple[float, float]] = []
    starts: list[int] = []
    for ring in image.image.mask:
        if pts:
            starts.append(len(pts))
        for u, v in ring:
            q = t.map(QPointF(lb.x + u * lb.w, lb.y + v * lb.h))
            pts.append((q.x(), q.y()))
    s = Shape.from_points("polygon", pts, layer_id, rings=starts)
    s.groups = image.groups
    return s


def release_mask(image: Shape, layer_id: str) -> tuple[Shape, Shape]:
    """(image without mask, mask outline on ``layer_id``)."""
    outline = mask_outline(image, layer_id)
    whole = replace(image, image=replace(image.image, mask=(), mask_layer=""))
    return whole, outline


__all__ = ["MODES", "MaskError", "MaskResult", "apply_mask", "area_rings", "combine_rings",
           "mask_inside", "mask_outline", "mask_rings", "masked_png", "release_mask", "ring_area"]
