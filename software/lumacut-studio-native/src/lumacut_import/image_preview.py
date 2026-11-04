"""Vorschau der Bildgravur im Dialog „Bildeinstellungen“ (wie LightBurn „Adjust Image“).

:func:`preview_array` rechnet das Bild mit genau der Engine der Ausgabe
(:func:`lumacut_job.raster.power_map` bzw. :func:`~lumacut_job.raster.depth_slices`)
im eingestellten Linienabstand um: ein Vorschaupixel = ein Laserpunkt.
Gelasert = dunkel (Graustufen nach Leistung, 3D nach Anzahl Durchgänge).
Größere Bilder werden auf einen mittigen Ausschnitt von höchstens
``MAX_PREVIEW_PIXELS`` Punkten begrenzt, damit der Dialog flüssig bleibt –
so bleibt die echte Punktstruktur sichtbar statt einer verkleinerten.
:func:`preview_shape` (Dialog mit Bildobjekt) rendert das Bild wie der Auftrag
samt Drehung und Glättung und rechnet im Maschinen-Nullpunkt oben rechts
gespiegelt (Fehlerverteilung, Halbtonwinkel) – Vorschau = Pixel des Auftrags;
:func:`preview_array` (nur Bilddaten) ignoriert die Drehung.
:func:`histograms` / :func:`auto_points_for`: Histogramm vor/nach der
Bildanpassung und Schwarz-/Weißpunkt für „Auto-Tonwert“ (:func:`auto_levels_for`
liefert die ältere Näherung über Helligkeit/Kontrast);
:func:`histograms_rendered`: Histogramm des wie im Auftrag gerenderten
(gedrehten) Bildes ohne die Ecken der Hüllbox.
Bildanpassung (Helligkeit, Kontrast, Gamma, Schärfen) und der Skizzen-Modus
laufen über dieselben Funktionen wie der Auftrag (``power_map`` /
``adjusted_height``); Nachbarschaftsfilter (Schärfen, Skizze) werden bei einem
Ausschnitt mit Rand gerechnet, damit die Ausschnittkante nicht abweicht.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lumacut_canvas.model import ImageSettings
from lumacut_job.raster import (AUTO_LEVELS_CLIP, PWM_MAX, RasterSettings, adjust_gray,
                                adjusted_height, auto_levels, depth_slices, filter_margin,
                                gray_histogram, levels_points, power_map, resample)

MAX_PREVIEW_PIXELS = 360_000      # z. B. 600 × 600 Punkte


@dataclass
class Preview:
    pixels: np.ndarray            # uint8, 0 = volle Leistung / tiefste Stufe, 255 = nicht lasern
    cropped: bool                 # nur ein mittiger Ausschnitt
    burn_share: float             # Anteil gelaserter Punkte (0..1)


def preview_settings(st: ImageSettings) -> RasterSettings:
    st = st.normalized()
    return RasterSettings(line_interval_mm=st.line_interval_mm, power=st.power,
                          min_power=min(st.min_power, st.power), speed_mm_min=st.speed_mm_min,
                          mode="floyd" if st.mode == "depth3d" else st.mode,
                          threshold=st.threshold, overscan_mm=0.0, negative=st.negative,
                          halftone_cpi=st.halftone_cpi, halftone_angle=st.halftone_angle,
                          dot_width_mm=st.dot_width_mm, brightness=st.brightness,
                          contrast=st.contrast, gamma=st.gamma, sharpen=st.sharpen,
                          sharpen_radius=st.sharpen_radius,
                          black_point=st.black_point, white_point=st.white_point)


def preview_array(gray: np.ndarray, width_mm: float, height_mm: float,
                  settings: ImageSettings, max_pixels: int = MAX_PREVIEW_PIXELS) -> Preview:
    """Gravurbild (Laserpunkte) für ``gray`` (uint8, 0 = schwarz) in ``width_mm × height_mm``."""
    st = settings.normalized()
    g = resample(gray, width_mm, height_mm, st.line_interval_mm)
    return preview_pixels(g, st, max_pixels)


def preview_pixels(g: np.ndarray, settings: ImageSettings,
                   max_pixels: int = MAX_PREVIEW_PIXELS,
                   inside: np.ndarray | None = None) -> Preview:
    """Wie :func:`preview_array`, aber ``g`` liegt schon im Linienabstand vor
    (ein Pixel = ein Laserpunkt); ``inside`` = Innen-Maske wie im Auftrag."""
    st = settings.normalized()
    s = preview_settings(st)
    rows, cols = g.shape
    cropped = rows * cols > max_pixels
    margin = (0, 0, 0, 0)
    if cropped:
        ch = min(rows, max(1, int(max_pixels ** 0.5)))
        cw = min(cols, max(1, max_pixels // ch))
        y0, x0 = (rows - ch) // 2, (cols - cw) // 2
        # Filter-Rand (Schärfen, Skizze) mitnehmen: Ausschnitt = gleiche Pixel wie im Auftrag.
        m = filter_margin(s)
        t, lft = min(m, y0), min(m, x0)
        b, r = min(m, rows - y0 - ch), min(m, cols - x0 - cw)
        margin = (t, b, lft, r)
        g = g[y0 - t:y0 + ch + b, x0 - lft:x0 + cw + r]
        if inside is not None:
            inside = inside[y0 - t:y0 + ch + b, x0 - lft:x0 + cw + r]
    if st.mode == "depth3d":
        t, b, lft, r = margin
        g = adjusted_height(g, s) if inside is None else adjusted_height(g, s, inside)
        g = g[t:g.shape[0] - b, lft:g.shape[1] - r]
        masks = depth_slices(g, st.depth_levels, st.negative)
        level = np.sum(masks, axis=0).astype(np.float64) / st.depth_levels
        out = 255.0 - level * 255.0
        share = float(np.mean(level > 0)) if level.size else 0.0
    else:
        kw = {} if inside is None else {"inside": inside}
        pm = power_map(g, s, margin=margin if any(margin) else 0, **kw)
        out = 255.0 - pm.astype(np.float64) * 255.0 / max(1, round(st.power / 100 * PWM_MAX))
        share = float(np.mean(pm > 0)) if pm.size else 0.0
    return Preview(np.clip(np.rint(out), 0, 255).astype(np.uint8), cropped, share)


# ----------------------------------------------------------- wie der Auftrag
def _job_shape(shape, settings: ImageSettings):
    """Kopie des Bildobjekts mit den (noch nicht übernommenen) Dialog-Einstellungen."""
    from dataclasses import replace
    return replace(shape, image=replace(shape.image, settings=settings.normalized()))


def render_for_preview(shape, settings: ImageSettings):
    """Bild wie im Auftrag rendern: ``(gray, inside)`` im Linienabstand,
    mit Drehung des Objekts und Glättung wie :func:`lumacut_job.images.render_gray`.

    ``inside`` (nur bei gedrehten Bildern) markiert die Pixel im Bild;
    ohne Bildanpassung / Skizze nutzt der Auftrag die Maske nicht."""
    from lumacut_job.images import render_gray, render_inside
    tmp = _job_shape(shape, settings)
    interval = tmp.image.settings.line_interval_mm
    gray, _ = render_gray(tmp, interval)
    inside = render_inside(tmp, interval)
    if inside is not None and inside.shape != gray.shape:
        inside = None
    return gray, inside


def preview_shape(shape, settings: ImageSettings, max_pixels: int = MAX_PREVIEW_PIXELS,
                  rendered=None) -> Preview:
    """Vorschau eines Bildobjekts mit genau den Pixeln des Auftrags
    (:func:`lumacut_job.images.image_job`): gerendert samt Drehung, im
    Maschinen-Nullpunkt oben rechts gespiegelt gerechnet (Fehlerverteilung
    und Halbtonwinkel wie in der Ausgabe) und für die Anzeige zurückgespiegelt.
    Ecken der Hüllbox außerhalb des gedrehten Bildes bleiben weiß.
    ``rendered``: bereits gerechnetes ``(gray, inside)`` (Cache des Dialogs)."""
    from lumacut_canvas.workarea import IMAGE_FLIP_X
    st = settings.normalized()
    gray, inside = rendered if rendered is not None else render_for_preview(shape, st)
    s = preview_settings(st)
    if not (st.mode == "sketch" or s.adjusted()):
        inside = None
    from dataclasses import replace
    if IMAGE_FLIP_X:
        gray = np.ascontiguousarray(gray[:, ::-1])
        if inside is not None:
            inside = np.ascontiguousarray(inside[:, ::-1])
        st = replace(st, halftone_angle=-st.halftone_angle)
    pv = preview_pixels(gray, st, max_pixels, inside)
    if IMAGE_FLIP_X:
        pv.pixels = np.ascontiguousarray(pv.pixels[:, ::-1])
    return pv


# ----------------------------------------------------------- Histogramm
@dataclass
class Histograms:
    source: np.ndarray            # 256 Werte, Grauwerte des Bildes (0 = schwarz)
    adjusted: np.ndarray          # nach Bildanpassung (Schärfen, Helligkeit, Kontrast, Gamma)
    black_share: float            # Anteil reines Schwarz nach Anpassung (0..1)
    white_share: float            # Anteil reines Weiß nach Anpassung (0..1)
    levels: tuple[int, int] | None  # Tonwertumfang (Auto-Tonwert-Grenzen) des Bildes
    points: tuple[int, int] = (0, 255)  # eingestellter Schwarz-/Weißpunkt


def _sample(gray: np.ndarray, width_mm: float, height_mm: float, st: ImageSettings,
            max_pixels: int) -> tuple[np.ndarray, float]:
    """Bild im Linienabstand (höchstens ``max_pixels``, sonst gröber) und der
    Vergröberungsfaktor (für den Schärferadius)."""
    interval = st.line_interval_mm
    n = (width_mm / interval) * (height_mm / interval)
    factor = max(1.0, (n / max_pixels) ** 0.5) if max_pixels > 0 else 1.0
    return resample(gray, width_mm, height_mm, interval * factor), factor


def _adjust_settings(st: ImageSettings, factor: float, levels: bool = True):
    s = preview_settings(st)
    s.sharpen_radius = max(0.5, s.sharpen_radius / factor)
    if not levels:
        s.brightness, s.contrast, s.gamma = 0.0, 0.0, 1.0
    return s


def histograms(gray: np.ndarray, width_mm: float, height_mm: float, settings: ImageSettings,
               max_pixels: int = MAX_PREVIEW_PIXELS) -> Histograms:
    """Histogramm des Bildes vor und nach der Bildanpassung (wie LightBurn /
    Bildbearbeitung): ganzes Bild im Linienabstand, große Bilder gröber
    abgetastet; Anpassung über :func:`lumacut_job.raster.adjust_gray`."""
    st = settings.normalized()
    g, factor = _sample(gray, width_mm, height_mm, st, max_pixels)
    src = gray_histogram(g)
    adj = gray_histogram(adjust_gray(g, _adjust_settings(st, factor)))
    total = max(1, int(adj.sum()))
    return Histograms(src, adj, float(adj[0]) / total, float(adj[255]) / total,
                      levels_points(src), (st.black_point, st.white_point))


def histograms_rendered(gray: np.ndarray, inside: np.ndarray | None, settings: ImageSettings,
                        max_pixels: int = MAX_PREVIEW_PIXELS) -> Histograms:
    """Wie :func:`histograms`, aber für das wie im Auftrag gerenderte Bild
    (:func:`render_for_preview`, samt Drehung): nur Pixel innerhalb des
    gedrehten Bildes (``inside``) zählen, die weißen Ecken der Hüllbox nicht.
    Große Bilder werden mit Schrittweite abgetastet (Schärferadius skaliert)."""
    st = settings.normalized()
    g = np.asarray(gray)
    step = 1
    if max_pixels > 0 and g.size > max_pixels:
        step = int(np.ceil((g.size / max_pixels) ** 0.5))
    g = g[::step, ::step]
    mask = None if inside is None else np.asarray(inside, dtype=bool)[::step, ::step]
    if mask is not None and mask.shape != g.shape:
        mask = None
    src = gray_histogram(g, mask)
    adj = gray_histogram(adjust_gray(g, _adjust_settings(st, float(step))), mask)
    total = max(1, int(adj.sum()))
    return Histograms(src, adj, float(adj[0]) / total, float(adj[255]) / total,
                      levels_points(src), (st.black_point, st.white_point))


def auto_levels_for(gray: np.ndarray, width_mm: float, height_mm: float,
                    settings: ImageSettings, clip: float = AUTO_LEVELS_CLIP,
                    max_pixels: int = MAX_PREVIEW_PIXELS) -> tuple[float, float]:
    """``(brightness, contrast)`` für „Auto-Tonwert“: Tonwertumfang des Bildes
    (nach dem Schärfen, das vorher läuft) auf Schwarz … Weiß strecken;
    Gamma und Schärfen bleiben wie eingestellt."""
    st = settings.normalized()
    g, factor = _sample(gray, width_mm, height_mm, st, max_pixels)
    base = adjust_gray(g, _adjust_settings(st, factor, levels=False))
    return auto_levels(gray_histogram(base), clip)


def auto_points_for(gray: np.ndarray, width_mm: float, height_mm: float,
                    settings: ImageSettings, clip: float = AUTO_LEVELS_CLIP,
                    max_pixels: int = MAX_PREVIEW_PIXELS) -> tuple[int, int]:
    """``(black_point, white_point)`` für „Auto-Tonwert“ (wie *Tonwertkorrektur
    → Auto* in Bildbearbeitungen): der Tonwertumfang des Bildes nach dem
    Schärfen (je ``clip`` Ausreißer unten/oben, :func:`levels_points`) wird
    exakt auf Schwarz … Weiß gestreckt. Gerechnet wird ohne die eingestellten
    Punkte, Helligkeit, Kontrast und Gamma – wiederholtes Klicken ändert nichts.
    Flaches oder leeres Bild: ``(0, 255)`` (unverändert)."""
    st = settings.normalized()
    g, factor = _sample(gray, width_mm, height_mm, st, max_pixels)
    s = _adjust_settings(st, factor, levels=False)
    s.black_point, s.white_point = 0, 255
    pts = levels_points(gray_histogram(adjust_gray(g, s)), clip)
    if pts is None or pts[1] <= pts[0]:
        return 0, 255
    return int(pts[0]), int(pts[1])


def gray_from_png(png: bytes) -> np.ndarray:
    """PNG-Bytes → 8-bit-Graustufen-Array (über den QImage-Cache)."""
    from PySide6.QtGui import QImage

    from lumacut_canvas.image_cache import qimage_for

    img = qimage_for(png)
    if img.isNull():
        raise ValueError("Bilddaten beschädigt")
    g = img.convertToFormat(QImage.Format_Grayscale8)
    stride = g.bytesPerLine()
    arr = np.frombuffer(g.constBits(), dtype=np.uint8, count=stride * g.height())
    return arr.reshape(g.height(), stride)[:, :g.width()].copy()


def to_qimage(pixels: np.ndarray):
    """uint8-Array → QImage (Grayscale8, eigene Kopie)."""
    from PySide6.QtGui import QImage

    a = np.ascontiguousarray(pixels, dtype=np.uint8)
    h, w = a.shape
    return QImage(a.data, w, h, w, QImage.Format_Grayscale8).copy()
