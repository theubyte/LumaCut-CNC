"""Weitere Importformate (Anforderungen 2026-10-26 §9.2): AI, EPS, xTool .xcs/.xs."""
from __future__ import annotations

import json
import math
import os
import shutil
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pypdf")
pytest.importorskip("svgelements")

from _pi_guard import pi_check  # noqa: E402
from test_import_pdf import MM, make_pdf  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "import"
XCS = FIX / "xtool_sample.xcs"
EPS = FIX / "rechteck.eps"


def _by_kind(shapes):
    out = {}
    for s in shapes:
        out.setdefault(s.kind, []).append(s)
    return out


def _raw(path, qapp):
    from lumacut_import.xtool import load_xtool
    return load_xtool(path, "L1")


# ------------------------------------------------------------------ xTool .xcs
def test_xcs_all_object_types_in_xtool_coordinates(qapp):
    res = _raw(XCS, qapp)
    k = _by_kind(res.shapes)
    rect = k["rect"][0]
    assert rect.geom.as_tuple() == pytest.approx((10, 20, 30, 15)) and rect.geom.rot == 0
    # abgerundetes Rechteck → Polygon mit echten Bögen (Sehnenfehler ≤ 0,02 mm)
    rounded = [s for s in k["polygon"] if s.bounds().w == pytest.approx(20, abs=1e-6)
               and s.bounds().x == pytest.approx(50, abs=1e-6)][0]
    pts = rounded.abs_points()
    corner = (50 + 5, 20 + 5)
    near = [p for p in pts if p[0] < corner[0] and p[1] < corner[1]]
    assert len(near) >= 4
    assert max(abs(math.dist(p, corner) - 5) for p in near) < 0.02
    # gedrehte Ellipse: Drehung um (x, y) → Mitte bei (100 - 10, 10 + 20)
    ell = k["ellipse"][0]
    assert ell.geom.center() == pytest.approx((90, 30)) and ell.geom.rot == pytest.approx(90)
    assert (ell.geom.w, ell.geom.h) == pytest.approx((40, 20))
    # Linie mit angle 90 zeigt nach unten (y wächst)
    line = k["line"][0]
    assert (line.geom.x, line.geom.y, line.geom.w, line.geom.h) == pytest.approx((10, 60, 0, 50), abs=1e-9)
    # Pfad: Versatz + Maßstab, Loch bleibt als zweiter Ring erhalten
    path = [s for s in k["polygon"] if s.rings and s.bounds().x == pytest.approx(60)][0]
    b = path.bounds()
    assert (b.x, b.y, b.w, b.h) == pytest.approx((60, 100, 40, 40))
    assert len(path.ring_ranges()) == 2
    # Text mit Glyphen → Kontur an der Glyphenstelle; ohne Glyphen → Textobjekt
    glyph = [s for s in k["polygon"] if s.bounds().x == pytest.approx(150)][0]
    gb = glyph.bounds()
    assert (gb.x, gb.y, gb.w, gb.h) == pytest.approx((150, 100, 10, 10))
    text = k["text"][0]
    assert text.text == "Hallo" and text.font_family == "Arial" and text.font_bold
    assert text.geom.as_tuple() == pytest.approx((150, 150, 40, 10))
    img = k["image"][0]
    assert img.geom.as_tuple() == pytest.approx((200, 10, 40, 20))
    assert (img.image.px_width, img.image.px_height) == (8, 4)
    pen = k["path"][0].bounds()  # PEN als offener Pfad
    assert (pen.x, pen.y, pen.w, pen.h) == pytest.approx((200, 200, 20, 5))
    notes = " ".join(res.notes())
    assert "QRCODE übersprungen" in notes and "ausgeblendet (RECT)" in notes


def test_xcs_import_file_places_groups_and_reports(qapp):
    from lumacut_import import import_file
    from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM
    res = import_file(XCS, "L1")
    assert len(res.shapes) == 9 and res.scale == pytest.approx(1)
    assert len({s.groups for s in res.shapes}) == 1 and res.shapes[0].groups
    for s in res.shapes:
        b = s.bounds()
        assert -1e-6 <= b.x and b.right <= WORK_WIDTH_MM + 1e-6
        assert -1e-6 <= b.y and b.bottom <= WORK_HEIGHT_MM + 1e-6
    text = res.summary("xtool_sample.xcs")
    assert "9 Objekt(e)" in text and "QRCODE übersprungen" in text
    # Ablegen per Drag & Drop: Mitte auf den Ablagepunkt
    dropped = import_file(XCS, "L1", drop=(180.0, 170.0))
    assert dropped.shapes[0].geom.x != pytest.approx(res.shapes[0].geom.x)


