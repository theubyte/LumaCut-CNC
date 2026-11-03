"""PDF417 generator (ISO/IEC 15438): compaction, Reed-Solomon, layout, sizes, vectors, UI."""

import json
import random
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import pdf417 as pd  # noqa: E402


# --- codeword tables ----------------------------------------------------------------------
def test_codeword_tables_follow_the_cluster_rule():
    for cluster in range(3):
        pats = [pd.pattern(cluster, cw) for cw in range(929)]
        assert len(set(pats)) == 929
        for p in pats:
            w = pd.widths(p)
            assert len(w) == 8 and sum(w) == 17 and max(w) <= 6 and p >> 16 == 1
            assert (w[0] - w[2] + w[4] - w[6] + 9) % 9 == 3 * cluster
    assert pd.widths(pd.START_PATTERN) == [8, 1, 1, 1, 1, 1, 1, 3]
    assert pd.widths(pd.STOP_PATTERN, 18) == [7, 1, 1, 3, 1, 1, 1, 2, 1]
    assert pd.widths(pd.pattern(0, 0)) == [3, 1, 1, 1, 1, 1, 3, 6]      # ISO table, cluster 0


# --- high-level encodation ----------------------------------------------------------------
def test_text_compaction_submodes():
    # Alpha is the start submode: two values per codeword, odd count padded with PS (29)
    assert pd.encode_data("AB") == [0 * 30 + 1]
    assert pd.encode_data("ABC") == [1, 2 * 30 + 29]
    assert pd.encode_data("A B") == [0 * 30 + 26, 1 * 30 + 29]
    # LL (27) to lower case, AS (27) shifts one capital inside lower case
    vals, sub = pd.text_values(b"abCd")
    assert vals == [27, 0, 1, 27, 2, 3] and sub == pd.LOWER
    # ML (28) for digits, PS (29) for a single punctuation character
    assert pd.text_values(b"A1")[0] == [0, 28, 1]
    assert pd.text_values(b"A!")[0] == [0, 29, 10]
    # many punctuation characters: ML PL latch
    vals, sub = pd.text_values(b"!?!?")
    assert vals[:2] == [28, 25] and sub == pd.PUNCT and len(vals) == 6
    # Lower → Alpha needs ML AL; from Punct back with AL (29)
    assert pd.text_values(b"aBC")[0] == [27, 0, 28, 28, 1, 2]
    assert pd.text_values(b"\n\nA", pd.PUNCT)[0] == [15, 15, 29, 0]


def test_numeric_and_byte_compaction():
    # ISO example: "000213298174000" → 902, 1, 624, 434, 632, 282, 200
    assert pd.numeric_codewords(b"000213298174000") == [1, 624, 434, 632, 282, 200]
    assert len(pd.numeric_codewords(b"1" * 44)) == 15
    assert len(pd.numeric_codewords(b"1" * 45)) == 15 + 1
    # 6 bytes → 5 codewords base 900, the rest one byte per codeword
    assert pd.byte_codewords(b"alcool") == [163, 238, 432, 766, 244]
    assert pd.byte_codewords(b"\x00\xff") == [0, 255]
    assert pd.encode_data("0123456789012") == [902] + pd.numeric_codewords(b"0123456789012")
    assert pd.encode_data("012345678901")[0] != 902                    # 12 digits stay text
    assert pd.encode_data("\x00" * 6) == [924] + pd.byte_codewords(b"\x00" * 6)
    assert pd.encode_data("\x00" * 7)[0] == 901
    # one byte inside text: Byte Shift 913, submode is kept (no latch back)
    words = pd.encode_data("ab\x00cdefg")
    assert pd.SHIFT_BYTE in words and pd.LATCH_TEXT not in words


def test_segments_and_eci():
    segs = pd.segments(b"Order 4006381333931 \x01\x02\x03\x04 done")
    assert [k for k, _ in segs] == ["text", "numeric", "byte", "text"]   # short text → byte
    assert segs[1][1] == b"4006381333931"
    words = pd.encode_data("Größe")
    assert words[:2] == [pd.ECI_CHARSET, pd.UTF8_ECI]
    assert pd.encode_data("Grosse")[0] != pd.ECI_CHARSET
    with pytest.raises(ValueError, match="Kein Text"):
        pd.encode_data("")


