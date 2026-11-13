"""Schnittreihenfolge „Nach Gruppen“ (wie LightBurn „Order by Group“).

Model / file (``CutOrder.order_by``), the job units (:func:`cut_units` – group
order with optimization off / reduce travel / direction / inside first,
ungrouped objects last, hidden layers and images), :func:`job_layers` per group,
fills („alle zusammen“ per group, scan-offset preview), G-code (``; GROUP``
comments, Pi guard, focus offsets per block, byte-identical without groups),
estimate / path preview, images first, dialog, summary / hints, undo and the
main-window action.
"""

import re

import pytest
from _pi_guard import pi_check
from PySide6.QtWidgets import QDialogButtonBox

from lumacut_canvas.commands import AddShapesCommand, SetGroupsCommand
from lumacut_canvas.export import cut_units, job_layers, layer_fill_blocks
from lumacut_canvas.gcode import layers_to_gcode
from lumacut_canvas.model import CUT_ORDER_UNITS, CutOrder, Document, Geometry, Layer, Shape
from lumacut_job.optimize_qt import (UNIT_LABELS, OptimizeDialog, apply_cut_order,
                                     group_count_note, order_hint, summary)
from lumacut_job.planner import optimize_layers, optimized_document_gcode

BY_GROUP = CutOrder(order_by="group")


def tags_doc(n=2, x0=40.0, dx=80.0, y=60.0, engrave_fill="hatch"):
    """``n`` name tags side by side: an engraved text-like rect + cut outline, each grouped."""
    doc = Document(with_default_layer=False)
    eng = doc.add_layer(Layer("Gravur", power=30, speed=3000, fill_mode=engrave_fill,
                              hatch_outline=False))
    cut = doc.add_layer(Layer("Schneiden", power=90, speed=400))
    for i in range(n):
        x = x0 + i * dx
        a = Shape("rect", Geometry(x + 10, y + 10, 40, 10), eng.id, groups=(f"g{i}",))
        b = Shape("rect", Geometry(x, y, 60, 30), cut.id, groups=(f"g{i}",))
        doc.add_shape(a)
        doc.add_shape(b)
    return doc, eng, cut


def layer_seq(layers):
    return [(l.name, l.unit) for l in layers]


def gcode_comments(g):
    return [line for line in g.splitlines() if line.startswith("; GROUP") or
            line.startswith("; LAYER")]


@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()
    ed.close()
    ed.deleteLater()
    qapp.processEvents()


# --- Modell / Datei ---------------------------------------------------------------

def test_model_default_round_trip_and_broken_values():
    assert CutOrder().order_by == "layer" and not CutOrder().by_group
    assert CUT_ORDER_UNITS == ("layer", "group", "priority")
    assert BY_GROUP.by_group and not BY_GROUP.is_default
    assert "order_by" not in CutOrder().to_dict()
    assert BY_GROUP.to_dict() == {"order_by": "group"}
    assert CutOrder.from_dict({"order_by": "group"}) == BY_GROUP
    for bad in ("Priority", "", None, 3, ["group"]):
        assert CutOrder.from_dict({"order_by": bad}).order_by == "layer"
    # the planner keywords stay the same (order_by is not a planner option)
    assert BY_GROUP.planner_options() == CutOrder().planner_options()


def test_document_file_round_trip(qapp):
    doc, _eng, _cut = tags_doc()
    assert "cut_order" not in doc.to_dict()
    doc.set_cut_order(CutOrder(order_by="group", direction="top_bottom"))
    d = doc.to_dict()
    assert d["cut_order"] == {"order_by": "group", "direction": "top_bottom"}
    again = Document.from_dict(d)
    assert again.cut_order == doc.cut_order
    assert layer_seq(job_layers(again)) == layer_seq(job_layers(doc))


# --- Einheiten -------------------------------------------------------------------

