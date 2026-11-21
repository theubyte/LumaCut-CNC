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
mit Scan-Winkel im gedrehten Raster des gewählten Durchgangs (``pass_index``,
Vorgabe der erste), für die Anzeige zurückgedreht (:func:`rotate_pixels`);
:func:`preview_shape_passes` legt die Durchgänge mit Winkel-Schritt übereinander
(dunkelster Wert je Punkt, wie LightBurns Vorschau aller Durchgänge) oder
addiert mit ``burn_sum`` die Leistung je Punkt über alle Durchgänge
(:func:`sum_previews`: Brennsumme, mehrfach gelaserte Punkte werden dunkler);
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
``focus_mm`` (:func:`preview_array`, :func:`preview_shape`,
:func:`preview_shape_passes`) verschiebt den Ausschnitt großer Bilder und die
Lupe der Laserpunkt-Simulation: Mitte des gezeigten Bereichs in mm neben der
Bildmitte in Canvas-Lage (x rechts, y unten), an den Rändern begrenzt –
:attr:`Preview.focus_mm` meldet die tatsächliche Mitte. None = mittig wie bisher.
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
    # Brennsumme (:func:`sum_previews`): Anteil der gelaserten Punkte, die
    # mehr als ein Durchgang trifft; sonst None.
    multi_share: float | None = None
    # Laserpunkt-Simulation (:mod:`.spot_preview`): ``pixels`` ist dann das
    # vergrößerte Bild der Spuren (mehrere Bildpunkte je Laserpunkt); sonst None.
    spot: object | None = None
    # Mitte des Ausschnitts von ``preview_pixels`` gegenüber der Mitte des
    # gerechneten Bildes (Laserpunkte, x rechts, y unten, in dessen Raster).
    center: tuple[float, float] = (0.0, 0.0)
    # Tatsächliche Mitte des gezeigten Bereichs in mm neben der Bildmitte
    # (Canvas-Lage); None = ganzes Bild zu sehen (kein Ausschnitt, keine Lupe).
    focus_mm: tuple[float, float] | None = None

    @property
    def pannable(self) -> bool:
        """Nur ein Ausschnitt / eine Lupe zu sehen – verschiebbar."""
        return bool(self.cropped or (self.spot is not None and self.spot.cropped))


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
                          black_point=st.black_point, white_point=st.white_point,
                          curve=st.curve)


def preview_array(gray: np.ndarray, width_mm: float, height_mm: float,
                  settings: ImageSettings, max_pixels: int = MAX_PREVIEW_PIXELS,
                  spot_mm: float | tuple[float, float] | None = None,
                  focus_mm: tuple[float, float] | None = None) -> Preview:
    """Gravurbild (Laserpunkte) für ``gray`` (uint8, 0 = schwarz) in ``width_mm × height_mm``.
    ``spot_mm``: Laserpunkt simulieren (:func:`with_spot`); ``focus_mm``: Mitte
    von Ausschnitt / Lupe in mm neben der Bildmitte (None = mittig)."""
    st = settings.normalized()
    g = resample(gray, width_mm, height_mm, st.line_interval_mm)
    off = focus_dots(focus_mm, st.line_interval_mm)
    pv = preview_pixels(g, st, max_pixels, offset=off)
    # Ohne Bildobjekt laufen die Zeilen waagerecht; ein länglicher Punkt liegt
    # trotzdem so zur Zeile wie im ersten Durchgang des Auftrags.
    pv = with_spot(pv, st, spot_mm, max_pixels, pass_angle(st, 0),
                   offset=_rest(off, pv.center))
    return _set_focus(pv, st.line_interval_mm)


# ----------------------------------------------------------- Ausschnitt verschieben
def focus_dots(focus_mm, interval_mm: float, angle: float = 0.0,
               flip_x: bool = False) -> tuple[float, float] | None:
    """Mitte ``focus_mm`` (mm neben der Bildmitte, Canvas-Lage, x rechts,
    y unten) in Laserpunkten im gerechneten Raster: um den Scan-Winkel
    ``angle`` gedreht (Raster des Durchgangs, :func:`rotate_pixels` dreht es
    gegen den Uhrzeigersinn zurück) bzw. in X gespiegelt (``flip_x``,
    Maschinen-Nullpunkt rechts). None / (0, 0) = mittig → None."""
    import math

    from .spot_preview import valid_offset
    off = valid_offset(focus_mm)
    if off is None:
        return None
    dx, dy = off[0] / interval_mm, off[1] / interval_mm
    if angle:
        t = math.radians(angle)
        c, s = math.cos(t), math.sin(t)
        dx, dy = dx * c - dy * s, dx * s + dy * c
    if flip_x:
        dx = -dx
    return dx, dy


