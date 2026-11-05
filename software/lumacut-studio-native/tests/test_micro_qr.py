"""Micro QR (ISO/IEC 18004 M1–M4): encode, shapes, dialog, G-code; full QR unchanged."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import generated, micro_qr as mq, qr  # noqa: E402

# Reference matrices from segno 1.6.6 (boost_error=False; M1 with error=None → D).
# Value = (version, mask, bit-matrix as int, row-major, dark=1).
REFERENCE = {
    ("1", "D"): (1, 0, 0x1fd60a5d3ba974e087f300b88d7effb),
    ("12", "D"): (1, 2, 0x1fd60a5d7ba375a08ff70079cd84f58),
    ("123", "D"): (1, 1, 0x1fd6085d7ba77460b7f40098213ecfd),
    ("1234", "D"): (1, 2, 0x1fd60a5d7ba175e09ff40079cd04fcb),
    ("12345", "D"): (1, 2, 0x1fd60b5d4ba175e09ff40079cd46783),
    ("12345", "L"): (2, 0, 0x1fd58205d76ea775e826ff6401fabc0524099be397f),
    ("ABC", "L"): (2, 0, 0x1fd58205d7eea375d826ff6801dabe2e7f0dd5c7a2a),
    ("ABCDEF", "L"): (2, 0, 0x1fd5824dd5aeb175e820ff6800dabe281ea4c2432e8),
    ("Hello", "L"): (3, 3, 0x1fd560bddd15ba597426090ff5c007df2406f3d6474ec3f05cdfd55dd),
    ("0123456789", "M"): (3, 0, 0x1fd56085dd47baa7758a0a4ff2f00eb0df53e07e3f28813cf52016c3f),
}

# Full-QR reference from test_qr_code (Nayuki) – must stay bit-identical after Micro QR.
FULL_QR_REF = {
    ("LumaCut", "M"): (1, 2, 0x1fca7f820a0dd7976eaebb75d5d82f20ff55fc028017c67c181f7bd95bb107d8de50300e8c7f2a3a0b01f75282babea5d7532087b9fd526),
    ("https://example.com", "L"): (2, 5, 0x1fc347f8266a0dd05176ea32bb75895d821a20ff555fc00ce018ea01889cfdf5953cad9132d3cfbb61c181914f9c9eee441db1f61f4008e887f485460bb62574d7f5ba22e1dd2c8360b4f63fd4d49),
}


def _bits(code) -> int:
    return int("".join("1" if v else "0" for row in code.modules for v in row), 2)


@pytest.mark.parametrize("key", list(REFERENCE))
def test_matches_segno_reference(key):
    text, ec = key
    ver, mask, bits = REFERENCE[key]
    code = mq.encode(text, ec)
    assert (code.version, code.mask, code.size) == (ver, mask, mq.VERSION_SIZE[ver])
    assert _bits(code) == bits


@pytest.mark.parametrize("key", list(FULL_QR_REF))
def test_full_qr_still_matches_nayuki(key):
    text, ec = key
    ver, mask, bits = FULL_QR_REF[key]
    code = qr.encode(text, ec)
    assert (code.version, code.mask) == (ver, mask)
    assert _bits(code) == bits
    # QrSpec default path (no micro) identical
    assert qr.QrSpec(text, ec).encode().modules == code.modules


def test_version_choice_and_capacities():
    assert mq.VERSION_SIZE == {1: 11, 2: 13, 3: 15, 4: 17}
    assert mq.EC_FOR_VERSION[1] == ("D",)
    assert mq.EC_FOR_VERSION[4] == ("L", "M", "Q")
    assert mq.choose_mode("12345") == "N"
    assert mq.choose_mode("ABC-12") == "A"
    assert mq.choose_mode("Hello") == "B"
    assert mq.choose_mode("Größe") == "B"
    assert mq.choose_version("1", "D") == (1, "N")
    assert mq.choose_version("12345", "L") == (2, "N")
    assert mq.choose_version("Hello", "L") == (3, "B")
    with pytest.raises(ValueError, match="zu lang"):
        mq.encode("x" * 40, "L")
    with pytest.raises(ValueError, match="Kein Text"):
        mq.encode("", "L")
    with pytest.raises(ValueError, match="Fehlerkorrektur"):
        mq.encode("a", "H")
    # M1 only D; Q only M4
    assert mq.encode("12", "D").version == 1
    assert mq.encode("Hi", "Q").version == 4


def test_forced_mask_and_format():
    a = mq.encode("12345", "L", mask=0)
    b = mq.encode("12345", "L", mask=1)
    assert a.mask == 0 and b.mask == 1 and a.modules != b.modules
    with pytest.raises(ValueError, match="Maske"):
        mq.encode("1", "D", mask=4)


def test_quiet_zone_and_invert_runs():
    code = mq.encode("Hello", "L")
    n = code.size
    dark = sum(map(sum, code.modules))
    runs = code.runs(2)
    assert sum(e - s for _, s, e in runs) == dark
    assert all(2 <= s and e <= n + 2 and 2 <= y < n + 2 for y, s, e in runs)
    inv = code.runs(2, invert=True)
    assert sum(e - s for _, s, e in inv) == (n + 4) ** 2 - dark
    assert any(y == 0 for y, _, _ in inv)


def _union(shapes):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from lumacut_canvas.shape_paths import shape_polygons
    polys = []
    for s in shapes:
        rings = shape_polygons(s)
        polys.append(Polygon(rings[0], rings[1:]))
    return unary_union(polys), polys


def test_shapes_bbox_quiet_invert_and_clamp(qapp):
    spec = qr.QrSpec("SN-042", "L", size_mm=15.0, quiet_zone=2, mode="micro", x=10, y=20)
    code = spec.encode()
    assert isinstance(code, mq.MicroQrCode)
    module = 15.0 / code.size
    shapes = qr.qr_shapes(spec, "L1", code)
    assert all(s.kind == "polygon" and s.layer_id == "L1" for s in shapes)
    assert len({s.groups for s in shapes}) == 1
    union, polys = _union(shapes)
    x0, y0, x1, y1 = union.bounds
    assert x0 == pytest.approx(10 + 2 * module) and y0 == pytest.approx(20 + 2 * module)
    assert x1 - x0 == pytest.approx(15.0) and y1 - y0 == pytest.approx(15.0)
    dark = sum(map(sum, code.modules))
    assert sum(p.area for p in polys) == pytest.approx(dark * module ** 2)
    assert spec.total_mm(code) == pytest.approx(module * (code.size + 4))
    inv = qr.qr_shapes(
        qr.QrSpec(spec.text, "L", 15.0, 2, invert=True, mode="micro", x=10, y=20), "L1", code)
    u2, _ = _union(inv)
    total = module * (code.size + 4)
    assert u2.bounds == pytest.approx((10, 20, 10 + total, 20 + total))
    assert u2.area == pytest.approx(total ** 2 - dark * module ** 2)
    with pytest.raises(ValueError, match="zu klein"):
        # M4 @ 3 mm → module ≈ 0.176 mm < HARD_MIN 0.2 mm
        qr.qr_shapes(qr.QrSpec("abcdefghij", "L", size_mm=3.0, mode="micro"), "L1")
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        qr.qr_shapes(qr.QrSpec("Hi", "L", size_mm=40.0, mode="micro",
                               x=WORK_WIDTH_MM - 20), "L1")


def test_spec_normalized_and_metadata_roundtrip():
    s = qr.QrSpec("LOT-7", "q", size_mm=2.0, quiet_zone=99, mode="micro").normalized()
    assert s.mode == "micro" and s.ec == "Q"
    assert s.size_mm == mq.SIZE_RANGE[0]
    assert s.quiet_zone == mq.QUIET_RANGE[1]
    assert s.eci is False
    shapes = qr.qr_shapes(qr.QrSpec("LOT-7", "L", 12.0, 2, mode="micro", x=5, y=5), "L1")
    meta = generated.make_meta(qr.QrSpec("LOT-7", "L", 12.0, 2, mode="micro"), shapes)
    assert meta["kind"] == "qr" and meta["spec"]["mode"] == "micro"
    back = generated.spec_from_meta(meta)
    assert back.mode == "micro" and back.text == "LOT-7" and back.ec == "L"
    assert back.quiet_zone == 2
    # Old full-QR meta without mode key still loads as text
    old = {"kind": "qr", "version": generated.VERSION,
           "spec": {"text": "Hi", "ec": "M", "size_mm": 20.0, "quiet_zone": 4,
                    "invert": False},
           "box": [20.0, 20.0]}
    assert generated.spec_from_meta(old).mode == "text"


def test_content_info_and_describe():
    s = qr.QrSpec("12345", "L", mode="micro")
    assert "Micro QR" in qr.content_info(s)
    assert "numerisch" in qr.content_info(s)
    code = s.encode()
    assert "Version M2" in qr.describe(code, 15.0)
    assert "Byte (UTF-8)" in qr.content_info(qr.QrSpec("Größe", "L", mode="micro"))


def test_dialog_micro_roundtrip(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.qr_qt import QrDialog

    dlg = QrDialog(active_layer=Layer("Kontur"))
    assert "micro" in qr.MODES
    idx = dlg.mode.findData("micro")
    assert idx >= 0
    dlg.mode.setCurrentIndex(idx)
    assert dlg.mode.currentData() == "micro"
    assert dlg.quiet.value() == mq.DEFAULT_QUIET
    assert dlg.eci.isHidden()
    assert set(dlg.ec.itemData(i) for i in range(dlg.ec.count())) == set(mq.EC_LEVELS)
    dlg.text.setText("SN-042")
    assert dlg.ok_button.isEnabled()
    assert "Version M" in dlg.info.text()
    assert "Micro QR" in dlg.content.text()
    s = dlg.spec()
    assert s.mode == "micro" and s.quiet_zone == 2
    # Edit round-trip: reopen with micro spec
    dlg.deleteLater()
    dlg2 = QrDialog(spec=qr.QrSpec("SN-042", "M", size_mm=15.0, quiet_zone=2, mode="micro"),
                    active_layer=Layer("Kontur"))
    assert dlg2.mode.currentData() == "micro"
    assert dlg2.ec.currentData() == "M"
    assert dlg2.quiet.value() == 2
    assert "Version M" in dlg2.info.text()
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


def test_insert_micro_fill_layer_undo_gcode_estimate(win):
    from lumacut_job.estimate import estimate_gcode
    from lumacut_job.planner import optimized_document_gcode

    tools = win.job_tools
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    depth = win.canvas.undo_stack.index()
    ids = tools.qr_code(qr.QrSpec("SN-042", "L", size_mm=15.0, quiet_zone=2, mode="micro"))
    assert ids and len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == mq.FILL_LAYER_NAME and new.fill_mode == "hatch"
    assert win.canvas.undo_stack.index() == depth + 1
    meta = doc.shape(ids[0]).generator
    assert meta["spec"]["mode"] == "micro"
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") > 20
    pi_check(gcode)
    est = estimate_gcode(gcode)
    assert est.cut_time_s > 0 and est.cut_length_mm > 0 and est.moves > 0
    win.canvas.undo_stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes


def test_old_full_qr_gcode_byte_identical(qapp):
    """Classic full-QR document G-code must stay byte-identical (no Micro path)."""
    from lumacut_canvas.model import Document, Layer
    from lumacut_job.planner import optimized_document_gcode

    doc = Document()
    layer = Layer("QR-Code", fill_mode="hatch", line_interval_mm=0.1)
    doc.add_layer(layer)
    doc.active_layer_id = layer.id
    shapes = generated.tag(
        qr.qr_shapes(qr.QrSpec("LumaCut", "M", size_mm=20.0, quiet_zone=4, x=50, y=50),
                     layer.id),
        qr.QrSpec("LumaCut", "M", size_mm=20.0, quiet_zone=4))
    for sh in shapes:
        doc.add_shape(sh)
    gcode = optimized_document_gcode(doc)
    digest = hashlib.sha256(gcode.encode()).hexdigest()
    assert digest == "d12dc9257767fd5a61135257c1d68fb3e7a030b907e4df95fc375df1966932b4"
    code = qr.encode("LumaCut", "M")
    assert _bits(code) == FULL_QR_REF[("LumaCut", "M")][2]
    assert qr.QrSpec("LumaCut", "M").encode().modules == code.modules
    assert hashlib.sha256(optimized_document_gcode(doc).encode()).hexdigest() == digest