def test_by_layer_unchanged_and_by_group_runs_each_group_with_all_layers(qapp):
    doc, eng, cut = tags_doc()
    by_layer = job_layers(doc)
    assert layer_seq(by_layer) == [("Gravur", ""), ("Schneiden", "")]
    assert [len(l.fills) for l in by_layer] == [2, 0]
    assert [len(l.polylines) for l in by_layer] == [0, 2]
    doc.set_cut_order(BY_GROUP)
    layers = job_layers(doc)
    assert layer_seq(layers) == [("Gravur", "1 OF 2"), ("Schneiden", "1 OF 2"),
                                 ("Gravur", "2 OF 2"), ("Schneiden", "2 OF 2")]
    assert [len(l.fills) for l in layers] == [1, 0, 1, 0]
    assert [len(l.polylines) for l in layers] == [0, 1, 0, 1]
    assert all(l.layer_id == eng.id for l in layers[::2])
    assert all(l.layer_id == cut.id for l in layers[1::2])
    # same geometry in total, only regrouped
    assert sorted(p for l in layers for p in l.polylines) == sorted(
        p for l in by_layer for p in l.polylines)
    assert sorted(b for l in layers for b in l.fills) == sorted(b for l in by_layer
                                                                 for b in l.fills)
    # parameters of each block follow its layer
    assert {(l.power_percent, l.speed_mm_min) for l in layers[::2]} == {(30, 3000)}


def test_without_groups_by_group_is_byte_identical(qapp):
    doc, _eng, _cut = tags_doc()
    for s in doc.shapes:
        s.groups = ()
    def plain(layers):
        return [(l.name, l.unit, l.polylines, l.fills) for l in layers]
    before_layers = plain(job_layers(doc))
    before = optimized_document_gcode(doc, scan_offsets=None)
    doc.set_cut_order(BY_GROUP)
    assert plain(job_layers(doc)) == before_layers
    assert optimized_document_gcode(doc, scan_offsets=None) == before
    assert "; GROUP" not in before
    # a single group is a single unit as well
    for s in doc.shapes:
        s.groups = ("only",)
    assert optimized_document_gcode(doc, scan_offsets=None) == before


def test_by_layer_default_gcode_unchanged_with_groups(qapp):
    doc, _eng, _cut = tags_doc(3)
    g = optimized_document_gcode(doc, scan_offsets=None)
    assert "; GROUP" not in g
    assert [c for c in gcode_comments(g)] == ["; LAYER Gravur", "; LAYER Schneiden"]


def test_ungrouped_objects_form_the_last_unit(qapp):
    doc, eng, cut = tags_doc(2)
    frame = Shape("rect", Geometry(20, 40, 200, 80), cut.id)       # ungrouped sheet outline
    doc.add_shape(frame)
    note = Shape("rect", Geometry(25, 45, 10, 5), eng.id)           # ungrouped engraving
    doc.shapes.insert(0, note)
    doc.set_cut_order(BY_GROUP)
    units = cut_units(doc)
    assert [gid for gid, _ in units] == ["g1", "g0", ""]   # nearest to the origin top right
    assert {s.id for s in units[-1][1]} == {frame.id, note.id}
    layers = job_layers(doc)
    assert [l.unit for l in layers][-2:] == ["3 OF 3", "3 OF 3"]
    assert layers[-1].polylines and len(layers[-1].polylines) == 1


def test_nested_groups_use_the_top_group(qapp):
    doc, eng, cut = tags_doc(2)
    for s in doc.shapes:
        if s.groups == ("g0",) and s.layer_id == eng.id:
            s.groups = ("g0", "inner")
    doc.set_cut_order(BY_GROUP)
    assert sorted(gid for gid, _ in cut_units(doc)) == ["g0", "g1"]
    assert len(job_layers(doc)) == 4


