"""Data Matrix ECC 200 generator: encodation, Reed-Solomon, placement, sizes, vectors, UI."""

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import datamatrix as dm  # noqa: E402


# --- encodation / RS -----------------------------------------------------------------
def test_iso_example_123456():
    # ISO/IEC 16022 Annex O example: "123456" in a 10×10 symbol.
    code = dm.encode("123456")
    assert code.size == 10
    assert code.codewords == (142, 164, 186, 114, 25, 5, 88, 102)


def test_ascii_encodation_digit_pairs_upper_shift_and_eci():
    assert dm.encode_ascii(b"A") == [66]
    assert dm.encode_ascii(b"0815") == [138, 145]
    assert dm.encode_ascii(b"12a3") == [142, 98, 52]       # odd digit stays single
    assert dm.encode_ascii("Ä".encode("latin-1")) == [235, 0xC4 - 127]
    assert dm.text_codewords("Ä") == [235, 69]               # ISO 8859-1, no ECI needed
    assert dm.text_codewords("€")[:2] == [241, 27]           # ECI 26 (UTF-8)


def test_pad_randomisation():
    assert dm.pad([66], 5) == [66, 129, 70, 220, 115]   # 129 + (149·pos mod 253) + 1, wrapped at 254
    assert dm.pad([1, 2, 3], 3) == [1, 2, 3]


def _poly_eval(cws, x):
    acc = 0
    for c in cws:
        acc = dm.gf_mul(acc, x) ^ c
    return acc


@pytest.mark.parametrize("size", dm.SIZES)
def test_reed_solomon_syndromes_zero(size):
    _r, _n, n_data, n_ecc, blocks = dm.SYMBOLS[size]
    data = dm.pad(dm.text_codewords("LumaCut 0815 " * 200)[: n_data - 1], n_data)
    cws = dm.interleave(size, data)
    assert len(cws) == n_data + n_ecc and cws[:n_data] == data
    per = n_ecc // blocks
    for b in range(blocks):
        block = cws[b:n_data:blocks] + cws[n_data + b::blocks]
        assert len(block) == len(cws[b:n_data:blocks]) + per
        for i in range(1, per + 1):
            assert _poly_eval(block, dm._EXP[i]) == 0, (size, b, i)


def test_capacity_and_size_choice():
    assert dm.choose_size(3) == 10 and dm.choose_size(4) == 12 and dm.choose_size(204) == 52
    assert dm.encode("1" * 6).size == 10 and dm.encode("1" * 7).size == 12
    assert dm.encode("A", 24).size == 24                     # minimum size honoured
    assert dm.capacity_digits(144) == 3116
    assert dm.encode("1" * 3116).size == 144
    with pytest.raises(ValueError, match="zu lang"):
        dm.encode("1" * 3117)
    with pytest.raises(ValueError, match="Kein Text"):
        dm.encode("")
    with pytest.raises(ValueError, match="Unbekannte"):
        dm.encode("A", 30)


@pytest.mark.parametrize("size", dm.SIZES)
def test_finder_and_timing_patterns(size):
    code = dm.encode("A", size)
    region, per, *_ = dm.SYMBOLS[size]
    step = region + 2
    m = code.modules
    assert len(m) == size and all(len(r) == size for r in m)
    for k in range(size):
        assert m[size - 1][k] and m[k][0]                   # solid L
        assert m[0][k] == (k % step % 2 == 0)              # dotted top edge
        assert m[k][size - 1] == (k % step % 2 == 1)       # dotted right edge
    for i in range(1, per):                                 # region separators
        assert all(m[i * step][k] == (k % step % 2 == 0) for k in range(size))
        assert all(m[i * step - 1][k] for k in range(size))


# --- reference / decoders --------------------------------------------------------------
def _module_image(code, px=6, quiet=2, invert=False):
    np = pytest.importorskip("numpy")
    n = code.size + 2 * quiet
    a = np.full((n * px, n * px), 255, np.uint8)
    for y in range(code.size):
        for x in range(code.size):
            if code.modules[y][x]:
                a[(y + quiet) * px:(y + quiet + 1) * px, (x + quiet) * px:(x + quiet + 1) * px] = 0
    return 255 - a if invert else a


def _zxing(img):
    zxingcpp = pytest.importorskip("zxingcpp")
    return [(r.text, r.format.name) for r in zxingcpp.read_barcodes(img)]


@pytest.mark.parametrize("size", dm.SIZES)
def test_every_size_decodes_with_zxing(size):
    n_data = dm.SYMBOLS[size][2]
    text = ""
    for ch in "LumaCut 0815 äöü " * 200:                    # fill to just below capacity
        if len(dm.text_codewords(text + ch)) > n_data - 2:
            break
        text += ch
    code = dm.encode(text, size)
    assert code.size == size
    assert _zxing(_module_image(code, px=4 if size > 60 else 6)) == [(text, "DataMatrix")]


@pytest.mark.parametrize("text", ["123456", "lumacut 2026", "0815" * 40, "1" * 1500,
                                  "7" * 3116])
def test_matches_zxing_writer(text):
    # For texts where ASCII encodation is optimal zxing-cpp's encoder produces the same
    # codewords, so the module matrices must be identical (incl. 6/10 interleaved blocks).
    zxingcpp = pytest.importorskip("zxingcpp")
    np = pytest.importorskip("numpy")
    try:
        ref = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.DataMatrix, force_square=True)
        img = np.array(zxingcpp.write_barcode_to_image(ref, scale=1, add_quiet_zones=False))
    except (AttributeError, TypeError):
        pytest.skip("zxing-cpp without writer API")
    ours = np.array(dm.encode(text).modules)
    assert img.shape == ours.shape
    assert ((img < 128) == ours).all()


def test_unicode_eci_decodes():
    text = "Preis 12 € – Größe ✓"
    assert _zxing(_module_image(dm.encode(text))) == [(text, "DataMatrix")]


def test_pylibdmtx_decodes():
    pylibdmtx = pytest.importorskip("pylibdmtx.pylibdmtx")
    np = pytest.importorskip("numpy")
    img = _module_image(dm.encode("LumaCut-2026-0815"), px=6)
    h, w = img.shape
    out = pylibdmtx.decode((np.ascontiguousarray(img).tobytes(), w, h))
    assert [r.data.decode() for r in out] == ["LumaCut-2026-0815"]


# --- vector shapes ---------------------------------------------------------------------
def _union(shapes):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from lumacut_canvas.shape_paths import shape_polygons
    polys = []
    for s in shapes:
        rings = shape_polygons(s)
        polys.append(Polygon(rings[0], rings[1:]))
    return unary_union(polys), polys


def _render(shapes, layer=None, px=10.0):
    """Black = lasered. With ``layer``: only the hatch lines of the layer."""
    import numpy as np
    from PySide6.QtCore import QLineF, QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

    from lumacut_canvas.export import shape_fill_segments
    from lumacut_canvas.shape_paths import shape_polygons
    union, _ = _union(shapes)
    x0, y0, x1, _y1 = union.bounds
    pad = 6.0
    w = int((x1 - x0 + 2 * pad) * px)
    img = QImage(w, w, QImage.Format_Grayscale8)
    img.fill(255)
    p = QPainter(img)
    ox, oy = x0 - pad, y0 - pad
    if layer is None:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0))
        for s in shapes:
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for poly in shape_polygons(s):
                path.moveTo(QPointF((poly[0][0] - ox) * px, (poly[0][1] - oy) * px))
                for x, y in poly[1:]:
                    path.lineTo(QPointF((x - ox) * px, (y - oy) * px))
                path.closeSubpath()
            p.drawPath(path)
    else:
        p.setPen(QPen(QColor(0, 0, 0), layer.line_interval_mm * px * 1.2, Qt.SolidLine, Qt.FlatCap))
        for s in shapes:
            for (ax, ay), (bx, by) in shape_fill_segments(s, layer):
                p.drawLine(QLineF((ax - ox) * px, (ay - oy) * px, (bx - ox) * px, (by - oy) * px))
    p.end()
    return np.frombuffer(img.constBits(), np.uint8).reshape(w, img.bytesPerLine())[:, :w].copy()


