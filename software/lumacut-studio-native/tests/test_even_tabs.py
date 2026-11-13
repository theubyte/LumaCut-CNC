"""„Stege gleichmäßig setzen …“ (LightBurn *Auto-place tabs*): manuelle Stege auf einmal
verteilen – Rechnung (Anzahl / Abstand, Ecken, innere Konturen, ersetzen / ergänzen),
Planer / G-Code durch den Pi-Wächter, Dialog, Aktion im Pfad-Menü, Hauptfenster."""

from __future__ import annotations

import math
import re

import pytest
from _pi_guard import pi_check
from PySide6.QtWidgets import QDialogButtonBox

from lumacut_canvas import pathsplit, tabs
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_canvas.tabs_ui import EVEN_ACTION, EvenTabsDialog
from lumacut_canvas.toolpath import parse_gcode
from lumacut_job.cutpath import _cum_lengths, project_on_poly
from lumacut_job.planner import PlanReport, optimized_document_gcode


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid)


def ellipse(lid, x, y, w, h):
    return Shape("ellipse", Geometry(x, y, w, h, 0.0), lid)


def burned(g: str) -> float:
    return parse_gcode(g).cut_length_mm


def gaps(g: str) -> int:
    lines = [ln for ln in g.splitlines() if ln.startswith(("G0 X", "G1 X"))]
    first = next(i for i, ln in enumerate(lines) if ln.startswith("G1"))
    return sum(1 for ln in lines[first:] if ln.startswith("G0"))


def on_outline(shape, pts, tol=1e-6):
    rings = tabs.closed_rings(shape)
    return all(tabs.nearest_on_rings(rings, p)[0] <= tol for p in pts)


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
    yield e
    e.undo_stack.setClean()
    e.close()


# --- Rechnung ------------------------------------------------------------------------

def test_defaults_and_broken_values_are_cleaned():
    d = tabs.even_defaults()
    assert d == {"mode": "count", "count": 4, "spacing_mm": 50.0, "max_count": 0,
                 "avoid_corners": True, "skip_inner": True, "min_perimeter_mm": 10.0,
                 "replace": True}
    assert tabs._clean_even(None) == d
    bad = tabs._clean_even({"mode": "zickzack", "count": "viele", "spacing_mm": float("nan"),
                            "max_count": 1e9, "min_perimeter_mm": -5, "replace": 0})
    assert bad["mode"] == "count" and bad["count"] == 4 and bad["spacing_mm"] == 50.0
    assert bad["max_count"] == tabs.EVEN_MAX_RANGE[1] and bad["min_perimeter_mm"] == 0.0
    assert bad["replace"] is False
    assert tabs._clean_even({"count": 99, "spacing_mm": 0.1})["count"] == tabs.EVEN_COUNT_RANGE[1]
    assert tabs._clean_even({"spacing_mm": 0.1})["spacing_mm"] == tabs.EVEN_SPACING_RANGE[0]
    assert tabs._clean_even({"count": 2.6})["count"] == 3


def test_even_count_by_count_spacing_and_limits():
    assert tabs.even_count(200, 2.0, "count", 4, 50) == 4
    assert tabs.even_count(200, 2.0, "spacing", 4, 50) == 4
    assert tabs.even_count(200, 2.0, "spacing", 4, 60) == 3          # 200 // 60
    assert tabs.even_count(30, 2.0, "spacing", 4, 50) == 1           # mindestens einer
    assert tabs.even_count(119.99999999, 2.0, "spacing", 4, 30) == 4  # Rundung des Umfangs
    assert tabs.even_count(200, 2.0, "spacing", 4, 10, max_count=6) == 6
    assert tabs.even_count(200, 2.0, "spacing", 4, 10, max_count=0) == 20
    # jedes Schnittstück mindestens eine Stegbreite: höchstens L // (2 · Breite)
    assert tabs.even_count(12, 2.0, "count", 24, 50) == 3
    assert tabs.even_count(3, 2.0, "count", 4, 50) == 0