def dots_to_focus(center: tuple[float, float], interval_mm: float, angle: float = 0.0,
                  flip_x: bool = False) -> tuple[float, float]:
    """Umkehrung von :func:`focus_dots`: Laserpunkte im Raster → mm in Canvas-Lage."""
    import math
    rx, ry = float(center[0]), float(center[1])
    if flip_x:
        rx = -rx
    if angle:
        t = math.radians(angle)
        c, s = math.cos(t), math.sin(t)
        rx, ry = rx * c + ry * s, -rx * s + ry * c
    return rx * interval_mm, ry * interval_mm


def clamp_focus(focus_mm, width_mm: float, height_mm: float,
                rotation: float = 0.0) -> tuple[float, float] | None:
    """Mitte ``focus_mm`` (mm neben der Bildmitte, Canvas-Lage) auf das Bild
    begrenzen: im (um ``rotation`` Grad gedrehten) Bild ``width_mm × height_mm``,
    damit Ausschnitt / Lupe nicht in die weißen Ecken der Hüllbox wandern.
    None / (0, 0) = mittig → None."""
    import math

    from .spot_preview import valid_offset
    off = valid_offset(focus_mm)
    if off is None:
        return None
    t = math.radians(rotation or 0.0)
    c, s = math.cos(t), math.sin(t)
    lx, ly = off[0] * c + off[1] * s, -off[0] * s + off[1] * c   # in Bildlage
    hw, hh = max(0.0, width_mm / 2.0), max(0.0, height_mm / 2.0)
    lx, ly = min(max(lx, -hw), hw), min(max(ly, -hh), hh)
    out = (lx * c - ly * s, lx * s + ly * c)
    return valid_offset(out)


def _rest(off, center) -> tuple[float, float] | None:
    """Rest der gewünschten Mitte ``off`` nach dem Ausschnitt mit Mitte ``center``
    (für die Lupe, bezogen auf die Mitte des Ausschnitts)."""
    if off is None:
        return None
    return off[0] - center[0], off[1] - center[1]


def _set_focus(pv: Preview, interval_mm: float, angle: float = 0.0,
               flip_x: bool = False) -> Preview:
    """:attr:`Preview.focus_mm` aus den Mitten von Ausschnitt und Lupe."""
    if not pv.pannable:
        pv.focus_mm = None
        return pv
    cx, cy = pv.center
    if pv.spot is not None:
        cx, cy = cx + pv.spot.center[0], cy + pv.spot.center[1]
    pv.focus_mm = dots_to_focus((cx, cy), interval_mm, angle, flip_x)
    return pv


def split_spot(spot_mm) -> tuple[float, float | None]:
    """``spot_mm`` als Zahl (runder Punkt) oder ``(X, Y)`` (länglicher
    Diodenpunkt) → ``(X, Y oder None)``."""
    if isinstance(spot_mm, (tuple, list)):
        x, y = spot_mm
        return float(x), (None if y is None else float(y))
    return float(spot_mm), None


def with_spot(pv: Preview, settings: ImageSettings, spot_mm,
              max_pixels: int = MAX_PREVIEW_PIXELS, angle: float = 0.0,
              offset: tuple[float, float] | None = None) -> Preview:
    """Vorschau ``pv`` (ein Pixel je Laserpunkt, Zeilen = Rasterzeilen) durch
    das Bild der gelaserten Spuren mit der Punktgröße ``spot_mm`` ersetzen
    (:func:`lumacut_import.spot_preview.simulate_spot`, Punktbreitenkorrektur
    wie im Auftrag); ``None`` = unverändert. ``spot_mm`` darf ``(X, Y)`` sein
    (länglicher Diodenpunkt in Maschinenlage), ``angle`` ist dann der
    Scan-Winkel des Rasters von ``pv``. ``burn_share`` bleibt der Anteil
    gelaserter Punkte. ``offset``: Mitte der Lupe in Laserpunkten neben der
    Mitte von ``pv`` (None = mittig)."""
    if spot_mm is None:
        return pv
    from .spot_preview import simulate_spot
    st = settings.normalized()
    x, y = split_spot(spot_mm)
    pv.pixels, pv.spot = simulate_spot(pv.pixels, st.line_interval_mm, x,
                                       st.dot_width_mm, max_pixels, spot_y_mm=y,
                                       angle=angle, offset=offset)
    return pv


