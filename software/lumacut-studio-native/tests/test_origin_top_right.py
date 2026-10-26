"""Nullpunkt oben rechts (docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md §2.1).

Maschine: X0 Y0 oben rechts, +X nach links, +Y zur Tür. Die Szene bleibt
ungespiegelt (Text/Bilder lesbar); umgerechnet wird nur in workarea.py.
"""
import pytest

from lumacut_canvas import workarea as wa
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.workarea import Rect


def test_switch_is_on_and_matches_doc_formula():
    assert wa.ORIGIN_TOP_RIGHT is True
    for sx, sy in ((0, 0), (360, 340), (12.5, 7.25), (180, 170)):
        assert wa.screen_to_machine(sx, sy) == pytest.approx((390 - sx, 30 + sy))


def test_corners_of_work_area():
    # Bildschirm oben rechts = Maschine nahe Nullpunkt (30, 30)
    assert wa.screen_to_machine(360, 0) == pytest.approx((30, 30))
    assert wa.screen_to_machine(0, 0) == pytest.approx((390, 30))
    assert wa.screen_to_machine(0, 340) == pytest.approx((390, 370))
    assert (wa.MACHINE_X_MIN, wa.MACHINE_Y_MIN, wa.MACHINE_X_MAX, wa.MACHINE_Y_MAX) == (30, 30, 390, 370)


@pytest.mark.parametrize("p", [(0, 0), (360, 340), (17.3, 222.2), (359.9, 0.1)])
def test_round_trips(p):
    assert wa.machine_to_screen(*wa.screen_to_machine(*p)) == pytest.approx(p)
    assert wa.user_to_screen(*wa.screen_to_user(*p)) == pytest.approx(p)
    assert wa.from_machine(*wa.to_machine(*p)) == pytest.approx(p)


def test_jog_directions_match_machine():
    # +10 mm Maschinen-X = Kopf nach links auf dem Bildschirm, +10 Y = nach unten (Tür)
    x0, y0 = wa.machine_to_screen(100, 100)
    x1, _ = wa.machine_to_screen(110, 100)
    _, y1 = wa.machine_to_screen(100, 110)
    assert x1 == pytest.approx(x0 - 10) and y1 == pytest.approx(y0 + 10)


def test_display_values_and_property_x():
    r = Rect(100, 10, 20, 10)
    assert wa.screen_to_user(100, 10) == (260, 10)
    assert wa.user_x_of(r) == 240                # rechte Kante: 360 − 120
    assert wa.screen_left_for_user_x(240, 20) == 100
    assert wa.machine_rect_to_screen(290, 40, 270, 50) == Rect(100, 10, 20, 10)


def test_shape_at_screen_left_gets_large_machine_x_and_is_not_mirrored(qapp):
    from lumacut_canvas.export import job_layers
    d = Document()
    d.add_shape(Shape("line", Geometry(10, 20, 30, 0), d.active_layer_id))
    (poly,) = job_layers(d)[0].polylines
    # Linie läuft auf dem Bildschirm von links nach rechts → Maschinen-X fällt
    assert poly[0] == pytest.approx((380, 50)) and poly[-1] == pytest.approx((350, 50))


def test_file_marker_and_old_files_keep_their_place():
    d = Document()
    d.add_shape(Shape("rect", Geometry(10, 20, 30, 40), d.active_layer_id))
    data = d.to_dict()
    assert data["coords"] == wa.COORD_CONVENTION
    old = dict(data)
    del old["coords"]                             # Datei von vor 2026-10-26
    e = Document()
    e.load_dict(old)
    assert e.shapes[0].geom.as_tuple() == (10, 20, 30, 40)   # gleiche Stelle auf dem Bildschirm


def test_unknown_convention_is_rejected():
    data = Document().to_dict()
    data["coords"] = "irgendwas-v9"
    with pytest.raises(ValueError):
        Document().load_dict(data)


def test_raster_column_0_lands_at_large_machine_x(qapp):
    """Vertrag (ZUSAMMENARBEIT §2, Anforderungen §2.3): Bildspalte 0 (linke Bildkante
    auf dem Bildschirm) liegt bei 390 − x, also beim großen Maschinen-X.

    Linke Bildhälfte schwarz, rechte weiß: gebrannt wird nur zwischen
    Maschinen-X 390 − 70 und 390 − 60, nicht in der rechten Hälfte (310…320).
    """
    from PySide6.QtGui import QColor, QImage
    from lumacut_canvas.model import Document, Geometry, ImageSettings, RasterImage, Shape
    from lumacut_canvas.toolpath import CUT, parse_gcode
    from lumacut_import.image import grayscale_png
    from lumacut_job.planner import optimized_document_gcode

    img = QImage(40, 8, QImage.Format_RGB32)
    for x in range(40):
        for y in range(8):
            v = 0 if x < 20 else 255
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, ph = grayscale_png(img)
    doc = Document()
    doc.add_shape(Shape("image", Geometry(60, 60, 20, 4, 0), doc.active_layer_id,
                        image=RasterImage(png, pw, ph,
                                          ImageSettings(mode="threshold", overscan_mm=0.0))))
    cuts = [m for m in parse_gcode(optimized_document_gcode(doc)).moves
            if m.kind == CUT and m.power > 0]
    assert cuts
    xs = [x for m in cuts for x in (m.x0, m.x1)]
    assert min(xs) >= 390 - 70 - 0.3
    assert max(xs) <= 390 - 60 + 0.3
    assert max(xs) > 325          # schwarze Spalte 0 sitzt am großen X-Rand
