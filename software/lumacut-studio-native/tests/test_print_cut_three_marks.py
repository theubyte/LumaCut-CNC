"""Passmarken mit drei Marken (Erweiterung von LightBurns *Print and Cut*): starrer
Ausgleich über alle drei Marken, getrennte X/Y-Maßstäbe mit „Maßstab angleichen“,
Scherung als Rest-Abweichung, Plausibilitätsprüfungen, G-Code, Werkzeug mit sechs
Tipps / Eingabe / Rücktaste / Schalter, Zahlen-Dialog mit drittem Paar."""

from __future__ import annotations

import json
import math

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from lumacut_canvas import marks
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.marks import MarkError, fit_marks
from lumacut_canvas.marks_ui import MarksDialog
from lumacut_canvas.model import Document, Geometry, Shape, rotate_point
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.tools import Tool
from lumacut_canvas.workarea import screen_to_user
from lumacut_job.planner import optimized_document_gcode

NO = Qt.NoModifier
SOLL = [(20.0, 20.0), (180.0, 20.0), (20.0, 120.0)]       # drei Ecken eines Bogens


def printer(p, sx=1.0, sy=1.0, deg=0.0, t=(0.0, 0.0), shear=0.0, c=(100.0, 70.0)):
    """So kommt ein Druck aufs Bett: X/Y-Maßstab, Scherung, Drehung um ``c``, Verschiebung."""
    x, y = p[0] - c[0], p[1] - c[1]
    x, y = x * sx + shear * y, y * sy
    r = math.radians(deg)
    co, si = math.cos(r), math.sin(r)
    return (c[0] + t[0] + x * co - y * si, c[1] + t[1] + x * si + y * co)


def world(shape):
    g = shape.geom
    cx, cy = g.center()
    return [rotate_point(x, y, cx, cy, g.rot) for x, y in shape.abs_points()]


def close(a, b, tol=1e-6):
    return len(a) == len(b) and all(math.dist(p, q) < tol for p, q in zip(a, b))


# ------------------------------------------------------------------ Modell
def test_three_exact_marks_rigid_hit_all():
    ist = [printer(p, deg=2.5, t=(7.0, -4.0)) for p in SOLL]
    f = fit_marks(SOLL, ist)
    assert f.pairs == 3 and f.scales is None and f.scale == 1.0
    assert f.angle_deg == pytest.approx(2.5) and f.error_mm == 0.0
    for a, b in zip(SOLL, ist):
        assert f.map_point(a) == pytest.approx(b)
    assert f.ratio == pytest.approx(1.0)


def test_rigid_three_marks_balance_the_error_and_keep_size():
    ist = [printer(p, sx=1.006, sy=0.995, deg=-1.5, t=(3.0, 2.0)) for p in SOLL]
    f = fit_marks(SOLL, ist)
    res = [(b[0] - f.map_point(a)[0], b[1] - f.map_point(a)[1]) for a, b in zip(SOLL, ist)]
    # Ausgleich: Rest-Abweichungen heben sich auf (Schwerpunkt auf Schwerpunkt)
    assert sum(r[0] for r in res) == pytest.approx(0, abs=1e-9)
    assert sum(r[1] for r in res) == pytest.approx(0, abs=1e-9)
    assert 0.1 < f.error_mm < 0.6 and f.error_mm == pytest.approx(max(math.hypot(*r) for r in res))
    g = f.map_geometry(Geometry(40, 40, 30, 20))
    assert (g.w, g.h) == pytest.approx((30, 20))
    # kleinste Quadrate: jede andere Drehung um den Schwerpunkt ist schlechter
    sq = sum(math.hypot(*r) ** 2 for r in res)
    for d in (-0.05, 0.05):
        g2 = marks.MarkFit(pivot=f.pivot, target=f.target, angle_deg=f.angle_deg + d, pairs=3)
        assert sum(math.dist(g2.map_point(a), b) ** 2 for a, b in zip(SOLL, ist)) > sq