def preview_pixels(g: np.ndarray, settings: ImageSettings,
                   max_pixels: int = MAX_PREVIEW_PIXELS,
                   inside: np.ndarray | None = None,
                   offset: tuple[float, float] | None = None) -> Preview:
    """Wie :func:`preview_array`, aber ``g`` liegt schon im Linienabstand vor
    (ein Pixel = ein Laserpunkt); ``inside`` = Innen-Maske wie im Auftrag.
    ``offset``: Mitte des Ausschnitts großer Bilder in Laserpunkten neben der
    Bildmitte (x rechts, y unten; None = mittig), an den Rändern begrenzt."""
    from .spot_preview import crop_center, offset_crop
    st = settings.normalized()
    s = preview_settings(st)
    rows, cols = g.shape
    cropped = rows * cols > max_pixels
    margin = (0, 0, 0, 0)
    center = (0.0, 0.0)
    if cropped:
        ch = min(rows, max(1, int(max_pixels ** 0.5)))
        cw = min(cols, max(1, max_pixels // ch))
        y0, x0 = offset_crop(rows, cols, ch, cw, offset)
        center = crop_center(rows, cols, y0, x0, ch, cw)
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
    return Preview(np.clip(np.rint(out), 0, 255).astype(np.uint8), cropped, share,
                   center=center)


# ----------------------------------------------------------- wie der Auftrag
def _job_shape(shape, settings: ImageSettings):
    """Kopie des Bildobjekts mit den (noch nicht übernommenen) Dialog-Einstellungen."""
    from dataclasses import replace
    return replace(shape, image=replace(shape.image, settings=settings.normalized()))


def pass_angle(settings: ImageSettings, pass_index: int = 0) -> float:
    """Scan-Winkel des Durchgangs ``pass_index`` (0 = erster; außerhalb
    der Durchgänge auf den ersten / letzten begrenzt)."""
    from lumacut_job.images import pass_angles
    angles = pass_angles(settings)
    return angles[min(max(0, int(pass_index)), len(angles) - 1)]


def render_for_preview(shape, settings: ImageSettings, pass_index: int = 0):
    """Bild wie im Auftrag rendern: ``(gray, inside)`` im Linienabstand,
    mit Drehung des Objekts und Glättung wie :func:`lumacut_job.images.render_gray`.

    ``inside`` (nur bei gedrehten Bildern) markiert die Pixel im Bild;
    ohne Bildanpassung / Skizze nutzt der Auftrag die Maske nicht.
    ``pass_index``: Durchgang, dessen Scan-Winkel gilt (Winkel-Schritt)."""
    from lumacut_job.images import (render_gray, render_gray_frame,
                                    render_inside, render_inside_frame, scan_geometry)
    tmp = _job_shape(shape, settings)
    interval = tmp.image.settings.line_interval_mm
    angle = pass_angle(tmp.image.settings, pass_index)
    if angle:
        # Scan-Winkel: im gedrehten Raster wie der Auftrag (gewählter Durchgang).
        geo = scan_geometry(tmp, angle, interval)
        return render_gray_frame(tmp, geo), render_inside_frame(tmp, geo)
    gray, _ = render_gray(tmp, interval)
    inside = render_inside(tmp, interval)
    if inside is not None and inside.shape != gray.shape:
        inside = None
    return gray, inside


def preview_shape(shape, settings: ImageSettings, max_pixels: int = MAX_PREVIEW_PIXELS,
                  rendered=None, pass_index: int = 0, spot_mm: float | tuple[float, float] | None = None,
                  focus_mm: tuple[float, float] | None = None) -> Preview:
    """Vorschau eines Bildobjekts mit genau den Pixeln des Auftrags
    (:func:`lumacut_job.images.image_job`): gerendert samt Drehung, im
    Maschinen-Nullpunkt oben rechts gespiegelt gerechnet (Fehlerverteilung
    und Halbtonwinkel wie in der Ausgabe) und für die Anzeige zurückgespiegelt.
    Ecken der Hüllbox außerhalb des gedrehten Bildes bleiben weiß.
    ``rendered``: bereits gerechnetes ``(gray, inside)`` (Cache des Dialogs).
    ``pass_index``: Durchgang mit Winkel-Schritt (0 = erster, wie bisher).
    ``spot_mm``: Laserpunkt simulieren (:func:`with_spot`) – im Raster des
    Durchgangs gerechnet (Spuren entlang der Scan-Richtung), dann gedreht.
    ``focus_mm``: Mitte von Ausschnitt / Lupe in mm neben der Bildmitte
    (Canvas-Lage), im Raster des Durchgangs gedreht bzw. gespiegelt."""
    from lumacut_canvas.workarea import IMAGE_FLIP_X
    from lumacut_job.raster import wrap_angle
    st = settings.normalized()
    gray, inside = (rendered if rendered is not None
                    else render_for_preview(shape, st, pass_index))
    s = preview_settings(st)
    mask = inside
    if not (st.mode == "sketch" or s.adjusted()):
        inside = None
    from dataclasses import replace
    angle = pass_angle(st, pass_index)
    if angle:
        # Gerechnet im gedrehten Raster (Halbton wie im Auftrag), angezeigt
        # zurückgedreht – so liegt das Bild wie auf dem Canvas.
        st = replace(st, halftone_angle=wrap_angle(st.halftone_angle + angle))
        off = focus_dots(focus_mm, st.line_interval_mm, angle)
        pv = preview_pixels(gray, st, max_pixels, inside, offset=off)
        if not pv.cropped and mask is not None and mask.shape == pv.pixels.shape and mask.any():
            # Anteil bezogen auf das Bild, nicht auf das größere gedrehte Raster.
            pv.burn_share = min(1.0, pv.burn_share * mask.size / int(mask.sum()))
        pv = with_spot(pv, st, spot_mm, max_pixels, angle, offset=_rest(off, pv.center))
        pv.pixels = rotate_pixels(pv.pixels, angle)
        return _set_focus(pv, st.line_interval_mm, angle)
    off = focus_dots(focus_mm, st.line_interval_mm, flip_x=IMAGE_FLIP_X)
    if IMAGE_FLIP_X:
        gray = np.ascontiguousarray(gray[:, ::-1])
        if inside is not None:
            inside = np.ascontiguousarray(inside[:, ::-1])
        st = replace(st, halftone_angle=-st.halftone_angle)
    pv = preview_pixels(gray, st, max_pixels, inside, offset=off)
    if IMAGE_FLIP_X:
        # Zurückgespiegelt: Ausschnitt und weitere Rechnung in Canvas-Lage.
        pv.pixels = np.ascontiguousarray(pv.pixels[:, ::-1])
        pv.center = (-pv.center[0], pv.center[1])
        if off is not None:
            off = (-off[0], off[1])
    pv = with_spot(pv, st, spot_mm, max_pixels, offset=_rest(off, pv.center))
    return _set_focus(pv, st.line_interval_mm)


def distinct_pass_indices(settings: ImageSettings) -> list[int]:
    """Je verschiedenem Scan-Winkel der erste Durchgang (gleicher Winkel =
    gleiche Pixel, z. B. 0° / 90° / 0° beim Kreuzraster → [0, 1])."""
    from lumacut_job.images import pass_angles
    seen, out = set(), []
    for k, a in enumerate(pass_angles(settings)):
        if a not in seen:
            seen.add(a)
            out.append(k)
    return out


def overlay_previews(previews: list[Preview]) -> Preview:
    """Vorschauen mehrerer Durchgänge mittig übereinanderlegen: je Punkt der
    dunkelste Wert (gelasert, wenn ein Durchgang ihn lasert). Unterschiedlich
    große Bilder (gedrehte Raster) werden mittig auf die größte Fläche gelegt,
    Ränder weiß. ``burn_share`` = Mittel der Anteile je Durchgang."""
    if not previews:
        raise ValueError("keine Durchgänge")
    if len(previews) == 1:
        p = previews[0]
        return Preview(p.pixels.copy(), p.cropped, p.burn_share, spot=p.spot)
    h = max(p.pixels.shape[0] for p in previews)
    w = max(p.pixels.shape[1] for p in previews)
    out = np.full((h, w), 255, dtype=np.uint8)
    for p in previews:
        ph, pw = p.pixels.shape
        y0, x0 = (h - ph) // 2, (w - pw) // 2
        view = out[y0:y0 + ph, x0:x0 + pw]
        np.minimum(view, p.pixels, out=view)
    share = float(np.mean([p.burn_share for p in previews]))
    return Preview(out, any(p.cropped for p in previews), share, spot=previews[0].spot)


def sum_previews(previews: list[Preview], counts: list[int] | None = None) -> Preview:
    """Brennsumme mehrerer Durchgänge: je Punkt wird die Leistung (Schwärzung
    ``255 - Wert``) aller Durchgänge addiert und durch die Zahl der Durchgänge
    geteilt – Schwarz = alle Durchgänge mit voller Leistung, ein einzelner
    Durchgang von N mit voller Leistung = 1/N Grau. So werden Punkte, die
    mehrere Durchgänge treffen (Kreuzraster, Graustufen), dunkler als Punkte
    eines Durchgangs, statt wie bei :func:`overlay_previews` nur den dunkelsten
    Wert zu zeigen. ``counts``: wie oft jede Vorschau vorkommt (gleicher
    Scan-Winkel in mehreren Durchgängen, z. B. 0° / 90° / 0° → ``[2, 1]``).
    Größen wie bei :func:`overlay_previews` mittig; ``burn_share`` = nach
    ``counts`` gewichtetes Mittel, ``multi_share`` = Anteil der gelaserten
    Punkte, die mehr als ein Durchgang lasert."""
    if not previews:
        raise ValueError("keine Durchgänge")
    counts = [1] * len(previews) if counts is None else [int(c) for c in counts]
    if len(counts) != len(previews) or any(c < 1 for c in counts):
        raise ValueError("ungültige Anzahl Durchgänge")
    h = max(p.pixels.shape[0] for p in previews)
    w = max(p.pixels.shape[1] for p in previews)
    energy = np.zeros((h, w), dtype=np.float64)
    hits = np.zeros((h, w), dtype=np.int32)
    for p, c in zip(previews, counts):
        ph, pw = p.pixels.shape
        y0, x0 = (h - ph) // 2, (w - pw) // 2
        energy[y0:y0 + ph, x0:x0 + pw] += c * (255.0 - p.pixels.astype(np.float64))
        hits[y0:y0 + ph, x0:x0 + pw] += c * (p.pixels < 255)
    n = sum(counts)
    out = np.clip(np.rint(255.0 - energy / n), 0, 255).astype(np.uint8)
    lit = int((hits > 0).sum())
    multi = float((hits > 1).sum()) / lit if lit else 0.0
    share = float(sum(p.burn_share * c for p, c in zip(previews, counts)) / n)
    return Preview(out, any(p.cropped for p in previews), share, multi, spot=previews[0].spot)


def preview_shape_passes(shape, settings: ImageSettings, max_pixels: int = MAX_PREVIEW_PIXELS,
                         rendered_for=None, burn_sum: bool = False,
                         spot_mm: float | tuple[float, float] | None = None,
                         focus_mm: tuple[float, float] | None = None) -> Preview:
    """Alle Durchgänge eines Bildobjekts mit Winkel-Schritt übereinander
    (:func:`overlay_previews`); jeder Winkel wird nur einmal gerechnet.
    ``rendered_for(pass_index)``: liefert ein bereits gerechnetes
    ``(gray, inside)`` (Cache des Dialogs), sonst wird gerendert.
    ``burn_sum``: Brennsumme (:func:`sum_previews`) statt dunkelstem Wert –
    ein Winkel, der in mehreren Durchgängen vorkommt, zählt so oft.
    ``spot_mm``: jeder Durchgang mit simuliertem Laserpunkt (:func:`with_spot`).
    ``focus_mm``: Mitte von Ausschnitt / Lupe (:func:`preview_shape`); begrenzt
    ein Rand die Mitte in einem Durchgang stärker, rechnen alle mit der
    engsten Mitte, damit die Ausschnitte übereinanderliegen."""
    from lumacut_job.images import pass_angles
    st = settings.normalized()
    angles = pass_angles(st)
    indices = distinct_pass_indices(st)

    def compute(focus):
        out = []
        for k in indices:
            rendered = rendered_for(k) if rendered_for is not None else None
            out.append(preview_shape(shape, st, max_pixels, rendered=rendered, pass_index=k,
                                     spot_mm=spot_mm, focus_mm=focus))
        return out

    previews = compute(focus_mm)
    focus = _common_focus(previews, focus_mm, st.line_interval_mm)
    if focus is not None:
        previews = compute(focus)
    counts = [angles.count(angles[k]) for k in indices]
    combined = sum_previews(previews, counts) if burn_sum else overlay_previews(previews)
    combined.focus_mm = previews[0].focus_mm
    return combined


def _common_focus(previews: list[Preview], focus_mm, interval_mm: float):
    """Engste tatsächliche Mitte mehrerer Durchgänge (je Achse der kleinste
    Betrag in Richtung des Wunsches), wenn sie um mehr als einen halben
    Laserpunkt auseinanderliegen; sonst None (kein zweiter Lauf nötig)."""
    from .spot_preview import valid_offset
    want = valid_offset(focus_mm)
    got = [p.focus_mm for p in previews if p.focus_mm is not None]
    if want is None or len(previews) < 2 or len(got) < 2:
        return None
    tol = 0.5 * interval_mm
    if all(abs(g[0] - got[0][0]) <= tol and abs(g[1] - got[0][1]) <= tol for g in got):
        return None

    def tight(axis):
        vals = [g[axis] if want[axis] * g[axis] > 0 else 0.0 for g in got]
        return min(vals, key=abs) if want[axis] else 0.0

    return tight(0), tight(1)


def rotate_pixels(pixels: np.ndarray, angle: float) -> np.ndarray:
    """Vorschaupixel des gedrehten Rasters (Zeilen unter ``angle`` Grad) zurück
    in Canvas-Lage drehen (gegen den Uhrzeigersinn um ``angle``, ohne
    Glättung – die Punkte bleiben scharf); Ränder weiß."""
    import math

    from PySide6.QtGui import QImage, QPainter, QTransform

    h, w = pixels.shape
    t = math.radians(angle)
    c, sn = abs(math.cos(t)), abs(math.sin(t))
    ow = max(1, int(math.ceil(w * c + h * sn - 1e-6)))
    oh = max(1, int(math.ceil(w * sn + h * c - 1e-6)))
    src = to_qimage(pixels)
    out = QImage(ow, oh, QImage.Format_Grayscale8)
    out.fill(255)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
    tr = QTransform()
    tr.translate(ow / 2, oh / 2)
    tr.rotate(-angle)           # Qt dreht im Uhrzeigersinn (Y nach unten)
    tr.translate(-w / 2, -h / 2)
    p.setTransform(tr)
    p.drawImage(0, 0, src)
    p.end()
    stride = out.bytesPerLine()
    arr = np.frombuffer(out.constBits(), dtype=np.uint8, count=stride * oh)
    return arr.reshape(oh, stride)[:, :ow].copy()


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
        s.brightness, s.contrast, s.gamma, s.curve = 0.0, 0.0, 1.0, ()
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


def curve_input_histogram(source: np.ndarray, black_point: int = 0,
                          white_point: int = 255) -> np.ndarray:
    """Histogramm am Eingang der Gradationskurve: das Bildhistogramm durch
    den Schwarz-/Weißpunkt gestreckt (die Kurve läuft danach), für den
    Hintergrund des Kurven-Editors."""
    src = np.asarray(source, dtype=np.float64)
    if (black_point, white_point) == (0, 255):
        return src.copy()
    v = (np.arange(256) - black_point) / float(max(1, white_point - black_point))
    idx = np.clip(np.rint(v * 255.0), 0, 255).astype(int)
    out = np.zeros(256)
    np.add.at(out, idx, src)
    return out


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
