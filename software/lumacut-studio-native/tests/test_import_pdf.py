"""PDF-Import (Vektorpfade, pypdf + eigene Pfad-Interpretation)."""
from __future__ import annotations

import math

import pytest

pypdf = pytest.importorskip("pypdf")

from _pi_guard import pi_check  # noqa: E402
from lumacut_canvas.model import Document, Layer  # noqa: E402
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402

MM = 72 / 25.4  # pt je mm


def make_pdf(path, pages, size=(100 * MM, 50 * MM), rotate=0, forms=None, user_unit=None):
    """PDF mit je einem Inhaltsstrom pro Seite (bytes) schreiben."""
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject,
                               NameObject, NumberObject)
    w = PdfWriter()
    for content in pages:
        page = w.add_blank_page(*size)
        if rotate:
            page[NameObject("/Rotate")] = NumberObject(rotate)
        if user_unit:
            page[NameObject("/UserUnit")] = FloatObject(user_unit)
        if forms:
            xo = DictionaryObject()
            for name, (body, matrix) in forms.items():
                f = DecodedStreamObject()
                f.set_data(body)
                f[NameObject("/Type")] = NameObject("/XObject")
                f[NameObject("/Subtype")] = NameObject("/Form")
                f[NameObject("/BBox")] = ArrayObject([FloatObject(v) for v in (0, 0, 1000, 1000)])
                if matrix:
                    f[NameObject("/Matrix")] = ArrayObject([FloatObject(v) for v in matrix])
                xo[NameObject(name)] = w._add_object(f)
            res = DictionaryObject({NameObject("/XObject"): xo})
            page[NameObject("/Resources")] = res
        s = DecodedStreamObject()
        s.set_data(content)
        page[NameObject("/Contents")] = w._add_object(s)
    with open(path, "wb") as fh:
        w.write(fh)
    return path


def _bbox(polys):
    xs = [p[0] for pl in polys for p in pl.points]
    ys = [p[1] for pl in polys for p in pl.points]
    return min(xs), min(ys), max(xs), max(ys)


def test_rect_and_line_units_and_yflip(tmp_path):
    from lumacut_import.pdf import load_pdf
    # Rechteck 20×10 mm bei (10 mm, 5 mm) von unten links; Linie oben.
    c = (f"{10 * MM} {5 * MM} {20 * MM} {10 * MM} re S "
         f"{0} {40 * MM} m {30 * MM} {40 * MM} l S").encode()
    vi = load_pdf(make_pdf(tmp_path / "a.pdf", [c]))
    assert len(vi.polylines) == 2
    rect = next(p for p in vi.polylines if p.closed)
    line = next(p for p in vi.polylines if not p.closed)
    xs = [p[0] for p in rect.points]
    ys = [p[1] for p in rect.points]
    # Seite 50 mm hoch: PDF y 5..15 mm → Canvas y 35..45 mm
    assert min(xs) == pytest.approx(10) and max(xs) == pytest.approx(30)
    assert min(ys) == pytest.approx(35) and max(ys) == pytest.approx(45)
    assert line.points[0] == pytest.approx((0, 10)) and line.points[-1] == pytest.approx((30, 10))


def test_bezier_is_flattened_close_to_circle(tmp_path):
    from lumacut_import.pdf import load_pdf
    r, cx, cy, k = 10 * MM, 50 * MM, 25 * MM, 0.5522847498 * 10 * MM
    c = (f"{cx + r} {cy} m "
         f"{cx + r} {cy + k} {cx + k} {cy + r} {cx} {cy + r} c "
         f"{cx - k} {cy + r} {cx - r} {cy + k} {cx - r} {cy} c "
         f"{cx - r} {cy - k} {cx - k} {cy - r} {cx} {cy - r} c "
         f"{cx + k} {cy - r} {cx + r} {cy - k} {cx + r} {cy} c h f").encode()
    vi = load_pdf(make_pdf(tmp_path / "c.pdf", [c]))
    assert len(vi.polylines) == 1 and vi.polylines[0].closed
    pts = vi.polylines[0].points
    assert len(pts) > 40
    for x, y in pts:
        assert math.hypot(x - 50, y - 25) == pytest.approx(10, abs=0.05)


def test_v_y_operators_and_close_variants(tmp_path):
    from lumacut_import.pdf import load_pdf
    c = (f"0 0 m {10 * MM} {10 * MM} {20 * MM} 0 v "
         f"{30 * MM} {10 * MM} {40 * MM} 0 y b").encode()
    vi = load_pdf(make_pdf(tmp_path / "v.pdf", [c]))
    assert len(vi.polylines) == 1 and vi.polylines[0].closed
    assert vi.polylines[0].points[-1][0] == pytest.approx(40)


def test_cm_transform_q_Q_and_clip_path_ignored(tmp_path):
    from lumacut_import.pdf import load_pdf
    # Clip-Rechteck (W n) wird nicht gelasert; cm verschiebt und skaliert ×2.
    c = (f"q 0 0 {100 * MM} {50 * MM} re W n "
         f"2 0 0 2 {10 * MM} {10 * MM} cm 0 0 {5 * MM} {5 * MM} re S Q "
         f"0 0 {1 * MM} {1 * MM} re S").encode()
    vi = load_pdf(make_pdf(tmp_path / "t.pdf", [c]))
    assert len(vi.polylines) == 2
    big, small = sorted(vi.polylines, key=lambda p: -_bbox([p])[2])
    x0, y0, x1, y1 = _bbox([big])
    assert (x0, x1) == pytest.approx((10, 20)) and (y0, y1) == pytest.approx((30, 40))
    x0, y0, x1, y1 = _bbox([small])  # nach Q wieder ohne Transformation
    assert (x0, x1, y0, y1) == pytest.approx((0, 1, 49, 50))


def test_form_xobject_with_matrix(tmp_path):
    from lumacut_import.pdf import load_pdf
    form = (f"0 0 {10 * MM} {10 * MM} re S".encode(), (1, 0, 0, 1, 20 * MM, 0))
    c = f"1 0 0 1 0 {10 * MM} cm /Fm1 Do".encode()
    vi = load_pdf(make_pdf(tmp_path / "f.pdf", [c], forms={"/Fm1": form}))
    assert len(vi.polylines) == 1
    x0, y0, x1, y1 = _bbox(vi.polylines)
    assert (x0, x1) == pytest.approx((20, 30)) and (y0, y1) == pytest.approx((30, 40))


def test_text_and_white_background_are_skipped(tmp_path):
    from lumacut_import.pdf import load_pdf
    c = (f"1 g 0 0 {100 * MM} {50 * MM} re f 0 g "
         f"BT /F1 12 Tf 10 10 Td (Hallo) Tj ET "
         f"{10 * MM} {10 * MM} {5 * MM} {5 * MM} re f").encode()
    vi = load_pdf(make_pdf(tmp_path / "w.pdf", [c]))
    assert len(vi.polylines) == 1
    notes = " ".join(vi.notes())
    assert "Text" in notes and "weiße Fläche" in notes


def test_multi_page_selection_and_errors(tmp_path):
    from lumacut_import.pdf import load_pdf, page_count
    p = make_pdf(tmp_path / "m.pdf", [f"0 0 {10 * MM} {10 * MM} re S".encode(),
                                      f"0 0 {30 * MM} {10 * MM} re S".encode()])
    assert page_count(p) == 2
    assert _bbox(load_pdf(p).polylines)[2] == pytest.approx(10)          # erste Seite
    assert _bbox(load_pdf(p, page=1).polylines)[2] == pytest.approx(30)
    with pytest.raises(ValueError, match="Seite 3"):
        load_pdf(p, page=2)
    empty = make_pdf(tmp_path / "e.pdf", [b"BT (x) Tj ET"])
    with pytest.raises(ValueError, match="keine Vektorpfade"):
        load_pdf(empty)
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"kein pdf")
    with pytest.raises(ValueError):
        load_pdf(bad)


