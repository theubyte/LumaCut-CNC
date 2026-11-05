"""Live park-corner box with cut options / scan offset (lumacut_job.park_zone).

Kerf offset, lead-ins / lead-outs and the fill scan offset burn outside the
object boxes; the live warning must flag exactly what the send-time check
(``park_corner.check_job`` on the planned G-code) refuses. Fill overscan is
laser-off and must not count.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_job import park_corner as pc
from lumacut_job import park_zone as pz
from lumacut_job import planner
from lumacut_job import scan_offset as so


class FakePanel(QObject):
    status_changed = Signal(object)

    def __init__(self, status=None, origin="absolute", anchor="tr"):
        super().__init__()
        self._status = status
        self.origin = origin
        self.anchor = anchor

    def job_origin(self):
        return self.origin, self.anchor


class FakeEditor(QObject):
    documentChanged = Signal()
    selectionChanged = Signal()

    def __init__(self, doc=None):
        super().__init__()
        self.document = doc or Document()
        self.selection = []
        self.refreshed = 0
        self.overlays = {}

    def add_overlay(self, key, ov, z=0.0):
        self.overlays[key] = ov

    def refresh_overlays(self):
        self.refreshed += 1


def _status(pos=None):
    return SimpleNamespace(raw={}, position=pos, origin=SimpleNamespace(user=None, supported=True),
                           coord_convention=pc.COORD_CONVENTION)


@pytest.fixture(autouse=True)
def _clean_state():
    old = so.set_active_table(None)
    pz._PLAN_CACHE.clear()
    yield
    so.set_active_table(old if old.active else None)
    pz._PLAN_CACHE.clear()


def _doc(**layer):
    doc = Document(with_default_layer=False)
    lay = doc.add_layer(Layer("Schnitt", **layer))
    return doc, lay


def _send_refused(doc, **kw) -> bool | None:
    """check_job on the planned G-code; None if the G-code cannot be built
    (kerf pushed outside the work area – send refuses that before the corner)."""
    try:
        g = planner.optimized_document_gcode(doc)
    except ValueError:
        return None
    return not pc.check_job(g, **kw).ok


# --- margin bound ---------------------------------------------------------------
@pytest.mark.parametrize("attrs, expected", [
    ({}, 0.0),
    ({"kerf_mm": 0.5}, 1.0),
    ({"kerf_mm": -0.4}, 0.8),
    ({"lead_in_mm": 3.0}, 3.0),
    ({"lead_in_mm": 2.0, "lead_out_mm": 4.0}, 4.0),
    ({"lead_in_mm": 3.0, "lead_in_arc": True}, 3.0 * math.sqrt(2)),
    ({"kerf_mm": 0.25, "lead_in_mm": 2.0}, 2.5),
    ({"fill_overscan_mm": 10.0, "fill_mode": "hatch"}, 0.0),   # overscan is laser-off
    ({"tab_count": 4, "overcut_mm": 2.0, "perf_cut_mm": 1.0}, 0.0),  # stay on the contour
])
def test_cut_margin_bound(attrs, expected):
    assert pz.cut_margin_mm(Layer("L", **attrs)) == pytest.approx(expected)


def test_cut_margin_scan_offset_only_for_line_fills():
    table = so.ScanOffsetTable(entries=[(1500.0, 1.2)]).normalized()
    assert pz.cut_margin_mm(Layer("L", fill_mode="hatch"), table) == pytest.approx(0.6)
    assert pz.cut_margin_mm(Layer("L", fill_mode="crosshatch"), table) == pytest.approx(0.6)
    assert pz.cut_margin_mm(Layer("L", fill_mode="offset"), table) == 0.0
    assert pz.cut_margin_mm(Layer("L"), table) == 0.0
    off = so.ScanOffsetTable(enabled=False, entries=[(1500.0, 1.2)])
    assert pz.cut_margin_mm(Layer("L", fill_mode="hatch"), off) == 0.0


@pytest.mark.parametrize("attrs", [
    {"kerf_mm": 1.0}, {"kerf_mm": -1.0, "lead_in_mm": 4.0},
    {"lead_in_mm": 5.0, "lead_in_arc": True, "lead_out_mm": 3.0},
    {"lead_in_mm": 6.0, "kerf_mm": 0.5, "tab_count": 2},
])
def test_margin_box_contains_planned_extent(attrs):
    """The cheap bound really contains the planned powered extent (shapes of all kinds)."""
    doc, lay = _doc(**attrs)
    doc.add_shape(Shape("rect", Geometry(100, 100, 20, 12), lay.id))
    doc.add_shape(Shape("ellipse", Geometry(150, 120, 15, 9, rot=30.0), lay.id))
    doc.add_shape(Shape("rect", Geometry(200, 40, 30, 30, rot=17.0), lay.id))
    hole = doc.add_shape(Shape("rect", Geometry(205, 50, 10, 10), lay.id))
    assert hole is not None
    items = [(s, lay) for s in doc.shapes]
    grown = pz.margin_box(items)
    exact = pz.planned_powered_box(doc)
    plain = pz.design_box(s for s, _l in items)
    assert exact is not None and grown is not None
    eps = 1e-6
    assert grown.xmin <= exact.xmin + eps and grown.ymin <= exact.ymin + eps
    assert grown.xmax >= exact.xmax - eps and grown.ymax >= exact.ymax - eps
    if attrs.get("kerf_mm", 0) > 0:
        assert pz.union_box(plain, exact) != plain     # really burns outside the boxes


def test_planned_box_equals_send_powered_bounds():
    doc, lay = _doc(kerf_mm=0.3, lead_in_mm=4.0, lead_out_mm=2.0, fill_mode="hatch",
                    fill_overscan_mm=5.0)
    doc.add_shape(Shape("rect", Geometry(50, 50, 20, 10), lay.id))
    doc.add_shape(Shape("ellipse", Geometry(90, 70, 12, 12), lay.id))
    table = so.ScanOffsetTable(entries=[(1500.0, 0.8)]).normalized()
    so.set_active_table(table)
    sent = pc.powered_bounds(planner.optimized_document_gcode(doc))
    assert pz.planned_powered_box(doc, table) == sent


def test_planned_box_is_cached(monkeypatch):
    doc, lay = _doc(lead_in_mm=3.0)
    doc.add_shape(Shape("rect", Geometry(50, 50, 20, 10), lay.id))
    calls = []
    real = planner.optimize_layers
    monkeypatch.setattr(planner, "optimize_layers", lambda *a, **k: calls.append(1) or real(*a, **k))
    a = pz.planned_powered_box(doc)
    b = pz.planned_powered_box(doc)
    assert a == b and len(calls) == 1
    doc.set_geometry(doc.shapes[0].id, Geometry(60, 50, 20, 10))
    c = pz.planned_powered_box(doc)
    assert len(calls) == 2 and c.xmin != a.xmin
    assert pz.planned_powered_box(Document(with_default_layer=False)) is None


def test_union_box():
    a, b = pc.Box(0, 0, 1, 1), pc.Box(-1, 0.5, 0.5, 3)
    assert pz.union_box(a, b) == pc.Box(-1, 0, 1, 3)
    assert pz.union_box(a, None) == a and pz.union_box(None, b) == b
    assert pz.union_box(None, None) is None


# --- live warning == send-time check -------------------------------------------------
@pytest.mark.parametrize("attrs", [
    {"lead_in_mm": 5.0},
    {"lead_in_mm": 4.0, "lead_in_arc": True, "lead_out_mm": 4.0},
    {"kerf_mm": 1.5},
])
def test_live_box_with_cut_options_matches_send_check(qapp, attrs):
    """A rect swept along the park corner: the live verdict equals check_job on
    the planned G-code everywhere – including positions where only the lead /
    kerf reaches in (the old object-box check said "frei" there)."""
    doc, lay = _doc(**attrs)
    ed = FakeEditor(doc)
    s = doc.add_shape(Shape("rect", Geometry(200, 40, 10, 10), lay.id))
    msgs = []
    sync = pz.install_park_zone(ed, FakePanel(), report=msgs.append)
    only_cut = 0
    for x in (290.0, 296.0, 299.0, 302.0, 306.0, 330.0):
        for y in (0.5, 4.0, 6.0, 8.0, 12.0, 20.0):
            doc.set_geometry(s.id, Geometry(x, y, 10, 10))
            ed.documentChanged.emit()
            refused = _send_refused(doc)
            if refused is None:
                continue
            assert sync.overlay.refused == refused, (x, y)
            plain = pz.design_hits_zone(pz.design_box([s]), pc.PARK_CORNER_MM)
            if refused and not plain:
                only_cut += 1
                assert sync.overlay.by_cut
                assert "Anfahrt" in sync.overlay.label()
            else:
                assert not sync.overlay.by_cut
    assert only_cut > 0                   # the sweep really hits the new case
    assert any("An-/Abfahrt" in m and "Park-Ecke" in m for m in msgs)


def test_live_box_lead_in_warning_text_and_reset(qapp):
    doc, lay = _doc(lead_in_mm=8.0)
    ed = FakeEditor(doc)
    s = doc.add_shape(Shape("rect", Geometry(200, 60, 10, 10), lay.id))
    msgs = []
    sync = pz.install_park_zone(ed, FakePanel(), report=msgs.append)
    assert not sync.overlay.refused and msgs == []
    # find a spot where only the lead reaches into the corner
    spot = None
    for y in (5.5, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0):
        doc.set_geometry(s.id, Geometry(320, y, 10, 10))
        if _send_refused(doc):
            spot = y
    assert spot is not None
    doc.set_geometry(s.id, Geometry(320, spot, 10, 10))
    ed.documentChanged.emit()
    assert sync.overlay.refused and sync.overlay.by_cut
    assert sync.overlay.hits == (s.id,)              # its grown box reaches in
    assert msgs[-1].startswith("Achtung: An-/Abfahrt") and "X0–78 / Y0–35" in msgs[-1]
    doc.set_geometry(s.id, Geometry(200, 60, 10, 10))
    ed.documentChanged.emit()
    assert not sync.overlay.refused and not sync.overlay.by_cut
    assert msgs[-1] == "Park-Ecke wieder frei."


def test_no_planning_far_from_corner_or_without_cut_options(qapp, monkeypatch):
    calls = []
    real = pz.planned_powered_box
    monkeypatch.setattr(pz, "planned_powered_box", lambda *a, **k: calls.append(1) or real(*a, **k))
    doc, lay = _doc(lead_in_mm=5.0)
    ed = FakeEditor(doc)
    s = doc.add_shape(Shape("rect", Geometry(100, 100, 10, 10), lay.id))
    mp = FakePanel()
    sync = pz.install_park_zone(ed, mp)
    for x in range(100, 280, 20):                     # far away: the bound decides
        doc.set_geometry(s.id, Geometry(float(x), 100, 10, 10))
        ed.documentChanged.emit()
    doc.set_geometry(s.id, Geometry(330, 1, 10, 10))   # box itself in the corner
    ed.documentChanged.emit()
    assert sync.overlay.refused and not sync.overlay.by_cut
    assert calls == []
    # plain layer next to the corner: no cut options, no planning
    doc2, lay2 = _doc()
    ed2 = FakeEditor(doc2)
    doc2.add_shape(Shape("rect", Geometry(320, 6, 10, 10), lay2.id))
    pz.install_park_zone(ed2, FakePanel())
    assert calls == []
    # ambiguous spot: planned once, status ticks reuse the cached plan
    doc.set_geometry(s.id, Geometry(320, 7, 10, 10))
    ed.documentChanged.emit()
    n = len(calls)
    assert n == 1
    counted = []
    real_opt = planner.optimize_layers
    monkeypatch.setattr(planner, "optimize_layers",
                        lambda *a, **k: counted.append(1) or real_opt(*a, **k))
    for _ in range(5):
        mp.status_changed.emit(None)
    assert counted == []


def test_fill_overscan_never_refused(qapp):
    """Overscan runs with the laser off: neither the Pi nor the live check count it."""
    doc, lay = _doc(fill_mode="hatch", fill_overscan_mm=15.0, hatch_outline=False)
    ed = FakeEditor(doc)
    s = doc.add_shape(Shape("rect", Geometry(300, 6, 10, 10), lay.id))
    sync = pz.install_park_zone(ed, FakePanel())
    g = planner.optimized_document_gcode(doc)
    assert "S0" in g
    assert pc.check_job(g).ok and not sync.overlay.refused
    doc.set_geometry(s.id, Geometry(330, 6, 10, 10))
    ed.documentChanged.emit()
    assert pc.check_job(planner.optimized_document_gcode(doc)).ok and not sync.overlay.refused


def test_scan_offset_reaching_in_matches_send_check(qapp):
    so.set_active_table(so.ScanOffsetTable(entries=[(1500.0, 2.0)]))
    doc, lay = _doc(fill_mode="hatch", hatch_outline=False, hatch_angle=90.0)
    ed = FakeEditor(doc)
    s = doc.add_shape(Shape("rect", Geometry(200, 60, 10, 10), lay.id))
    sync = pz.install_park_zone(ed, FakePanel())
    for y in (4.2, 4.6, 5.0, 5.4, 5.8, 6.5):
        doc.set_geometry(s.id, Geometry(320, y, 10, 10))
        ed.documentChanged.emit()
        assert sync.overlay.refused == _send_refused(doc), y


def test_selection_only_plans_only_the_selection(qapp):
    doc, lay = _doc(lead_in_mm=8.0)
    ed = FakeEditor(doc)
    near = doc.add_shape(Shape("rect", Geometry(320, 5.5, 10, 10), lay.id))
    far = doc.add_shape(Shape("rect", Geometry(100, 100, 10, 10), lay.id))
    only = [True]
    ed.selection = [far.id]
    sync = pz.install_park_zone(ed, FakePanel(), selection_only=lambda: only[0])
    assert not sync.overlay.refused
    from lumacut_job.selection import selection_document
    assert not _send_refused(selection_document(doc, [far.id]))
    ed.selection = [near.id]
    ed.selectionChanged.emit()
    assert _send_refused(selection_document(doc, [near.id]))   # only its lead reaches in
    assert sync.overlay.refused and sync.overlay.by_cut
    only[0] = False                                             # whole design: same verdict
    ed.selectionChanged.emit()
    assert sync.overlay.refused == _send_refused(doc)


@pytest.mark.parametrize("anchor", ["bl", "center"])
def test_placed_job_with_lead_ins_matches_send_check(qapp, anchor):
    doc, lay = _doc(lead_in_mm=5.0, lead_in_arc=True)
    ed = FakeEditor(doc)
    doc.add_shape(Shape("rect", Geometry(100, 100, 20, 20), lay.id))
    target = [(60.0, 40.0)]
    mp = FakePanel(_status(pos=target[0]), "current", anchor)
    sync = pz.install_park_zone(ed, mp)
    seen = set()
    for tx in (70.0, 84.0, 86.0, 88.0, 90.0, 96.0, 98.0, 100.0, 104.0, 120.0):
        for ty in (30.0, 34.0, 38.0, 44.0, 60.0):
            mp._status = _status(pos=(tx, ty))
            mp.status_changed.emit(mp._status)
            refused = _send_refused(doc, origin="current", anchor=anchor, target=(tx, ty))
            assert sync.overlay.refused == refused, (tx, ty)
            seen.add((refused, sync.overlay.by_cut))
    assert (True, True) in seen and (False, False) in seen


def test_planning_error_falls_back_to_object_boxes(qapp, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(pz, "planned_powered_box", boom)
    doc, lay = _doc(lead_in_mm=8.0)
    ed = FakeEditor(doc)
    doc.add_shape(Shape("rect", Geometry(320, 8, 10, 10), lay.id))
    sync = pz.install_park_zone(ed, FakePanel())
    assert not sync.overlay.refused                  # the send check still decides
