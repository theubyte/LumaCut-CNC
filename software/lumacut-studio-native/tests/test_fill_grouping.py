"""Füllgruppen je Ebene (LightBurn „Fill shapes individually / groups together / all at once“)
und Offset-Reihenfolge von innen nach außen."""

from __future__ import annotations

import math

import pytest

from _pi_guard import pi_check
from lumacut_canvas import hatch
from lumacut_canvas.hatch import offset_fill_rings, segments_length

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _doc(**layer):
    """Rahmen aus zwei getrennten Rechtecken (40×30 außen, 20×10 innen) plus ein
    gruppiertes Paar überlappender Rechtecke weiter rechts."""
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, **layer)
    outer = doc.add_shape(Shape("rect", Geometry(10, 10, 40, 30), lid))
    inner = doc.add_shape(Shape("rect", Geometry(20, 20, 20, 10), lid))
    a = doc.add_shape(Shape("rect", Geometry(100, 10, 20, 20), lid))
    b = doc.add_shape(Shape("rect", Geometry(110, 10, 20, 20), lid))
    doc.set_groups(a.id, ("g1",))
    doc.set_groups(b.id, ("g1",))
    return doc, (outer, inner, a, b)


def _blocks(doc):
    from lumacut_canvas.export import layer_fill_blocks
    return layer_fill_blocks(doc, doc.active_layer)


def _moves(g):
    return [l for l in g.splitlines() if l.startswith(("G0 ", "G1 "))]


# --- Modell -----------------------------------------------------------------------

def test_groupings_are_registered_with_german_labels():
    assert hatch.FILL_GROUPINGS == ("individual", "groups", "together")
    assert hatch.FILL_GROUPING_LABELS["together"] == "Alle Objekte zusammen"


def test_layer_defaults_normalize_and_roundtrip(qapp):
    from lumacut_canvas.model import Document, Layer
    l = Layer("x")
    assert l.fill_grouping == "individual" and l.offset_inside_out is False
    assert "fill_grouping" not in l.to_dict() and "offset_inside_out" not in l.to_dict()
    l = Layer.from_dict({"name": "x", "fill_mode": "offset", "fill_grouping": "together",
                         "offset_inside_out": True})
    assert l.fill_grouping == "together" and l.offset_inside_out
    assert Layer.from_dict(l.to_dict()) == l
    assert Layer.from_dict({"fill_grouping": "bogus"}).fill_grouping == "individual"
    doc, _ = _doc(fill_mode="hatch", fill_grouping="groups")
    assert Document.from_dict(doc.to_dict()).layers[0].fill_grouping == "groups"


# --- Blöcke -----------------------------------------------------------------------

def test_individual_fills_each_object_on_its_own(qapp):
    doc, shapes = _doc(fill_mode="hatch", line_interval_mm=1.0)
    blocks = _blocks(doc)
    assert [ids for ids, _ in blocks] == [[s.id] for s in shapes]
    # innen liegendes Rechteck wird zusätzlich gefüllt (doppelt gelasert)
    assert segments_length(blocks[0][1]) == pytest.approx(40 * 30)
    assert segments_length(blocks[1][1]) == pytest.approx(20 * 10)


def test_together_makes_nested_objects_holes_and_overlaps_free(qapp):
    doc, (outer, inner, a, b) = _doc(fill_mode="hatch", line_interval_mm=1.0)
    doc.update_layer(doc.active_layer_id, fill_grouping="together")
    (ids, segs), = _blocks(doc)
    assert ids == [s.id for s in (outer, inner, a, b)]
    # Rahmen: 40×30 − 20×10; Paar: 2 × 20×20 − Überlappung 10×20 doppelt frei
    assert segments_length(segs) == pytest.approx(40 * 30 - 20 * 10 + 400 + 400 - 2 * 200)
    for (x0, y0), (x1, y1) in segs:              # nichts im Loch
        if 20 < y0 < 30:
            assert not (20 < (x0 + x1) / 2 < 40)