def _xs_from_xcs(dst: Path, externalize=True) -> Path:
    """.xs-Bündel (ZIP, Studio ≥ 1.7) aus dem .xcs-Fixture bauen."""
    import base64
    import hashlib
    data = json.loads(XCS.read_text(encoding="utf-8"))
    displays = data["canvas"][0]["displays"]
    vectors, files = {}, {}
    for d in displays:
        if externalize and d["type"] == "PATH":
            h = hashlib.sha256(d["dPath"].encode()).hexdigest()
            vectors[h] = d.pop("dPath")
            d["vectorRef"] = {"vectorHash": h, "bucketType": "svg", "originalField": "dPath"}
        if d["type"] == "BITMAP":
            raw = base64.b64decode(d.pop("base64").split(",", 1)[1])
            name = f"resources/{hashlib.sha256(raw).hexdigest()}.png"
            files[name] = raw
            d["resourcePath"] = name
    half = len(displays) // 2
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(".format", "v2")
        z.writestr("project.json", json.dumps({"version": "1.7.30"}))
        z.writestr("canvases/c1.json", json.dumps({"id": "c1"}))
        # zwei Teildateien, absichtlich in falscher Reihenfolge geschrieben
        z.writestr("canvases/c1/displays-1.json",
                   json.dumps({"canvasId": "c1", "chunkIndex": 1, "displays": displays[half:]}))
        z.writestr("canvases/c1/displays-0.json",
                   json.dumps({"canvasId": "c1", "chunkIndex": 0, "displays": displays[:half]}))
        if vectors:
            z.writestr("vectors/svg/data-0.json",
                       json.dumps({"bucketType": "svg", "chunkIndex": 0, "entries": vectors}))
        for name, raw in files.items():
            z.writestr(name, raw)
    return dst


def test_xs_bundle_resolves_vector_and_resource_refs(qapp, tmp_path):
    a = _raw(XCS, qapp)
    b = _raw(_xs_from_xcs(tmp_path / "projekt.xs"), qapp)
    assert [s.kind for s in a.shapes] == [s.kind for s in b.shapes]
    for s, t in zip(a.shapes, b.shapes):
        assert s.geom.as_tuple() == pytest.approx(t.geom.as_tuple())
        if s.points:
            assert [c for p in s.points for c in p] == pytest.approx([c for p in t.points for c in p])
    assert b.notes() == a.notes()


def test_xtool_bad_files_give_clear_german_messages(qapp, tmp_path):
    from lumacut_import import import_file
    bad = tmp_path / "kaputt.xcs"
    bad.write_bytes(b"\x00\x01 kein json")
    with pytest.raises(ValueError, match="kein JSON.*SVG"):
        import_file(bad, "L1")
    nocanvas = tmp_path / "leer.xcs"
    nocanvas.write_text('{"version": "1.0"}')
    with pytest.raises(ValueError, match="canvas"):
        import_file(nocanvas, "L1")
    empty = tmp_path / "nichts.xcs"
    empty.write_text('{"canvas": [{"displays": []}]}')
    with pytest.raises(ValueError, match="keine Objekte"):
        import_file(empty, "L1")
    only_unknown = tmp_path / "unbekannt.xcs"
    only_unknown.write_text('{"canvas": [{"displays": [{"type": "QRCODE", "x": 1}]}]}')
    with pytest.raises(ValueError, match="nichts importierbar.*QRCODE"):
        import_file(only_unknown, "L1")
    notzip = tmp_path / "alt.xs"
    notzip.write_text("{}")
    with pytest.raises(ValueError, match="kein ZIP"):
        import_file(notzip, "L1")
    nodisp = tmp_path / "leer.xs"
    with zipfile.ZipFile(nodisp, "w") as z:
        z.writestr(".format", "v2")
    with pytest.raises(ValueError, match="ohne Objekte"):
        import_file(nodisp, "L1")


# ------------------------------------------------------------------ AI / EPS
def test_ai_with_pdf_core_imports_without_ghostscript(qapp, tmp_path, monkeypatch):
    from lumacut_import import import_file, postscript
    monkeypatch.setattr(postscript, "find_ghostscript", lambda: None)
    src = make_pdf(tmp_path / "logo.pdf", [f"{10 * MM} {10 * MM} {30 * MM} {20 * MM} re S".encode()])
    ai = tmp_path / "logo.ai"
    shutil.copy(src, ai)
    res = import_file(ai, "L1")
    assert len(res.shapes) == 1
    b = res.shapes[0].bounds()
    assert (b.w, b.h) == pytest.approx((30, 20), abs=0.01)