def test_scale_mode_recovers_separate_x_and_y_scale():
    ist = [printer(p, sx=1.006, sy=0.995, deg=-1.5, t=(3.0, 2.0)) for p in SOLL]
    f = fit_marks(SOLL, ist, scale=True)
    assert f.scales == pytest.approx((1.006, 0.995), abs=1e-9)
    assert f.angle_deg == pytest.approx(-1.5, abs=1e-7) and f.error_mm == 0.0
    assert f.scale == pytest.approx((1.006 + 0.995) / 2)
    for a, b in zip(SOLL, ist):
        assert f.map_point(a) == pytest.approx(b, abs=1e-7)
    g = f.map_geometry(Geometry(40, 40, 30, 20))
    assert (g.w, g.h) == pytest.approx((30 * 1.006, 20 * 0.995), abs=1e-6)
    assert g.rot == pytest.approx(-1.5, abs=1e-7)
    assert close(g.corner_points(), [f.map_point(p) for p in Geometry(40, 40, 30, 20).corner_points()],
                 tol=1e-6)


def test_rotated_objects_stay_form_true_with_the_centre_exact():
    ist = [printer(p, sx=1.01, sy=0.99, deg=4.0) for p in SOLL]
    f = fit_marks(SOLL, ist, scale=True)
    src = Geometry(60, 50, 40, 10, 30)
    g = f.map_geometry(src)
    assert g.center() == pytest.approx(f.map_point(src.center()), abs=1e-6)
    pts = g.corner_points()                           # weiterhin ein Rechteck (keine Scherung)
    v1 = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    v2 = (pts[3][0] - pts[0][0], pts[3][1] - pts[0][1])
    assert v1[0] * v2[0] + v1[1] * v2[1] == pytest.approx(0, abs=1e-6)
    assert g.rot == pytest.approx(34.0, abs=1e-6)


def test_every_unrotated_kind_tabs_and_start_follow_exactly():
    lid = "L"
    poly = Shape.from_points("polygon", [(30, 30), (90, 35), (60, 80)], lid)
    poly.tabs = ((0.5, 0.0),)
    poly.start = (1.0, 0.5)
    path = Shape.from_points("path", [(25, 25), (45, 60), (95, 28)], lid)
    rect = Shape("rect", Geometry(50, 40, 20, 10), lid)
    line = Shape("line", Geometry(25, 25, 40, -10), lid)
    text = Shape("text", Geometry(70, 70, 40, 10), lid, text="Hallo")
    ist = [printer(p, sx=0.996, sy=1.004, deg=6.0, t=(10, 5)) for p in SOLL]
    f = fit_marks(SOLL, ist, scale=True)
    for s in (poly, path):
        t = s.copy()
        t.geom = f.map_geometry(s.geom)
        assert close([f.map_point(p) for p in world(s)], world(t))
    for s in (rect, line, text):
        t = s.copy()
        t.geom = f.map_geometry(s.geom)
        assert close([f.map_point(p) for p in s.geom.corner_points()], t.geom.corner_points())
    t = poly.copy()
    t.geom = f.map_geometry(poly.geom)
    assert close([f.map_point(p) for p in poly.tab_points()], t.tab_points())
    assert f.map_point(poly.start_point()) == pytest.approx(t.start_point())


def test_shear_stays_as_reported_rest_error():
    ist = [printer(p, shear=0.008, deg=1.0) for p in SOLL]
    f = fit_marks(SOLL, ist, scale=True)
    assert f.error_mm > 0.1
    assert f.error_mm == pytest.approx(max(math.dist(f.map_point(a), b) for a, b in zip(SOLL, ist)))
    s = marks.summary(f)
    assert "Maßstab X" in s and "Y" in s and "größte Rest-Abweichung" in s