def test_hidden_layers_and_images_are_not_units(qapp):
    from lumacut_canvas.model import RasterImage
    from lumacut_import.image import grayscale_png
    from PySide6.QtGui import QColor, QImage
    doc, eng, cut = tags_doc(2)
    hidden = doc.add_layer(Layer("Versteckt", visible=False))
    doc.add_shape(Shape("rect", Geometry(300, 300, 10, 10), hidden.id, groups=("h",)))
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor(90, 90, 90))
    png, pw, ph = grayscale_png(img)
    doc.add_shape(Shape("image", Geometry(300, 200, 8, 8), eng.id, groups=("pic",),
                        image=RasterImage(png, pw, ph)))
    doc.set_cut_order(BY_GROUP)
    assert [gid for gid, _ in cut_units(doc)] == ["g1", "g0"]
    assert {l.unit for l in job_layers(doc)} == {"1 OF 2", "2 OF 2"}


def test_units_without_output_are_dropped_from_the_count(qapp):
    doc, eng, cut = tags_doc(2)
    # an empty text on the fill-only layer gives neither fill nor contour
    doc.add_shape(Shape("text", Geometry(10, 300, 30, 10), eng.id, text="",
                        groups=("empty",)))
    doc.set_cut_order(BY_GROUP)
    assert len(cut_units(doc)) == 3
    assert {l.unit for l in job_layers(doc)} == {"1 OF 2", "2 OF 2"}


# --- Reihenfolge der Gruppen ---------------------------------------------------------

def _unit_x(doc):
    return [round(min(s.geom.x for s in shapes)) for _gid, shapes in cut_units(doc)]


def test_group_order_nearest_from_the_machine_origin(qapp):
    # the machine origin is top right: the right-most tag starts, then leftwards
    doc, _eng, _cut = tags_doc(3, x0=20, dx=110)
    doc.set_cut_order(BY_GROUP)
    assert _unit_x(doc) == [240, 130, 20]
    # optimization off: drawing order of the first object of each group
    doc.set_cut_order(CutOrder(order_by="group", enabled=False))
    assert _unit_x(doc) == [20, 130, 240]
    # inside first only (no travel reduction, no direction): drawing order as well
    doc.set_cut_order(CutOrder(order_by="group", reduce_travel=False))
    assert _unit_x(doc) == [20, 130, 240]


def test_group_order_follows_the_direction_rows(qapp):
    doc = Document(with_default_layer=False)
    lid = doc.add_layer(Layer("Schneiden")).id
    spots = {"a": (20, 200), "b": (200, 20), "c": (120, 205), "d": (300, 210), "e": (60, 25)}
    for gid, (x, y) in spots.items():
        doc.add_shape(Shape("rect", Geometry(x, y, 30, 20), lid, groups=(gid,)))
    doc.set_cut_order(CutOrder(order_by="group", direction="top_bottom"))
    order = [gid for gid, _ in cut_units(doc)]
    assert set(order[:2]) == {"b", "e"} and set(order[2:]) == {"a", "c", "d"}
    doc.set_cut_order(CutOrder(order_by="group", direction="bottom_top"))
    order = [gid for gid, _ in cut_units(doc)]
    assert set(order[:3]) == {"a", "c", "d"} and set(order[3:]) == {"b", "e"}
    doc.set_cut_order(CutOrder(order_by="group", direction="left_right"))
    assert [gid for gid, _ in cut_units(doc)] == ["a", "e", "c", "b", "d"]
    doc.set_cut_order(CutOrder(order_by="group", direction="right_left"))
    assert [gid for gid, _ in cut_units(doc)] == ["d", "b", "c", "e", "a"]


def test_inside_first_puts_a_group_inside_another_before_it(qapp):
    doc = Document(with_default_layer=False)
    lid = doc.add_layer(Layer("Schneiden")).id
    # big plate group drawn first, a small group lying inside it drawn later
    doc.add_shape(Shape("rect", Geometry(100, 100, 150, 120), lid, groups=("plate",)))
    doc.add_shape(Shape("ellipse", Geometry(150, 140, 30, 30), lid, groups=("disc",)))
    doc.add_shape(Shape("rect", Geometry(300, 10, 20, 20), lid, groups=("far",)))
    doc.set_cut_order(BY_GROUP)
    order = [gid for gid, _ in cut_units(doc)]
    assert order.index("disc") < order.index("plate")
    doc.set_cut_order(CutOrder(order_by="group", inside_first=False, reduce_travel=False))
    assert [gid for gid, _ in cut_units(doc)] == ["plate", "disc", "far"]
    # identical boxes do not block each other
    doc.add_shape(Shape("rect", Geometry(100, 100, 150, 120), lid, groups=("twin",)))
    doc.set_cut_order(BY_GROUP)
    assert sorted(gid for gid, _ in cut_units(doc)) == ["disc", "far", "plate", "twin"]


