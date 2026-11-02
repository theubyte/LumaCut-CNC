"""1D barcode generator: encoding (vs. reference), check digits, set switching,
geometry, errors, decoding of the rendered vectors, dialog, window, undo, G-code."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import barcode as bc  # noqa: E402

# Module strings ("1" = bar) from python-barcode 0.16.1 (Code128/EAN13/EAN8/UPCA,
# trailing termination bar of the Code 128 stop symbol included); all of them
# decode with zxing-cpp 3.1.
REFERENCE = {
    ("code128", "LumaCut"):
        "1101001000010001101110100111100101111011101010010110000100010001"
        "101001111001010011110100110011101001100011101011",
    ("code128", "1234567890"):
        "1101001110010110011100100010110001110001011011000010100110111101"
        "10100111100101100011101011",
    ("ean13", "400638133393"):
        "1010001101010011101011110111101000100101100110101010000101000010"
        "1000010111010010000101100110101",
    ("ean8", "9638507"):
        "1010001011010111101111010110111010101001110111001010001001011100"
        "101",
    ("upca", "03600029145"):
        "1010001101011110101011110001101000110100011010101011011001110100"
        "1100110101110010011101101100101",
}


def test_matches_reference_modules():
    for (sym, data), mods in REFERENCE.items():
        assert bc.encode(sym, data).modules == mods, (sym, data)


def test_code128_table_and_checksum():
    # ISO/IEC 15417: every symbol 11 modules, 3 bars + 3 spaces; stop 13 modules
    for widths in bc._C128:
        assert len(widths) == 6 and sum(map(int, widths)) == 11
        assert sum(map(int, widths[0::2])) % 2 == 0          # even bar modules
    assert sum(map(int, bc._C128_STOP)) == 13
    assert len({bc._C128}) == 1 and len(set(bc._C128)) == 106
    # Wikipedia example "Wikipedia": Start B, data, check 88, stop
    vals = bc.code128_values("Wikipedia")
    assert vals == [104, 55, 73, 75, 73, 80, 69, 68, 73, 65, 88, 106]
    assert bc.code128_checksum(vals[:-2]) == 88
    assert len(bc.encode("code128", "Wikipedia").modules) == 11 * 11 + 13


@pytest.mark.parametrize("text,values", [
    ("1234567890", [105, 12, 34, 56, 78, 90]),                 # all digits: Start C
    ("X12345", [104, 56, 17, 99, 23, 45]),                     # odd digit run: one in B, then C
    ("12345", [104, 17, 99, 23, 45]),
    ("0123456789012", [104, 16, 99, 12, 34, 56, 78, 90, 12]),
    ("RI 476", [104, 50, 41, 0, 20, 23, 22]),                  # short digit runs stay in B
    ("ab1234cd", [104, 65, 66, 17, 18, 19, 20, 67, 68]),       # tie: stay in B
    ("AB123456CD", [104, 33, 34, 99, 12, 34, 56, 100, 35, 36]),  # C in the middle and back
    ("2026-11-02", [105, 20, 26, 100, 13, 17, 17, 13, 16, 18]),
])
def test_code128_set_switching(text, values):
    got = bc.code128_values(text)
    assert got[:-2] == values and got[-1] == bc.STOP
    assert got[-2] == bc.code128_checksum(values)


def test_code128_shortest():
    # Brute force over all B/C segmentations for a few strings: DP is optimal.
    def best(t, i=0, s=None):
        if i == len(t):
            return 0
        opts = []
        for ns in ("B", "C"):
            sw = 0 if s in (None, ns) else 1
            if ns == "B":
                opts.append(sw + 1 + best(t, i + 1, "B"))
            elif t[i:i + 2].isdigit() and len(t[i:i + 2]) == 2:
                opts.append(sw + 1 + best(t, i + 2, "C"))
        return min(opts)
    for t in ("a1234", "12a34567b", "9", "99", "123", "1a2b3c", "000000x0000"):
        assert len(bc.code128_values(t)) - 3 == best(t), t


def test_ean_check_digits_and_errors():
    assert bc.ean_check_digit("400638133393") == 1
    assert bc.ean_check_digit("590123412345") == 7
    assert bc.ean_check_digit("9638507") == 4
    assert bc.ean_check_digit("03600029145") == 2
    assert bc.complete_digits("ean13", "4006381333931") == "4006381333931"
    assert bc.complete_digits("ean13", " 400638 133393 ") == "4006381333931"
    assert bc.complete_digits("upca", "036000291452") == "036000291452"
    with pytest.raises(ValueError, match="Prüfziffer.*falsch.*richtig wäre 1"):
        bc.encode("ean13", "4006381333932")
    with pytest.raises(ValueError, match="nur Ziffern"):
        bc.encode("ean8", "12a4567")
    with pytest.raises(ValueError, match="braucht 7 Ziffern"):
        bc.encode("ean8", "123")
    with pytest.raises(ValueError, match="Keine Ziffern"):
        bc.encode("upca", "")
    with pytest.raises(ValueError, match="Kein Text"):
        bc.encode("code128", "")
    with pytest.raises(ValueError, match="nur ASCII"):
        bc.encode("code128", "Grüße")
    with pytest.raises(ValueError, match="zu lang"):
        bc.encode("code128", "x" * (bc.MAX_CODE128_CHARS + 1))
    with pytest.raises(ValueError, match="Unbekannter"):
        bc.encode("pdf417", "x")
    # UPC-A is EAN-13 with a leading 0
    assert bc.encode("upca", "03600029145").modules == bc.encode("ean13", "003600029145").modules


def test_ean_structure():
    code = bc.encode("ean13", "590123412345")
    m = code.modules
    assert len(m) == 95 and m[:3] == "101" and m[45:50] == "01010" and m[-3:] == "101"
    assert len(bc.encode("ean8", "5512345").modules) == 67
    assert code.quiet == (11, 7)
    assert [s.text for s in code.segments] == ["5", "901234", "123457"]


def _union(shapes):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from lumacut_canvas.shape_paths import shape_polygons
    polys = []
    for s in shapes:                     # even-odd: glyphs may have several outer rings
        g = Polygon()
        for ring in shape_polygons(s):
            g = g.symmetric_difference(Polygon(ring).buffer(0))
        polys.append(g)
    return unary_union(polys), polys


def test_bar_geometry_widths_and_quiet_zone(qapp):
    spec = bc.BarcodeSpec("code128", "LumaCut", module_mm=0.4, height_mm=12.0, show_text=False,
                          x=10, y=20)
    code = bc.encode(spec.symbology, spec.data)
    shapes = bc.barcode_shapes(spec, "L1", code)
    bars = code.bars()
    assert len(shapes) == len(bars)                      # one rectangle per merged bar
    assert all(s.kind == "polygon" and s.layer_id == "L1" for s in shapes)
    assert len({s.groups for s in shapes}) == 1 and len(shapes[0].groups) == 1
    union, polys = _union(shapes)
    x0, y0, x1, y1 = union.bounds
    assert x0 == pytest.approx(10 + 10 * 0.4) and y0 == pytest.approx(20)
    assert x1 - x0 == pytest.approx(len(code.modules) * 0.4) and y1 - y0 == pytest.approx(12.0)
    assert union.area == pytest.approx(code.modules.count("1") * 0.4 * 12.0)
    assert sum(p.area for p in polys) == pytest.approx(union.area)   # no overlap
    for p, (start, width) in zip(sorted(polys, key=lambda p: p.bounds[0]), bars):
        assert p.bounds[0] == pytest.approx(14 + start * 0.4)
        assert p.bounds[2] - p.bounds[0] == pytest.approx(width * 0.4)
        assert p.geom_type == "Polygon" and len(p.exterior.coords) == 5   # plain rectangle
    w, h = spec.size_mm(code)
    assert w == pytest.approx((len(code.modules) + 20) * 0.4) and h == pytest.approx(12.0)
    # bar width reduction: each bar narrower by shrink, centred on the module
    thin = bc.barcode_shapes(bc.BarcodeSpec("code128", "LumaCut", 0.4, 12.0, show_text=False,
                                            shrink_mm=0.1, x=10, y=20), "L1", code)
    u2, _ = _union(thin)
    assert u2.area == pytest.approx(union.area - len(bars) * 0.1 * 12.0)
    assert u2.bounds[0] == pytest.approx(x0 + 0.05)
    # without quiet zone the bars start at x
    nq = bc.barcode_shapes(bc.BarcodeSpec("code128", "LumaCut", 0.4, 12.0, quiet_zone=False,
                                          show_text=False, x=10, y=20), "L1", code)
    assert _union(nq)[0].bounds[0] == pytest.approx(10.0)


def _glyphs(text, height):
    """Qt-free stand-in: every digit a box ``height`` high, 0.6 * height wide."""
    from lumacut_job.arctext import Glyph
    w = 0.6 * height
    return [Glyph(c, w * 1.1, (((0, -height), (w, -height), (w, 0), (0, 0)),)) for c in text]


def test_ean_text_and_guards():
    spec = bc.BarcodeSpec("ean13", "590123412345", module_mm=0.33, height_mm=20.0, text_mm=2.5,
                          x=5, y=5)
    code = bc.encode(spec.symbology, spec.data)
    rects = bc.bar_rects(spec, code)
    tall = [r for r in rects if r[3] - r[1] > 20.0 + 1e-9]
    assert len(tall) == 6                                # 2 bars each in the 3 guards
    rings = bc.text_rings(spec, code, _glyphs)
    assert len(rings) == 13
    gap = spec.text_gap()
    for (ring,) in rings:
        ys = [p[1] for p in ring]
        assert min(ys) == pytest.approx(5 + 20 + gap) and max(ys) == pytest.approx(5 + 20 + gap + 2.5)
    first = rings[0][0]
    assert max(p[0] for p in first) < 5 + 11 * 0.33      # first digit in the left quiet zone
    w, h = spec.size_mm(code)
    assert w == pytest.approx(113 * 0.33) and h == pytest.approx(20 + gap + 2.5)
    # text too wide for its slot: shrunk uniformly
    big = bc.text_rings(bc.BarcodeSpec("ean8", "5512345", 0.2, 10.0, text_mm=10.0),
                        bc.encode("ean8", "5512345"), _glyphs)
    widths = [max(p[0] for p in r[0]) - min(p[0] for p in r[0]) for r in big]
    assert max(widths) * 4 <= 28 * 0.2 + 1e-6
    shapes = bc.barcode_shapes(spec, "L1", code, _glyphs)
    assert len(shapes) == len(code.bars()) + 13 and len({s.groups for s in shapes}) == 1
    assert len(bc.barcode_shapes(spec, "L1", code)) == len(code.bars())   # no glyphs: bars only


def test_shape_errors_and_limits():
    with pytest.raises(ValueError, match="zu schmal"):
        bc.barcode_shapes(bc.BarcodeSpec("code128", "abc", module_mm=0.05), "L1")
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        bc.barcode_shapes(bc.BarcodeSpec("code128", "x" * 40, module_mm=1.0), "L1")
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        bc.barcode_shapes(bc.BarcodeSpec("ean8", "5512345", x=WORK_WIDTH_MM - 10), "L1")
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        bc.barcode_shapes(bc.BarcodeSpec("ean8", "5512345", height_mm=50, y=WORK_HEIGHT_MM - 40),
                          "L1")
    with pytest.raises(ValueError, match="Strichkorrektur"):
        bc.barcode_shapes(bc.BarcodeSpec("ean8", "5512345", module_mm=0.2, shrink_mm=0.15), "L1")
    s = bc.BarcodeSpec("QR", "a", module_mm=99, height_mm=0, text_mm=-1, shrink_mm=5).normalized()
    assert s.symbology == "code128" and s.module_mm == bc.MODULE_RANGE[1]
    assert (s.height_mm, s.text_mm, s.shrink_mm) == (bc.HEIGHT_RANGE[0], bc.TEXT_RANGE[0],
                                                       bc.SHRINK_RANGE[1])
    # biggest Code 128 that fits: 360 mm wide incl. quiet zone
    code = bc.encode("code128", "LumaCut")
    module = WORK_WIDTH_MM / (len(code.modules) + 20)
    ok = bc.centered(bc.BarcodeSpec("code128", "LumaCut", module_mm=module), code=code)
    assert bc.barcode_shapes(ok, "L1", code)


def _render(shapes, px=12.0, layer=None):
    """Black = lasered. With ``layer``: only the layer's hatch lines."""
    import numpy as np
    from PySide6.QtCore import QLineF, QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

    from lumacut_canvas.export import shape_fill_segments
    from lumacut_canvas.shape_paths import shape_polygons
    union, _ = _union(shapes)
    x0, y0, x1, y1 = union.bounds
    pad = 8.0
    w, h = int((x1 - x0 + 2 * pad) * px), int((y1 - y0 + 2 * pad) * px)
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
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w].copy()
    return a, (ox, oy)


