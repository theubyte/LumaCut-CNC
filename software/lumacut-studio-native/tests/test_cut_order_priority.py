"""Schnittreihenfolge „Nach Priorität“ (wie LightBurn „Order by Priority“).

Model / file (``Shape.priority``, ``CutOrder.order_by == "priority"``), the job
units (:func:`priority_units` – smallest first, images / hidden layers excluded,
groups ignored), :func:`job_layers` per priority, fills („alle zusammen“ /
„Gruppen“ per priority), G-code (``; PRIORITY`` comments, Pi guard, byte-identical
with one priority and by layer), estimate / path preview, images first, the
inside-shape conflict note, dialog / summary / hints, the property-bar field
„Priorität“ (visibility, one undo step, touch mode, save / load) and the
main-window action.
"""

import math
import re

import pytest
from _pi_guard import pi_check

from lumacut_canvas.commands import AddShapesCommand, SetGroupsCommand
from lumacut_canvas.export import JobLayer, job_layers, layer_fill_blocks, priority_units
from lumacut_canvas.gcode import layers_to_gcode
from lumacut_canvas.model import (CUT_ORDER_UNITS, PRIORITY_RANGE, CutOrder, Document,
                                  Geometry, Layer, Shape, read_priority)
from lumacut_canvas.priority_ui import priority_targets
from lumacut_job.optimize_qt import (UNIT_LABELS, OptimizeDialog, apply_cut_order,
                                     group_count_note, order_hint, priority_conflicts,
                                     priority_count_note, summary)
from lumacut_job.planner import optimized_document_gcode

BY_PRIO = CutOrder(order_by="priority")


def tags_doc(prios=(0, 1), x0=40.0, dx=80.0, y=60.0, engrave_fill="hatch"):
    """Name tags side by side (engraved rect + cut outline), tag i with priority prios[i]."""
    doc = Document(with_default_layer=False)
    eng = doc.add_layer(Layer("Gravur", power=30, speed=3000, fill_mode=engrave_fill,
                              hatch_outline=False))
    cut = doc.add_layer(Layer("Schneiden", power=90, speed=400))
    for i, p in enumerate(prios):
        x = x0 + i * dx
        doc.add_shape(Shape("rect", Geometry(x + 10, y + 10, 40, 10), eng.id, priority=p))
        doc.add_shape(Shape("rect", Geometry(x, y, 60, 30), cut.id, priority=p))
    return doc, eng, cut


def layer_seq(layers):
    return [(l.name, l.unit) for l in layers]


def gcode_comments(g):
    return [line for line in g.splitlines()
            if line.startswith(("; PRIORITY", "; GROUP", "; LAYER"))]


def _png(grey=90):
    from lumacut_import.image import grayscale_png
    from PySide6.QtGui import QColor, QImage
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor(grey, grey, grey))
    return grayscale_png(img)


@pytest.fixture
def ed(qapp):
    from lumacut_canvas.editor import CanvasEditor
    e = CanvasEditor()
    e.resize(1280, 720)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()
    e.deleteLater()
    qapp.processEvents()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes, "Objekte"))
    return shapes


# --- Modell / Datei ---------------------------------------------------------------

def test_cut_order_model_and_broken_values():
    assert "priority" in CUT_ORDER_UNITS and CUT_ORDER_UNITS[0] == "layer"
    assert BY_PRIO.by_priority and not BY_PRIO.by_group and not BY_PRIO.is_default
    assert not CutOrder().by_priority and not CutOrder(order_by="group").by_priority
    assert BY_PRIO.to_dict() == {"order_by": "priority"}
    assert CutOrder.from_dict({"order_by": "priority"}) == BY_PRIO
    assert CutOrder.from_dict({"order_by": "Priorität"}).order_by == "layer"
    assert BY_PRIO.planner_options() == CutOrder().planner_options()