# --- Füllung -------------------------------------------------------------------------

def test_fill_together_is_split_per_group(qapp):
    doc, eng, _cut = tags_doc(2)
    doc.update_layer(eng.id, fill_grouping="together")
    eng = doc.layer(eng.id)
    assert len(layer_fill_blocks(doc, eng)) == 1
    doc.set_cut_order(BY_GROUP)
    blocks = layer_fill_blocks(doc, eng)
    assert len(blocks) == 2 and all(len(ids) == 1 for ids, _ in blocks)
    layers = job_layers(doc)
    assert [len(l.fills) for l in layers] == [1, 0, 1, 0]


def test_fill_groups_mode_and_offset_fill_per_group(qapp):
    doc, eng, _cut = tags_doc(2, engrave_fill="offset")
    doc.set_cut_order(BY_GROUP)
    layers = optimize_layers(job_layers(doc))
    assert [bool(l.fills) for l in layers] == [True, False, True, False]
    assert all(l.fill_fixed_order for l in layers[::2])
    doc.update_layer(eng.id, fill_mode="hatch", fill_grouping="groups")
    layers = job_layers(doc)
    assert [len(l.fills) for l in layers] == [1, 0, 1, 0]


def test_scan_offset_fill_preview_collects_every_group(qapp):
    from lumacut_job import scan_offset as so
    doc, eng, _cut = tags_doc(2)
    table = so.ScanOffsetTable(entries=[(3000.0, 0.4)]).normalized()
    plain = so.preview_fill_lines(doc, table)
    doc.set_cut_order(BY_GROUP)
    grouped = so.preview_fill_lines(doc, table)
    assert {k for k, v in grouped.items() if v} == {eng.id}
    assert len(grouped[eng.id]) == len(plain[eng.id]) > 0


# --- G-Code ------------------------------------------------------------------------

def test_gcode_group_comments_pi_guard_and_order(qapp):
    doc, _eng, _cut = tags_doc(3, x0=20, dx=110)
    doc.set_cut_order(BY_GROUP)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert gcode_comments(g) == [
        "; GROUP 1 OF 3", "; LAYER Gravur", "; LAYER Schneiden",
        "; GROUP 2 OF 3", "; LAYER Gravur", "; LAYER Schneiden",
        "; GROUP 3 OF 3", "; LAYER Gravur", "; LAYER Schneiden"]
    # every tag is cut before the next one is engraved: the cut power S230 of a
    # group comes before the engraving power S76 of the next
    powers = [int(m) for m in re.findall(r"G1 [^\n]* S(\d+)", g) if m != "0"]
    runs = [p for i, p in enumerate(powers) if i == 0 or powers[i - 1] != p]
    assert runs == [76, 230, 76, 230, 76, 230]
    assert not re.search(r"^G[23] ", g, re.M)
    assert g.count("M3 I") == 1 and g.rstrip().endswith("M400")


def test_gcode_same_burns_as_by_layer(qapp):
    doc, _eng, _cut = tags_doc(2)
    a = optimized_document_gcode(doc, scan_offsets=None)
    doc.set_cut_order(BY_GROUP)
    b = optimized_document_gcode(doc, scan_offsets=None)

    def burns(g):
        return sorted(line for line in g.splitlines()
                      if line.startswith("G1") and not line.endswith("S0"))
    assert a != b and burns(a) == burns(b)


