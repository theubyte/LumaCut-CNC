"""Plain-text QR codes with non-ASCII text: ECI 26 (UTF-8) designator and Kanji mode."""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lumacut_job import qr  # noqa: E402
from lumacut_job.qr import QrSpec  # noqa: E402
from test_gs1_qr import _module_image  # noqa: E402
from test_qr_code import _bits  # noqa: E402

# Reference matrices from segno 1.6 (boost_error=False, automatic mask), row-wise, dark = 1:
# „Grüße“ as one UTF-8 byte segment with ECI 26, „東京タワー“ as one Kanji segment.
ECI_REFERENCE = {
    ("Grüße", "M"): (1, 2, 0x1fce7f825a0dd7576ebabb7515d82f20ff55fc020017ce7ccdfcfb9e55ab5f19359b800e8e7f18aa0b84b75211ba9f55d6552097affd53a),
    ("東京タワー", "Q"): (1, 0, 0x1fdd7f82e20dd4976eaebb75f5d82720ff55fc02e00d6d5f54135a95b7fa17ce7db5a00e49ff61ae0915975267ba4255d74660a8d5fc168),
}
GERMAN = ["Größe", "Grüße aus Köln – 25 °C, 3 €", "Straße 12, 50667 Köln", "Ä", "ÄÖÜäöüß 1234567890",
          "Café crème", "Grüße 😀", "Øresund", "Привет", "日本語とÄ"]
JAPANESE = ["東京タワー", "こんにちは世界 2026", "東京タワー ABC-123", "カタカナ", "品番 4711 ロット A"]


def _zxing_hex(code):
    """zxing-cpp result as hex with symbology identifier: "]Q2\\000026…" = ECI present."""
    zxingcpp = pytest.importorskip("zxingcpp")
    found = zxingcpp.read_barcodes(_module_image(code), text_mode=zxingcpp.TextMode.HexECI)
    assert len(found) == 1
    return bytes.fromhex(found[0].text)


# --- charset choice --------------------------------------------------------------------
@pytest.mark.parametrize("text,eci,charset", [
    ("https://example.com", True, "ascii"), ("https://example.com", False, "ascii"),
    ("Größe", False, "bytes"), ("Größe", True, "eci"), ("25 °C", True, "eci"),
    ("東京タワー", True, "kanji"), ("東京タワー", False, "bytes"), ("こんにちは 2026", True, "kanji"),
    ("日本語とÄ", True, "eci"),           # Ä is not in Shift JIS
    ("カタカナ\\", True, "eci"),          # backslash is ¥ in Shift JIS
    ("カタカナ~", True, "eci"), ("ｶﾀｶﾅ", True, "eci"),   # half-width kana: single SJIS bytes
    ("×°±", True, "eci")])                # SJIS double-byte, but not Japanese text
def test_text_charset(text, eci, charset):
    assert qr.text_charset(text, eci) == charset


def test_kanji_values_match_iso_examples():
    # ISO/IEC 18004 7.4.6: 点 (SJIS 0x935F) → 0xD9F, 茗 (SJIS 0xE4AA) → 0x1AAA
    assert qr.kanji_value("点") == 0xD9F
    assert qr.kanji_value("茗") == 0x1AAA
    assert qr.kanji_value("A") is None and qr.kanji_value("Ä") is None
    assert qr.kanji_value("ｶ") is None


def test_eci_header_bits():
    assert qr.eci_bits(26) == [0, 1, 1, 1] + [0, 0, 0, 1, 1, 0, 1, 0]
    assert len(qr.eci_bits(200)) == 4 + 16 and len(qr.eci_bits(20000)) == 4 + 24
    with pytest.raises(ValueError):
        qr.eci_bits(1000000)
    ver, bits = qr.mixed_bits(list("Größe".encode()), "M", eci=qr.ECI_UTF8)
    assert bits[:12] == qr.eci_bits(26) and bits[12:16] == [0, 1, 0, 0]
    assert len(bits) == 12 + 4 + 8 + 7 * 8


# --- encoder ----------------------------------------------------------------------------
@pytest.mark.parametrize("key", list(ECI_REFERENCE))
def test_matches_reference_encoder(key):
    text, ec = key
    version, mask, bits = ECI_REFERENCE[key]
    code = qr.encode_text(text, ec, eci=True)
    assert (code.version, code.mask, _bits(code)) == (version, mask, bits)
    assert QrSpec(text, ec, eci=True).encode().modules == code.modules


