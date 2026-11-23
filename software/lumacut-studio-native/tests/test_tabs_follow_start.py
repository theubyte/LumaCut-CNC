"""Gleichmäßige Stege folgen dem Startpunkt: wird der Startpunkt nach „Stege
gleichmäßig setzen …“ gesetzt, verschoben oder entfernt, verteilt LumaCut die Stege
der betroffenen Kontur ab dem neuen Start gleich (gleiche Anzahl und Eckenregel);
von Hand gesetzte Stege bleiben. Rechnung, Datei, G-Code durch den Pi-Wächter,
Werkzeug „Startpunkt“ (Setzen, Ziehen, Entfernen, Umschalt, Menü) mit Undo."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas import pathsplit, startpoint, tabs
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.tools import Tool
from lumacut_canvas.workarea import to_machine
from lumacut_job.cutpath import _cum_lengths, project_on_poly
from lumacut_job.planner import PlanReport, optimized_document_gcode

CLEAR = 2.0 / 2 + 0.5          # Startabstand bei Stegbreite 2 mm


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid)


def same_points(a, b, tol=1e-6) -> bool:
    return len(a) == len(b) and all(any(math.dist(p, q) <= tol for q in b) for p in a)


def even(doc, s, values):
    return tabs.place_even_tabs(doc, [s], values).add[0]


def gap_centres(g: str) -> list[tuple[float, float]]:
    lines = [ln for ln in g.splitlines() if ln.startswith(("G0 X", "G1 X"))]

    def xy(ln):
        parts = dict((t[0], t[1:]) for t in ln.split()[1:] if t[0] in "XY")
        return float(parts["X"]), float(parts["Y"])

    first = next(i for i, ln in enumerate(lines) if ln.startswith("G1"))
    out = []
    for prev, ln in zip(lines[first:], lines[first + 1:]):
        if ln.startswith("G0"):
            a, b = xy(prev), xy(ln)
            out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    return out


@pytest.fixture
def doc(qapp):
    d = Document()
    d.update_layer(d.active_layer_id, tab_width_mm=2.0)
    return d


# --- Rechnung ------------------------------------------------------------------------

@pytest.mark.parametrize("values", [{"count": 4}, {"count": 5, "avoid_corners": False},
                                    {"count": 3}, {"mode": "spacing", "spacing_mm": 20.0}])
def test_setting_a_start_redistributes_like_placing_after_it(doc, values):
    lid = doc.active_layer_id
    placed = even(doc, rect(lid), values)
    doc.add_shape(placed)
    res = tabs.follow_start(doc, placed, startpoint.with_start(placed, (75.0, 70.0)))
    want = even(doc, startpoint.with_start(rect(lid), (75.0, 70.0)), values)
    assert res.contours == 1 and res.tabs == len(placed.tabs) and res.kept == 0
    assert same_points(res.shape.tab_points(), want.tab_points())
    assert res.shape.start_point() == pytest.approx((75.0, 70.0))
    assert not same_points(res.shape.tab_points(), placed.tab_points())
    # jeder Steg hält den Startabstand
    rot = startpoint.rotate_ring_to(tabs.closed_rings(placed)[0], (75.0, 70.0))
    cum = _cum_lengths(rot)
    arcs = sorted(project_on_poly(rot, p, cum)[1] for p in res.shape.tab_points())
    assert arcs[0] >= CLEAR - 1e-9 and arcs[-1] <= cum[-1] - CLEAR + 1e-9


def test_corner_rule_is_kept_and_ambiguous_tabs_avoid_corners(doc):
    lid = doc.active_layer_id
    (ring,) = tabs.closed_rings(rect(lid))
    # 5 Stege ohne „Ecken meiden“: einer sitzt genau auf einer Ecke – eindeutig
    loose = even(doc, rect(lid), {"count": 5, "avoid_corners": False})
    assert tabs.even_pattern(ring, loose.tab_points(), 2.0) is False
    assert tabs.even_pattern(ring, even(doc, rect(lid), {"count": 5}).tab_points(), 2.0) is True
    # 4 Stege liegen mit und ohne Eckenregel gleich: dann mit „Ecken meiden“ weiter
    four = even(doc, rect(lid), {"count": 4, "avoid_corners": False})
    assert tabs.even_pattern(ring, four.tab_points(), 2.0) is True
    res = tabs.follow_start(doc, four, startpoint.with_start(four, (75.0, 70.0)))
    want = even(doc, startpoint.with_start(rect(lid), (75.0, 70.0)), {"count": 4})
    assert same_points(res.shape.tab_points(), want.tab_points())
    assert tabs.even_pattern(ring, [], 2.0) is None


def test_moving_and_removing_the_start_follow_too(doc):
    lid = doc.active_layer_id
    a = even(doc, startpoint.with_start(rect(lid), (75.0, 70.0)), {"count": 4})
    doc.add_shape(a)
    moved = tabs.follow_start(doc, a, startpoint.with_start(a, (90.0, 61.0)))
    want = even(doc, startpoint.with_start(rect(lid), (90.0, 61.0)), {"count": 4})
    assert moved.contours == 1 and same_points(moved.shape.tab_points(), want.tab_points())
    gone = tabs.follow_start(doc, moved.shape, startpoint.clear_start(moved.shape))
    plain = even(doc, rect(lid), {"count": 4})
    assert gone.shape.start == () and gone.contours == 1
    assert same_points(gone.shape.tab_points(), plain.tab_points())
    # hin und zurück: wieder die Stege des Anfangs
    back = tabs.follow_start(doc, gone.shape, startpoint.with_start(gone.shape, (75.0, 70.0)))
    assert same_points(back.shape.tab_points(), a.tab_points())


def test_hand_placed_or_moved_tabs_stay(doc):
    lid = doc.active_layer_id
    placed = even(doc, rect(lid), {"count": 4})
    nudged = tabs.move_tab(placed, 0, (68.0, 49.0))                # ein Steg von Hand verschoben
    res = tabs.follow_start(doc, nudged, startpoint.with_start(nudged, (75.0, 70.0)))
    assert res.contours == 0 and res.kept == 1 and res.shape.tabs == nudged.tabs
    assert res.shape.start_point() == pytest.approx((75.0, 70.0))
    assert "von Hand gesetzte Stege an 1 Kontur unverändert" in res.readout()
    added, _ = tabs.add_tab(placed, (55.0, 70.0), 1.0)             # einer dazu
    res = tabs.follow_start(doc, added, startpoint.with_start(added, (75.0, 70.0)))
    assert res.contours == 0 and res.kept == 1 and res.shape.tabs == added.tabs
    single, _ = tabs.add_tab(rect(lid), (52.0, 50.0), 1.0)         # einzelner Handsteg
    res = tabs.follow_start(doc, single, startpoint.with_start(single, (75.0, 70.0)))
    assert res.kept == 1 and res.shape.tabs == single.tabs


def test_nothing_to_follow_returns_the_new_shape(doc):
    lid = doc.active_layer_id
    s = rect(lid)
    new = startpoint.with_start(s, (75.0, 70.0))
    res = tabs.follow_start(doc, s, new)                             # keine Stege
    assert res.shape is new and res.readout() == ""
    placed = even(doc, rect(lid), {"count": 4})
    far = startpoint.with_start(placed, (70.0, 75.0))                # 5 mm neben dem Umriss: ignoriert
    res = tabs.follow_start(doc, placed, far)
    assert res.shape is far and res.contours == 0 and res.kept == 0
    same = startpoint.with_start(placed, (50.0, 50.0))               # = gezeichneter Konturstart
    res = tabs.follow_start(doc, placed, same)
    assert res.shape is same and res.contours == 0


def test_changed_tab_width_counts_only_where_it_moved_a_tab(doc):
    lid = doc.active_layer_id
    placed = even(doc, rect(lid), {"count": 5})                      # ein Steg 1,5 mm neben einer Ecke
    doc.update_layer(lid, tab_width_mm=6.0)                          # danach geändert: wäre 3,5 mm
    res = tabs.follow_start(doc, placed, startpoint.with_start(placed, (75.0, 70.0)))
    assert res.contours == 0 and res.kept == 1 and res.shape.tabs == placed.tabs
    four = even(doc, rect(lid), {"count": 4})                        # ohne Eckenschub: breitenunabhängig
    doc.update_layer(lid, tab_width_mm=2.0)
    res = tabs.follow_start(doc, four, startpoint.with_start(four, (75.0, 70.0)))
    assert res.contours == 1
    doc.update_layer(lid, tab_width_mm=0.0)                          # 0: mit Ersatzbreite verteilt
    placed = even(doc, rect(lid), {"count": 5})
    res = tabs.follow_start(doc, placed, startpoint.with_start(placed, (75.0, 70.0)))
    assert res.contours == 1 and res.kept == 0


def test_start_moving_from_outer_ring_to_hole(doc):
    lid = doc.active_layer_id
    a = Shape.from_points("polygon", square(100, 10, 40)[:-1], lid)
    b = Shape.from_points("polygon", square(110, 20, 20)[:-1], lid)
    (frame,) = pathsplit.combine([a, b]).add
    doc.add_shape(frame)
    values = {"count": 4, "skip_inner": False}
    on_outer = startpoint.with_start(frame, (120.0, 10.0))
    placed = even(doc, on_outer, values)
    res = tabs.follow_start(doc, placed, startpoint.with_start(placed, (120.0, 20.0)))
    want = even(doc, startpoint.with_start(frame, (120.0, 20.0)), values)
    assert res.contours == 2 and res.tabs == 8                       # außen zurück, Loch ab Start
    assert same_points(res.shape.tab_points(), want.tab_points())
    # Loch ausgelassen: nur die Außenkontur hat Stege, nur sie folgt
    placed = even(doc, on_outer, {"count": 4})
    res = tabs.follow_start(doc, placed, startpoint.with_start(placed, (120.0, 20.0)))
    assert res.contours == 1 and len(res.shape.tabs) == 4
    assert same_points(res.shape.tab_points(), even(doc, frame, {"count": 4}).tab_points())


def test_rotated_shape_and_saved_project(doc):
    lid = doc.active_layer_id
    base = rect(lid, rot=30.0)
    placed = even(doc, base, {"count": 3})
    loaded = Shape.from_dict(placed.to_dict())                       # 6 Nachkommastellen in der Datei
    (ring,) = tabs.closed_rings(loaded)
    res = tabs.follow_start(doc, loaded, startpoint.with_start(loaded, ring[2]))
    want = even(doc, startpoint.with_start(base, ring[2]), {"count": 3})
    assert res.contours == 1 and same_points(res.shape.tab_points(), want.tab_points(), tol=1e-3)


def test_readout_texts(doc):
    r = tabs.FollowResult(shape=None, contours=2, tabs=8, kept=1)
    assert r.readout() == ("8 Stege an 2 Konturen ab dem neuen Start gleichmäßig neu verteilt · "
                           "von Hand gesetzte Stege an 1 Kontur unverändert")
    assert tabs.FollowResult(shape=None, contours=1, tabs=1).readout() == \
        "1 Steg an 1 Kontur ab dem neuen Start gleichmäßig neu verteilt"


# --- G-Code --------------------------------------------------------------------------

def test_gcode_gaps_sit_on_the_followed_tabs(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, lead_in_mm=2.0)
    placed = even(doc, rect(lid), {"count": 4})
    doc.add_shape(placed)
    # ohne Nachziehen: ein Steg liegt auf dem neuen Start, der Planer schiebt ihn weg
    doc.shapes[0] = startpoint.with_start(placed, (75.0, 70.0))
    g_old = optimized_document_gcode(doc, scan_offsets=None)
    assert not same_points(gap_centres(g_old), [to_machine(*p) for p in placed.tab_points()], 1e-3)
    new = tabs.follow_start(doc, placed, startpoint.with_start(placed, (75.0, 70.0))).shape
    doc.shapes[0] = new
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert same_points(gap_centres(g), [to_machine(*p) for p in new.tab_points()], 1e-3)
    assert report.manual_tabs == 4 and report.dropped_tabs == 0 and report.manual_starts == 1
    pi_check(g)


# --- Werkzeug „Startpunkt“ -----------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.msgs = []
    e.statusMessage.connect(e.msgs.append)
    e.document.update_layer(e.document.active_layer_id, tab_width_mm=2.0)
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def click(ed, x, y, mods=Qt.NoModifier):
    ed.tools.press(QPointF(x, y), mods)
    ed.tools.release(QPointF(x, y), mods)


def test_tool_click_redistributes_in_one_undo_step(ed):
    doc = ed.document
    lid = doc.active_layer_id
    (s,) = _add(ed, [even(doc, rect(lid), {"count": 4})])
    ed.set_tool(Tool.START)
    n0 = ed.undo_stack.count()
    click(ed, 75.0, 70.2)
    cur = doc.shape(s.id)
    want = even(doc, startpoint.with_start(rect(lid), (75.0, 70.0)), {"count": 4})
    assert same_points(cur.tab_points(), want.tab_points())
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Startpunkt setzen"
    assert "Startpunkt gesetzt" in ed.msgs[-1]
    assert "4 Stege an 1 Kontur ab dem neuen Start gleichmäßig neu verteilt" in ed.msgs[-1]
    ed.undo_stack.undo()
    assert doc.shape(s.id).start == () and doc.shape(s.id).tabs == s.tabs
    ed.undo_stack.redo()
    click(ed, 75.1, 70.0)                                          # Tippen auf den Punkt entfernt
    assert doc.shape(s.id).start == () and "Startpunkt entfernt" in ed.msgs[-1]
    assert same_points(doc.shape(s.id).tab_points(), s.tab_points())
    assert "neu verteilt" in ed.msgs[-1]


def test_tool_drag_moves_tabs_live_and_escape_restores(ed):
    doc = ed.document
    lid = doc.active_layer_id
    (s,) = _add(ed, [even(doc, startpoint.with_start(rect(lid), (75.0, 70.0)), {"count": 4})])
    ed.set_tool(Tool.START)
    n0 = ed.undo_stack.count()
    ed.tools.press(QPointF(75.0, 70.0), Qt.NoModifier)
    ed.tools.move(QPointF(85.0, 72.0), Qt.NoModifier, True)
    want = even(doc, startpoint.with_start(rect(lid), (85.0, 70.0)), {"count": 4})
    assert same_points(doc.shape(s.id).tab_points(), want.tab_points())     # schon beim Ziehen
    ed.tools.move(QPointF(90.5, 61.0), Qt.NoModifier, True)
    ed.tools.release(QPointF(90.5, 61.0), Qt.NoModifier)
    want = even(doc, startpoint.with_start(rect(lid), (90.0, 61.0)), {"count": 4})
    assert same_points(doc.shape(s.id).tab_points(), want.tab_points())
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Startpunkt verschieben"
    assert "Startpunkt verschoben" in ed.msgs[-1] and "neu verteilt" in ed.msgs[-1]
    ed.undo_stack.undo()
    assert doc.shape(s.id).tabs == s.tabs and doc.shape(s.id).start == s.start
    ed.tools.press(QPointF(75.0, 70.0), Qt.NoModifier)
    ed.tools.move(QPointF(85.0, 72.0), Qt.NoModifier, True)
    assert doc.shape(s.id).tabs != s.tabs
    ed.tools.cancel()
    assert doc.shape(s.id).tabs == s.tabs and doc.shape(s.id).start == s.start


def test_tool_keeps_hand_tabs_and_says_so(ed):
    doc = ed.document
    lid = doc.active_layer_id
    hand = tabs.move_tab(even(doc, rect(lid), {"count": 4}), 0, (68.0, 49.0))
    (s,) = _add(ed, [hand])
    ed.set_tool(Tool.START)
    click(ed, 75.0, 70.0)
    assert doc.shape(s.id).tabs == hand.tabs and doc.shape(s.id).start
    assert "von Hand gesetzte Stege an 1 Kontur unverändert" in ed.msgs[-1]


def test_shift_click_sets_reverses_and_redistributes(ed):
    doc = ed.document
    lid = doc.active_layer_id
    (s,) = _add(ed, [even(doc, rect(lid), {"count": 4})])
    ed.set_tool(Tool.START)
    n0 = ed.undo_stack.count()
    click(ed, 75.0, 70.0, Qt.ShiftModifier)
    cur = doc.shape(s.id)
    want = even(doc, startpoint.with_start(rect(lid), (75.0, 70.0)), {"count": 4})
    assert cur.reverse and same_points(cur.tab_points(), want.tab_points())
    assert ed.undo_stack.count() == n0 + 1 and "neu verteilt" in ed.msgs[-1]


def test_clear_action_puts_even_tabs_back_from_the_drawn_start(ed):
    doc = ed.document
    lid = doc.active_layer_id
    a, b = _add(ed, [even(doc, startpoint.with_start(rect(lid), (75.0, 70.0)), {"count": 4}),
                     startpoint.with_start(rect(lid, y=100), (70.0, 100.0))])
    ed.set_selection([a.id, b.id])
    n0 = ed.undo_stack.count()
    ed.actions_by_name["start_clear"].trigger()
    assert ed.undo_stack.count() == n0 + 1 and all(not s.start for s in doc.shapes)
    assert same_points(doc.shape(a.id).tab_points(), even(doc, rect(lid), {"count": 4}).tab_points())
    assert doc.shape(b.id).tabs == ()
    assert "2 Startpunkte entfernt" in ed.msgs[-1]
    assert "4 gleichmäßige(r) Steg(e) ab dem gezeichneten Konturstart neu verteilt" in ed.msgs[-1]
    ed.undo_stack.undo()
    assert doc.shape(a.id).tabs == a.tabs and doc.shape(a.id).start == a.start


def test_dialog_tooltip_mentions_tabs_following_the_start(qapp):
    from lumacut_canvas.tabs_ui import EvenTabsDialog
    d = Document()
    s = rect(d.active_layer_id)
    d.add_shape(s)
    dlg = EvenTabsDialog(d, [s], values={"count": 4})
    try:
        assert "wandern die Stege mit" in dlg.mode.toolTip()
    finally:
        dlg.reject()