def test_summary_texts_for_three_marks():
    ist = [printer(p, sx=1.01, sy=0.99) for p in SOLL]
    s = marks.summary(fit_marks(SOLL, ist, scale=True))
    assert "Maßstab X 101.00 %, Y 99.00 %" in s and "gedreht" in s and "drei Marken ausgeglichen" in s
    s = marks.summary(fit_marks(SOLL, ist))
    assert "Abstände Ist/Soll" in s and "Maßstab X" not in s


@pytest.mark.parametrize("soll, ist, scale, text", [
    (SOLL, [(20, 20), (180, 20), (20, 300)], False, "Marke 1 und 3"),
    ([(0, 0), (3, 0), (0, 100)], [(0, 0), (3, 0), (0, 100)], False, "Soll-Punkte (Marke 1 und 2) liegen zu dicht"),
    ([(0, 0), (100, 0), (50, 80)], [(0, 0), (100, 0), (50, -80)], False, "gespiegelt"),
    ([(0, 0), (100, 0), (200, 1)], [(0, 0), (100, 0), (200, 1)], True, "über Eck"),
    ([(0, 0), (100, 0), (0, 3)], [(0, 0), (100, 0), (0, 3)], True, "dicht"),
    ([(0, 0), (float("inf"), 0), (0, 50)], [(0, 0), (1, 0), (0, 50)], False, "ungültige"),
])
def test_implausible_three_marks_are_refused(soll, ist, scale, text):
    with pytest.raises(MarkError) as e:
        fit_marks(soll, ist, scale)
    assert text in str(e.value)


def test_collinear_marks_are_fine_without_scale_and_extra_points_ignored():
    soll = [(0, 0), (100, 0), (200, 0)]
    ist = [printer(p, deg=3.0, c=(0, 0)) for p in soll]
    f = fit_marks(soll, ist)
    assert f.pairs == 3 and f.angle_deg == pytest.approx(3.0) and f.error_mm == 0.0
    f4 = fit_marks(soll + [(5, 5)], ist + [(900, 900)])
    assert f4.pairs == 3 and f4.angle_deg == pytest.approx(3.0)
    assert fit_marks(soll, ist[:2]).pairs == 2


def test_gcode_of_an_xy_scaled_part_is_pi_safe():
    doc = Document()
    doc.add_shape(Shape("rect", Geometry(40, 40, 30, 20), doc.active_layer_id))
    ist = [printer(p, sx=1.02, sy=0.98, t=(5, 5)) for p in SOLL]
    f = fit_marks(SOLL, ist, scale=True)
    s = doc.shapes[0]
    doc.set_geometry(s.id, f.map_geometry(s.geom))
    g = optimized_document_gcode(doc)
    pi_check(g)
    assert parse_gcode(g).cut_length_mm == pytest.approx(2 * (30 * 1.02 + 20 * 0.98), abs=0.05)


# ------------------------------------------------------------------ Werkzeug
@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.msgs = []
    e.statusMessage.connect(e.msgs.append)
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return list(shapes)


def click(ed, x, y):
    ed.tools.press(QPointF(x, y), NO)
    ed.tools.release(QPointF(x, y), NO)


def key(ed, k):
    return ed.tools.key_press(QKeyEvent(QEvent.KeyPress, k, NO))


def sheet(ed):
    """Drei Kreis-Marken an SOLL und ein Teil dazwischen."""
    lid = ed.document.active_layer_id
    shapes = [Shape("ellipse", Geometry(x - 2, y - 2, 4, 4), lid) for x, y in SOLL]
    shapes.append(Shape("rect", Geometry(60, 50, 60, 40), lid))
    return _add(ed, shapes)


