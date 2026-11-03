"""Aztec Code generator (ISO/IEC 24778): encodation, Reed-Solomon, layout, sizes, vectors, UI."""

import random
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import aztec as az  # noqa: E402


def _bits(pairs):
    return [(v >> (b - 1 - k)) & 1 for v, b in pairs for k in range(b)]


# --- high-level encodation -------------------------------------------------------------
def test_upper_lower_digit_and_latches():
    assert az.encode_items(list(b"LUMA")) == [(13, 5), (22, 5), (14, 5), (2, 5)]
    # Upper → L/L, lower case; U/S for a single capital inside lower case
    assert az.encode_items(list(b"aBc")) == [(28, 5), (2, 5), (28, 5), (3, 5), (4, 5)]
    # Digit mode: 4-bit codes, space / comma / point stay in Digit
    assert az.encode_items(list(b"12.5")) == [(30, 5), (3, 4), (4, 4), (13, 4), (7, 4)]
    assert len(az.encode_bits("LumaCut 2026")) == 70
    assert len(az.encode_bits("LUMACUT")) == 35


def test_punct_shift_pairs_and_mixed():
    # one punctuation character: P/S + code; ". " / ", " / ": " / CR LF are one Punct code
    assert az.encode_items(list(b"A!")) == [(2, 5), (0, 5), (6, 5)]
    assert az.encode_items(list(b"A. B")) == [(2, 5), (0, 5), (3, 5), (3, 5)]
    assert az.encode_items(list(b"\r\n")) == [(0, 5), (2, 5)]
    assert az.encode_items(list(b"@")) == [(29, 5), (20, 5)]               # M/L, '@'
    many = az.encode_items(list(b"!?!?!?"))                                # latch Punct
    assert many[:2] == [(29, 5), (30, 5)] and len(_bits(many)) == 10 + 6 * 5


def test_binary_shift_eci_and_gs1():
    out = az.encode_items([0xFF, 0x00])
    assert out == [(31, 5), (2, 5), (0xFF, 8), (0x00, 8)]
    long = az.encode_items([0xFE] * 40)
    assert long[:3] == [(31, 5), (0, 5), (40 - 31, 11)] and len(long) == 3 + 40
    # non-ASCII text: P/S FLG(2) "26" (ECI 26 = UTF-8), then the UTF-8 bytes in a binary run
    prefix, items = az.text_items("ä")
    assert _bits(prefix) == _bits([(0, 5), (0, 5), (2, 3), (4, 4), (8, 4)])
    assert items == list("ä".encode())
    _p, gs = az.text_items("(10)AB", gs1_mode=True)
    assert gs[0] == az.FNC1
    # D/L (digits follow), P/S in Digit (4 bits), FLG(0)
    assert az.encode_items(gs)[:4] == [(30, 5), (0, 4), (0, 5), (0, 3)]
    with pytest.raises(ValueError, match="richtig wäre 3"):
        az.encode("(01)09501101530004", gs1_mode=True)


def test_dynamic_program_is_never_worse_than_greedy_modes():
    random.seed(18)
    for _ in range(40):
        text = "".join(random.choice("ABCabc 012.,:;!?@_~-/\r\n") for _ in range(random.randint(1, 60)))
        bits = len(az.encode_bits(text))
        # upper bound: every character via Binary Shift from Upper
        assert bits <= 5 + 5 + 8 * len(text) + (6 if len(text) > 31 else 0)


# --- stuffing / Reed-Solomon / mode message ----------------------------------------------
def test_bit_stuffing():
    assert az.stuff_bits([1] * 12, 6)[:2] == [0b111110, 0b111110]
    assert az.stuff_bits([0] * 6, 6)[0] == 0b000001
    for size in (6, 8, 10, 12):
        random.seed(size)
        bits = [random.choice((0, 0, 0, 1)) for _ in range(300)] + [1] * 40 + [0] * 40
        words = az.stuff_bits(bits, size)
        mask = (1 << size) - 2
        assert all(wd not in (0, (1 << size) - 1) for wd in words)
        # unstuff: drop the stuffed last bit of words whose first bits are all equal
        out = []
        for wd in words:
            b = [(wd >> (size - 1 - k)) & 1 for k in range(size)]
            out += b[:-1] if (wd >> 1) in (0, mask >> 1) else b
        assert out[:len(bits)] == bits and all(out[len(bits):])


