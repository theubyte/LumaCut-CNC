"""GS1 QR Code (FNC1 mode, mixed segments) and GS1 Digital Link URIs (review round 23)."""

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_job import generated, gs1_link, qr  # noqa: E402
from lumacut_job.qr import QrSpec  # noqa: E402

GS = "\x1d"
GTIN = "09501101530003"


# --- reference reader: data bits straight from the module matrix -------------------------
def _data_codewords(code: qr.QrCode) -> bytes:
    b = qr._Builder(code.version, code.ec)
    b.draw_function_patterns()
    n, f = code.size, qr._MASKS[code.mask]
    bits = []
    right = n - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for vert in range(n):
            y = n - 1 - vert if upward else vert
            for j in range(2):
                x = right - j
                if not b.is_function[y][x]:
                    bits.append(code.modules[y][x] ^ f(x, y))
        right -= 2
    raw = [int("".join("1" if v else "0" for v in bits[i:i + 8]), 2)
           for i in range(0, len(bits) // 8 * 8, 8)]
    ver, ec = code.version, code.ec
    blocks, ecc = qr._NUM_BLOCKS[ec][ver], qr._ECC_PER_BLOCK[ec][ver]
    total = qr.raw_modules(ver) // 8
    n_short, short_len = blocks - total % blocks, total // blocks
    lens = [short_len - ecc + (0 if i < n_short else 1) for i in range(blocks)]
    data = [[] for _ in range(blocks)]
    k = 0
    for i in range(max(lens)):
        for j in range(blocks):
            if i < lens[j]:
                data[j].append(raw[k])
                k += 1
    # Reed-Solomon of every block must match the stored ECC codewords
    ecc_words = raw[sum(lens):]
    div = qr.rs_divisor(ecc)
    for j in range(blocks):
        assert qr.rs_remainder(data[j], div) == [ecc_words[i * blocks + j] for i in range(ecc)]
    return bytes(sum(data, []))


def _decode(code: qr.QrCode):
    """(fnc1_first, [(mode, n)], text with GS for FNC1) – independent of the encoder."""
    bits = "".join(f"{b:08b}" for b in _data_codewords(code))
    cls = qr._version_class(code.version)
    pos, fnc1, segs, out = 0, False, [], []

    def read(n):
        nonlocal pos
        v = int(bits[pos:pos + n], 2)
        pos += n
        return v
    while pos + 4 <= len(bits):
        mode = read(4)
        if mode == 0:
            break
        if mode == 0b0101:
            assert not segs, "FNC1 indicator must come first"
            fnc1 = True
            continue
        name = {1: "N", 2: "A", 4: "B"}[mode]
        count = read(qr._COUNT_BITS[name][cls])
        segs.append((name, count))
        if name == "N":
            s = ""
            while len(s) < count:
                k = min(3, count - len(s))
                s += str(read((4, 7, 10)[k - 1])).zfill(k)
            out.append(s)
        elif name == "A":
            chars = []
            while len(chars) < count:
                if count - len(chars) >= 2:
                    v = read(11)
                    chars += [qr.ALNUM_CHARS[v // 45], qr.ALNUM_CHARS[v % 45]]
                else:
                    chars.append(qr.ALNUM_CHARS[read(6)])
            s = "".join(chars)
            if fnc1:
                s = s.replace("%%", "\0").replace("%", GS).replace("\0", "%")
            out.append(s)
        else:
            out.append(bytes(read(8) for _ in range(count)).decode("latin-1"))
    return fnc1, segs, "".join(out)


def _module_image(code, px=6, quiet=4):
    np = pytest.importorskip("numpy")
    n = code.size + 2 * quiet
    a = np.full((n * px, n * px), 255, np.uint8)
    for y in range(code.size):
        for x in range(code.size):
            if code.modules[y][x]:
                a[(y + quiet) * px:(y + quiet + 1) * px, (x + quiet) * px:(x + quiet + 1) * px] = 0
    return a


# --- GS1 Digital Link ---------------------------------------------------------------------
def test_build_orders_path_qualifiers_and_query_attributes():
    uri = gs1_link.build(f"(17)261231(21)SN-7(10)AB-12(01){GTIN}(3103)000189")
    assert uri == (f"https://id.gs1.org/01/{GTIN}/10/AB-12/21/SN-7?17=261231&3103=000189")
    assert gs1_link.build(f"(01){GTIN}") == f"https://id.gs1.org/01/{GTIN}"
    assert gs1_link.build(f"(01){GTIN}(22)V1(10)L1") == f"https://id.gs1.org/01/{GTIN}/22/V1/10/L1"
    assert gs1_link.build("(00)106141411234567897") == "https://id.gs1.org/00/106141411234567897"
    assert gs1_link.build("(414)9520123456788(254)A1") == "https://id.gs1.org/414/9520123456788/254/A1"
    # values with URI delimiters are percent-encoded, unreserved characters stay
    assert gs1_link.build(f"(01){GTIN}(21)12/3&x?(10)a_b.c-") == \
        f"https://id.gs1.org/01/{GTIN}/10/a_b.c-/21/12%2F3%26x%3F"


def test_build_domain_variants():
    t = f"(01){GTIN}(10)L1"
    assert gs1_link.build(t, "marke.example/") == f"https://marke.example/01/{GTIN}/10/L1"
    assert gs1_link.build(t, "HTTPS://Marke.Example/Produkte/") == \
        f"https://marke.example/Produkte/01/{GTIN}/10/L1"
    assert gs1_link.build(t, " ") == f"https://id.gs1.org/01/{GTIN}/10/L1"
    assert gs1_link.build(t, "http://localhost.lan:8080") == f"http://localhost.lan:8080/01/{GTIN}/10/L1"
    for bad in ("ftp://x.example", "https://x.example?a=1", "https://nohost", "https://a..b",
                "https://bad_host.example", "https://.example"):
        with pytest.raises(ValueError, match="Domain"):
            gs1_link.normalize_domain(bad)


@pytest.mark.parametrize("text,msg", [
    ("(10)AB(17)261231", "Primärschlüssel"),
    (f"(01){GTIN}(00)106141411234567897", "Nur ein Primärschlüssel"),
    (f"(01){GTIN}(10)A(10)B", "doppelt"),
    (f"(01){GTIN}(21)A(235)B", "schließen sich aus"),
    ("(01)09501101530004", "richtig wäre 3"),
    ("01095011", "Klammern"),
])
def test_build_errors(text, msg):
    with pytest.raises(ValueError, match=msg):
        gs1_link.build(text)


def test_parse_round_trip_prefix_extras_and_errors():
    uri = gs1_link.build(f"(01){GTIN}(21)12/3(17)261231(10)AB-12")
    link = gs1_link.parse(uri)
    assert link.domain == gs1_link.DEFAULT_DOMAIN
    assert link.element_string() == f"(01){GTIN}(10)AB-12(21)12/3(17)261231"
    assert gs1_link.build(link.element_string()) == uri
    link = gs1_link.parse(f"https://marke.example/p/01/{GTIN}/10/X%2F1/?17=270101&linkType=gs1:pip#a")
    assert link.domain == "https://marke.example/p"
    assert [(e.ai, e.data) for e in link.elements] == [("01", GTIN), ("10", "X/1"), ("17", "270101")]
    assert link.extra == (("linkType", "gs1:pip"),)
    assert gs1_link.describe(link) == f"GTIN {GTIN}, (10) X/1, (17) 270101"
    for bad, msg in [("www.example.com/01/" + GTIN, "https"),
                     ("https://example.com/produkt/4711", "Primärschlüssel"),
                     (f"https://example.com/01/{GTIN}/21/A/10/B", "Reihenfolge"),
                     (f"https://example.com/01/{GTIN}/17/261231", "nicht erlaubt"),
                     (f"https://example.com/01/{GTIN}?00=106141411234567897", "Pfad"),
                     (f"https://example.com/01/{GTIN} x", "Leerzeichen"),
                     ("https://example.com/01/09501101530004", "Prüfziffer")]:
        with pytest.raises(ValueError, match=msg):
            gs1_link.parse(bad)


def test_resolve_uses_uri_verbatim_or_builds():
    typed = f"https://example.com/01/{GTIN}?linkType=gs1:certificationInfo"
    uri, link = gs1_link.resolve("  " + typed + " ")
    assert uri == typed and link.key.data == GTIN
    uri, _ = gs1_link.resolve(f"(01){GTIN}", "brand.example")
    assert uri == f"https://brand.example/01/{GTIN}"
    with pytest.raises(ValueError, match="Keine GS1-Daten"):
        gs1_link.resolve("   ")


# --- QR segments / GS1 QR -------------------------------------------------------------------
def test_segments_pick_numeric_alnum_and_byte():
    items = list(b"https://id.gs1.org/01/09501101530003")
    segs = qr.segments(items, 1)
    assert [m for m, _ in segs] == ["B", "N"]
    assert "".join(segs[1][1]) == "09501101530003"
    upper = qr.segments(list(b"HTTPS://ID.GS1.ORG/01/09501101530003"), 1)
    assert [m for m, _ in upper] == ["A", "N"]
    assert qr.segments(list(b"12"), 1) == [("N", ["1", "2"])]
    # short digit runs inside text are not worth a segment switch
    assert [m for m, _ in qr.segments(list(b"ab12cd"), 1)] == ["B"]
    # GS1: FNC1 is "%" in alphanumeric mode, a literal "%" doubles, GS in byte mode
    fn = qr.gs1.FNC1
    assert qr.segments([ord("A"), fn, ord("%")], 1, gs1_mode=True) == [("A", ["A", "%", "%", "%"])]
    assert qr.segments([ord("a"), fn], 1, gs1_mode=True) == [("B", [ord("a"), qr.GS])]
    assert qr.segments([], 1) == []


@pytest.mark.parametrize("text,stream", [
    (f"(01){GTIN}(17)261231(10)AB-12", f"01{GTIN}17261231" + "10AB-12"),
    (f"(10)LOT%7(21)SN0815(17)270101", "10LOT%7" + GS + "21SN0815" + GS + "17270101"),
    (f"(01){GTIN}(10)ab12(21)x", f"01{GTIN}10ab12{GS}21x"),
    ("(00)106141411234567897(3103)000189", "00106141411234567897" + "3103000189"),
])
def test_gs1_qr_data_stream(text, stream):
    code = qr.encode_gs1(text, "M")
    fnc1, segs, got = _decode(code)
    assert fnc1 and got == stream
    assert QrSpec(text, mode="gs1").encode() == code
    assert QrSpec(text, mode="gs1").content() == text


def test_gs1_qr_is_more_compact_than_bytes_and_errors():
    text = f"(01){GTIN}(17)261231(10)123456(21)987654321"
    code = qr.encode_gs1(text, "Q")
    _, segs, _ = _decode(code)
    # digits in numeric mode, only the FNC1 separator after (10) is an alphanumeric "%"
    assert [m for m, _ in segs] == ["N", "A", "N"] and segs[1][1] == 1
    bytes_only = qr.encode(text.replace("(", "").replace(")", ""), "Q")
    assert code.version < bytes_only.version
    with pytest.raises(ValueError, match="richtig wäre 3"):
        qr.encode_gs1("(01)09501101530004")
    with pytest.raises(ValueError, match="zu lang"):
        qr.encode_gs1("".join(f"(91){'A' * 90}" for _ in range(40)), "H")
    with pytest.raises(ValueError, match="FNC1"):
        qr.encode_items([65, qr.gs1.FNC1])
    with pytest.raises(ValueError, match="Kein Inhalt"):
        qr.encode_items([])


def test_digital_link_qr_data_and_version():
    text = f"(01){GTIN}(10)AB-12(17)261231"
    code = qr.encode_link(text, "M")
    fnc1, segs, got = _decode(code)
    assert not fnc1 and got == f"https://id.gs1.org/01/{GTIN}/10/AB-12?17=261231"
    assert "N" in {m for m, _ in segs}
    assert code.version <= qr.encode(got, "M").version
    spec = QrSpec(text, mode="link", domain="marke.example")
    assert _decode(spec.encode())[2] == f"https://marke.example/01/{GTIN}/10/AB-12?17=261231"
    assert spec.content() == f"https://marke.example/01/{GTIN}/10/AB-12?17=261231"
    assert qr.content_info(spec).startswith("Adresse: https://marke.example/01/")
    assert "GTIN 09501101530003" in qr.content_info(spec)


def test_large_versions_and_masks_round_trip():
    text = "".join(f"(91){k:04d}ABCDEFGHIJ{k:06d}" for k in range(60))
    for ec in qr.EC_LEVELS:
        code = qr.encode_gs1(text, ec)
        assert code.version >= 10
        stream = "".join(chr(c) if c != qr.gs1.FNC1 else GS for c in qr.gs1_items(text))
        assert _decode(code)[2] == stream
    for mask in range(8):
        assert _decode(qr.encode_gs1(f"(01){GTIN}", "L", mask=mask))[2] == f"01{GTIN}"


def test_text_mode_unchanged_and_spec_normalization():
    assert QrSpec("LumaCut").encode() == qr.encode("LumaCut", "M")
    assert QrSpec("LumaCut").content() == "LumaCut" and qr.content_info(QrSpec("x")) == ""
    s = QrSpec("x", mode="GS1", domain="  ").normalized()
    assert (s.mode, s.domain) == ("gs1", gs1_link.DEFAULT_DOMAIN)
    assert QrSpec("x", mode="unbekannt").normalized().mode == "text"
    # positional arguments of older callers still work
    assert QrSpec("a", "L", 20.0, 2, True, 1.0, 2.0).normalized().mode == "text"


@pytest.mark.parametrize("text", [f"(01){GTIN}(17)261231(10)AB-12", "(10)LOT%7(21)SN0815(17)270101"])
def test_gs1_qr_decodes_with_zxing(text):
    zxingcpp = pytest.importorskip("zxingcpp")
    got = [(r.text, r.symbology_identifier) for r in
           zxingcpp.read_barcodes(_module_image(qr.encode_gs1(text)))]
    assert got == [(text, "]Q3")]


def test_digital_link_decodes_with_zxing():
    zxingcpp = pytest.importorskip("zxingcpp")
    for spec in (QrSpec(f"(01){GTIN}(21)12/3(17)261231", mode="link"),
                 QrSpec(f"https://example.com/p/01/{GTIN}?linkType=gs1:pip", mode="link")):
        got = [(r.text, r.symbology_identifier) for r in
               zxingcpp.read_barcodes(_module_image(spec.encode()))]
        assert got == [(spec.content(), "]Q1")]


# --- generated objects / file -----------------------------------------------------------------
def test_generator_meta_keeps_mode_and_old_meta_is_text(qapp):
    spec = QrSpec(f"(01){GTIN}(10)L1", size_mm=25.0, mode="link", domain="marke.example")
    shapes = generated.tag(qr.qr_shapes(replace(spec, x=10, y=10), "L1"), spec)
    meta = shapes[0].generator
    assert meta["spec"]["mode"] == "link" and meta["spec"]["domain"] == "marke.example"
    assert generated.spec_from_meta(meta) == spec.normalized()
    old = {"kind": "qr", "version": 1, "spec": {"text": "alt", "ec": "M", "size_mm": 20.0,
                                                 "quiet_zone": 4, "invert": False}}
    assert generated.spec_from_meta(old).mode == "text"
    from lumacut_job.generated_qt import build_shapes
    fresh = build_shapes(spec, "L1")
    assert fresh and fresh[0].generator["spec"]["mode"] == "link"


# --- dialog / window ------------------------------------------------------------------------------
def test_dialog_modes_domain_example_and_errors(qapp):
    from lumacut_job.qr_qt import EXAMPLES, QrDialog
    dlg = QrDialog()
    assert dlg.mode.currentData() == "text" and dlg.domain.isHidden() and dlg.content.isHidden()
    dlg.mode.setCurrentIndex(qr.MODES.index("gs1"))
    assert dlg.domain.isHidden() and not dlg.content.isHidden()
    assert "(AI)" in dlg.text.placeholderText()
    dlg.example.click()
    assert dlg.text.text() == EXAMPLES["gs1"] and dlg.ok_button.isEnabled()
    assert dlg.content.text() == "GS1-Daten: " + EXAMPLES["gs1"]
    dlg.text.setText("(01)09501101530004")
    assert not dlg.ok_button.isEnabled() and "richtig wäre 3" in dlg.info.text()
    assert dlg.content.text() == ""
    dlg.mode.setCurrentIndex(qr.MODES.index("link"))
    assert not dlg.domain.isHidden()
    dlg.example.click()
    assert dlg.ok_button.isEnabled() and "https://id.gs1.org/01/" in dlg.content.text()
    dlg.domain.setText("marke.example")
    assert "https://marke.example/01/" in dlg.content.text()
    s = dlg.spec()
    assert (s.mode, s.domain, s.text) == ("link", "marke.example", EXAMPLES["link"])
    dlg.domain.setText("ftp://x")
    assert not dlg.ok_button.isEnabled() and "Domain" in dlg.info.text()
    edit = QrDialog(spec=QrSpec(f"(01){GTIN}", mode="link", domain="brand.example"))
    assert edit.mode.currentData() == "link" and edit.domain.text() == "brand.example"
    assert not edit.domain.isHidden() and edit.ok_button.isEnabled()


@pytest.fixture
def win(qapp, tmp_path):
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


def test_window_insert_gs1_and_link_gcode_and_edit(win):
    from lumacut_job.generated_qt import unit_spec
    from lumacut_job.planner import optimized_document_gcode
    tools, doc = win.job_tools, win.canvas.document
    msgs = []
    tools._msg = msgs.append
    ids = tools.qr_code(QrSpec(f"(01){GTIN}(10)AB-12", size_mm=20.0, mode="gs1"))
    assert ids and msgs[-1].startswith("GS1 QR-Code eingefügt")
    link_ids = tools.qr_code(QrSpec(f"(01){GTIN}(17)261231", size_mm=25.0, mode="link"))
    assert link_ids and msgs[-1].startswith("GS1-Digital-Link-QR-Code eingefügt")
    pi_check(optimized_document_gcode(doc))
    unit = generated.find_unit(doc, link_ids[0])
    spec = unit_spec(unit)
    assert spec.mode == "link" and spec.text == f"(01){GTIN}(17)261231"
    win.canvas.set_selection(link_ids)
    new_ids = tools.edit_generated(replace(spec, text=f"(01){GTIN}(17)270101", domain="b.example"))
    assert new_ids and not any(doc.has_shape(i) for i in link_ids)
    got = generated.spec_from_meta(doc.shape(new_ids[0]).generator)
    assert (got.mode, got.domain) == ("link", "b.example")
    assert got.content() == f"https://b.example/01/{GTIN}?17=270101"