def test_focus_offset_and_z_step_per_group_block_are_restored(qapp):
    doc, eng, cut = tags_doc(2)
    doc.update_layer(cut.id, z_offset=-1.0, passes=2, z_step=0.5)
    doc.set_cut_order(BY_GROUP)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    z = re.findall(r"G0 Z(-?[\d.]+)", g)
    # per group: offset down, step down, step back up, offset back – twice
    assert z == ["-1.000", "-0.500", "0.500", "1.000"] * 2
    assert sum(float(v) for v in z) == pytest.approx(0.0)


def test_layers_to_gcode_writes_a_group_comment_only_on_change():
    from lumacut_canvas.export import JobLayer
    sq = [(100.0, 100.0), (120.0, 100.0), (120.0, 120.0), (100.0, 100.0)]
    a = JobLayer("a", "A", 50, 1000, 1, [sq], unit="1 OF 2")
    b = JobLayer("b", "B", 50, 1000, 1, [sq], unit="1 OF 2")
    c = JobLayer("a", "A", 50, 1000, 1, [sq], unit="2 OF 2")
    g = layers_to_gcode([a, b, c])
    assert gcode_comments(g) == ["; GROUP 1 OF 2", "; LAYER A", "; LAYER B",
                                 "; GROUP 2 OF 2", "; LAYER A"]
    plain = layers_to_gcode([JobLayer("a", "A", 50, 1000, 1, [sq])])
    assert "; GROUP" not in plain


def test_estimate_and_path_preview_merge_the_layer_blocks(qapp):
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.estimate import estimate_gcode
    doc, _eng, _cut = tags_doc(2)
    plain = estimate_gcode(optimized_document_gcode(doc, scan_offsets=None), park=False)
    doc.set_cut_order(BY_GROUP)
    g = optimized_document_gcode(doc, scan_offsets=None)
    est = estimate_gcode(g, park=False)
    assert [name for name, _t in est.layers] == ["Gravur", "Schneiden"]
    assert est.cut_length_mm == pytest.approx(plain.cut_length_mm, rel=1e-6)
    assert "Gravur" in est.layer_summary() and "Schneiden" in est.layer_summary()
    tp = parse_gcode(g)
    assert tp.sources() == [("layer", "Gravur"), ("layer", "Schneiden")]


def test_images_are_still_engraved_first(qapp):
    from lumacut_canvas.model import RasterImage
    from lumacut_import.image import grayscale_png
    from PySide6.QtGui import QColor, QImage
    doc, eng, _cut = tags_doc(2)
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor(60, 60, 60))
    png, pw, ph = grayscale_png(img)
    doc.add_shape(Shape("image", Geometry(60, 70, 8, 8), eng.id, groups=("g1",),
                        image=RasterImage(png, pw, ph)))
    doc.set_cut_order(BY_GROUP)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    lines = g.splitlines()
    first_image = next(i for i, l in enumerate(lines) if l.startswith("; IMAGE"))
    first_group = next(i for i, l in enumerate(lines) if l.startswith("; GROUP"))
    assert first_image < first_group


def test_frame_and_park_box_cover_all_groups(qapp):
    from lumacut_job.park_zone import planned_powered_box
    doc, _eng, _cut = tags_doc(2)
    box = planned_powered_box(doc)
    doc.set_cut_order(BY_GROUP)
    grouped = planned_powered_box(doc)
    assert grouped is not None
    assert (grouped.xmin, grouped.ymin, grouped.xmax, grouped.ymax) == pytest.approx(
        (box.xmin, box.ymin, box.xmax, box.ymax))


# --- Dialog / Texte / Undo -----------------------------------------------------------

