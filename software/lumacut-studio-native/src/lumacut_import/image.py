"""Bitmap-Import (PNG/JPG/BMP …) als Bildobjekt.

Das Bild wird einmal in 8-bit-Graustufen umgerechnet (Transparenz → Weiß =
nicht lasern) und als PNG im Projekt eingebettet. Die Größe in mm kommt aus
der DPI-Angabe der Datei (ohne Angabe 96 dpi); zu große Bilder werden später
gemeinsam mit der Platzierung in die Arbeitsfläche eingepasst.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter

from lumacut_canvas.model import ImageSettings, RasterImage

MAX_PIXELS_LONG_SIDE = 4096
DEFAULT_DPI = 96.0


def _dpi(img: QImage) -> float:
    dpm = img.dotsPerMeterX()
    dpi = dpm * 0.0254 if dpm > 0 else DEFAULT_DPI
    return dpi if 30.0 <= dpi <= 5000.0 else DEFAULT_DPI


def grayscale_png(img: QImage) -> tuple[bytes, int, int]:
    """QImage → (PNG-Bytes 8-bit grau, Breite, Höhe), Alpha auf Weiß."""
    if img.hasAlphaChannel():
        flat = QImage(img.size(), QImage.Format_ARGB32)
        flat.fill(QColor(255, 255, 255))
        p = QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        img = flat
    gray = img.convertToFormat(QImage.Format_Grayscale8)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    if not gray.save(buf, "PNG"):
        raise ValueError("Bild konnte nicht umgewandelt werden")
    buf.close()
    return bytes(data.data()), gray.width(), gray.height()


def load_image(path, settings: ImageSettings | None = None) -> tuple[RasterImage, float, float]:
    """Bilddatei → (RasterImage, Breite mm, Höhe mm)."""
    reader = QImageReader(os.fspath(path))
    reader.setAutoTransform(True)  # EXIF-Drehung von Handyfotos
    img = reader.read()
    if img.isNull():
        raise ValueError(f"Bild nicht lesbar: {reader.errorString()}")
    dpi = _dpi(img)
    w_mm = img.width() / dpi * 25.4
    h_mm = img.height() / dpi * 25.4
    long_side = max(img.width(), img.height())
    if long_side > MAX_PIXELS_LONG_SIDE:
        img = img.scaled(img.width() * MAX_PIXELS_LONG_SIDE // long_side,
                         img.height() * MAX_PIXELS_LONG_SIDE // long_side,
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    png, w, h = grayscale_png(img)
    return RasterImage(png, w, h, (settings or ImageSettings()).normalized()), w_mm, h_mm