def test_points_are_evenly_spaced_on_the_outline_and_off_the_start():
    ring = square(0, 0, 40)                                   # Umfang 160, Start (0, 0)
    pts = tabs.even_points_on_ring(ring, 4, 2.0)
    assert pts == [pytest.approx(p) for p in [(20, 0), (40, 20), (20, 40), (0, 20)]]
    cum = _cum_lengths(ring)
    s = sorted(project_on_poly(ring, p, cum)[1] for p in tabs.even_points_on_ring(ring, 8, 2.0))
    assert all(b - a == pytest.approx(20.0) for a, b in zip(s, s[1:]))
    assert s[0] == pytest.approx(10.0)                        # halber Abschnitt nach dem Start
    assert tabs.even_points_on_ring(ring, 0, 2.0) == []
    assert tabs.even_points_on_ring([(0, 0), (1, 0), (0, 0)], 2, 2.0) == []


def test_corners_are_avoided_only_when_asked():
    ring = square(0, 0, 40)
    # 2 Stege: Mitten bei 40 und 120 – genau auf den Ecken (40, 0) und (0, 40)
    raw = tabs.even_points_on_ring(ring, 2, 2.0, avoid_corners=False)
    assert raw == [pytest.approx((40.0, 0.0)), pytest.approx((0.0, 40.0))]
    moved = tabs.even_points_on_ring(ring, 2, 2.0, avoid_corners=True)
    for p, corner in zip(moved, [(40.0, 0.0), (0.0, 40.0)]):
        assert math.dist(p, corner) == pytest.approx(1.5)     # Breite/2 + 0,5 mm
    assert all(tabs.nearest_on_rings([ring], p)[0] < 1e-9 for p in moved)


def test_place_skips_holes_of_the_same_layer_and_own_holes(doc):
    lid = doc.active_layer_id
    plate, hole = rect(lid, 10, 10, 60, 40), ellipse(lid, 30, 20, 10, 10)
    for s in (plate, hole):
        doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [plate, hole], {"count": 3})
    assert [s.id for s in res.add] == [plate.id] and res.skipped_inner == 1
    assert res.tabs == 3 and res.contours == 1 and len(res.add[0].tabs) == 3
    assert on_outline(res.add[0], res.add[0].tab_points())
    # Loch allein gewählt: liegt trotzdem in der Platte derselben Ebene
    assert tabs.place_even_tabs(doc, [hole], {"count": 3}).changed == 0
    # „Innere Konturen auslassen“ aus: auch das Loch
    res = tabs.place_even_tabs(doc, [plate, hole], {"count": 3, "skip_inner": False})
    assert res.changed == 2 and res.tabs == 6 and res.skipped_inner == 0
    # eigene Löcher eines kombinierten Objekts
    a = Shape.from_points("polygon", square(100, 10, 40)[:-1], lid)
    b = Shape.from_points("polygon", square(110, 20, 20)[:-1], lid)
    (frame,) = pathsplit.combine([a, b]).add
    doc.add_shape(frame)
    res = tabs.place_even_tabs(doc, [frame], {"count": 2})
    assert res.skipped_inner == 1 and res.tabs == 2
    outer = square(100, 10, 40)
    assert all(tabs.nearest_on_rings([outer], p)[0] < 1e-6 for p in res.add[0].tab_points())


def test_shapes_on_another_layer_are_not_outer_shapes(doc):
    lid = doc.active_layer_id
    plate = rect(lid, 10, 10, 60, 40)
    lid2 = doc.add_layer(Layer("Schnitt 2", tab_width_mm=2.0)).id
    inner = rect(lid2, 20, 20, 20, 10)
    doc.add_shape(plate)
    doc.add_shape(inner)
    res = tabs.place_even_tabs(doc, [inner], {"count": 2})
    assert res.changed == 1 and res.skipped_inner == 0