def _poly_eval(words, x, bits):
    acc = 0
    for c in words:
        acc = az.gf_mul(acc, x, bits) ^ c
    return acc


@pytest.mark.parametrize("bits", [4, 6, 8, 10, 12])
def test_reed_solomon_syndromes_zero(bits):
    random.seed(bits)
    data = [random.randrange(1 << bits) for _ in range(min(20, (1 << bits) - 12))]
    words = data + az.rs_ecc(data, 9, bits)
    exp, _log = az._field(bits)
    assert all(_poly_eval(words, exp[i], bits) == 0 for i in range(1, 10))


def test_formats_and_sizes():
    assert az.SIZES[:5] == (15, 19, 23, 27, 31) and az.SIZES[-1] == 151 and len(az.SIZES) == 33
    assert az.FORMATS[15].compact and az.FORMATS[27].layers == 4 and not az.FORMATS[31].compact
    assert az.FORMATS[31].layers == 4 and az.FORMATS[151].layers == 32
    assert az.FORMATS[67].size == 67 and az.FORMATS[19].word_size == 6
    assert az.FORMATS[151].word_size == 12 and az.FORMATS[151].words == 1664
    assert az.symbol_key("23") == 23 and az.symbol_key(0) == az.AUTO
    with pytest.raises(ValueError, match="Unbekannte"):
        az.symbol_key(17)
    assert az.ecc_words_needed(17) == 4 + 3