def _scan_modules(img, module_px, row):
    """Read the module string back from one image row (independent of zxing)."""
    line = img[row] < 128
    xs = [i for i, v in enumerate(line) if v]
    start, end = xs[0], xs[-1] + 1
    out = []
    for k in range(round((end - start) / module_px)):
        c = int(start + (k + 0.5) * module_px)
        out.append("1" if line[c] else "0")
    return "".join(out)


@pytest.mark.parametrize("sym,data", list(REFERENCE) + [("code128", "LC-2026/11 ab12345")])
def test_rendered_vectors_read_back(qapp, sym, data):
    spec = bc.BarcodeSpec(sym, data, module_mm=0.5, height_mm=15.0, show_text=False, x=5, y=5)
    code = bc.encode(sym, data)
    img, (_ox, oy) = _render(bc.barcode_shapes(spec, "L1", code), px=12.0)
    row = int((5 + 7.5 - oy) * 12.0)
    assert _scan_modules(img, 0.5 * 12.0, row) == code.modules


def _zxing(img):
    zxingcpp = pytest.importorskip("zxingcpp")
    return [(r.text, r.format.name) for r in zxingcpp.read_barcodes(img)]


@pytest.mark.parametrize("sym,data,expected,fmt", [
    ("code128", "LumaCut Studio 2026", "LumaCut Studio 2026", "Code128"),
    ("code128", "0123456789012", "0123456789012", "Code128"),
    ("ean13", "400638133393", "4006381333931", "EAN13"),
    ("ean8", "9638507", "96385074", "EAN8"),
    ("upca", "03600029145", "036000291452", "UPCA"),
])
def test_vector_shapes_decode(qapp, sym, data, expected, fmt):
    from lumacut_job.barcode_qt import glyph_fn
    spec = bc.BarcodeSpec(sym, data, module_mm=0.33, height_mm=12.0, x=5, y=5)
    img, _ = _render(bc.barcode_shapes(spec, "L1", glyph_fn=glyph_fn("Sans")), px=10.0)
    got = _zxing(img)
    texts = [t for t, _f in got]
    if fmt == "UPCA":   # zxing reports UPC-A as EAN-13 with a leading 0 unless asked otherwise
        assert expected in texts or "0" + expected in texts
    else:
        assert (expected, fmt) in got


def test_hatch_fill_decodes(qapp):
    from lumacut_canvas.model import Layer
    layer = Layer("Barcode", fill_mode="hatch", line_interval_mm=0.1)
    shapes = bc.barcode_shapes(bc.BarcodeSpec("code128", "LC-0815", module_mm=0.3,
                                              height_mm=10.0, show_text=False, x=5, y=5), "L1")
    img, _ = _render(shapes, px=20.0, layer=layer)
    assert ("LC-0815", "Code128") in _zxing(img)


# --- inverted mode ------------------------------------------------------------
def test_inverted_geometry_holes_margin_and_shrink():
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    from lumacut_canvas.shape_paths import shape_polygons
    spec = bc.BarcodeSpec("code128", "LC-0815", module_mm=0.4, height_mm=10.0, show_text=False,
                          quiet_zone=False, invert=True, shrink_mm=0.1, x=5, y=7)
    s = spec.normalized()
    assert s.quiet_zone                                           # forced on when inverted
    code = bc.encode("code128", "LC-0815")
    m = s.margin_mm()
    assert m == pytest.approx(max(bc.INVERT_MARGIN_MM, 5 * 0.4))
    w, h = s.size_mm(code)
    assert h == pytest.approx(10.0 + 2 * m)
    assert w == pytest.approx((sum(code.quiet) + len(code.modules)) * 0.4)
    shapes = bc.barcode_shapes(spec, "L1", code)
    assert len({sh.groups for sh in shapes}) == 1 and shapes[0].groups
    lasered = unary_union([Polygon(r[0], r[1:]) for r in map(shape_polygons, shapes)])
    assert lasered.bounds == pytest.approx((5, 7, 5 + w, 7 + h))
    bars = bc.bar_rects(s, code)
    for x0, y0, x1, y1 in bars:                                  # widened by the correction
        assert y0 == pytest.approx(7 + m) and y1 == pytest.approx(7 + m + 10.0)
    widths = sorted(round(x1 - x0, 6) for x0, _y0, x1, _y1 in bars)
    assert widths[0] == pytest.approx(0.4 + 0.1)
    bar_area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in bars)
    assert lasered.area == pytest.approx(w * h - bar_area, rel=1e-9)
    assert not any(lasered.intersection(box(*r)).area > 1e-9 for r in bars)
    normal = bc.bar_rects(bc.BarcodeSpec("code128", "LC-0815", module_mm=0.4, height_mm=10.0,
                                         show_text=False, shrink_mm=0.1, x=5, y=7), code)
    assert min(x1 - x0 for x0, _y0, x1, _y1 in normal) == pytest.approx(0.4 - 0.1)


def test_inverted_text_digits_are_holes(qapp):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from lumacut_canvas.shape_paths import shape_polygons
    from lumacut_job.barcode_qt import glyph_fn
    spec = bc.BarcodeSpec("ean13", "400638133393", module_mm=0.33, height_mm=12.0, invert=True,
                          x=5, y=5)
    code = bc.encode("ean13", "400638133393")
    with_text = bc.barcode_shapes(spec, "L1", code, glyph_fn=glyph_fn("Sans"))
    without = bc.barcode_shapes(spec, "L1", code)
    area = [unary_union([Polygon(r[0], r[1:]) for r in map(shape_polygons, sh)]).area
            for sh in (with_text, without)]
    assert area[0] < area[1] - 1.0                               # digits cut out of the background


@pytest.mark.parametrize("sym,data,expected,fmt", [
    ("code128", "LumaCut 2026", "LumaCut 2026", "Code128"),
    ("ean13", "400638133393", "4006381333931", "EAN13"),
    ("ean8", "9638507", "96385074", "EAN8"),
])
def test_inverted_decodes_on_light_marking(qapp, sym, data, expected, fmt):
    np = pytest.importorskip("numpy")
    from lumacut_job.barcode_qt import glyph_fn
    spec = bc.BarcodeSpec(sym, data, module_mm=0.33, height_mm=12.0, invert=True, x=5, y=5)
    img, _ = _render(bc.barcode_shapes(spec, "L1", glyph_fn=glyph_fn("Sans")), px=10.0)
    marked = 255 - img                       # laser turns light, untouched material stays dark
    assert (expected, fmt) in _zxing(np.pad(marked, 60, constant_values=255))


