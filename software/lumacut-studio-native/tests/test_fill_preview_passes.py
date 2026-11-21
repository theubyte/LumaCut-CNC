"""Canvas fill preview with the angle increment per pass: further passes under their own angle."""

from __future__ import annotations

import math

import pytest

from _pi_guard import pi_check
from test_fill_angle_increment import _doc, _gcode, _passes


@pytest.fixture(autouse=True)
def _plain_preview():
    """Synchronous preview without a scan offset table (restored afterwards)."""
    from lumacut_canvas import fill_preview
    from lumacut_job import scan_offset
    old_bg, old_tab = fill_preview.BACKGROUND, scan_offset.active_table()
    fill_preview.BACKGROUND = False
    scan_offset.set_active_table(None)
    scan_offset._PREVIEW_CACHE.clear()
    yield
    fill_preview.BACKGROUND = old_bg
    scan_offset.set_active_table(old_tab)
    scan_offset._PREVIEW_CACHE.clear()


def _editor(doc):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor(doc)
    ed.fill_preview.rebuild()
    return ed


def _segs(lines):
    return sorted((round(l.x1(), 6), round(l.y1(), 6), round(l.x2(), 6), round(l.y2(), 6))
                  for l in lines)


def _geom(doc, layer, angle):
    from lumacut_canvas.export import layer_fill_blocks
    return sorted((round(a[0], 6), round(a[1], 6), round(b[0], 6), round(b[1], 6))
                  for _ids, segs in layer_fill_blocks(doc, layer, angle) for a, b in segs)


def _dirs(lines):
    return {round(math.degrees(math.atan2(l.dy(), l.dx())) % 180.0, 1) % 180.0 for l in lines}


def test_second_pass_shown_under_its_own_angle(qapp):
    doc = _doc(passes=2, hatch_angle=0.0, fill_angle_increment=90.0)
    fp = _editor(doc).fill_preview
    layer = doc.layers[0]
    (_c, lines), = fp.lines
    assert _segs(lines) == _geom(doc, layer, 0.0) and _dirs(lines) == {0.0}
    (color, angle, extra), = fp.pass_lines
    assert angle == 90.0 and _segs(extra) == _geom(doc, layer, 90.0) and _dirs(extra) == {90.0}
    assert fp.pass_angles_shown() == [90.0]
    assert fp.pass_line_count() == len(extra) and fp.line_count() == len(lines)
    from PySide6.QtGui import QColor
    base = QColor(layer.color)
    assert (color.red(), color.green(), color.blue()) == (base.red(), base.green(), base.blue())
    assert color.alphaF() == pytest.approx(0.45, abs=0.01)


def test_each_angle_only_once_and_first_angle_skipped(qapp):
    doc = _doc(passes=4, hatch_angle=0.0, fill_angle_increment=90.0)
    fp = _editor(doc).fill_preview
    assert fp.pass_angles_shown() == [90.0]          # 0, 90, 0, 90
    doc.update_layer(doc.active_layer_id, passes=3, fill_angle_increment=45.0)
    fp.rebuild()
    assert fp.pass_angles_shown() == [45.0, 90.0]
    for _c, a, lines in fp.pass_lines:
        assert _segs(lines) == _geom(doc, doc.layers[0], a)


@pytest.mark.parametrize("layer", [
    dict(passes=2, fill_angle_increment=0.0),          # no step
    dict(passes=1, fill_angle_increment=90.0),         # one pass
    dict(passes=3, fill_angle_increment=-90.0, hatch_angle=0.0, fill_mode="offset"),
    dict(passes=2, fill_angle_increment=90.0, fill_mode="none"),
])
def test_no_further_passes_without_an_effective_step(qapp, layer):
    doc = _doc(**layer)
    fp = _editor(doc).fill_preview
    assert fp.pass_lines == [] and fp.pass_line_count() == 0


def test_first_pass_lines_unchanged_by_the_step(qapp):
    doc = _doc(passes=2, hatch_angle=30.0)
    fp = _editor(doc).fill_preview
    before = _segs(fp.lines[0][1])
    doc.update_layer(doc.active_layer_id, fill_angle_increment=60.0)
    fp.rebuild()
    assert _segs(fp.lines[0][1]) == before and fp.pass_angles_shown() == [90.0]


def test_crosshatch_further_pass_geometry(qapp):
    doc = _doc(passes=2, fill_mode="crosshatch", hatch_angle=0.0, fill_angle_increment=45.0)
    fp = _editor(doc).fill_preview
    (_c, a, lines), = fp.pass_lines
    assert a == 45.0 and _segs(lines) == _geom(doc, doc.layers[0], 45.0)
    assert _dirs(lines) == {45.0, 135.0}


def test_hidden_layer_and_switch(qapp):
    doc = _doc(passes=2, fill_angle_increment=90.0)
    fp = _editor(doc).fill_preview
    fp.show_all_passes = False
    fp.rebuild()
    assert fp.pass_lines == [] and fp.lines
    fp.show_all_passes = True
    fp.rebuild()
    assert fp.pass_angles_shown() == [90.0]
    doc.update_layer(doc.active_layer_id, visible=False)
    fp.rebuild()
    assert fp.pass_lines == [] and fp.lines == []


def test_several_layers_each_with_their_own_angles(qapp):
    from lumacut_canvas.model import Geometry, Layer, Shape
    doc = _doc(passes=2, fill_angle_increment=90.0)
    lid2 = doc.add_layer(Layer("B", color="#00aa00", fill_mode="hatch", line_interval_mm=2.0,
                               hatch_outline=False, passes=2, hatch_angle=0.0,
                               fill_angle_increment=45.0)).id
    doc.add_shape(Shape("rect", Geometry(60, 10, 20, 20), lid2))
    fp = _editor(doc).fill_preview
    assert sorted(fp.pass_angles_shown()) == [45.0, 90.0]


def test_document_change_updates_the_further_passes(qapp):
    doc = _doc(passes=2, fill_angle_increment=0.0)
    ed = _editor(doc)
    fp = ed.fill_preview
    assert fp.pass_lines == []
    doc.update_layer(doc.active_layer_id, fill_angle_increment=90.0)
    fp.rebuild()                                      # (debounced in the app)
    assert fp.pass_angles_shown() == [90.0]
    ed.grab()


def test_line_limit_counts_further_passes(qapp, monkeypatch):
    from lumacut_canvas import fill_preview
    doc = _doc(passes=2, fill_angle_increment=90.0)
    fp = _editor(doc).fill_preview
    n1 = fp.line_count()
    assert not fp.truncated and n1 > 0
    monkeypatch.setattr(fill_preview, "MAX_PREVIEW_LINES", n1 + 2)
    fp.rebuild()
    assert fp.truncated and fp.line_count() == n1 and fp.pass_line_count() == 0


def test_painted_vertical_lines_of_the_second_pass(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    doc = _doc(passes=2, hatch_angle=0.0, fill_angle_increment=90.0, line_interval_mm=2.0)
    doc.update_layer(doc.active_layer_id, color="#000000")
    fp = _editor(doc).fill_preview

    def render():
        img = QImage(400, 400, QImage.Format_ARGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.scale(10, 10)
        fp.paint(p, QRectF(0, 0, 40, 40))
        p.end()
        return img

    def dark_columns(img, y):
        return sum(img.pixelColor(x, y).lightness() < 230 for x in range(105, 295))
    img = render()
    row = next(y for y in range(105, 295)
               if all(img.pixelColor(x, y).lightness() > 100 for x in range(105, 295, 7)))
    assert dark_columns(img, row) >= 5               # vertical pass-2 lines cross the row
    fp.show_all_passes = False
    fp.rebuild()
    assert dark_columns(render(), row) == 0


def test_scan_offset_keeps_pass_one_shifted_and_adds_plain_passes(qapp):
    from lumacut_job.scan_offset import ScanOffsetTable, set_active_table
    doc = _doc(passes=2, hatch_angle=0.0, fill_angle_increment=90.0, speed=3000)
    set_active_table(ScanOffsetTable(True, [(3000, 0.4)]).normalized())
    fp = _editor(doc).fill_preview
    assert fp.scan_offset_applied
    (_c, a, lines), = fp.pass_lines
    assert a == 90.0 and _segs(lines) == _geom(doc, doc.layers[0], 90.0)


def test_gcode_untouched_by_the_preview_and_matches_pass_two(qapp):
    doc = _doc(passes=2, hatch_angle=0.0, fill_angle_increment=90.0)
    before = _gcode(doc)
    ed = _editor(doc)
    ed.fill_preview.show_all_passes = False
    ed.fill_preview.rebuild()
    assert _gcode(doc) == before
    pi_check(before)
    p = _passes(before)
    assert len(p) == 2
    n2 = len(p[1]["burns"])
    assert n2 > 0 and ed.fill_preview.pass_line_count() == 0
    ed.fill_preview.show_all_passes = True
    ed.fill_preview.rebuild()
    assert n2 == len(ed.fill_preview.pass_lines[0][2])


def test_panel_tooltip_mentions_the_canvas_passes(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel
    p = LayersPanel(_doc(), QUndoStack())
    tip = p.fill_angle_step.toolTip()
    assert "Angle Increment" in tip and "weiteren Durchgänge blasser" in tip
