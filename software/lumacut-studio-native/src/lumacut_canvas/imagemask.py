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

Images without a mask (every image before this feature) are unchanged byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

import numpy as np

from .imagecrop import CropError, _bytes_of, canvas_to_pixels, decode_png, encode_png, mask_shapes
from .model import Shape

FLATTEN_TOL_MM = 0.01
MAX_MASK_POINTS = 200_000


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


def apply_mask(image: Shape, shapes) -> MaskResult:
    """Image with the even-odd area of ``shapes`` as live mask (see module doc)."""
    if image.kind != "image" or image.image is None:
        raise MaskError("Für die Maske ein Bild auswählen.")
    if image.image.mask:
        raise MaskError("Das Bild hat schon eine Maske – erst „Bildmaske lösen“, die Form "
                        "ändern und dann neu anwenden.")
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
    rings = mask_rings(image, masks)
    points = sum(len(r) for r in rings)
    if not rings:
        raise MaskError("Die Form hat keine Fläche.")
    if points > MAX_MASK_POINTS:
        raise MaskError(f"Die Maske hat zu viele Punkte ({points}) – Form erst vereinfachen.")
    inside = mask_inside(w, h, rings)
    shown = np.ones((h, w), bool) if alpha is None else alpha > 0
    visible = inside & shown
    if not visible.any():
        raise MaskError("Die Form überdeckt das Bild nicht – Form über das Bild legen.")
    if np.array_equal(visible, shown):
        raise MaskError("Die Form deckt das ganze Bild ab – nichts zu maskieren.")
    layer = masks[0].layer_id
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


__all__ = ["MaskError", "MaskResult", "apply_mask", "mask_inside", "mask_outline", "mask_rings",
           "masked_png", "release_mask"]
