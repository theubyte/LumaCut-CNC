"""Verschachteln mit Schnittzugaben („Kerf und An-/Abfahrt einrechnen“): der Abstand
gilt zwischen den echten Schnittlinien (Kerf-Versatz der Ebene nach außen), rund um
Teile mit An-/Abfahrt bleibt deren Länge frei – keine Anfahrt muss verlegt, gekürzt
oder weggelassen werden. Ohne Kerf / Anfahrt auf den Ebenen unverändert; Löcher und
Gravuren im Teil zählen nicht; ausgesparte Objekte mit Anfahrt; Hüllbox; G-Code
(Pi-Wächter); Ablesewerte, Dialog und Editor."""

from __future__ import annotations

import pytest
from _pi_guard import pi_check
from shapely.geometry import LineString

from lumacut_canvas import nesting
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import job_layers
from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect
from lumacut_job.cutpath import KIND_LEAD_IN, KIND_LEAD_OUT
from lumacut_job.planner import PlanReport, optimize_layers, optimized_document_gcode

EPS = 1e-6


@pytest.fixture
def doc(qapp):
    return Document()


def add(doc, *shapes):
    return [doc.add_shape(s).id for s in shapes]


def rects(doc, n, w, h, layer_id=None, x=10.0, y=10.0):
    lid = layer_id or doc.active_layer_id
    return add(doc, *[Shape("rect", Geometry(x, y, w, h), lid) for _ in range(n)])


def apply(doc, res):
    for i, g in res.moves.items():
        doc.set_geometry(i, g)


def fps(doc, ids):
    return [nesting.shape_footprint(doc.shape(i)) for i in ids]


def gaps(doc, a_ids, b_ids=None):
    fa = fps(doc, a_ids)
    if b_ids is None:
        return [fa[i].distance(fa[j]) for i in range(len(fa)) for j in range(i + 1, len(fa))]
    fb = fps(doc, b_ids)
    return [x.distance(y) for x in fa for y in fb]


def edge_gap(doc, ids, r: Rect):
    out = []
    for f in fps(doc, ids):
        x0, y0, x1, y1 = f.bounds
        out.append(min(x0 - r.x, y0 - r.y, r.right - x1, r.bottom - y1))
    return min(out)


WORK = Rect(0, 0, WORK_WIDTH_MM, WORK_HEIGHT_MM)


# --- Zugabe je Ebene / Teil ---------------------------------------------------------------

def test_layer_allowance_takes_outward_kerf_and_the_longer_lead():
    assert nesting.layer_allowance(Layer("a")) == nesting.Allowance()
    assert not nesting.Allowance().active
    a = nesting.layer_allowance(Layer("a", kerf_mm=0.15, lead_in_mm=2.0, lead_out_mm=3.5))
    assert a == nesting.Allowance(0.15, 3.5) and a.active
    assert nesting.layer_allowance(Layer("a", kerf_mm=-0.2)) == nesting.Allowance()   # Teile kleiner
    assert nesting.layer_allowance(Layer("a", lead_out_mm=1.0)).lead == 1.0
    assert nesting.layer_allowance(None) == nesting.Allowance()
    assert nesting.Allowance(0.1, 2.0).merged(nesting.Allowance(0.3, 1.0)) == nesting.Allowance(0.3, 2.0)
    assert nesting.Allowance(0.1, 2.0).text() == "Kerf +0,10 mm, An-/Abfahrt 2,0 mm"
    assert nesting.Allowance(0.0, 2.0).text() == "An-/Abfahrt 2,0 mm"
    assert nesting.Allowance(0.25, 0.0).text() == "Kerf +0,25 mm"


def test_unit_allowance_counts_only_outer_closed_objects(doc):
    plain = doc.active_layer_id
    lead = doc.add_layer(Layer("Anfahrt", lead_in_mm=3.0, kerf_mm=0.2)).id
    plate = Shape("rect", Geometry(100, 100, 60, 40), plain)
    hole = Shape("ellipse", Geometry(120, 110, 10, 10), lead)          # Loch mit Anfahrt
    assert nesting.unit_allowance(doc, [plate, hole]) == nesting.Allowance()
    assert nesting.unit_allowance(doc, [hole]) == nesting.Allowance(0.2, 3.0)
    outer = Shape("rect", Geometry(100, 100, 60, 40), lead)
    assert nesting.unit_allowance(doc, [outer, Shape("ellipse", Geometry(120, 110, 10, 10), plain)]) \
        == nesting.Allowance(0.2, 3.0)
    line = Shape("line", Geometry(0, 0, 30, 10), lead)                  # offen: kein Versatz
    path = Shape.from_points("path", [(0, 0), (10, 10), (20, 0)], lead)
    assert nesting.unit_allowance(doc, [line, path]) == nesting.Allowance()
    side = Shape("rect", Geometry(300, 100, 10, 10), lead)              # daneben, nicht drin
    assert nesting.unit_allowance(doc, [plate, side]) == nesting.Allowance(0.2, 3.0)