def test_postscript_without_ghostscript_has_clear_message(qapp, tmp_path, monkeypatch):
    from lumacut_import import import_file, postscript
    monkeypatch.setattr(postscript, "find_ghostscript", lambda: None)
    with pytest.raises(ValueError, match="EPS-Import braucht Ghostscript.*SVG"):
        import_file(EPS, "L1")
    old_ai = tmp_path / "alt.ai"
    old_ai.write_bytes(EPS.read_bytes())  # Illustrator ≤ 8: reines PostScript
    with pytest.raises(ValueError, match="AI-Import braucht Ghostscript"):
        import_file(old_ai, "L1")
    junk = tmp_path / "x.eps"
    junk.write_text("hallo")
    with pytest.raises(ValueError, match="Keine gültige EPS-Datei"):
        import_file(junk, "L1")


def test_eps_via_ghostscript_command_and_result(qapp, tmp_path, monkeypatch):
    import subprocess

    from lumacut_import import import_file, postscript
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = next(a.split("=", 1)[1] for a in cmd if a.startswith("-sOutputFile="))
        # Ghostscript mit -dEPSCrop: Seite = BoundingBox (72 × 36 pt)
        make_pdf(out, [b"0 0 72 36 re S"], size=(72, 36))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(postscript, "find_ghostscript", lambda: "gswin64c")
    monkeypatch.setattr(postscript.subprocess, "run", fake_run)
    res = import_file(EPS, "L1")
    cmd = calls[0]
    assert cmd[0] == "gswin64c" and "-dSAFER" in cmd and "-dEPSCrop" in cmd
    assert "-sDEVICE=pdfwrite" in cmd and cmd[-1] == os.fspath(EPS)
    b = res.shapes[0].bounds()
    assert (b.w, b.h) == pytest.approx((25.4, 12.7), abs=0.01)

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, b"", b"Error: /undefined in foo")

    monkeypatch.setattr(postscript.subprocess, "run", failing)
    with pytest.raises(ValueError, match="EPS nicht lesbar.*undefined"):
        import_file(EPS, "L1")


def test_find_ghostscript_env_override(tmp_path, monkeypatch):
    from lumacut_import import postscript
    exe = tmp_path / "gswin64c.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("LUMACUT_GHOSTSCRIPT", str(exe))
    assert postscript.find_ghostscript() == str(exe)


@pytest.mark.skipif(not any(shutil.which(n) for n in ("gs", "gswin64c", "gswin32c")),
                    reason="Ghostscript nicht installiert")
def test_eps_real_ghostscript(qapp):
    from lumacut_import import import_file
    res = import_file(EPS, "L1")
    b = res.shapes[0].bounds()
    assert (b.w, b.h) == pytest.approx((25.4, 12.7), abs=0.05)


# ------------------------------------------------------------------ Oberfläche
def test_filter_drop_and_shortcut_cover_new_formats(qapp):
    from lumacut_import.qt import FILTER, ImportTools
    for ext in ("*.svg", "*.dxf", "*.pdf", "*.ai", "*.eps", "*.xcs", "*.xs",
                "*.png", "*.jpg", "*.bmp"):
        assert ext in FILTER
    assert "xTool-Projekt (*.xcs *.xs)" in FILTER
    for name in ("Logo.AI", "Logo.eps", "Projekt.XCS", "Projekt.xs"):
        assert ImportTools._accepted(Path("C:/Users/A/Desktop") / name)


def test_main_window_imports_xcs_one_undo_step_and_gcode_guard(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_job.planner import optimized_document_gcode
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        assert w.import_tools.import_action.shortcut().toString() == "Ctrl+I"
        before = len(w.canvas.document.shapes)
        ids = w.import_tools.import_path(XCS)
        assert len(ids) == 9 and w.import_tools.last_error is None
        assert w.canvas.undo_stack.undoText() == "Importieren"
        pi_check(optimized_document_gcode(w.canvas.document))
        w.canvas.undo_stack.undo()
        assert len(w.canvas.document.shapes) == before
        bad = tmp_path / "kaputt.xs"
        bad.write_text("x")
        assert w.import_tools.import_path(bad) == []
        assert "xTool" in w.import_tools.last_error
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