def test_compaction_beats_plain_byte_mode():
    random.seed(15438)
    for _ in range(40):
        text = "".join(random.choice("ABCabc 0123456789.,:;!?@_~-/\r\n") for _ in range(
            random.randint(1, 200)))
        data = text.encode()
        plain = 1 + len(data) // 6 * 5 + len(data) % 6            # everything as bytes
        assert len(pd.encode_data(text)) <= plain + 1
    assert len(pd.encode_data("1" * 300)) < 300 / 2.9 + 2


# --- Reed-Solomon ----------------------------------------------------------------------
def _poly_eval(words, x):
    acc = 0
    for c in words:
        acc = (acc * x + c) % pd.GF
    return acc


@pytest.mark.parametrize("level", pd.ECC_LEVELS)
def test_reed_solomon_roots(level):
    random.seed(level)
    data = [random.randrange(929) for _ in range(30)]
    words = data + pd.rs_ecc(data, level)
    k = pd.ecc_count(level)
    assert len(words) == 30 + k and k == 2 ** (level + 1)
    for j in range(1, k + 1):
        assert _poly_eval(words, pow(3, j, 929)) == 0


def test_reed_solomon_iso_example():
    # ISO/IEC 15438 Annex Q example: data 5, 453, 178, 121, 239 at level 1
    assert pd.rs_ecc([5, 453, 178, 121, 239], 1) == [452, 327, 657, 619]


def test_recommended_levels():
    assert [pd.recommended_level(n) for n in (1, 40, 41, 160, 161, 320, 321, 863)] == [
        2, 2, 3, 3, 4, 4, 5, 5]
    assert pd.encode("LumaCut").ecc_level == 2
    assert pd.encode("x" * 300).ecc_level == pd.recommended_level(pd.encode("x" * 300).source_words + 1)


# --- symbol layout / sizes ---------------------------------------------------------------
def test_symbol_structure():
    code = pd.encode("LumaCut 2026", columns=3)
    assert code.columns == 3 and code.rows >= 3 and code.width == 17 * 3 + 69
    assert len(code.modules) == code.rows and all(len(r) == code.width for r in code.modules)
    assert len(code.codewords) == code.columns * code.rows
    assert code.codewords[0] == code.data_words                         # length descriptor
    assert code.codewords[code.data_words - code.pad_words:code.data_words] == (pd.PAD,) * code.pad_words
    for y, row in enumerate(code.modules):
        assert pd.widths(int("".join("1" if b else "0" for b in row[:17]), 2)) == [8, 1, 1, 1, 1, 1, 1, 3]
        stop = int("".join("1" if b else "0" for b in row[-18:]), 2)
        assert stop == pd.STOP_PATTERN
        left, right = pd.row_indicators(y, code.rows, 3, code.ecc_level)
        assert row[17:34] == tuple(b == "1" for b in format(pd.pattern(y % 3, left), "017b"))
        assert row[-35:-18] == tuple(b == "1" for b in format(pd.pattern(y % 3, right), "017b"))
    compact = pd.encode("LumaCut 2026", columns=3, compact=True)
    assert compact.width == 17 * 3 + 35 and all(r[-1] and not r[-2] for r in compact.modules)


def test_columns_rows_and_capacity():
    assert pd.encode("A", columns=5).rows == 3                           # minimum 3 rows
    c = pd.encode("LumaCut Werkstatt 2026", columns=1)
    assert c.columns == 1 and c.rows == -(-(c.source_words + 1 + 8) // 1)
    with pytest.raises(ValueError, match="mehr Spalten"):
        pd.encode("x" * 400, columns=1)
    auto = pd.encode("LumaCut Werkstatt 0815 " * 8)
    ratio = auto.width / (auto.rows * 3.0)
    for cols in range(1, 31):                                          # auto: ratio closest to 3
        try:
            other = pd.encode("LumaCut Werkstatt 0815 " * 8, columns=cols)
        except ValueError:
            continue
        import math
        r2 = other.width / (other.rows * 3.0)
        assert abs(math.log(ratio / 3)) <= abs(math.log(r2 / 3)) + 1e-12
    # largest symbol: 928 codewords
    def fits(n, level=pd.AUTO_ECC):
        try:
            pd.encode("7" * n, ecc_level=level)
            return True
        except ValueError:
            return False
    lo, hi = 1, 3000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid - 1)
    big = pd.encode("7" * lo)
    assert big.columns * big.rows <= 928 and big.ecc_level == 2 and 2600 < lo < 2720
    assert fits(lo + 12, 0) and not fits(lo + 1)
    with pytest.raises(ValueError, match="zu lang"):
        pd.encode("x" * 2000)
    with pytest.raises(ValueError, match="Stufe 9"):
        pd.encode("A", ecc_level=9)


# --- reference decoder ------------------------------------------------------------------
def _module_image(code, px=2, row_height=3, quiet=4, invert=False):
    np = pytest.importorskip("numpy")
    a = np.array(code.modules, dtype=bool)
    a = np.repeat(np.repeat(a, row_height * px, 0), px, 1)
    img = np.where(a, 0, 255).astype(np.uint8)
    img = np.pad(img, quiet * px, constant_values=255)
    return 255 - img if invert else img


def _zxing(img):
    zxingcpp = pytest.importorskip("zxingcpp")
    return [(r.text, r.format.name)
            for r in zxingcpp.read_barcodes(img, text_mode=zxingcpp.TextMode.Plain)]


@pytest.mark.parametrize("text", [
    "LUMACUT", "LumaCut 2026", "Hello, World. Test: 1\r\n2\t3", "https://lumacut.example/a?b=1&c=2",
    "Größe äöü – 12 €", "\x00\x01binary\x7f~@_", "MiXeD CaSe lumacut LASER 0815 !?#",
    "4006381333931" * 20, "a" * 500, "x@y.z " * 40, "{\"id\": 42, \"name\": 'LC'}", "日本語テキスト",
])
def test_texts_decode(text):
    code = pd.encode(text)
    assert _zxing(_module_image(code)) == [(text, "PDF417")]


@pytest.mark.parametrize("level", pd.ECC_LEVELS)
def test_every_level_decodes(level):
    text = "LumaCut Werkstatt 2026-0815"
    code = pd.encode(text, ecc_level=level)
    assert code.ecc_level == level and code.ecc_words == 2 << level
    assert _zxing(_module_image(code)) == [(text, "PDF417")]


@pytest.mark.parametrize("columns", [1, 2, 5, 10, 20, 30])
def test_columns_and_compact_decode(columns):
    text = "Seriennummer LC-0815, Charge 4711"
    for compact in (False, True):
        code = pd.encode(text, columns=columns, compact=compact)
        assert code.columns == columns and code.compact == compact
        assert _zxing(_module_image(code)) == [(text, "PDF417")]


def test_random_texts_decode():
    random.seed(417)
    for _ in range(60):
        text = "".join(random.choice("ABCabc 012.,:;!?\r\n\t@_~xyzXYZ-/äé€\x00\x7f\"'{}0123456789")
                       for _ in range(random.randint(1, 300)))
        cols = random.choice([pd.AUTO, 2, 4, 8, 16, 30])
        try:
            code = pd.encode(text, columns=cols, ecc_level=random.choice([-1, 0, 2, 4, 5]),
                             compact=random.random() < 0.3)
        except ValueError:
            continue
        assert _zxing(_module_image(code)) == [(text, "PDF417")]


def test_largest_symbol_decodes():
    text = "7" * 2600
    code = pd.encode(text)
    assert code.columns * code.rows > 850
    assert _zxing(_module_image(code, px=2)) == [(text, "PDF417")]