def test_shape_priority_default_round_trip_and_clamping():
    lid = "L"
    s = Shape("rect", Geometry(0, 0, 10, 10), lid)
    assert s.priority == 0 and "priority" not in s.to_dict()
    s5 = Shape("rect", Geometry(0, 0, 10, 10), lid, priority=5)
    assert s5.to_dict()["priority"] == 5
    assert Shape.from_dict(s5.to_dict()).priority == 5
    assert PRIORITY_RANGE == (0, 999)
    for raw, want in ((None, 0), ("x", 0), (-3, 0), (5000, 999), (2.6, 3), ("7", 7),
                      (True, 0), (float("nan"), 0), (math.inf, 0), ([1], 0), ({}, 0)):
        assert read_priority(raw) == want, raw
        d = dict(s5.to_dict(), priority=raw)
        assert Shape.from_dict(d).priority == want, raw
    # copies (duplicate / paste) keep the priority
    assert s5.copy(new_identity=True).priority == 5


def test_document_file_round_trip(qapp):
    doc, _eng, _cut = tags_doc((2, 0))
    doc.set_cut_order(BY_PRIO)
    d = doc.to_dict()
    assert d["cut_order"] == {"order_by": "priority"}
    assert sorted(s.get("priority", 0) for s in d["objects"]) == [0, 0, 2, 2]
    again = Document.from_dict(d)
    assert again.cut_order == BY_PRIO
    assert [s.priority for s in again.shapes] == [s.priority for s in doc.shapes]
    assert layer_seq(job_layers(again)) == layer_seq(job_layers(doc))
    # old files without priorities load with 0
    plain, _e, _c = tags_doc((0, 0))
    assert all("priority" not in s for s in plain.to_dict()["objects"])


def test_path_operations_keep_the_priority(qapp):
    from lumacut_canvas import pathjoin, pathops, pathsimplify, pathsplit
    lid = "L"
    plate = Shape.from_points("polygon", [(0, 0), (40, 0), (40, 30), (0, 30),
                                          (60, 0), (80, 0), (80, 20), (60, 20)], lid, rings=(4,))
    plate.priority = 3
    parts = pathsplit.break_shape(plate)
    assert parts and len(parts) == 2 and {p.priority for p in parts} == {3}
    a = Shape("rect", Geometry(0, 0, 20, 20), lid, priority=4)
    b = Shape("rect", Geometry(50, 0, 20, 20), lid, priority=2)
    (_ids, combined), = pathsplit.combine([a, b]).groups
    assert combined.priority == 2                      # the earliest priority of the parts
    assert {s.priority for s in pathops.boolean([a, Shape("rect", Geometry(10, 10, 20, 20),
                                                              lid)], "union")} == {4}
    assert {s.priority for s in pathops.offset([a], 1.0)} == {4}
    text = Shape("text", Geometry(0, 0, 30, 10), lid, text="Ab", priority=6)
    assert pathops.text_to_outline(text).priority == 6
    dense = Shape.from_points("polygon", [(i * 0.5, (i % 2) * 0.001) for i in range(40)]
                              + [(20, 10), (0, 10)], lid)
    dense.priority = 5
    assert pathsimplify.simplify_shape(dense, 0.05).priority == 5
    gap = Shape.from_points("path", [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.02)], lid)
    gap.priority = 7
    assert [s.priority for s in pathjoin.close_paths([gap], 0.1).add] == [7]


# --- Einheiten -------------------------------------------------------------------

def test_priority_units_smallest_first_without_images_and_hidden_layers(qapp):
    from lumacut_canvas.model import RasterImage
    doc, eng, cut = tags_doc((3, 1))
    hidden = doc.add_layer(Layer("Versteckt", visible=False))
    doc.add_shape(Shape("rect", Geometry(300, 300, 10, 10), hidden.id, priority=0))
    png, pw, ph = _png()
    doc.add_shape(Shape("image", Geometry(300, 200, 8, 8), eng.id, priority=0,
                        image=RasterImage(png, pw, ph)))
    units = priority_units(doc)
    assert [p for p, _ in units] == [1, 3]
    assert all(len(shapes) == 2 for _p, shapes in units)
    assert all(s.priority == p for p, shapes in units for s in shapes)