@pytest.mark.parametrize("size", [15, 19, 27, 31, 37, 67, 151])
def test_finder_orientation_and_reference_grid(size):
    code = az.encode("LC", size)
    m, c = code.modules, size // 2
    assert code.size == size and len(m) == size and all(len(r) == size for r in m)
    eye = 5 if code.compact else 7
    for r in range(eye):                  # bull's eye: dark rings at even Chebyshev radius
        assert all(m[c + dy][c + dx] == (r % 2 == 0)
                   for dy in range(-r, r + 1) for dx in range(-r, r + 1) if max(abs(dx), abs(dy)) == r)
    assert m[c - eye][c - eye] and m[c - eye][c - eye + 1] and m[c - eye + 1][c - eye]
    assert m[c - eye][c + eye] and m[c - eye + 1][c + eye] and m[c + eye - 1][c + eye]
    if not code.compact:                  # reference grid: dark every other module, every 16 rows
        base = 14 + 4 * code.layers                    # size without the grid lines
        for j in range(0, 16 * ((base // 2 - 2) // 15) + 1, 16):
            for k in range(c % 2, size, 2):
                assert m[c - j][k] and m[c + j][k] and m[k][c - j] and m[k][c + j]


def test_capacity_and_errors():
    assert az.encode("LUMACUT").size == 15
    assert az.encode("7" * 3832).size == 151
    with pytest.raises(ValueError, match="zu lang"):
        az.encode("7" * 3833)
    with pytest.raises(ValueError, match="Kein Text"):
        az.encode("")
    assert az.encode("A", 45).size == 45                                    # minimum honoured
    assert az.encode("x" * 60, 15).size > 15                                # next larger
    small = az.encode("LumaCut-2026-0815", ecc_percent=10)
    big = az.encode("LumaCut-2026-0815", ecc_percent=90)
    assert small.size < big.size and big.ecc_words >= 0.9 * big.format.words


# --- reference decoder ------------------------------------------------------------------
def _module_image(code, px=5, quiet=3, invert=False):
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
    return [(r.text, r.format.name)
            for r in zxingcpp.read_barcodes(img, text_mode=zxingcpp.TextMode.Plain)]


@pytest.mark.parametrize("size", az.SIZES)
def test_every_size_decodes_with_zxing(size):
    pattern = "LumaCut 0815, äöü! " * 120

    def fits(n):
        try:
            return az.encode(pattern[:n], size).size == size
        except ValueError:
            return False
    f = az.FORMATS[size]
    lo, hi = 1, f.words * f.word_size // 5         # binary search: fill to capacity
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid - 1)
    text = pattern[:lo]
    assert not fits(lo + 1)
    code = az.encode(text, size)
    assert code.size == size
    assert _zxing(_module_image(code, px=3 if size > 60 else 5)) == [(text, "Aztec")]


@pytest.mark.parametrize("text", ["LUMACUT", "LumaCut 2026", "0123456789" * 30, "A" * 200,
                                  "abc" * 30, "ABC 123 abc" * 5])
def test_matches_zxing_writer(text):
    # Where the mode choice is unambiguous the reference writer produces the same bits,
    # so the module matrices must be identical (stuffing, RS, mode message, layout).
    zxingcpp = pytest.importorskip("zxingcpp")
    np = pytest.importorskip("numpy")
    try:
        ref = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.Aztec)
        img = np.array(zxingcpp.write_barcode_to_image(ref, scale=1, add_quiet_zones=False))
    except (AttributeError, TypeError):
        pytest.skip("zxing-cpp without writer API")
    ours = np.array(az.encode(text).modules)
    assert img.shape == ours.shape
    assert ((img < 128) == ours).all()


@pytest.mark.parametrize("text", [
    "Hello, World. Test: 1\r\n2", "https://lumacut.example/a?b=1&c=2", "Größe äöü – 12 €",
    "\x00\x01binary\x7f~@_", "MiXeD CaSe lumacut LASER 0815 !?#", "ä" * 120 + "plain" * 30,
    "a" * 500, "x@y.z " * 40,
])
def test_mixed_texts_decode(text):
    code = az.encode(text)
    assert _zxing(_module_image(code, px=3 if code.size > 60 else 5)) == [(text, "Aztec")]


def test_random_texts_decode():
    random.seed(24778)
    for _ in range(25):
        text = "".join(random.choice("ABCabc 012.,:;!?\r\n@_~xyzXYZ-/äé€\x00\x7f")
                       for _ in range(random.randint(1, 250)))
        code = az.encode(text)
        assert _zxing(_module_image(code, px=3 if code.size > 60 else 5)) == [(text, "Aztec")]


def test_gs1_aztec_decodes_as_gs1():
    zxingcpp = pytest.importorskip("zxingcpp")
    text = "(01)09501101530003(17)261231(10)AB-12"
    code = az.encode(text, gs1_mode=True)
    got = [(r.text, r.symbology_identifier) for r in zxingcpp.read_barcodes(_module_image(code))]
    assert got == [(text, "]z1")]


def test_error_correction_repairs_damage():
    random.seed(7)
    code = az.encode("LumaCut Werkstatt 2026-0815", 31, ecc_percent=40)
    m = [list(r) for r in code.modules]
    c = code.size // 2
    flipped = 0
    while flipped < 12:                    # data modules only (outside finder + mode ring)
        x, y = random.randrange(code.size), random.randrange(code.size)
        if max(abs(x - c), abs(y - c)) > 8 and (x - c) % 16 and (y - c) % 16:
            m[y][x] = not m[y][x]
            flipped += 1
    damaged = replace(code, modules=tuple(tuple(r) for r in m))
    assert _zxing(_module_image(damaged)) == [("LumaCut Werkstatt 2026-0815", "Aztec")]


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
    spec = az.AztecSpec("LumaCut", size_mm=15.0, quiet_zone=1, x=10, y=20)
    code = spec.encode()
    shapes = az.aztec_shapes(spec, "L1", code)
    assert shapes and all(s.kind == "polygon" and s.layer_id == "L1" for s in shapes)
    assert len({s.groups for s in shapes}) == 1 and shapes[0].groups
    union, polys = _union(shapes)
    module = 15.0 / code.size
    dark = sum(map(sum, code.modules))
    assert union.area == pytest.approx(dark * module ** 2, rel=1e-9)
    assert sum(p.area for p in polys) == pytest.approx(union.area, rel=1e-9)   # no overlaps
    x0, y0, x1, y1 = union.bounds
    assert (x0, y0) == pytest.approx((10 + module, 20 + module))
    assert (x1 - x0, y1 - y0) == pytest.approx((15.0, 15.0))
    inv = az.aztec_shapes(replace(spec, invert=True), "L1", code)
    iu, _ = _union(inv)
    total = spec.total_mm(code)
    assert iu.bounds == pytest.approx((10, 20, 10 + total, 20 + total))
    assert iu.area == pytest.approx(total ** 2 - union.area, rel=1e-9)
    assert az.describe(code, 15.0) == ("15 × 15 Module (kompakt, 1 Lage, 8 Datenwörter, "
                                       "Fehlerkorrektur 53 %), Modul 1.00 mm")


def test_spec_normalize_and_shape_errors():
    s = az.AztecSpec(symbol=17, ecc_percent=200, quiet_zone=99, size_mm=1.0).normalized()
    assert (s.symbol, s.ecc_percent, s.quiet_zone, s.size_mm) == (
        az.AUTO, az.ECC_RANGE[1], az.QUIET_RANGE[1], az.SIZE_RANGE[0])
    assert az.AztecSpec().quiet_zone == 1 and az.AztecSpec().ecc_percent == 23
    with pytest.raises(ValueError, match="zu klein"):
        az.aztec_shapes(az.AztecSpec("1" * 3000, size_mm=20.0), "L1")
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        az.aztec_shapes(az.AztecSpec("A", size_mm=50.0, x=WORK_WIDTH_MM - 20), "L1")
    with pytest.raises(ValueError, match="Kein Text"):
        az.aztec_shapes(az.AztecSpec(""), "L1")


@pytest.mark.parametrize("text,symbol", [("LumaCut-2026-0815", 0), ("https://lumacut.example/ä", 0),
                                         ("0123456789" * 20, 0), ("Werkstatt", 31)])
def test_vector_shapes_decode(qapp, text, symbol):
    spec = az.AztecSpec(text, symbol=symbol, size_mm=30.0, quiet_zone=1, x=5, y=5)
    assert _zxing(_render(az.aztec_shapes(spec, "L1"), px=8.0)) == [(text, "Aztec")]


def test_inverted_decodes_on_light_marking(qapp):
    np = pytest.importorskip("numpy")
    spec = az.AztecSpec("Eloxal 42", size_mm=15.0, quiet_zone=2, invert=True, x=5, y=5)
    img = 255 - _render(az.aztec_shapes(spec, "L1"), px=8.0)               # laser turns light
    assert _zxing(np.pad(img, 60, constant_values=255)) == [("Eloxal 42", "Aztec")]


def test_hatch_fill_decodes(qapp):
    from lumacut_canvas.model import Layer
    layer = Layer("Aztec", fill_mode="hatch", line_interval_mm=0.1)
    spec = az.AztecSpec("LC-0815", size_mm=10.0, quiet_zone=1, x=5, y=5)
    assert _zxing(_render(az.aztec_shapes(spec, "L1"), layer, px=20.0)) == [("LC-0815", "Aztec")]


# --- Qt: dialog and main window ----------------------------------------------------------
def test_dialog(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.aztec_qt import AztecDialog
    dlg = AztecDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert not dlg.fill_layer()
    keys = [dlg.symbol.itemData(i) for i in range(dlg.symbol.count())]
    assert keys == [az.AUTO, *az.SIZES]
    dlg.text.setText("LUMACUT")
    assert dlg.ok_button.isEnabled() and "15 × 15" in dlg.info.text() and "kompakt" in dlg.info.text()
    dlg.symbol.setCurrentIndex(dlg.symbol.findData(37))
    assert dlg.spec().symbol == 37 and "37 × 37" in dlg.info.text() and "voll" in dlg.info.text()
    dlg.symbol.setCurrentIndex(dlg.symbol.findData(15))
    dlg.text.setText("x" * 60)
    assert "nächste passende" in dlg.info.text()
    dlg.ecc.setValue(50)
    assert dlg.spec().ecc_percent == 50
    dlg.text.setText("")
    assert not dlg.ok_button.isEnabled() and "Kein Text" in dlg.info.text()
    dlg.text.setText("1" * 3000)
    dlg.ecc.setValue(23)
    dlg.size_mm.setValue(10.0)
    assert not dlg.ok_button.isEnabled() and "zu klein" in dlg.info.text()
    dlg.text.setText("abc")
    dlg.symbol.setCurrentIndex(0)
    dlg.size_mm.setValue(330.0)
    assert not dlg.ok_button.isEnabled() and "Arbeitsfläche" in dlg.info.text()
    dlg.gs1.setChecked(True)
    dlg.size_mm.setValue(15.0)
    dlg.text.setText("(01)09501101530004")
    assert not dlg.ok_button.isEnabled() and "richtig wäre 3" in dlg.info.text()
    dlg.text.setText(az.gs1.EXAMPLE)
    assert dlg.ok_button.isEnabled() and dlg.spec().gs1
    dlg.invert.setChecked(True)
    assert dlg.spec().invert
    dlg.deleteLater()
    dlg2 = AztecDialog(active_layer=Layer("Kontur"))
    assert dlg2.fill_layer()
    dlg2.fill.setChecked(False)
    assert "nur Umrisse" in dlg2.info.text()
    dlg2.deleteLater()
    edit = AztecDialog(spec=az.AztecSpec("(10)A", symbol=23, ecc_percent=40, gs1=True))
    assert edit.spec() == az.AztecSpec("(10)A", symbol=23, ecc_percent=40, gs1=True)
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
    a = tools.aztec_action
    assert a.objectName() == "aztec_action" and a.text() == "Aztec-Code…"
    assert a.shortcut() == QKeySequence("Alt+Z")
    clash = [b.text() for b in win.findChildren(QAction)
             if b is not a and b.shortcut() == a.shortcut()]
    assert clash == []
    assert not any(m.text().replace("&&", "").lower().startswith("&z")
                   for m in win.menuBar().actions())                    # no Alt+Z mnemonic
    assert a in win.main_view.design_menu.actions()
    assert a in win.main_view.job_menu.actions()
    doc = win.canvas.document
    layer = doc.active_layer
    win.canvas.undo_stack.push(SetLayerAttrCommand(doc, layer.id, "fill_mode", "hatch"))
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    depth = win.canvas.undo_stack.index()
    ids = tools.aztec(az.AztecSpec("LumaCut", size_mm=12.0))
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
    assert tools.aztec(az.AztecSpec("1" * 4000, size_mm=20.0)) == []
    assert warned and len(doc.shapes) == n_shapes


def test_window_new_fill_layer_one_undo_step(win):
    tools = win.job_tools
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    ids = tools.aztec(az.AztecSpec("Werkstatt", size_mm=20.0, invert=True))
    assert len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == "Aztec" and new.fill_mode == "hatch" and new.line_interval_mm == 0.1
    win.canvas.undo_stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes


def test_re_edit_scaled_and_saved(win, tmp_path):
    from lumacut_canvas.commands import SetGeometryCommand
    from lumacut_canvas.model import Rect
    from lumacut_job import generated
    from lumacut_job.generated_qt import edit_dialog, generated_unit, unit_spec
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "hatch"
    spec = az.AztecSpec("LC-0815", symbol=19, ecc_percent=33, size_mm=12.0, gs1=False)
    ids = tools.aztec(spec)
    assert doc.shape(ids[0]).generator["kind"] == "aztec"
    win.canvas.set_selection(ids[:1])
    ob = doc.selection_bounds(ids)
    nb = Rect(ob.x, ob.y, ob.w * 1.5, ob.h * 1.5)
    old = {i: doc.shape(i).geom.copy() for i in ids}
    stack.push(SetGeometryCommand(doc, old, {i: g.mapped(ob, nb) for i, g in old.items()}, "Maße"))
    unit = generated_unit(win.canvas)
    assert unit.kind == "aztec" and unit.label == "Aztec-Code"
    got = unit_spec(unit)
    assert got.size_mm == pytest.approx(18.0)
    assert (got.text, got.symbol, got.ecc_percent) == ("LC-0815", 19, 33)
    dlg = edit_dialog(unit, got, doc.layer(unit.layer_id), win)
    assert dlg.windowTitle() == "Aztec-Code bearbeiten" and dlg.spec() == got
    assert not dlg.fill.isVisible()
    dlg.deleteLater()
    new_ids = tools.edit_generated(replace(got, text="LC-0816"))
    u2 = generated.find_unit(doc, new_ids[0])
    assert u2.center == pytest.approx(unit.center, abs=1e-6) and not u2.scaled
    assert _zxing(_render([doc.shape(i) for i in new_ids], px=8.0)) == [("LC-0816", "Aztec")]
    # generator parameters survive the file format
    from lumacut_canvas.model import Shape
    again = Shape.from_dict(doc.shape(new_ids[0]).to_dict())
    assert generated.spec_from_meta(again.generator) == replace(got, text="LC-0816")