def test_inverted_hatch_fill_decodes(qapp):
    np = pytest.importorskip("numpy")
    from lumacut_canvas.model import Layer
    layer = Layer("Barcode", fill_mode="hatch", line_interval_mm=0.1)
    spec = bc.BarcodeSpec("code128", "LC-0815", module_mm=0.3, height_mm=10.0, show_text=False,
                          invert=True, x=5, y=5)
    img, _ = _render(bc.barcode_shapes(spec, "L1"), px=20.0, layer=layer)
    assert ("LC-0815", "Code128") in _zxing(np.pad(255 - img, 60, constant_values=255))


# --- Qt: dialog and main window ----------------------------------------------
def test_dialog_invert(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.barcode_qt import BarcodeDialog
    dlg = BarcodeDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    dlg.quiet.setChecked(False)
    assert not dlg.spec().invert and dlg.quiet.isEnabled()
    dlg.invert.setChecked(True)
    s = dlg.spec()
    assert s.invert and s.quiet_zone and not dlg.quiet.isEnabled()
    assert "invertiert" in dlg.info.text() and "breiter" in dlg.shrink.toolTip()
    dlg.invert.setChecked(False)
    assert dlg.quiet.isEnabled() and not dlg.spec().quiet_zone
    dlg.deleteLater()


def test_dialog(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.barcode_qt import BarcodeDialog
    dlg = BarcodeDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert not dlg.fill_layer() and dlg.windowTitle() == "Barcode einfügen"
    assert dlg.ok_button.isEnabled() and "Code 128" in dlg.info.text()
    dlg.kind.setCurrentIndex(bc.SYMBOLOGIES.index("ean13"))
    assert dlg.data.text() == "400638133393"                 # text did not fit: example digits
    assert dlg.ok_button.isEnabled() and "Prüfziffer 1" in dlg.info.text()
    dlg.data.setText("4006381333932")
    assert not dlg.ok_button.isEnabled() and "richtig wäre 1" in dlg.info.text()
    dlg.data.setText("4006381333931")
    dlg.kind.setCurrentIndex(bc.SYMBOLOGIES.index("code128"))
    assert dlg.data.text() == "4006381333931"                # digits are valid Code 128: kept
    dlg.module.setValue(0.12)
    assert dlg.ok_button.isEnabled() and "Laserfleck" in dlg.info.text()
    dlg.module.setValue(3.0)
    assert not dlg.ok_button.isEnabled() and "Arbeitsfläche" in dlg.info.text()
    dlg.module.setValue(0.33)
    dlg.show_text.setChecked(False)
    assert not dlg.text_mm.isEnabled()
    s = dlg.spec()
    assert (s.symbology, s.data, s.module_mm, s.show_text) == ("code128", "4006381333931", 0.33,
                                                               False)
    dlg.deleteLater()
    dlg2 = BarcodeDialog(active_layer=Layer("Kontur"))
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


def test_window_action_active_layer_undo_and_gcode(win, monkeypatch):
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import QMessageBox

    from lumacut_canvas.commands import SetLayerAttrCommand
    from lumacut_job.planner import optimized_document_gcode
    tools = win.job_tools
    a = tools.barcode_action
    assert a.objectName() == "barcode_action" and a.text() == "Barcode einfügen…"
    assert a.shortcut() == QKeySequence("Alt+C")
    clash = [b.text() for b in win.findChildren(QAction)
             if b is not a and b.shortcut() == a.shortcut()]
    assert clash == []
    assert not any(m.text().replace("&&", "").lower().startswith("&c")
                   for m in win.menuBar().actions())                    # no Alt+C mnemonic
    assert a in win.main_view.design_menu.actions()
    assert a in win.main_view.job_menu.actions()
    doc = win.canvas.document
    layer = doc.active_layer
    win.canvas.undo_stack.push(SetLayerAttrCommand(doc, layer.id, "fill_mode", "hatch"))
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    depth = win.canvas.undo_stack.index()
    ids = tools.barcode(bc.BarcodeSpec("ean13", "400638133393", module_mm=0.33, height_mm=15.0))
    assert len(ids) == len(bc.encode("ean13", "400638133393").bars()) + 13   # bars + digits
    assert len(doc.layers) == n_layers
    assert all(doc.shape(i).layer_id == layer.id for i in ids)
    assert sorted(win.canvas.selection) == sorted(ids)
    assert win.canvas.undo_stack.index() == depth + 1
    union, _ = _union([doc.shape(i) for i in ids])
    spec = bc.BarcodeSpec("ean13", "400638133393", module_mm=0.33, height_mm=15.0)
    w, h = spec.size_mm(bc.encode("ean13", "400638133393"))
    # centred incl. quiet zone (11 left, 7 right modules)
    assert union.bounds[0] == pytest.approx(WORK_WIDTH_MM / 2 - w / 2 + 11 * 0.33 - 7 * 0.33,
                                            abs=0.6)
    assert union.bounds[1] == pytest.approx(WORK_HEIGHT_MM / 2 - h / 2, abs=0.01)
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") > 100
    pi_check(gcode)
    win.canvas.undo_stack.undo()
    assert len(doc.shapes) == n_shapes and not any(doc.has_shape(i) for i in ids)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert tools.barcode(bc.BarcodeSpec("ean13", "4006381333932")) == []
    assert warned and "Prüfziffer" in warned[-1] and len(doc.shapes) == n_shapes
    doc.active_layer.locked = True
    assert tools.barcode(bc.BarcodeSpec("code128", "abc"), fill_layer=False) == []
    assert "gesperrt" in warned[-1] and len(doc.shapes) == n_shapes
    doc.active_layer.locked = False


def test_window_new_fill_layer_one_undo_step(win):
    tools = win.job_tools
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    ids = tools.barcode(bc.BarcodeSpec("code128", "Werkstatt 7"))   # default: new fill layer
    assert len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == "Barcode" and new.fill_mode == "hatch" and new.line_interval_mm == 0.1
    assert new.hatch_outline and doc.active_layer_id == new.id
    win.canvas.undo_stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes


def test_window_inverted_one_undo_step_and_gcode(win):
    from lumacut_job.planner import optimized_document_gcode
    tools = win.job_tools
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    depth = win.canvas.undo_stack.index()
    ids = tools.barcode(bc.BarcodeSpec("code128", "LC-0815", module_mm=0.4, height_mm=10.0,
                                       invert=True))
    assert ids and len(doc.layers) == n_layers + 1
    assert doc.layer(doc.shape(ids[0]).layer_id).fill_mode == "hatch"
    assert win.canvas.undo_stack.index() == depth + 1
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") > 50
    pi_check(gcode)
    win.canvas.undo_stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes
