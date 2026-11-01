"""Bogentext: Geometrie auf dem Kreis, Canvas-Objekte, Undo, G-Code, Dialog."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import arctext  # noqa: E402
from lumacut_job.arctext import ArcSpec, Glyph  # noqa: E402

W, H = 4.0, 5.0


def box(ch="A", w=W, h=H):
    return Glyph(ch, w, (((0.0, -h), (w, -h), (w, 0.0), (0.0, 0.0)),))


def dist(p, c=(0.0, 0.0)):
    return math.hypot(p[0] - c[0], p[1] - c[1])


def test_top_text_centered_clockwise_outside():
    r = 20.0
    pl = arctext.place_glyphs([box("A"), box("B"), box("C")], r)
    span = 3 * W
    step = math.degrees(W / r)
    assert [p.angle_deg for p in pl] == pytest.approx([-step, 0.0, step])
    assert pl[1].anchor == pytest.approx((0.0, -r))  # 12 Uhr (y nach unten)
    assert pl[2].anchor[0] > 0 > pl[0].anchor[0]     # liest von links nach rechts
    for p in pl:
        assert dist(p.anchor) == pytest.approx(r)
        assert p.rotation_deg == pytest.approx(p.angle_deg)
        assert all(dist(q) >= r - 1e-6 for ring in p.rings for q in ring)  # außen
        assert max(dist(q) for ring in p.rings for q in ring) == pytest.approx(
            math.hypot(r + H, W / 2))
    sweep = pl[-1].angle_deg - pl[0].angle_deg + step
    assert math.radians(sweep) * r == pytest.approx(span)
    # mittlerer Buchstabe steht aufrecht
    xs = [q[0] for q in pl[1].rings[0]]
    assert min(xs) == pytest.approx(-W / 2) and max(xs) == pytest.approx(W / 2)


def test_bottom_text_inside_reads_left_to_right():
    r = 20.0
    pl = arctext.place_glyphs([box("A"), box("B"), box("C")], r, angle_deg=180.0, bottom=True,
                              cap_height_mm=H)
    assert pl[1].anchor == pytest.approx((0.0, r))
    assert pl[0].anchor[0] < 0 < pl[2].anchor[0]
    for p in pl:
        d = [dist(q) for ring in p.rings for q in ring]  # Buchstaben stehen innen
        assert max(d) == pytest.approx(math.hypot(r, W / 2))
        assert min(d) == pytest.approx(math.hypot(r - H, W / 2))
        assert dist(p.anchor) == pytest.approx(r)
    ys = [q[1] for q in pl[1].rings[0]]
    assert min(ys) == pytest.approx(r - H) and max(ys) == pytest.approx(r)  # aufrecht


@pytest.mark.parametrize("align,first,last", [("start", 0.0, 2.0), ("end", -3.0, -1.0),
                                              ("center", -1.5, 0.5)])
def test_align_and_angle(align, first, last):
    r = 30.0
    g = [box(c) for c in "ABC"]
    pl = arctext.place_glyphs(g, r, angle_deg=90.0, align=align)
    unit = math.degrees(W / r)
    # Mitte des ersten/letzten Buchstabens relativ zum Bezugswinkel
    assert pl[0].angle_deg == pytest.approx(90.0 + (first + 0.5) * unit)
    assert pl[-1].angle_deg == pytest.approx(90.0 + (last + 0.5) * unit)
    with pytest.raises(ValueError, match="Ausrichtung"):
        arctext.place_glyphs(g, r, align="links")


def test_spacing_and_spaces():
    g = [box("A"), Glyph(" ", 2.0), box("B")]
    assert arctext.text_span(g, 1.0) == pytest.approx(W * 2 + 2.0 + 2 * 1.0)
    pl = arctext.place_glyphs(g, 50.0, spacing_mm=1.0)
    assert pl[1].rings == []
    a = arctext.place_glyphs([box(), box()], 50.0)
    b = arctext.place_glyphs([box(), box()], 50.0, spacing_mm=3.0)
    assert b[1].angle_deg - b[0].angle_deg > a[1].angle_deg - a[0].angle_deg


def test_errors():
    with pytest.raises(ValueError, match="Kreisumfang"):
        arctext.place_glyphs([box()] * 40, 20.0)   # 160 mm > 2π·20
    with pytest.raises(ValueError, match="höher als der Radius"):
        arctext.place_glyphs([box()], 4.0, bottom=True, cap_height_mm=5.0)
    with pytest.raises(ValueError, match="Kein Text"):
        arctext.place_glyphs([], 10.0)
    with pytest.raises(ValueError, match="sichtbaren"):
        arctext.arc_shapes([Glyph(" ", 3.0)], ArcSpec(text=" "), "L1")
    big = [box(w=30.0, h=30.0)] * 30
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        arctext.arc_shapes(big, ArcSpec(text="x" * 30, radius_mm=200.0), "L1")


def test_spec_normalized():
    s = ArcSpec(text="a\nb", radius_mm=0.1, height_mm=999, angle_deg=None, bottom=True,
                align="?").normalized()
    assert (s.text, s.radius_mm, s.height_mm, s.angle_deg, s.align) == (
        "a b", arctext.RADIUS_RANGE[0], arctext.HEIGHT_RANGE[1], 180.0, "center")


def test_arc_shapes_grouped_centered_and_clamped():
    g = [box(c) for c in "ABCD"] + [Glyph(" ", 2.0), box("E")]
    shapes = arctext.arc_shapes(g, ArcSpec(text="ABCD E", radius_mm=25.0), "L7",
                                target_center=(100.0, 80.0))
    assert len(shapes) == 5 and all(s.kind == "polygon" and s.layer_id == "L7" for s in shapes)
    assert len({s.groups for s in shapes}) == 1 and len(shapes[0].groups) == 1
    bs = [s.bounds() for s in shapes]
    x0, y0 = min(b.x for b in bs), min(b.y for b in bs)
    x1, y1 = max(b.x + b.w for b in bs), max(b.y + b.h for b in bs)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((100.0, 80.0))
    edge = arctext.arc_shapes(g, ArcSpec(text="ABCD E", radius_mm=25.0), "L7",
                              target_center=(0.0, WORK_HEIGHT_MM))
    bs = [s.bounds() for s in edge]
    assert min(b.x for b in bs) >= -1e-6
    assert max(b.y + b.h for b in bs) <= WORK_HEIGHT_MM + 1e-6


# --- Qt -----------------------------------------------------------------------
def test_glyphs_for_font_metrics(qapp):
    from lumacut_job.arctext_qt import glyphs_for
    g = glyphs_for("HI H", "Segoe UI", 10.0)
    assert [x.char for x in g] == list("HI H")
    assert all(x.advance > 0 for x in g) and g[2].rings == ()
    ys = [p[1] for ring in g[0].rings for p in ring]
    assert -min(ys) == pytest.approx(10.0, rel=0.06) and max(ys) == pytest.approx(0.0, abs=0.3)
    wide = glyphs_for("HI H", "Segoe UI", 20.0)
    assert arctext.text_span(wide, 0) == pytest.approx(2 * arctext.text_span(g, 0), rel=0.02)


def test_dialog(qapp):
    from lumacut_job.arctext_qt import ArcTextDialog
    dlg = ArcTextDialog(spec=ArcSpec(text="LumaCut", radius_mm=40.0, height_mm=8.0))
    assert dlg.ok_button.isEnabled() and "Bogen" in dlg.info.text()
    assert not dlg.replace_source()
    dlg.side.setCurrentIndex(1)
    assert dlg.angle.value() == 180.0 and dlg.spec().bottom
    dlg.align.setCurrentIndex(arctext.ALIGNS.index("start"))
    assert dlg.spec().align == "start"
    dlg.radius.setValue(5.0)
    assert not dlg.ok_button.isEnabled()
    dlg.radius.setValue(40.0)
    dlg.text.setText("   ")
    assert not dlg.ok_button.isEnabled()
    dlg.deleteLater()
    dlg2 = ArcTextDialog(can_replace=True)
    assert dlg2.replace_source()
    dlg2.deleteLater()


@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_window_insert_undo_and_gcode(win):
    from PySide6.QtGui import QKeySequence

    from lumacut_job.planner import optimized_document_gcode
    tools = win.job_tools
    assert tools.arc_action.objectName() == "arc_text_action"
    assert tools.arc_action.shortcut() == QKeySequence("Alt+B")
    assert tools.arc_action in win.main_view.design_menu.actions()
    doc = win.canvas.document
    layer = doc.active_layer
    n = len(doc.shapes)
    depth = win.canvas.undo_stack.index()
    ids = tools.arc_text(ArcSpec(text="LumaCut Studio", radius_mm=40.0, height_mm=8.0))
    assert len(ids) == 13 and all(doc.shape(i).layer_id == layer.id for i in ids)
    assert win.canvas.undo_stack.index() == depth + 1
    assert sorted(win.canvas.selection) == sorted(ids)
    bs = [doc.shape(i).bounds() for i in ids]
    cx = (min(b.x for b in bs) + max(b.x + b.w for b in bs)) / 2
    assert cx == pytest.approx(WORK_WIDTH_MM / 2, abs=0.01)
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") > 50
    pi_check(gcode)
    win.canvas.undo_stack.undo()
    assert len(doc.shapes) == n


def test_window_replace_selected_text(win):
    from lumacut_canvas.commands import AddShapesCommand
    from lumacut_canvas.model import Geometry, Shape
    from lumacut_job.arctext_qt import spec_from_text
    doc = win.canvas.document
    layer = doc.active_layer
    txt = Shape("text", Geometry(50.0, 50.0, 60.0, 12.0), layer.id, text="Hallo")
    win.canvas.undo_stack.push(AddShapesCommand(doc, [txt]))
    win.canvas.set_selection([txt.id])
    pre = spec_from_text(txt)
    assert pre.text == "Hallo" and pre.radius_mm == pytest.approx(30.0)
    assert 5.0 < pre.height_mm < 12.0
    depth = win.canvas.undo_stack.index()
    ids = win.job_tools.arc_text(pre, replace=True)
    assert len(ids) == 5 and not doc.has_shape(txt.id)
    bs = [doc.shape(i).bounds() for i in ids]
    cx = (min(b.x for b in bs) + max(b.x + b.w for b in bs)) / 2
    cy = (min(b.y for b in bs) + max(b.y + b.h for b in bs)) / 2
    assert (cx, cy) == pytest.approx((80.0, 56.0), abs=0.01)  # an der Stelle des Textes
    assert win.canvas.undo_stack.index() == depth + 1
    win.canvas.undo_stack.undo()
    assert doc.has_shape(txt.id) and not any(doc.has_shape(i) for i in ids)
