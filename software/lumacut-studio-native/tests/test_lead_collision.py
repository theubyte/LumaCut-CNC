"""An-/Abfahrten dürfen keine anderen Teile anschneiden (Kollisionsprüfung)."""
import math

import pytest
from shapely.geometry import LineString

from _pi_guard import pi_check
from lumacut_canvas.export import JobLayer, job_layers
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_job.cutpath import (KIND_LEAD_IN, KIND_LEAD_OUT, CutOptions, LeadObstacles,
                                 apply_cut_options, start_candidates)
from lumacut_job.planner import PlanReport, optimize_layers, optimized_document_gcode


def square(x, y, s, ccw=True):
    sq = [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]
    return sq if ccw else list(reversed(sq))


def layer(polys, lid="l", name="Schneiden", **opts):
    return JobLayer(lid, name, 80, 600, 1, polys, **opts)


def leads(lay):
    return [p for p, k in zip(lay.polylines, lay.poly_kinds) if k in (KIND_LEAD_IN, KIND_LEAD_OUT)]


def touches_any(lead, contours):
    g = LineString(lead)
    return any(g.intersects(LineString(c)) for c in contours)


@pytest.mark.parametrize("arc", [False, True])
def test_leads_avoid_neighbour_parts(arc):
    # 3×3 dicht gepackte Teile (1 mm Abstand), Anfahrt 4 mm: ohne Prüfung
    # schneiden Anfahrten in die Nachbarn.
    parts = [square(50 + 11 * i, 50 + 11 * j, 10) for i in range(3) for j in range(3)]
    naive = apply_cut_options(parts, CutOptions(lead_in_mm=4.0, lead_in_arc=arc), [0] * 9)
    assert any(len([c for c in parts if LineString(c).intersects(LineString(p))]) > 1
               for p, k in zip(naive.polylines, naive.kinds) if k == KIND_LEAD_IN)
    report = PlanReport()
    (lay,) = optimize_layers([layer(parts, lead_in_mm=4.0, lead_in_arc=arc, lead_out_mm=2.0)],
                             report=report)
    assert len(leads(lay)) == 18  # je Teil An- und Abfahrt
    for lead in leads(lay):
        hit = [c for c in parts if LineString(c).intersects(LineString(lead))]
        assert len(hit) == 1, "Anfahrt berührt ein anderes Teil"
    assert report.skipped_leads == 0  # Mittelteil: kürzer statt weggelassen
    assert report.message() == ""


def test_lead_dropped_and_reported_when_no_room(qapp):
    # Teil steckt mit 0,2 mm Spalt in einem Rahmen auf einer anderen Ebene.
    part = square(100, 100, 20)
    frame = square(99.8, 99.8, 20.4)
    report = PlanReport()
    lays = optimize_layers([layer([frame], "a", "Rahmen"),
                            layer([part], "b", "Teile", lead_in_mm=3.0, lead_in_arc=True)],
                           report=report)
    assert not leads(lays[1])
    assert report.skipped_leads == 1
    assert report.layers_with_skipped == ["Teile"]
    assert "weggelassen" in report.message() and "Teile" in report.message()


def test_duplicate_contour_on_other_layer_does_not_block():
    part = square(100, 100, 20)
    score = list(reversed(square(100, 100, 20)))  # gleiche Form, andere Ebene, umgekehrt
    report = PlanReport()
    lays = optimize_layers([layer([score], "a", "Markieren"),
                            layer([part], "b", "Schneiden", lead_in_mm=3.0)], report=report)
    assert leads(lays[1])
    assert report.skipped_leads == 0


def test_start_moved_along_contour_when_neighbour_blocks_start():
    # Große Platte, rundherum knapp von Nachbarn umgeben – nur rechts Platz.
    part = square(100, 100, 30)
    blockers = [[(95, 131), (135, 131)],  # oben
                [(95, 99), (135, 99)],    # unten
                [(99, 95), (99, 135)]]    # links
    obstacles = LeadObstacles([part] + blockers)
    res = apply_cut_options([part], CutOptions(lead_in_mm=3.0), [0], obstacles)
    assert res.kinds[0] == KIND_LEAD_IN
    lead = res.polylines[0]
    assert res.moved_leads == 1 and res.skipped_leads == 0
    assert not touches_any(lead, blockers)
    assert min(q[0] for q in lead) >= 130 - 1e-6  # rechts herausgeführt


def test_lead_must_not_cross_own_concave_contour():
    # U-Form: eine lange Anfahrt in der Kerbe würde die eigene Kontur kreuzen.
    u = [(100, 100), (140, 100), (140, 140), (125, 140), (125, 105), (115, 105),
         (115, 140), (100, 140), (100, 100)]
    obstacles = LeadObstacles([u])
    res = apply_cut_options([u], CutOptions(lead_in_mm=12.0, lead_in_arc=True), [0], obstacles)
    for p, k in zip(res.polylines, res.kinds):
        if k == KIND_LEAD_IN:
            g = LineString(p)
            free = g.difference(LineString([p[-1], p[-1]]).buffer(1e-3))
            assert not free.intersects(LineString(u))


def test_start_candidates_rotate_and_keep_shape():
    sq = square(0, 0, 10)
    cands = start_candidates(sq)
    assert len(cands) == 4
    for c in cands:
        assert math.dist(c[0], c[-1]) < 1e-9
        assert abs(LineString(c).length - 40) < 1e-6
    circle = [(50 + 10 * math.cos(2 * math.pi * k / 64), 50 + 10 * math.sin(2 * math.pi * k / 64))
              for k in range(64)]
    circle.append(circle[0])
    assert len(start_candidates(circle)) == 8


def test_document_gcode_with_collision_checked_leads_is_pi_safe(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, lead_in_mm=3.0, lead_in_arc=True, lead_out_mm=1.0)
    for i in range(4):
        doc.add_shape(Shape("rect", Geometry(40 + 21 * i, 60, 20, 20), lid))
    report = PlanReport()
    g = optimized_document_gcode(doc, report=report)
    pi_check(g)
    assert report.skipped_leads == 0
    (lay,) = optimize_layers(job_layers(doc))
    assert len(leads(lay)) >= 4
