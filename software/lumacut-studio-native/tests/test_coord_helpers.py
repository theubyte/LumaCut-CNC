"""Koordinaten-Helfer in workarea.py für beide Nullpunkt-Stellungen.

Der Schalter ORIGIN_TOP_RIGHT (docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md
§2.1/§2.3) lebt nur in workarea.py; alle Anzeige-/Maschinen-Umrechnungen
müssen mit beiden Stellungen konsistent sein.
"""
import pytest

from lumacut_canvas import workarea as wa
from lumacut_canvas.workarea import Rect


@pytest.fixture(params=[False, True], ids=["oben-links", "oben-rechts"])
def origin(request, monkeypatch):
    monkeypatch.setattr(wa, "ORIGIN_TOP_RIGHT", request.param)
    return request.param


@pytest.mark.parametrize("p", [(0, 0), (360, 340), (17.3, 222.2), (359.9, 0.1)])
def test_round_trips(origin, p):
    assert wa.machine_to_screen(*wa.screen_to_machine(*p)) == pytest.approx(p)
    assert wa.user_to_screen(*wa.screen_to_user(*p)) == pytest.approx(p)


def test_machine_formula(origin):
    mx, my = wa.screen_to_machine(10, 20)
    assert my == 50
    assert mx == (380 if origin else 40)


def test_user_x_and_left_edge_are_inverse(origin):
    r = Rect(100, 10, 20, 10)
    u = wa.user_x_of(r)
    assert u == (240 if origin else 100)
    assert wa.screen_left_for_user_x(u, r.w) == r.x


def test_machine_rect_to_screen_any_corner_order(origin):
    r = Rect(100, 10, 20, 10)
    (ax, ay), (bx, by) = wa.screen_to_machine(r.x, r.y), wa.screen_to_machine(r.right, r.bottom)
    assert wa.machine_rect_to_screen(ax, ay, bx, by) == r
    assert wa.machine_rect_to_screen(bx, by, ax, ay) == r


def test_machine_limits_do_not_depend_on_direction(origin):
    xs = [wa.screen_to_machine(x, 0)[0] for x in (0, 360)]
    assert (min(xs), max(xs)) == (wa.MACHINE_X_MIN, wa.MACHINE_X_MAX)


def test_axis_tooltips_follow_switch(origin):
    x_tip, _ = wa.axis_tooltips()
    assert ("rechten" in x_tip) is origin
