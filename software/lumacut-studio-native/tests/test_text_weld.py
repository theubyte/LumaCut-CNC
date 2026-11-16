"""Text verschweißen (LightBurn *Text › Weld*): überlappende Buchstaben eines Textobjekts
zu einem Umriss vereinigen – Modell, Datei, Umriss, Füllung, G-Code, Folgefunktionen,
Bedienung."""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import unary_union

from lumacut_canvas import text_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.pathops import shape_area, text_to_outline
from lumacut_canvas.shape_paths import (WELD_TOL_MM, local_path, shape_path, shape_polygons,
                                        shape_text_path, text_path, weld_path)

FAMILY = "DejaVu Sans"


def _real_fonts(qapp):
    r = text_path("Il", FAMILY).boundingRect()
    w = text_path("WW", FAMILY).boundingRect()
    if w.width() <= r.width() * 1.05:
        pytest.skip("Keine echten Schriften auf diesem System (Ersatzkästen statt Glyphen)")


def _text(text="oo", **kw):
    kw.setdefault("letter_spacing", -20.0)
    return Shape("text", Geometry(20, 30, 40, 20), "L1", text=text, font_family=FAMILY, **kw)


def _elements(path):
    return [(e.type, round(e.x, 9), round(e.y, 9)) for e in
            (path.elementAt(i) for i in range(path.elementCount()))]


def _rings(shape):
    return [p for p in shape_polygons(shape) if len(p) >= 3]


def _eo_area(rings):
    a = Polygon()
    for r in rings:
        a = a.symmetric_difference(Polygon(r).buffer(0))
    return a


def _boundary(rings):
    return MultiLineString([LineString(r) for r in rings])


# --- Modell und Datei ------------------------------------------------------------------------

def test_default_is_off_and_not_saved():
    s = Shape("text", Geometry(0, 0, 10, 5), "L1", text="A")
    assert s.text_weld is False and "weld" not in s.to_dict()
    assert Shape.from_dict(s.to_dict()).text_weld is False


def test_saved_only_when_set_and_round_trip():
    s = Shape("text", Geometry(0, 0, 10, 5), "L1", text="A", text_weld=True)
    d = s.to_dict()
    assert d["weld"] is True
    back = Shape.from_dict(json.loads(json.dumps(d)))
    assert back.text_weld is True and back.to_dict() == d


def test_old_file_saves_identically():
    d = {"id": "t1", "kind": "text", "layer": "L1", "x": 1.0, "y": 2.0, "w": 30.0, "h": 8.0,
         "text": "Anna", "font": FAMILY}
    assert Shape.from_dict(d).to_dict() == d


@pytest.mark.parametrize("raw", ["true", 1, "1", "yes", None, [], {}, 0, False, 1.0])
def test_broken_values_load_as_off(raw):
    d = {"kind": "text", "layer": "L1", "x": 0, "y": 0, "w": 10, "h": 5, "text": "A", "weld": raw}
    assert Shape.from_dict(d).text_weld is False


@pytest.mark.parametrize("kind", ["rect", "ellipse", "line"])
def test_ignored_on_other_kinds(kind):
    d = {"kind": kind, "layer": "L1", "x": 0, "y": 0, "w": 10, "h": 5, "weld": True}
    s = Shape.from_dict(d)
    assert s.text_weld is False and "weld" not in s.to_dict()


def test_copy_keeps_the_flag():
    s = Shape("text", Geometry(0, 0, 10, 5), "L1", text="A", text_weld=True)
    assert s.copy(new_identity=True).text_weld is True


# --- Umriss ----------------------------------------------------------------------------------

def test_outline_without_weld_is_the_scaled_text_path(qapp):
    s = _text()
    src = shape_text_path(s)
    r = src.boundingRect()
    t = QTransform()
    t.translate(s.geom.x, s.geom.y)
    t.scale(s.geom.w / r.width(), s.geom.h / r.height())
    t.translate(-r.x(), -r.y())
    assert _elements(local_path(s)) == _elements(t.map(src))


def test_weld_path_merges_overlapping_squares(qapp):
    p = QPainterPath()
    p.addRect(QRectF(0, 0, 10, 10))
    p.addRect(QRectF(5, 5, 10, 10))
    w = weld_path(p)
    polys = w.toSubpathPolygons()
    assert len(polys) == 1
    assert Polygon([(q.x(), q.y()) for q in polys[0]]).area == pytest.approx(175.0, abs=1e-6)
    assert weld_path(QPainterPath()).isEmpty()


def test_weld_path_keeps_holes_and_separate_parts(qapp):
    p = QPainterPath()
    p.addRect(QRectF(0, 0, 10, 10))
    hole = QPainterPath()             # Loch gegenläufig wie in Schriften
    hole.moveTo(3, 3); hole.lineTo(3, 7); hole.lineTo(7, 7); hole.lineTo(7, 3); hole.closeSubpath()
    p.addPath(hole)
    p.addRect(QRectF(20, 0, 5, 5))
    polys = weld_path(p).toSubpathPolygons()
    assert len(polys) == 3
    area = _eo_area([[(q.x(), q.y()) for q in poly] for poly in polys]).area
    assert area == pytest.approx(100 - 16 + 25, abs=1e-6)


def test_overlapping_letters_become_one_outline(qapp):
    _real_fonts(qapp)
    plain = _text()
    welded = _text(text_weld=True)
    rp, rw = _rings(plain), _rings(welded)
    assert len(rp) == 4                    # zwei „o“ mit je einem Loch
    assert len(rw) == 3                    # ein Außenumriss, beide Löcher bleiben
    first, second = _eo_area(rp[:2]), _eo_area(rp[2:])
    assert first.intersects(second) and first.intersection(second).area > 1.0
    union = unary_union([first, second])
    a = shape_area(welded)
    assert shape_area(plain).geom_type == "MultiPolygon" and a.geom_type == "Polygon"
    assert len(a.interiors) == 2
    assert a.is_valid and a.area == pytest.approx(union.area, rel=2e-3)
    assert a.area > shape_area(plain).area + 1.0      # Überlappung wird mitgefüllt
    assert a.symmetric_difference(union).area < union.length * 2 * WELD_TOL_MM


def test_welded_outline_is_exact_where_nothing_overlaps(qapp):
    _real_fonts(qapp)
    plain = _text("Hallo ABO", letter_spacing=0.0)
    welded = _text("Hallo ABO", letter_spacing=0.0, text_weld=True)
    rp, rw = _rings(plain), _rings(welded)
    assert len(rw) == len(rp)
    d = _boundary(rw).hausdorff_distance(_boundary(rp))
    assert d <= WELD_TOL_MM
    assert shape_area(welded).area == pytest.approx(shape_area(plain).area, rel=1e-3)


def test_welded_outline_has_no_point_flood(qapp):
    _real_fonts(qapp)
    kw = dict(text="Lorem ipsum dolor\nsit amet", letter_spacing=0.0)
    n_plain = sum(len(p) for p in _rings(_text(**kw)))
    n_weld = sum(len(p) for p in _rings(_text(text_weld=True, **kw)))
    assert n_weld <= 2.5 * n_plain       # Qt's dense flattening thinned out


def test_weld_keeps_the_box(qapp):
    _real_fonts(qapp)
    s = _text(text_weld=True)
    r = shape_path(s).boundingRect()
    g = s.geom
    assert (r.x(), r.y(), r.width(), r.height()) == pytest.approx((g.x, g.y, g.w, g.h), abs=0.02)


def test_rotated_and_mirrored_text_welds_the_same(qapp):
    _real_fonts(qapp)
    base = shape_area(_text(text_weld=True)).area
    rot = _text(text_weld=True)
    rot.geom.rot = 37.0
    mir = _text(text_weld=True)
    mir.geom.x, mir.geom.w = 60.0, -40.0
    for s in (rot, mir):
        assert len(_rings(s)) == 3
        assert shape_area(s).area == pytest.approx(base, rel=2e-3)


def test_overlapping_lines_weld_too(qapp):
    _real_fonts(qapp)
    kw = dict(text="ll\nll", letter_spacing=0.0, line_spacing=50.0)
    plain, welded = _text(**kw), _text(text_weld=True, **kw)
    assert len(_rings(welded)) < len(_rings(plain))
    assert shape_area(welded).area > shape_area(plain).area


def test_blank_text_with_weld(qapp):
    s = _text(" ", text_weld=True)
    assert isinstance(local_path(s), QPainterPath)


# --- Folgefunktionen -------------------------------------------------------------------------

def _doc_with(s):
    doc = Document()
    s.layer_id = doc.active_layer_id
    doc.add_shape(s)
    return doc


def test_job_polylines_follow_the_weld(qapp):
    _real_fonts(qapp)
    from lumacut_canvas.export import job_layers
    plain = [len(jl.polylines) for jl in job_layers(_doc_with(_text()))]
    welded = [len(jl.polylines) for jl in job_layers(_doc_with(_text(text_weld=True)))]
    assert sum(welded) == sum(plain) - 1


def test_document_gcode_unchanged_without_weld(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc = _doc_with(_text())
    g0 = document_to_gcode(doc)
    doc2 = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert "weld" not in json.dumps(doc.to_dict())
    assert document_to_gcode(doc2) == g0
    doc2.shapes[0].text_weld = True
    assert document_to_gcode(doc2) != g0


def test_fill_covers_the_overlap(qapp):
    _real_fonts(qapp)
    from lumacut_canvas.hatch import hatch_lines
    plain, welded = _text(), _text(text_weld=True)
    lp = hatch_lines(_rings(plain), 0.2)
    lw = hatch_lines(_rings(welded), 0.2)
    total = lambda ls: sum(LineString(seg).length for seg in ls)    # noqa: E731
    assert total(lw) > total(lp)


def test_text_to_path_keeps_the_welded_outline(qapp):
    _real_fonts(qapp)
    s = _text(text_weld=True)
    out = text_to_outline(s)
    assert len(out.ring_ranges()) == 3
    assert shape_area(out).area == pytest.approx(shape_area(s).area, rel=1e-3)


def test_serial_numbers_keep_the_weld(qapp):
    from lumacut_job.serial import SerialSpec, serial_shapes
    from lumacut_canvas.shape_paths import text_aspect
    src = _text("Nr 1", text_weld=True)
    shapes = serial_shapes(src, SerialSpec("Nr {n}", start=1, count=2, columns=2), text_aspect)
    assert shapes and all(sh.text_weld for sh in shapes)


def test_svg_export_uses_the_welded_outline(qapp, tmp_path):
    _real_fonts(qapp)
    from lumacut_canvas.export import export_svg
    a, b = tmp_path / "a.svg", tmp_path / "b.svg"
    export_svg(_doc_with(_text()), a)
    export_svg(_doc_with(_text(text_weld=True)), b)
    assert a.read_text() != b.read_text()


# --- Bedienung -------------------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1400, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, text="oo", **kw):
    s = Shape("text", Geometry(20, 20, 40, 14), ed.document.active_layer_id, text=text,
              font_family=FAMILY, **kw)
    ed.document.add_shape(s)
    ed.set_selection([s.id])
    return ed.document.shape(s.id)


def test_with_weld_keeps_box_and_style(qapp):
    s = _text(font_bold=True, text_align="center")
    o = text_ui.with_weld(s, True)
    assert o.text_weld and not s.text_weld
    assert (o.geom.x, o.geom.y, o.geom.w, o.geom.h) == (s.geom.x, s.geom.y, s.geom.w, s.geom.h)
    assert (o.font_bold, o.text_align, o.letter_spacing) == (True, "center", -20.0)
    assert text_ui.with_weld(o, False).text_weld is False


def test_button_toggles_in_one_undo_step(ed):
    bar = ed.property_bar.text_style
    t = _add(ed)
    bar.refresh()
    assert bar.weld.isCheckable() and not bar.weld.isChecked() and bar.weld.isEnabled()
    n0 = ed.undo_stack.count()
    g0 = t.geom.copy()
    bar.weld.click()
    s = ed.document.shape(t.id)
    assert s.text_weld and ed.undo_stack.count() == n0 + 1
    assert ed.undo_stack.undoText() == "Verschweißen"
    assert (s.geom.x, s.geom.y, s.geom.w, s.geom.h) == (g0.x, g0.y, g0.w, g0.h)
    bar.refresh()
    assert bar.weld.isChecked()
    bar.weld.click()
    assert not ed.document.shape(t.id).text_weld
    assert ed.undo_stack.undoText() == "Verschweißen aus"
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert not ed.document.shape(t.id).text_weld


def test_button_applies_to_the_whole_selection(ed):
    bar = ed.property_bar.text_style
    a = _add(ed, "AB")
    b = _add(ed, "CD", text_weld=True)
    ed.set_selection([a.id, b.id])
    bar.refresh()
    assert not bar.weld.isChecked()                 # gemischt
    n0 = ed.undo_stack.count()
    bar.weld.click()
    assert all(ed.document.shape(i).text_weld for i in (a.id, b.id))
    assert ed.undo_stack.count() == n0 + 1          # nur „a“ geändert, ein Schritt
    ed.undo_stack.undo()
    assert not ed.document.shape(a.id).text_weld and ed.document.shape(b.id).text_weld


def test_refresh_does_not_push(ed):
    bar = ed.property_bar.text_style
    _add(ed, text_weld=True)
    n0 = ed.undo_stack.count()
    bar.refresh()
    assert bar.weld.isChecked() and ed.undo_stack.count() == n0


def test_locked_layer_text_is_not_changed(ed):
    t = _add(ed)
    ed.document.layer(t.layer_id).locked = True
    bar = ed.property_bar.text_style
    n0 = ed.undo_stack.count()
    bar._weld_toggled(True)
    assert ed.undo_stack.count() == n0 and not ed.document.shape(t.id).text_weld


def test_canvas_item_shows_the_welded_outline(ed, qapp):
    _real_fonts(qapp)
    t = _add(ed, letter_spacing=-20.0)
    ed.property_bar.text_style.refresh()
    ed.property_bar.text_style.weld.click()
    qapp.processEvents()
    item = next(i for i in ed.scene.items() if getattr(i, "shape_id", None) == t.id)
    assert len(item._path.toSubpathPolygons()) == 3


def test_touch_mode_size(ed, qapp):
    bar = ed.property_bar.text_style
    _add(ed)
    bar.refresh()
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    try:
        assert bar.weld.sizeHint().height() >= 40 and bar.weld.sizeHint().width() >= 40
    finally:
        ed.set_touch_mode(False, persist=False)


def test_icon_and_tooltip():
    from lumacut_canvas import icons
    assert "text_weld" in icons.available() and not icons.icon("text_weld").isNull()
    assert "Weld" in text_ui.TIP_WELD and "verschweißen" in text_ui.TIP_WELD


def test_save_load_keeps_weld(ed, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    t = _add(ed, text_weld=True)
    p = save_document(ed.document, tmp_path / "t.lcut")
    doc = Document()
    load_into(doc, p)
    assert doc.shape(t.id).text_weld is True


def test_main_window_has_the_button(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    ed = win.canvas
    t = _add(ed)
    bar = ed.property_bar.text_style
    bar.refresh()
    bar.weld.click()
    assert ed.document.shape(t.id).text_weld
    ed.undo_stack.setClean()
    win.close()