def test_shapes_geometry_group_and_area(qapp):
    spec = dm.DataMatrixSpec("LumaCut", size_mm=16.0, quiet_zone=2, x=10, y=20)
    code = dm.encode("LumaCut")
    shapes = dm.datamatrix_shapes(spec, "L1", code)
    assert shapes and all(s.kind == "polygon" and s.layer_id == "L1" for s in shapes)
    assert len({s.groups for s in shapes}) == 1 and shapes[0].groups
    union, polys = _union(shapes)
    module = 16.0 / code.size
    dark = sum(map(sum, code.modules))
    assert union.area == pytest.approx(dark * module ** 2, rel=1e-9)
    assert sum(p.area for p in polys) == pytest.approx(union.area, rel=1e-9)   # no overlaps
    x0, y0, x1, y1 = union.bounds
    assert (x0, y0) == pytest.approx((10 + 2 * module, 20 + 2 * module))
    assert (x1 - x0, y1 - y0) == pytest.approx((16.0, 16.0))
    inv = dm.datamatrix_shapes(replace(spec, invert=True), "L1", code)
    iu, _ = _union(inv)
    total = spec.total_mm(code)
    assert iu.bounds == pytest.approx((10, 20, 10 + total, 20 + total))
    assert iu.area == pytest.approx(total ** 2 - union.area, rel=1e-9)


def test_shape_errors():
    with pytest.raises(ValueError, match="zu klein"):
        dm.datamatrix_shapes(dm.DataMatrixSpec("1" * 3000, size_mm=20.0), "L1")
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        dm.datamatrix_shapes(dm.DataMatrixSpec("A", size_mm=50.0, x=WORK_WIDTH_MM - 20), "L1")
    with pytest.raises(ValueError, match="Kein Text"):
        dm.datamatrix_shapes(dm.DataMatrixSpec(""), "L1")
    assert dm.DataMatrixSpec(symbol=30).normalized().symbol == dm.AUTO
    assert dm.DataMatrixSpec(quiet_zone=99).normalized().quiet_zone == dm.QUIET_RANGE[1]


@pytest.mark.parametrize("text,symbol", [("LumaCut-2026-0815", 0), ("https://lumacut.example/ä", 0),
                                         ("0123456789" * 20, 52), ("Werkstatt", 32)])
def test_vector_shapes_decode(qapp, text, symbol):
    spec = dm.DataMatrixSpec(text, symbol=symbol, size_mm=30.0, quiet_zone=2, x=5, y=5)
    assert _zxing(_render(dm.datamatrix_shapes(spec, "L1"), px=8.0)) == [(text, "DataMatrix")]


def test_inverted_decodes_on_light_marking(qapp):
    np = pytest.importorskip("numpy")
    spec = dm.DataMatrixSpec("Eloxal 42", size_mm=15.0, quiet_zone=2, invert=True, x=5, y=5)
    img = 255 - _render(dm.datamatrix_shapes(spec, "L1"), px=8.0)   # laser turns light
    assert _zxing(np.pad(img, 60, constant_values=255)) == [("Eloxal 42", "DataMatrix")]


def test_hatch_fill_decodes(qapp):
    from lumacut_canvas.model import Layer
    layer = Layer("Data Matrix", fill_mode="hatch", line_interval_mm=0.1)
    spec = dm.DataMatrixSpec("LC-0815", size_mm=10.0, quiet_zone=2, x=5, y=5)
    assert _zxing(_render(dm.datamatrix_shapes(spec, "L1"), layer, px=20.0)) == [("LC-0815", "DataMatrix")]


