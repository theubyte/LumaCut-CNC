"""Crop an image object to vector shapes (LightBurn *Tools › Crop Image*, xTool „Zuschneiden“).

The selected closed shapes (rectangle, ellipse, polygon / star, text, closed paths) form a
mask; several shapes and the sub-paths of one shape combine by the even-odd rule like a
fill, so a circle inside a rectangle leaves a ring and a text keeps its counters (LightBurn
masks a group of nested shapes the same way). Pixels outside the mask become transparent
(alpha 0, grey value white) and the image is cut down to the box of what is left, so the
job, frame and estimate only cover the kept part. The pixel size in mm and the rotation stay;
the image keeps its id, layer, groups and engraving settings.

Transparent pixels never burn: the job and the dialog preview paint the image over the
„do not burn“ value (white, black with *Negativ* – :func:`lumacut_job.images.render_gray`)
and the inside mask of adjustments / sketch follows the alpha channel
(:func:`lumacut_job.images.render_inside`). Images without alpha (every image before this
feature – imports flatten transparency to white) take the unchanged code path.

The PNG is written here as 8-bit grey + alpha (colour type 4), or plain 8-bit grey when the
crop left no transparent pixel (a rectangle along the pixel grid).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, replace

import numpy as np

from .model import FILLABLE_KINDS, Geometry, Shape, rotate_point

MASK_KINDS = FILLABLE_KINDS


class CropError(ValueError):
    """User-facing reason why nothing was cropped (German text)."""


@dataclass
class CropResult:
    shape: Shape            # the cropped image (same id)
    kept_share: float       # share of the old image's pixels that stay visible (0..1)
    px: tuple[int, int]     # new pixel size (width, height)
    transparent: bool       # the PNG carries an alpha channel


# ------------------------------------------------------------------------- PNG helpers

def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode_png(gray: np.ndarray, alpha: np.ndarray | None = None) -> bytes:
    """8-bit grey (``alpha`` None) or grey + alpha PNG of a ``uint8`` array."""
    gray = np.ascontiguousarray(gray, dtype=np.uint8)
    h, w = gray.shape
    if alpha is None:
        raw, ctype = gray, 0
    else:
        raw = np.dstack([gray, np.asarray(alpha, dtype=np.uint8)]).reshape(h, w * 2)
        ctype = 4
    rows = np.hstack([np.zeros((h, 1), np.uint8), raw])   # filter byte 0 per row
    ihdr = struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 9)) + _chunk(b"IEND", b""))


def _bytes_of(img, h: int) -> np.ndarray:
    stride = img.bytesPerLine()
    return np.frombuffer(img.constBits(), dtype=np.uint8, count=stride * h).reshape(h, stride)


def decode_png(png: bytes) -> tuple[np.ndarray, np.ndarray | None]:
    """PNG → (grey ``uint8``, alpha ``uint8`` or None when the image has no alpha)."""
    from PySide6.QtGui import QImage

    from .image_cache import qimage_for
    img = qimage_for(png)
    if img.isNull():
        raise CropError("Bilddaten beschädigt")
    w, h = img.width(), img.height()
    g8 = img.convertToFormat(QImage.Format_Grayscale8)   # keep alive while reading its bits
    gray = _bytes_of(g8, h)[:, :w].copy()
    if not img.hasAlphaChannel():
        return gray, None
    a8 = img.convertToFormat(QImage.Format_Alpha8)
    alpha = _bytes_of(a8, h)[:, :w].copy()
    return gray, alpha


# ------------------------------------------------------------------------- mask

def mask_shapes(shapes) -> list[Shape]:
    """The shapes that can serve as a mask (closed, not images)."""
    return [s for s in shapes if s.kind in MASK_KINDS]


def mask_path(shapes):
    """All mask outlines in canvas mm (with rotation) as one even-odd path."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainterPath

    from .shape_paths import shape_path
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for s in shapes:
        path.addPath(shape_path(s))
    path.setFillRule(Qt.OddEvenFill)
    return path


def canvas_to_pixels(image: Shape):
    """QTransform canvas mm → pixel coordinates of the image's PNG."""
    from PySide6.QtGui import QTransform

    from .shape_paths import geometry_transform
    lb = image.geom.local_bounds()
    inv, _ok = geometry_transform(image.geom).inverted()
    return (inv * QTransform.fromTranslate(-lb.x, -lb.y)
            * QTransform.fromScale(image.image.px_width / lb.w, image.image.px_height / lb.h))


def mask_pixels(image: Shape, shapes) -> np.ndarray:
    """Bool array (px_height × px_width): pixel centre inside the mask."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    w, h = image.image.px_width, image.image.px_height
    canvas = QImage(w, h, QImage.Format_Grayscale8)
    canvas.fill(QColor(0, 0, 0))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setTransform(canvas_to_pixels(image))
    p.setPen(Qt.NoPen)
    p.fillPath(mask_path(shapes), QColor(255, 255, 255))
    p.end()
    return _bytes_of(canvas, h)[:, :w] >= 128


# ------------------------------------------------------------------------- crop

def crop_image(image: Shape, shapes) -> CropResult:
    """Image cropped to the even-odd area of ``shapes`` (see module doc)."""
    if image.kind != "image" or image.image is None:
        raise CropError("Zum Zuschneiden ein Bild auswählen.")
    masks = mask_shapes(shapes)
    if not masks:
        raise CropError("Zum Zuschneiden eine geschlossene Form (Rechteck, Ellipse, Vieleck, "
                        "Text oder geschlossener Pfad) zusammen mit dem Bild auswählen.")
    lb = image.geom.local_bounds()
    if lb.w <= 0 or lb.h <= 0:
        raise CropError("Das Bild hat keine Fläche.")
    gray, alpha = decode_png(image.image.png)
    h, w = gray.shape
    if (w, h) != (image.image.px_width, image.image.px_height):
        image = replace(image, image=replace(image.image, px_width=w, px_height=h))
    inside = mask_pixels(image, masks)
    visible = inside if alpha is None else (inside & (alpha > 0))
    before = int(np.count_nonzero(alpha > 0)) if alpha is not None else w * h
    if not visible.any():
        raise CropError("Die Form überdeckt das Bild nicht – Form über das Bild legen.")
    if alpha is None and visible.all():
        raise CropError("Die Form deckt das ganze Bild ab – nichts zuzuschneiden.")
    if alpha is not None and np.array_equal(visible, alpha > 0):
        raise CropError("Die Form deckt den sichtbaren Teil des Bildes ganz ab – "
                        "nichts zuzuschneiden.")
    rows = np.flatnonzero(visible.any(axis=1))
    cols = np.flatnonzero(visible.any(axis=0))
    r0, r1, c0, c1 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    keep = visible[r0:r1, c0:c1]
    new_alpha = np.where(keep, 255 if alpha is None else alpha[r0:r1, c0:c1], 0).astype(np.uint8)
    new_gray = np.where(new_alpha > 0, gray[r0:r1, c0:c1], 255).astype(np.uint8)
    transparent = not bool((new_alpha == 255).all())
    png = encode_png(new_gray, new_alpha if transparent else None)
    nw, nh = c1 - c0, r1 - r0
    sx, sy = lb.w / w, lb.h / h
    x0, y0 = lb.x + c0 * sx, lb.y + r0 * sy
    gw, gh = nw * sx, nh * sy
    cx, cy = image.geom.center()
    ncx, ncy = rotate_point(x0 + gw / 2, y0 + gh / 2, cx, cy, image.geom.rot)
    geom = Geometry(ncx - gw / 2, ncy - gh / 2, gw, gh, image.geom.rot)
    out = replace(image, geom=geom, image=replace(image.image, png=png, px_width=nw, px_height=nh))
    share = int(np.count_nonzero(new_alpha)) / before if before else 0.0
    return CropResult(out, share, (nw, nh), transparent)


__all__ = ["CropError", "CropResult", "MASK_KINDS", "canvas_to_pixels", "crop_image",
           "decode_png", "encode_png", "mask_path", "mask_pixels", "mask_shapes"]
