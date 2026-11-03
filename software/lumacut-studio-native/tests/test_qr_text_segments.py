"""Plain-text QR codes with optimal mixed segments (numeric / alphanumeric / byte)."""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lumacut_job import qr  # noqa: E402
from lumacut_job.qr import QrSpec  # noqa: E402
from test_gs1_qr import _module_image  # noqa: E402
from test_qr_code import REFERENCE, _bits, _decode, _render  # noqa: E402

DIGITS = "12345678901234567890123456789012345"
UPPER_URL = "HTTPS://LUMACUT.EXAMPLE/P/4711"
SERIAL_URL = "https://x.de/01/09501101530003/10/ABC123/21/1234567890"


def _single_mode_bits(items, ver, mode):
    """Bits of the whole text in one segment of ``mode`` (None = not representable)."""
    chars = []
    for it in items:
        u = qr._units(it, mode, False)
        if u is None:
            return None
        chars.extend(u)
    return len(qr.segment_bits([(mode, chars)], ver))


# --- encoder ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,ec,old,new", [
    (DIGITS, "M", 3, 2), (UPPER_URL, "M", 3, 2), (SERIAL_URL, "M", 4, 3),
    ("0" * 1000, "L", 22, 13), ("4711" * 30 + "ABC", "Q", 9, 5),
    ("WIFI:T:WPA;S:Werkstatt;P:geheim;;", "Q", 4, 3)])
def test_mixed_segments_give_smaller_versions(text, ec, old, new):
    assert qr.encode(text, ec).version == old          # one byte segment
    assert qr.encode_text(text, ec).version == new
    assert QrSpec(text, ec).encode().version == new


@pytest.mark.parametrize("key", list(REFERENCE))
def test_reference_texts_stay_bit_identical(key):
    text, ec = key
    version, mask, bits = REFERENCE[key]
    code = qr.encode_text(text, ec)
    assert (code.version, code.mask, _bits(code)) == (version, mask, bits)
    assert qr.text_segments(text, ec) == [("B", list(text.encode()))]


@pytest.mark.parametrize("text,ec", [
    ("https://lumacut.example/produkt/4711", "M"), ("SN-2026-000123", "H"), ("LumaCut", "L"),
    ("mailto:info@lumacut.example", "Q"), ("a1", "M")])
def test_no_gain_keeps_old_byte_matrix(text, ec):
    """Same version as one byte segment → exactly the old matrix (edited codes stay equal)."""
    old, new = qr.encode(text, ec), qr.encode_text(text, ec)
    assert (new.version, new.mask, new.modules) == (old.version, old.mask, old.modules)
    assert qr.content_info(QrSpec(text, ec)) == ""


def test_non_ascii_text_stays_one_byte_segment():
    text = "Größe " + "1234567890" * 6
    assert qr.text_segments(text) == [("B", list(text.encode("utf-8")))]
    assert qr.encode_text(text).modules == qr.encode(text).modules


def test_capacity_beyond_byte_mode():
    # 7089 digits / 4296 alphanumerics are the ISO maxima at level L, version 40
    assert qr.encode_text("7" * 7089, "L").version == 40
    assert qr.encode_text("A" * 4296, "L").version == 40
    with pytest.raises(ValueError, match="zu lang"):
        qr.encode_text("7" * 7090, "L")
    with pytest.raises(ValueError, match="Kein Text"):
        qr.encode_text("", "M")
    with pytest.raises(ValueError, match="Text zu lang"):
        qr.encode_text("ä" * 1477, "L")          # 2954 bytes non-ASCII: old message
    with pytest.raises(ValueError):
        qr.encode_text("1", "X")


def test_min_version_and_mask_are_honoured():
    code = qr.encode_text(DIGITS, "M", min_version=5, mask=3)
    assert code.version == 5 and code.mask == 3
    assert qr.encode_text(DIGITS, "M", min_version=5).modules == qr.encode(DIGITS, "M", 5).modules


def test_segments_never_longer_than_one_mode_random():
    rnd = random.Random(25)
    alphabet = "0123456789ABCDEFXYZ $%*+-./:abcxyz?&=_"
    for _ in range(300):
        text = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 60)))
        items = list(text.encode())
        for ver in (1, 10, 27):
            best = len(qr.segment_bits(qr.segments(items, ver), ver))
            for mode in "NAB":
                single = _single_mode_bits(items, ver, mode)
                if single is not None:
                    assert best <= single


def test_known_optimal_segmentation():
    segs = qr.segments(list(SERIAL_URL.encode()), 3)
    assert [m for m, _ in segs] == ["B", "N", "A", "N"]
    assert "".join(map(str, segs[1][1])) == "09501101530003"
    assert qr.segment_summary(segs) == ("Segmente: Byte 16, numerisch 14, alphanumerisch 14, "
                                        "numerisch 10")
    info = qr.content_info(QrSpec(SERIAL_URL))
    assert info.startswith("Segmente: Byte 16") and "kleinere Version" in info


# --- decoding --------------------------------------------------------------------------
TEXTS = [DIGITS, UPPER_URL, SERIAL_URL, "0" * 300, "ORDER 4711/2026: 25 STK. +10% $",
         "Charge 20261103 0001 0002 0003 0004 0005 LOS-A"]


@pytest.mark.parametrize("text", TEXTS)
def test_mixed_codes_decode_with_opencv(qapp, text):
    assert qr.text_segments(text) != [("B", list(text.encode()))]   # really mixed
    shapes = qr.qr_shapes(QrSpec(text, "M", size_mm=40.0, quiet_zone=4, x=5, y=5), "L1")
    assert _decode(_render(shapes)) == text


@pytest.mark.parametrize("text", TEXTS)
def test_mixed_codes_decode_with_zxing(text):
    zxingcpp = pytest.importorskip("zxingcpp")
    found = zxingcpp.read_barcodes(_module_image(qr.encode_text(text)))
    assert [r.text for r in found] == [text]


def test_hatch_filled_mixed_code_decodes(qapp):
    from lumacut_canvas.model import Layer
    layer = Layer("QR", fill_mode="hatch", line_interval_mm=0.1)
    shapes = qr.qr_shapes(QrSpec(UPPER_URL, "M", size_mm=20.0, quiet_zone=4, x=5, y=5), "L1")
    assert _decode(_render(shapes, layer, px=20.0)) == UPPER_URL


# --- dialog and generated objects -------------------------------------------------------
def test_dialog_shows_segments_only_when_they_help(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.qr_qt import QrDialog
    dlg = QrDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    dlg.text.setText("https://example.com")
    assert dlg.content.isHidden() and dlg.content.text() == ""
    dlg.text.setText(DIGITS)
    assert not dlg.content.isHidden() and "numerisch 35" in dlg.content.text()
    assert "Version 2" in dlg.info.text() and dlg.ok_button.isEnabled()
    dlg.text.setText("abc")
    assert dlg.content.isHidden()
    dlg.deleteLater()


def test_edit_rebuild_of_old_byte_code_is_unchanged(qapp):
    """A QR code inserted before mixed segments re-builds identically unless it can shrink."""
    from lumacut_job import generated_qt
    spec = QrSpec("https://lumacut.example/produkt/4711", "M", size_mm=30.0)
    old_code = qr.encode(spec.text, spec.ec)
    shapes = generated_qt.build_shapes(spec, "L1")
    ref = qr.qr_shapes(qr.QrSpec(**{**spec.__dict__}), "L1", old_code)
    assert [s.points for s in shapes] != [] and len(shapes) == len(ref)
    def norm(shs):
        return sorted(tuple(round(c, 6) for p in s.points for c in p) for s in shs)
    # same matrix → same polygons up to the placement offset
    dx = min(x for s in shapes for x, _ in s.points) - min(x for s in ref for x, _ in s.points)
    dy = min(y for s in shapes for _, y in s.points) - min(y for s in ref for _, y in s.points)
    moved = [[(x - dx, y - dy) for x, y in s.points] for s in shapes]
    assert sorted(tuple(round(c, 6) for p in m for c in p) for m in moved) == norm(ref)
