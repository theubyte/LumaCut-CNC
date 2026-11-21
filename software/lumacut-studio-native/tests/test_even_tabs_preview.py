"""Live-Vorschau von „Stege gleichmäßig setzen …“ auf der Arbeitsfläche: neue Stege blau,
ersetzte alte Stege grau, ausgelassene Konturen gestrichelt – nur Anzeige, kein Undo-Schritt;
Dialog neben den Objekten, Touch-Größen, G-Code unverändert bis OK."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QDialog

from lumacut_canvas import tabs
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.tabs_ui import (PREVIEW_COLOR, TOUCH_PX, EvenTabsDialog, place_beside,
                                    shapes_screen_rect, side_position)
from lumacut_job.planner import optimized_document_gcode


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid)


def ellipse(lid, x, y, w, h):
    return Shape("ellipse", Geometry(x, y, w, h, 0.0), lid)


@pytest.fixture
def doc(qapp):
    d = Document()
    d.update_layer(d.active_layer_id, tab_width_mm=2.0)
    return d


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.document.update_layer(e.document.active_layer_id, tab_width_mm=2.0)
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def _snapshot(doc):
    return [(s.id, s.tabs) for s in doc.shapes]


# --- Rechnung: ausgelassene Konturen ---------------------------------------------------

def test_result_lists_skipped_contours_with_reason(doc):
    lid = doc.active_layer_id
    big, hole, tiny = rect(lid), ellipse(lid, 60, 52, 10, 10), rect(lid, x=150, y=50, w=2, h=2)
    for s in (big, hole, tiny):
        doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [big, hole, tiny], {"count": 2})
    reasons = sorted(why for _r, why in res.skipped)
    assert reasons == ["inner", "short"]
    assert res.skipped_inner == 1 and res.too_short == 1
    ring = next(r for r, why in res.skipped if why == "inner")
    xs = [p[0] for p in ring]
    assert min(xs) == pytest.approx(60, abs=0.1) and max(xs) == pytest.approx(70, abs=0.1)
    # Readout unverändert (gleicher Text wie ohne Vorschau)
    assert "1 innere Kontur(en) ausgelassen" in res.readout() and "1 Kontur(en) zu kurz" in res.readout()
    # ohne „Innere Konturen auslassen“ nur noch die zu kurze
    res2 = tabs.place_even_tabs(doc, [big, hole, tiny], {"count": 2, "skip_inner": False})
    assert [why for _r, why in res2.skipped] == ["short"]


# --- Vorschau im Werkzeug ----------------------------------------------------------------

def test_preview_replace_marks_new_blue_and_old_grey_without_changing_the_document(ed):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [rect(lid)])
    ed.tab_tool.add_at((70.0, 50.0))               # ein alter manueller Steg oben
    assert len(ed.tab_tool.item.marks) == 1
    before, n0 = _snapshot(ed.document), ed.undo_stack.count()
    res = tabs.place_even_tabs(ed.document, [ed.document.shapes[0]], {"count": 4})
    ed.tab_tool.set_preview(res)
    item = ed.tab_tool.item
    kinds = sorted(k for _a, _b, k in item.preview_marks)
    assert kinds == ["new"] * 4 + ["removed"]
    assert item.marks == [] and item.isVisible()   # der alte Steg erscheint nur grau
    assert _snapshot(ed.document) == before and ed.undo_stack.count() == n0
    # Balken in Stegbreite entlang der Kontur
    for a, b, _k in item.preview_marks:
        assert math.hypot(b.x() - a.x(), b.y() - a.y()) == pytest.approx(2.0, abs=1e-6)
    ed.tab_tool.clear_preview()
    assert item.preview_marks == [] and len(item.marks) == 1 and ed.tab_tool.preview is None


def test_preview_add_mode_keeps_old_tabs_orange(ed):
    lid = ed.document.active_layer_id
    _add(ed, [rect(lid)])
    ed.tab_tool.add_at((70.0, 50.0))
    res = tabs.place_even_tabs(ed.document, [ed.document.shapes[0]], {"count": 4, "replace": False})
    ed.tab_tool.set_preview(res)
    item = ed.tab_tool.item
    assert len(item.marks) == 1                     # alter Steg bleibt orange
    assert [k for _a, _b, k in item.preview_marks].count("new") == len(res.add[0].tabs) - 1
    assert "removed" not in [k for _a, _b, k in item.preview_marks]


def test_preview_shows_skipped_contours_and_untouched_objects(ed):
    lid = ed.document.active_layer_id
    a, hole, other = _add(ed, [rect(lid), ellipse(lid, 60, 52, 10, 10), rect(lid, y=120)])
    ed.tab_tool.add_at((70.0, 120.0))              # Objekt außerhalb des Bereichs
    res = tabs.place_even_tabs(ed.document, [a, hole], {"count": 3})
    ed.tab_tool.set_preview(res)
    item = ed.tab_tool.item
    assert [why for _r, why in item.skipped] == ["inner"]
    assert [k for _a, _b, k in item.preview_marks] == ["new"] * 3
    assert len(item.marks) == 1                     # Stege anderer Objekte unverändert orange


def test_preview_on_hidden_layer_draws_no_bars(ed):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [rect(lid)])
    res = tabs.place_even_tabs(ed.document, [s], {"count": 2})
    ed.document.update_layer(lid, visible=False)
    ed.tab_tool.set_preview(res)
    assert ed.tab_tool.item.preview_marks == []
    ed.tab_tool.clear_preview()
    ed.document.update_layer(lid, visible=True)


def test_preview_paints_blue_bars(ed, qapp):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [rect(lid, x=10, y=10, w=40, h=20)])
    ed.tab_tool.set_preview(tabs.place_even_tabs(ed.document, [s], {"count": 4}))
    img = QImage(200, 120, QImage.Format_ARGB32)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    p.scale(3.0, 3.0)
    ed.tab_tool.item.paint(p, None)
    p.end()
    blue = QColor(PREVIEW_COLOR)
    hits = sum(1 for x in range(0, 200, 1) for y in range(0, 120, 2)
               if img.pixelColor(x, y).blue() > 200 and img.pixelColor(x, y).red() < 120
               and abs(img.pixelColor(x, y).green() - blue.green()) < 60)
    assert hits > 0
    ed.tab_tool.clear_preview()


# --- Dialog ---------------------------------------------------------------------------------

def test_dialog_feeds_the_preview_live_and_ends_it(doc, qapp):
    lid = doc.active_layer_id
    s = rect(lid)
    doc.add_shape(s)
    seen = []
    dlg = EvenTabsDialog(doc, [s], values={"count": 3}, on_preview=seen.append)
    try:
        assert dlg.show_preview.isChecked() and not dlg.show_preview.isHidden()
        assert seen and seen[-1].tabs == 3
        dlg.count.setValue(5)
        assert seen[-1].tabs == 5
        dlg.show_preview.setChecked(False)
        assert seen[-1] is None
        dlg.show_preview.setChecked(True)
        assert seen[-1].tabs == 5
        dlg.reject()
        assert seen[-1] is None
        assert doc.shapes[0].tabs == ()             # Dokument nie geändert
    finally:
        dlg.close()


def test_dialog_without_preview_hook_hides_the_switch(doc, qapp):
    lid = doc.active_layer_id
    s = rect(lid)
    doc.add_shape(s)
    dlg = EvenTabsDialog(doc, [s])
    try:
        assert dlg.show_preview.isHidden()
        assert "Stege" in dlg.readout.text()
    finally:
        dlg.close()


def test_touch_mode_dialog_controls_are_44_px(doc, qapp):
    lid = doc.active_layer_id
    s = rect(lid)
    doc.add_shape(s)
    dlg = EvenTabsDialog(doc, [s], touch=True, on_preview=lambda r: None)
    dlg.show()
    qapp.processEvents()
    try:
        for w in (dlg.mode, dlg.count, dlg.spacing, dlg.max_count, dlg.min_perimeter,
                  dlg.avoid_corners, dlg.skip_inner, dlg.replace, dlg.show_preview):
            assert w.minimumHeight() >= TOUCH_PX and w.height() >= TOUCH_PX
        for b in dlg.buttons.buttons():
            assert b.height() >= TOUCH_PX
        assert "indicator" in dlg.styleSheet() and f"min-height: {TOUCH_PX}px" in dlg.styleSheet()
    finally:
        dlg.close()
    plain = EvenTabsDialog(doc, [s])
    try:
        assert plain.count.minimumHeight() < TOUCH_PX
    finally:
        plain.close()


def test_action_shows_the_preview_while_open_and_one_undo_step_on_ok(ed, monkeypatch):
    lid = ed.document.active_layer_id
    a, b = _add(ed, [rect(lid), rect(lid, y=100)])
    ed.set_selection([a.id, b.id])
    assert "gleichmäßig verteilen mit Vorschau" in ed.path_ops_button.toolTip()
    during = {}

    def fake_exec(dlg):
        during["preview"] = ed.tab_tool.preview
        during["marks"] = list(ed.tab_tool.item.preview_marks)
        during["tabs"] = _snapshot(ed.document)
        dlg.count.setValue(3)
        during["after"] = len(ed.tab_tool.item.preview_marks)
        return QDialog.Accepted
    monkeypatch.setattr(EvenTabsDialog, "exec", fake_exec)
    n0 = ed.undo_stack.count()
    ed.actions_by_name["tabs_even"].trigger()
    assert during["preview"] is not None and len(during["marks"]) == 8      # 2 × 4 Stege
    assert all(t == () for _i, t in during["tabs"])                         # nur Anzeige
    assert during["after"] == 6
    assert ed.undo_stack.count() == n0 + 1
    assert ed.tab_tool.preview is None and ed.tab_tool.item.preview_marks == []
    assert len(ed.tab_tool.item.marks) == 6 and ed.tab_tool.even.last["count"] == 3
    ed.undo_stack.undo()
    assert all(not s.tabs for s in ed.document.shapes)


def test_action_cancel_leaves_nothing_and_remembers_the_switch(ed, monkeypatch):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [rect(lid)])
    ed.set_selection([s.id])

    def fake_exec(dlg):
        assert ed.tab_tool.preview is not None
        dlg.show_preview.setChecked(False)
        assert ed.tab_tool.preview is None
        return QDialog.Rejected
    monkeypatch.setattr(EvenTabsDialog, "exec", fake_exec)
    n0 = ed.undo_stack.count()
    ed.actions_by_name["tabs_even"].trigger()
    assert ed.undo_stack.count() == n0 and ed.document.shapes[0].tabs == ()
    assert ed.tab_tool.preview is None and ed.tab_tool.even.show_preview is False
    seen = {}

    def second(dlg):
        seen["checked"] = dlg.show_preview.isChecked()
        seen["preview"] = ed.tab_tool.preview
        return QDialog.Rejected
    monkeypatch.setattr(EvenTabsDialog, "exec", second)
    ed.actions_by_name["tabs_even"].trigger()
    assert seen == {"checked": False, "preview": None}


def test_preview_cleared_even_when_the_dialog_raises(ed, monkeypatch):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [rect(lid)])

    def boom(dlg):
        assert ed.tab_tool.preview is not None
        raise RuntimeError("x")
    monkeypatch.setattr(EvenTabsDialog, "exec", boom)
    with pytest.raises(RuntimeError):
        ed.tab_tool.even._ask([s])
    assert ed.tab_tool.preview is None


def test_touch_mode_action_opens_touch_dialog(ed, qapp, monkeypatch):
    lid = ed.document.active_layer_id
    _add(ed, [rect(lid)])
    got = {}

    def fake_exec(dlg):
        dlg.show()
        qapp.processEvents()
        got["h"] = [w.height() for w in (dlg.mode, dlg.count, dlg.spacing, dlg.avoid_corners,
                                         dlg.show_preview, *dlg.buttons.buttons())]
        dlg.hide()
        return QDialog.Rejected
    monkeypatch.setattr(EvenTabsDialog, "exec", fake_exec)
    ed.set_touch_mode(True, persist=False)
    try:
        ed.actions_by_name["tabs_even"].trigger()
    finally:
        ed.set_touch_mode(False, persist=False)
    assert got["h"] and min(got["h"]) >= TOUCH_PX


# --- Platzierung neben den Objekten --------------------------------------------------------

def test_side_position_prefers_right_then_left_above_below():
    avail = QRect(0, 0, 1000, 700)
    size = QSize(300, 200)
    p = side_position(size, avail, QRect(100, 250, 200, 100))
    assert p == QPoint(100 + 200 + 12, 200) and not QRect(p, size).intersects(QRect(100, 250, 200, 100))
    p = side_position(size, avail, QRect(650, 250, 300, 100))              # rechts kein Platz
    assert p.x() + 300 <= 650 and avail.contains(QRect(p, size))
    wide = QRect(50, 400, 900, 100)                                         # links / rechts zu eng
    p = side_position(size, avail, wide)
    assert p.y() + 200 <= 400
    low = QRect(50, 50, 900, 100)
    p = side_position(size, avail, low)
    assert p.y() >= 150
    assert side_position(size, avail, QRect(0, 0, 1000, 700)) is None
    assert side_position(QSize(0, 0), avail, low) is None


def test_side_position_clamps_into_the_screen():
    avail = QRect(0, 0, 1000, 700)
    p = side_position(QSize(300, 200), avail, QRect(100, 0, 100, 20))
    assert p.y() >= 0 and avail.contains(QRect(p, QSize(300, 200)))


def test_dialog_moves_beside_shapes_it_would_cover(ed, qapp):
    lid = ed.document.active_layer_id
    ed.view.fitInView(0, 0, 400, 300)
    qapp.processEvents()
    # Objekt in der Mitte der Ansicht
    c = ed.view.mapToScene(ed.view.viewport().rect().center())
    (s,) = _add(ed, [rect(lid, x=c.x() - 10, y=c.y() - 5, w=20, h=10)])
    target = shapes_screen_rect(ed, [s])
    assert not target.isEmpty()
    dlg = EvenTabsDialog(ed.document, [s], ed)
    try:
        assert place_beside(dlg, ed, [s]) is True
        assert not QRect(dlg.pos(), dlg.sizeHint()).intersects(target)
        dlg.show()
        qapp.processEvents()
        assert not dlg.frameGeometry().intersects(target)
    finally:
        dlg.close()
    assert shapes_screen_rect(ed, []).isEmpty()


def test_dialog_stays_centred_when_it_covers_nothing(ed, qapp):
    lid = ed.document.active_layer_id
    ed.view.fitInView(0, 0, 400, 300)
    qapp.processEvents()
    tl = ed.view.mapToScene(ed.view.viewport().rect().topLeft())
    (s,) = _add(ed, [rect(lid, x=tl.x() + 2, y=tl.y() + 2, w=4, h=4)])
    dlg = EvenTabsDialog(ed.document, [s], ed)
    try:
        assert place_beside(dlg, ed, [s]) is False
    finally:
        dlg.close()


def test_place_beside_without_view_or_shapes_does_nothing(doc, qapp):
    lid = doc.active_layer_id
    s = rect(lid)
    doc.add_shape(s)
    dlg = EvenTabsDialog(doc, [s])
    try:
        assert place_beside(dlg, object(), [s]) is False
    finally:
        dlg.close()


# --- G-Code ---------------------------------------------------------------------------------

def test_gcode_unchanged_by_preview_and_equal_after_ok(ed, monkeypatch):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [rect(lid)])
    before = optimized_document_gcode(ed.document, scan_offsets=None)
    ed.tab_tool.set_preview(tabs.place_even_tabs(ed.document, [s], {"count": 4}))
    assert optimized_document_gcode(ed.document, scan_offsets=None) == before
    ed.tab_tool.clear_preview()
    monkeypatch.setattr(EvenTabsDialog, "exec", lambda dlg: dlg.count.setValue(4) or QDialog.Accepted)
    ed.actions_by_name["tabs_even"].trigger()
    g = optimized_document_gcode(ed.document, scan_offsets=None)
    ref = Document()
    ref.update_layer(ref.active_layer_id, tab_width_mm=2.0)
    r = rect(ref.active_layer_id)
    ref.add_shape(r)
    ref.shapes[0] = tabs.place_even_tabs(ref, [r], {"count": 4}).add[0]
    assert g == optimized_document_gcode(ref, scan_offsets=None)
    pi_check(g)


def test_main_window_preview_hook_is_the_tab_tool(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        assert w.canvas.tab_tool.even.tool is w.canvas.tab_tool
        dlg = w.canvas.tab_tool.even.dialog([rect(w.canvas.document.active_layer_id)])
        assert not dlg.show_preview.isHidden()
        dlg.reject()
        assert w.canvas.tab_tool.preview is None
        dlg.close()
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