def test_dialog_combo_values_and_reset(qapp):
    dlg = OptimizeDialog(CutOrder())
    assert [dlg.order_by.itemText(i) for i in range(dlg.order_by.count())] == [
        "Nach Ebenen", "Nach Gruppen", "Nach Priorität"]
    assert [UNIT_LABELS[k] for k in CUT_ORDER_UNITS] == ["Nach Ebenen", "Nach Gruppen",
                                                         "Nach Priorität"]
    assert dlg.order_by.currentText() == "Nach Ebenen" and dlg.value() == CutOrder()
    assert "Order by" in dlg.order_by.toolTip() and "Gruppe" in dlg.order_by.toolTip()
    dlg.order_by.setCurrentIndex(dlg.order_by.findData("group"))
    assert dlg.value() == BY_GROUP
    assert dlg.hint.text().startswith("Nach Gruppen")
    # the order choice stays usable with the optimization off
    dlg.enabled.setChecked(False)
    assert dlg.order_by.isEnabled()
    assert dlg.value() == CutOrder(order_by="group", enabled=False)
    dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.RestoreDefaults).click()
    assert dlg.value() == CutOrder() and dlg.order_by.currentText() == "Nach Ebenen"
    dlg.deleteLater()
    dlg = OptimizeDialog(CutOrder(order_by="group", direction="left_right"))
    assert dlg.order_by.currentText() == "Nach Gruppen"
    assert dlg.value() == CutOrder(order_by="group", direction="left_right")
    dlg.deleteLater()


def test_summary_hint_and_group_note(qapp):
    assert summary(BY_GROUP) == "nach Gruppen"
    assert summary(CutOrder(order_by="group", enabled=False)) == (
        "Optimierung aus (Zeichenreihenfolge), nach Gruppen")
    assert summary(CutOrder(order_by="group", direction="top_bottom")) == (
        "nach Gruppen, in Richtung von oben nach unten")
    assert "Gruppe" in order_hint(BY_GROUP)
    assert order_hint(CutOrder(order_by="group", enabled=False)).startswith("Achtung")
    doc, _eng, _cut = tags_doc(3)
    assert group_count_note(doc) == ""
    doc.set_cut_order(BY_GROUP)
    assert group_count_note(doc) == " (3 Gruppe(n))"
    for s in doc.shapes:
        s.groups = ()
    assert "keine Gruppen" in group_count_note(doc)


def test_apply_is_one_undo_step_and_regroups_the_job(editor):
    doc = editor.document
    lid = doc.active_layer_id
    a = Shape("rect", Geometry(20, 20, 30, 20), lid)
    b = Shape("rect", Geometry(200, 20, 30, 20), lid)
    editor.undo_stack.push(AddShapesCommand(doc, [a, b], "Rechtecke"))
    editor.undo_stack.push(SetGroupsCommand(doc, {a.id: ("ga",)}, "Gruppieren"))
    editor.undo_stack.push(SetGroupsCommand(doc, {b.id: ("gb",)}, "Gruppieren"))
    n = editor.undo_stack.count()
    assert apply_cut_order(editor, BY_GROUP)
    assert editor.undo_stack.count() == n + 1
    assert {l.unit for l in job_layers(doc)} == {"1 OF 2", "2 OF 2"}
    editor.undo_stack.undo()
    assert doc.cut_order == CutOrder()
    assert {l.unit for l in job_layers(doc)} == {""}


def test_main_window_action_status_and_gcode(qapp):
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
        before = tools.job_gcode(ask_inputs=False)[0]
        assert tools.optimize_settings(BY_GROUP)
        assert "nach Gruppen" in win.statusBar().currentMessage()
        assert "keine Gruppen" in win.statusBar().currentMessage()
        assert tools.job_gcode(ask_inputs=False)[0] == before
        ed.undo_stack.push(SetGroupsCommand(doc, {a.id: ("ga",), b.id: ("gb",)}, "Gruppieren"))
        after = tools.job_gcode(ask_inputs=False)[0]
        pi_check(after)
        assert after.count("; GROUP") == 2
        assert tools.optimize_settings(CutOrder())
        assert tools.job_gcode(ask_inputs=False)[0] == before
        assert tools.optimize_settings(BY_GROUP)
        assert "(2 Gruppe(n))" in win.statusBar().currentMessage()
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