def test_groups_fill_together_only_within_a_group(qapp):
    doc, (outer, inner, a, b) = _doc(fill_mode="hatch", line_interval_mm=1.0,
                                     fill_grouping="groups")
    blocks = _blocks(doc)
    assert [ids for ids, _ in blocks] == [[outer.id], [inner.id], [a.id, b.id]]
    assert segments_length(blocks[2][1]) == pytest.approx(400 + 400 - 2 * 200)
    # Gruppe aus Rahmen-Teilen: dann wird das innere Rechteck zum Loch
    doc.set_groups(outer.id, ("g2",))
    doc.set_groups(inner.id, ("g2", "sub"))
    blocks = _blocks(doc)
    assert [ids for ids, _ in blocks] == [[outer.id, inner.id], [a.id, b.id]]
    assert segments_length(blocks[0][1]) == pytest.approx(40 * 30 - 20 * 10)
    # nur die oberste Gruppe zählt
    doc.set_groups(a.id, ("g1", "x"))
    doc.set_groups(b.id, ("g1", "y"))
    assert len(_blocks(doc)) == 2


def test_together_with_offset_fill_follows_the_hole(qapp):
    doc, _ = _doc(fill_mode="offset", line_interval_mm=1.0, fill_grouping="together")
    (_, segs), = _blocks(doc)
    from shapely.geometry import Point, box
    hole = box(20, 20, 40, 30)
    assert all(not hole.contains(Point(p)) for p, _ in segs)
    assert segments_length(segs) == pytest.approx(40 * 30 - 20 * 10 + 400, rel=0.03)


def test_open_and_image_shapes_are_not_part_of_a_fill_group(qapp):
    from lumacut_canvas.model import Geometry, Shape
    doc, _ = _doc(fill_mode="hatch", line_interval_mm=1.0, fill_grouping="together")
    doc.add_shape(Shape("line", Geometry(0, 0, 50, 50), doc.active_layer_id))
    (ids, _), = _blocks(doc)
    assert len(ids) == 4
    doc.update_layer(doc.active_layer_id, fill_mode="none")
    assert _blocks(doc) == []


# --- Offset von innen nach außen ---------------------------------------------------

def test_inside_out_reverses_ring_order_per_island():
    out_in = offset_fill_rings([SQUARE], 1.0)
    in_out = offset_fill_rings([SQUARE], 1.0, inside_out=True)
    assert len(in_out) == len(out_in) == 5
    widths = [max(p[0] for p in r) - min(p[0] for p in r) for r in in_out]
    assert widths == pytest.approx([1, 3, 5, 7, 9])
    assert segments_length(hatch.rings_to_segments(in_out)) == pytest.approx(100.0)
    b = [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)]
    rings = offset_fill_rings([SQUARE, b], 1.0, inside_out=True)
    left = [max(p[0] for p in r) < 15 for r in rings]
    assert left == [True] * 5 + [False] * 5        # Insel für Insel
    assert [round(max(p[0] for p in r) - min(p[0] for p in r), 3) for r in rings[5:]] == \
        pytest.approx([1, 3, 5, 7, 9])
    assert hatch.fill_segments([SQUARE], "offset", 1.0, inside_out=True) == \
        hatch.rings_to_segments(in_out)
    # Schraffur ignoriert inside_out
    assert hatch.fill_segments([SQUARE], "hatch", 1.0, inside_out=True) == \
        hatch.fill_segments([SQUARE], "hatch", 1.0)


def test_offset_gcode_keeps_the_ring_order_even_if_the_inner_end_is_nearer(qapp):
    """Offset-Blöcke werden nie rückwärts gefahren (sonst kehrte sich die Reihenfolge um)."""
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode, order_fill_blocks
    from lumacut_canvas.model import Document, Geometry, Shape
    for inside_out in (False, True):
        doc = Document()
        lid = doc.active_layer_id
        doc.update_layer(lid, fill_mode="offset", line_interval_mm=2.0, hatch_outline=False,
                         offset_inside_out=inside_out)
        # zwei Objekte: das zweite liegt mit seiner Mitte nah am Ende des ersten
        doc.add_shape(Shape("rect", Geometry(20, 20, 20, 20), lid))
        doc.add_shape(Shape("rect", Geometry(42, 10, 40, 40), lid))
        (jl,) = job_layers(doc)
        assert jl.fill_fixed_order
        g = layers_to_gcode([jl])
        g1 = [m for m in _moves(g) if m.startswith("G1")]
        assert len(g1) == sum(len(b) for b in jl.fills)
        ordered = order_fill_blocks(jl.fills, (0.0, 0.0), reversible=False)
        assert ordered == [b for b in jl.fills]
        second = jl.fills[1]
        size = lambda seg: math.dist(*seg)
        first_ring, last_ring = size(second[0]), size(second[-1])
        assert (first_ring < last_ring) == inside_out
    # Schraffur-Blöcke bleiben umkehrbar
    doc.update_layer(lid, fill_mode="hatch")
    (jl,) = job_layers(doc)
    assert not jl.fill_fixed_order


