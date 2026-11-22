"""„Stege gleichmäßig setzen …“ mit gesetztem Startpunkt: die Kontur, auf der der
Startpunkt liegt, wird ab ihm verteilt (dort beginnt beim Senden der Schnitt bzw. die
Anfahrt) – kein Steg muss vom Planer vom Start weggeschoben werden. Rechnung, Vorschau,
Auslesung, G-Code durch den Pi-Wächter, Dialog-Tooltip."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check

from lumacut_canvas import pathsplit, startpoint, tabs
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.tabs_ui import EvenTabsDialog
from lumacut_canvas.workarea import to_machine
from lumacut_job.cutpath import _cum_lengths, project_on_poly
from lumacut_job.planner import PlanReport, optimized_document_gcode

CLEAR = 2.0 / 2 + 0.5          # Startabstand bei Stegbreite 2 mm


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid)


def gap_centres(g: str) -> list[tuple[float, float]]:
    """Mitten der Laser-aus-Lücken innerhalb des Schnitts (Maschinen-mm)."""
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


def same_points(a, b, tol=1e-3) -> bool:
    return len(a) == len(b) and all(any(math.dist(p, q) <= tol for q in b) for p in a)


def arc_from_start(ring, start, pts):
    rot = startpoint.rotate_ring_to(ring, start)
    cum = _cum_lengths(rot)
    return rot, cum[-1], sorted(project_on_poly(rot, p, cum)[1] for p in pts)


@pytest.fixture
def doc(qapp):
    d = Document()
    d.update_layer(d.active_layer_id, tab_width_mm=2.0)
    return d


# --- Rechnung ------------------------------------------------------------------------

def test_start_ring_index_nearest_ring_within_snap_distance(doc):
    lid = doc.active_layer_id
    s = rect(lid)
    rings = tabs.closed_rings(s)
    assert tabs.start_ring_index(s, rings) == -1                       # ohne Startpunkt
    assert tabs.start_ring_index(startpoint.with_start(s, (70.0, 70.0)), rings) == 0
    assert tabs.start_ring_index(startpoint.with_start(s, (70.0, 71.4)), rings) == 0
    assert tabs.start_ring_index(startpoint.with_start(s, (70.0, 72.0)), rings) == -1   # > 1,5 mm
    assert tabs.start_ring_index(None, rings) == -1
    assert tabs.start_ring_index(startpoint.with_start(s, (70.0, 70.0)), []) == -1
    a = Shape.from_points("polygon", square(100, 10, 40)[:-1], lid)
    b = Shape.from_points("polygon", square(110, 20, 20)[:-1], lid)
    (frame,) = pathsplit.combine([a, b]).add
    frings = tabs.closed_rings(frame)
    k = tabs.start_ring_index(startpoint.with_start(frame, (120.0, 20.0)), frings)
    assert tabs.nearest_on_rings([frings[k]], (120.0, 20.0))[0] < 1e-6   # der Loch-Ring


def test_ring_is_distributed_from_the_start_point(doc):
    lid = doc.active_layer_id
    s = startpoint.with_start(rect(lid), (75.0, 70.0))
    doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [s], {"count": 4, "avoid_corners": False})
    pts = res.add[0].tab_points()
    (ring,) = tabs.closed_rings(s)
    rot, L, arcs = arc_from_start(ring, (75.0, 70.0), pts)
    assert L == pytest.approx(120.0)
    assert arcs == [pytest.approx(a) for a in (15.0, 45.0, 75.0, 105.0)]   # (i + ½) · L / n ab Start
    assert res.from_start == 1 and res.tabs == 4
    assert pts == [pytest.approx(p) for p in tabs.even_points_on_ring(rot, 4, 2.0, False)]
    assert all(tabs.nearest_on_rings([ring], p)[0] < 1e-9 for p in pts)


def test_every_tab_keeps_the_start_clearance_also_with_corners(doc):
    lid = doc.active_layer_id
    s = startpoint.with_start(rect(lid), (75.0, 70.0))
    doc.add_shape(s)
    for values in ({"count": 4}, {"count": 6}, {"mode": "spacing", "spacing_mm": 20.0},
                   {"count": 4, "avoid_corners": False}):
        pts = tabs.place_even_tabs(doc, [s], values).add[0].tab_points()
        _rot, L, arcs = arc_from_start(tabs.closed_rings(s)[0], (75.0, 70.0), pts)
        assert arcs[0] >= CLEAR - 1e-9 and arcs[-1] <= L - CLEAR + 1e-9, values
    # ohne Startabstands-Rücksicht lag hier ein Steg genau auf dem Startpunkt
    old = tabs.place_even_tabs(doc, [rect(lid)], {"count": 4}).add[0].tab_points()
    assert min(math.dist(p, (75.0, 70.0)) for p in old) < 1e-6


def test_without_start_point_placement_is_unchanged(doc):
    lid = doc.active_layer_id
    s = rect(lid)
    doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [s], {"count": 4})
    assert res.add[0].tab_points() == [pytest.approx(p) for p in
                                       [(65.0, 50.0), (90.0, 55.0), (75.0, 70.0), (50.0, 65.0)]]
    assert res.from_start == 0 and "Startpunkt" not in res.readout()


def test_start_far_from_every_ring_is_ignored(doc):
    lid = doc.active_layer_id
    plain = rect(lid)
    s = startpoint.with_start(plain, (70.0, 75.0))                    # 5 mm neben dem Umriss
    doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [s], {"count": 4})
    assert res.from_start == 0
    assert res.add[0].tab_points() == [pytest.approx(p) for p in
                                       tabs.place_even_tabs(doc, [plain], {"count": 4}).add[0].tab_points()]


def test_rotated_shape_distributes_from_its_rotated_start(doc):
    lid = doc.active_layer_id
    base = rect(lid, rot=30.0)
    (ring,) = tabs.closed_rings(base)
    start = ring[2]                                                   # eine Ecke des gedrehten Rechtecks
    s = startpoint.with_start(base, start)
    doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [s], {"count": 3})
    pts = res.add[0].tab_points()
    _rot, L, arcs = arc_from_start(ring, start, pts)
    assert res.from_start == 1 and len(pts) == 3
    assert arcs[0] >= CLEAR - 1e-9 and arcs[-1] <= L - CLEAR + 1e-9
    assert all(tabs.nearest_on_rings([ring], p)[0] < 1e-6 for p in pts)


def test_only_the_ring_with_the_start_is_rotated(doc):
    lid = doc.active_layer_id
    a = Shape.from_points("polygon", square(100, 10, 40)[:-1], lid)
    b = Shape.from_points("polygon", square(110, 20, 20)[:-1], lid)
    (frame,) = pathsplit.combine([a, b]).add
    doc.add_shape(frame)
    plain = tabs.place_even_tabs(doc, [frame], {"count": 4, "skip_inner": False,
                                                "avoid_corners": False}).add[0].tab_points()
    s = startpoint.with_start(frame, (120.0, 20.0))                   # Startpunkt auf dem Loch
    doc.shapes[0] = s
    res = tabs.place_even_tabs(doc, [s], {"count": 4, "skip_inner": False, "avoid_corners": False})
    outer, hole = sorted(tabs.closed_rings(s), key=lambda r: -tabs.ring_length(r))
    on_outer = [p for p in res.add[0].tab_points() if tabs.nearest_on_rings([outer], p)[0] < 1e-6]
    assert on_outer == [pytest.approx(p) for p in plain
                        if tabs.nearest_on_rings([outer], p)[0] < 1e-6]   # Außenkontur unverändert
    on_hole = [p for p in res.add[0].tab_points() if tabs.nearest_on_rings([hole], p)[0] < 1e-6]
    _rot, L, arcs = arc_from_start(hole, (120.0, 20.0), on_hole)
    assert L == pytest.approx(80.0) and arcs == [pytest.approx(a) for a in (10.0, 30.0, 50.0, 70.0)]
    assert res.from_start == 1
    # Loch ausgelassen („Innere Konturen auslassen“): nichts ab dem Startpunkt verteilt
    res = tabs.place_even_tabs(doc, [s], {"count": 4})
    assert res.skipped_inner == 1 and res.from_start == 0


def test_readout_counts_contours_from_the_start(doc):
    lid = doc.active_layer_id
    a = startpoint.with_start(rect(lid), (75.0, 70.0))
    b = startpoint.with_start(rect(lid, 120.0, 50.0), (130.0, 50.0))
    c = rect(lid, 50.0, 100.0)
    for s in (a, b, c):
        doc.add_shape(s)
    res = tabs.place_even_tabs(doc, [a, b, c], {"count": 2})
    assert res.from_start == 2 and res.contours == 3
    assert "2 Kontur(en) ab dem gesetzten Startpunkt verteilt" in res.readout()
    # nichts gesetzt (zu kurz): kein Hinweis
    tiny = startpoint.with_start(rect(lid, 10, 10, 2, 2), (11.0, 10.0))
    doc.add_shape(tiny)
    res = tabs.place_even_tabs(doc, [tiny], {"count": 2})
    assert res.tabs == 0 and "Startpunkt" not in res.readout()


# --- G-Code --------------------------------------------------------------------------

def test_gcode_cuts_every_tab_exactly_where_it_was_placed(doc):
    lid = doc.active_layer_id
    s = startpoint.with_start(rect(lid), (75.0, 70.0))
    doc.add_shape(s)
    report = PlanReport()
    # vorher (ohne Rücksicht auf den Startpunkt): der Planer muss einen Steg vom Start schieben
    old = tabs.place_even_tabs(doc, [rect(lid)], {"count": 4}).add[0]
    doc.shapes[0] = startpoint.with_start(old, (75.0, 70.0))
    g_old = optimized_document_gcode(doc, scan_offsets=None)
    assert not same_points(gap_centres(g_old), [to_machine(*p) for p in old.tab_points()])
    # jetzt: jede Lücke sitzt genau auf ihrem Steg
    new = tabs.place_even_tabs(doc, [s], {"count": 4}).add[0]
    doc.shapes[0] = new
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert same_points(gap_centres(g), [to_machine(*p) for p in new.tab_points()])
    assert report.manual_tabs == 4 and report.dropped_tabs == 0 and report.manual_starts == 1
    pi_check(g)
    assert not any(ln.split()[0] in ("G2", "G3") for ln in g.splitlines() if ln.strip())


def test_gcode_with_kerf_and_lead_in_keeps_the_even_spots(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.2, lead_in_mm=2.0)
    s = startpoint.with_start(rect(lid), (75.0, 70.0))
    doc.add_shape(s)
    new = tabs.place_even_tabs(doc, [s], {"count": 4}).add[0]
    doc.shapes[0] = new
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert report.manual_tabs == 4 and report.dropped_tabs == 0
    pi_check(g)
    centres = gap_centres(g)
    for p in new.tab_points():                       # Kerf-Versatz 0,2 mm nach außen, nicht entlang
        assert min(math.dist(to_machine(*p), c) for c in centres) == pytest.approx(0.2, abs=1e-3)


# --- Bedienung -----------------------------------------------------------------------

def test_dialog_readout_and_mode_tooltip_mention_the_start(doc, qapp):
    lid = doc.active_layer_id
    s = startpoint.with_start(rect(lid), (75.0, 70.0))
    doc.add_shape(s)
    dlg = EvenTabsDialog(doc, [s], values={"count": 4})
    try:
        assert "Startpunkt" in dlg.mode.toolTip()
        assert "ab dem gesetzten Startpunkt verteilt" in dlg.readout.text()
    finally:
        dlg.close()


def test_dialog_preview_shows_the_bars_from_the_start_point(doc, qapp):
    lid = doc.active_layer_id
    s = startpoint.with_start(rect(lid), (75.0, 70.0))
    doc.add_shape(s)
    seen = []
    dlg = EvenTabsDialog(doc, [s], values={"count": 4}, on_preview=seen.append)
    try:
        dlg.update_readout()
        res = seen[-1]
        assert res is not None and res.from_start == 1
        expected = tabs.place_even_tabs(doc, [s], {"count": 4}).add[0].tab_points()
        assert same_points(res.add[0].tab_points(), expected, tol=1e-9)
        plain = tabs.place_even_tabs(doc, [rect(lid)], {"count": 4}).add[0].tab_points()
        assert not same_points(res.add[0].tab_points(), plain)
        assert doc.shapes[0].tabs == s.tabs == ()                      # nur Vorschau
    finally:
        dlg.reject()