def test_by_priority_runs_each_priority_with_all_layers(qapp):
    doc, eng, cut = tags_doc((1, 0))
    by_layer = job_layers(doc)
    assert layer_seq(by_layer) == [("Gravur", ""), ("Schneiden", "")]
    doc.set_cut_order(BY_PRIO)
    layers = job_layers(doc)
    assert layer_seq(layers) == [("Gravur", "0 (1 OF 2)"), ("Schneiden", "0 (1 OF 2)"),
                                 ("Gravur", "1 (2 OF 2)"), ("Schneiden", "1 (2 OF 2)")]
    assert {l.unit_kind for l in layers} == {"PRIORITY"}
    # priority 0 is the right-hand tag (x0 + dx)
    assert min(x for x, _y in layers[1].polylines[0]) == pytest.approx(
        min(x for x, _y in job_layers_for(doc, 1).polylines[0]))
    assert sorted(p for l in layers for p in l.polylines) == sorted(
        p for l in by_layer for p in l.polylines)
    assert sorted(b for l in layers for b in l.fills) == sorted(b for l in by_layer
                                                                 for b in l.fills)
    assert {(l.power_percent, l.speed_mm_min) for l in layers[::2]} == {(30, 3000)}


def job_layers_for(doc, index):
    """Cut layer of the tag ``index`` alone (helper for the geometry check)."""
    one = Document.from_dict(doc.to_dict())
    keep = {s.id for s in one.shapes[index * 2:index * 2 + 2]}
    for s in list(one.shapes):
        if s.id not in keep:
            one.remove_shape(s.id)
    one.set_cut_order(CutOrder())
    return job_layers(one)[1]


def test_priority_overrides_the_layer_order(qapp):
    # cut first (priority 0), engrave afterwards (priority 1) – against the layer order
    doc, eng, cut = tags_doc((0,))
    for s in doc.shapes:
        if s.layer_id == eng.id:
            s.priority = 1
    doc.set_cut_order(BY_PRIO)
    assert [l.name for l in job_layers(doc)] == ["Schneiden", "Gravur"]
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert gcode_comments(g) == ["; PRIORITY 0 (1 OF 2)", "; LAYER Schneiden",
                                 "; PRIORITY 1 (2 OF 2)", "; LAYER Gravur"]


def test_one_priority_and_default_order_are_byte_identical(qapp):
    doc, _eng, _cut = tags_doc((0, 0))
    before = optimized_document_gcode(doc, scan_offsets=None)
    plain = [(l.name, l.unit, l.polylines, l.fills) for l in job_layers(doc)]
    doc.set_cut_order(BY_PRIO)
    assert [(l.name, l.unit, l.polylines, l.fills) for l in job_layers(doc)] == plain
    assert optimized_document_gcode(doc, scan_offsets=None) == before
    for s in doc.shapes:                       # all the same non-zero priority: one unit
        s.priority = 7
    assert optimized_document_gcode(doc, scan_offsets=None) == before
    # by layer (default) ignores the priorities completely
    doc.set_cut_order(CutOrder())
    doc.shapes[0].priority = 4
    assert optimized_document_gcode(doc, scan_offsets=None) == before
    assert "; PRIORITY" not in before and "; GROUP" not in before


def test_groups_are_ignored_and_split_by_priority(qapp):
    doc, eng, cut = tags_doc((0, 1))
    for s in doc.shapes:
        s.groups = ("all",)
    doc.set_cut_order(BY_PRIO)
    assert [l.unit for l in job_layers(doc)] == ["0 (1 OF 2)"] * 2 + ["1 (2 OF 2)"] * 2
    # „Nach Gruppen“ sees a single group – one unit, no comments
    doc.set_cut_order(CutOrder(order_by="group"))
    assert {l.unit for l in job_layers(doc)} == {""}


def test_units_without_output_are_dropped_from_the_count(qapp):
    doc, eng, _cut = tags_doc((0, 1))
    doc.add_shape(Shape("text", Geometry(10, 300, 30, 10), eng.id, text="", priority=5))
    doc.set_cut_order(BY_PRIO)
    assert [p for p, _ in priority_units(doc)] == [0, 1, 5]
    assert {l.unit for l in job_layers(doc)} == {"0 (1 OF 2)", "1 (2 OF 2)"}


# --- Füllung ------------------------------------------------------------------------