def test_min_perimeter_and_too_short_contours(doc):
    lid = doc.active_layer_id
    small, big = rect(lid, 0, 0, 3, 3), rect(lid, 20, 0, 40, 20)   # Umfang 12 / 120
    for s in (small, big):
        doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [small, big], {"count": 4, "min_perimeter_mm": 20})
    assert [s.id for s in res.add] == [big.id] and res.too_short == 1
    assert "1 Kontur(en) zu kurz" in res.readout()
    # ohne Mindestumfang: die kleine Kontur bekommt so viele, wie hineinpassen (12 // 4 = 3)
    res = tabs.place_even_tabs(doc, [small], {"count": 4, "min_perimeter_mm": 0})
    assert res.tabs == 3


def test_replace_or_add_and_untouched_objects(doc):
    lid = doc.active_layer_id
    s = tabs.with_tab_points(rect(lid), [(52.0, 50.0)])
    doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [s], {"count": 2})
    assert res.removed == 1 and len(res.add[0].tabs) == 2
    assert (52.0, 50.0) not in [tuple(round(c, 6) for c in p) for p in res.add[0].tab_points()]
    assert "1 alte(r) manuelle(r) Steg(e) ersetzt" in res.readout()
    res = tabs.place_even_tabs(doc, [s], {"count": 2, "replace": False})
    assert res.removed == 0 and len(res.add[0].tabs) == 3
    # ergänzen mit denselben Stegen: nichts Neues → keine Änderung
    done = res.add[0]
    doc.shapes[0] = done
    assert tabs.place_even_tabs(doc, [done], {"count": 2, "replace": False}).changed == 0
    # nichts zu setzen (Mindestumfang): vorhandene Stege bleiben
    assert tabs.place_even_tabs(doc, [done], {"count": 2, "min_perimeter_mm": 500}).changed == 0
    # Linien / offene Pfade und Bilder bekommen keine Stege
    line = Shape("line", Geometry(0, 0, 50, 0), lid)
    assert tabs.place_even_tabs(doc, [line], {}).changed == 0


def test_rotated_shapes_and_text_get_points_on_their_outline(doc):
    lid = doc.active_layer_id
    r = rect(lid, rot=30.0)
    t = Shape("text", Geometry(10, 100, 30, 12), lid, text="O")
    for s in (r, t):
        doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [r, t], {"count": 2, "min_perimeter_mm": 0})
    assert res.changed == 2
    for s in res.add:
        assert on_outline(s, s.tab_points(), 1e-6)
    # „O“: Innenring ausgelassen, Außenring zwei Stege
    t2 = next(s for s in res.add if s.kind == "text")
    assert len(t2.tabs) == 2 and res.skipped_inner == 1


def test_readout_warns_about_zero_width_and_auto_tabs(doc):
    lid = doc.active_layer_id
    s = rect(lid)
    doc.add_shape(s)
    doc.update_layer(lid, tab_width_mm=0.0)
    res = tabs.place_even_tabs(doc, [s], {"count": 4})
    assert res.tabs == 4 and "Stegbreite 0" in res.readout()
    doc.update_layer(lid, tab_width_mm=2.0, tab_count=3)
    text = tabs.place_even_tabs(doc, [s], {"count": 4}).readout()
    assert "Stegbreite 0" not in text and "automatischen Stege" in text
    assert tabs.EvenTabsResult().readout() == "keine Stege gesetzt"


# --- Planer / G-Code -----------------------------------------------------------------