# --- Kerf ---------------------------------------------------------------------------------

def test_kerf_is_added_so_the_offset_cut_lines_keep_the_spacing(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.4)
    ids = rects(doc, 12, 40, 25)
    res = nesting.nest(doc, ids, spacing=1.0, margin=2.0, rotation="none")
    assert res.placed == 12 and res.allowance == nesting.Allowance(0.4, 0.0)
    assert res.allowance_parts == 12
    apply(doc, res)
    assert min(gaps(doc, ids)) >= 1.0 + 2 * 0.4 - EPS
    assert edge_gap(doc, ids, WORK) >= 2.0 + 0.4 - EPS          # Versatz bleibt im Randabstand
    off = nesting.nest(doc, ids, spacing=1.0, margin=2.0, rotation="none", cut_allowance=False)
    apply(doc, off)
    assert min(gaps(doc, ids)) < 1.0 + 2 * 0.4 - 0.1             # ohne Zugabe enger
    assert off.allowance_parts == 0 and "Schnittzugabe" not in off.readout()


def test_kerf_spacing_holds_for_the_planned_offset_contours(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.5)
    ids = rects(doc, 8, 30, 30)
    apply(doc, nesting.nest(doc, ids, spacing=0.5, rotation="none"))
    (lay,) = optimize_layers(job_layers(doc))
    rings = [LineString(p) for p in lay.polylines]
    assert len(rings) == 8
    d = min(rings[i].distance(rings[j]) for i in range(8) for j in range(i + 1, 8))
    assert d >= 0.5 - 1e-3                                       # echte Schnittlinien


# --- An-/Abfahrt ----------------------------------------------------------------------------

def _leads(lay):
    return [p for p, k in zip(lay.polylines, lay.poly_kinds) if k in (KIND_LEAD_IN, KIND_LEAD_OUT)]


def test_lead_room_keeps_every_lead_full_length_and_in_place(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, lead_in_mm=3.0, lead_out_mm=2.0)
    ids = rects(doc, 9, 20, 20)
    res = nesting.nest(doc, ids, spacing=0.5, rotation="none")
    assert res.placed == 9 and res.allowance == nesting.Allowance(0.0, 3.0)
    apply(doc, res)
    assert min(gaps(doc, ids)) >= 0.5 + 3.0 - EPS
    report = PlanReport()
    (lay,) = optimize_layers(job_layers(doc), report=report)
    assert report.moved_leads == 0 and report.skipped_leads == 0
    leads = _leads(lay)
    assert len(leads) == 18
    assert sum(LineString(p).length for p in leads) == pytest.approx(9 * (3.0 + 2.0), rel=1e-6)
    cuts = [LineString(p) for p, k in zip(lay.polylines, lay.poly_kinds)
            if k not in (KIND_LEAD_IN, KIND_LEAD_OUT)]
    assert len(cuts) == 9
    for p in leads:                       # jede An-/Abfahrt berührt nur ihr eigenes Teil
        assert sum(1 for c in cuts if LineString(p).intersects(c)) == 1


def test_without_allowance_tight_leads_get_moved_or_shortened(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, lead_in_mm=3.0, lead_out_mm=2.0)
    ids = rects(doc, 9, 20, 20)
    apply(doc, nesting.nest(doc, ids, spacing=0.5, rotation="none", cut_allowance=False))
    assert min(gaps(doc, ids)) < 1.0
    report = PlanReport()
    (lay,) = optimize_layers(job_layers(doc), report=report)
    full = sum(LineString(p).length for p in _leads(lay))
    assert report.moved_leads + report.skipped_leads > 0 or full < 9 * 5.0 - 1e-6