def test_fill_together_and_groups_split_per_priority(qapp):
    doc, eng, _cut = tags_doc((0, 1, 1))
    doc.update_layer(eng.id, fill_grouping="together")
    assert len(layer_fill_blocks(doc, doc.layer(eng.id))) == 1
    doc.set_cut_order(BY_PRIO)
    blocks = layer_fill_blocks(doc, doc.layer(eng.id))
    assert [len(ids) for ids, _segs in blocks] == [1, 2]
    assert [len(l.fills) for l in job_layers(doc)][::2] == [1, 1]
    # „Gruppen“: one group with two priorities fills once per priority
    for s in doc.shapes:
        s.groups = ("g",)
    doc.update_layer(eng.id, fill_grouping="groups")
    blocks = layer_fill_blocks(doc, doc.layer(eng.id))
    assert [len(ids) for ids, _segs in blocks] == [1, 2]
    doc.set_cut_order(CutOrder(order_by="group"))
    assert [len(ids) for ids, _segs in layer_fill_blocks(doc, doc.layer(eng.id))] == [3]


def test_scan_offset_fill_preview_collects_every_priority(qapp):
    from lumacut_job import scan_offset as so
    doc, eng, _cut = tags_doc((0, 1))
    table = so.ScanOffsetTable(entries=[(3000.0, 0.4)]).normalized()
    plain = so.preview_fill_lines(doc, table)
    doc.set_cut_order(BY_PRIO)
    pr = so.preview_fill_lines(doc, table)
    assert {k for k, v in pr.items() if v} == {eng.id}
    assert len(pr[eng.id]) == len(plain[eng.id]) > 0


# --- G-Code ------------------------------------------------------------------------

def test_gcode_priority_comments_pi_guard_and_order(qapp):
    doc, _eng, _cut = tags_doc((2, 0, 1), x0=20, dx=110)
    doc.set_cut_order(BY_PRIO)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert gcode_comments(g) == [
        "; PRIORITY 0 (1 OF 3)", "; LAYER Gravur", "; LAYER Schneiden",
        "; PRIORITY 1 (2 OF 3)", "; LAYER Gravur", "; LAYER Schneiden",
        "; PRIORITY 2 (3 OF 3)", "; LAYER Gravur", "; LAYER Schneiden"]
    powers = [int(m) for m in re.findall(r"G1 [^\n]* S(\d+)", g) if m != "0"]
    runs = [p for i, p in enumerate(powers) if i == 0 or powers[i - 1] != p]
    assert runs == [76, 230, 76, 230, 76, 230]
    assert not re.search(r"^G[23] ", g, re.M)
    assert g.count("M3 I") == 1


def test_gcode_same_burns_as_by_layer(qapp):
    doc, _eng, _cut = tags_doc((1, 0))
    a = optimized_document_gcode(doc, scan_offsets=None)
    doc.set_cut_order(BY_PRIO)
    b = optimized_document_gcode(doc, scan_offsets=None)

    def burns(g):
        return sorted(line for line in g.splitlines()
                      if line.startswith("G1") and not line.endswith("S0"))
    assert a != b and burns(a) == burns(b)


def test_layers_to_gcode_unit_kind():
    sq = [(100.0, 100.0), (120.0, 100.0), (120.0, 120.0), (100.0, 100.0)]
    a = JobLayer("a", "A", 50, 1000, 1, [sq], unit="0 (1 OF 2)", unit_kind="PRIORITY")
    b = JobLayer("b", "B", 50, 1000, 1, [sq], unit="0 (1 OF 2)", unit_kind="PRIORITY")
    c = JobLayer("a", "A", 50, 1000, 1, [sq], unit="3 (2 OF 2)", unit_kind="PRIORITY")
    g = layers_to_gcode([a, b, c])
    assert gcode_comments(g) == ["; PRIORITY 0 (1 OF 2)", "; LAYER A", "; LAYER B",
                                 "; PRIORITY 3 (2 OF 2)", "; LAYER A"]
    # the default kind stays the group comment of round 70
    assert JobLayer("a", "A", 50, 1000, 1, [sq]).unit_kind == "GROUP"


def test_focus_offset_restored_per_priority_block(qapp):
    doc, _eng, cut = tags_doc((0, 1))
    doc.update_layer(cut.id, z_offset=-1.0)
    doc.set_cut_order(BY_PRIO)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert re.findall(r"G0 Z(-?[\d.]+)", g) == ["-1.000", "1.000"] * 2


