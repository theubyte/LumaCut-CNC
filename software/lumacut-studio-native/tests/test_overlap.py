"""Überlappende Linien entfernen (Engine, Planer, G-Code, Dialog) und der Hinweis
auf offene Pfade in Füll-Ebenen beim Senden."""

from __future__ import annotations

import math
import re

import pytest
from _pi_guard import pi_check

from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.export import job_layers
from lumacut_canvas.model import CUT_LAYER_DEFAULTS, CUT_LAYER_FIELDS, Document, Geometry, Layer, Shape
from lumacut_job.cutpath import KIND_PERF, CutOptions
from lumacut_job.estimate import estimate_gcode
from lumacut_job.overlap import covered_interval, remove_overlaps
from lumacut_job.planner import (PlanReport, open_paths_on_fill_layers, optimize_layers,
                                 optimized_document_gcode)


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def length(p):
    return sum(math.dist(a, b) for a, b in zip(p, p[1:]))


def total(polys):
    return sum(length(p) for p in polys)


def burned_mm(gcode: str) -> float:
    """Länge aller G1-Fahrten mit Leistung (S > 0)."""
    pos, out = None, 0.0
    for line in gcode.splitlines():
        m = re.match(r"G([01]) X(-?[\d.]+) Y(-?[\d.]+)(?:.* S(\d+))?", line)
        if not m:
            continue
        p = (float(m.group(2)), float(m.group(3)))
        if m.group(1) == "1" and pos is not None and int(m.group(4) or 0) > 0:
            out += math.dist(pos, p)
        pos = p
    return out


# --- Engine --------------------------------------------------------------------

def test_shared_edge_of_two_adjacent_squares_is_cut_once():
    a, b = square(0, 0, 10), square(10, 0, 10)
    res = remove_overlaps([a, b], 0.05)
    assert res.polylines[0] is a                      # erstes Teil unverändert
    assert res.changed == 1 and res.removed_mm == pytest.approx(10)
    (rest,) = res.polylines[1:]
    assert rest[0] == pytest.approx((10, 0)) and rest[-1] == pytest.approx((10, 10))
    assert length(rest) == pytest.approx(30)          # drei Seiten, offen
    assert total(res.polylines) == pytest.approx(70)


def test_partial_overlap_removes_only_the_shared_part():
    a, b = square(0, 0, 10), square(10, 3, 10)        # gemeinsame Kante nur y 3..10
    res = remove_overlaps([a, b], 0.05)
    assert res.removed_mm == pytest.approx(7)
    assert total(res.polylines) == pytest.approx(80 - 7)
    # Die Strecke (10,3)-(10,10) ist weg, (10,10)-(10,13) bleibt.
    pts = [p for poly in res.polylines[1:] for p in poly]
    assert any(p == pytest.approx((10, 13)) for p in pts)
    assert not any(p == pytest.approx((10, 3)) and q == pytest.approx((10, 10))
                   for poly in res.polylines[1:] for p, q in zip(poly, poly[1:]))


def test_collinear_line_inside_another_and_reversed_direction():
    res = remove_overlaps([[(0, 0), (10, 0)], [(8, 0), (2, 0)]], 0.05)
    assert res.polylines == [[(0, 0), (10, 0)]] and res.removed_mm == pytest.approx(6)
    # Längere zweite Linie: nur der Überstand bleibt
    res = remove_overlaps([[(0, 0), (10, 0)], [(5, 0), (15, 0)]], 0.05)
    assert res.polylines[1] == [pytest.approx((10, 0)), pytest.approx((15, 0))]


def test_tolerance_decides_what_counts_as_overlap():
    near = [[(0, 0), (10, 0)], [(2, 0.03), (8, 0.03)]]
    assert remove_overlaps(near, 0.05).removed_mm == pytest.approx(6)
    assert remove_overlaps(near, 0.02).removed_mm == 0
    far = [[(0, 0), (10, 0)], [(2, 0.3), (8, 0.3)]]
    assert remove_overlaps(far, 0.05).polylines == far
    assert remove_overlaps(far, 0.5).removed_mm == pytest.approx(6)


def test_crossings_touching_ends_and_corners_stay():
    cross = [[(0, 0), (10, 0)], [(5, -5), (5, 5)]]
    shallow = [[(0, 0), (10, 0)], [(0, -1), (10, 1)]]        # flache Kreuzung (≈ 11,3°)
    chain = [[(0, 0), (10, 0)], [(10, 0), (20, 0)]]          # stößt nur an
    corner = [square(0, 0, 10), square(10, 10, 10)]          # Ecke an Ecke
    for polys in (cross, chain, corner):
        res = remove_overlaps(polys, 0.05)
        assert res.removed_mm == 0 and res.polylines == polys
        assert all(x is y for x, y in zip(res.polylines, polys))
    # Flache Kreuzung: höchstens ein kurzer Abschnitt um den Schnittpunkt
    assert remove_overlaps(shallow, 0.05).removed_mm < 0.6