@pytest.mark.parametrize("text", ["Größe", "Ä", "Café crème", "25 °C – 3 €", "Grüße 😀",
                                  "東京タワー", "カタカナ", "こんにちは世界"])
@pytest.mark.parametrize("ec", qr.EC_LEVELS)
def test_single_segment_codes_match_segno(text, ec):
    segno = pytest.importorskip("segno")
    code = qr.encode_text(text, ec, eci=True)
    segs = qr.text_segments(text, ec, eci=True)
    assert len(segs) == 1                 # segno does not optimise mixed segments
    kw = {"mode": "kanji"} if segs[0][0] == "K" else {"eci": True, "encoding": "utf-8"}
    ref = segno.make_qr(text, error=ec, boost_error=False, version=code.version, mask=code.mask, **kw)
    assert tuple(tuple(bool(v) for v in row) for row in ref.matrix) == code.modules


def test_without_eci_old_codes_stay_bit_identical():
    for text in GERMAN + JAPANESE:
        assert qr.encode_text(text).modules == qr.encode(text).modules
        assert QrSpec(text).encode().modules == qr.encode(text).modules
        assert qr.text_segments(text) == [("B", list(text.encode()))]


def test_ascii_text_ignores_eci():
    for text in ("https://example.com", "12345678901234567890123456789012345", "LumaCut"):
        assert qr.encode_text(text, eci=True).modules == qr.encode_text(text).modules
        assert qr.text_segments(text, eci=True) == qr.text_segments(text)


def test_eci_allows_mixed_segments_with_umlauts():
    text = "Größe " + "1234567890" * 6
    segs = qr.text_segments(text, "M", eci=True)
    assert [m for m, _ in segs] == ["B", "N"]
    assert qr.encode_text(text, eci=True).version < qr.encode(text).version


def test_kanji_mode_is_smaller_than_utf8():
    text = "東京都千代田区丸の内一丁目" * 4
    k = qr.encode_text(text, "M", eci=True)
    assert [m for m, _ in qr.text_segments(text, eci=True)] == ["K"]
    assert k.version < qr.encode(text, "M").version


def test_kanji_segments_random_never_worse_than_single_mode():
    rnd = random.Random(33)
    alphabet = list("東京タワーこんにちは品番ロット") + list("0123456789ABC -abc")
    for _ in range(150):
        text = "東" + "".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 40)))
        items = qr.text_items(text, "kanji")
        for ver in (1, 10, 27):
            segs = qr.segments(items, ver)
            assert sum(len(c) for _, c in segs) == len(items)
            cls = qr._version_class(ver)
            bits = len(qr.segment_bits(segs, ver))
            # never worse than one K segment per kanji run plus one byte segment per ASCII run
            kanji = [it >= qr.KANJI_BASE for it in items]
            k_runs = sum(1 for i, k in enumerate(kanji) if k and (i == 0 or not kanji[i - 1]))
            b_runs = sum(1 for i, k in enumerate(kanji) if not k and (i == 0 or kanji[i - 1]))
            n_k = sum(kanji)
            upper = (k_runs * (4 + qr._COUNT_BITS["K"][cls]) + 13 * n_k
                     + b_runs * (4 + qr._COUNT_BITS["B"][cls]) + 8 * (len(items) - n_k))
            assert bits <= upper


def test_capacity_errors():
    with pytest.raises(ValueError, match="zu lang"):
        qr.encode_text("ä" * 1477, "L", eci=True)
    assert qr.encode_text("ä" * 1470, "L", eci=True).version == 40
    with pytest.raises(ValueError, match="Kein Text"):
        qr.encode_text("", "M", eci=True)
    # Kanji maximum at version 40-L is 1817 characters (ISO table 7)
    assert qr.encode_text("東" * 1817, "L", eci=True).version == 40
    with pytest.raises(ValueError, match="zu lang"):
        qr.encode_text("東" * 1818, "L", eci=True)


# --- decoding --------------------------------------------------------------------------
@pytest.mark.parametrize("text", GERMAN)
def test_eci_codes_decode_with_zxing_and_carry_the_designator(text):
    raw = _zxing_hex(qr.encode_text(text, "M", eci=True))
    assert raw == b"]Q2\\000026" + text.encode("utf-8")
    old = _zxing_hex(qr.encode_text(text, "M"))
    assert old.startswith(b"]Q1")             # old codes: no designator


@pytest.mark.parametrize("text", JAPANESE)
def test_kanji_codes_decode_with_zxing(text):
    zxingcpp = pytest.importorskip("zxingcpp")
    code = qr.encode_text(text, "M", eci=True)
    assert any(m == "K" for m, _ in qr.text_segments(text, "M", eci=True))
    found = zxingcpp.read_barcodes(_module_image(code))
    assert [r.text for r in found] == [text]


def test_hatch_filled_eci_code_decodes_with_zxing(qapp):
    zxingcpp = pytest.importorskip("zxingcpp")
    from lumacut_canvas.model import Layer
    from test_qr_code import _render
    text = "Grüße aus der Werkstatt – 25 °C"
    layer = Layer("QR", fill_mode="hatch", line_interval_mm=0.1)
    shapes = qr.qr_shapes(QrSpec(text, "M", size_mm=25.0, quiet_zone=4, x=5, y=5, eci=True), "L1")
    assert [r.text for r in zxingcpp.read_barcodes(_render(shapes, layer, px=20.0))] == [text]


# --- spec, info line, dialog, generated objects ----------------------------------------
def test_spec_default_and_old_documents():
    assert QrSpec().eci is False                     # old generator dicts without the key
    from lumacut_job import generated
    shapes = qr.qr_shapes(QrSpec("Größe", eci=True, x=5, y=5), "L1")
    meta = generated.make_meta(QrSpec("Größe", eci=True), shapes)
    assert meta["spec"]["eci"] is True
    assert generated.spec_from_meta(meta).eci is True
    old = {**meta, "spec": {k: v for k, v in meta["spec"].items() if k != "eci"}}
    assert generated.spec_from_meta(old).eci is False


def test_content_info_lines():
    assert "ECI 26" in qr.content_info(QrSpec("Größe", eci=True))
    assert "Segmente: Byte 7" in qr.content_info(QrSpec("Größe", eci=True))
    assert "Kanji-Modus" in qr.content_info(QrSpec("東京タワー", eci=True))
    assert "Kanji 5" in qr.content_info(QrSpec("東京タワー", eci=True))
    assert "ohne Zeichensatz-Kennung" in qr.content_info(QrSpec("Größe"))
    assert qr.content_info(QrSpec("https://example.com", eci=True)) == ""
    with pytest.raises(ValueError):                  # GS1 ignores eci, data still checked
        qr.content_info(QrSpec("Größe", mode="gs1", eci=True))


def test_dialog_new_codes_use_eci(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.qr_qt import QrDialog
    dlg = QrDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert dlg.eci.isChecked() and not dlg.eci.isHidden()
    dlg.text.setText("Größe")
    assert dlg.spec().eci is True
    assert not dlg.content.isHidden() and "ECI 26" in dlg.content.text()
    dlg.eci.setChecked(False)
    assert dlg.spec().eci is False and "ohne Zeichensatz-Kennung" in dlg.content.text()
    dlg.text.setText("https://example.com")
    assert dlg.content.isHidden()
    dlg.mode.setCurrentIndex(qr.MODES.index("gs1"))
    assert dlg.eci.isHidden()
    dlg.deleteLater()


def test_dialog_keeps_old_code_without_eci(qapp):
    from lumacut_job.qr_qt import QrDialog
    dlg = QrDialog(spec=QrSpec("Größe"))
    assert not dlg.eci.isChecked()
    assert dlg.spec().encode().modules == qr.encode("Größe").modules
    dlg.deleteLater()


def test_edit_rebuild_of_old_umlaut_code_is_unchanged(qapp):
    from lumacut_job import generated_qt
    spec = QrSpec("Grüße aus Köln", "M", size_mm=30.0)
    rebuilt = generated_qt.build_shapes(spec, "L1")
    ref = qr.qr_shapes(spec, "L1", qr.encode(spec.text, spec.ec))

    def norm(shs):
        x0 = min(x for s in shs for x, _ in s.points)
        y0 = min(y for s in shs for _, y in s.points)
        return sorted(tuple(round(c, 6) for x, y in s.points for c in (x - x0, y - y0)) for s in shs)
    assert norm(rebuilt) == norm(ref)