def test_lead_rooms_may_overlap_the_sheet_edge_and_each_other(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, lead_in_mm=4.0)
    (mat,) = add(doc, Shape("rect", Geometry(0, 0, 100, 60), doc.add_layer(Layer("Material")).id))
    ids = rects(doc, 4, 44, 25, x=200, y=200)
    res = nesting.nest(doc, ids + [mat], container_id=mat, spacing=1.0, margin=1.0, rotation="none")
    # 2 × 2 Teile: 1 + 44 + 1 + 4 + 44 + 1 = 95 ≤ 100 – Anfahrtsraum nur zwischen den Teilen
    assert res.placed == 4 and not res.unplaced
    apply(doc, res)
    assert edge_gap(doc, ids, doc.shape(mat).bounds()) >= 1.0 - EPS
    assert min(gaps(doc, ids)) >= 1.0 + 4.0 - EPS


def test_mixed_layers_need_the_longer_lead_between_two_parts(doc):
    plain = doc.active_layer_id
    lead = doc.add_layer(Layer("Anfahrt", lead_in_mm=5.0)).id
    a = rects(doc, 4, 25, 25, layer_id=lead)
    b = rects(doc, 8, 25, 25, layer_id=plain)
    res = nesting.nest(doc, a + b, spacing=1.0, rotation="none")
    assert res.placed == 12 and res.allowance_parts == 4
    apply(doc, res)
    assert min(gaps(doc, a)) >= 6.0 - EPS
    assert min(gaps(doc, a, b)) >= 6.0 - EPS
    assert min(gaps(doc, b)) < 2.0                                # ohne Anfahrt dicht wie bisher


def test_other_objects_keep_their_own_lead_room(doc):
    lid = doc.active_layer_id
    lead = doc.add_layer(Layer("Anfahrt", lead_in_mm=6.0)).id
    (obst,) = add(doc, Shape("rect", Geometry(WORK_WIDTH_MM - 80, 0, 80, 60), lead))
    ids = rects(doc, 6, 40, 30, layer_id=lid, x=10, y=250)
    res = nesting.nest(doc, ids, spacing=1.0)
    assert res.obstacles == 1 and res.placed == 6 and res.allowance_parts == 0
    apply(doc, res)
    ob = nesting.shape_footprint(doc.shape(obst))
    assert min(ob.distance(f) for f in fps(doc, ids)) >= 1.0 + 6.0 - EPS
    off = nesting.nest(doc, ids, spacing=1.0, cut_allowance=False)
    apply(doc, off)
    assert min(ob.distance(f) for f in fps(doc, ids)) < 1.0 + 6.0 - 0.5


def test_holes_with_leads_inside_a_plate_do_not_widen_the_spacing(doc):
    plain = doc.active_layer_id
    lead = doc.add_layer(Layer("Löcher", lead_in_mm=4.0)).id
    ids = []
    for _ in range(6):
        plate, hole = add(doc, Shape("rect", Geometry(10, 10, 40, 30), plain),
                          Shape("ellipse", Geometry(20, 15, 10, 10), lead))
        ids += [plate, hole]
    res = nesting.nest(doc, ids, spacing=1.0, rotation="none")
    assert res.total == 6 and res.allowance_parts == 0
    apply(doc, res)
    plates = ids[::2]
    assert min(gaps(doc, plates)) < 2.0


def test_box_form_with_kerf_and_lead(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.3, lead_in_mm=2.0)
    ids = add(doc, *[Shape("ellipse", Geometry(10, 10, 30, 20), lid) for _ in range(8)])
    res = nesting.nest(doc, ids, spacing=1.0, form="box", rotation="none")
    assert res.placed == 8
    apply(doc, res)
    boxes = [doc.shape(i).bounds() for i in ids]
    for i in range(8):
        for j in range(i + 1, 8):
            a, b = boxes[i], boxes[j]
            dx = max(b.x - a.right, a.x - b.right)
            dy = max(b.y - a.bottom, a.y - b.bottom)
            assert max(dx, dy) >= 1.0 + 0.6 + 2.0 - 2 * res.res


def test_no_kerf_or_lead_gives_the_same_layout_as_before(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, tab_count=2, overcut_mm=1.0)           # andere Schnittoptionen zählen nicht
    ids = rects(doc, 7, 33, 21) + add(doc, *[Shape("ellipse", Geometry(5, 5, 18, 26), lid)
                                              for _ in range(5)])
    for rot in ("none", "90", "45"):
        on = nesting.nest(doc, ids, spacing=1.5, rotation=rot)
        off = nesting.nest(doc, ids, spacing=1.5, rotation=rot, cut_allowance=False)
        assert on.moves == off.moves and on.readout() == off.readout()
        assert on.allowance_parts == 0