def test_error_correction_repairs_damage():
    text = "LumaCut Werkstatt 2026-0815"
    code = pd.encode(text, columns=4, ecc_level=4)
    random.seed(3)
    m = [list(r) for r in code.modules]
    for y in random.sample(range(code.rows), 6):       # destroy one data codeword in 6 rows
        col = random.randrange(code.columns)
        x0 = 34 + 17 * col
        for x in range(x0 + 1, x0 + 16):
            m[y][x] = not m[y][x]
    damaged = replace(code, modules=tuple(tuple(r) for r in m))
    assert _zxing(_module_image(damaged)) == [(text, "PDF417")]


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
    x0, y0, x1, y1 = union.bounds
    pad = 6.0
    w = int((x1 - x0 + 2 * pad) * px)
    h = int((y1 - y0 + 2 * pad) * px)
    img = QImage(w, h, QImage.Format_Grayscale8)
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
    return np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w].copy()


def test_shapes_geometry_group_and_area(qapp):
    spec = pd.Pdf417Spec("LumaCut", width_mm=40.0, row_height=3.0, quiet_zone=2, x=10, y=20)
    code = spec.encode()
    shapes = pd.pdf417_shapes(spec, "L1", code)
    assert shapes and all(s.kind == "polygon" and s.layer_id == "L1" for s in shapes)
    assert len({s.groups for s in shapes}) == 1 and shapes[0].groups
    union, polys = _union(shapes)
    module = 40.0 / code.width
    dark = sum(map(sum, code.modules))
    assert union.area == pytest.approx(dark * module * module * 3.0, rel=1e-9)
    assert sum(p.area for p in polys) == pytest.approx(union.area, rel=1e-9)   # no overlaps
    x0, y0, x1, y1 = union.bounds
    assert (x0, y0) == pytest.approx((10 + 2 * module, 20 + 2 * module))
    assert (x1 - x0, y1 - y0) == pytest.approx((40.0, code.rows * 3.0 * module))
    assert spec.height_mm(code) == pytest.approx(code.rows * 3.0 * module)
    inv = pd.pdf417_shapes(replace(spec, invert=True), "L1", code)
    iu, ipolys = _union(inv)
    tw, th = spec.total(code)
    assert iu.bounds == pytest.approx((10, 20, 10 + tw, 20 + th))
    assert iu.area == pytest.approx(tw * th - union.area, rel=1e-9)
    assert sum(p.area for p in ipolys) == pytest.approx(iu.area, rel=1e-9)
    assert pd.describe(code, 40.0).startswith(f"{code.columns} Spalte")
    assert "Stufe 2 (8 Prüfwörter)" in pd.describe(code, 40.0)


def test_spec_normalize_and_shape_errors():
    s = pd.Pdf417Spec(columns=99, ecc_level=12, quiet_zone=99, width_mm=1.0,
                      row_height=0.5).normalized()
    assert (s.columns, s.ecc_level, s.quiet_zone, s.width_mm, s.row_height) == (
        30, 8, pd.QUIET_RANGE[1], pd.WIDTH_RANGE[0], pd.ROW_HEIGHT_RANGE[0])
    s = pd.Pdf417Spec(columns=-3, ecc_level=-7).normalized()
    assert (s.columns, s.ecc_level) == (pd.AUTO, pd.AUTO_ECC)
    assert pd.Pdf417Spec().quiet_zone == 2 and pd.Pdf417Spec().row_height == 3.0
    with pytest.raises(ValueError, match="zu schmal"):
        pd.pdf417_shapes(pd.Pdf417Spec("x" * 300, columns=30, width_mm=20.0), "L1")
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        pd.pdf417_shapes(pd.Pdf417Spec("A", width_mm=50.0, x=WORK_WIDTH_MM - 20), "L1")
    with pytest.raises(ValueError, match="Kein Text"):
        pd.pdf417_shapes(pd.Pdf417Spec(""), "L1")


@pytest.mark.parametrize("text,columns,compact", [
    ("LumaCut-2026-0815", 0, False), ("https://lumacut.example/ä", 0, False),
    ("0123456789" * 20, 6, False), ("Werkstatt", 2, True)])