def test_three_marks_switch_in_context_menu_default_off(ed):
    sheet(ed)
    ed.set_tool(Tool.MARKS)
    a = ed.actions_by_name["marks_three"]
    assert a.isCheckable() and not a.isChecked() and not ed.marks_tool.three
    assert ed.marks_tool.max_points == 4
    texts = [x.text() for x in ed.build_context_menu(QPointF(200, 200)).actions()]
    assert "Passmarken: drei Marken" in texts
    assert texts.index("Passmarken: drei Marken") == texts.index("Passmarken: Maßstab angleichen") + 1
    a.trigger()
    assert ed.marks_tool.three and ed.marks_tool.max_points == 6 and "drei Marken" in ed.msgs[-1]
    ed.marks_tool.set_three(False)
    assert not a.isChecked() and ed.msgs[-1] == "Passmarken: zwei Marken"


def test_six_taps_align_with_xy_scale_in_one_undo_step(ed):
    *mk, part = sheet(ed)
    ed.set_selection([s.id for s in mk] + [part.id])
    ed.set_tool(Tool.MARKS)
    ed.marks_tool.set_three(True)
    ed.marks_tool.set_scale(True)
    ist = [printer(p, sx=1.005, sy=0.995, deg=1.2, t=(4.0, 3.0)) for p in SOLL]
    n0 = ed.undo_stack.count()
    for i in range(2):
        click(ed, SOLL[i][0] + 0.3, SOLL[i][1] - 0.4)    # fängt die Kreismitte
        click(ed, *ist[i])
    assert len(ed.marks_tool.points) == 4 and ed.undo_stack.count() == n0
    assert "Soll 3" in ed.msgs[-1] and "über Eck" in ed.msgs[-1]
    click(ed, SOLL[2][0] - 0.3, SOLL[2][1] + 0.2)
    assert "Ist 3" in ed.msgs[-1]
    click(ed, *ist[2])
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Passmarken ausrichten"
    assert ed.marks_tool.points == []
    for s, b in zip(mk, ist):
        assert ed.document.shape(s.id).geom.center() == pytest.approx(b, abs=1e-6)
    g = ed.document.shape(part.id).geom
    assert (g.w, g.h) == pytest.approx((60 * 1.005, 40 * 0.995), abs=1e-6)
    assert "Maßstab X 100.50 %, Y 99.50 %" in ed.msgs[-1] and "Strg+Z" in ed.msgs[-1]
    ed.undo_stack.undo()
    assert ed.document.shape(part.id).geom.as_tuple() == pytest.approx((60, 50, 60, 40))


def test_enter_after_four_or_five_points_uses_two_marks(ed):
    *mk, part = sheet(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    ed.marks_tool.set_three(True)
    b1 = (24.0, 22.0)
    b2 = rotate_point(184.0, 22.0, *b1, 2.0)
    for p in (SOLL[0], b1, SOLL[1], b2, SOLL[2]):
        click(ed, *p)
    assert len(ed.marks_tool.points) == 5
    key(ed, Qt.Key_Return)
    f = fit_marks(SOLL[:2], [b1, b2])
    assert f.pairs == 2
    g = ed.document.shape(part.id).geom
    assert close(g.corner_points(), [f.map_point(p) for p in Geometry(60, 50, 60, 40).corner_points()])
    assert ed.marks_tool.points == []


def test_backspace_overlay_limit_and_switching_off_trims_points(ed):
    sheet(ed)
    ed.set_tool(Tool.MARKS)
    ed.marks_tool.set_three(True)
    for p in (SOLL[0], (22, 21), SOLL[1], (182, 21), SOLL[2]):
        click(ed, *p)
    assert ed.marks_tool.item.limit == 6
    ed.marks_tool.hover(QPointF(25, 125))
    assert ed.marks_tool.item.hover == pytest.approx((25, 125))
    assert ed.marks_tool.item.ghost                       # Vorschau an zwei Marken
    key(ed, Qt.Key_Backspace)
    assert len(ed.marks_tool.points) == 4
    click(ed, *SOLL[2])
    ed.marks_tool.set_three(False)
    assert len(ed.marks_tool.points) == 4 and ed.marks_tool.item.limit == 4
    ed.marks_tool.hover(QPointF(30, 30))
    assert ed.marks_tool.item.hover is None


def test_wrong_sixth_point_is_refused_and_can_be_set_again(ed):
    *mk, part = sheet(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    ed.marks_tool.set_three(True)
    n0 = ed.undo_stack.count()
    for p in (SOLL[0], SOLL[0], SOLL[1], SOLL[1], SOLL[2]):
        click(ed, *p)
    click(ed, 20, 160)                                    # 40 % zu weit
    assert ed.undo_stack.count() == n0 and "Marke 1 und 3" in ed.msgs[-1]
    assert len(ed.marks_tool.points) == 5
    click(ed, 21, 120)
    assert ed.undo_stack.count() == n0 + 1 and "drei Marken ausgeglichen" in ed.msgs[-1]


def test_dialog_with_a_third_pair(ed):
    *mk, part = sheet(ed)
    ed.set_selection([part.id])
    dlg = MarksDialog(ed.marks_tool, ed)
    assert not dlg.third.isChecked() and len(dlg.spins) == 6
    assert not dlg.spins[4][0].isEnabled() and not dlg.spins[5][1].isEnabled()
    assert (dlg.spins[4][0].value(), dlg.spins[4][1].value()) == pytest.approx(screen_to_user(60, 90))
    dlg.third.setChecked(True)
    assert dlg.spins[4][0].isEnabled() and len(dlg.screen_points()) == 6
    dlg.second.setChecked(False)
    assert not dlg.third.isEnabled() and not dlg.spins[4][0].isEnabled()
    assert len(dlg.screen_points()) == 2
    dlg.second.setChecked(True)
    dlg.scale.setChecked(True)
    ist = [printer(p, sx=1.01, sy=0.99, t=(2.0, 1.0)) for p in SOLL]
    for i in range(3):
        dlg.set_point(2 * i, *screen_to_user(*SOLL[i]))
        dlg.set_point(2 * i + 1, *screen_to_user(*ist[i]))
    assert "Maßstab X 101.00 %, Y 99.00 %" in dlg.info.text()
    assert dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled()
    dlg.set_point(5, *screen_to_user(20, 125))            # über Eck, aber mit Scherung
    assert "Rest-Abweichung" in dlg.info.text() and "Rest-Abweichung 0.00 mm" not in dlg.info.text()
    dlg.set_point(5, *screen_to_user(*ist[2]))
    assert dlg.apply()
    g = ed.document.shape(part.id).geom
    assert (g.w, g.h) == pytest.approx((60 * 1.01, 40 * 0.99), abs=0.01)
    ed.marks_tool.set_three(True)
    assert MarksDialog(ed.marks_tool, ed).third.isChecked()


def test_save_has_no_new_project_key(ed, tmp_path):
    from lumacut_canvas.document_io import save_document
    *mk, part = sheet(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    ed.marks_tool.set_three(True)
    ed.marks_tool.set_scale(True)
    ist = [printer(p, sx=1.004, sy=0.997, deg=0.8) for p in SOLL]
    for a, b in zip(SOLL, ist):
        click(ed, *a)
        click(ed, *b)
    assert ed.undo_stack.undoText() == "Passmarken ausrichten"
    p = tmp_path / "m.lcs"
    save_document(ed.document, p)
    plain = Document()
    plain.add_shape(Shape("rect", Geometry(40, 30, 50, 30, 10), plain.active_layer_id))
    q = tmp_path / "plain.lcs"
    save_document(plain, q)

    def keys(node, out=None):
        out = set() if out is None else out
        if isinstance(node, dict):
            for k, v in node.items():
                out.add(k)
                keys(v, out)
        elif isinstance(node, list):
            for v in node:
                keys(v, out)
        return out
    assert keys(json.loads(p.read_text(encoding="utf-8"))) == keys(json.loads(q.read_text(encoding="utf-8")))