def test_readout_names_the_allowance(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.1, lead_in_mm=2.0)
    ids = rects(doc, 3, 20, 20)
    res = nesting.nest(doc, ids)
    assert res.readout().endswith(" · Schnittzugabe eingerechnet (Kerf +0,10 mm, An-/Abfahrt "
                                  "2,0 mm, 3 Teil(e))")


def test_gcode_after_nesting_with_allowance_passes_the_pi_guard(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.1, lead_in_mm=2.0, lead_in_arc=True, lead_out_mm=1.0)
    ids = rects(doc, 6, 30, 20) + add(doc, *[Shape("ellipse", Geometry(5, 5, 25, 25), lid)
                                             for _ in range(4)])
    res = nesting.nest(doc, ids, spacing=0.5, rotation="90")
    assert res.placed == 10
    apply(doc, res)
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    pi_check(g)
    assert report.skipped_leads == 0 and report.moved_leads == 0
    again = Document.from_dict(doc.to_dict())
    assert [x.geom for x in again.shapes] == [x.geom for x in doc.shapes]


# --- Dialog / Editor ----------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def test_dialog_switch_default_values_tooltip_and_readout(qapp):
    from lumacut_canvas.nesting_ui import NestDialog, default_values
    assert default_values()["cut_allowance"] is True
    dlg = NestDialog(3, None)
    assert dlg.allow.isChecked() and dlg.values()["cut_allowance"] is True
    assert dlg.allow.text() == "Kerf und An-/Abfahrt einrechnen"
    assert "echten Schnittlinien" in dlg.allow.toolTip()
    assert "Kerf und An-/Abfahrt einrechnen" in dlg.spacing.toolTip()
    assert dlg.readout.text() == "3 Teil(e) ausgewählt"
    dlg.allow.setChecked(False)
    assert dlg.values()["cut_allowance"] is False
    dlg.deleteLater()
    dlg = NestDialog(2, None, values={"cut_allowance": False},
                     allowance=nesting.Allowance(0.1, 2.5))
    assert not dlg.allow.isChecked()
    assert dlg.readout.text() == ("2 Teil(e) ausgewählt · Schnittzugabe der Ebenen: Kerf +0,10 mm, "
                                  "An-/Abfahrt 2,5 mm")
    dlg.deleteLater()


def test_editor_nest_uses_the_switch_and_reports_it(ed):
    doc = ed.document
    lid = doc.active_layer_id
    doc.update_layer(lid, lead_in_mm=3.0)
    parts = [Shape("rect", Geometry(10, 10, 20, 20), lid) for _ in range(6)]
    ed.undo_stack.push(AddShapesCommand(doc, list(parts)))
    ids = [p.id for p in parts]
    seen = []
    nester = ed.arranger.nester
    nester.ask = lambda n, cont: seen.append(nester.allowance) or {"spacing": 0.5, "rotation": "none"}
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection(ids)
    ed.actions_by_name["nest"].trigger()
    assert seen == [nesting.Allowance(0.0, 3.0)]
    assert ed.undo_stack.undoText() == "Verschachteln"
    assert "Schnittzugabe eingerechnet (An-/Abfahrt 3,0 mm, 6 Teil(e))" in msgs[-1]
    assert min(gaps(doc, ids)) >= 3.5 - EPS
    assert nester.last["cut_allowance"] is True
    ed.undo_stack.undo()
    nester.ask = lambda n, cont: {"spacing": 0.5, "rotation": "none", "cut_allowance": False}
    ed.set_selection(ids)
    ed.actions_by_name["nest"].trigger()
    assert "Schnittzugabe" not in msgs[-1]
    assert min(gaps(doc, ids)) < 3.0
    assert nester.last["cut_allowance"] is False


def test_real_dialog_shows_the_allowance_of_the_selection(ed):
    doc = ed.document
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.2)
    part = Shape("rect", Geometry(10, 10, 30, 20), lid)
    ed.undo_stack.push(AddShapesCommand(doc, [part]))
    from lumacut_canvas.nesting_ui import NestDialog
    shown = []
    orig = NestDialog.exec
    NestDialog.exec = lambda self: shown.append(self.readout.text()) or 0
    try:
        ed.set_selection([part.id])
        ed.actions_by_name["nest"].trigger()
    finally:
        NestDialog.exec = orig
    assert shown == ["1 Teil(e) ausgewählt · Schnittzugabe der Ebenen: Kerf +0,20 mm"]