def test_estimate_path_preview_and_images_first(qapp):
    from lumacut_canvas.model import RasterImage
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.estimate import estimate_gcode
    doc, eng, _cut = tags_doc((1, 0))
    plain = estimate_gcode(optimized_document_gcode(doc, scan_offsets=None), park=False)
    png, pw, ph = _png(60)
    doc.set_cut_order(BY_PRIO)
    g = optimized_document_gcode(doc, scan_offsets=None)
    est = estimate_gcode(g, park=False)
    assert [name for name, _t in est.layers] == ["Gravur", "Schneiden"]
    assert est.cut_length_mm == pytest.approx(plain.cut_length_mm, rel=1e-6)
    assert parse_gcode(g).sources() == [("layer", "Gravur"), ("layer", "Schneiden")]
    doc.add_shape(Shape("image", Geometry(60, 70, 8, 8), eng.id, priority=9,
                        image=RasterImage(png, pw, ph)))
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    lines = g.splitlines()
    first_image = next(i for i, l in enumerate(lines) if l.startswith("; IMAGE"))
    first_prio = next(i for i, l in enumerate(lines) if l.startswith("; PRIORITY"))
    assert first_image < first_prio


# --- Hinweise / Dialog ------------------------------------------------------------------

def test_inside_shape_conflicts(qapp):
    doc = Document(with_default_layer=False)
    cut = doc.add_layer(Layer("Schneiden", power=90, speed=400))
    plate = Shape("rect", Geometry(50, 50, 80, 60), cut.id, priority=0)
    hole = Shape("ellipse", Geometry(70, 70, 10, 10), cut.id, priority=1)
    doc.add_shape(plate)
    doc.add_shape(hole)
    assert priority_conflicts(doc) == 1
    plate.priority, hole.priority = 1, 0            # hole first: fine
    assert priority_conflicts(doc) == 0
    # a text does not count as the outer contour of a part
    doc2 = Document(with_default_layer=False)
    l2 = doc2.add_layer(Layer("L"))
    doc2.add_shape(Shape("text", Geometry(50, 50, 80, 60), l2.id, text="Hallo", priority=0))
    doc2.add_shape(Shape("rect", Geometry(60, 60, 5, 5), l2.id, priority=2))
    assert priority_conflicts(doc2) == 0
    doc.set_cut_order(BY_PRIO)
    plate.priority, hole.priority = 0, 1
    note = priority_count_note(doc)
    assert note.startswith(" (2 Prioritäten: 0, 1)") and "1 innere Form(en)" in note


def test_conflict_check_gives_up_on_huge_documents(qapp, monkeypatch):
    from lumacut_job import optimize_qt
    doc, _eng, _cut = tags_doc((0, 1))
    assert priority_conflicts(doc) == 0
    doc.add_shape(Shape("rect", Geometry(55, 75, 5, 5), doc.layers[1].id, priority=2))
    assert priority_conflicts(doc) == 1
    monkeypatch.setattr(optimize_qt, "CONFLICT_CHECK_LIMIT", 1)
    assert priority_conflicts(doc) == 0


def test_summary_hint_and_notes(qapp):
    assert summary(BY_PRIO) == "nach Priorität"
    assert summary(CutOrder(order_by="priority", enabled=False)) == (
        "Optimierung aus (Zeichenreihenfolge), nach Priorität")
    assert order_hint(BY_PRIO).startswith("Nach Priorität")
    assert order_hint(CutOrder(order_by="priority", inside_first=False)).startswith("Achtung")
    doc, _eng, _cut = tags_doc((0, 0))
    assert group_count_note(doc) == ""
    doc.set_cut_order(BY_PRIO)
    assert "dieselbe Priorität" in group_count_note(doc)
    doc.shapes[1].priority = 3          # the outline of a tag after its engraving: fine
    assert group_count_note(doc) == " (2 Prioritäten: 0, 3)"
    doc.shapes[0].priority = 5          # its engraving after the outline: warned
    assert "Achtung: 1 innere Form(en)" in group_count_note(doc)
    many, _e, _c = tags_doc(tuple(range(10)))
    many.set_cut_order(BY_PRIO)
    assert priority_count_note(many).startswith(" (10 Prioritäten: 0, 1, 2, 3, 4, 5, 6, 7 …)")


def test_dialog_priority_choice(qapp):
    assert UNIT_LABELS["priority"] == "Nach Priorität"
    dlg = OptimizeDialog(CutOrder())
    tip = dlg.order_by.toolTip()
    assert "Order by Priority" in tip and "Priorität" in tip
    dlg.order_by.setCurrentIndex(dlg.order_by.findData("priority"))
    assert dlg.value() == BY_PRIO
    assert dlg.hint.text().startswith("Nach Priorität") and dlg.hint.isVisibleTo(dlg)
    dlg.enabled.setChecked(False)
    assert dlg.order_by.isEnabled()
    assert dlg.value() == CutOrder(order_by="priority", enabled=False)
    dlg.deleteLater()
    dlg = OptimizeDialog(CutOrder(order_by="priority", direction="top_bottom"))
    assert dlg.order_by.currentText() == "Nach Priorität"
    assert dlg.value() == CutOrder(order_by="priority", direction="top_bottom")
    dlg.restore_defaults()
    assert dlg.value() == CutOrder()
    dlg.deleteLater()


# --- Eigenschaftsleiste ---------------------------------------------------------------

def test_field_visibility(ed, qapp):
    from lumacut_canvas.model import RasterImage
    lid = ed.document.active_layer_id
    a, b = _add(ed, [Shape("rect", Geometry(20, 20, 30, 20), lid),
                     Shape("ellipse", Geometry(120, 20, 30, 20), lid)])
    png, pw, ph = _png()
    (img,) = _add(ed, [Shape("image", Geometry(200, 100, 8, 8), lid,
                             image=RasterImage(png, pw, ph))])
    pc = ed.property_bar.priority_controls
    ed.set_selection([a.id])
    qapp.processEvents()
    assert not pc.isVisible()                      # by layer and priority 0: hidden
    ed.document.set_cut_order(BY_PRIO)
    qapp.processEvents()
    assert pc.isVisible() and pc.priority.value() == 0
    assert "LightBurn" in pc.priority.toolTip() and pc.priority.maximum() == 999
    ed.set_selection([img.id])
    assert not pc.isVisible()                      # images are always engraved first
    ed.set_selection([a.id, img.id])
    assert pc.isVisible() and [s.id for s in pc.targets()] == [a.id]
    ed.set_selection([])
    assert not pc.isVisible()
    # back to „Nach Ebenen“: visible only while a selected object has a priority
    ed.document.set_cut_order(CutOrder())
    ed.set_selection([a.id, b.id])
    assert not pc.isVisible()
    ed.document.shape(b.id).priority = 2
    ed.property_bar.refresh()
    assert pc.isVisible() and pc.priority.value() == 0    # mixed: the smallest


def test_field_sets_priority_with_one_undo_step(ed, qapp):
    lid = ed.document.active_layer_id
    a, b = _add(ed, [Shape("rect", Geometry(20, 20, 30, 20), lid),
                     Shape("rect", Geometry(120, 20, 30, 20), lid)])
    ed.document.set_cut_order(BY_PRIO)
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([a.id, b.id])
    n = ed.undo_stack.count()
    ed.property_bar.priority_controls.priority.setValue(3)
    assert ed.undo_stack.count() == n + 1
    doc = ed.document
    assert doc.shape(a.id).priority == 3 and doc.shape(b.id).priority == 3
    assert msgs[-1] == "Priorität 3: 2 Objekte"
    assert [s.id for s in doc.shapes] == [a.id, b.id] and set(ed.selection) == {a.id, b.id}
    ed.undo_stack.undo()
    assert doc.shape(a.id).priority == 0 and doc.shape(b.id).priority == 0
    ed.undo_stack.redo()
    assert doc.shape(a.id).priority == 3
    # same value: nothing to do
    assert ed.property_bar.priority_controls.apply(3) == []
    # values are clamped
    ed.set_selection([a.id])
    assert ed.property_bar.priority_controls.apply(5000)[0].priority == 999


def test_apply_in_layer_mode_says_when_it_works(ed, qapp):
    lid = ed.document.active_layer_id
    (a,) = _add(ed, [Shape("rect", Geometry(20, 20, 30, 20), lid)])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([a.id])
    assert ed.property_bar.priority_controls.apply(1)
    assert "1 Objekt" in msgs[-1] and "Nach Priorität" in msgs[-1]
    assert ed.property_bar.priority_controls.isVisible()  # now it has a priority


def test_locked_layer_and_targets(ed, qapp):
    lid = ed.document.active_layer_id
    (a,) = _add(ed, [Shape("rect", Geometry(20, 20, 30, 20), lid)])
    ed.document.set_cut_order(BY_PRIO)
    ed.set_selection([a.id])
    assert [s.id for s in priority_targets(ed.document, ed.selection)] == [a.id]
    ed.document.update_layer(lid, locked=True)
    ed.property_bar.refresh()
    assert not ed.property_bar.priority_controls.isVisible()
    assert ed.property_bar.priority_controls.apply(4) == []


def test_move_keeps_priority_and_save_load_touch(ed, qapp, tmp_path):
    lid = ed.document.active_layer_id
    (a,) = _add(ed, [Shape("rect", Geometry(20, 20, 30, 20), lid, priority=4)])
    ed.document.set_cut_order(BY_PRIO)
    ed.set_selection([a.id])
    ed.property_bar.x.setValue(ed.property_bar.x.value() + 10)
    assert ed.document.shape(a.id).priority == 4
    path = ed.save_file(tmp_path / "prio.lcs")
    ed.undo_stack.setClean()
    ed.load_file(path)
    (s,) = ed.document.shapes
    assert s.priority == 4 and ed.document.cut_order == BY_PRIO
    ed.set_selection([s.id])
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    spin = ed.property_bar.priority_controls.priority
    assert spin.isVisible() and spin.value() == 4 and spin.height() >= 34
    ed.set_touch_mode(False, persist=False)


def test_apply_cut_order_one_undo_step(ed, qapp):
    doc = ed.document
    lid = doc.active_layer_id
    _add(ed, [Shape("rect", Geometry(20, 20, 30, 20), lid, priority=1),
              Shape("rect", Geometry(200, 20, 30, 20), lid)])
    n = ed.undo_stack.count()
    assert apply_cut_order(ed, BY_PRIO)
    assert ed.undo_stack.count() == n + 1
    assert {l.unit for l in job_layers(doc)} == {"0 (1 OF 2)", "1 (2 OF 2)"}
    ed.undo_stack.undo()
    assert {l.unit for l in job_layers(doc)} == {""}


def test_main_window_action_field_and_gcode(qapp):
    from main import LumaCutStudio
    win = LumaCutStudio()
    try:
        tools = win.job_tools
        ed = win.canvas
        doc = ed.document
        lid = doc.active_layer.id
        a = Shape("rect", Geometry(10, 300, 20, 20), lid)
        b = Shape("rect", Geometry(320, 5, 20, 20), lid)
        ed.undo_stack.push(AddShapesCommand(doc, [a, b], "Rechtecke"))
        ed.undo_stack.push(SetGroupsCommand(doc, {a.id: ("ga",)}, "Gruppieren"))
        before = tools.job_gcode(ask_inputs=False)[0]
        assert tools.optimize_settings(BY_PRIO)
        msg = win.statusBar().currentMessage()
        assert "nach Priorität" in msg and "dieselbe Priorität" in msg
        assert tools.job_gcode(ask_inputs=False)[0] == before
        ed.set_selection([b.id])
        ed.property_bar.priority_controls.priority.setValue(2)
        after = tools.job_gcode(ask_inputs=False)[0]
        pi_check(after)
        assert [c for c in gcode_comments(after) if c.startswith("; PRIORITY")] == [
            "; PRIORITY 0 (1 OF 2)", "; PRIORITY 2 (2 OF 2)"]
        assert tools.optimize_settings(CutOrder())
        assert tools.job_gcode(ask_inputs=False)[0] == before
        assert tools.optimize_settings(BY_PRIO)
        assert "(2 Prioritäten: 0, 2)" in win.statusBar().currentMessage()
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