def test_gcode_burns_perimeter_minus_even_tabs_through_the_pi_guard(doc):
    lid = doc.active_layer_id
    s = rect(lid)
    doc.add_shape(s)
    before = optimized_document_gcode(doc, scan_offsets=None)
    res = tabs.place_even_tabs(doc, [s], {"count": 4})
    doc.shapes[0] = res.add[0]
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert burned(g) == pytest.approx(120.0 - 4 * 2.0, abs=1e-3)
    assert gaps(g) == 4 and report.manual_tabs == 4 and report.dropped_tabs == 0
    pi_check(g)
    assert not re.search(r"^G[23]\b", g, re.M)
    # gleich viel Steg wie die automatischen Stege der Ebene mit derselben Anzahl
    auto = Document()
    auto.update_layer(auto.active_layer_id, tab_width_mm=2.0, tab_count=4)
    auto.add_shape(rect(auto.active_layer_id))
    assert burned(optimized_document_gcode(auto, scan_offsets=None)) == pytest.approx(burned(g), abs=1e-3)
    # ohne die Aktion: G-Code unverändert
    doc.shapes[0] = s
    assert optimized_document_gcode(doc, scan_offsets=None) == before


def test_gcode_with_kerf_and_rotation_keeps_every_tab(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.2)
    s = rect(lid, rot=20.0)
    doc.add_shape(s)
    doc.shapes[0] = tabs.place_even_tabs(doc, [s], {"mode": "spacing", "spacing_mm": 30}).add[0]
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert report.manual_tabs == 4 and report.dropped_tabs == 0
    assert burned(g) == pytest.approx(2 * (40.4 + 20.4) - 4 * 2.0, abs=0.05)
    pi_check(g)


# --- Dialog / Aktion ----------------------------------------------------------------

def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def test_dialog_fields_readout_and_ok_button(doc, qapp):
    lid = doc.active_layer_id
    s = rect(lid)
    doc.add_shape(s)
    dlg = EvenTabsDialog(doc, [s], values={"count": 3})
    try:
        assert dlg.values() == {**tabs.even_defaults(), "count": 3}
        assert "3 Stege an 1 Kontur" in dlg.readout.text()
        assert dlg.count.isEnabled() and not dlg.spacing.isEnabled() and not dlg.max_count.isEnabled()
        dlg.mode.setCurrentIndex(dlg.mode.findData("spacing"))
        assert dlg.spacing.isEnabled() and dlg.max_count.isEnabled() and not dlg.count.isEnabled()
        dlg.spacing.setValue(20.0)
        assert "6 Stege" in dlg.readout.text()
        dlg.max_count.setValue(5)
        assert "5 Stege" in dlg.readout.text()
        assert dlg.max_count.text() and dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
        dlg.min_perimeter.setValue(500.0)
        assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
        assert "zu kurz" in dlg.readout.text()
    finally:
        dlg.close()


def test_action_in_path_menu_one_undo_step_and_scope(ed):
    msgs = []
    ed.statusMessage.connect(msgs.append)
    lid = ed.document.active_layer_id
    ed.document.update_layer(lid, tab_width_mm=2.0)
    a, b, c = _add(ed, [rect(lid), rect(lid, y=100), ellipse(lid, 60, 52, 10, 10)])
    texts = [x.text() for x in ed.path_ops_button.menu().actions() if x.text()]
    i = texts.index("Stege")
    assert texts[i:i + 3] == ["Stege", "Stege gleichmäßig setzen …", "Manuelle Stege entfernen"]
    assert "gleichmäßig" in ed.path_ops_button.toolTip()
    asked = []
    ed.tab_tool.even.ask = lambda shapes: asked.append([s.id for s in shapes]) or {"count": 2}
    ed.set_selection([a.id, c.id])
    n0 = ed.undo_stack.count()
    ed.actions_by_name["tabs_even"].trigger()
    assert asked[-1] == [a.id, c.id]
    assert ed.undo_stack.count() == n0 + 1
    assert [len(s.tabs) for s in ed.document.shapes] == [2, 0, 0]      # Loch ausgelassen
    assert "Stege gleichmäßig setzen: 2 Stege an 1 Kontur" in msgs[-1]
    assert "1 innere Kontur(en) ausgelassen" in msgs[-1]
    assert sorted(ed.selection) == sorted([a.id, c.id])
    assert len(ed.tab_tool.item.marks) == 2
    assert ed.tab_tool.even.last["count"] == 2
    ed.undo_stack.undo()
    assert all(not s.tabs for s in ed.document.shapes)
    # ohne Auswahl: alle bearbeitbaren Objekte
    ed.set_selection([])
    ed.actions_by_name["tabs_even"].trigger()
    assert asked[-1] == [a.id, b.id, c.id]
    assert [len(s.tabs) for s in ed.document.shapes] == [2, 2, 0]
    # abgebrochen: nichts
    ed.tab_tool.even.ask = lambda shapes: None
    n1 = ed.undo_stack.count()
    ed.actions_by_name["tabs_even"].trigger()
    assert ed.undo_stack.count() == n1