def test_individual_hatch_gcode_is_unchanged(qapp):
    """Standard „einzeln“: G-Code wie bisher (ein Block je Objekt)."""
    from lumacut_canvas.export import job_layers
    doc, shapes = _doc(fill_mode="hatch", line_interval_mm=1.0)
    (jl,) = job_layers(doc)
    assert len(jl.fills) == 4


def test_gcode_planner_and_pi_guard_with_fill_together(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    from lumacut_job.planner import optimized_document_gcode
    from lumacut_job.estimate import estimate_gcode
    for mode in ("hatch", "crosshatch", "offset"):
        doc, _ = _doc(fill_mode=mode, line_interval_mm=0.5, fill_grouping="together",
                      hatch_outline=False, offset_inside_out=True)
        plain = document_to_gcode(doc)
        opt = optimized_document_gcode(doc)
        assert opt.count("G1 ") == plain.count("G1 ")
        pi_check(opt)
        assert opt.count("M3 I") == 1
        if mode == "hatch":
            assert estimate_gcode(plain).cut_length_mm == pytest.approx(
                (40 * 30 - 20 * 10 + 400) / 0.5, rel=0.01)


# --- Panel, Vorschau, Export --------------------------------------------------------

def test_panel_grouping_combo_and_inside_out_box(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel, layer_summary
    doc, _ = _doc()
    stack = QUndoStack()
    p = LayersPanel(doc, stack)
    assert not p.fill_grouping.isEnabled() and not p.fill_inside_out.isEnabled()
    p.fill_mode.setCurrentIndex(p.fill_mode.findData("hatch"))
    p.fill_mode.activated.emit(p.fill_mode.currentIndex())
    assert p.fill_grouping.isEnabled() and not p.fill_inside_out.isEnabled()
    idx = p.fill_grouping.findData("together")
    assert p.fill_grouping.itemText(idx) == "Alle Objekte zusammen"
    p.fill_grouping.setCurrentIndex(idx)
    p.fill_grouping.activated.emit(idx)
    layer = doc.active_layer
    assert layer.fill_grouping == "together" and "alle zusammen" in layer_summary(layer)
    p.fill_mode.setCurrentIndex(p.fill_mode.findData("offset"))
    p.fill_mode.activated.emit(p.fill_mode.currentIndex())
    assert p.fill_inside_out.isEnabled()
    p.fill_inside_out.setChecked(True)
    assert doc.active_layer.offset_inside_out
    assert stack.count() == 4
    assert stack.text(3) == "Offset von innen nach außen"
    stack.undo()
    assert not doc.active_layer.offset_inside_out and not p.fill_inside_out.isChecked()
    stack.undo()
    stack.undo()
    assert doc.active_layer.fill_grouping == "individual"
    assert p.fill_grouping.currentData() == "individual"


def test_canvas_preview_uses_fill_groups(qapp):
    from lumacut_canvas.editor import CanvasEditor
    doc, _ = _doc(fill_mode="hatch", line_interval_mm=1.0)
    ed = CanvasEditor(doc)
    def length():
        return sum(l.length() for _, lines in ed.fill_preview.lines for l in lines)
    ed.fill_preview.rebuild()
    assert length() == pytest.approx(40 * 30 + 20 * 10 + 2 * 400)
    doc.update_layer(doc.active_layer_id, fill_grouping="together")
    ed.fill_preview.rebuild()
    assert length() == pytest.approx(40 * 30 - 20 * 10 + 400)   # Loch, Überlappung frei
    ed.grab()


def test_png_export_draws_the_together_fill_with_hole(qapp, tmp_path):
    from PySide6.QtGui import QColor
    from lumacut_canvas.export import export_png
    doc, _ = _doc(fill_mode="hatch", line_interval_mm=1.0, fill_grouping="together",
                  hatch_outline=False)
    img = export_png(doc, str(tmp_path / "f.png"), px_per_mm=10.0,
                     background=QColor("white"), show_fill=True)

    def inked(x0, y0, x1, y1):
        return sum(img.pixelColor(x, y).lightness() < 200
                   for x in range(x0 * 10, x1 * 10, 3) for y in range(y0 * 10, y1 * 10, 3))
    assert inked(12, 12, 18, 18) > 0              # Rahmen gefüllt
    assert inked(22, 22, 38, 28) == 0             # Loch frei (inneres Rechteck nur Loch)
    assert inked(112, 12, 118, 28) == 0           # Überlappung des Paars frei
    assert inked(102, 12, 108, 28) > 0