def test_rotate_90_and_user_unit(tmp_path):
    from lumacut_import.pdf import load_pdf
    c = f"0 0 {10 * MM} {5 * MM} re S".encode()   # unten links
    vi = load_pdf(make_pdf(tmp_path / "r.pdf", [c], rotate=90))
    # Seite 100×50 → angezeigt 50×100; unten links → oben links nach Drehung im Uhrzeigersinn
    x0, y0, x1, y1 = _bbox(vi.polylines)
    assert (x0, y0, x1, y1) == pytest.approx((0, 0, 5, 10))
    vi = load_pdf(make_pdf(tmp_path / "u.pdf", [c], user_unit=2.0, size=(50 * MM, 25 * MM)))
    x0, y0, x1, y1 = _bbox(vi.polylines)
    assert (x1 - x0, y1 - y0) == pytest.approx((20, 10))


def test_import_file_places_into_work_area_and_gcode_passes_guard(qapp, tmp_path):
    from lumacut_import import import_file
    from lumacut_job.planner import optimized_document_gcode
    # A2-Seite (420×594 mm) mit Rahmen über die ganze Seite → wird verkleinert
    c = f"{5 * MM} {5 * MM} {410 * MM} {584 * MM} re S {100 * MM} {100 * MM} m {200 * MM} {300 * MM} l S".encode()
    p = make_pdf(tmp_path / "gross.pdf", [c], size=(420 * MM, 594 * MM))
    d = Document()
    res = import_file(p, d.active_layer_id)
    assert res.scale < 1 and len(res.shapes) == 2
    for s in res.shapes:
        d.add_shape(s)
    b = d.selection_bounds([s.id for s in res.shapes])
    assert b.x >= -1e-6 and b.y >= -1e-6
    assert b.right <= WORK_WIDTH_MM + 1e-6 and b.bottom <= WORK_HEIGHT_MM + 1e-6
    assert b.h == pytest.approx(WORK_HEIGHT_MM, abs=0.5)  # proportional auf die Höhe
    assert "Objekt" in res.summary("gross.pdf")
    pi_check(optimized_document_gcode(d))


def test_import_menu_filter_and_drop_accept_pdf(qapp, tmp_path):
    from pathlib import Path

    from lumacut_import.qt import FILTER, ImportTools
    assert "*.pdf" in FILTER
    assert ImportTools._accepted(Path("C:/Users/A/Desktop/Logo.PDF"))


def test_main_window_imports_pdf_one_undo_step(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        p = make_pdf(tmp_path / "zwei.pdf", [f"0 0 {10 * MM} {10 * MM} re S".encode(),
                                             f"0 0 {30 * MM} {10 * MM} re S "
                                             f"{40 * MM} 0 m {50 * MM} {5 * MM} l S".encode()])
        before = len(w.canvas.document.shapes)
        ids = w.import_tools.import_path(p, page=1)
        assert len(ids) == 2 and len(w.canvas.document.shapes) == before + 2
        w.canvas.undo_stack.undo()
        assert len(w.canvas.document.shapes) == before
        assert len(w.import_tools.import_path(p)) == 1  # nicht interaktiv: erste Seite
    finally:
        w.canvas.undo_stack.setClean()
        w.close()


def test_qt_pdf_strokes_as_fill_rings_become_single_contours(qapp, tmp_path):
    """Echtes PDF eines Fremdprogramms (Qt): Striche liegen als schmale Ringe vor."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter, QPen

    from lumacut_import.pdf import load_pdf
    path = str(tmp_path / "qt.pdf")
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setResolution(254)  # 10 Geräte-Pixel je mm
    p = QPainter(w)
    p.setPen(QPen())
    p.drawRect(QRectF(100, 100, 500, 300))     # 50 × 30 mm
    p.drawEllipse(QRectF(700, 100, 200, 200))  # Ø 20 mm
    p.end()
    vi = load_pdf(path)
    assert len(vi.polylines) == 2
    sizes = sorted(round(_bbox([pl])[2] - _bbox([pl])[0]) for pl in vi.polylines)
    assert sizes == [20, 50]
    assert any("doppelte Strichkante" in n for n in vi.notes())