def test_locked_layer_and_no_closed_shapes(ed):
    msgs = []
    ed.statusMessage.connect(msgs.append)
    lid = ed.document.active_layer_id
    ed.tab_tool.even.ask = lambda shapes: pytest.fail("kein Dialog erwartet")
    ed.actions_by_name["tabs_even"].trigger()
    assert "keine geschlossenen Formen im Dokument" in msgs[-1]
    (line,) = _add(ed, [Shape("line", Geometry(0, 0, 50, 0), lid)])
    ed.set_selection([line.id])
    ed.actions_by_name["tabs_even"].trigger()
    assert "keine geschlossenen Formen in der Auswahl" in msgs[-1]
    (r,) = _add(ed, [rect(lid)])
    ed.document.update_layer(lid, locked=True)
    ed.set_selection([])
    ed.actions_by_name["tabs_even"].trigger()
    assert "keine geschlossenen Formen im Dokument" in msgs[-1]
    ed.document.update_layer(lid, locked=False)


def test_tabs_saved_and_movable_after_placement(ed, tmp_path):
    lid = ed.document.active_layer_id
    ed.document.update_layer(lid, tab_width_mm=2.0)
    (s,) = _add(ed, [rect(lid)])
    ed.tab_tool.even.ask = lambda shapes: {"count": 4}
    ed.set_selection([s.id])
    ed.actions_by_name["tabs_even"].trigger()
    pts = ed.document.shapes[0].tab_points()
    path = ed.save_file(tmp_path / "gleich.lcs")
    ed.undo_stack.setClean()
    ed.load_file(path)
    assert ed.document.shapes[0].tab_points() == [pytest.approx(p) for p in pts]
    # ein Steg einzeln entfernen wie mit dem Werkzeug
    ed.tab_tool.remove(ed.document.shapes[0].id, 0)
    assert len(ed.document.shapes[0].tabs) == 3


def test_touch_mode_dialog_opens(ed, qapp):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [rect(lid)])
    ed.set_touch_mode(True, persist=False)
    try:
        dlg = EvenTabsDialog(ed.document, [s], ed)
        dlg.show()
        qapp.processEvents()
        assert dlg.isVisible() and "Stege" in dlg.readout.text()
        dlg.close()
    finally:
        ed.set_touch_mode(False, persist=False)


def test_main_window_alt_shift_g_is_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        assert EVEN_ACTION[2] == "Alt+Shift+G"
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+G")]
        assert [a.text() for a in owners] == ["Stege gleichmäßig setzen …"]
        lid = w.canvas.document.active_layer_id
        w.canvas.document.update_layer(lid, tab_width_mm=1.5)
        w.canvas.undo_stack.push(AddShapesCommand(w.canvas.document, [rect(lid)]))
        w.canvas.tab_tool.even.ask = lambda shapes: {"mode": "spacing", "spacing_mm": 40}
        w.canvas.actions_by_name["tabs_even"].trigger()
        assert len(w.canvas.document.shapes[0].tabs) == 3
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
