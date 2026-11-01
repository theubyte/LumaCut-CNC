"""QR-Code-Generator: Kodierung (gegen Referenz), Ruhezone, Größen, Canvas, G-Code, UI."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import qr  # noqa: E402

# Referenzmatrizen aus Project Nayukis qrcodegen 1.8 (Byte-Segment, boostecl=False,
# automatische Maske), zeilenweise als Bits, dunkel = 1.
REFERENCE = {
    ("LumaCut", "M"): (1, 2, 0x1fca7f820a0dd7976eaebb75d5d82f20ff55fc028017c67c181f7bd95bb107d8de50300e8c7f2a3a0b01f75282babea5d7532087b9fd526),
    ("https://example.com", "L"): (2, 5, 0x1fc347f8266a0dd05176ea32bb75895d821a20ff555fc00ce018ea01889cfdf5953cad9132d3cfbb61c181914f9c9eee441db1f61f4008e887f485460bb62574d7f5ba22e1dd2c8360b4f63fd4d49),
    ("Hallo", "H"): (1, 6, 0x1fc57f82520dd5d76eb4bb7455d823a0ff55fc0020036e0c358da3b069e31368cd6ba00c05ff4a120889f7575bba8685d14fe08cfffcbc0),
}


def _bits(code: qr.QrCode) -> int:
    return int("".join("1" if v else "0" for row in code.modules for v in row), 2)


@pytest.mark.parametrize("key", list(REFERENCE))
def test_matches_reference_encoder(key):
    text, ec = key
    version, mask, bits = REFERENCE[key]
    code = qr.encode(text, ec)
    assert (code.version, code.mask, code.size) == (version, mask, 17 + 4 * version)
    assert _bits(code) == bits


def test_byte_capacities_match_iso_table():
    # ISO/IEC 18004 Tabelle 7, Byte-Modus
    expected = {(1, "L"): 17, (1, "M"): 14, (1, "Q"): 11, (1, "H"): 7, (2, "M"): 26,
                (10, "M"): 213, (40, "L"): 2953, (40, "M"): 2331, (40, "Q"): 1663,
                (40, "H"): 1273}
    for (v, ec), n in expected.items():
        assert qr.capacity(v, ec) == n
    assert qr.choose_version(14, "M") == 1 and qr.choose_version(15, "M") == 2
    assert qr.encode("x" * 2953, "L").version == 40
    with pytest.raises(ValueError, match="zu lang"):
        qr.encode("x" * 2954, "L")
    with pytest.raises(ValueError, match="Kein Text"):
        qr.encode("", "M")
    with pytest.raises(ValueError, match="Fehlerkorrektur"):
        qr.encode("a", "X")


def _format_word(code: qr.QrCode, second: bool = False) -> int:
    n, m = code.size, code.modules
    if not second:
        cells = [(8, i) for i in (0, 1, 2, 3, 4, 5, 7)] + [(8, 8), (7, 8)] + \
                [(14 - i, 8) for i in range(9, 15)]
    else:
        cells = [(n - 1 - i, 8) for i in range(8)] + [(8, n - 15 + i) for i in range(8, 15)]
    return sum(int(m[y][x]) << i for i, (x, y) in enumerate(cells))


@pytest.mark.parametrize("ec", qr.EC_LEVELS)
def test_format_info_ec_level_and_masks(ec):
    seen = set()
    for mask in range(8):
        code = qr.encode("LumaCut Studio", ec, mask=mask)
        word = _format_word(code) ^ 0x5412
        assert _format_word(code, second=True) == _format_word(code)
        assert word >> 13 == qr._FORMAT_BITS[ec] and (word >> 10) & 7 == mask
        assert code.modules[code.size - 8][8]  # dunkles Modul
        seen.add(_bits(code))
    assert len(seen) == 8
    auto = qr.encode("LumaCut Studio", ec)
    pens = []
    for mask in range(8):
        b = qr._Builder(auto.version, ec)
        b.modules = [list(r) for r in qr.encode("LumaCut Studio", ec, mask=mask).modules]
        pens.append(b.penalty())
    assert pens[auto.mask] == min(pens)


def test_higher_ec_needs_more_modules_and_utf8():
    sizes = [qr.encode("https://lumacut.example/produkt/4711", ec).size for ec in qr.EC_LEVELS]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]
    assert qr.encode("Grüße €", "M").version == 1   # 10 Bytes UTF-8
    v7 = qr.encode("v" * 110, "M")
    assert v7.version == 7
    n = v7.size  # Versionsinformation (18 Bit, BCH) in beiden Blöcken: 0x07C94 für Version 7
    word_a = sum(int(v7.modules[i // 3][n - 11 + i % 3]) << i for i in range(18))
    word_b = sum(int(v7.modules[n - 11 + i % 3][i // 3]) << i for i in range(18))
    assert word_a == word_b == 0x07C94


def test_runs_and_quiet_zone():
    code = qr.encode("Hallo", "M")
    n = code.size
    dark = sum(map(sum, code.modules))
    runs = qr.code_runs = code.runs(4)
    assert sum(e - s for _, s, e in runs) == dark
    assert all(4 <= s and e <= n + 4 and 4 <= y < n + 4 for y, s, e in runs)
    inv = code.runs(4, invert=True)
    assert sum(e - s for _, s, e in inv) == (n + 8) ** 2 - dark
    assert any(y == 0 for y, _, _ in inv)  # Ruhezone mitgraviert


def _union(shapes):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from lumacut_canvas.shape_paths import shape_polygons
    polys = []
    for s in shapes:
        rings = shape_polygons(s)
        polys.append(Polygon(rings[0], rings[1:]))
    return unary_union(polys), polys


def test_shapes_geometry_quiet_zone_and_area(qapp):
    spec = qr.QrSpec("https://example.com", "L", size_mm=25.0, quiet_zone=4, x=10, y=20)
    code = qr.encode(spec.text, spec.ec)
    module = 25.0 / code.size
    shapes = qr.qr_shapes(spec, "L1", code)
    assert all(s.kind == "polygon" and s.layer_id == "L1" for s in shapes)
    assert len({s.groups for s in shapes}) == 1 and len(shapes[0].groups) == 1
    union, polys = _union(shapes)
    x0, y0, x1, y1 = union.bounds
    assert x0 == pytest.approx(10 + 4 * module) and y0 == pytest.approx(20 + 4 * module)
    assert x1 - x0 == pytest.approx(25.0) and y1 - y0 == pytest.approx(25.0)
    dark = sum(map(sum, code.modules))
    assert sum(p.area for p in polys) == pytest.approx(dark * module ** 2)  # keine Überlappung
    assert union.area == pytest.approx(dark * module ** 2)
    assert spec.total_mm(code) == pytest.approx(module * (code.size + 8))
    # invertiert: Ruhezone wird mitgraviert, Fläche = Gesamtquadrat − dunkle Module
    inv = qr.qr_shapes(qr.QrSpec(spec.text, "L", 25.0, 4, invert=True, x=10, y=20), "L1", code)
    u2, _ = _union(inv)
    total = module * (code.size + 8)
    assert u2.bounds == pytest.approx((10, 20, 10 + total, 20 + total))
    assert u2.area == pytest.approx(total ** 2 - dark * module ** 2)


def test_shape_errors():
    with pytest.raises(ValueError, match="zu klein"):
        qr.qr_shapes(qr.QrSpec("x" * 1000, "H", size_mm=5.0), "L1")
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        qr.qr_shapes(qr.QrSpec("abc", "M", size_mm=40.0, x=WORK_WIDTH_MM - 30), "L1")
    s = qr.QrSpec("a", "q", size_mm=1000, quiet_zone=99).normalized()
    assert (s.ec, s.size_mm, s.quiet_zone) == ("Q", qr.SIZE_RANGE[1], qr.QUIET_RANGE[1])


def _render(shapes, layer=None, px=10.0, size=None):
    """Schwarz = gelasert. Mit ``layer``: nur die Schraffurlinien der Ebene."""
    import numpy as np
    from PySide6.QtCore import QLineF, QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

    from lumacut_canvas.export import shape_fill_segments
    from lumacut_canvas.shape_paths import shape_polygons
    union, _ = _union(shapes)
    x0, y0, x1, y1 = union.bounds
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
    a = np.frombuffer(img.constBits(), np.uint8).reshape(w, img.bytesPerLine())[:, :w].copy()
    return a


def _decode(img):
    cv2 = pytest.importorskip("cv2")
    text, _pts, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return text


@pytest.mark.parametrize("text,ec", [("https://lumacut.example/äöü", "M"),
                                     ("WIFI:T:WPA;S:Werkstatt;P:geheim;;", "Q"),
                                     ("Seriennummer 0815 " * 6, "L"), ("Hallo", "H")])
def test_vector_shapes_decode(qapp, text, ec):
    shapes = qr.qr_shapes(qr.QrSpec(text, ec, size_mm=40.0, quiet_zone=4, x=5, y=5), "L1")
    assert _decode(_render(shapes)) == text


def test_inverted_decodes_on_light_marking(qapp):
    shapes = qr.qr_shapes(qr.QrSpec("Eloxal", "M", size_mm=30.0, quiet_zone=4, invert=True,
                                    x=5, y=5), "L1")
    import numpy as np
    img = 255 - _render(shapes, px=6.0)  # Laser macht hell; Rest (dunkle Module, Umgebung) bleibt dunkel
    assert _decode(np.pad(img, 60, constant_values=255)) == "Eloxal"


def test_hatch_fill_decodes(qapp):
    from lumacut_canvas.model import Layer
    layer = Layer("QR", fill_mode="hatch", line_interval_mm=0.1)
    shapes = qr.qr_shapes(qr.QrSpec("LumaCut", "M", size_mm=20.0, quiet_zone=4, x=5, y=5), "L1")
    assert _decode(_render(shapes, layer, px=20.0)) == "LumaCut"


# --- Qt: Dialog und Hauptfenster ---------------------------------------------
def test_dialog(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.qr_qt import QrDialog
    dlg = QrDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert not dlg.fill_layer()
    dlg.text.setText("https://example.com")
    assert dlg.ok_button.isEnabled() and "Version 2" in dlg.info.text()
    dlg.ec.setCurrentIndex(qr.EC_LEVELS.index("H"))
    assert dlg.spec().ec == "H" and "Version 3" in dlg.info.text()
    dlg.text.setText("")
    assert not dlg.ok_button.isEnabled() and "Kein Text" in dlg.info.text()
    dlg.text.setText("x" * 1200)
    dlg.size_mm.setValue(10.0)
    assert not dlg.ok_button.isEnabled() and "zu klein" in dlg.info.text()
    dlg.text.setText("abc")
    dlg.size_mm.setValue(330.0)
    assert not dlg.ok_button.isEnabled() and "Arbeitsfläche" in dlg.info.text()
    dlg.deleteLater()
    dlg2 = QrDialog(active_layer=Layer("Kontur"))
    assert dlg2.fill_layer()  # aktive Ebene füllt nicht → eigene Füll-Ebene vorgeschlagen
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
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QMessageBox

    from lumacut_canvas.commands import SetLayerAttrCommand
    from lumacut_job.planner import optimized_document_gcode
    tools = win.job_tools
    assert tools.qr_action.objectName() == "qr_code_action"
    assert tools.qr_action.shortcut() == QKeySequence("Alt+Q")
    assert tools.qr_action in win.main_view.design_menu.actions()
    assert tools.qr_action in win.main_view.job_menu.actions()
    doc = win.canvas.document
    layer = doc.active_layer
    win.canvas.undo_stack.push(SetLayerAttrCommand(doc, layer.id, "fill_mode", "hatch"))
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    depth = win.canvas.undo_stack.index()
    ids = tools.qr_code(qr.QrSpec("LumaCut", "M", size_mm=20.0))
    assert ids and len(doc.layers) == n_layers
    assert all(doc.shape(i).layer_id == layer.id for i in ids)
    assert sorted(win.canvas.selection) == sorted(ids)
    assert win.canvas.undo_stack.index() == depth + 1  # ein Undo-Schritt
    # mittig auf der Arbeitsfläche
    union, _ = _union([doc.shape(i) for i in ids])
    cx, cy = (union.bounds[0] + union.bounds[2]) / 2, (union.bounds[1] + union.bounds[3]) / 2
    assert cx == pytest.approx(WORK_WIDTH_MM / 2, abs=0.01)
    assert cy == pytest.approx(WORK_HEIGHT_MM / 2, abs=0.01)
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") > 100
    pi_check(gcode)
    win.canvas.undo_stack.undo()
    assert len(doc.shapes) == n_shapes and not any(doc.has_shape(i) for i in ids)
    # Fehler: Warnung, nichts verändert
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert tools.qr_code(qr.QrSpec("x" * 2000, "H", size_mm=20.0)) == []
    assert warned and len(doc.shapes) == n_shapes


def test_window_new_fill_layer_one_undo_step(win):
    tools = win.job_tools
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    ids = tools.qr_code(qr.QrSpec("Werkstatt", "Q", size_mm=30.0, invert=True))  # Standard: neue Ebene
    assert len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == "QR-Code" and new.fill_mode == "hatch" and new.line_interval_mm == 0.1
    assert doc.active_layer_id == new.id
    win.canvas.undo_stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes
