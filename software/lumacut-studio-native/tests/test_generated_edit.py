"""Re-editable generated objects: QR code, barcode, Data Matrix, arc text (lumacut_job.generated)."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.model import Document, Geometry, Shape  # noqa: E402
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import generated  # noqa: E402
from lumacut_job import qr  # noqa: E402
from lumacut_job.arctext import ArcSpec  # noqa: E402
from lumacut_job.barcode import BarcodeSpec  # noqa: E402
from lumacut_job.datamatrix import DataMatrixSpec  # noqa: E402
from lumacut_job.qr import QrSpec  # noqa: E402


def _qr_doc(spec=QrSpec("https://lumacut.example", size_mm=30.0)):
    from lumacut_job.qr_qt import centered
    doc = Document()
    layer = doc.layers[0]
    s = centered(spec)
    shapes = generated.tag(qr.qr_shapes(s, layer.id), s)
    for sh in shapes:
        doc.add_shape(sh)
    return doc, shapes


def _center(shapes):
    x0, y0, x1, y1 = generated.extent(shapes)
    return (x0 + x1) / 2, (y0 + y1) / 2


# --- pure helpers ------------------------------------------------------------------------
def test_tag_meta_is_shared_json_and_round_trips():
    doc, shapes = _qr_doc()
    meta = shapes[0].generator
    assert all(sh.generator is meta for sh in shapes)
    assert meta["kind"] == "qr" and meta["version"] == generated.VERSION
    assert "x" not in meta["spec"] and "y" not in meta["spec"]
    x0, y0, x1, y1 = generated.extent(shapes)
    assert meta["box"] == [pytest.approx(x1 - x0), pytest.approx(y1 - y0)]
    spec = generated.spec_from_meta(meta)
    assert spec == QrSpec("https://lumacut.example", size_mm=30.0).normalized()
    # file / autosave round trip keeps the parameters on every part
    d = json.loads(json.dumps(doc.to_dict()))
    assert d["version"] == Document.VERSION_WITHOUT_IMAGES        # old app versions still open it
    doc2 = Document.from_dict(d)
    assert [s.generator for s in doc2.shapes] == [meta] * len(shapes)
    assert generated.find_unit(doc2, doc2.shapes[0].id).ids == [s.id for s in shapes]
    # plain objects do not get the key
    plain = Shape("rect", Geometry(10, 10, 5, 5), doc.layers[0].id)
    assert "generator" not in plain.to_dict() and Shape.from_dict(plain.to_dict()).generator is None


def test_spec_from_meta_errors_and_unknown_keys():
    with pytest.raises(ValueError, match="Unbekannt"):
        generated.spec_from_meta({"kind": "pdf417", "spec": {}})
    with pytest.raises(ValueError, match="neueren Version"):
        generated.spec_from_meta({"kind": "qr", "version": generated.VERSION + 1, "spec": {}})
    s = generated.spec_from_meta({"kind": "datamatrix", "version": 1,
                                  "spec": {"text": "A1", "size_mm": 9.0, "future_field": 3, "x": 50}})
    assert s == DataMatrixSpec("A1", size_mm=9.0)
    assert generated.spec_kind(ArcSpec()) == "arctext" and generated.spec_kind(BarcodeSpec()) == "barcode"
    with pytest.raises(TypeError):
        generated.spec_kind(object())


def test_scaled_spec():
    q = QrSpec("x", size_mm=20.0)
    assert generated.scaled_spec(q, (1.0005, 0.9999)) is q
    assert generated.scaled_spec(q, (1.5, 1.5)).size_mm == pytest.approx(30.0)
    assert generated.scaled_spec(DataMatrixSpec("x", size_mm=10.0), (2.0, 2.0)).size_mm == 20.0
    b = generated.scaled_spec(BarcodeSpec(module_mm=0.3, height_mm=15.0, text_mm=3.0), (2.0, 0.5))
    assert (b.module_mm, b.height_mm, b.text_mm) == pytest.approx((0.6, 7.5, 1.5))
    a = generated.scaled_spec(ArcSpec(radius_mm=40.0, height_mm=8.0, spacing_mm=1.0), (1.25, 1.25))
    assert (a.radius_mm, a.height_mm, a.spacing_mm) == pytest.approx((50.0, 10.0, 1.25))


def test_unit_frame_and_scale_after_move_rotate_resize():
    doc, shapes = _qr_doc()
    c0 = _center(shapes)
    w0 = generated.extent(shapes)[2] - generated.extent(shapes)[0]
    # user scales the group ×1.2 about its centre, rotates by 30° and moves it
    for sh in shapes:
        g = sh.geom
        cx, cy = g.center()
        g = Geometry(0, 0, g.w * 1.2, g.h * 1.2).with_center(c0[0] + (cx - c0[0]) * 1.2,
                                                            c0[1] + (cy - c0[1]) * 1.2)
        sh.geom = g.rotated(30.0, *c0).translated(-40.0, 25.0)
    u = generated.find_unit(doc, shapes[3].id)
    assert u.kind == "qr" and u.label == "QR-Code" and len(u.ids) == len(shapes)
    assert u.rot == pytest.approx(30.0) and u.scaled
    assert u.center == pytest.approx((c0[0] - 40.0, c0[1] + 25.0), abs=1e-6)
    assert u.size == pytest.approx((w0 * 1.2, w0 * 1.2), rel=1e-6)
    assert u.scale == pytest.approx((1.2, 1.2), rel=1e-6)
    # place() puts fresh shapes at that centre with that rotation
    from lumacut_job.generated_qt import build_shapes
    fresh = build_shapes(QrSpec("neu", size_mm=36.0), doc.layers[0].id)
    generated.place(fresh, u.center, u.rot)
    c, size = generated.unit_frame(fresh, 30.0)
    assert c == pytest.approx(u.center, abs=1e-6) and all(s.geom.rot == 30.0 for s in fresh)


def test_find_unit_none_mixed_and_individually_rotated():
    doc, shapes = _qr_doc()
    plain = Shape("rect", Geometry(10, 10, 5, 5), doc.layers[0].id)
    doc.add_shape(plain)
    assert generated.find_unit(doc, plain.id) is None
    assert generated.find_unit(doc, "missing") is None
    # foreign part inside the generator group (e.g. result of a boolean op)
    plain.groups = shapes[0].groups
    with pytest.raises(ValueError, match="kombiniert"):
        generated.find_unit(doc, shapes[0].id)
    plain.groups = ()
    shapes[1].geom = shapes[1].geom.rotated(10.0, *shapes[1].geom.center())
    with pytest.raises(ValueError, match="einzeln gedreht"):
        generated.find_unit(doc, shapes[0].id)
    shapes[1].geom.rot = 0.0
    # ungrouped: parts are plain polygons again
    for sh in shapes:
        sh.groups = ()
    assert generated.find_unit(doc, shapes[0].id) is None


# --- window ----------------------------------------------------------------------------
@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.canvas.document.active_layer.fill_mode = "hatch"
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _decode_shapes(shapes, px=8.0):
    """Render filled polygons (black = lasered) and decode with zxing-cpp."""
    np = pytest.importorskip("numpy")
    zxingcpp = pytest.importorskip("zxingcpp")
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QImage, QPainter, QPainterPath, QPolygonF

    from lumacut_canvas.shape_paths import shape_polygons
    rings_all = [shape_polygons(s) for s in shapes]
    pts = [p for rings in rings_all for r in rings for p in r]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    pad = 8.0
    w, h = int((x1 - x0 + 2 * pad) * px), int((y1 - y0 + 2 * pad) * px)
    img = QImage(w, h, QImage.Format_Grayscale8)
    img.fill(255)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.black)
    for rings in rings_all:
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for r in rings:
            path.addPolygon(QPolygonF([QPointF((x - x0 + pad) * px, (y - y0 + pad) * px) for x, y in r]))
            path.closeSubpath()
        p.drawPath(path)
    p.end()
    ptr = img.constBits()
    a = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine())[:, :w].copy()
    return [r.text for r in zxingcpp.read_barcodes(a)]


def test_action_shortcut_menus(win):
    from PySide6.QtGui import QAction, QKeySequence
    a = win.job_tools.edit_generated_action
    assert a.objectName() == "edit_generated_action" and a.text() == "Code bearbeiten…"
    assert a.shortcut() == QKeySequence("Alt+E")
    assert [b.text() for b in win.findChildren(QAction)
            if b is not a and b.shortcut() == a.shortcut()] == []
    assert not any(m.text().replace("&&", "").lower().startswith("&e")
                   for m in win.menuBar().actions())                    # no Alt+E mnemonic
    assert a in win.main_view.design_menu.actions() and a in win.main_view.job_menu.actions()
    assert win.canvas.generated_edit_handler == win.job_tools.edit_generated_at


def test_qr_edit_keeps_place_rotation_group_one_undo_step(win):
    from lumacut_canvas.commands import SetGeometryCommand
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    ids = tools.qr_code(QrSpec("https://alt.example", size_mm=30.0))
    group = doc.shape(ids[0]).groups[-1]
    # user rotates the code by 30° and moves it
    old = {i: doc.shape(i).geom.copy() for i in ids}
    c0 = _center([doc.shape(i) for i in ids])
    new = {i: g.rotated(30.0, *c0).translated(-50.0, 20.0) for i, g in old.items()}
    stack.push(SetGeometryCommand(doc, old, new, "Drehen"))
    unit = generated.find_unit(doc, ids[0])
    depth = stack.index()
    win.canvas.set_selection(ids)
    from lumacut_job.generated_qt import unit_spec
    spec = unit_spec(unit)
    assert spec.text == "https://alt.example" and spec.size_mm == pytest.approx(30.0)
    new_ids = tools.edit_generated(replace(spec, text="https://neu.example/werkstatt", ec="Q"))
    assert new_ids and not any(doc.has_shape(i) for i in ids)
    assert stack.index() == depth + 1
    parts = [doc.shape(i) for i in new_ids]
    assert {p.groups for p in parts} == {(group,)}
    assert all(p.geom.rot == pytest.approx(30.0) for p in parts)
    assert all(p.layer_id == doc.active_layer.id for p in parts)
    u2 = generated.find_unit(doc, new_ids[0])
    assert u2.center == pytest.approx(unit.center, abs=1e-6) and not u2.scaled
    assert generated.spec_from_meta(u2.meta).text == "https://neu.example/werkstatt"
    assert sorted(win.canvas.selection) == sorted(new_ids)
    assert _decode_shapes(parts) == ["https://neu.example/werkstatt"]
    pi_check(__import__("lumacut_job.planner", fromlist=["x"]).optimized_document_gcode(doc))
    stack.undo()
    assert all(doc.has_shape(i) for i in ids) and not any(doc.has_shape(i) for i in new_ids)
    assert doc.shape(ids[0]).geom.rot == pytest.approx(30.0)


def test_resized_datamatrix_prefills_scaled_size(win):
    from lumacut_canvas.commands import SetGeometryCommand
    from lumacut_canvas.model import Rect
    from lumacut_job.generated_qt import generated_unit, unit_spec
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    ids = tools.datamatrix(DataMatrixSpec("LC-0815", size_mm=12.0))
    win.canvas.set_selection(ids)
    ob = doc.selection_bounds(ids)
    nb = Rect(ob.x, ob.y, ob.w * 1.5, ob.h * 1.5)
    old = {i: doc.shape(i).geom.copy() for i in ids}
    stack.push(SetGeometryCommand(doc, old, {i: g.mapped(ob, nb) for i, g in old.items()}, "Maße"))
    unit = generated_unit(win.canvas)
    assert unit.scale == pytest.approx((1.5, 1.5), rel=1e-6)
    spec = unit_spec(unit)
    assert spec.size_mm == pytest.approx(18.0) and spec.text == "LC-0815"
    new_ids = tools.edit_generated(replace(spec, text="LC-0816"))
    u2 = generated.find_unit(doc, new_ids[0])
    assert u2.size == pytest.approx(unit.size, abs=0.01) and not u2.scaled
    assert u2.center == pytest.approx(unit.center, abs=1e-6)
    assert _decode_shapes([doc.shape(i) for i in new_ids]) == ["LC-0816"]


def test_barcode_and_arc_text_edit(win):
    from lumacut_job.planner import optimized_document_gcode
    tools, doc = win.job_tools, win.canvas.document
    ids = tools.barcode(BarcodeSpec("code128", "LUMA-1", module_mm=0.4, height_mm=12.0))
    c = _center([doc.shape(i) for i in ids])
    win.canvas.set_selection(ids[:1])                 # one part is enough
    new_ids = tools.edit_generated(BarcodeSpec("ean13", "400638133393", module_mm=0.4, height_mm=12.0))
    parts = [doc.shape(i) for i in new_ids]
    assert _center(parts) == pytest.approx(c, abs=1e-6)
    assert generated.find_unit(doc, new_ids[0]).meta["spec"]["symbology"] == "ean13"
    assert "4006381333931" in _decode_shapes(parts)
    arc = tools.arc_text(ArcSpec(text="Werkstatt", radius_mm=30.0, height_mm=6.0))
    win.canvas.set_selection(arc)
    spec = generated.spec_from_meta(doc.shape(arc[0]).generator)
    assert spec.text == "Werkstatt" and spec.radius_mm == 30.0
    arc2 = tools.edit_generated(replace(spec, text="Werkstatt 2026", bottom=True, angle_deg=None))
    assert len(arc2) == 13 and generated.spec_from_meta(doc.shape(arc2[0]).generator).bottom
    assert not any(doc.has_shape(i) for i in arc)
    pi_check(optimized_document_gcode(doc))


def test_copy_paste_and_outer_group_and_kind_guard(win):
    tools, doc, ed = win.job_tools, win.canvas.document, win.canvas
    ids = tools.qr_code(QrSpec("original", size_mm=25.0))
    ed.set_selection(ids)
    ed.copy_selection()
    ed.paste()
    copy_ids = list(ed.selection)
    assert generated.find_unit(doc, copy_ids[0]).group != generated.find_unit(doc, ids[0]).group
    new_copy = tools.edit_generated(QrSpec("kopie", size_mm=25.0))
    assert all(doc.has_shape(i) for i in ids)                    # original untouched
    assert generated.spec_from_meta(doc.shape(new_copy[0]).generator).text == "kopie"
    # group the original with a rectangle: the outer group survives the edit
    rect = Shape("rect", Geometry(20, 20, 10, 10), doc.active_layer.id)
    from lumacut_canvas.commands import AddShapesCommand
    ed.undo_stack.push(AddShapesCommand(doc, [rect]))
    ed.set_selection(ids + [rect.id])
    ed.group_selection()
    outer = doc.shape(rect.id).groups
    assert len(outer) == 1 and doc.shape(ids[0]).groups[0] == outer[0]
    ed.set_selection(ids + [rect.id])
    edited = tools.edit_generated(QrSpec("original v2", size_mm=25.0))
    assert all(doc.shape(i).groups[0] == outer[0] and len(doc.shape(i).groups) == 2 for i in edited)
    assert doc.has_shape(rect.id) and doc.shape(rect.id).groups == outer
    with pytest.raises(ValueError, match="Objektart"):
        from lumacut_job.generated_qt import replace_unit
        replace_unit(ed, generated.find_unit(doc, edited[0]), DataMatrixSpec("x"))


def test_messages_locked_layer_and_two_codes(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    tools, doc, ed = win.job_tools, win.canvas.document, win.canvas
    msgs = []
    monkeypatch.setattr(tools, "_msg", lambda text, ms=8000: msgs.append(text))
    ed.set_selection([])
    assert tools.edit_generated() == [] and "auswählen" in msgs[-1]
    a = tools.qr_code(QrSpec("a", size_mm=20.0))
    b = tools.datamatrix(DataMatrixSpec("b", size_mm=10.0))
    ed.set_selection(a + b)
    assert tools.edit_generated() == [] and "nur ein" in msgs[-1]
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *x, **k: warned.append(x[2]))
    doc.active_layer.locked = True
    n = len(doc.shapes)
    # locked shapes cannot be selected; programmatic edit by id is refused
    assert tools.edit_generated(QrSpec("neu", size_mm=20.0), shape_id=a[0]) == []
    assert warned and "gesperrt" in warned[-1] and len(doc.shapes) == n and all(doc.has_shape(i) for i in a)
    doc.active_layer.locked = False
    ed.set_selection(a)
    assert tools.edit_generated(QrSpec("x" * 3000, size_mm=20.0)) == [] and len(warned) == 2      # too long → warning
    assert all(doc.has_shape(i) for i in a)


def test_edit_dialogs_prefilled_in_edit_mode(win):
    from lumacut_job.generated_qt import edit_dialog, unit_spec
    tools, doc = win.job_tools, win.canvas.document
    cases = [tools.qr_code(QrSpec("q", ec="H", size_mm=22.0, invert=True)),
             tools.barcode(BarcodeSpec("ean8", "9638507", module_mm=0.5, show_text=False)),
             tools.datamatrix(DataMatrixSpec("d", symbol=16, size_mm=11.0)),
             tools.arc_text(ArcSpec(text="Bogen", radius_mm=25.0, height_mm=5.0, bottom=True))]
    for ids in cases:
        unit = generated.find_unit(doc, ids[0])
        spec = unit_spec(unit)
        dlg = edit_dialog(unit, spec, doc.layer(unit.layer_id), win)
        assert dlg.windowTitle().endswith("bearbeiten") and dlg.ok_button.text() == "Übernehmen"
        got = dlg.spec()
        if hasattr(spec, "font_family"):       # the font combo falls back to an installed family
            got = replace(got, font_family=spec.font_family)
        assert got == spec
        fill = getattr(dlg, "fill", None)
        assert fill is None or (fill.isHidden() and not dlg.fill_layer())
        if unit.kind == "arctext":
            assert not dlg.replace_source()
        dlg.deleteLater()


def test_double_click_opens_editor_and_plain_shapes_fall_through(win, monkeypatch):
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QDialog

    import lumacut_job.generated_qt as gq
    tools, doc, ed = win.job_tools, win.canvas.document, win.canvas
    ids = tools.qr_code(QrSpec("doppelklick", size_mm=40.0, invert=True))   # inverted: solid border
    shown = []

    class FakeDialog:
        def __init__(self, unit, spec, layer, parent=None):
            shown.append(spec)

        def exec(self):
            return QDialog.Accepted

        def spec(self):
            return replace(shown[-1], text="geändert")

    monkeypatch.setattr(gq, "edit_dialog", FakeDialog)
    ed.set_selection([])
    b = doc.shape(ids[0]).bounds()             # the outer border ring of the inverted code
    ed.tools.double_click(QPointF(b.x + 0.3, b.y + b.h / 2))
    assert shown and shown[0].text == "doppelklick"
    new = [s for s in doc.shapes if s.generator and s.generator["spec"]["text"] == "geändert"]
    assert new and not any(doc.has_shape(i) for i in ids)
    # a plain object still gets no generator dialog
    called = []
    monkeypatch.setattr(tools, "edit_generated", lambda **k: called.append(k))
    rect = Shape("rect", Geometry(10, 10, 20, 20), doc.active_layer.id)
    from lumacut_canvas.commands import AddShapesCommand
    ed.undo_stack.push(AddShapesCommand(doc, [rect]))
    ed.tools.double_click(QPointF(10.2, 20))
    assert called == []
    assert tools.edit_generated_at(rect.id) is False


def test_arc_text_replacing_grouped_text_keeps_own_group_innermost(win):
    from lumacut_canvas.commands import AddShapesCommand
    tools, doc, ed = win.job_tools, win.canvas.document, win.canvas
    t = Shape("text", Geometry(100, 100, 40, 10), doc.active_layer.id, text="Gruppe")
    r = Shape("rect", Geometry(100, 130, 10, 10), doc.active_layer.id)
    ed.undo_stack.push(AddShapesCommand(doc, [t, r]))
    ed.set_selection([t.id, r.id])
    ed.group_selection()
    outer = doc.shape(t.id).groups
    from lumacut_job.arctext_qt import insert_arc_text
    ids = insert_arc_text(ed, ArcSpec(text="Gruppe", radius_mm=30.0), t.id)
    assert not doc.has_shape(t.id)
    assert all(doc.shape(i).groups[:1] == outer and len(doc.shape(i).groups) == 2 for i in ids)
    unit = generated.find_unit(doc, ids[0])
    assert unit.outer == outer and sorted(unit.ids) == sorted(ids)


def test_work_area_centre_default():
    # build_shapes centres in the work area before place() moves the group
    from lumacut_job.generated_qt import build_shapes
    shapes = build_shapes(DataMatrixSpec("abc", size_mm=10.0), "L")
    assert _center(shapes) == pytest.approx((WORK_WIDTH_MM / 2, WORK_HEIGHT_MM / 2), abs=1e-6)
    assert all(s.generator["kind"] == "datamatrix" for s in shapes)