def test_vector_shapes_decode(qapp, text, columns, compact):
    spec = pd.Pdf417Spec(text, columns=columns, compact=compact, width_mm=60.0, x=5, y=5)
    assert _zxing(_render(pd.pdf417_shapes(spec, "L1"), px=8.0)) == [(text, "PDF417")]


def test_inverted_decodes_on_light_marking(qapp):
    np = pytest.importorskip("numpy")
    spec = pd.Pdf417Spec("Eloxal 42", width_mm=40.0, quiet_zone=2, invert=True, x=5, y=5)
    img = 255 - _render(pd.pdf417_shapes(spec, "L1"), px=8.0)               # laser turns light
    assert _zxing(np.pad(img, 60, constant_values=255)) == [("Eloxal 42", "PDF417")]


def test_hatch_fill_decodes(qapp):
    from lumacut_canvas.model import Layer
    layer = Layer("PDF417", fill_mode="hatch", line_interval_mm=0.1)
    spec = pd.Pdf417Spec("LC-0815", width_mm=35.0, x=5, y=5)
    assert _zxing(_render(pd.pdf417_shapes(spec, "L1"), layer, px=20.0)) == [("LC-0815", "PDF417")]


# --- Qt: dialog and main window ----------------------------------------------------------
def test_dialog(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.pdf417_qt import Pdf417Dialog
    dlg = Pdf417Dialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert not dlg.fill_layer()
    assert [dlg.ecc.itemData(i) for i in range(dlg.ecc.count())] == [pd.AUTO_ECC, *pd.ECC_LEVELS]
    assert dlg.columns.specialValueText() == "Automatisch" and dlg.columns.value() == pd.AUTO
    dlg.text.setText("LUMACUT")
    assert dlg.ok_button.isEnabled() and "Zeilen" in dlg.info.text() and "Stufe 2" in dlg.info.text()
    dlg.columns.setValue(4)
    assert dlg.spec().columns == 4 and dlg.info.text().startswith("4 Spalten")
    dlg.compact.setChecked(True)
    assert dlg.spec().compact and "kompakt" in dlg.info.text()
    dlg.ecc.setCurrentIndex(dlg.ecc.findData(1))
    assert dlg.spec().ecc_level == 1 and "unter der ISO-Empfehlung" in dlg.info.text()
    dlg.ecc.setCurrentIndex(0)
    dlg.row_height.setValue(2.0)
    assert "Zeilenhöhe unter 3" in dlg.info.text()
    dlg.row_height.setValue(3.0)
    dlg.quiet.setValue(0)
    assert "Ruhezone unter 2" in dlg.info.text()
    dlg.quiet.setValue(2)
    dlg.text.setText("")
    assert not dlg.ok_button.isEnabled() and "Kein Text" in dlg.info.text()
    dlg.columns.setValue(1)
    dlg.text.setText("x" * 300)
    assert not dlg.ok_button.isEnabled() and "mehr Spalten" in dlg.info.text()
    dlg.columns.setValue(30)
    dlg.width_mm.setValue(20.0)
    assert not dlg.ok_button.isEnabled() and "zu schmal" in dlg.info.text()
    dlg.width_mm.setValue(150.0)
    assert dlg.ok_button.isEnabled() and "schlecht lesbar" in dlg.info.text()
    dlg.columns.setValue(0)
    dlg.text.setText("abc")
    dlg.width_mm.setValue(355.0)
    assert not dlg.ok_button.isEnabled() and "Arbeitsfläche" in dlg.info.text()
    dlg.invert.setChecked(True)
    assert dlg.spec().invert
    dlg.deleteLater()
    dlg2 = Pdf417Dialog(active_layer=Layer("Kontur"))
    assert dlg2.fill_layer()
    dlg2.fill.setChecked(False)
    assert "nur Umrisse" in dlg2.info.text()
    dlg2.deleteLater()
    spec = pd.Pdf417Spec("LC", columns=3, ecc_level=4, width_mm=55.5, row_height=4.25,
                         quiet_zone=3, compact=True)
    edit = Pdf417Dialog(spec=spec)
    assert edit.spec() == spec
    edit.deleteLater()


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
    a = tools.pdf417_action
    assert a.objectName() == "pdf417_action" and a.text() == "PDF417-Code…"
    assert a.shortcut() == QKeySequence("Alt+F")
    clash = [b.text() for b in win.findChildren(QAction)
             if b is not a and b.shortcut() == a.shortcut()]
    assert clash == []
    assert not any(m.text().replace("&&", "").lower().startswith("&f")
                   or "&f" in m.text().lower().replace("&&", "")
                   for m in win.menuBar().actions())                    # no Alt+F mnemonic
    assert a in win.main_view.design_menu.actions()
    assert a in win.main_view.job_menu.actions()
    doc = win.canvas.document
    layer = doc.active_layer
    win.canvas.undo_stack.push(SetLayerAttrCommand(doc, layer.id, "fill_mode", "hatch"))
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    depth = win.canvas.undo_stack.index()
    ids = tools.pdf417(pd.Pdf417Spec("LumaCut", width_mm=40.0))
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
    assert gcode.count("G1 ") > 30
    pi_check(gcode)
    win.canvas.undo_stack.undo()
    assert len(doc.shapes) == n_shapes and not any(doc.has_shape(i) for i in ids)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert tools.pdf417(pd.Pdf417Spec("1" * 4000, width_mm=40.0)) == []
    assert warned and len(doc.shapes) == n_shapes


def test_window_new_fill_layer_one_undo_step(win):
    tools = win.job_tools
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    ids = tools.pdf417(pd.Pdf417Spec("Werkstatt", width_mm=50.0, invert=True))
    assert len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == "PDF417" and new.fill_mode == "hatch" and new.line_interval_mm == 0.1
    win.canvas.undo_stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes


def test_re_edit_scaled_and_saved(win):
    from lumacut_canvas.commands import SetGeometryCommand
    from lumacut_canvas.model import Document, Rect
    from lumacut_job import generated
    from lumacut_job.generated_qt import edit_dialog, generated_unit, unit_spec
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "hatch"
    spec = pd.Pdf417Spec("LC-0815", columns=3, ecc_level=3, width_mm=40.0, compact=True)
    ids = tools.pdf417(spec)
    assert doc.shape(ids[0]).generator["kind"] == "pdf417"
    win.canvas.set_selection(ids[:1])
    ob = doc.selection_bounds(ids)
    nb = Rect(ob.x, ob.y, ob.w * 1.5, ob.h * 3.0)                        # wider, much taller
    old = {i: doc.shape(i).geom.copy() for i in ids}
    stack.push(SetGeometryCommand(doc, old, {i: g.mapped(ob, nb) for i, g in old.items()}, "Maße"))
    unit = generated_unit(win.canvas)
    assert unit.kind == "pdf417" and unit.label == "PDF417-Code"
    got = unit_spec(unit)
    assert got.width_mm == pytest.approx(60.0) and got.row_height == pytest.approx(6.0)
    assert (got.text, got.columns, got.ecc_level, got.compact) == ("LC-0815", 3, 3, True)
    dlg = edit_dialog(unit, got, doc.layer(unit.layer_id), win)
    assert dlg.windowTitle() == "PDF417-Code bearbeiten" and dlg.spec() == got
    assert not dlg.fill.isVisible()
    dlg.deleteLater()
    new_ids = tools.edit_generated(replace(got, text="LC-0816"))
    u2 = generated.find_unit(doc, new_ids[0])
    assert u2.center == pytest.approx(unit.center, abs=1e-6) and not u2.scaled
    assert _zxing(_render([doc.shape(i) for i in new_ids], px=8.0)) == [("LC-0816", "PDF417")]
    # generator parameters survive the file format
    other = Document()
    other.load_dict(json.loads(json.dumps(doc.to_dict())))
    again = other.shape(new_ids[0])
    assert generated.spec_from_meta(again.generator) == replace(got, text="LC-0816")
    stack.undo()
    assert all(doc.has_shape(i) for i in ids) and not any(doc.has_shape(i) for i in new_ids)