# --- Qt: dialog and main window ----------------------------------------------------------
def test_dialog(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.datamatrix_qt import DataMatrixDialog
    dlg = DataMatrixDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert not dlg.fill_layer()
    dlg.text.setText("123456")
    assert dlg.ok_button.isEnabled() and "10 × 10" in dlg.info.text()
    dlg.symbol.setCurrentIndex(dlg.symbol.findData(24))
    assert dlg.spec().symbol == 24 and "24 × 24" in dlg.info.text()
    dlg.text.setText("x" * 100)
    assert "nächste passende" in dlg.info.text()
    dlg.text.setText("")
    assert not dlg.ok_button.isEnabled() and "Kein Text" in dlg.info.text()
    dlg.text.setText("1" * 3000)
    dlg.size_mm.setValue(10.0)
    assert not dlg.ok_button.isEnabled() and "zu klein" in dlg.info.text()
    dlg.text.setText("abc")
    dlg.symbol.setCurrentIndex(0)
    dlg.size_mm.setValue(330.0)
    assert not dlg.ok_button.isEnabled() and "Arbeitsfläche" in dlg.info.text()
    dlg.invert.setChecked(True)
    assert dlg.spec().invert
    dlg.deleteLater()
    dlg2 = DataMatrixDialog(active_layer=Layer("Kontur"))
    assert dlg2.fill_layer()
    dlg2.fill.setChecked(False)
    assert "nur Umrisse" in dlg2.info.text()
    dlg2.deleteLater()


@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_window_action_menus_shortcut_undo_and_gcode(win, monkeypatch):
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import QMessageBox

    from lumacut_canvas.commands import SetLayerAttrCommand
    from lumacut_job.planner import optimized_document_gcode
    tools = win.job_tools
    a = tools.datamatrix_action
    assert a.objectName() == "datamatrix_action" and a.text() == "Data Matrix…"
    assert a.shortcut() == QKeySequence("Alt+X")
    clash = [b.text() for b in win.findChildren(QAction)
             if b is not a and b.shortcut() == a.shortcut()]
    assert clash == []
    assert not any(m.text().replace("&&", "").lower().startswith("&x")
                   for m in win.menuBar().actions())                    # no Alt+X mnemonic
    assert a in win.main_view.design_menu.actions()
    assert a in win.main_view.job_menu.actions()
    doc = win.canvas.document
    layer = doc.active_layer
    win.canvas.undo_stack.push(SetLayerAttrCommand(doc, layer.id, "fill_mode", "hatch"))
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    depth = win.canvas.undo_stack.index()
    ids = tools.datamatrix(dm.DataMatrixSpec("LumaCut", size_mm=12.0))
    assert ids and len(doc.layers) == n_layers
    assert all(doc.shape(i).layer_id == layer.id for i in ids)
    assert len({doc.shape(i).groups for i in ids}) == 1
    assert sorted(win.canvas.selection) == sorted(ids)
    assert win.canvas.undo_stack.index() == depth + 1
    union, _ = _union([doc.shape(i) for i in ids])
    cx, cy = (union.bounds[0] + union.bounds[2]) / 2, (union.bounds[1] + union.bounds[3]) / 2
    assert cx == pytest.approx(WORK_WIDTH_MM / 2, abs=0.01)
    assert cy == pytest.approx(WORK_HEIGHT_MM / 2, abs=0.01)
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") > 50
    pi_check(gcode)
    win.canvas.undo_stack.undo()
    assert len(doc.shapes) == n_shapes and not any(doc.has_shape(i) for i in ids)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert tools.datamatrix(dm.DataMatrixSpec("1" * 4000, size_mm=20.0)) == []
    assert warned and len(doc.shapes) == n_shapes


def test_window_new_fill_layer_one_undo_step(win):
    tools = win.job_tools
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    ids = tools.datamatrix(dm.DataMatrixSpec("Werkstatt", size_mm=20.0, invert=True))
    assert len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == "Data Matrix" and new.fill_mode == "hatch" and new.line_interval_mm == 0.1
    win.canvas.undo_stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes
