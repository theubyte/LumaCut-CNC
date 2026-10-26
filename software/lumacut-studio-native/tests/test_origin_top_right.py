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