def test_duplicate_closed_contour_and_its_own_retrace():
    a = square(0, 0, 10)
    res = remove_overlaps([a, list(reversed(a))], 0.05)
    assert res.polylines == [a] and res.removed_mm == pytest.approx(40)
    # Ein Pfad, der auf sich selbst zurückläuft, fährt die Strecke nur einmal
    spike = [(0, 0), (10, 0), (4, 0)]
    res = remove_overlaps([spike], 0.05)
    assert total(res.polylines) == pytest.approx(10)


def test_flattened_circles_with_other_start_points():
    def circle(cx, cy, r, n, phase):
        pts = [(cx + r * math.cos(phase + 2 * math.pi * k / n),
                cy + r * math.sin(phase + 2 * math.pi * k / n)) for k in range(n)]
        return pts + pts[:1]
    a = circle(50, 50, 10, 360, 0.0)
    b = circle(50, 50, 10, 360, math.radians(0.5))      # andere Zerlegung, gleicher Kreis
    res = remove_overlaps([a, b], 0.05)
    assert res.removed_mm > 0.95 * length(b)
    assert total(res.polylines) == pytest.approx(length(a), rel=0.05)


def test_closed_ring_rest_is_one_open_chain_and_zero_tolerance_is_off():
    a, b = square(0, 0, 10), square(10, 0, 10)
    # b beginnt mitten auf der gemeinsamen Kante: die beiden Reste werden verbunden
    b = [(10, 5), (10, 0), (20, 0), (20, 10), (10, 10), (10, 5)]
    res = remove_overlaps([a, b], 0.05)
    assert len(res.polylines) == 2 and length(res.polylines[1]) == pytest.approx(30)
    off = remove_overlaps([a, b], 0.0)
    assert off.polylines == [a, b] and off.removed_mm == 0


def test_covered_interval_needs_parallel_and_close():
    assert covered_interval((0, 0), (10, 0), (2, 0), (6, 0), 0.05) == pytest.approx((2, 6))
    assert covered_interval((0, 0), (10, 0), (2, 0), (2, 6), 0.05) is None
    assert covered_interval((0, 0), (10, 0), (2, 1), (6, 1), 0.05) is None
    # Nur Anstoßen am Endpunkt: kein Abschnitt
    assert covered_interval((0, 0), (10, 0), (10, 0), (20, 0), 0.05) is None
    # Kurzes Stück (< 2 × Toleranz) wird in remove_overlaps nicht entfernt
    assert remove_overlaps([[(2, 0), (2.05, 0)], [(0, 0), (10, 0)]], 0.05).removed_mm == 0


def test_many_segments_are_fast():
    import time
    polys = [square(x * 10.0, y * 10.0, 10.0) for x in range(30) for y in range(30)]
    t = time.perf_counter()
    res = remove_overlaps(polys, 0.05)
    assert time.perf_counter() - t < 5.0
    # 30 × 30-Raster: 2 × 30 × 31 Kanten à 10 mm statt 4 × 900
    assert total(res.polylines) == pytest.approx(2 * 30 * 31 * 10, rel=1e-6)


# --- Modell / Planer / G-Code ----------------------------------------------------

def two_parts(overlap=0.05, **layer_attrs):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, overlap_tol_mm=overlap, **layer_attrs)
    doc.add_shape(Shape("rect", Geometry(40, 40, 30, 20), lid))
    doc.add_shape(Shape("rect", Geometry(70, 40, 30, 20), lid))
    return doc


def test_layer_field_saves_only_when_set_and_is_clamped():
    assert "overlap_tol_mm" in CUT_LAYER_FIELDS and CUT_LAYER_DEFAULTS["overlap_tol_mm"] == 0.0
    assert "overlap_tol_mm" not in Layer(name="x").to_dict()
    l = Layer(name="x", overlap_tol_mm=0.05)
    assert Layer.from_dict(l.to_dict()).overlap_tol_mm == 0.05
    assert Layer(name="x", overlap_tol_mm=5.0).normalized().overlap_tol_mm == 1.0
    assert Layer(name="x", overlap_tol_mm=-1).normalized().overlap_tol_mm == 0.0
    (jl,) = job_layers(two_parts())
    assert jl.overlap_tol_mm == 0.05 and CutOptions.of(jl).removes_overlaps
    assert not CutOptions.of(jl).active          # keine weitere Schnittoption nötig


def test_gcode_cuts_the_shared_edge_once_and_passes_the_pi_guard():
    on, off = two_parts(), two_parts(overlap=0.0)
    report = PlanReport()
    g_on = optimized_document_gcode(on, scan_offsets=None, report=report)
    g_off = optimized_document_gcode(off, scan_offsets=None)
    assert burned_mm(g_off) == pytest.approx(200, abs=0.01)
    assert burned_mm(g_on) == pytest.approx(180, abs=0.01)
    assert report.overlap_removed and sum(report.overlap_removed.values()) == pytest.approx(20)
    assert "Überlappende Linien entfernt: 20,0 mm" in report.message()
    assert g_on.count("M3 I") == 1 and g_on.rstrip().endswith("M400")
    pi_check(g_on)
    assert estimate_gcode(g_on).cut_length_mm == pytest.approx(180, abs=0.01)
    assert estimate_gcode(g_on).cut_time_s < estimate_gcode(g_off).cut_time_s


def test_off_by_default_output_is_unchanged():
    doc = two_parts(overlap=0.0)
    report = PlanReport()
    layers = optimize_layers(job_layers(doc), report=report)
    assert sum(len(l.polylines) for l in layers) == 2 and report.message() == ""


def test_inside_first_kept_and_holes_untouched():
    doc = two_parts()
    lid = doc.active_layer_id
    hole = Shape("ellipse", Geometry(80, 45, 10, 10), lid)
    doc.add_shape(hole)
    (layer,) = optimize_layers(job_layers(doc))
    closed = [p for p in layer.polylines if math.dist(p[0], p[-1]) < 0.01]
    # Loch (geschlossen, unverändert) vor dem offenen Rest seines Teils
    hole_i = next(i for i, p in enumerate(layer.polylines)
                  if p in closed and length(p) < 40)
    open_i = next(i for i, p in enumerate(layer.polylines) if p not in closed)
    assert hole_i < open_i
    assert total(layer.polylines) == pytest.approx(180 + math.pi * 10, rel=1e-3)


def test_kerf_tabs_leads_skip_overlap_removal_and_report_it():
    for attrs in ({"kerf_mm": 0.1}, {"tab_count": 2}, {"lead_in_mm": 1.0},
                  {"lead_out_mm": 1.0}, {"overcut_mm": 0.5}):
        doc = two_parts(**attrs)
        report = PlanReport()
        g = optimized_document_gcode(doc, scan_offsets=None, report=report)
        assert report.overlap_skipped == [doc.active_layer.name], attrs
        assert not report.overlap_removed
        assert "Überlappungen nicht entfernt" in report.message()
        assert burned_mm(g) > 195          # beide Konturen vollständig (Stege: 4 × 1 mm)
        (jl,) = job_layers(doc)
        assert not CutOptions.of(jl).removes_overlaps


def test_perforation_applies_to_the_remaining_pieces():
    doc = two_parts(perf_cut_mm=2.0, perf_skip_mm=1.0)
    (layer,) = optimize_layers(job_layers(doc))
    assert KIND_PERF in layer.poly_kinds
    burned = total(layer.polylines)
    assert burned == pytest.approx(180 * 2 / 3, rel=0.05)
    pi_check(optimized_document_gcode(doc, scan_offsets=None))


def test_only_the_same_layer_and_never_the_fill():
    doc = Document()
    l1 = doc.active_layer_id
    other = Layer(name="Andere")
    doc.add_layer(other)
    for lid in (l1, other.id):
        doc.update_layer(lid, overlap_tol_mm=0.05)
    doc.add_shape(Shape("rect", Geometry(40, 40, 30, 20), l1))
    doc.add_shape(Shape("rect", Geometry(70, 40, 30, 20), other.id))
    layers = optimize_layers(job_layers(doc))
    assert total([p for l in layers for p in l.polylines]) == pytest.approx(200)
    # Füll-Ebene: Schraffur bleibt Strecke für Strecke gleich, nur die Kontur verliert die Kante
    fill = two_parts(fill_mode="hatch", line_interval_mm=1.0)
    plain = two_parts(overlap=0.0, fill_mode="hatch", line_interval_mm=1.0)
    (a,) = optimize_layers(job_layers(fill))
    (b,) = optimize_layers(job_layers(plain))
    assert a.fills == b.fills
    assert total(a.polylines) == pytest.approx(180) and total(b.polylines) == pytest.approx(200)


# --- Offene Pfade auf Füll-Ebenen -------------------------------------------------

def fill_doc_with_open_paths():
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, fill_mode="hatch")
    doc.add_shape(Shape("rect", Geometry(10, 10, 20, 20), lid))
    for a, b in (((50, 10), (70, 10)), ((70, 10), (70, 30)), ((70, 30), (50, 10))):
        doc.add_shape(Shape.from_points("path", [a, b], lid))
    return doc


def test_open_paths_on_fill_layer_are_reported():
    doc = fill_doc_with_open_paths()
    report = PlanReport()
    assert open_paths_on_fill_layers(doc, report) == {doc.active_layer.name: 3}
    assert report.open_on_fill_joinable == 3
    msg = report.message()
    assert "3 offene Konturen auf Füll-Ebene" in msg and "nicht gefüllt" in msg
    assert "„Pfade verbinden“ (Alt+J)" in msg and "„Pfade schließen“" in msg
    # Über optimized_document_gcode genauso
    report = PlanReport()
    optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert report.open_on_fill == {doc.active_layer.name: 3}


def test_no_warning_without_fill_hidden_layer_or_only_closed_shapes():
    doc = fill_doc_with_open_paths()
    lid = doc.active_layer_id
    doc.update_layer(lid, fill_mode="none")
    assert open_paths_on_fill_layers(doc) == {}
    doc.update_layer(lid, fill_mode="hatch", visible=False)
    assert open_paths_on_fill_layers(doc) == {}
    closed = Document()
    closed.update_layer(closed.active_layer_id, fill_mode="offset")
    closed.add_shape(Shape("ellipse", Geometry(10, 10, 20, 20), closed.active_layer_id))
    report = PlanReport()
    optimized_document_gcode(closed, scan_offsets=None, report=report)
    assert report.open_fill_message() == "" and report.message() == ""


def test_single_open_line_counts_but_is_not_joinable():
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, fill_mode="crosshatch")
    doc.add_shape(Shape("line", Geometry(10, 10, 30, 0), lid))
    report = PlanReport()
    open_paths_on_fill_layers(doc, report)
    assert report.open_on_fill == {doc.active_layer.name: 1}
    assert report.open_on_fill_joinable == 0
    assert "1 offene Kontur auf" in report.message() and "verbindbar" not in report.message()


# --- Dialog / App ------------------------------------------------------------------

@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()
    ed.close()
    ed.deleteLater()
    qapp.processEvents()


def test_dialog_overlap_field_summary_and_hint(editor):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.cut_qt import CutOptionsDialog, apply_cut_options, summary
    layer = editor.document.active_layer
    dlg = CutOptionsDialog(layer)
    assert dlg.overlap.text() == "aus" and dlg.values()["overlap_tol_mm"] == 0.0
    dlg.overlap.setValue(0.05)
    assert dlg.values()["overlap_tol_mm"] == pytest.approx(0.05)
    assert dlg.overlap_hint.isHidden()
    dlg.kerf.setValue(0.1)
    assert not dlg.overlap_hint.isHidden() and "Wirkt nicht" in dlg.overlap_hint.text()
    dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.RestoreDefaults).click()
    assert dlg.values() == CUT_LAYER_DEFAULTS
    n = editor.undo_stack.count()
    assert apply_cut_options(editor, layer.id, dict(CUT_LAYER_DEFAULTS, overlap_tol_mm=0.05))
    assert editor.undo_stack.count() == n + 1
    assert summary(editor.document.layer(layer.id)) == "Überlappungen entfernen (0.05 mm)"
    editor.undo_stack.undo()
    assert editor.document.layer(layer.id).overlap_tol_mm == 0.0


def test_main_window_send_note_and_cut_options(qapp):
    from main import LumaCutStudio
    win = LumaCutStudio()
    try:
        ed = win.canvas
        doc = ed.document
        lid = doc.active_layer.id
        ed.undo_stack.push(AddShapesCommand(doc, [Shape("rect", Geometry(40, 40, 30, 20), lid),
                                                  Shape("rect", Geometry(70, 40, 30, 20), lid)],
                                            "Rechtecke"))
        tools = win.job_tools
        assert tools.cut_options(dict(CUT_LAYER_DEFAULTS, overlap_tol_mm=0.05))
        assert "Überlappungen entfernen" in win.statusBar().currentMessage()
        g, note = tools.job_gcode(ask_inputs=False)
        assert burned_mm(g) == pytest.approx(180, abs=0.01)
        assert "Überlappende Linien entfernt" in note
        # Füll-Ebene mit offenen Strecken: Hinweis beim Senden
        doc.update_layer(lid, fill_mode="hatch")
        ed.undo_stack.push(AddShapesCommand(doc, [Shape.from_points("path", [(120, 40), (140, 60)],
                                                                    lid)], "Linie"))
        job = win._build_canvas_job()
        assert job is not None
        assert "offene Kontur auf Füll-Ebene" in job[2] and "Alt+J" in job[2]
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
